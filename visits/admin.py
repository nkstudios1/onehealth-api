from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from users.admin import RoleAwareModelAdmin, hospital_for_user
from users.models import Hospital, HospitalStaffProfile, PatientProfile, User

from .models import Medication, Vital, Visit


def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff(user):
    return getattr(user, "staff_profile", None)


@admin.register(Visit)
class VisitAdmin(RoleAwareModelAdmin):
    list_display = ("id", "patient", "hospital", "status", "admitted_at", "checked_out_at", "created_by_staff")
    list_filter = ("status", "hospital")
    search_fields = ("id", "patient__full_name", "hospital__name", "created_by_staff__full_name")
    readonly_fields = ("id", "admitted_at", "checked_out_at", "checkout_requested_by_patient_at")
    ordering = ("-admitted_at",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            if "patient" in form.base_fields:
                form.base_fields["patient"].queryset = PatientProfile.objects.filter(user=request.user)
            if "hospital" in form.base_fields:
                form.base_fields["hospital"].queryset = Hospital.objects.filter(visits__patient__user=request.user).distinct()
            if "created_by_staff" in form.base_fields:
                form.base_fields["created_by_staff"].queryset = HospitalStaffProfile.objects.none()
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = hospital_for_user(request.user)
            if not hospital:
                return form
            if "patient" in form.base_fields:
                form.base_fields["patient"].queryset = PatientProfile.objects.filter(visits__hospital=hospital).distinct()
            if "hospital" in form.base_fields:
                form.base_fields["hospital"].queryset = Hospital.objects.filter(pk=hospital.id)
                form.base_fields["hospital"].initial = hospital.id
                form.base_fields["hospital"].disabled = True
            if "created_by_staff" in form.base_fields:
                form.base_fields["created_by_staff"].queryset = HospitalStaffProfile.objects.filter(hospital=hospital)
                form.base_fields["created_by_staff"].initial = staff.pk if staff else None
                form.base_fields["created_by_staff"].disabled = True
        return form

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
            hospital = hospital_for_user(request.user)
            return bool(hospital and obj.hospital_id == hospital.id)
        return False

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return False
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        hospital = hospital_for_user(request.user)
        if not hospital:
            return False
        if obj is None:
            return True
        return obj.hospital_id == hospital.id

    def has_add_permission(self, request):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        return bool(hospital_for_user(request.user))

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def save_model(self, request, obj, form, change):
        if is_platform_admin(request.user):
            super().save_model(request, obj, form, change)
            return
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            raise PermissionDenied("Only hospital staff can create or update visits.")
        hospital = hospital_for_user(request.user)
        staff = current_staff(request.user)
        if not hospital or not staff:
            raise PermissionDenied("You must belong to a hospital to manage visits.")
        obj.hospital = hospital
        obj.created_by_staff = staff
        super().save_model(request, obj, form, change)

    @admin.action(description="Start visit")
    def start_visit(self, request, queryset):
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN) and not is_platform_admin(request.user):
            raise PermissionDenied("Only hospital staff can start visits.")
        updated = queryset.filter(status=Visit.Status.CHECKED_OUT).count()
        queryset.update(status=Visit.Status.ACTIVE, checked_out_at=None)
        self.message_user(request, f"{updated} visit(s) restarted.")

    @admin.action(description="Checkout visit")
    def checkout_visit(self, request, queryset):
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN) and not is_platform_admin(request.user):
            raise PermissionDenied("Only hospital staff can check out visits.")
        queryset.update(status=Visit.Status.CHECKED_OUT, checked_out_at=timezone.now())
        self.message_user(request, f"{queryset.count()} visit(s) checked out.")


@admin.register(Vital)
class VitalAdmin(RoleAwareModelAdmin):
    list_display = ("id", "visit", "recorded_by_staff", "recorded_at", "heart_rate", "oxygen_saturation")
    list_filter = ("recorded_by_staff__hospital",)
    search_fields = ("id", "visit__patient__full_name", "recorded_by_staff__full_name")
    readonly_fields = ("id", "recorded_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(visit__patient__user=request.user)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return qs.none()
            return qs.filter(recorded_by_staff__hospital=hospital)
        return qs.none()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = hospital_for_user(request.user)
            if not hospital:
                return form
            if "visit" in form.base_fields:
                form.base_fields["visit"].queryset = Visit.objects.filter(hospital=hospital)
            if "recorded_by_staff" in form.base_fields:
                form.base_fields["recorded_by_staff"].queryset = HospitalStaffProfile.objects.filter(hospital=hospital)
                form.base_fields["recorded_by_staff"].initial = staff.pk if staff else None
                form.base_fields["recorded_by_staff"].disabled = True
        return form

    def has_add_permission(self, request):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        return bool(hospital_for_user(request.user))

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return False
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        hospital = hospital_for_user(request.user)
        if not hospital:
            return False
        if obj is None:
            return True
        return obj.visit.hospital_id == hospital.id

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def save_model(self, request, obj, form, change):
        if is_platform_admin(request.user):
            super().save_model(request, obj, form, change)
            return
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            raise PermissionDenied("Only hospital staff can create or update vital records.")
        staff = current_staff(request.user)
        hospital = hospital_for_user(request.user)
        if not hospital or not staff:
            raise PermissionDenied("You must belong to a hospital to manage vital records.")
        if obj.visit and obj.visit.hospital_id != hospital.id:
            raise PermissionDenied("You can only add or edit vitals for patients in your hospital.")
        obj.recorded_by_staff = staff
        if change:
            type(obj).objects.filter(pk=obj.pk).update(
                visit_id=obj.visit_id,
                recorded_by_staff_id=obj.recorded_by_staff_id,
                recorded_at=obj.recorded_at,
                blood_pressure_systolic=obj.blood_pressure_systolic,
                blood_pressure_diastolic=obj.blood_pressure_diastolic,
                heart_rate=obj.heart_rate,
                temperature_c=obj.temperature_c,
                respiratory_rate=obj.respiratory_rate,
                oxygen_saturation=obj.oxygen_saturation,
                weight_kg=obj.weight_kg,
                height_cm=obj.height_cm,
                notes=obj.notes,
            )
            return
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        if not is_platform_admin(request.user):
            raise ValidationError("Vitals are append-only and cannot be deleted.")
        super().delete_model(request, obj)


@admin.register(Medication)
class MedicationAdmin(RoleAwareModelAdmin):
    list_display = ("id", "patient", "medication", "dose", "frequency", "status", "prescribed_by_staff", "created_at")
    list_filter = ("status", "prescribed_by_staff__hospital")
    search_fields = ("id", "patient__full_name", "medication", "reason")
    readonly_fields = ("id", "created_at")

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
            return qs.filter(prescribed_by_staff__hospital=hospital)
        return qs.none()

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def save_model(self, request, obj, form, change):
        if change and not is_platform_admin(request.user):
            raise ValidationError("Medication records are append-only and cannot be edited.")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        if not is_platform_admin(request.user):
            raise ValidationError("Medication records are append-only and cannot be deleted.")
        super().delete_model(request, obj)
