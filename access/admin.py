from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from users.admin import RoleAwareModelAdmin
from users.models import User, HospitalStaffProfile
from import_export.admin import ImportExportModelAdmin
from .models import AccessGrant, AccessRequest, EmergencyContact, EmergencyEscalation


def is_platform_admin(user):
    return bool(user and user.is_active and (user.is_superuser or user.user_type == User.UserType.PLATFORM_ADMIN))


def current_staff(user):
    return getattr(user, "staff_profile", None)


@admin.register(EmergencyContact)
class EmergencyContactAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ("full_name", "patient", "relationship", "phone_number", "priority_order", "is_active", "created_at")
    list_filter = ("is_active", "patient__account_type")
    search_fields = ("full_name", "patient__full_name", "phone_number", "email")
    readonly_fields = ("id", "response_token", "created_at")
    ordering = ("-created_at",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            if "patient" in form.base_fields:
                form.base_fields["patient"].queryset = obj.patient.__class__.objects.filter(user=request.user) if obj else obj.__class__.objects.none()
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return form
            if "patient" in form.base_fields:
                form.base_fields["patient"].queryset = __import__("users.models", fromlist=["PatientProfile"]).PatientProfile.objects.filter(
                    visits__hospital=hospital
                ).distinct()
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
            return qs.filter(patient__visits__hospital=hospital).distinct()
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
            return bool(hospital and obj.patient.visits.filter(hospital_id=hospital.id).exists())
        return False

    def has_change_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        return request.user.user_type == User.UserType.PATIENT and (obj is None or obj.patient.user_id == request.user.id)

    def has_add_permission(self, request):
        if is_platform_admin(request.user):
            return True
        return request.user.user_type == User.UserType.PATIENT

    def has_delete_permission(self, request, obj=None):
        if is_platform_admin(request.user):
            return True
        return request.user.user_type == User.UserType.PATIENT and (obj is None or obj.patient.user_id == request.user.id)


@admin.register(AccessRequest)
class AccessRequestAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ("id", "patient", "hospital", "request_type", "access_level", "status", "requested_by_staff", "created_at")
    list_filter = ("request_type", "access_level", "status", "hospital")
    search_fields = ("id", "patient__full_name", "hospital__name", "requested_by_staff__full_name", "code")
    readonly_fields = ("id", "code", "created_at", "responded_at", "patient_response_deadline")
    ordering = ("-created_at",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if is_platform_admin(request.user):
            return form
        if request.user.user_type == User.UserType.PATIENT:
            if "patient" in form.base_fields:
                form.base_fields["patient"].queryset = __import__("users.models", fromlist=["PatientProfile"]).PatientProfile.objects.filter(user=request.user)
            if "hospital" in form.base_fields:
                form.base_fields["hospital"].queryset = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(visits__patient__user=request.user).distinct()
            if "visit" in form.base_fields:
                form.base_fields["visit"].queryset = __import__("visits.models", fromlist=["Visit"]).Visit.objects.filter(patient__user=request.user)
            if "requested_by_staff" in form.base_fields:
                queryset = __import__("users.models", fromlist=["HospitalStaffProfile"]).HospitalStaffProfile.objects.none()
                if obj and obj.requested_by_staff_id:
                    queryset = __import__("users.models", fromlist=["HospitalStaffProfile"]).HospitalStaffProfile.objects.filter(pk=obj.requested_by_staff_id)
                    form.base_fields["requested_by_staff"].initial = obj.requested_by_staff_id
                form.base_fields["requested_by_staff"].queryset = queryset
                form.base_fields["requested_by_staff"].disabled = True
            if "status" in form.base_fields:
                form.base_fields["status"].disabled = False
            return form
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return form
            if "hospital" in form.base_fields:
                form.base_fields["hospital"].queryset = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(pk=hospital.id)
                form.base_fields["hospital"].initial = hospital.id
                form.base_fields["hospital"].disabled = True
            patient_queryset = __import__("users.models", fromlist=["PatientProfile"]).PatientProfile.objects.filter(visits__hospital=hospital).distinct()
            if "patient" in form.base_fields:
                qr_patient_id = request.GET.get("patient_id")
                if qr_patient_id:
                    patient_queryset = patient_queryset.filter(pk=qr_patient_id)
                    form.base_fields["patient"].initial = __import__("uuid", fromlist=["UUID"]).UUID(qr_patient_id)
                    form.base_fields["patient"].disabled = True
                form.base_fields["patient"].queryset = patient_queryset
            if "visit" in form.base_fields:
                visit_queryset = __import__("visits.models", fromlist=["Visit"]).Visit.objects.filter(hospital=hospital)
                if request.GET.get("patient_id"):
                    visit_queryset = visit_queryset.filter(patient_id=request.GET.get("patient_id"))
                form.base_fields["visit"].queryset = visit_queryset
            if "requested_by_staff" in form.base_fields:
                form.base_fields["requested_by_staff"].queryset = __import__("users.models", fromlist=["HospitalStaffProfile"]).HospitalStaffProfile.objects.filter(hospital=hospital)
                form.base_fields["requested_by_staff"].initial = obj.requested_by_staff_id if obj and obj.requested_by_staff_id else (staff.pk if staff else None)
                form.base_fields["requested_by_staff"].disabled = True
            if "status" in form.base_fields:
                form.base_fields["status"].initial = obj.status if obj and obj.status else AccessRequest.Status.PENDING
                form.base_fields["status"].disabled = True
        return form

    def _ensure_access_grant_for_approved_request(self, access_request):
        if access_request is None or access_request.status != AccessRequest.Status.APPROVED:
            return

        grant, created = AccessGrant.objects.get_or_create(
            access_request=access_request,
            defaults={
                "access_level": access_request.access_level,
                "granted_by": AccessGrant.GrantedBy.PATIENT,
            },
        )
        if grant.access_level != access_request.access_level:
            grant.access_level = access_request.access_level
        if grant.revoked_at is not None:
            grant.revoked_at = None
            grant.revoked_by = None
        if not grant.granted_by:
            grant.granted_by = AccessGrant.GrantedBy.PATIENT
        grant.granted_at = grant.granted_at or timezone.now()
        grant.save(update_fields=["access_level", "granted_by", "granted_at", "revoked_at", "revoked_by"])

    def save_model(self, request, obj, form, change):
        if not is_platform_admin(request.user) and request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            if not obj.pk:
                obj.status = AccessRequest.Status.PENDING
            else:
                current = AccessRequest.objects.filter(pk=obj.pk).only("status").first()
                if current is not None:
                    obj.status = current.status
        super().save_model(request, obj, form, change)
        if obj.status == AccessRequest.Status.APPROVED:
            self._ensure_access_grant_for_approved_request(obj)

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
        if is_platform_admin(request.user):
            return True
        if request.user.user_type == User.UserType.PATIENT:
            return obj is None or obj.patient.user_id == request.user.id
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return False
            if obj is None:
                return True
            return obj.hospital_id == hospital.id
        return False

    def has_add_permission(self, request):
        if is_platform_admin(request.user):
            return True
        if request.user.user_type not in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            return False
        return bool(__import__("users.admin", fromlist=["hospital_for_user"]).hospital_for_user(request.user))

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def delete_model(self, request, obj):
        if is_platform_admin(request.user):
            super().delete_model(request, obj)
            return
        raise ValidationError("Access requests are historical records and should not be deleted.")

    @admin.action(description="Approve selected request(s)")
    def approve_selected(self, request, queryset):
        if not (is_platform_admin(request.user) or request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN)):
            raise PermissionDenied("Only platform admins or hospital staff can approve requests.")
        for item in queryset:
            item.status = AccessRequest.Status.APPROVED
            item.responded_at = timezone.now()
            item.save(update_fields=["status", "responded_at"])
            self._ensure_access_grant_for_approved_request(item)
        self.message_user(request, f"{queryset.count()} request(s) approved.")

    @admin.action(description="Deny selected request(s)")
    def deny_selected(self, request, queryset):
        if not (is_platform_admin(request.user) or request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN)):
            raise PermissionDenied("Only platform admins or hospital staff can deny requests.")
        for item in queryset:
            item.status = AccessRequest.Status.DENIED
            item.responded_at = timezone.now()
            item.save(update_fields=["status", "responded_at"])
        self.message_user(request, f"{queryset.count()} request(s) denied.")


