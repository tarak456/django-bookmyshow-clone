"""
movies/email_service.py — Task 6: Booking Confirmation Email System
====================================================================

Design
------
send_booking_confirmation() is called immediately after a payment succeeds.
It does NOT block the HTTP response — it spawns a daemon thread and returns
instantly.  The caller (payment_callback / payment_webhook) continues to the
redirect within milliseconds regardless of email latency.

Retry logic
-----------
The background thread retries up to MAX_RETRIES times with exponential
backoff (2, 4, 8 seconds).  All failures are logged; after exhausting
retries a final ERROR log is written so the ops team can re-send manually.

Why no Celery?
--------------
Celery requires Redis/RabbitMQ which the student's local machine doesn't have.
threading.Thread(daemon=True) achieves the same "non-blocking" semantics for
development.  In production, swap _dispatch() to enqueue a Celery task.

Security
--------
- SMTP credentials come from environment variables (never hardcoded).
- Email is sent with TLS (EMAIL_USE_TLS = True in settings).
- The booking_ref (UUID) in the email is not guessable — safe to include.
"""

import logging
import threading
import time
from typing import Dict, Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3          # attempts before giving up
BASE_BACKOFF = 2          # seconds; doubles each retry (2, 4, 8)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_booking_confirmation(payment, bookings):
    """
    Entry point — build the email context and dispatch in the background.

    Parameters
    ----------
    payment  : Payment model instance (status must already be PAID)
    bookings : QuerySet/list of Booking instances for this payment
    """
    if not payment.user.email:
        logger.info(
            'Skipping confirmation email for booking_ref=%s: user has no email address.',
            payment.booking_ref,
        )
        return

    context: Dict[str, Any] = {
        'user':        payment.user,
        'movie_name':  payment.theater.movie.name,
        'theater_name': payment.theater.name,
        'show_time':   payment.theater.time,
        'booking_ref': str(payment.booking_ref),
        'amount_inr':  payment.amount_inr,
        'seats':       [b.seat.seat_number for b in bookings],
        'payment_id':  payment.razorpay_payment_id or '—',
        'site_name':   'BookMySeat',
    }

    _dispatch(context, payment.user.email, str(payment.booking_ref))


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch(context: dict, to_email: str, booking_ref: str):
    """Spawn a daemon thread so the HTTP response is not blocked."""
    thread = threading.Thread(
        target=_send_with_retry,
        args=(context, to_email, booking_ref),
        daemon=True,
        name=f'email-{booking_ref[:8]}',
    )
    thread.start()
    logger.debug('Email dispatch thread started for booking_ref=%s', booking_ref)


def _send_with_retry(context: dict, to_email: str, booking_ref: str):
    """Retry loop with exponential backoff. Runs in background thread."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _send(context, to_email)
            logger.info(
                'Booking confirmation email sent (attempt %d/%d) to %s — ref=%s',
                attempt, MAX_RETRIES, to_email, booking_ref,
            )
            return  # success — exit thread
        except Exception as exc:
            logger.warning(
                'Email attempt %d/%d failed for ref=%s: %s',
                attempt, MAX_RETRIES, booking_ref, exc,
            )
            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF ** attempt
                logger.debug('Retrying in %ds…', backoff)
                time.sleep(backoff)

    logger.error(
        'All %d email attempts failed for booking_ref=%s to %s. '
        'Manual re-send required.',
        MAX_RETRIES, booking_ref, to_email,
    )


def _send(context: dict, to_email: str):
    """
    Render HTML template and send via Django's email backend.

    Uses EmailMultiAlternatives so we can attach both an HTML body
    and a plain-text fallback for email clients that block HTML.
    """
    subject      = f"Booking Confirmed — {context['movie_name']} | {context['site_name']}"
    from_email   = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bookmyseat.in')

    html_body    = render_to_string('emails/booking_confirmation.html', context)
    plain_body   = _plain_text(context)

    msg = EmailMultiAlternatives(subject, plain_body, from_email, [to_email])
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)


def _plain_text(ctx: dict) -> str:
    """
    Plain-text fallback for email clients that don't render HTML.
    Also useful if the template file is missing (belt-and-suspenders).
    """
    seats = ', '.join(ctx['seats']) if ctx['seats'] else '—'
    return (
        f"Hi {ctx['user'].username},\n\n"
        f"Your booking is CONFIRMED!\n\n"
        f"Movie     : {ctx['movie_name']}\n"
        f"Theater   : {ctx['theater_name']}\n"
        f"Show time : {ctx['show_time']}\n"
        f"Seats     : {seats}\n"
        f"Amount    : ₹{ctx['amount_inr']}\n"
        f"Payment ID: {ctx['payment_id']}\n"
        f"Booking ref: {ctx['booking_ref']}\n\n"
        f"Enjoy your movie!\n"
        f"— Team {ctx['site_name']}"
    )
