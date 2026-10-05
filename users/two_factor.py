"""TOTP authenticator-app two-factor authentication."""

import base64
import io
import pyotp
import qrcode
from django.conf import settings
from django.core.cache import cache

ATTEMPT_CACHE_PREFIX = '2fa:attempt:'
DEFAULT_MAX_VERIFY_ATTEMPTS = 5
DEFAULT_ATTEMPT_WINDOW_SECONDS = 15 * 60

SESSION_PENDING_USER_ID = 'pending_2fa_user_id'
SESSION_PENDING_BACKEND = 'pending_2fa_backend'
SESSION_PENDING_NEXT = 'pending_2fa_next'
SESSION_SETUP_SECRET = '2fa_setup_secret'
SESSION_PENDING_ENABLE = '2fa_pending_enable'
SESSION_PENDING_DISABLE = '2fa_pending_disable'


def _max_verify_attempts():
    return int(getattr(settings, 'TWO_FACTOR_MAX_VERIFY_ATTEMPTS', DEFAULT_MAX_VERIFY_ATTEMPTS))


def _attempt_window():
    return int(getattr(settings, 'TWO_FACTOR_ATTEMPT_WINDOW_SECONDS', DEFAULT_ATTEMPT_WINDOW_SECONDS))


def _attempt_cache_key(user_id, purpose):
    return f'{ATTEMPT_CACHE_PREFIX}{purpose}:{user_id}'


def _totp_issuer():
    return getattr(settings, 'TWO_FACTOR_ISSUER', None) or getattr(settings, 'SITE_NAME', 'CrowdSource')


def generate_totp_secret():
    return pyotp.random_base32()


def account_label(user):
    if user.email:
        return user.email
    if user.phone:
        return str(user.phone)
    return f'user-{user.pk}'


def provisioning_uri(secret, user):
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_label(user),
        issuer_name=_totp_issuer(),
    )


def qr_code_data_url(uri):
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def normalize_code(submitted_code):
    return (submitted_code or '').strip().replace(' ', '')


def _record_failed_attempt(user_id, purpose):
    key = _attempt_cache_key(user_id, purpose)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, _attempt_window())
    if attempts >= _max_verify_attempts():
        return False, 'Too many incorrect attempts. Wait a few minutes and try again.'
    return False, 'Incorrect code. Open your authenticator app and try again.'


def _clear_attempts(user_id, purpose):
    cache.delete(_attempt_cache_key(user_id, purpose))


def verify_totp_secret(secret, submitted_code, user_id, purpose):
    if not secret:
        return False, 'Authenticator is not set up for this account.'

    code = normalize_code(submitted_code)
    if not code.isdigit() or len(code) != 6:
        return False, 'Enter the 6-digit code from your authenticator app.'

    if cache.get(_attempt_cache_key(user_id, purpose), 0) >= _max_verify_attempts():
        return False, 'Too many incorrect attempts. Wait a few minutes and try again.'

    totp = pyotp.TOTP(secret)
    if totp.verify(code, valid_window=1):
        _clear_attempts(user_id, purpose)
        return True, ''

    return _record_failed_attempt(user_id, purpose)


def verify_user_totp(user, submitted_code, purpose='login'):
    if not user.two_factor_enabled or not user.totp_secret:
        return False, 'Two-factor authentication is not enabled for this account.'
    return verify_totp_secret(user.totp_secret, submitted_code, user.pk, purpose)


def begin_totp_setup(request, user):
    secret = generate_totp_secret()
    request.session[SESSION_SETUP_SECRET] = secret
    request.session[SESSION_PENDING_ENABLE] = str(user.pk)
    return secret


def get_pending_setup_secret(request, user):
    if request.session.get(SESSION_PENDING_ENABLE) != str(user.pk):
        return ''
    return request.session.get(SESSION_SETUP_SECRET) or ''


def clear_totp_setup(request):
    request.session.pop(SESSION_SETUP_SECRET, None)
    request.session.pop(SESSION_PENDING_ENABLE, None)


def activate_totp(user, secret):
    user.totp_secret = secret
    user.two_factor_enabled = True
    user.save(update_fields=['totp_secret', 'two_factor_enabled', 'updated_at'])


def deactivate_totp(user):
    user.totp_secret = ''
    user.two_factor_enabled = False
    user.save(update_fields=['totp_secret', 'two_factor_enabled', 'updated_at'])


def set_pending_login(request, user, backend, next_url=''):
    request.session[SESSION_PENDING_USER_ID] = str(user.pk)
    request.session[SESSION_PENDING_BACKEND] = backend
    if next_url:
        request.session[SESSION_PENDING_NEXT] = next_url
    else:
        request.session.pop(SESSION_PENDING_NEXT, None)


def get_pending_login(request):
    user_id = request.session.get(SESSION_PENDING_USER_ID)
    if not user_id:
        return None, '', ''
    from .models import User

    try:
        user = User.objects.get(pk=int(user_id), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        clear_pending_login(request)
        return None, '', ''
    backend = request.session.get(SESSION_PENDING_BACKEND) or 'django.contrib.auth.backends.ModelBackend'
    next_url = request.session.get(SESSION_PENDING_NEXT) or ''
    return user, backend, next_url


def clear_pending_login(request):
    for key in (SESSION_PENDING_USER_ID, SESSION_PENDING_BACKEND, SESSION_PENDING_NEXT):
        request.session.pop(key, None)
