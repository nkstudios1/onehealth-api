from datetime import date

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import authenticate
from django.test import RequestFactory, TestCase

from access.admin import AccessRequestAdmin
from access.models import AccessGrant, AccessRequest
from cards.models import PatientCard
from records.admin import MedicalRecordAdmin
from records.models import MedicalRecord
from users.admin import HospitalAdmin, HospitalStaffProfileAdmin, PatientProfileAdmin, UserAdmin
from users.models import Hospital, HospitalStaffProfile, PatientProfile, User
from visits.admin import VisitAdmin
from visits.models import Visit


class AdminRolePermissionsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()

        self.hospital_a = Hospital.objects.create(
            name="Hospital A",
            registration_number="HOSP-A-001",
            verification_status=Hospital.VerificationStatus.VERIFIED,
        )
        self.hospital_b = Hospital.objects.create(
            name="Hospital B",
            registration_number="HOSP-B-001",
            verification_status=Hospital.VerificationStatus.VERIFIED,
        )

        self.platform_admin = User.objects.create_user(
            email="platform@demo.test",
            password="testing",
            phone_number="+10000000001",
            user_type=User.UserType.PLATFORM_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        self.patient_user = User.objects.create_user(
            email="patient@demo.test",
            password="testing",
            phone_number="+10000000002",
            user_type=User.UserType.PATIENT,
            is_staff=True,
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            full_name="Demo Patient",
            date_of_birth=date(1990, 1, 1),
            account_type=PatientProfile.AccountType.SELF_MANAGED,
        )

        self.staff_user_a = User.objects.create_user(
            email="doctor_a@demo.test",
            password="testing",
            phone_number="+10000000003",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.staff_profile_a = HospitalStaffProfile.objects.create(
            user=self.staff_user_a,
            hospital=self.hospital_a,
            full_name="Dr. Alpha",
            role=HospitalStaffProfile.Role.DOCTOR,
            professional_license_number="MDCN-ALPHA-001",
        )

        self.staff_user_b = User.objects.create_user(
            email="doctor_b@demo.test",
            password="testing",
            phone_number="+10000000004",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.staff_profile_b = HospitalStaffProfile.objects.create(
            user=self.staff_user_b,
            hospital=self.hospital_b,
            full_name="Dr. Beta",
            role=HospitalStaffProfile.Role.DOCTOR,
            professional_license_number="MDCN-BETA-001",
        )

        self.hospital_admin_a = User.objects.create_user(
            email="admin_a@demo.test",
            password="testing",
            phone_number="+10000000005",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.hospital_admin_profile_a = HospitalStaffProfile.objects.create(
            user=self.hospital_admin_a,
            hospital=self.hospital_a,
            full_name="Admin Alpha",
            role=HospitalStaffProfile.Role.ADMIN,
        )

        self.hospital_admin_user = User.objects.create_user(
            email="hospital_admin@demo.test",
            password="testing",
            phone_number="+10000000006",
            user_type=User.UserType.HOSPITAL_ADMIN,
            is_staff=True,
        )
        self.hospital_a.admin = self.hospital_admin_user
        self.hospital_a.save(update_fields=["admin"])

        self.visit = Visit.objects.create(
            patient=self.patient_profile,
            hospital=self.hospital_a,
            created_by_staff=self.staff_profile_a,
        )

    def test_hospital_admin_sees_only_same_hospital_queryset(self):
        request = self.factory.get("/")
        request.user = self.hospital_admin_a

        visit_admin = VisitAdmin(Visit, self.site)
        queryset = visit_admin.get_queryset(request)

        self.assertEqual(queryset.count(), 1)
        self.assertQuerySetEqual(queryset, [self.visit.pk], transform=lambda obj: obj.pk, ordered=False)

        hospital_admin = HospitalAdmin(Hospital, self.site)
        self.assertEqual(hospital_admin.get_queryset(request).count(), 1)
        self.assertEqual(hospital_admin.get_queryset(request).first(), self.hospital_a)

    def test_hospital_staff_form_choices_are_hospital_scoped(self):
        request = self.factory.get("/")
        request.user = self.hospital_admin_a

        visit_admin = VisitAdmin(Visit, self.site)
        form = visit_admin.get_form(request)

        self.assertIn(self.hospital_a.pk, set(form.base_fields["hospital"].queryset.values_list("pk", flat=True)))
        self.assertNotIn(self.hospital_b.pk, set(form.base_fields["hospital"].queryset.values_list("pk", flat=True)))
        self.assertIn(self.staff_profile_a.pk, set(form.base_fields["created_by_staff"].queryset.values_list("pk", flat=True)))
        self.assertNotIn(self.staff_profile_b.pk, set(form.base_fields["created_by_staff"].queryset.values_list("pk", flat=True)))
        self.assertIn(self.patient_profile.pk, set(form.base_fields["patient"].queryset.values_list("pk", flat=True)))

    def test_hospital_admin_user_type_has_same_hospital_scope(self):
        request = self.factory.get("/")
        request.user = self.hospital_admin_user

        user_admin = UserAdmin(User, self.site)
        queryset = user_admin.get_queryset(request)
        self.assertIn(self.hospital_admin_user.pk, set(queryset.values_list("pk", flat=True)))
        self.assertIn(self.patient_user.pk, set(queryset.values_list("pk", flat=True)))
        self.assertIn(self.staff_user_a.pk, set(queryset.values_list("pk", flat=True)))
        self.assertNotIn(self.staff_user_b.pk, set(queryset.values_list("pk", flat=True)))

        hospital_admin = HospitalAdmin(Hospital, self.site)
        self.assertEqual(hospital_admin.get_queryset(request).count(), 1)
        self.assertEqual(hospital_admin.get_queryset(request).first(), self.hospital_a)

    def test_patient_can_only_view_own_account_and_records(self):
        request = self.factory.get("/")
        request.user = self.patient_user

        user_admin = UserAdmin(User, self.site)
        self.assertEqual(user_admin.get_queryset(request).count(), 1)
        self.assertEqual(user_admin.get_queryset(request).first(), self.patient_user)

        patient_admin = PatientProfileAdmin(PatientProfile, self.site)
        self.assertEqual(patient_admin.get_queryset(request).count(), 1)
        self.assertEqual(patient_admin.get_queryset(request).first(), self.patient_profile)

        visit_admin = VisitAdmin(Visit, self.site)
        self.assertEqual(visit_admin.get_queryset(request).count(), 1)
        self.assertEqual(visit_admin.get_queryset(request).first(), self.visit)


class UniversalAdminLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="universal@demo.test",
            password="StrongPass123!",
            phone_number="+2348000000000",
            user_type=User.UserType.PATIENT,
            is_staff=True,
        )

    def test_admin_authentication_accepts_email_or_phone_number(self):
        self.assertIsNotNone(authenticate(username=self.user.email, password="StrongPass123!"))
        self.assertIsNotNone(authenticate(username=self.user.phone_number, password="StrongPass123!"))


class HospitalStaffCanCreateClinicalRecordsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()

        self.hospital = Hospital.objects.create(
            name="City Clinic",
            registration_number="HOSP-CITY-001",
            verification_status=Hospital.VerificationStatus.VERIFIED,
        )

        self.doctor_user = User.objects.create_user(
            email="doctor@city.test",
            password="StrongPass123!",
            phone_number="+2348000000100",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.doctor_profile = HospitalStaffProfile.objects.create(
            user=self.doctor_user,
            hospital=self.hospital,
            full_name="Dr. City",
            role=HospitalStaffProfile.Role.DOCTOR,
            professional_license_number="LIC-100",
        )

        self.patient_user = User.objects.create_user(
            email="patient@city.test",
            password="StrongPass123!",
            phone_number="+2348000000101",
            user_type=User.UserType.PATIENT,
            is_staff=True,
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            full_name="Jane Patient",
            date_of_birth=date(1990, 1, 1),
            account_type=PatientProfile.AccountType.SELF_MANAGED,
        )

        self.visit = Visit.objects.create(
            patient=self.patient_profile,
            hospital=self.hospital,
            created_by_staff=self.doctor_profile,
        )

    def test_hospital_staff_can_add_new_medical_record(self):
        request = self.factory.get("/")
        request.user = self.doctor_user

        medical_record_admin = MedicalRecordAdmin(MedicalRecord, self.site)
        self.assertTrue(medical_record_admin.has_add_permission(request))
        self.assertTrue(medical_record_admin.has_view_permission(request))

        form = medical_record_admin.get_form(request)
        self.assertEqual(form.base_fields["hospital"].initial, self.hospital.id)
        self.assertTrue(form.base_fields["hospital"].disabled)
        self.assertEqual(form.base_fields["verified_by_staff"].initial, self.doctor_profile.pk)
        self.assertTrue(form.base_fields["verified_by_staff"].disabled)
        self.assertEqual(form.base_fields["verification_status"].initial, MedicalRecord.VerificationStatus.DOCTOR_VERIFIED)
        self.assertTrue(form.base_fields["verification_status"].disabled)

    def test_hospital_staff_requires_approved_access_grant_to_view_patient_detail(self):
        request = self.factory.get("/")
        request.user = self.doctor_user

        patient_admin = PatientProfileAdmin(PatientProfile, self.site)
        self.assertIn(self.patient_profile, patient_admin.get_queryset(request))
        self.assertFalse(patient_admin.has_view_permission(request, self.patient_profile))

        access_request = AccessRequest.objects.create(
            visit=self.visit,
            patient=self.patient_profile,
            hospital=self.hospital,
            requested_by_staff=self.doctor_profile,
            request_type=AccessRequest.RequestType.NORMAL,
            access_level=AccessRequest.AccessLevel.FULL_RECORD,
            status=AccessRequest.Status.PENDING,
        )
        self.assertFalse(patient_admin.has_view_permission(request, self.patient_profile))

        access_request.status = AccessRequest.Status.APPROVED
        access_request.save(update_fields=["status"])
        AccessGrant.objects.create(
            access_request=access_request,
            access_level=AccessRequest.AccessLevel.FULL_RECORD,
            granted_by=AccessGrant.GrantedBy.PATIENT,
        )

        self.assertTrue(patient_admin.has_view_permission(request, self.patient_profile))

    def test_staff_access_request_form_defaults_to_own_hospital_and_staff(self):
        request = self.factory.get("/")
        request.user = self.doctor_user

        access_request_admin = AccessRequestAdmin(AccessRequest, self.site)
        form = access_request_admin.get_form(request)

        self.assertEqual(form.base_fields["hospital"].initial, self.hospital.id)
        self.assertTrue(form.base_fields["hospital"].disabled)
        self.assertEqual(form.base_fields["requested_by_staff"].initial, self.doctor_profile.pk)
        self.assertTrue(form.base_fields["requested_by_staff"].disabled)

    def test_only_superusers_and_hospital_staff_can_add_access_requests(self):
        staff_request = self.factory.get("/")
        staff_request.user = self.doctor_user

        patient_request = self.factory.get("/")
        patient_request.user = self.patient_user

        access_request_admin = AccessRequestAdmin(AccessRequest, self.site)

        self.assertTrue(access_request_admin.has_add_permission(staff_request))
        self.assertFalse(access_request_admin.has_add_permission(patient_request))


class HospitalStaffAndHospitalAdminPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()

        self.hospital_a = Hospital.objects.create(
            name="Alpha General",
            registration_number="HOSP-ALPHA-001",
            verification_status=Hospital.VerificationStatus.VERIFIED,
        )
        self.hospital_b = Hospital.objects.create(
            name="Beta General",
            registration_number="HOSP-BETA-001",
            verification_status=Hospital.VerificationStatus.VERIFIED,
        )

        self.hospital_admin_user = User.objects.create_user(
            email="admin@alpha.test",
            password="StrongPass123!",
            phone_number="+2348000000001",
            user_type=User.UserType.HOSPITAL_ADMIN,
            is_staff=True,
        )
        self.hospital_a.admin = self.hospital_admin_user
        self.hospital_a.save(update_fields=["admin"])

        self.hospital_admin_staff = User.objects.create_user(
            email="adminstaff@alpha.test",
            password="StrongPass123!",
            phone_number="+2348000000002",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.hospital_admin_staff_profile = HospitalStaffProfile.objects.create(
            user=self.hospital_admin_staff,
            hospital=self.hospital_a,
            full_name="Admin Staff",
            role=HospitalStaffProfile.Role.ADMIN,
        )

        self.regular_staff_user = User.objects.create_user(
            email="doctor@alpha.test",
            password="StrongPass123!",
            phone_number="+2348000000003",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.regular_staff_profile = HospitalStaffProfile.objects.create(
            user=self.regular_staff_user,
            hospital=self.hospital_a,
            full_name="Doctor One",
            role=HospitalStaffProfile.Role.DOCTOR,
            professional_license_number="LIC-001",
        )

        self.other_hospital_staff_user = User.objects.create_user(
            email="doctor@beta.test",
            password="StrongPass123!",
            phone_number="+2348000000004",
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        self.other_hospital_staff_profile = HospitalStaffProfile.objects.create(
            user=self.other_hospital_staff_user,
            hospital=self.hospital_b,
            full_name="Doctor Two",
            role=HospitalStaffProfile.Role.DOCTOR,
            professional_license_number="LIC-002",
        )

    def test_regular_hospital_staff_cannot_edit_their_role_or_hospital(self):
        request = self.factory.get("/")
        request.user = self.regular_staff_user

        hospital_admin = HospitalAdmin(Hospital, self.site)
        staff_admin = HospitalStaffProfileAdmin(HospitalStaffProfile, self.site)

        self.assertFalse(hospital_admin.has_change_permission(request, self.hospital_a))
        self.assertTrue(staff_admin.has_view_permission(request, self.regular_staff_profile))
        self.assertFalse(staff_admin.has_change_permission(request, self.regular_staff_profile))

        form = staff_admin.get_form(request, obj=self.regular_staff_profile)
        self.assertTrue(form.base_fields["role"].disabled)

    def test_hospital_admin_can_see_and_edit_all_staff_in_own_hospital_only(self):
        request = self.factory.get("/")
        request.user = self.hospital_admin_user

        hospital_admin = HospitalAdmin(Hospital, self.site)
        staff_admin = HospitalStaffProfileAdmin(HospitalStaffProfile, self.site)

        self.assertTrue(hospital_admin.has_change_permission(request, self.hospital_a))
        self.assertFalse(hospital_admin.has_change_permission(request, self.hospital_b))
        self.assertTrue(staff_admin.has_view_permission(request, self.regular_staff_profile))
        self.assertTrue(staff_admin.has_change_permission(request, self.regular_staff_profile))
        self.assertFalse(staff_admin.has_change_permission(request, self.other_hospital_staff_profile))

        form = staff_admin.get_form(request, obj=self.regular_staff_profile)
        self.assertFalse(form.base_fields["role"].disabled)
