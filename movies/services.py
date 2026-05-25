"""
services.py — Business logic layer

Keeps views thin. Each public function is the single source of truth
for one operation. All DB writes happen inside transaction.atomic().
"""
import logging
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    Booking, EmailLog, Movie, Payment, Seat,
    SeatReservation, Theater, RESERVATION_TIMEOUT_MINUTES,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Task 5 — Movie filtering & pagination
# ─────────────────────────────────────────────────────────────────────────────

def get_filtered_movies(search='', genre_slugs=None, language_codes=None,
                        sort='name', page=1, per_page=12):
    """
    Server-side filtering with pagination.

    Performance notes
    -----------------
    • All filtering is done in SQL (WHERE/JOIN) — never loads the full table.
    • genre_slugs / language_codes use __in lookups on M2M join tables,
      backed by the implicit M2M index.
    • prefetch_related('genres','languages') fetches related rows in 2 extra
      queries (not N+1).
    • The booking_count annotation uses a subquery COUNT — only one extra
      column in the SELECT, no Python loops.
    """
    qs = Movie.objects.prefetch_related('genres', 'languages')

    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(cast__icontains=search)
        )

    if genre_slugs:
        # AND-semantics: movie must have ALL selected genres
        for slug in genre_slugs:
            qs = qs.filter(genres__slug=slug)

    if language_codes:
        for code in language_codes:
            qs = qs.filter(languages__code=code)

    # Annotate booking count for popularity sort — COUNT at DB level
    qs = qs.annotate(booking_count=Count('bookings', distinct=True))

    sort_map = {
        'name':     'name',
        '-name':    '-name',
        'rating':   '-rating',
        'popular':  '-booking_count',
        'newest':   '-release_date',
    }
    qs = qs.order_by(sort_map.get(sort, 'name')).distinct()

    paginator = Paginator(qs, per_page)
    page_obj  = paginator.get_page(page)
    return page_obj, paginator.count


def get_filter_facets():
    """
    Returns genre and language lists WITH booking counts — shown as
    "(Action, 42 bookings)" in the UI.  Two queries total, no Python math.
    """
    from .models import Genre, Language
    genres = (
        Genre.objects
        .annotate(movie_count=Count('movies', distinct=True))
        .order_by('name')
    )
    languages = (
        Language.objects
        .annotate(movie_count=Count('movies', distinct=True))
        .order_by('name')
    )
    return list(genres), list(languages)


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — Seat reservation
# ─────────────────────────────────────────────────────────────────────────────

def annotate_seats_for_user(seats, theater, user):
    """
    Attach .reserved_by_other and .reserved_by_me booleans to seat objects
    without N+1 queries. Two queryset calls total, regardless of seat count.
    """
    now = timezone.now()
    others_ids = set(
        SeatReservation.objects
        .filter(theater=theater, expires_at__gt=now)
        .exclude(user=user)
        .values_list('seat_id', flat=True)
    )
    mine_ids = set(
        SeatReservation.objects
        .filter(theater=theater, user=user, expires_at__gt=now)
        .values_list('seat_id', flat=True)
    )
    for seat in seats:
        seat.reserved_by_other = seat.id in others_ids
        seat.reserved_by_me    = seat.id in mine_ids
    return seats


