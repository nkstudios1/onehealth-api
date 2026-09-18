from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone
from import_export.admin import ImportExportModelAdmin
from users.admin import RoleAwareModelAdmin
from users.models import User

from .models import MedicalRecord


def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff(user):
    return getattr(user, "staff_profile", None)


@admin.register(MedicalRecord)
class MedicalRecordAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = (
        "id",
        "patient",
        "entry_type",
        "verification_status",
        "hospital",
        "visit",
        "created_by_staff",
        "verified_by_staff",
        "created_at",
    )
    list_filter = ("verification_status", "entry_type", "hospital")
    search_fields = (
        "id",
        "patient__full_name",
        "entry_type",
        "description",
    )
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)

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

    def has_view_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if obj is None:
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return obj.patient.user_id == request.user.id
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            return bool(hospital and obj.hospital_id == hospital.id)
        return False

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def save_model(self, request, obj, form, change):
        if change and not is_platform_admin(request.user):
            raise ValidationError("Medical records are append-only and cannot be edited.")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        if not is_platform_admin(request.user):
            raise ValidationError("Medical records are append-only and cannot be deleted.")
        super().delete_model(request, obj)

    @admin.action(description="Verify selected medical record(s)")
    def verify_selected(self, request, queryset):
        staff = current_staff(request.user)
        if not (is_platform_admin(request.user) or (staff and staff.role == "doctor")):
            raise PermissionDenied("Only doctors or platform admins can verify medical records.")
        for record in queryset:
            if record.hospital_id != staff.hospital_id:
                raise PermissionDenied("You can only verify records for your hospital.")
            record.verified_by_staff = staff
            record.verification_status = MedicalRecord.VerificationStatus.DOCTOR_VERIFIED
            type(record).objects.filter(pk=record.pk).update(
                verification_status=record.verification_status,
                verified_by_staff_id=record.verified_by_staff_id,
            )
        self.message_user(request, f"{queryset.count()} record(s) marked as doctor-verified.")
