"""
Background cleanup scheduler — zero external dependencies.

Uses Python's built-in threading module to run a daemon thread that
sweeps expired SeatReservation rows every 30 seconds.

A daemon thread is automatically killed when the main Django process
exits, so no explicit shutdown is needed.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

_thread = None  # module-level guard — prevents double-start within a process


def release_expired_reservations():
    """Delete every SeatReservation whose expiry time has passed."""
    try:
        from django.utils import timezone
        from .models import SeatReservation
        deleted_count, _ = SeatReservation.objects.filter(
            expires_at__lt=timezone.now()
        ).delete()
        if deleted_count:
            logger.info('Auto-released %d expired seat reservation(s).', deleted_count)
    except Exception as e:
        logger.error('Error releasing expired reservations: %s', e)


def _run_loop(interval_seconds):
    """Infinite loop that calls the cleanup job every interval_seconds."""
    while True:
        time.sleep(interval_seconds)
        release_expired_reservations()


def start_scheduler(interval_seconds=30):
    """
    Start the background cleanup thread if not already running.
    Called from MoviesConfig.ready().
    """
    global _thread
    if _thread is not None and _thread.is_alive():
        return  # already running in this process

    _thread = threading.Thread(
        target=_run_loop,
        args=(interval_seconds,),
        daemon=True,   # dies automatically when Django process exits
        name='seat-reservation-cleanup',
    )
    _thread.start()
    logger.info(
        'Seat reservation cleanup thread started (interval: %ds).', interval_seconds
    )
