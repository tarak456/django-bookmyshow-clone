import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import Booking, Payment
from .services import release_expired_locks

logger = logging.getLogger(__name__)


try:
    from celery import shared_task
except ImportError:
    class _SyncTask:
        def __init__(self, fn):
            self.fn = fn
            self.__name__ = fn.__name__

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

        def delay(self, *args, **kwargs):
            logger.warning('Celery is not installed; running %s synchronously.', self.__name__)
            return self.fn(*args, **kwargs)

    def shared_task(*decorator_args, **decorator_kwargs):
        def decorate(fn):
            return _SyncTask(fn)
        return decorate


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def release_expired_seat_locks(self):
    """Periodic task: frees locks abandoned after browser close/network failure."""
    try:
        return release_expired_locks()
    except Exception as exc:
        logger.exception('Expired seat-lock cleanup failed')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_booking_confirmation_email(self, payment_id):
    """
    Send booking confirmation after successful payment.

    This runs outside the request/response path, so slow SMTP does not make
    the payment callback feel slow or cause gateway retries.
    """
    try:
        payment = (
            Payment.objects.select_related('user', 'theater__movie')
            .get(pk=payment_id, status=Payment.Status.PAID)
        )
        bookings = (
            Booking.objects.filter(
                user=payment.user,
                theater=payment.theater,
                seat_id__in=payment.seat_ids,
            )
            .select_related('seat', 'movie', 'theater')
            .order_by('seat__seat_number')
        )

        if not payment.user.email:
            logger.info('Skipping confirmation email for payment %s: user has no email.', payment.pk)
            return 'missing-email'

        context = {'payment': payment, 'bookings': bookings}
        subject = f'Booking confirmed: {payment.theater.movie.name}'
        text_body = render_to_string('emails/booking_confirmation.txt', context)
        html_body = render_to_string('emails/booking_confirmation.html', context)

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[payment.user.email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send()
        return 'sent'
    except Exception as exc:
        logger.exception('Booking confirmation email failed for payment_id=%s', payment_id)
        raise self.retry(exc=exc)
