import re

from django.db import migrations, models
import movies.models


def normalize_trailer_ids(apps, schema_editor):
    Movie = apps.get_model('movies', 'Movie')
    for movie in Movie.objects.exclude(trailer_video_id__isnull=True).exclude(trailer_video_id=''):
        value = movie.trailer_video_id or ''
        match = re.search(r'youtu\.be/([\w\-]{11})', value) or re.search(r'[?&]v=([\w\-]{11})', value)
        if match:
            movie.trailer_video_id = match.group(1)
            movie.save(update_fields=['trailer_video_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0010_movie_filters'),
    ]

    operations = [
        migrations.RenameField(
            model_name='movie',
            old_name='trailer_url',
            new_name='trailer_video_id',
        ),
        migrations.RunPython(normalize_trailer_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='movie',
            name='trailer_video_id',
            field=models.CharField(
                blank=True,
                help_text='Paste a YouTube URL or 11-character video ID. Only the ID is stored.',
                max_length=11,
                null=True,
                validators=[movies.models.validate_youtube_url_or_id],
            ),
        ),
    ]
