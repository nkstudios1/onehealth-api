from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from .models import User, Hospital, HospitalStaffProfile, PatientProfile


def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff_profile(user):
    return getattr(user, "staff_profile", None)


def is_hospital_admin_user(user):
    if not user or not getattr(user, "is_active", False):
        return False
    if getattr(user, "user_type", None) == User.UserType.HOSPITAL_ADMIN:
        return True
    staff = current_staff_profile(user)
    return bool(staff and staff.role == HospitalStaffProfile.Role.ADMIN)


def hospital_for_user(user):
    if not user or not getattr(user, "is_active", False):
        return None
    staff = current_staff_profile(user)
    if staff:
        return staff.hospital
    if getattr(user, "user_type", None) == User.UserType.HOSPITAL_ADMIN:
        return Hospital.objects.filter(admin=user).first()
    return None


def site_has_permission(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_active)


admin.site.has_permission = site_has_permission


class RoleAwareModelAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        if is_platform_admin(request.user):
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_active)


@admin.register(User)
class UserAdmin(DjangoUserAdmin, RoleAwareModelAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "user_type", "is_active", "must_change_password", "date_joined"]
    list_filter = ["user_type", "is_active", "must_change_password"]
    search_fields = ["full_name", "email", "phone_number"]
    readonly_fields = ["password", "last_login", "date_joined"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Account info", {"fields": ("full_name", "user_type", "phone_number", "must_change_password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "user_type", "password1", "password2")}),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            for field_name in ("user_type", "is_active", "is_staff", "is_superuser", "must_change_password"):
                if field_name in form.base_fields:
                    form.base_fields[field_name].disabled = True
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff_profile(request.user)
            hospital = hospital_for_user(request.user)
            if not hospital and not staff:
                return form
            if not is_hospital_admin_user(request.user):
                for field_name in ("user_type", "is_active", "is_staff", "is_superuser", "must_change_password"):
                    if field_name in form.base_fields:
                        form.base_fields[field_name].disabled = True
            return form
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(pk=request.user.pk)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return qs.none()
            if is_hospital_admin_user(request.user):
                return qs.filter(
                    Q(pk=request.user.pk)
                    | Q(staff_profile__hospital=hospital)
                    | Q(patient_profile__visits__hospital=hospital)
                    | Q(patient_profile__medical_records__hospital=hospital)
                    | Q(patient_profile__access_requests__hospital=hospital)
                ).distinct()
            return qs.filter(pk=request.user.pk)
        return qs.none()

    def has_view_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if obj is None:
            return True
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if obj is None:
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return obj.pk == request.user.pk
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return False
            if obj.pk == request.user.pk:
                return True
            if is_hospital_admin_user(request.user):
                if getattr(obj, "staff_profile", None) is not None:
                    return obj.staff_profile.hospital_id == hospital.id
                if getattr(obj, "patient_profile", None) is not None:
                    return obj.patient_profile.visits.filter(hospital_id=hospital.id).exists() or obj.patient_profile.medical_records.filter(hospital_id=hospital.id).exists() or obj.patient_profile.access_requests.filter(hospital_id=hospital.id).exists()
                return False
            return False
        return False

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)


