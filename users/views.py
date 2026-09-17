"""
Function-based views for the auth module.

All business logic here is unchanged from the original class-based
version — only the *shape* changed: FBVs with explicit decorators
instead of generics/APIView subclasses, per the team's preference.

Every view:
  - returns core.responses.success_response(...) on success — never a
    bare Response(...) — so every endpoint has the same envelope shape.
  - lets exceptions (ValidationError, PermissionDenied, etc.) propagate
    instead of catching them — core.exceptions.custom_exception_handler
    (wired in settings via EXCEPTION_HANDLER) turns them into the same
    envelope shape on the error side. Don't add your own try/except
    around serializer.is_valid(raise_exception=True) — that's the point
    of raise_exception=True.
  - is documented with @extend_schema for the auto-generated Swagger/
    OpenAPI docs (see urls.py / project_urls_snippet.py for where those
    are served).
"""

from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import permissions, status, throttling
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from core.audit import log_event
from core.messages import AUTH, GENERIC, PASSWORD, PROFILE, REGISTRATION
from core.responses import error_response, success_response

from .models import CustomUser, HospitalStaffProfile, PatientProfile
from .permissions import IsHospitalAdmin, IsPatient
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    DependentRegistrationSerializer,
    HospitalRegistrationSerializer,
    HospitalStaffCreateSerializer,
    HospitalStaffProfileSerializer,
    PatientProfileSerializer,
    PatientRegistrationSerializer,
)


# ---------------------------------------------------------------------------
# THROTTLES
# ---------------------------------------------------------------------------
# Registration and login are the two endpoints most likely to be hit by
# automated abuse (fake sign-ups, brute-force login attempts). Named
# scopes so they can be tuned independently in settings.py without
# touching this file again.

class RegistrationThrottle(throttling.AnonRateThrottle):
    scope = "registration"


class LoginThrottle(throttling.AnonRateThrottle):
    scope = "login"


# ---------------------------------------------------------------------------
# REGISTRATION
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Auth — Registration"],
    summary="Register a new adult patient",
    description=(
        "Public, self-service signup for an adult patient. Creates both "
        "the login account and the medical-identity profile in one call."
    ),
    request=PatientRegistrationSerializer,
    responses={201: PatientProfileSerializer},
    examples=[
        OpenApiExample(
            "Success",
            value={
                "success": True,
                "message": REGISTRATION["PATIENT_REGISTERED"],
                "data": {
                    "id": "b3b3c3d3-...",
                    "full_name": "Ada Lovelace",
                    "date_of_birth": "1990-01-01",
                    "gender": "female",
                    "blood_type": "O+",
                    "account_type": "self_managed",
                    "created_at": "2026-09-17T10:00:00Z",
                },
            },
            response_only=True,
            status_codes=["201"],
        ),
    ],
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([RegistrationThrottle])
def register_patient(request):
    serializer = PatientRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    profile = serializer.save()
    log_event("patient_registered", user_id=str(profile.user_id), email=profile.user.email)
    return success_response(
        PatientProfileSerializer(profile).data,
        message=REGISTRATION["PATIENT_REGISTERED"],
        status_code=status.HTTP_201_CREATED,
    )


@extend_schema(
    tags=["Auth — Registration"],
    summary="Register a dependent (child) under the logged-in patient",
    description=(
        "Must be called by an already-logged-in patient. Registers a child "
        "with no login of their own — access is entirely through the "
        "guardian's account."
    ),
    request=DependentRegistrationSerializer,
    responses={201: PatientProfileSerializer},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsPatient])
def register_dependent(request):
    guardian_profile = request.user.patient_profile
    serializer = DependentRegistrationSerializer(
        data=request.data, context={"guardian_profile": guardian_profile}
    )
    serializer.is_valid(raise_exception=True)
    dependent = serializer.save()
    log_event(
        "dependent_registered",
        user_id=str(request.user.id),
        email=request.user.email,
        dependent_id=str(dependent.id),
    )
    return success_response(
        PatientProfileSerializer(dependent).data,
        message=REGISTRATION["DEPENDENT_REGISTERED"],
        status_code=status.HTTP_201_CREATED,
    )


