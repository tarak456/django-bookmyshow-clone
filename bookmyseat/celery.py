import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bookmyseat.settings')

try:
    from celery import Celery
except ImportError:
    app = None
else:
    app = Celery('bookmyseat')
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()
