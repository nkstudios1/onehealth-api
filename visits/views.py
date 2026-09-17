from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.responses import success_response
from core.audit import log_event
from records.models import MedicalRecord
from records.serializers import MedicalRecordSerializer
from users.models import HospitalStaffProfile, PatientProfile
from users.permissions import IsFromVerifiedHospital, IsHospitalStaff, IsPatient

from .models import Medication, Vital, Visit
from .serializers import MedicationSerializer, StartVisitSerializer, VitalSerializer, VisitSerializer


def staff_for_request(request):
    return get_object_or_404(HospitalStaffProfile.objects.select_related("hospital"), user=request.user)


def hospital_staff_visit(request, visit_id):
    staff = staff_for_request(request)
    visit = get_object_or_404(Visit.objects.select_related("patient", "hospital"), pk=visit_id)
    if visit.hospital_id != staff.hospital_id:
        raise PermissionDenied("You can only access visits belonging to your hospital.")
    return staff, visit


@api_view(["POST"])
@permission_classes([IsHospitalStaff, IsFromVerifiedHospital])
def start_visit(request):
    serializer = StartVisitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    staff = staff_for_request(request)
    patient = get_object_or_404(PatientProfile, pk=serializer.validated_data["patient"])
    visit = Visit.objects.create(patient=patient, hospital=staff.hospital, created_by_staff=staff)
    log_event("visit_started", user_id=request.user, request=request, patient_id=visit.patient_id,
              hospital_id=visit.hospital_id, target_type="visit", target_id=visit.id)
    return success_response(VisitSerializer(visit).data, "Visit started successfully.", status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsHospitalStaff, IsFromVerifiedHospital])
def checkout_visit(request, visit_id):
    staff, visit = hospital_staff_visit(request, visit_id)
    if visit.status == Visit.Status.CHECKED_OUT:
        return success_response(VisitSerializer(visit).data, "Visit is already checked out.")
    visit.status = Visit.Status.CHECKED_OUT
    visit.checked_out_at = visit.checked_out_at or __import__("django.utils.timezone", fromlist=["now"]).now()
    visit.save(update_fields=["status", "checked_out_at"])
    from access.views import revoke_visit_grants
    revoke_visit_grants(visit)
    log_event("visit_checked_out", user_id=request.user, request=request, patient_id=visit.patient_id,
              hospital_id=visit.hospital_id, target_type="visit", target_id=visit.id)
    return success_response(VisitSerializer(visit).data, "Visit checked out successfully.")


@api_view(["GET"])
@permission_classes([IsPatient])
def my_visits(request):
    patient = get_object_or_404(PatientProfile, user=request.user)
    visits = patient.visits.select_related("hospital", "created_by_staff").all()
    return success_response(VisitSerializer(visits, many=True).data, "Visits retrieved successfully.")


@api_view(["POST"])
@permission_classes([IsPatient])
def request_checkout(request, visit_id):
    patient = get_object_or_404(PatientProfile, user=request.user)
    visit = get_object_or_404(Visit, pk=visit_id, patient=patient)
    if visit.status != Visit.Status.ACTIVE:
        raise PermissionDenied("Only active visits can receive a checkout request.")
    if visit.checkout_requested_by_patient_at is None:
        from django.utils import timezone
        visit.checkout_requested_by_patient_at = timezone.now()
        visit.save(update_fields=["checkout_requested_by_patient_at"])
    return success_response(VisitSerializer(visit).data, "Checkout request submitted successfully.")



@api_view(["GET", "POST"])
@permission_classes([IsHospitalStaff, IsFromVerifiedHospital])
def visit_records(request, visit_id):
    staff, visit = hospital_staff_visit(request, visit_id)
    if request.method == "GET":
        records = visit.medical_records.select_related("verified_by_staff", "created_by_staff", "hospital", "supersedes_entry")
        return success_response(MedicalRecordSerializer(records, many=True).data, "Visit medical records retrieved successfully.")

    entry_type = request.data.get("entry_type")
    description = request.data.get("description")
    if not entry_type or not description:
        raise ValidationError({
            "entry_type": "This field is required." if not entry_type else None,
            "description": "This field is required." if not description else None,
        })
    record = MedicalRecord.objects.create(
        patient=visit.patient,
        entry_type=entry_type,
        description=description,
        created_by_staff=staff,
        hospital=visit.hospital,
        visit=visit,
    )
    return success_response(MedicalRecordSerializer(record).data, "Medical record added successfully.", status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsHospitalStaff, IsFromVerifiedHospital])
def visit_vitals(request, visit_id):
    staff, visit = hospital_staff_visit(request, visit_id)
    if request.method == "GET":
        vitals = visit.vitals.select_related("recorded_by_staff")
        return success_response(VitalSerializer(vitals, many=True).data, "Vitals retrieved successfully.")
    serializer = VitalSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    vital = serializer.save(visit=visit, recorded_by_staff=staff)
    return success_response(VitalSerializer(vital).data, "Vitals recorded successfully.", status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsHospitalStaff, IsFromVerifiedHospital])
def visit_medications(request, visit_id):
    staff, visit = hospital_staff_visit(request, visit_id)
    if request.method == "GET":
        meds = visit.medications.select_related("prescribed_by_staff")
        return success_response(MedicationSerializer(meds, many=True).data, "Medications retrieved successfully.")
    serializer = MedicationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    medication = serializer.save(patient=visit.patient, visit=visit, prescribed_by_staff=staff)
    return success_response(MedicationSerializer(medication).data, "Medication recorded successfully.", status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsPatient])
def my_medications(request):
    patient = get_object_or_404(PatientProfile, user=request.user)
    medications = patient.medications.select_related("visit", "prescribed_by_staff").all()
    return success_response(MedicationSerializer(medications, many=True).data, "Medications retrieved successfully.")