def reserve_seats(theater, user, seat_ids):
    """
    Atomically lock the given seats for RESERVATION_TIMEOUT_MINUTES.

    Race condition prevention
    -------------------------
    select_for_update() acquires a row-level write lock on the Seat rows.
    On PostgreSQL this is a FOR UPDATE lock; on SQLite it serialises writes
    at the connection level via WAL.  Either way, two concurrent calls for
    the same seat_id cannot both succeed: the second sees the first's lock
    and either blocks (SELECT FOR UPDATE) or raises IntegrityError on INSERT
    (OneToOneField constraint on SeatReservation.seat).

    Returns (reserved_count, conflict_seat_numbers).
    """
    now        = timezone.now()
    expires_at = now + timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)

    # Wipe all old reservations for this user in this theater — fresh start
    SeatReservation.objects.filter(user=user, theater=theater).delete()

    reserved_count = 0
    conflicts      = []

    for seat_id in seat_ids:
        try:
            with transaction.atomic():
                try:
                    seat = Seat.objects.select_for_update().get(id=seat_id, theater=theater)
                except OperationalError:
                    # SQLite fallback — no nowait support
                    seat = Seat.objects.get(id=seat_id, theater=theater)

                if seat.is_booked:
                    conflicts.append(seat.seat_number)
                    continue

                held_by_other = (
                    SeatReservation.objects
                    .filter(seat=seat, expires_at__gt=now)
                    .exclude(user=user)
                    .exists()
                )
                if held_by_other:
                    conflicts.append(seat.seat_number)
                    continue

                SeatReservation.objects.create(
                    seat=seat, user=user, theater=theater, expires_at=expires_at
                )
                reserved_count += 1

        except IntegrityError:
            try:
                conflicts.append(Seat.objects.get(id=seat_id).seat_number)
            except Seat.DoesNotExist:
                pass

    return reserved_count, conflicts


def finalize_booking(payment: Payment) -> bool:
    """
    Convert a verified Payment into permanent Booking rows.

    Idempotent: if payment.status is already PAID, returns True immediately.
    Called from both the Razorpay callback (browser) AND the webhook (server),
    so it must be safe to call twice concurrently.  select_for_update() on the
    Payment row serialises concurrent callers at the DB level.
    """
    with transaction.atomic():
        try:
            locked = Payment.objects.select_for_update().get(pk=payment.pk)
        except OperationalError:
            locked = payment

        if locked.status == Payment.Status.PAID:
            return True   # already processed — idempotent

        seats = list(Seat.objects.select_for_update().filter(id__in=locked.seat_ids))

        for seat in seats:
            if seat.is_booked:
                locked.status = Payment.Status.FAILED
                locked.failure_reason = f'Seat {seat.seat_number} concurrently booked.'
                locked.save(update_fields=['status', 'failure_reason', 'updated_at'])
                return False
            try:
                booking = Booking.objects.create(
                    user=locked.user, seat=seat,
                    movie=locked.theater.movie, theater=locked.theater,
                    payment=locked,
                )
                seat.is_booked = True
                seat.save(update_fields=['is_booked'])

                # Task 6: queue confirmation email (non-blocking)
                queue_confirmation_email(booking)

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
# Task 6 — Email confirmation (non-blocking DB queue)
# ─────────────────────────────────────────────────────────────────────────────

def queue_confirmation_email(booking: Booking):
    """
    Insert an EmailLog row — does NOT send the email here.
    The background email worker (email_worker.py) picks it up.

    Why DB queue instead of Celery?
    --------------------------------
    No Redis or broker required. Survives server restart. Audit log built-in.
    In production swap the worker for a Celery task — the EmailLog model
    stays identical; only the dispatch mechanism changes.
    """
    if not booking.user.email:
        logger.warning('User %s has no email — skipping confirmation.', booking.user.username)
        return

    subject   = f'Booking Confirmed — {booking.movie.name}'
    body_html = _render_email_body(booking)

    try:
        EmailLog.objects.create(
            booking=booking,
            recipient=booking.user.email,
            subject=subject,
            body_html=body_html,
        )
    except Exception as exc:
        # Never let email queueing break the booking flow
        logger.error('Failed to queue confirmation email for booking %d: %s', booking.pk, exc)


def _render_email_body(booking: Booking) -> str:
    """Render the HTML email body from Django's template engine."""
    from django.template.loader import render_to_string
    return render_to_string('emails/booking_confirmation.html', {
        'booking':  booking,
        'user':     booking.user,
        'movie':    booking.movie,
        'theater':  booking.theater,
        'seat':     booking.seat,
        'payment':  booking.payment,
    })
