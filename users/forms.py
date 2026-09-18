from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Hospital, HospitalStaffProfile, PatientProfile, User


class PatientRegistrationForm(forms.Form):
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", widget=forms.PasswordInput(render_value=False))
    phone_number = forms.CharField(label="Phone number")
    full_name = forms.CharField(label="Full name")
    date_of_birth = forms.DateField(label="Date of birth", widget=forms.DateInput(attrs={"type": "date"}))
    gender = forms.CharField(label="Gender", required=False)
    blood_type = forms.CharField(label="Blood type", required=False)

    def clean_email(self):
        value = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return value

    def clean_phone_number(self):
        value = self.cleaned_data["phone_number"].strip()
        if User.objects.filter(phone_number=value).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return value

    def clean_password(self):
        value = self.cleaned_data["password"]
        validate_password(value)
        return value

    def save(self):
        user = User.objects.create_user(
            full_name=self.cleaned_data["full_name"],
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            phone_number=self.cleaned_data["phone_number"],
            user_type=User.UserType.PATIENT,
            is_staff=True,
        )
        profile = PatientProfile.objects.create(
            user=user,
            full_name=self.cleaned_data["full_name"],
            date_of_birth=self.cleaned_data["date_of_birth"],
            gender=self.cleaned_data.get("gender", ""),
            blood_type=self.cleaned_data.get("blood_type", ""),
            account_type=PatientProfile.AccountType.SELF_MANAGED,
        )
        return user


class HospitalRegistrationForm(forms.Form):
    hospital_name = forms.CharField(label="Hospital name")
    registration_number = forms.CharField(label="Registration number")
    phermc_number = forms.CharField(label="PHERMC number", required=False)
    cac_number = forms.CharField(label="CAC number", required=False)
    address = forms.CharField(label="Hospital address", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    admin_email = forms.EmailField(label="Admin email")
    admin_password = forms.CharField(label="Admin password", widget=forms.PasswordInput(render_value=False))
    admin_full_name = forms.CharField(label="Admin full name")
    admin_phone_number = forms.CharField(label="Admin phone number")

    def clean_hospital_name(self):
        value = self.cleaned_data["hospital_name"].strip()
        if Hospital.objects.filter(name=value).exists():
            raise forms.ValidationError("A hospital with this name already exists.")
        return value

    def clean_registration_number(self):
        value = self.cleaned_data["registration_number"].strip()
        if Hospital.objects.filter(registration_number=value).exists():
            raise forms.ValidationError("A hospital with this registration number already exists.")
        return value

    def clean_phermc_number(self):
        value = self.cleaned_data.get("phermc_number", "").strip()
        if value and Hospital.objects.filter(phermc_number=value).exists():
            raise forms.ValidationError("A hospital with this PHERMC number already exists.")
        return value

    def clean_cac_number(self):
        value = self.cleaned_data.get("cac_number", "").strip()
        if value and Hospital.objects.filter(cac_number=value).exists():
            raise forms.ValidationError("A hospital with this CAC number already exists.")
        return value

    def clean_admin_email(self):
        value = self.cleaned_data["admin_email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return value

    def clean_admin_phone_number(self):
        value = self.cleaned_data["admin_phone_number"].strip()
        if User.objects.filter(phone_number=value).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return value

    def clean_admin_password(self):
        value = self.cleaned_data["admin_password"]
        validate_password(value)
        return value

    def save(self):
        hospital = Hospital.objects.create(
            name=self.cleaned_data["hospital_name"],
            registration_number=self.cleaned_data["registration_number"],
            phermc_number=self.cleaned_data.get("phermc_number", ""),
            cac_number=self.cleaned_data.get("cac_number", ""),
            address=self.cleaned_data.get("address", ""),
            verification_status=Hospital.VerificationStatus.PENDING,
        )
        admin_user = User.objects.create_user(
            email=self.cleaned_data["admin_email"],
            password=self.cleaned_data["admin_password"],
            phone_number=self.cleaned_data["admin_phone_number"],
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        staff_profile = HospitalStaffProfile.objects.create(
            user=admin_user,
            hospital=hospital,
            full_name=self.cleaned_data["admin_full_name"],
            role=HospitalStaffProfile.Role.ADMIN,
        )
        hospital.admin = admin_user
        hospital.save(update_fields=["admin"])
        return hospital


class HospitalStaffRegistrationForm(forms.Form):
    hospital = forms.ModelChoiceField(label="Hospital", queryset=Hospital.objects.all())
    email = forms.EmailField(label="Staff email")
    password = forms.CharField(label="Password", widget=forms.PasswordInput(render_value=False))
    phone_number = forms.CharField(label="Phone number")
    full_name = forms.CharField(label="Full name")
    role = forms.ChoiceField(label="Role", choices=HospitalStaffProfile.Role.choices)
    professional_license_number = forms.CharField(label="Professional license number", required=False)

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return value

    def clean_phone_number(self):
        value = self.cleaned_data["phone_number"].strip()
        if User.objects.filter(phone_number=value).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return value

    def clean_password(self):
        value = self.cleaned_data["password"]
        validate_password(value)
        return value

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        if role == HospitalStaffProfile.Role.DOCTOR and not cleaned_data.get("professional_license_number"):
            self.add_error(
                "professional_license_number",
                "Professional license number is required for doctors.",
            )
        return cleaned_data

    def save(self):
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            phone_number=self.cleaned_data["phone_number"],
            user_type=User.UserType.HOSPITAL_STAFF,
            is_staff=True,
        )
        staff_profile = HospitalStaffProfile.objects.create(
            user=user,
            hospital=self.cleaned_data["hospital"],
            full_name=self.cleaned_data["full_name"],
            role=self.cleaned_data["role"],
            professional_license_number=self.cleaned_data.get("professional_license_number", ""),
        )
        return staff_profile
