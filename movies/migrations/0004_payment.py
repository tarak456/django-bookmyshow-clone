import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0003_seatreservation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('booking_ref', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ('seat_ids', models.JSONField(help_text='List of Seat PKs included in this payment.')),
                ('amount_paise', models.PositiveIntegerField(help_text='Total amount in paise. 1 INR = 100 paise.')),
                ('currency', models.CharField(default='INR', max_length=8)),
                ('razorpay_order_id', models.CharField(max_length=100, unique=True)),
                ('razorpay_payment_id', models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ('status', models.CharField(
                    choices=[('created', 'Order Created'), ('paid', 'Paid'), ('failed', 'Failed'), ('cancelled', 'Cancelled')],
                    default='created', max_length=20,
                )),
                ('failure_reason', models.TextField(blank=True)),
                ('webhook_event_id', models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ('webhook_received_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to=settings.AUTH_USER_MODEL)),
                ('theater', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='movies.theater')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['razorpay_order_id'], name='movies_paym_razorpa_idx'),
                    models.Index(fields=['status', 'created_at'], name='movies_paym_status_idx'),
                ],
            },
        ),
    ]
