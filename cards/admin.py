from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from users.admin import RoleAwareModelAdmin
from users.models import User
from import_export.admin import ImportExportModelAdmin
from .models import PatientCard


def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff(user):
    return getattr(user, "staff_profile", None)


@admin.register(PatientCard)
class PatientCardAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ("card_reference", "patient", "status", "issued_at", "renewed_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("card_reference", "patient__full_name", "patient__user__email")
    readonly_fields = ("id", "patient", "card_reference", "issued_at", "renewed_at", "expires_at", "status")
    ordering = ("-issued_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(patient__user=request.user)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return qs.none()
            return qs.filter(patient__visits__hospital=hospital).distinct()
        return qs.none()

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    @admin.action(description="Renew selected card(s)")
    def renew_card(self, request, queryset):
        for card in queryset:
            card.renew()
        self.message_user(request, f"{queryset.count()} card(s) renewed.")

    @admin.action(description="Revoke selected card(s)")
    def revoke_card(self, request, queryset):
        for card in queryset:
            card.revoke()
        self.message_user(request, f"{queryset.count()} card(s) revoked.")
