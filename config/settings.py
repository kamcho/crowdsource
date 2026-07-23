"""
Django settings for config project.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(BASE_DIR / '.env', override=True)


def _env_bool(name, default='false'):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-1qpvj2gtd3r0fiigc(*q4jicugy-%u#&si(6swkk5cl%afv5*9',
)

DEBUG = _env_bool('DEBUG', 'true')

ALLOWED_HOSTS = _env_list(
    'ALLOWED_HOSTS',
    'localhost,127.0.0.1' if DEBUG else '',
)
if DEBUG and 'testserver' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('testserver')

CSRF_TRUSTED_ORIGINS = [
    'https://*.ngrok-free.app',
    'https://*.ngrok-free.dev',
    'https://*.ngrok.io',
    'http://localhost:8001',
    'http://127.0.0.1:8001',
]
CSRF_TRUSTED_ORIGINS += _env_list('CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'phonenumber_field',
    'users',
    'core',
    'home',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.cart_summary',
                'core.context_processors.wishlist_summary',
                'core.context_processors.admin_sidebar',
                'core.context_processors.currency',
                'core.context_processors.category_nav',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

if os.environ.get('DB_ENGINE', 'sqlite').strip().lower() in ('postgres', 'postgresql'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'crowdsource'),
            'USER': os.environ.get('DB_USER', 'crowdsource'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_USER_MODEL = 'users.User'

AUTHENTICATION_BACKENDS = [
    'users.backends.PhonePasswordBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'users:signin'
LOGIN_REDIRECT_URL = 'users:profile'
LOGOUT_REDIRECT_URL = 'home:landing'

SECURE_CROSS_ORIGIN_OPENER_POLICY = os.environ.get(
    'SECURE_CROSS_ORIGIN_OPENER_POLICY',
    'same-origin-allow-popups',
)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', 'false')
    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', 'true')
    CSRF_COOKIE_SECURE = _env_bool('CSRF_COOKIE_SECURE', 'true')
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'true')
    SECURE_HSTS_PRELOAD = _env_bool('SECURE_HSTS_PRELOAD', 'true')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# Google Sign-In (Google Identity Services)
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_IDS = [
    item.strip() for item in GOOGLE_CLIENT_ID.split(',') if item.strip()
]

PHONENUMBER_DEFAULT_REGION = 'KE'

# Payments — demo simulates instantly; mpesa uses Daraja STK push.
PAYMENT_PROVIDER = os.environ.get('PAYMENT_PROVIDER', 'demo')
USD_TO_KES_RATE = os.environ.get('USD_TO_KES_RATE', '135')

# M-Pesa Daraja (Paybill 4161900 — same credentials as Excel project)
MPESA_ENVIRONMENT = os.environ.get('MPESA_ENVIRONMENT', 'production')
MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY', '').strip()
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', '').strip()
MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY', '').strip()
MPESA_SHORTCODE = os.environ.get('MPESA_SHORTCODE', '4161900').strip()
MPESA_CALLBACK_BASE_URL = os.environ.get('MPESA_CALLBACK_BASE_URL', '').strip()

# Notifications — console logging in development; TextSMS in production.
NOTIFICATION_BACKEND = os.environ.get('NOTIFICATION_BACKEND', 'console')
NOTIFICATION_SMS_ENABLED = os.environ.get('NOTIFICATION_SMS_ENABLED', 'true').lower() in ('1', 'true', 'yes')
NOTIFICATION_EMAIL_ENABLED = os.environ.get('NOTIFICATION_EMAIL_ENABLED', 'true').lower() in ('1', 'true', 'yes')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@crowdsource.local')

# TextSMS (textsms.co.ke) — same provider as Excel / Soma Smart projects
TEXTSMS_ENABLED = os.environ.get('TEXTSMS_ENABLED', 'false').lower() in ('1', 'true', 'yes')
TEXTSMS_API_KEY = os.environ.get('TEXTSMS_API_KEY', '').strip()
TEXTSMS_PARTNER_ID = os.environ.get('TEXTSMS_PARTNER_ID', '').strip()
TEXTSMS_SHORTCODE = os.environ.get('TEXTSMS_SHORTCODE', '').strip()

# Legacy / alternate SMS providers (not used when NOTIFICATION_BACKEND=textsms)
AFRICASTALKING_USERNAME = os.environ.get('AFRICASTALKING_USERNAME', '').strip()
AFRICASTALKING_API_KEY = os.environ.get('AFRICASTALKING_API_KEY', '').strip()
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '').strip()

# Email
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '').strip()

# OpenAI — product import wizard
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini').strip()

EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', 'true')