@admin.register(Hospital)
class HospitalAdmin(RoleAwareModelAdmin):
    list_display = ["name", "admin", "registration_number", "verification_status", "created_at"]
    list_filter = ["verification_status"]
    search_fields = ["name", "registration_number", "address"]
    readonly_fields = ["created_at", "verified_at"]
    ordering = ["name"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return qs.none()
            return qs.filter(pk=hospital.id)
        return qs.none()

    def has_view_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return False
            if obj is None:
                return True
            return obj.pk == hospital.id
        return False

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        hospital = hospital_for_user(request.user)
        if not hospital:
            return False
        if obj is None:
            return True
        return obj.pk == hospital.id

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    @admin.action(description="Verify hospital")
    def verify_hospital(self, request, queryset):
        if not is_platform_admin(request.user):
            raise PermissionDenied("Only platform admins may verify hospitals.")
        queryset.update(verification_status=Hospital.VerificationStatus.VERIFIED, verified_at=timezone.now())
        self.message_user(request, f"{queryset.count()} hospital(s) marked as verified.")

    @admin.action(description="Reject hospital")
    def reject_hospital(self, request, queryset):
        if not is_platform_admin(request.user):
            raise PermissionDenied("Only platform admins may reject hospitals.")
        queryset.update(verification_status=Hospital.VerificationStatus.REJECTED, verified_at=None)
        self.message_user(request, f"{queryset.count()} hospital(s) marked as rejected.")

    @admin.action(description="Suspend hospital")
    def suspend_hospital(self, request, queryset):
        if not is_platform_admin(request.user):
            raise PermissionDenied("Only platform admins may suspend hospitals.")
        queryset.update(verification_status=Hospital.VerificationStatus.SUSPENDED, verified_at=None)
        self.message_user(request, f"{queryset.count()} hospital(s) marked as suspended.")


@admin.register(PatientProfile)
class PatientProfileAdmin(RoleAwareModelAdmin):
    list_display = ["full_name", "user", "account_type", "date_of_birth", "created_at"]
    list_filter = ["account_type", "gender"]
    search_fields = ["full_name", "user__email", "user__phone_number"]
    readonly_fields = ["created_at"]
    ordering = ["full_name"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            if "user" in form.base_fields:
                form.base_fields["user"].queryset = User.objects.filter(pk=request.user.pk)
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return form
            if "user" in form.base_fields:
                form.base_fields["user"].queryset = User.objects.filter(
                    Q(patient_profile__visits__hospital=hospital)
                    | Q(patient_profile__medical_records__hospital=hospital)
                    | Q(patient_profile__access_requests__hospital=hospital)
                ).distinct()
            if "guardian" in form.base_fields:
                form.base_fields["guardian"].queryset = PatientProfile.objects.filter(
                    Q(visits__hospital=hospital)
                    | Q(medical_records__hospital=hospital)
                    | Q(access_requests__hospital=hospital)
                ).distinct()
            if "enrolled_by_staff" in form.base_fields:
                form.base_fields["enrolled_by_staff"].queryset = HospitalStaffProfile.objects.filter(hospital=hospital)
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(user=request.user)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return qs.none()
            return qs.filter(
                Q(visits__hospital=hospital)
                | Q(medical_records__hospital=hospital)
                | Q(access_requests__hospital=hospital)
            ).distinct()
        return qs.none()

    def has_view_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return obj is None or obj.user_id == request.user.id
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return False
            if obj is None:
                return True
            return (
                obj.visits.filter(hospital_id=hospital.id).exists()
                or obj.medical_records.filter(hospital_id=hospital.id).exists()
                or obj.access_requests.filter(hospital_id=hospital.id).exists()
            )
        return False

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return obj is None or obj.user_id == request.user.id
        return False

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)


@admin.register(HospitalStaffProfile)
class HospitalStaffProfileAdmin(RoleAwareModelAdmin):
    list_display = ["full_name", "hospital", "role", "professional_license_number", "created_at"]
    list_filter = ["role", "hospital"]
    search_fields = ["full_name", "user__email", "professional_license_number"]
    ordering = ["hospital__name", "full_name"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return form
        hospital = hospital_for_user(request.user)
        if not hospital:
            return form
        if "hospital" in form.base_fields:
            form.base_fields["hospital"].queryset = Hospital.objects.filter(pk=hospital.id)
        if "user" in form.base_fields:
            if is_hospital_admin_user(request.user):
                form.base_fields["user"].queryset = User.objects.filter(
                    Q(staff_profile__hospital=hospital)
                    | Q(pk=request.user.pk)
                ).distinct()
            else:
                form.base_fields["user"].queryset = User.objects.filter(pk=request.user.pk)
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.none()
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            hospital = hospital_for_user(request.user)
            if not hospital:
                return qs.none()
            if is_hospital_admin_user(request.user):
                return qs.filter(hospital=hospital)
            return qs.filter(user=request.user)
        return qs.none()

    def has_view_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        hospital = hospital_for_user(request.user)
        if not hospital:
            return False
        if obj is None:
            return True
        if is_hospital_admin_user(request.user):
            return obj.hospital_id == hospital.id
        return obj.user_id == request.user.id

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        hospital = hospital_for_user(request.user)
        if not hospital:
            return False
        if is_hospital_admin_user(request.user):
            if obj is None:
                return True
            return obj.hospital_id == hospital.id
        return obj is not None and obj.user_id == request.user.id

    def has_add_permission(self, request):
        return is_platform_admin(request.user) or is_hospital_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)
