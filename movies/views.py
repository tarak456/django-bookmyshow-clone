"""
movies/views.py
===============
All HTTP views for the BookMySeat platform, covering all 6 internship tasks.

View inventory
--------------
movie_list          — Task 5: filtered/paginated movie catalogue
theater_list        — movie detail + trailer + shows
book_seats          — Task 2: seat map (GET)
reserve_seats       — Task 2: atomic 2-min seat lock (POST)
confirm_booking     — Task 2/3: review page with countdown
create_payment      — Task 3: create Razorpay order (AJAX POST)
payment_callback    — Task 3: verify signature, finalise booking
payment_webhook     — Task 3: Razorpay server-to-server event
payment_success     — Task 3/6: success page + email dispatch
payment_failed      — Task 3: failure page
release_seats       — Task 2: immediate release (JS beacon)
analytics_dashboard — Task 4: admin-only dashboard
analytics_api       — Task 4: AJAX data endpoint
"""

import json
import logging
import uuid
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import analytics as _analytics
from .email_service import send_booking_confirmation
from .models import (
    Booking, Genre, Language, Movie, Payment,
    Seat, SeatReservation, Theater,
    RESERVATION_TIMEOUT_MINUTES,
)
from .razorpay_client import RazorpayError, razorpay_client

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _seat_price_paise():
    from django.conf import settings
    return getattr(settings, 'PRICE_PER_SEAT_PAISE', 15000)


def _annotate_seats(seats, theater, user):
    """
    Attach .reserved_by_other and .reserved_by_me to each Seat object.

    Why this helper?
    A bug was found where the reserve_seats error path rendered the seat
    map without annotations, making reserved seats appear green.  Now
    every render path calls this helper — no way to forget it.
    """
    now = timezone.now()
    reserved_by_others = set(
        SeatReservation.objects
        .filter(theater=theater, expires_at__gt=now)
        .exclude(user=user)
        .values_list('seat_id', flat=True)
    )
    reserved_by_me = set(
        SeatReservation.objects
        .filter(theater=theater, user=user, expires_at__gt=now)
        .values_list('seat_id', flat=True)
    )
    for seat in seats:
        seat.reserved_by_other = seat.id in reserved_by_others
        seat.reserved_by_me    = seat.id in reserved_by_me
    return seats


def _seat_map_response(request, theater, error=None):
    """Single render path for the seat map — always fully annotated."""
    seats = _annotate_seats(
        list(Seat.objects.filter(theater=theater)),
        theater, request.user,
    )
    return render(request, 'movies/seat_selection.html', {
        'theaters': theater, 'seats': seats, 'error': error,
    })


def _finalize_booking(payment: Payment) -> bool:
    """
    Idempotent atomic booking finalisation.

    Steps
    -----
    1. select_for_update() serialises concurrent calls (callback + webhook).
    2. Early-return if already paid (idempotency).
    3. Lock seats, create Booking rows, mark is_booked=True.
    4. Delete SeatReservation rows (now permanent).
    5. Mark Payment.status = PAID.

    Called from: payment_callback (browser) + payment_webhook (Razorpay).
    """
    with transaction.atomic():
        try:
            locked = Payment.objects.select_for_update().get(pk=payment.pk)
        except OperationalError:
            locked = payment   # SQLite fallback

        if locked.status == Payment.Status.PAID:
            return True        # already processed

        seats = list(Seat.objects.select_for_update().filter(id__in=locked.seat_ids))

        for seat in seats:
            if seat.is_booked:
                locked.status = Payment.Status.FAILED
                locked.failure_reason = f'Seat {seat.seat_number} already booked.'
                locked.save(update_fields=['status', 'failure_reason', 'updated_at'])
                return False
            try:
                Booking.objects.create(
                    user=locked.user, seat=seat,
                    movie=locked.theater.movie, theater=locked.theater,
                )
                seat.is_booked = True
                seat.save(update_fields=['is_booked'])
            except IntegrityError:
                locked.status = Payment.Status.FAILED
                locked.failure_reason = 'Concurrent booking conflict.'
                locked.save(update_fields=['status', 'failure_reason', 'updated_at'])
                return False

        SeatReservation.objects.filter(user=locked.user, theater=locked.theater).delete()
        locked.status = Payment.Status.PAID
        locked.save(update_fields=['status', 'updated_at'])
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Task 5 — Movie list with advanced filtering
# ─────────────────────────────────────────────────────────────────────────────

