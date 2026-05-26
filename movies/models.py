"""
movies/models.py
================
All domain models for the BookMySeat movie-ticketing platform.

App structure
-------------
Movie      — film catalogue with trailer, genres, languages
Genre      — e.g. Action, Drama (Task 5 — filtering)
Language   — e.g. Hindi, English (Task 5 — filtering)
Theater    — screening hall linked to one Movie + Show time
Seat       — individual seat in a Theater
Booking    — permanent confirmed booking (one seat per row)
SeatReservation — temporary 2-min lock (Task 2 — concurrency)
Payment    — Razorpay order/payment record (Task 3)
"""
import re
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

# How long a seat hold lasts before the background scheduler releases it.
RESERVATION_TIMEOUT_MINUTES = 2


# ─────────────────────────────────────────────────────────────────────────────
# Task 1 — YouTube URL helpers
# ─────────────────────────────────────────────────────────────────────────────

def validate_youtube_url(value):
    """
    Model-level validator that blocks anything other than a real YouTube URL.
    This is the FIRST XSS gate: bad values never reach the DB.

    The template tag (movie_tags.py) is the SECOND gate: it re-validates the
    extracted video ID before interpolating anything into the DOM.
    """
    if not value:
        return
    pattern = re.compile(
        r'^https?://'
        r'(?:(?:www\.)?youtube\.com/watch\?.*v=|(?:www\.)?youtu\.be/)'
        r'([\w\-]{11})[^\s]*$',
        re.IGNORECASE,
    )
    if not pattern.match(value):
        raise ValidationError(
            'Enter a valid YouTube URL '
            '(e.g. https://www.youtube.com/watch?v=XXXXXXXXXXX).'
        )


def extract_youtube_id(url):
    """Return the 11-char video ID from any valid YouTube URL, or None."""
    if not url:
        return None
    short = re.search(r'youtu\.be/([\w\-]{11})', url)
    if short:
        return short.group(1)
    long_ = re.search(r'[?&]v=([\w\-]{11})', url)
    return long_.group(1) if long_ else None


# ─────────────────────────────────────────────────────────────────────────────
# Task 5 — Genre & Language (Advanced Filtering)
# ─────────────────────────────────────────────────────────────────────────────

class Genre(models.Model):
    """
    Film genre used for server-side filtering.

    Why slug? Slugs let us build clean filter URLs like
    /movies/?genre=action without exposing internal PKs.
    The slug is auto-generated from name on save.
    """
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(
        unique=True,
        help_text='Auto-generated from name. Used in filter URLs.',
    )

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['slug'], name='genre_slug_idx')]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Language(models.Model):
    """
    Audio/subtitle language for a movie.
    ISO 639-1 code (e.g. 'hi', 'en', 'te') used for filtering.
    """
    name = models.CharField(max_length=60, unique=True)
    code = models.CharField(
        max_length=8, unique=True,
        help_text="ISO 639-1 code, e.g. 'hi', 'en', 'te'",
    )

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['code'], name='language_code_idx')]

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# Core catalogue
# ─────────────────────────────────────────────────────────────────────────────

class Movie(models.Model):
    """
    Film record.

    genres and languages are ManyToMany so a single query with
    Prefetch can load them without N+1 queries:
        Movie.objects.prefetch_related('genres', 'languages')

    Performance note (Task 5):
    Filtering by genre/language uses the junction table created by
    the M2M field.  Because genres and languages are low-cardinality
    (< 30 rows each), no extra index is needed on the junction table —
    SQLite will bitmap-scan the small sets efficiently.
    """
    name        = models.CharField(max_length=255)
    image       = models.ImageField(upload_to='movies/')
    rating      = models.DecimalField(max_digits=3, decimal_places=1)
    cast        = models.TextField()
    description = models.TextField(blank=True, null=True)
    trailer_url = models.URLField(
        blank=True, null=True,
        validators=[validate_youtube_url],
        help_text='YouTube trailer URL — only valid YouTube links accepted.',
    )

    # Task 5 — filtering dimensions
    genres    = models.ManyToManyField(Genre,    blank=True, related_name='movies')
    languages = models.ManyToManyField(Language, blank=True, related_name='movies')

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['-id']
        indexes  = [models.Index(fields=['name'], name='movie_name_idx')]

    def __str__(self):
        return self.name

    @property
    def youtube_embed_id(self):
        return extract_youtube_id(self.trailer_url)


class Theater(models.Model):
    """
    A screening — one movie, one venue, one show-time.

    Design note: in a full production system this would be split into
    Venue + Screen + Show, but for this internship scope we keep it flat.
    """
    name  = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='theaters')
    time  = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['movie'], name='theater_movie_idx')]

    def __str__(self):
        return f'{self.name} — {self.movie.name} at {self.time}'


class Seat(models.Model):
    """
    One physical seat in a Theater.
    is_booked is the permanent booking flag (set after payment confirmed).
    The temporary 2-min lock lives in SeatReservation, not here.
    """
    theater     = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked   = models.BooleanField(default=False)

    class Meta:
        indexes = [
            # Occupancy query: WHERE theater_id=X AND is_booked=1
            models.Index(fields=['theater', 'is_booked'], name='seat_theater_booked_idx'),
        ]

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'