@admin.register(AccessGrant)
class AccessGrantAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ("id", "access_request", "access_level", "granted_by", "granted_at", "revoked_at", "revoked_by")
    list_filter = ("access_level", "granted_by", "revoked_by")
    search_fields = ("id", "access_request__patient__full_name", "access_request__hospital__name")
    readonly_fields = ("id", "access_request", "access_level", "granted_at", "granted_by", "revoked_at", "revoked_by")
    ordering = ("-granted_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(access_request__patient__user=request.user)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return qs.none()
            return qs.filter(access_request__hospital=hospital)
        return qs.none()

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    @admin.action(description="Revoke selected grant(s)")
    def revoke_selected(self, request, queryset):
        for item in queryset:
            if item.revoked_at is None:
                item.revoke(AccessGrant.RevokedBy.SYSTEM)
        self.message_user(request, f"{queryset.count()} grant(s) revoked.")


@admin.register(EmergencyEscalation)
class EmergencyEscalationAdmin(ImportExportModelAdmin, RoleAwareModelAdmin):
    list_display = ("id", "access_request", "stage", "triggered_at", "resolved_at", "resolved_by")
    list_filter = ("stage",)
    search_fields = ("id", "access_request__patient__full_name", "access_request__hospital__name", "resolved_by")
    readonly_fields = ("id", "access_request", "stage", "triggered_at", "resolved_at", "resolved_by")
    ordering = ("-triggered_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_platform_admin(request.user):
            return qs
        if request.user.user_type == User.UserType.PATIENT:
            return qs.filter(access_request__patient__user=request.user)
        if request.user.user_type in (User.UserType.HOSPITAL_STAFF, User.UserType.HOSPITAL_ADMIN):
            staff = current_staff(request.user)
            hospital = getattr(staff, "hospital", None) if staff else None
            if not hospital and request.user.user_type == User.UserType.HOSPITAL_ADMIN:
                hospital = __import__("users.models", fromlist=["Hospital"]).Hospital.objects.filter(admin=request.user).first()
            if not hospital:
                return qs.none()
            return qs.filter(access_request__hospital=hospital)
        return qs.none()

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    @admin.action(description="Resolve escalation")
    def resolve_selected(self, request, queryset):
        for item in queryset:
            if item.resolved_at is None:
                item.resolve(request.user.email or request.user.get_full_name() or "admin")
        self.message_user(request, f"{queryset.count()} escalation(s) resolved.")
