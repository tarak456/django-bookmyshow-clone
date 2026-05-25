"""
Migration: add analytics-optimised indexes to Booking and Seat.

Why these indexes?
------------------
All analytics queries use DB-level aggregation (SUM, COUNT, GROUP BY) —
they never load full rows into Python. The indexes let SQLite/PostgreSQL
satisfy those queries with an index scan instead of a full table scan,
keeping P95 query time under 100ms even at 50,000+ bookings.

booking_booked_at_idx     — WHERE booked_at >= <date> (all time-range filters)
booking_movie_time_idx    — GROUP BY movie_id ORDER BY booked_at (popular movies)
booking_theater_time_idx  — GROUP BY theater_id ORDER BY booked_at (busy theaters)
booking_user_time_idx     — WHERE user_id = X ORDER BY booked_at (profile page)
seat_theater_booked_idx   — WHERE theater_id = X AND is_booked = 1 (occupancy rate)
payment_status_time_idx   — WHERE status='paid' AND created_at >= <date> (revenue)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0005_seatreservation_created_at'),
    ]

    operations = [
        # Booking analytics indexes
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['booked_at'], name='booking_booked_at_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['movie', 'booked_at'], name='booking_movie_time_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['theater', 'booked_at'], name='booking_theater_time_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['user', 'booked_at'], name='booking_user_time_idx'),
        ),
        # Seat occupancy index (theater + booking status together)
        migrations.AddIndex(
            model_name='seat',
            index=models.Index(fields=['theater', 'is_booked'], name='seat_theater_booked_idx'),
        ),
        # Payment revenue index
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['status', 'created_at'], name='payment_status_time_idx'),
        ),
    ]
