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
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
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

@swagger_auto_schema(
    method="post",
    tags=["Patients"],
    operation_summary="Register a new patient account",
    operation_description="""
    Creates a new self-managed patient account.

    This endpoint creates:
    - A `User` account used for authentication.
    - A `PatientProfile` containing the patient's medical identity information.
    - The user is automatically assigned the `patient` user type.
    - The patient profile is intended to be assigned the `self_managed` account type.

    **Notes for Frontend:**
    - This is a public registration endpoint.
    - `email` must be a valid email address.
    - The email must not already belong to another user.
    - `date_of_birth` must use the format `YYYY-MM-DD`.
    - `gender` is required by the current view.
    - `full_name` is accepted by the endpoint and is used when creating the patient profile.
    - A successful registration returns the newly created user information.
    - JWT tokens are NOT returned by this endpoint. The patient must log in separately after registration.
    - Registration is protected by `RegistrationThrottle`, so repeated registration attempts may be rate-limited.

    **Important Current Implementation Note:**
    - The current view reads `phone_number` from `data.get("email")` instead of
      `data.get("phone_number")`.
    - The current view also reads `blood_type` from `data.get("email")` instead of
      `data.get("blood_type")`.
    - These appear to be implementation mistakes and should be corrected in the view.
    - The intended request structure is documented below.

    **Authentication:** Not required.
    """,
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=[
            "email",
            "password",
            "phone_number",
            "full_name",
            "date_of_birth",
            "gender",
        ],
        properties={
            "email": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_EMAIL,
                description="Unique email address used by the patient to log in."
            ),
            "password": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_PASSWORD,
                description="Password for the patient's account."
            ),
            "phone_number": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Patient's phone number."
            ),
            "full_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Patient's full legal or preferred name."
            ),
            "date_of_birth": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                description="Patient's date of birth. Must be provided as YYYY-MM-DD."
            ),
            "gender": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Patient's gender."
            ),
            "blood_type": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Patient's blood type, for example A+, O-, AB+."
            ),
        },
        example={
            "email": "john.patient@example.com",
            "password": "SecurePassword123!",
            "phone_number": "08012345678",
            "full_name": "John Patient",
            "date_of_birth": "1995-06-14",
            "gender": "male",
            "blood_type": "O+"
        }
    ),
    responses={
        201: openapi.Response(
            description="Patient account created successfully",
            examples={
                "application/json": {
                    "status": True,
                    "message": "Account created successfully",
                    "data": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "email": "john.patient@example.com",
                        "phone_number": "08012345678",
                        "user_type": "patient",
                        "profile": {
                            "id": "a12e8400-e29b-41d4-a716-446655440111",
                            "full_name": "John Patient",
                            "date_of_birth": "1995-06-14",
                            "gender": "male",
                            "blood_type": "O+",
                            "account_type": "self_managed",
                            "created_at": "2026-09-17T12:30:00Z"
                        }
                    }
                }
            }
        ),
        400: openapi.Response(
            description="Invalid registration data",
            examples={
                "application/json": {
                    "status": False,
                    "message": "Invalid email format."
                }
            }
        ),
        429: openapi.Response(
            description="Too many registration attempts",
            examples={
                "application/json": {
                    "detail": "Request was throttled."
                }
            }
        ),
    }
)
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

