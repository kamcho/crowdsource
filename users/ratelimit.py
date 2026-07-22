"""Cache-backed rate limiting for authentication endpoints."""

from django.core.cache import cache

from .auth_utils import get_client_ip


def _cache_incr(key, window_seconds):
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window_seconds)
        return 1


def is_rate_limited(key, limit, window_seconds):
    if limit <= 0:
        return False
    return _cache_incr(key, window_seconds) > limit


def check_rate_limits(limits):
    for key, limit, window in limits:
        if is_rate_limited(key, limit, window):
            return key
    return None


def throttle_login_attempt(request, phone=''):
    ip = get_client_ip(request)
    limits = [
        (f'rl:signin:ip:{ip}', 15, 15 * 60),
    ]
    if phone:
        limits.append((f'rl:signin:phone:{phone}', 8, 15 * 60))
    if check_rate_limits(limits):
        return 'Too many sign-in attempts. Please wait 15 minutes and try again.'
    return None


def throttle_google_auth(request):
    ip = get_client_ip(request)
    if check_rate_limits([(f'rl:google:ip:{ip}', 20, 15 * 60)]):
        return 'Too many Google sign-in attempts. Please wait and try again.'
    return None
