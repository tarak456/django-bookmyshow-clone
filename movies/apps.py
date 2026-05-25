import os
import sys
from django.apps import AppConfig


class MoviesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'movies'

    def ready(self):
        # Skip scheduler during management commands (migrate, makemigrations,
        # collectstatic, shell, etc.) — only run when serving HTTP requests.
        management_commands = {
            'migrate', 'makemigrations', 'collectstatic',
            'shell', 'test', 'createsuperuser', 'changepassword',
        }
        if len(sys.argv) > 1 and sys.argv[1] in management_commands:
            return

        # In Django's dev server the app is loaded twice (reloader + worker).
        # RUN_MAIN=true is set only in the worker process, so we start the
        # scheduler there. In production (gunicorn) RUN_MAIN is unset — start.
        run_main = os.environ.get('RUN_MAIN')
        if run_main == 'true' or run_main is None:
            from .scheduler import start_scheduler
            start_scheduler()