def movie_list(request):
    """
    Server-side filtering by genre(s), language(s), and text search.
    Pagination: 12 cards per page.

    Performance
    -----------
    - filter() uses the M2M junction table with indexed FK columns — no full scans.
    - prefetch_related loads genres/languages in 2 extra queries total
      (not N+1 per movie).
    - annotate(booking_count) runs a single GROUP BY sub-query for sorting.
    - Genre/Language counts use Count() at DB level — no Python loops.

    Trade-offs
    ----------
    - Multiple genre filters use OR (movie has at least one of them),
      implemented via __in lookup on the junction table.
    - Counts in the sidebar reflect the FILTERED set so users see "0"
      for incompatible combinations.
    """
    # ── Fetch filter options with counts ──────────────────────────────────
    all_genres    = Genre.objects.annotate(count=Count('movies')).order_by('name')
    all_languages = Language.objects.annotate(count=Count('movies')).order_by('name')

    # ── Parse filter parameters ───────────────────────────────────────────
    selected_genres    = request.GET.getlist('genre')    # list of slugs
    selected_languages = request.GET.getlist('language') # list of codes
    search_query       = request.GET.get('search', '').strip()
    sort_by            = request.GET.get('sort', '-created_at')

    # ── Build queryset — DB-level filtering ───────────────────────────────
    qs = Movie.objects.prefetch_related('genres', 'languages')

    if search_query:
        qs = qs.filter(name__icontains=search_query)

    if selected_genres:
        # __in generates: WHERE genre.slug IN (...) on the junction table
        qs = qs.filter(genres__slug__in=selected_genres).distinct()

    if selected_languages:
        qs = qs.filter(languages__code__in=selected_languages).distinct()

    # Allowed sort options (whitelist prevents ORDER BY injection)
    _allowed_sorts = {
        '-created_at': '-created_at',
        'name':        'name',
        '-rating':     '-rating',
        '-bookings':   '-booking_count',
    }
    if sort_by == '-bookings':
        qs = qs.annotate(booking_count=Count('booking')).order_by('-booking_count')
    else:
        qs = qs.order_by(_allowed_sorts.get(sort_by, '-created_at'))

    # ── Pagination ────────────────────────────────────────────────────────
    paginator = Paginator(qs, 12)   # 12 cards per page
    page_obj  = paginator.get_page(request.GET.get('page'))

    return render(request, 'movies/movie_list.html', {
        'page_obj':          page_obj,
        'movies':            page_obj.object_list,
        'all_genres':        all_genres,
        'all_languages':     all_languages,
        'selected_genres':   selected_genres,
        'selected_languages': selected_languages,
        'search_query':      search_query,
        'sort_by':           sort_by,
        'total_count':       paginator.count,
    })


