"""
email_worker.py — Background email delivery (Task 6)

Runs as a daemon thread started in MoviesConfig.ready().
Polls EmailLog for PENDING rows every 60 seconds and sends them via SMTP.

Retry logic
-----------
On SMTP failure, retry_count is incremented.  When retry_count >= max_retries
the row is marked FAILED and an error is logged.  This prevents infinite loops
on bad recipient addresses or SMTP misconfiguration.

How to replace with Celery
--------------------------
1. pip install celery
2. Create tasks.py with @shared_task send_confirmation_email(email_log_id)
3. In queue_confirmation_email(), call the task with .delay() instead of relying on this worker.
4. The EmailLog model and queue_confirmation_email() service function stay identical.
"""
import logging
import threading
import time

from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

logger = logging.getLogger(__name__)

_worker_thread = None


def _deliver_pending_emails():
    """Process all PENDING EmailLog rows."""
    from .models import EmailLog

    pending = (
        EmailLog.objects
        .filter(status=EmailLog.Status.PENDING, retry_count__lt=3)
        .select_related('booking__user', 'booking__movie')
        .order_by('created_at')[:20]    # process max 20 per cycle — avoids memory spike
    )

    for log in pending:
        try:
            msg = EmailMultiAlternatives(
                subject=log.subject,
                body=f'Booking confirmed for {log.booking.movie.name}.',  # plain-text fallback
                from_email=None,   # uses DEFAULT_FROM_EMAIL from settings
                to=[log.recipient],
            )
            msg.attach_alternative(log.body_html, 'text/html')
            msg.send(fail_silently=False)

            log.status  = EmailLog.Status.SENT
            log.sent_at = timezone.now()
            log.save(update_fields=['status', 'sent_at'])

            # Mark booking as email-confirmed
            log.booking.confirmation_email_sent    = True
            log.booking.confirmation_email_sent_at = timezone.now()
            log.booking.save(update_fields=['confirmation_email_sent', 'confirmation_email_sent_at'])

            logger.info('Confirmation email sent to %s for booking %d.', log.recipient, log.booking_id)

        except Exception as exc:
            log.retry_count += 1
            log.last_error   = str(exc)[:500]
            if log.retry_count >= log.max_retries:
                log.status = EmailLog.Status.FAILED
                logger.error(
                    'Email to %s permanently failed after %d retries: %s',
                    log.recipient, log.retry_count, exc
                )
            log.save(update_fields=['retry_count', 'last_error', 'status'])


def _worker_loop(interval_seconds=60):
    """Infinite loop — runs as daemon thread."""
    while True:
        time.sleep(interval_seconds)
        try:
            _deliver_pending_emails()
        except Exception as exc:
            logger.error('Email worker loop error: %s', exc)


def start_email_worker():
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(
        target=_worker_loop,
        daemon=True,
        name='email-confirmation-worker',
    )
    _worker_thread.start()
    logger.info('Email confirmation worker started.')
