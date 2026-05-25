"""
Analytics engine for the BookMySeat admin dashboard.

Design principles
-----------------
1. ALL aggregation happens in the database via Django ORM aggregation functions
   (Sum, Count, Avg, TruncDay, ExtractHour, etc.).  No row is ever loaded into
   Python memory just to be summed or counted.

2. Every public function checks the in-memory cache first.  Cache misses trigger
   a single optimised DB query; the result is stored for CACHE_TTL seconds.
   This prevents hammering the DB when multiple admins view the dashboard.

3. The functions expose a `force_refresh=False` parameter so the dashboard can
   offer a manual "Refresh data" button without waiting for the TTL to expire.

Cache backend
-------------
Uses Django's built-in LocMemCache (no Redis, no extra packages).
Configured in settings.py under the 'analytics' alias so it doesn't
share the default cache namespace.
"""

import logging
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import caches
from django.db.models import (
    Avg, Case, Count, ExpressionWrapper, F, FloatField,
    IntegerField, Q, Sum, Value, When,
)
from django.db.models.functions import (
    ExtractHour, TruncDay, TruncMonth, TruncWeek,
)
from django.utils import timezone

from .models import Booking, Movie, Payment, Seat, Theater

logger = logging.getLogger(__name__)

# Cache TTL: 5 minutes for most analytics, 1 min for today's live numbers
CACHE_TTL        = 300
LIVE_CACHE_TTL   = 60
_CACHE_ALIAS     = 'analytics'


def _cache():
    """Return the analytics cache backend."""
    try:
        return caches[_CACHE_ALIAS]
    except Exception:
        return caches['default']


# ── Summary stats ──────────────────────────────────────────────────────────────

def get_summary_stats(force_refresh=False):
    """
    Returns a dict with headline KPIs shown in the summary cards.
    Uses a single DB pass per metric; no Python-level loops.
    """
    key = 'analytics:summary'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    now  = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    paid_qs = Payment.objects.filter(status=Payment.Status.PAID)

    # Revenue aggregates — one query each, SUM at DB level
    total_rev   = paid_qs.aggregate(t=Sum('amount_paise'))['t'] or 0
    today_rev   = paid_qs.filter(created_at__gte=today_start).aggregate(t=Sum('amount_paise'))['t'] or 0
    week_rev    = paid_qs.filter(created_at__gte=week_start).aggregate(t=Sum('amount_paise'))['t'] or 0
    month_rev   = paid_qs.filter(created_at__gte=month_start).aggregate(t=Sum('amount_paise'))['t'] or 0

    # Booking counts — COUNT at DB level
    total_bookings = Booking.objects.count()
    today_bookings = Booking.objects.filter(booked_at__gte=today_start).count()
    week_bookings  = Booking.objects.filter(booked_at__gte=week_start).count()

    # Users
    total_users = User.objects.filter(is_active=True, is_staff=False).count()

    # Cancellation / failure rate
    total_payments = Payment.objects.count()
    failed_count   = Payment.objects.filter(
        status__in=[Payment.Status.FAILED, Payment.Status.CANCELLED]
    ).count()
    failure_rate = round(failed_count / total_payments * 100, 1) if total_payments else 0.0

    # Average ticket price (over all paid payments)
    avg_ticket = paid_qs.aggregate(a=Avg('amount_paise'))['a'] or 0

    result = {
        'total_revenue_inr':  total_rev   / 100,
        'today_revenue_inr':  today_rev   / 100,
        'week_revenue_inr':   week_rev    / 100,
        'month_revenue_inr':  month_rev   / 100,
        'total_bookings':     total_bookings,
        'today_bookings':     today_bookings,
        'week_bookings':      week_bookings,
        'total_users':        total_users,
        'failure_rate':       failure_rate,
        'avg_ticket_inr':     round(avg_ticket / 100, 2),
    }
    c.set(key, result, LIVE_CACHE_TTL)
    return result


# ── Revenue over time ──────────────────────────────────────────────────────────

def get_revenue_chart(period='daily', days=30, force_refresh=False):
    """
    Returns labels + values for the revenue line chart.
    period: 'daily' | 'weekly' | 'monthly'
    Aggregation happens entirely in SQL via TruncDay/TruncWeek/TruncMonth.
    """
    key = f'analytics:revenue:{period}:{days}'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    since = timezone.now() - timedelta(days=days)
    trunc_map = {'daily': TruncDay, 'weekly': TruncWeek, 'monthly': TruncMonth}
    trunc_fn = trunc_map.get(period, TruncDay)

    # GROUP BY truncated date at DB level — never pulls individual rows
    qs = (
        Payment.objects
        .filter(status=Payment.Status.PAID, created_at__gte=since)
        .annotate(period=trunc_fn('created_at'))
        .values('period')
        .annotate(
            revenue=Sum('amount_paise'),
            bookings=Count('id'),
        )
        .order_by('period')
    )

    labels   = [row['period'].strftime('%d %b') for row in qs]
    revenues = [round(row['revenue'] / 100, 2)  for row in qs]
    counts   = [row['bookings']                  for row in qs]

    result = {'labels': labels, 'revenues': revenues, 'counts': counts}
    c.set(key, result, CACHE_TTL)
    return result


