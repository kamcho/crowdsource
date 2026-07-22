from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .models import User


class GoogleAuthError(Exception):
    pass


def get_google_client_ids():
    return list(getattr(settings, 'GOOGLE_CLIENT_IDS', []) or [])


def verify_google_credential(credential):
    client_ids = get_google_client_ids()
    if not client_ids:
        raise GoogleAuthError('Google Sign-In is not configured.')

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_ids[0] if len(client_ids) == 1 else client_ids,
        )
    except ValueError as exc:
        raise GoogleAuthError('Invalid Google sign-in token.') from exc

    audience = idinfo.get('aud')
    if audience not in client_ids:
        raise GoogleAuthError('Google token audience mismatch.')

    if not idinfo.get('email_verified'):
        raise GoogleAuthError('Google email address is not verified.')

    return idinfo


def get_or_create_user_from_google(idinfo):
    google_id = idinfo['sub']
    email = (idinfo.get('email') or '').strip()
    first_name = (idinfo.get('given_name') or '').strip()
    last_name = (idinfo.get('family_name') or '').strip()

    user = User.objects.filter(google_id=google_id).first()
    if user:
        return user, False

    if email:
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if user.google_id and user.google_id != google_id:
                raise GoogleAuthError('This email is linked to a different Google account.')
            user.google_id = google_id
            if not user.first_name and first_name:
                user.first_name = first_name
            if not user.last_name and last_name:
                user.last_name = last_name
            user.save(update_fields=['google_id', 'first_name', 'last_name', 'updated_at'])
            return user, False

    user = User(
        google_id=google_id,
        email=email or None,
        first_name=first_name or 'Google',
        last_name=last_name or 'User',
    )
    user.set_unusable_password()
    user.save()
    return user, True
