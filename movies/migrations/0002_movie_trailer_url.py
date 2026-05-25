from django.db import migrations, models
import movies.models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='trailer_url',
            field=models.URLField(
                blank=True,
                null=True,
                validators=[movies.models.validate_youtube_url],
                help_text=(
                    'YouTube trailer URL, e.g. '
                    'https://www.youtube.com/watch?v=XXXXXXXXXXX'
                ),
            ),
        ),
    ]
