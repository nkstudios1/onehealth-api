from rest_framework import serializers

from .models import MedicalRecord


class MedicalRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalRecord
        fields = [
            "id",
            "patient",
            "entry_type",
            "description",
            "verification_status",
            "verified_by_staff",
            "created_by_staff",
            "hospital",
            "visit",
            "supersedes_entry",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "patient",
            "verification_status",
            "verified_by_staff",
            "created_by_staff",
            "hospital",
            "visit",
            "created_at",
        ]


class PatientMedicalRecordCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalRecord
        fields = ["entry_type", "description", "supersedes_entry"]

    def validate_supersedes_entry(self, value):
        patient = self.context["patient"]
        if value and value.patient_id != patient.id:
            raise serializers.ValidationError("You can only supersede one of your own records.")
        return value
