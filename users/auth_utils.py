"""Shared authentication helpers."""


def user_needs_phone_link(user):
    """Google-signed users should link a phone and password for backup sign-in."""
    if not user.is_authenticated:
        return False
    return bool(user.google_id) and not user.phone


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')