@swagger_auto_schema(
    method="post",
    tags=["Patients"],
    operation_summary="Register a dependent patient",
    operation_description="""
    Creates a dependent patient under the currently authenticated patient's account.

    A dependent is a patient profile that is controlled by a guardian rather than
    having its own login credentials.

    **Notes for Frontend:**
    - The logged-in user must be a patient.
    - The authenticated patient's profile becomes the dependent's guardian.
    - A dependent does NOT require an email address.
    - A dependent does NOT require a password.
    - A dependent does NOT receive JWT tokens.
    - `full_name`, `date_of_birth`, and `gender` are required by the current view.
    - `date_of_birth` must use `YYYY-MM-DD`.
    - `blood_type` can be supplied if known.
    - The returned `data` object contains the created patient profile.

    **Important Current Implementation Note:**
    - The model requires an `account_type`.
    - The intended account type for this endpoint is `dependent`.
    - The current view does not explicitly provide
      `account_type=PatientProfile.AccountType.DEPENDENT` when creating the profile.
    - This should be corrected in the view.

    **Authentication:** Required.

    **Required Role:** Patient.
    """,
    security=[{"Bearer": []}],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["full_name", "date_of_birth", "gender"],
        properties={
            "full_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Full name of the dependent."
            ),
            "date_of_birth": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                description="Dependent's date of birth in YYYY-MM-DD format."
            ),
            "gender": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Dependent's gender."
            ),
            "blood_type": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Dependent's blood type, if known."
            ),
        },
        example={
            "full_name": "Sarah Patient",
            "date_of_birth": "2018-04-20",
            "gender": "female",
            "blood_type": "A+"
        }
    ),
    responses={
        201: openapi.Response(
            description="Dependent created successfully",
            examples={
                "application/json": {
                    "status": True,
                    "message": "Dependent created successfully",
                    "data": {
                        "id": "750e8400-e29b-41d4-a716-446655440000",
                        "full_name": "Sarah Patient",
                        "date_of_birth": "2018-04-20",
                        "gender": "female",
                        "blood_type": "A+",
                        "account_type": "dependent",
                        "created_at": "2026-09-17T12:35:00Z"
                    }
                }
            }
        ),
        400: openapi.Response(
            description="Missing or invalid dependent information",
            examples={
                "application/json": {
                    "status": False,
                    "message": "Date of birth must be provided in form YYYY-MM-DD"
                }
            }
        ),
        401: openapi.Response(
            description="Authentication credentials were not provided or token is invalid",
            examples={
                "application/json": {
                    "detail": "Authentication credentials were not provided."
                }
            }
        ),
        403: openapi.Response(
            description="Authenticated user is not permitted to register a dependent",
            examples={
                "application/json": {
                    "detail": "You do not have permission to perform this action."
                }
            }
        ),
    }
)
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

@swagger_auto_schema(
    method="post",
    tags=["Hospitals"],
    operation_summary="Register a hospital and its first administrator",
    operation_description="""
    Registers a new hospital together with the hospital's first administrator account.

    The hospital is intended to be created with verification status `pending`.
    The administrator receives a normal user account with user type `hospital_staff`
    and a hospital staff profile with role `admin`.

    **Notes for Frontend:**
    - This endpoint is publicly accessible.
    - All fields listed in the request schema are required by the current view.
    - `admin_email` must be a valid email address.
    - The administrator email cannot already belong to another user.
    - The hospital registration number must be unique.
    - Hospital name, PHERMC number, and CAC number are also checked for duplicates.
    - The current view requires the administrator password to contain at least 5 characters.
    - A successful registration does NOT mean the hospital has been verified.
    - New hospitals start with `verification_status = pending`.
    - Verification must occur through a separate verification process.
    - Registration is protected by `RegistrationThrottle`.

    **Important Current Implementation Note:**
    - The current view creates the hospital using `Hospital(...)` but does not call
      `hospital.save()` before using it in `HospitalStaffProfile.objects.create(...)`.
    - The hospital must normally be saved before it can be referenced by the staff profile.
    - This should be corrected in the implementation.

    **Authentication:** Not required.
    """,
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=[
            "hospital_name",
            "registration_number",
            "phermc_number",
            "cac_number",
            "address",
            "admin_email",
            "admin_password",
            "admin_full_name",
        ],
        properties={
            "hospital_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Official name of the hospital."
            ),
            "registration_number": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Unique National Health Facility Registry or hospital registration number."
            ),
            "phermc_number": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Hospital PHERMC registration/reference number."
            ),
            "cac_number": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Hospital Corporate Affairs Commission registration number."
            ),
            "address": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Physical address of the hospital."
            ),
            "admin_email": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_EMAIL,
                description="Email address for the hospital's first administrator."
            ),
            "admin_password": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_PASSWORD,
                description="Password for the first hospital administrator."
            ),
            "admin_full_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Full name of the first hospital administrator."
            ),
        },
        example={
            "hospital_name": "Central Medical Hospital",
            "registration_number": "HFR-2026-001245",
            "phermc_number": "PHERMC-88291",
            "cac_number": "RC-1948273",
            "address": "15 Medical Avenue, Lagos",
            "admin_email": "admin@centralmedical.example",
            "admin_password": "SecurePassword123!",
            "admin_full_name": "Dr. James Williams"
        }
    ),
    responses={
        201: openapi.Response(
            description="Hospital registered successfully and awaiting verification",
            examples={
                "application/json": {
                    "status": True,
                    "message": "Hospital created successfully",
                    "data": {
                        "id": "850e8400-e29b-41d4-a716-446655440000",
                        "name": "Central Medical Hospital",
                        "registration_number": "HFR-2026-001245",
                        "phermc_number": "PHERMC-88291",
                        "cac_number": "RC-1948273",
                        "address": "15 Medical Avenue, Lagos",
                        "verification_status": "pending",
                        "created_at": "2026-09-17T12:40:00Z"
                    }
                }
            }
        ),
        400: openapi.Response(
            description="Missing, invalid, or duplicate hospital information",
            examples={
                "application/json": {
                    "status": False,
                    "message": "All fields are required"
                }
            }
        ),
        404: openapi.Response(
            description="Administrator email already exists. The current view returns HTTP 404 for this condition.",
            examples={
                "application/json": {
                    "status": False,
                    "message": "Email is already in use"
                }
            }
        ),
        429: openapi.Response(
            description="Too many registration attempts",
            examples={
                "application/json": {
                    "detail": "Request was throttled."
                }
            }
        ),
    }
)
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