def theater_list(request, movie_id):
    movie   = get_object_or_404(Movie.objects.prefetch_related('genres', 'languages'), id=movie_id)
    theaters = Theater.objects.filter(movie=movie).select_related('movie')
    return render(request, 'movies/theater_list.html', {
        'movie': movie, 'theaters': theaters,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — Seat reservation
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    return _seat_map_response(request, theater)


@login_required(login_url='/login/')
def reserve_seats(request, theater_id):
    """
    Atomically reserve selected seats for RESERVATION_TIMEOUT_MINUTES.

    Race condition prevention
    -------------------------
    1. SeatReservation.objects.filter(...).delete() — clears stale holds.
    2. transaction.atomic() ensures all DB operations in the loop are one unit.
    3. select_for_update() acquires a row-level write lock on the Seat row,
       so a second concurrent request blocks until the first commits.
    4. is_booked check + held_by_other check inside the lock.
    5. SeatReservation.OneToOneField(seat) — DB UNIQUE constraint is the
       final safety net; second INSERT raises IntegrityError.

    Consistency model: ACID — all-or-nothing per seat, serialised writes.
    """
    theater = get_object_or_404(Theater, id=theater_id)
    if request.method != 'POST':
        return redirect('book_seats', theater_id=theater_id)

    selected_seat_ids = request.POST.getlist('seats')
    if not selected_seat_ids:
        return redirect('book_seats', theater_id=theater_id)

    now        = timezone.now()
    expires_at = now + timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)
    conflicts  = []
    reserved_count = 0

    # Step 1: Clean up ALL expired reservations system-wide.
    # Critical on Render free tier — the service spins down after inactivity
    # and the background scheduler stops running, leaving stale rows in the DB.
    # This ensures expired holds from before the spindown never block new bookings.
    SeatReservation.objects.filter(expires_at__lte=now).delete()

    # Step 2: Delete ALL previous holds by this user across ALL theaters
    # so switching between movies/theaters never leaves ghost reservations.
    SeatReservation.objects.filter(user=request.user).delete()

    for seat_id in selected_seat_ids:
        try:
            with transaction.atomic():
                try:
                    seat = Seat.objects.select_for_update().get(id=seat_id, theater=theater)
                except OperationalError:
                    seat = get_object_or_404(Seat, id=seat_id, theater=theater)

                if seat.is_booked:
                    conflicts.append(seat.seat_number)
                    continue

                if SeatReservation.objects.filter(
                    seat=seat, expires_at__gt=now
                ).exclude(user=request.user).exists():
                    conflicts.append(seat.seat_number)
                    continue

                SeatReservation.objects.create(
                    seat=seat, user=request.user,
                    theater=theater, expires_at=expires_at,
                )
                reserved_count += 1

        except IntegrityError:
            try:
                conflicts.append(Seat.objects.get(id=seat_id).seat_number)
            except Seat.DoesNotExist:
                pass

    if reserved_count == 0:
        error = (
            f"Seat(s) {', '.join(conflicts)} are already held or booked."
            if conflicts else None
        )
        return _seat_map_response(request, theater, error=error)

    return redirect('confirm_booking', theater_id=theater_id)


@login_required(login_url='/login/')
def confirm_booking(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    now     = timezone.now()

    active = (
        SeatReservation.objects
        .filter(user=request.user, theater=theater, expires_at__gt=now)
        .select_related('seat')
    )

    if not active.exists():
        return _seat_map_response(
            request, theater,
            error='Your reservation expired. Please select seats again.',
        )

    earliest         = active.order_by('expires_at').first()
    seconds_remaining = max(0, int((earliest.expires_at - now).total_seconds()))
    amount_paise      = active.count() * _seat_price_paise()

    from django.conf import settings
    return render(request, 'movies/confirm_booking.html', {
        'theater':          theater,
        'reservations':     active,
        'seconds_remaining': seconds_remaining,
        'timeout_minutes':  RESERVATION_TIMEOUT_MINUTES,
        'amount_paise':     amount_paise,
        'amount_inr':       amount_paise / 100,
        'razorpay_key_id':  settings.RAZORPAY_KEY_ID,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Task 3 — Payment (Razorpay)
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def create_payment(request, theater_id):
    """
    Create a Razorpay order server-side.

    Amount is computed from the reservation count (server knows the price).
    The client cannot send an amount — fraud is impossible at this layer.

    Idempotency: if the same seats already have a CREATED payment, reuse it.
    This handles the "browser back + retry" case without double-charging.
    """
    theater = get_object_or_404(Theater, id=theater_id)
    now     = timezone.now()

    reservations = SeatReservation.objects.filter(
        user=request.user, theater=theater, expires_at__gt=now,
    )
    if not reservations.exists():
        return JsonResponse({'error': 'Reservation expired. Please select seats again.'}, status=400)

    seat_ids     = list(reservations.values_list('seat_id', flat=True))
    amount_paise = len(seat_ids) * _seat_price_paise()

    # Idempotency check
    existing = Payment.objects.filter(
        user=request.user, theater=theater, status=Payment.Status.CREATED,
    ).order_by('-created_at').first()

    if existing and set(existing.seat_ids) == set(seat_ids):
        payment = existing
    else:
        try:
            order = razorpay_client.create_order(
                amount_paise=amount_paise,
                receipt=str(uuid.uuid4()),
                notes={'theater': theater.name, 'movie': theater.movie.name},
            )
        except RazorpayError as exc:
            logger.error('Razorpay order creation failed: %s', exc)
            return JsonResponse({'error': str(exc)}, status=502)

        payment = Payment.objects.create(
            user=request.user, theater=theater,
            seat_ids=seat_ids, amount_paise=amount_paise,
            razorpay_order_id=order['id'],
        )

    from django.conf import settings
    return JsonResponse({
        'order_id':    payment.razorpay_order_id,
        'amount':      payment.amount_paise,
        'currency':    payment.currency,
        'booking_ref': str(payment.booking_ref),
        'key_id':      settings.RAZORPAY_KEY_ID,
        'movie_name':  theater.movie.name,
        'theater_name': theater.name,
    })


@login_required(login_url='/login/')
@require_POST
def payment_callback(request, theater_id):
    """
    Browser redirect after checkout.

    Security: HMAC-SHA256 signature is verified BEFORE any booking is created.
    The signature binds order_id + payment_id, preventing replay attacks.
    """
    theater             = get_object_or_404(Theater, id=theater_id)
    razorpay_order_id   = request.POST.get('razorpay_order_id', '')
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '')
    razorpay_signature  = request.POST.get('razorpay_signature', '')

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return redirect('payment_failed')

    try:
        valid = razorpay_client.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        )
    except Exception:
        valid = False

    if not valid:
        logger.warning('Invalid signature for order %s user %s', razorpay_order_id, request.user)
        return redirect('payment_failed')

    try:
        payment = Payment.objects.get(razorpay_order_id=razorpay_order_id, user=request.user)
    except Payment.DoesNotExist:
        return redirect('payment_failed')

    if not payment.razorpay_payment_id:
        Payment.objects.filter(pk=payment.pk).update(razorpay_payment_id=razorpay_payment_id)
        payment.razorpay_payment_id = razorpay_payment_id

    if _finalize_booking(payment):
        # Task 6: send confirmation email (non-blocking background thread)
        bookings = Booking.objects.filter(
            user=payment.user, theater=payment.theater
        ).select_related('seat').order_by('-booked_at')[:len(payment.seat_ids)]
        send_booking_confirmation(payment.refresh_from_db() or payment, bookings)
        return redirect('payment_success')
    return redirect('payment_failed')


@csrf_exempt
@require_POST
def payment_webhook(request):
    """
    Razorpay → our server (no browser involved).

    Security layers
    ---------------
    1. HMAC-SHA256 over raw request body (webhook secret ≠ API secret).
    2. webhook_event_id UNIQUE constraint — re-delivery is a no-op.
    3. Amount mismatch check — captured_amount must equal stored amount.
    4. @csrf_exempt only here (Razorpay servers can't send CSRF tokens).
    """
    raw_body  = request.body
    signature = request.headers.get('X-Razorpay-Signature', '')

    if not razorpay_client.verify_webhook_signature(raw_body, signature):
        return HttpResponse('Signature mismatch', status=400)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return HttpResponse('Bad JSON', status=400)

    event    = payload.get('event', '')
    event_id = payload.get('id', '')

    # Idempotency: reject duplicate webhook deliveries
    if event_id and Payment.objects.filter(webhook_event_id=event_id).exists():
        return HttpResponse('Already processed', status=200)

    if event == 'payment.captured':
        try:
            entity          = payload['payload']['payment']['entity']
            order_id        = entity.get('order_id', '')
            payment_id      = entity.get('id', '')
            captured_amount = entity.get('amount', 0)
            payment = Payment.objects.get(razorpay_order_id=order_id)

            if captured_amount != payment.amount_paise:
                payment.status = Payment.Status.FAILED
                payment.failure_reason = 'Amount mismatch.'
                payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
                return HttpResponse('Amount mismatch', status=200)

            Payment.objects.filter(pk=payment.pk).update(
                razorpay_payment_id=payment_id,
                webhook_event_id=event_id,
                webhook_received_at=timezone.now(),
            )
            payment.refresh_from_db()

            if _finalize_booking(payment):
                bookings = Booking.objects.filter(
                    user=payment.user, theater=payment.theater
                ).select_related('seat').order_by('-booked_at')[:len(payment.seat_ids)]
                send_booking_confirmation(payment, bookings)

        except Payment.DoesNotExist:
            logger.error('Webhook: no Payment for order_id=%s', order_id)
        except (KeyError, TypeError) as exc:
            logger.error('Webhook payload error: %s', exc)

    elif event == 'payment.failed':
        try:
            entity   = payload['payload']['payment']['entity']
            order_id = entity.get('order_id', '')
            reason   = entity.get('error_description', 'Payment failed')
            Payment.objects.filter(razorpay_order_id=order_id).update(
                status=Payment.Status.FAILED,
                failure_reason=reason,
                webhook_event_id=event_id,
                webhook_received_at=timezone.now(),
            )
        except (KeyError, TypeError):
            pass

    return HttpResponse('OK', status=200)


@login_required(login_url='/login/')
def payment_success(request):
    payment = (
        Payment.objects.filter(user=request.user, status=Payment.Status.PAID)
        .order_by('-updated_at').select_related('theater__movie').first()
    )
    return render(request, 'movies/payment_success.html', {'payment': payment})


@login_required(login_url='/login/')
def payment_failed(request):
    payment = (
        Payment.objects.filter(user=request.user)
        .exclude(status=Payment.Status.PAID)
        .order_by('-updated_at').select_related('theater__movie').first()
    )
    return render(request, 'movies/payment_failed.html', {'payment': payment})


@login_required(login_url='/login/')
def release_seats(request, theater_id):
    if request.method == 'POST':
        theater = get_object_or_404(Theater, id=theater_id)
        deleted, _ = SeatReservation.objects.filter(
            user=request.user, theater=theater,
        ).delete()
        return JsonResponse({'status': 'released', 'count': deleted})
    return JsonResponse({'status': 'noop'})


# ─────────────────────────────────────────────────────────────────────────────
# Task 4 — Analytics dashboard
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required(login_url='/login/')
def analytics_dashboard(request):
    """
    Admin-only dashboard.
    @staff_member_required checks user.is_active AND user.is_staff on EVERY
    request — not just at login — preventing privilege escalation.
    """
    force = request.GET.get('refresh') == '1'

    summary       = _analytics.get_summary_stats(force_refresh=force)
    popular       = _analytics.get_popular_movies(limit=8,  force_refresh=force)
    occupancy     = _analytics.get_theater_occupancy(force_refresh=force)
    peak_hours    = _analytics.get_peak_hours(force_refresh=force)
    revenue_d     = _analytics.get_revenue_chart('daily',   days=30,  force_refresh=force)
    revenue_w     = _analytics.get_revenue_chart('weekly',  days=90,  force_refresh=force)
    revenue_m     = _analytics.get_revenue_chart('monthly', days=365, force_refresh=force)
    pay_breakdown = _analytics.get_payment_breakdown(force_refresh=force)
    recent        = _analytics.get_recent_bookings(limit=8)

    return render(request, 'movies/analytics_dashboard.html', {
        'summary':             summary,
        'popular':             popular,
        'occupancy':           occupancy,
        'recent':              recent,
        'revenue_daily_json':  json.dumps(revenue_d),
        'revenue_weekly_json': json.dumps(revenue_w),
        'revenue_monthly_json': json.dumps(revenue_m),
        'peak_hours_json':     json.dumps(peak_hours),
        'popular_json':        json.dumps(popular),
        'pay_breakdown_json':  json.dumps(pay_breakdown),
        'cache_ttl_secs':      _analytics.CACHE_TTL,
    })


@staff_member_required(login_url='/login/')
def analytics_api(request):
    section = request.GET.get('section', 'summary')
    force   = request.GET.get('refresh') == '1'
    dispatch = {
        'summary':  lambda: _analytics.get_summary_stats(force_refresh=force),
        'revenue':  lambda: _analytics.get_revenue_chart(
                        request.GET.get('period', 'daily'),
                        int(request.GET.get('days', 30)), force_refresh=force),
        'movies':   lambda: _analytics.get_popular_movies(force_refresh=force),
        'theaters': lambda: _analytics.get_theater_occupancy(force_refresh=force),
        'hours':    lambda: _analytics.get_peak_hours(force_refresh=force),
        'payments': lambda: _analytics.get_payment_breakdown(force_refresh=force),
    }
    return JsonResponse({'data': dispatch.get(section, dispatch['summary'])(),
                         'cached_ttl': _analytics.CACHE_TTL})
