from django.contrib import admin

from users.admin import RoleAwareModelAdmin
from users.models import User

from .models import AuditLog
from import_export.admin import ImportExportModelAdmin

def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff(user):
    return getattr(user, "staff_profile", None)


@admin.register(AuditLog)
class AuditLogAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ["created_at", "action", "actor", "hospital", "patient", "target_type", "target_id"]
    list_filter = ["action", "hospital", "created_at"]
    search_fields = ["action", "target_type", "target_id", "actor__email"]
    readonly_fields = ["id", "actor", "hospital", "patient", "action", "target_type", "target_id", "metadata", "ip_address", "created_at"]
    ordering = ["-created_at"]

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
            return qs.filter(hospital=hospital)
        return qs.none()

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)
