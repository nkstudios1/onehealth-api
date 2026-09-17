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
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import EmailMessage

from core.audit import log_event
from core.messages import AUTH, GENERIC, PASSWORD, PROFILE, REGISTRATION
from core.responses import error_response, success_response
from core.utils import is_correct_format, generate_temporary_password, is_valid_email

from .models import User, Hospital, HospitalStaffProfile, PatientProfile
from .permissions import IsHospitalAdmin, IsPatient
from .serializers import (
    UserSerializer,
    HospitalSerializer,
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    DependentRegistrationSerializer,
    HospitalRegistrationSerializer,
    HospitalStaffCreateSerializer,
    HospitalStaffProfileSerializer,
    PatientProfileSerializer,
    PatientRegistrationSerializer,
)
from django.conf import settings
from django.contrib.auth import authenticate

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


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([RegistrationThrottle])
def register_patient(request):

    data = request.data

    email = data.get('email')
    password = data.get('password')
    phone_number = data.get('email')
    date_of_birth = data.get('date_of_birth')
    gender = data.get('gender')
    blood_type = data.get('email')
    full_name = data.get('full_name')

    if not is_correct_format(date_of_birth):
        return Response({
            'status': False,
            'message': 'Date of birth must be provided in form YYYY-MM-DD'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not (email and password and phone_number and date_of_birth and gender):
        return Response({
            'status': False,
            'message': 'Email, password, phone_number, date of birth and gender are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not is_valid_email(email):
        return Response({
            "status": False,
            "message": "Invalid email format."
        }, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({
            'status': False,
            "message": "Email is already in use"
        }, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(phone_number=phone_number).exists():
        return Response({
            'status': False,
            "message": "Email is already in use"
        }, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        email = email,
        password = password,
        date_of_birth = date_of_birth,
        user_type = User.UserType.PATIENT,
        gender = gender
    )

    # create patient profile
    PatientProfile.objects.create(
        user = user,
        full_name = full_name,
        blood_type = blood_type,
        account_type = PatientProfile.AccountType.SELF_MANAGED,

    )

    serializer = UserSerializer(user)
    return Response({
        'status': True,
        'message': 'Account created successfully',
        'data': serializer.data
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsPatient])
def register_dependent(request):
    guardian_profile = request.user.patient_profile

    data = request.data

    full_name = data.get('full_name')
    date_of_birth = data.get('date_of_birth')
    gender = data.get('gender')
    blood_type = data.get('blood_type', None)

    if not (full_name and date_of_birth and gender):
        return Response({
            'status': False,
            'message': 'Full name, date of birth, and gender'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not is_correct_format(date_of_birth):
        return Response({
            'status': False,
            'message': 'Date of birth must be provided in form YYYY-MM-DD'
        }, status=status.HTTP_400_BAD_REQUEST)

    patient = PatientProfile.objects.create(
        full_name = full_name,
        date_of_birth = date_of_birth,
        gender = gender,
        blood_type = blood_type,
        guardian = guardian_profile
    )

    serializer = PatientProfileSerializer(patient)
    return Response({
        'status': True,
        'message': 'Dependent created successfully',
        'data': serializer.data
    }, status=status.HTTP_201_CREATED)

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([RegistrationThrottle])
def register_hospital(request):

    data = request.data

    hospital_name = data.get('hospital_name')

    # unique 
    registration_number = data.get('registration_number')
    phermc_number = data.get('phermc_number')
    cac_number = data.get('cac_number')

    address = data.get('address')
    admin_email = data.get('admin_email')
    admin_password = data.get('admin_password')
    admin_full_name = data.get('admin_full_name')

    if not (
        hospital_name and registration_number and phermc_number 
        and cac_number and address and admin_email and admin_password 
        and admin_full_name
    ):
        return Response({
            'status': False,
            'message': 'All fields are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not is_valid_email(admin_email):
        return Response({
            "status": False,
            "message": "Invalid email format."
        }, status=status.HTTP_400_BAD_REQUEST)

    if len(admin_password) < 5:
        return Response({
            'status': False,
            'message': 'Password must be at least  characters'
        }, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=admin_email).exists():
        return Response({
            'status': False,
            'message': 'Email is already in use'
        }, status=status.HTTP_404_NOT_FOUND)    

    if Hospital.objects.filter(name=hospital_name).exists():
        return Response({
            'status': False,
            'message': 'Registration number already in use'
        }, status=status.HTTP_400_BAD_REQUEST) 

    if Hospital.objects.filter(registration_number=registration_number).exists():
        return Response({
            'status': False,
            'message': 'Registration number already in use'
        }, status=status.HTTP_400_BAD_REQUEST) 

    if Hospital.objects.filter(phermc_number=phermc_number).exists():
        return Response({
            'status': False,
            'message': 'Registration number already in use'
        }, status=status.HTTP_400_BAD_REQUEST) 

    if Hospital.objects.filter(cac_number=cac_number).exists():
        return Response({
            'status': False,
            'message': 'CAC number already in use'
        }, status=status.HTTP_400_BAD_REQUEST) 

    # create hospital
    hospital = Hospital(
        name = hospital_name,
        registration_number = registration_number,
        phermc_number = phermc_number,
        cac_number = cac_number,
        address = address,
        verification_status=Hospital.VerificationStatus.PENDING,
    )

    # create an admin user for the hospital
    admin_user = User.objects.create_user(
        email = admin_email,
        password = admin_password,
        user_type=User.UserType.HOSPITAL_STAFF,
    )

    # create a profile for the hospital
    HospitalStaffProfile.objects.create(
        user=admin_user,
        hospital=hospital,
        full_name = admin_full_name,
        role = HospitalStaffProfile.Role.ADMIN,
    )

    serializer = HospitalSerializer(hospital)
    return Response({
        'status': True,
        'message': 'Hospital created successfully',
        'data': serializer.data
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsHospitalAdmin])
def create_hospital_staff(request):

    hospital = request.user.staff_profile.hospital

    data = request.data
    email = data.get('email')
    full_name = data.get('full_name')
    role = data.get('role')
    professional_license_number = data.get('professional_license_number')

    if not (
        email and full_name and role and professional_license_number
    ):
        return Response({
            'status': False,
            'message': 'All fields are required'
        }, status=status.HTTP_201_CREATED)

    if not is_valid_email(email):
        return Response({
            "status": False,
            "message": "Invalid email format."
        }, status=status.HTTP_400_BAD_REQUEST)

    if not (
        role == HospitalStaffProfile.Role.DOCTOR or
        role == HospitalStaffProfile.Role.NURSE 
    ):
        return Response({
            'status': False,
            'message': "Role must either be 'doctor' or 'nurse'"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    temp_password = generate_temporary_password()

    # create user profile
    user = User.objects.create_user(
        email = email,
        password = temp_password,
        user_type = User.UserType.HOSPITAL_STAFF,
        must_change_password = True,
    )

    # create staff profile for user
    staff_profile = HospitalStaffProfile.objects.create(
        user = user,
        hospital = hospital,
        full_name= full_name,
        role = role,
        professional_license_number = professional_license_number,
    )
    
    # email the temporary password to the user
    email_message = EmailMessage(
        'Temporary Staff Password',
        f'Your staff account has been created under hospital {hospital.name} and you temporary password is:\n\n{temp_password}\n\nMake sure to change this password later on',
        settings.EMAIL_HOST_USER,
        [email]
    )
    email_message.fail_silently = True
    email_message.send()   

    serializer = HospitalStaffProfileSerializer(staff_profile)
    return Response({
        'status': True,
        'message': 'Staff created successfully',
        'data': serializer.data
    }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):

    data = request.data
    identifier = data.get('identifier')
    password = data.get('password')

    user = None

    # identifier is email
    if '@' in identifier:
        email = email.strip().lower()
        
        if not is_valid_email(email):
            return Response({
                "status": False,
                "message": "Invalid email format."
            }, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=email, password=password)

        return Response({
            'status': False,
            'message': 'Invalid credentials provided'
        }, status=status.HTTP_400_BAD_REQUEST)

    else:
        # else identifier is phone number
        if not identifier.isdigit():
            return Response({
                'status': False,
                'message': 'You must enter either a phone number or valid email address'
            }, status=status.HTTP_400_BAD_REQUEST)

        # make sure user enters correct length of phone number
        if len(identifier) != 11:
            return Response({
                'status': False,
                'message': 'Phone numbers must be 11 digits long'
            }, status=status.HTTP_400_BAD_REQUEST)

        # attempt to authenticate the user with phone number
    
        _user = User.objects.filter(phone_number=identifier).first()
        if _user and _user.check_password(password):
            user = _user

    if user is not None:        
        serializer = UserSerializer(user)
        return Response({
            'status': True,
            'message': 'Login successful',
            'data': {
                'user': serializer.data,
                'tokens': user.auth_tokens()
            }
        })

    return Response({
        'status': False,
        'message': 'Invalid credentials provided'
    }, status=status.HTTP_400_BAD_REQUEST)
   



@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def refresh_token_view(request):
    serializer = TokenRefreshSerializer(data=request.data)

    try:
        serializer.is_valid(raise_exception=True)
        return Response({
            "status": True,
            "message": "Token refreshed successfully",
            "data": serializer.validated_data
        }, status=status.HTTP_200_OK)

    except (TokenError, InvalidToken):
        return Response({
            "status": False,
            "message": "Token is invalid or has expired"
        }, status=status.HTTP_401_UNAUTHORIZED)

    except Exception:
        return Response({
            "status": False,
            "message": "An unexpected error occurred"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    try:
        refresh_token = request.data.get("refresh")
        if refresh_token is None:
            return Response({
                "error": "Refresh token is required."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Blacklist the refresh token to prevent further use
        token = RefreshToken(refresh_token)
        token.blacklist()
        
        return Response({
            "status": True,
            "message": "Successfully logged out."
            }, status=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        return Response({
            "status": False,
            "error": str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

# ---------------------------------------------------------------------------
# "ME" — profile retrieval, works for either user type
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_view(request):
    user = request.user
    if user.user_type == User.UserType.PATIENT:
        profile_data = PatientProfileSerializer(user.patient_profile).data
    elif user.user_type == User.UserType.HOSPITAL_STAFF:
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
    user = User.objects.filter(email__iexact=email).first()

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
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
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
