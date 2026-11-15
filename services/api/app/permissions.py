"""RBAC + patient-level permissions.

Access to a patient record requires BOTH:
  1. the user's role allows the action (ROLE_CAPABILITIES), and
  2. a patient relationship: the patient themself, or an active, unexpired,
     non-revoked CareGrant whose scopes include the needed scope.
Admins manage accounts but do NOT get clinical data access by default (least privilege);
an emergency "break-glass" grant is possible and heavily audited.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Patient, CareGrant, User, utcnow

SCOPES = {
    "profile:read", "profile:write",
    "meds:read", "meds:write", "meds:verify",
    "doses:write",
    "vitals:read", "vitals:write", "thresholds:write",
    "appointments:read", "appointments:write",
    "records:read", "records:write",
    "notes:read", "notes:write",
    "documents:read", "documents:write",
    "alerts:read", "alerts:ack",
    "tasks:read", "tasks:write",
    "ai:use", "audit:read",
}

ROLE_CAPABILITIES: dict[str, set[str]] = {
    "patient": SCOPES - {"meds:verify", "thresholds:write", "notes:write"},
    "caregiver": {"profile:read", "meds:read", "meds:write", "doses:write", "vitals:read", "vitals:write",
                  "appointments:read", "appointments:write", "records:read", "documents:read",
                  "documents:write", "alerts:read", "alerts:ack", "tasks:read", "tasks:write", "ai:use",
                  "notes:read"},
    "clinician": set(SCOPES),
    "admin": set(),  # account administration only; clinical access needs break-glass grant
}

DEFAULT_GRANT_SCOPES = {
    "caregiver": ROLE_CAPABILITIES["caregiver"],
    "family": {"profile:read", "meds:read", "appointments:read", "alerts:read", "vitals:read"},
    "clinician": ROLE_CAPABILITIES["clinician"] - {"audit:read"},
}


def active_grant(db: Session, user: User, patient_id: int) -> CareGrant | None:
    g = db.scalar(select(CareGrant).where(CareGrant.patient_id == patient_id, CareGrant.grantee_id == user.id,
                                          CareGrant.revoked_at.is_(None)))
    if g and g.expires_at and g.expires_at < utcnow():
        return None
    return g


def is_self(patient: Patient, user: User) -> bool:
    return patient.owner_id is not None and patient.owner_id == user.id


def require_patient(db: Session, user: User, patient_id: int, scope: str) -> Patient:
    """Raise 404 (not 403) for inaccessible patients to avoid record enumeration."""
    if scope not in SCOPES:
        raise RuntimeError(f"unknown scope {scope}")
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    if is_self(patient, user):
        if scope in ROLE_CAPABILITIES["patient"]:
            return patient
        raise HTTPException(403, "This action requires a clinician")
    grant = active_grant(db, user, patient_id)
    if not grant:
        raise HTTPException(404, "Patient not found")
    role_caps = ROLE_CAPABILITIES.get(user.role, set())
    if user.role == "admin" and grant.relationship == "break_glass":
        role_caps = ROLE_CAPABILITIES["clinician"]
    if scope not in role_caps or scope not in set(grant.scopes.split(",")):
        raise HTTPException(403, "You do not have permission for this action on this patient")
    if scope.startswith(("meds:verify", "notes:write", "thresholds:write")) and not user.is_verified_clinician:
        raise HTTPException(403, "Clinician identity must be verified by an administrator")
    return patient


def accessible_patient_ids(db: Session, user: User) -> list[int]:
    ids = set(db.scalars(select(Patient.id).where(Patient.owner_id == user.id)).all())
    now = utcnow()
    for g in db.scalars(select(CareGrant).where(CareGrant.grantee_id == user.id, CareGrant.revoked_at.is_(None))):
        if not g.expires_at or g.expires_at > now:
            ids.add(g.patient_id)
    return sorted(ids)


def can_manage_sharing(db: Session, user: User, patient: Patient) -> bool:
    """The patient (or a creating caregiver for patients without their own account) controls sharing."""
    if is_self(patient, user):
        return True
    if patient.owner_id is None and patient.created_by == user.id:
        return True
    return False
