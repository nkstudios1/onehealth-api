"""
Structured audit logging for auth-relevant events.

WHY: for a medical records system, "who created this account, and when"
is not a nice-to-have — it's part of the accountability trail a clinical
safety review or an incident investigation will ask for (e.g. "who added
this doctor's account?", "when was this hospital's staff account
created?"). Regular Django request logs don't capture this in a
queryable, consistent way.

RULES for what goes in an audit record:
  - User id (UUID) and email: fine — these identify the actor/subject,
    which is the whole point of an audit trail.
  - NEVER a password, temp password, or token, in any form — not even
    partially or hashed-and-truncated. If you're tempted to log
    "for debugging", log the user id instead and look the rest up.
  - NEVER raw request bodies — they may contain the fields above.

This writes to the same logger the rest of the app uses
("onehealth.api"), tagged so they're easy to filter/ship to a separate
audit sink later (e.g. a SIEM) without changing call sites.
"""

import logging

logger = logging.getLogger("onehealth.audit")


def log_event(event: str, *, user_id=None, email=None, **extra):
    """
    event: short, stable string, e.g. "patient_registered", "login_success",
           "staff_created", "password_changed".
    user_id / email: identify who the event is about. Pass whichever you
           have — for pre-login events (e.g. a registration) you'll only
           have email; for authenticated actions you'll have both.
    extra: any additional non-sensitive context (e.g. hospital_id, role).
           Double-check before adding a new field here that it isn't a
           secret or PHI.
    """
    logger.info(
        "AUDIT event=%s user_id=%s email=%s %s",
        event,
        user_id,
        email,
        " ".join(f"{k}={v}" for k, v in extra.items()),
    )
