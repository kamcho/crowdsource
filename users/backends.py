from django.contrib.auth.backends import ModelBackend

from .models import User


class PhonePasswordBackend(ModelBackend):
    """Authenticate with phone number and password."""

    def authenticate(self, request, phone=None, password=None, **kwargs):
        if phone is None or password is None:
            return None

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