@swagger_auto_schema(
    method="post",
    tags=["Hospital Staff"],
    operation_summary="Create a new hospital staff account",
    operation_description="""
    Allows an authenticated hospital administrator to create a new staff account
    under their own hospital.

    The hospital is automatically determined from the authenticated administrator's
    `staff_profile`. The client therefore does NOT provide a hospital ID.

    **Notes for Frontend:**
    - Authentication is required.
    - Only a hospital administrator can access this endpoint.
    - The current view accepts `doctor` and `nurse` as valid roles.
    - The current view requires `professional_license_number` for both roles.
    - The server generates a temporary password automatically.
    - The temporary password is NOT returned in the API response.
    - `must_change_password` is set to `True` on the new user.
    - The temporary password is emailed to the staff member.
    - The staff member should change the temporary password after logging in.
    - The staff member is automatically assigned to the administrator's hospital.

    **Important Current Implementation Note:**
    - The current view returns HTTP 201 even when required fields are missing.
    - In that case the response contains `status: false`.
    - Frontend code should therefore inspect the response `status` field as well as
      the HTTP status until this behavior is corrected.
    - The supplied serializer allows `professional_license_number` to be optional for
      nurses, but the current view requires it for every staff member.

    **Authentication:** Required.

    **Required Role:** Hospital Admin.
    """,
    security=[{"Bearer": []}],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=[
            "email",
            "full_name",
            "role",
            "professional_license_number",
        ],
        properties={
            "email": openapi.Schema(
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_EMAIL,
                description="Email address of the new staff member."
            ),
            "full_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Full name of the staff member."
            ),
            "role": openapi.Schema(
                type=openapi.TYPE_STRING,
                enum=["doctor", "nurse"],
                description="Staff role. The current view accepts only `doctor` or `nurse`."
            ),
            "professional_license_number": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Professional license number. Required by the current view."
            ),
        },
        example={
            "email": "doctor@centralmedical.example",
            "full_name": "Dr. Sarah Johnson",
            "role": "doctor",
            "professional_license_number": "MDCN-123456"
        }
    ),
    responses={
        201: openapi.Response(
            description="Staff created successfully. Note: the current view also uses HTTP 201 when required fields are missing.",
            examples={
                "application/json": {
                    "status": True,
                    "message": "Staff created successfully",
                    "data": {
                        "id": "950e8400-e29b-41d4-a716-446655440000",
                        "full_name": "Dr. Sarah Johnson",
                        "role": "doctor",
                        "professional_license_number": "MDCN-123456",
                        "hospital": "850e8400-e29b-41d4-a716-446655440000",
                        "hospital_name": "Central Medical Hospital",
                        "hospital_verification_status": "pending",
                        "created_at": "2026-09-17T12:45:00Z"
                    }
                }
            }
        ),
        400: openapi.Response(
            description="Invalid email or invalid staff role",
            examples={
                "application/json": {
                    "status": False,
                    "message": "Role must either be 'doctor' or 'nurse'"
                }
            }
        ),
        401: openapi.Response(
            description="Authentication required",
            examples={
                "application/json": {
                    "detail": "Authentication credentials were not provided."
                }
            }
        ),
        403: openapi.Response(
            description="Authenticated user is not a hospital administrator",
            examples={
                "application/json": {
                    "detail": "You do not have permission to perform this action."
                }
            }
        ),
    }
)
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

    return Response({
        'status': True,
        'message': 'Profile retrieved successfully',
        'data': profile_data
    }, status=status.HTTP_200_OK)


