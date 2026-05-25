from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0002_movie_trailer_url'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SeatReservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reserved_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('seat', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reservation',
                    to='movies.seat',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL,
                )),
                ('theater', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='movies.theater',
                )),
            ],
        ),
        migrations.AddIndex(
            model_name='seatreservation',
            index=models.Index(fields=['expires_at'], name='movies_reservation_expires_idx'),
        ),
    ]
