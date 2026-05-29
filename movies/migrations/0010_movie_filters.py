from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0009_seat_locks_payment_idempotency'),
    ]

    operations = [
        migrations.CreateModel(
            name='Genre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=80, unique=True)),
                ('slug', models.SlugField(max_length=90, unique=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='Language',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=80, unique=True)),
                ('code', models.CharField(max_length=16, unique=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.AddField(
            model_name='movie',
            name='genres',
            field=models.ManyToManyField(blank=True, related_name='movies', to='movies.genre'),
        ),
        migrations.AddField(
            model_name='movie',
            name='languages',
            field=models.ManyToManyField(blank=True, related_name='movies', to='movies.language'),
        ),
        migrations.AddIndex(
            model_name='movie',
            index=models.Index(fields=['name'], name='movie_name_idx'),
        ),
        migrations.AddIndex(
            model_name='movie',
            index=models.Index(fields=['rating'], name='movie_rating_idx'),
        ),
    ]