# ── Popular movies ─────────────────────────────────────────────────────────────

def get_popular_movies(limit=10, force_refresh=False):
    """
    Top movies by booking count + revenue.
    Uses GROUP BY movie_id at DB level; O(movies) not O(bookings).
    """
    key = f'analytics:movies:popular:{limit}'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    # COUNT bookings per movie — one GROUP BY query
    booking_counts = (
        Booking.objects
        .values('movie_id', 'movie__name')
        .annotate(bookings=Count('id'))
        .order_by('-bookings')[:limit]
    )

    # SUM revenue per movie — one GROUP BY query
    revenue_map = dict(
        Payment.objects
        .filter(status=Payment.Status.PAID)
        .values('theater__movie_id')
        .annotate(rev=Sum('amount_paise'))
        .values_list('theater__movie_id', 'rev')
    )

    result = [
        {
            'movie_id':   row['movie_id'],
            'name':       row['movie__name'],
            'bookings':   row['bookings'],
            'revenue_inr': round(revenue_map.get(row['movie_id'], 0) / 100, 2),
        }
        for row in booking_counts
    ]
    c.set(key, result, CACHE_TTL)
    return result


# ── Theater occupancy ──────────────────────────────────────────────────────────

def get_theater_occupancy(force_refresh=False):
    """
    Occupancy rate per theater = booked_seats / total_seats * 100.
    Calculated with a CASE expression at DB level — no Python division loops.
    """
    key = 'analytics:theaters:occupancy'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    qs = (
        Theater.objects
        .annotate(
            total_seats  = Count('seats'),
            booked_seats = Count('seats', filter=Q(seats__is_booked=True)),
        )
        .filter(total_seats__gt=0)
        .annotate(
            # ExpressionWrapper lets us do float division in SQL
            occupancy_pct=ExpressionWrapper(
                F('booked_seats') * 100.0 / F('total_seats'),
                output_field=FloatField(),
            )
        )
        .select_related('movie')
        .order_by('-occupancy_pct')
    )

    result = [
        {
            'theater_id':    t.id,
            'theater_name':  t.name,
            'movie_name':    t.movie.name,
            'total_seats':   t.total_seats,
            'booked_seats':  t.booked_seats,
            'occupancy_pct': round(t.occupancy_pct, 1),
        }
        for t in qs
    ]
    c.set(key, result, CACHE_TTL)
    return result


# ── Peak booking hours ─────────────────────────────────────────────────────────

def get_peak_hours(force_refresh=False):
    """
    Booking count grouped by hour-of-day (0–23).
    ExtractHour runs in SQL; returns 24 rows maximum.
    """
    key = 'analytics:bookings:peak_hours'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    hour_data = (
        Booking.objects
        .annotate(hour=ExtractHour('booked_at'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('hour')
    )

    # Build a complete 0–23 array (hours with no bookings = 0)
    hour_map = {row['hour']: row['count'] for row in hour_data}
    labels = [f'{h:02d}:00' for h in range(24)]
    counts = [hour_map.get(h, 0) for h in range(24)]

    result = {'labels': labels, 'counts': counts}
    c.set(key, result, CACHE_TTL)
    return result


# ── Recent activity ────────────────────────────────────────────────────────────

def get_recent_bookings(limit=10):
    """
    Most recent bookings for the activity feed.
    Uses select_related to avoid N+1; limited to `limit` rows.
    No cache — always fresh for the live feed.
    """
    return (
        Booking.objects
        .select_related('user', 'movie', 'theater', 'seat')
        .order_by('-booked_at')[:limit]
    )


def get_payment_breakdown(force_refresh=False):
    """
    Count of payments by status — for the donut chart.
    Single GROUP BY query.
    """
    key = 'analytics:payments:breakdown'
    c = _cache()
    if not force_refresh:
        cached = c.get(key)
        if cached:
            return cached

    qs = (
        Payment.objects
        .values('status')
        .annotate(count=Count('id'))
    )
    result = {row['status']: row['count'] for row in qs}
    c.set(key, result, CACHE_TTL)
    return result


def invalidate_all():
    """Force-clear all analytics cache keys (e.g. after bulk data import)."""
    c = _cache()
    prefixes = [
        'analytics:summary', 'analytics:payments:breakdown',
        'analytics:theaters:occupancy', 'analytics:bookings:peak_hours',
        'analytics:movies:popular:10',
        'analytics:revenue:daily:30', 'analytics:revenue:weekly:90',
        'analytics:revenue:monthly:365',
    ]
    for key in prefixes:
        c.delete(key)
    logger.info('Analytics cache invalidated.')
