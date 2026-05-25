"""
bookmyseat/settings.py — unified dev + production settings
All secrets come from environment variables; safe to commit.
"""
import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Core ──────────────────────────────────────────────────────────────────────
SECRET_KEY    = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-change-me-in-prod')
DEBUG         = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

# Allow Render's auto-assigned domain automatically
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# ── Apps ──────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'users',
    'movies',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serves static files in production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF     = 'bookmyseat.urls'
WSGI_APPLICATION = 'bookmyseat.wsgi.application'
LOGIN_URL        = '/login/'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

# ── Database ──────────────────────────────────────────────────────────────────
_db_url = os.environ.get('DATABASE_URL')
DATABASES = (
    {'default': dj_database_url.parse(_db_url, conn_max_age=600)}
    if _db_url
    else {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
)

# ── Static & Media ────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'UTC'
USE_I18N      = True
USE_TZ        = True

# ── Security (production) ─────────────────────────────────────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER      = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT           = True
    SESSION_COOKIE_SECURE         = True
    CSRF_COOKIE_SECURE            = True

SESSION_COOKIE_HTTPONLY         = True
SESSION_COOKIE_AGE              = 3600

# ── Razorpay (Task 3) ─────────────────────────────────────────────────────────
RAZORPAY_KEY_ID         = os.environ.get('RAZORPAY_KEY_ID',         'rzp_test_REPLACE_ME')
RAZORPAY_KEY_SECRET     = os.environ.get('RAZORPAY_KEY_SECRET',     'REPLACE_ME')
RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
PRICE_PER_SEAT_PAISE    = int(os.environ.get('PRICE_PER_SEAT_PAISE', '15000'))

# ── Cache (Task 4) ────────────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bms-default',
    },
    'analytics': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bms-analytics',
    },
}

# ── Email (Task 6) ────────────────────────────────────────────────────────────
# Dev: prints to console. Prod: set EMAIL_BACKEND=smtp + SMTP env vars.
EMAIL_BACKEND       = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = os.environ.get('EMAIL_HOST',          'smtp.gmail.com')
EMAIL_PORT          = int(os.environ.get('EMAIL_PORT',      '587'))
EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS',       'True') == 'True'
EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER',     '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL  = os.environ.get('DEFAULT_FROM_EMAIL',  'noreply@bookmyseat.in')

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'}},
    'handlers':   {'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
    'loggers':    {'movies': {'handlers': ['console'], 'level': 'INFO', 'propagate': False}},
}