@extend_schema(
    tags=["Auth — Registration"],
    summary="Register a new hospital and its first admin account",
    description=(
        "Public. The hospital starts in `pending` verification status — "
        "this endpoint grants NO patient-data access on its own. See "
        "IsFromVerifiedHospital, applied on data-access endpoints elsewhere "
        "in the project."
    ),
    request=HospitalRegistrationSerializer,
    examples=[
        OpenApiExample(
            "Success",
            value={
                "success": True,
                "message": REGISTRATION["HOSPITAL_REGISTERED"],
                "data": {
                    "hospital_id": "b3b3c3d3-...",
                    "verification_status": "pending",
                },
            },
            response_only=True,
            status_codes=["201"],
        ),
    ],
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([RegistrationThrottle])
def register_hospital(request):
    serializer = HospitalRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    hospital = serializer.save()
    log_event("hospital_registered", hospital_id=str(hospital.id))
    return success_response(
        {
            "hospital_id": str(hospital.id),
            "verification_status": hospital.verification_status,
        },
        message=REGISTRATION["HOSPITAL_REGISTERED"],
        status_code=status.HTTP_201_CREATED,
    )


@extend_schema(
    tags=["Auth — Registration"],
    summary="Add a staff member to your hospital",
    description=(
        "Hospital-admin only. Creates a staff account with a system-generated "
        "temporary password — the account is forced to change it on first "
        "login. The temporary password is NEVER included in this response; "
        "it is handed off to the notification service only."
    ),
    request=HospitalStaffCreateSerializer,
    responses={201: HospitalStaffProfileSerializer},
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsHospitalAdmin])
def create_hospital_staff(request):
    hospital = request.user.staff_profile.hospital
    serializer = HospitalStaffCreateSerializer(data=request.data, context={"hospital": hospital})
    serializer.is_valid(raise_exception=True)
    staff_profile = serializer.save()

    # --- TODO for whoever wires up notifications ---
    # send_temp_password_email(
    #     to=staff_profile.user.email,
    #     temp_password=staff_profile._temp_password,
    # )
    # Never log staff_profile._temp_password, and never let it reach the
    # HTTP response below — HospitalStaffProfileSerializer doesn't expose
    # it, which is what actually enforces this; the line here is a
    # reminder for whoever edits that serializer later.

    log_event(
        "staff_created",
        user_id=str(staff_profile.user_id),
        email=staff_profile.user.email,
        hospital_id=str(hospital.id),
        role=staff_profile.role,
        created_by=str(request.user.id),
    )
    return success_response(
        HospitalStaffProfileSerializer(staff_profile).data,
        message=REGISTRATION["STAFF_CREATED"],
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Auth — Session"],
    summary="Log in",
    description=(
        "Returns access + refresh JWTs with custom claims (user_type, and "
        "hospital context for staff) baked in, so the frontend can route "
        "users without an extra call. On failure, the message is "
        "deliberately generic (\"incorrect email or password\") — it never "
        "confirms whether the email exists, to prevent account enumeration."
    ),
    request=CustomTokenObtainPairSerializer,
    examples=[
        OpenApiExample(
            "Success",
            value={
                "success": True,
                "message": AUTH["LOGIN_SUCCESS"],
                "data": {"access": "<jwt>", "refresh": "<jwt>"},
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):
    # LoginThrottle here rate-limits repeated attempts from one IP. For
    # real production hardening, ALSO add per-account lockout after N
    # failed attempts (e.g. django-axes) — not included in this module,
    # flagged as a follow-up in the README.
    serializer = CustomTokenObtainPairSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    log_event("login_success", email=request.data.get("email", ""))
    return success_response(serializer.validated_data, message=AUTH["LOGIN_SUCCESS"])


@extend_schema(
    tags=["Auth — Session"],
    summary="Refresh an access token",
    request=TokenRefreshSerializer,
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def refresh_token_view(request):
    serializer = TokenRefreshSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return success_response(serializer.validated_data, message=AUTH["TOKEN_REFRESHED"])


@extend_schema(
    tags=["Auth — Session"],
    summary="Log out",
    description="Blacklists the given refresh token so it can never be used again, even before it expires.",
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return error_response(
            AUTH["LOGOUT_MISSING_TOKEN"],
            errors={"refresh": ["This field is required."]},
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        # Deliberately vague — don't tell the caller WHY a token failed to
        # blacklist (could leak whether a token is valid/expired/forged).
        return error_response(
            AUTH["LOGOUT_INVALID_TOKEN"],
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_TOKEN",
        )
    log_event("logout_success", user_id=str(request.user.id), email=request.user.email)
    return success_response(message=AUTH["LOGOUT_SUCCESS"], status_code=status.HTTP_205_RESET_CONTENT)


# ---------------------------------------------------------------------------
# "ME" — profile retrieval, works for either user type
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Auth — Profile"],
    summary="Get the logged-in user's own profile",
    description=(
        "Returns the right profile shape depending on whether the caller is "
        "a patient or hospital staff — the frontend doesn't need to know "
        "which in advance, just call this after login."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_view(request):
    user = request.user
    if user.user_type == CustomUser.UserType.PATIENT:
        profile_data = PatientProfileSerializer(user.patient_profile).data
    elif user.user_type == CustomUser.UserType.HOSPITAL_STAFF:
        profile_data = HospitalStaffProfileSerializer(user.staff_profile).data
    else:
        # Platform admins have no patient/staff profile — an empty dict is
        # correct here, not a bug: there is nothing else safe to return.
        profile_data = {}

    return success_response(
        {
            "user_type": user.user_type,
            "email": user.email,
            "must_change_password": user.must_change_password,
            "profile": profile_data,
        },
        message=PROFILE["FETCHED"],
    )


# ---------------------------------------------------------------------------
# PASSWORD MANAGEMENT
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Auth — Password"],
    summary="Change your password",
    description=(
        "Works both for a voluntary change and the forced first-login "
        "change (must_change_password=True). This is the ONE endpoint that "
        "must stay reachable even when must_change_password is True."
    ),
    request=ChangePasswordSerializer,
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def change_password_view(request):
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    log_event("password_changed", user_id=str(request.user.id), email=request.user.email)
    return success_response(message=PASSWORD["CHANGED"])


@extend_schema(
    tags=["Auth — Password"],
    summary="Request a password reset email",
    description=(
        "Always returns 200 with the same message whether or not the email "
        "exists, to avoid leaking which emails are registered."
    ),
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def request_password_reset_view(request):
    email = request.data.get("email", "")
    user = CustomUser.objects.filter(email__iexact=email).first()

    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        # --- TODO for whoever wires up notifications ---
        # reset_link = f"{FRONTEND_URL}/reset-password/{uid}/{token}/"
        # send_password_reset_email(to=user.email, link=reset_link)
        log_event("password_reset_requested", user_id=str(user.id), email=user.email)

    # No `else` branch that logs/behaves differently — that asymmetry is
    # exactly what would let an attacker tell registered emails apart from
    # unregistered ones by timing or side effects.
    return success_response(message=PASSWORD["RESET_REQUESTED"])


@extend_schema(
    tags=["Auth — Password"],
    summary="Complete a password reset",
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def confirm_password_reset_view(request):
    uid = request.data.get("uid", "")
    token = request.data.get("token", "")
    new_password = request.data.get("new_password", "")

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = CustomUser.objects.get(pk=user_id)
    except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
        return error_response(
            PASSWORD["RESET_LINK_INVALID"],
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_RESET_LINK",
        )

    if not default_token_generator.check_token(user, token):
        return error_response(
            PASSWORD["RESET_LINK_EXPIRED"],
            status_code=status.HTTP_400_BAD_REQUEST,
            code="EXPIRED_RESET_LINK",
        )

    try:
        validate_password(new_password, user=user)
    except Exception as exc:
        return error_response(
            GENERIC["VALIDATION_ERROR"],
            errors={"new_password": list(exc.messages)},
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
        )

    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    log_event("password_reset_completed", user_id=str(user.id), email=user.email)

    return success_response(message=PASSWORD["RESET_SUCCESS"])
