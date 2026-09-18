from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrPhoneBackend(ModelBackend):
    """Allow Django admin logins with either email or phone number."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        username = username.strip()
        user_model = get_user_model()

        try:
            user = user_model.objects.filter(
                Q(email__iexact=username) | Q(phone_number=username)
            ).order_by("id").first()
        except user_model.DoesNotExist:
            return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
