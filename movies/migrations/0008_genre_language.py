"""
Migration 0008 — Genre, Language, and Movie M2M fields (Tasks 5 & 6)

Replaces the auto-generated 0008_auto_20260514_1720 which tried to
remove indexes that don't exist in SQLite, causing OperationalError.

This migration ONLY adds new tables and fields — nothing is dropped.
Safe to apply on any DB that has 0007 (analytics indexes) applied.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0007_analytics_indexes'),
    ]

    operations = [
        # ── Genre ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Genre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=60, unique=True)),
                ('slug', models.SlugField(unique=True, help_text='Used in filter URLs, e.g. action')),
            ],
            options={'ordering': ['name']},
        ),
        # ── Language ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Language',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=60, unique=True)),
                ('code', models.CharField(max_length=8, unique=True, help_text='ISO 639-1 code, e.g. hi, en, te')),
            ],
            options={'ordering': ['name']},
        ),
        # ── M2M on Movie ────────────────────────────────────────────────────
        migrations.AddField(
            model_name='movie',
            name='genres',
            field=models.ManyToManyField(
                'movies.Genre', blank=True, related_name='movies',
                help_text='Select one or more genres.',
            ),
        ),
        migrations.AddField(
            model_name='movie',
            name='languages',
            field=models.ManyToManyField(
                'movies.Language', blank=True, related_name='movies',
                help_text='Available audio/subtitle languages.',
            ),
        ),
        # ── Indexes for filter queries ──────────────────────────────────────
        migrations.AddIndex(
            model_name='genre',
            index=models.Index(fields=['slug'], name='genre_slug_idx'),
        ),
        migrations.AddIndex(
            model_name='language',
            index=models.Index(fields=['code'], name='language_code_idx'),
        ),
    ]
