from django.urls import path

from . import views

# Mount this in your project's root urls.py, e.g.:
#   path("api/v1/auth/", include("users.urls"))

urlpatterns = [
    # --- Registration ---
    path("register/patient/", views.register_patient, name="register-patient"),
    path("register/hospital/", views.register_hospital, name="register-hospital"),

    # --- Dependents (nested under patient, but kept here for auth-app cohesion) ---
    path("patients/me/dependents/", views.register_dependent, name="register-dependent"),

    # --- Hospital staff management ---
    path("hospitals/me/staff/", views.create_hospital_staff, name="hospital-staff-create"),

    # --- Login / token lifecycle ---
    path("login/", views.login_view, name="login"),
    path("login/refresh/", views.refresh_token_view, name="login-refresh"),
    path("logout/", views.logout_view, name="logout"),

    # --- Profile ---
    path("me/", views.me_view, name="me"),

    # --- Password management ---
    path("change-password/", views.change_password_view, name="change-password"),
    path("password-reset/", views.request_password_reset_view, name="password-reset"),
    path(
        "password-reset/confirm/",
        views.confirm_password_reset_view,
        name="password-reset-confirm",
    ),
]
