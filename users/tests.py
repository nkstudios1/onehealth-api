from datetime import date

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from access.models import AccessRequest
from cards.models import PatientCard
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
