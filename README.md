# OneHealth

OneHealth is a secure healthcare administration platform built around role-aware access, patient privacy, and hospital operations. It is designed for a healthcare workflow where patients, hospital staff, hospital administrators, and platform administrators each interact with the system through different permissions and responsibilities.

## Overview

This project focuses on the operational and administrative side of a digital healthcare environment. Rather than treating all user roles as equal, the platform explicitly enforces ownership boundaries, hospital scoping, and patient-approved access before sensitive health data is visible.

The result is a healthcare admin experience that prioritizes:

- clear role separation
- consent-driven patient data access
- hospital-level governance
- safe staff workflows for clinical records and visits
- a clean Django admin interface tailored for healthcare operations

## Why this exists

Healthcare systems must be trusted with highly sensitive information. This project was designed to model a more responsible healthcare admin flow where:

- patients control who can access their health information
- hospital staff can only work within their assigned hospital context
- hospital admins can manage their hospital and their team
- platform administrators can supervise the broader system without bypassing patient consent boundaries
- clinical records are verified by authorized staff and remain auditable

## Core capabilities

### Role-based administration
- platform admin management
- hospital admin and hospital staff role handling
- patient profile management
- hospital-scoped permissions and access restrictions

### Patient and hospital onboarding
- patient self-registration
- hospital registration alongside first-admin setup
- staff onboarding for a specific hospital
- hospital verification workflow with pending or verified states

### Clinical workflow
- medical record creation and verification tracking
- visit management
- vitals tracking
- staff-led care management within authorized hospital contexts

### Patient consent and access management
- access requests created by staff for patient data
- patient approvals or rejections of access requests
- access grants that enforce actual data visibility rules
- patient-owned authorization flow for sensitive records

### Security and auditability
- hospital and staff scoping checks
- role restrictions on sensitive edits
- audit-oriented record and access logging
- protected detail access based on approved access grants

## Technology stack

- Python 3.14
- Django 6.1.1
- Django REST Framework
- JWT authentication via Simple JWT
- django-jazzmin for admin customizations
- drf-spectacular / Swagger documentation
- SQLite for local development
- QR code generation for patient card and access flows

## Primary app structure

- users: authentication, profile, hospital, and staff logic
- access: patient access requests, grants, and approval flow
- records: medical records and verification rules
- visits: patient visit records and related workflows
- cards: patient card generation and QR-based access coordination
- audit: append-only audit trails
- core: shared utilities, exceptions, responses, and helper logic
- onehealth: project settings and routing

## Key workflow examples

### Patient registration
A patient can register with their profile, contact information, and basic medical metadata. The profile is created alongside the account so the system maintains a consistent patient identity.

### Hospital registration
A new hospital is created with its own first admin account. The hospital starts in a pending verification state until it is explicitly reviewed and approved.

### Hospital staff creation
Hospital admins can create staff accounts for their own hospital. Staff roles may include administrative and clinical responsibilities, and doctors are required to provide a professional license number when applicable.

### Access requests
Staff members can request patient access through an explicit workflow. The request is not enough by itself to grant visibility; it must be accepted by the patient and translated into an active access grant before sensitive data can be viewed in detail.

### Medical record verification
Clinical records are managed in a controlled way, with verification requirements tied to authorized staff roles and record integrity checks.

## Security model

The project follows a patient-first data protection model:

- visibility is not assumed by hospital membership alone
- staff access to patient detail is gated by explicit approval
- hospital boundaries prevent cross-hospital viewing
- role restrictions reduce the chance of unauthorized edits
- audit and verification logic preserve accountability

This is especially important in healthcare, where open data visibility is not a safe default.

## Getting started

### Prerequisites
- Python 3.14
- pip or pipenv
- a local virtual environment

### Install dependencies

```bash
pip install -r requirements.txt
```

Or with Pipenv:

```bash
pipenv install
pipenv shell
```

### Run database migrations

```bash
python manage.py migrate
```

### Create a superuser

```bash
python manage.py createsuperuser
```

### Start the local server

```bash
python manage.py runserver
```

## Admin and navigation

The project is structured around a Django admin experience with custom role-aware navigation and permissions. It includes model management, hospital filtering, and routed views for different user types so the admin interface behaves differently depending on the logged-in user.

## Current implementation status

This repository represents an active healthcare admin and access-control implementation rather than a static prototype. The platform includes custom registration, authentication, hospital and staff management, patient approval workflow, record handling, and role-aware visibility controls.

This project is best understood as a secure healthcare admin layer with patient-controlled access governance and hospital-specific operational workflows.

## Notes

- The design is intentionally centered on controlled access to sensitive medical information.
- The access model is purposely stricter than a generic hospital dashboard, because patient approval is treated as a critical permission boundary.
- Some production-grade integrations, such as external notification delivery or external verification services, may still require dedicated implementation depending on deployment needs.

## License

This project is provided for internal project and portfolio use. Update the license terms as needed before production deployment or redistribution.
