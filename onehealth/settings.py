# ============================================================================
# PASTE / MERGE THESE INTO YOUR PROJECT'S settings.py
# This file is NOT imported automatically — it's a reference to copy from.
# ============================================================================

import os
from datetime import timedelta

INSTALLED_APPS = [
    # ... your existing default apps (admin, auth, contenttypes, etc.) ...
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",  # required for logout_view to work
    "drf_spectacular",  # generates the OpenAPI schema behind Swagger UI / ReDoc

    "core",   # shared response envelope, exception handler, messages, audit log
    "users",  # our custom auth app — MUST be listed before any app that
              # imports from it, and migrations for it should run FIRST
]

# ----------------------------------------------------------------------------
# THIS IS THE MOST IMPORTANT LINE IN THIS ENTIRE FILE.
# Tells Django "when anything says User, it means users.CustomUser" — this
# must be set BEFORE your first migration, and cannot be safely changed
# after the database has real data in it. Do not skip this.
# ----------------------------------------------------------------------------
AUTH_USER_MODEL = "users.CustomUser"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        # Every endpoint requires login UNLESS explicitly marked AllowAny
        # (registration, login, password reset). This is the safer
        # default for a medical records API — nothing is accidentally
        # left open.
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/day",
        "anon": "100/day",
        "registration": "10/hour",   # matches RegistrationThrottle.scope in views.py
        "login": "20/hour",          # matches LoginThrottle.scope in views.py
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,

    # --- Consistent error shape + Swagger schema (see core/exceptions.py) ---
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ----------------------------------------------------------------------------
# SWAGGER / OPENAPI DOCS (drf-spectacular)
# Served at /api/schema/swagger-ui/ and /api/schema/redoc/ once you add the
# paths from project_urls_snippet.py to your root urls.py.
# ----------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "OneHealth API",
    "DESCRIPTION": (
        "Authentication and identity for the OneHealth platform. "
        "Every endpoint returns the standard envelope described in "
        "core/responses.py: `{success, message, data}` on success, "
        "`{success, code, message, errors}` on failure."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Adds the "Authorize" button in Swagger UI so a JWT can be attached to
    # every subsequent try-it-out request in one place.
    "SECURITY": [{"bearerAuth": []}],
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
    "COMPONENT_SPLIT_REQUEST": True,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    # Short-lived on purpose — this is a medical records system. If an
    # access token leaks, 15 minutes limits the blast radius.
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Combined with ROTATE_REFRESH_TOKENS, this means a refresh token can
    # only be used ONCE — if someone steals an old one and tries to reuse
    # it after the legitimate user already rotated it, it's rejected.
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": None,  # defaults to Django's SECRET_KEY — fine for now,
                          # consider a dedicated signing key for real production
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Password strength rules — applied via validate_password() in our
# serializers. Adjust MinimumLengthValidator's min_length if 8 feels too
# short for a medical system (10-12 is reasonable).
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ----------------------------------------------------------------------------
# LOGGING
# WHY: core.exceptions logs every unhandled exception with `logger.exception`
# (full traceback), and core.audit logs auth events (logins, registrations,
# password changes) — both need somewhere to actually go, or they're
# silently dropped with Django's default logging config. Console output is
# fine for local dev; in real production point the handler at a file or a
# log-aggregation service instead.
#
# NEVER add request bodies or headers to this config's formatters — that's
# exactly how a password or JWT ends up sitting in a log file.
# ----------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "onehealth.api": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "onehealth.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

# ----------------------------------------------------------------------------
# DO NOT hardcode SECRET_KEY, DB credentials, or email credentials here or
# anywhere committed to git. Load them from environment variables
# (os.environ / django-environ / python-decouple) — flagging this since
# it's the #1 thing that trips up student teams under time pressure.
# ----------------------------------------------------------------------------
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # fail loudly if missing rather than fall back to a default
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

# ----------------------------------------------------------------------------
# PRODUCTION HARDENING — everything below should be True/enforced whenever
# DEBUG is False. A medical system carries PHI; these are not optional
# extras once this is live behind a real domain with HTTPS.
# ----------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days — raise once you're confident, per Django's HSTS guidance
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
# DEBUG=True on a live medical system would leak stack traces (SQL, file
# paths, settings values) to anyone who can trigger a 500 — double-check
# your deployment's DJANGO_DEBUG env var is unset/"False" before going live.
