# ============================================================================
# PASTE / MERGE THESE INTO YOUR PROJECT'S ROOT urls.py
# (the urls.py next to settings.py, not users/urls.py)
# This file is NOT imported automatically — it's a reference to copy from.
# ============================================================================

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),

    # --- Auth module ---
    path("api/v1/auth/", include("users.urls")),

    # --- API docs ---
    # /api/schema/             -> raw OpenAPI schema (JSON/YAML) — what tools like
    #                             Postman or a frontend codegen step would import
    # /api/schema/swagger-ui/  -> interactive Swagger UI — click "Authorize", paste
    #                             a Bearer token, and try any endpoint from the browser
    # /api/schema/redoc/       -> a cleaner read-only reference view, nicer to link
    #                             teammates or reviewers to than Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
