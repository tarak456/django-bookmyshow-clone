import hashlib

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def populate_payment_idempotency_keys(apps, schema_editor):
    Payment = apps.get_model('movies', 'Payment')
    for payment in Payment.objects.all().iterator():
        seat_ids = payment.seat_ids or []
        raw = f'{payment.user_id}:{payment.theater_id}:{".".join(map(str, sorted(seat_ids)))}:{payment.pk}'
        payment.idempotency_key = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        payment.save(update_fields=['idempotency_key'])


def deduplicate_legacy_seat_numbers(apps, schema_editor):
    Seat = apps.get_model('movies', 'Seat')
    seen = set()
    for seat in Seat.objects.order_by('theater_id', 'seat_number', 'id').iterator():
        key = (seat.theater_id, seat.seat_number)
        if key not in seen:
            seen.add(key)
            continue

        base = seat.seat_number[:6]
        candidate = f'{base}-{seat.pk}'
        while Seat.objects.filter(theater_id=seat.theater_id, seat_number=candidate).exists():
            candidate = f'{base}-{seat.pk}-x'
        seat.seat_number = candidate[:10]
        seat.save(update_fields=['seat_number'])
        seen.add((seat.theater_id, seat.seat_number))


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('movies', '0008_auto_20260514_1720'),
    ]

    operations = [
        migrations.AddField(
            model_name='seat',
            name='locked_by',
            field=models.ForeignKey(
                blank=True,
                help_text='User who currently holds the temporary payment lock.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='locked_seats',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='seat',
            name='locked_until',
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text='Seat lock expiry. Expired locks are treated as available.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='idempotency_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Stable key for one user/theater/seat-set payment attempt.',
                max_length=128,
                null=True,
            ),
        ),
        migrations.RunPython(populate_payment_idempotency_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='payment',
            name='idempotency_key',
            field=models.CharField(
                db_index=True,
                help_text='Stable key for one user/theater/seat-set payment attempt.',
                max_length=128,
                unique=True,
            ),
        ),
        migrations.RunPython(deduplicate_legacy_seat_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='seat',
            constraint=models.UniqueConstraint(
                fields=('theater', 'seat_number'),
                name='unique_seat_number_per_theater',
            ),
        ),
        migrations.AddIndex(
            model_name='seat',
            index=models.Index(fields=['theater', 'is_booked'], name='seat_theater_booked_idx'),
        ),
        migrations.AddIndex(
            model_name='seat',
            index=models.Index(fields=['theater', 'locked_until'], name='seat_theater_lock_idx'),
        ),
        migrations.AddIndex(
            model_name='seat',
            index=models.Index(fields=['locked_by', 'locked_until'], name='seat_user_lock_idx'),
        ),
    ]