class Booking(models.Model):
    """
    Permanent booking record created after payment is confirmed.

    OneToOneField on seat guarantees at the DB level that no seat
    can be double-booked — even under concurrent writes the UNIQUE
    constraint will reject the second INSERT.

    Indexes (Task 4 — analytics):
    Each composite index maps to one analytics GROUP BY pattern:
      movie + booked_at  →  "top movies this month"
      theater + booked_at →  "busiest theater this week"
      user + booked_at   →  profile booking history
    """
    user     = models.ForeignKey(User,    on_delete=models.CASCADE)
    seat     = models.OneToOneField(Seat, on_delete=models.CASCADE)
    movie    = models.ForeignKey(Movie,   on_delete=models.CASCADE)
    theater  = models.ForeignKey(Theater, on_delete=models.CASCADE)
    booked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['booked_at'],           name='booking_booked_at_idx'),
            models.Index(fields=['movie', 'booked_at'],  name='booking_movie_time_idx'),
            models.Index(fields=['theater', 'booked_at'],name='booking_theater_time_idx'),
            models.Index(fields=['user', 'booked_at'],   name='booking_user_time_idx'),
        ]

    def __str__(self):
        return f'Booking by {self.user.username} — {self.seat.seat_number} at {self.theater.name}'


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — Concurrency-safe seat reservation
# ─────────────────────────────────────────────────────────────────────────────

class SeatReservation(models.Model):
    """
    Temporary 2-minute lock on a Seat.

    Race condition prevention
    -------------------------
    1. select_for_update() acquires a row-level write lock in the DB.
    2. transaction.atomic() ensures the lock + INSERT are one atomic unit.
    3. OneToOneField seat provides a UNIQUE constraint as a final safety net:
       even if two transactions somehow pass the application checks, the DB
       will reject the second INSERT with IntegrityError.

    Consistency model: ACID via Django's atomic transactions.
    The scheduler (scheduler.py) runs every 30 s to release expired rows.

    Edge cases handled
    ------------------
    - User closes tab     → beforeunload JS fires release_seats endpoint;
                            scheduler cleans up anything missed.
    - Network failure     → navigator.sendBeacon with keepalive:true;
                            scheduler is the safety net.
    - Multiple devices    → same user, same seat: select_for_update serialises
                            the requests; first wins, second gets conflict.
    """
    seat      = models.OneToOneField(Seat, on_delete=models.CASCADE, related_name='reservation')
    user      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reservations')
    theater   = models.ForeignKey(Theater, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['expires_at'], name='reservation_expires_idx')]

    def __str__(self):
        return f'Reservation: {self.seat} by {self.user.username} until {self.expires_at}'

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


# ─────────────────────────────────────────────────────────────────────────────
# Task 3 — Payment (Razorpay)
# ─────────────────────────────────────────────────────────────────────────────

class Payment(models.Model):
    """
    One Payment row per Razorpay order attempt.

    Idempotency
    -----------
    booking_ref (UUID) is our idempotency key — generated server-side, sent
    to Razorpay as the `receipt`.  If the browser retries create_payment,
    we reuse the existing CREATED payment rather than creating a new order.

    webhook_event_id has unique=True:  if Razorpay delivers the same webhook
    twice, the second INSERT raises IntegrityError and we return 200 without
    re-processing (at-most-once semantics).

    Replay attack prevention
    ------------------------
    verify_payment_signature() signs order_id + payment_id with HMAC-SHA256.
    A valid signature from a different transaction cannot be replayed here
    because the order_id is bound into the signature.

    Fraud prevention
    ----------------
    amount_paise is set SERVER-SIDE from the reservation count; the client
    cannot send an amount.  The webhook handler also checks that
    captured_amount == payment.amount_paise before finalising.
    """

    class Status(models.TextChoices):
        CREATED   = 'created',   'Order Created'
        PAID      = 'paid',      'Paid'
        FAILED    = 'failed',    'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    booking_ref        = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    user               = models.ForeignKey(User,    on_delete=models.CASCADE, related_name='payments')
    theater            = models.ForeignKey(Theater, on_delete=models.CASCADE)
    seat_ids           = models.JSONField(help_text='Seat PKs in this payment.')
    amount_paise       = models.PositiveIntegerField()
    currency           = models.CharField(max_length=8, default='INR')
    razorpay_order_id  = models.CharField(max_length=100, unique=True)
    razorpay_payment_id= models.CharField(max_length=100, unique=True, null=True, blank=True)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    failure_reason     = models.TextField(blank=True)
    webhook_event_id   = models.CharField(max_length=100, unique=True, null=True, blank=True)
    webhook_received_at= models.DateTimeField(null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['razorpay_order_id'],    name='payment_order_idx'),
            models.Index(fields=['status', 'created_at'], name='payment_status_time_idx'),
        ]

    def __str__(self):
        return f'Payment {self.booking_ref} — {self.status} — ₹{self.amount_paise // 100}'

    @property
    def amount_inr(self):
        return self.amount_paise / 100
