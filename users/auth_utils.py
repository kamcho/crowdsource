"""Shared authentication helpers."""

from phonenumber_field.phonenumber import to_python as parse_phone_number


def user_needs_phone_link(user):
    """Google-signed users should link a phone number for M-Pesa and account recovery."""
    if not user.is_authenticated:
        return False
    return bool(user.google_id) and not user.phone


def is_google_passwordless_account(user):
    """Account created or primarily used via Google without a local password."""
    if not user:
        return False
    return bool(user.google_id) and not user.has_usable_password()


def lookup_user_by_login(login_raw):
    """Resolve a user from a phone number or email address entered at sign-in."""
    value = (login_raw or '').strip()
    if not value:
        return None
    if '@' in value:
        from .models import User

        return User.objects.filter(email__iexact=value).first()
    phone = parse_phone_number(value, region='KE')
    if not phone or not phone.is_valid():
        return None
    from .models import User

    return User.objects.filter(phone=phone).first()


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')
