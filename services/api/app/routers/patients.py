from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from ..audit import audit
from ..db import get_db
from ..models import (Patient, CareGrant, Consent, Allergy, Condition, Medication, Appointment, Reading, User,
                      utcnow)
from ..permissions import (require_patient, accessible_patient_ids, can_manage_sharing, DEFAULT_GRANT_SCOPES,
                           ROLE_CAPABILITIES, SCOPES, is_self)
from ..schemas import PatientIn, PatientUpdate, GrantIn, ConsentIn, AllergyIn, ConditionIn
from ..security import current_user

router = APIRouter(tags=["patients"])


def patient_out(p: Patient, user: User | None = None) -> dict:
    return {"id": p.id, "name": p.name, "date_of_birth": p.date_of_birth, "sex": p.sex, "notes": p.notes,
            "emergency_contact": p.emergency_contact, "is_self": bool(user and is_self(p, user))}


def full_record(db: Session, p: Patient) -> dict:
    return {"patient": patient_out(p),
            "allergies": [allergy_out(a) for a in db.scalars(select(Allergy).where(Allergy.patient_id == p.id))],
            "conditions": [condition_out(c) for c in db.scalars(select(Condition).where(Condition.patient_id == p.id))],
            "medications": [{"name": m.name, "dose": m.dose, "frequency": m.frequency, "status": m.status}
                            for m in db.scalars(select(Medication).where(Medication.patient_id == p.id))],
            "appointments": [{"clinician": a.clinician, "purpose": a.purpose, "scheduled_at": a.scheduled_at,
                              "status": a.status} for a in db.scalars(select(Appointment).where(Appointment.patient_id == p.id))],
            "readings": [{"kind": r.kind, "value": r.value, "unit": r.unit, "recorded_at": r.recorded_at}
                         for r in db.scalars(select(Reading).where(Reading.patient_id == p.id))]}


def allergy_out(a): return {"id": a.id, "substance": a.substance, "reaction": a.reaction, "severity": a.severity}
def condition_out(c): return {"id": c.id, "name": c.name, "code": c.code, "status": c.status, "onset_date": c.onset_date}


@router.get("/patients")
def list_patients(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = accessible_patient_ids(db, user)
    if not ids:
        return []
    return [patient_out(p, user) for p in db.scalars(select(Patient).where(Patient.id.in_(ids)).order_by(Patient.id))]


@router.post("/patients", status_code=201)
def create_patient(data: PatientIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Caregivers/clinicians create records for people without their own account; creator gets a grant."""
    if user.role not in ("caregiver", "clinician"):
        raise HTTPException(403, "Caregiver or clinician role required")
    p = Patient(**data.model_dump(), created_by=user.id)
    db.add(p); db.commit()
    rel = "clinician" if user.role == "clinician" else "caregiver"
    c = Consent(patient_id=p.id, kind="data_sharing", policy_version="2026-01", granted=True, recorded_by=user.id,
                detail=f"Recorded by {rel} on behalf of patient; confirm consent documentation offline")
    db.add(c); db.commit()
    db.add(CareGrant(patient_id=p.id, grantee_id=user.id, relationship=rel, granted_by=user.id, consent_id=c.id,
                     scopes=",".join(sorted(DEFAULT_GRANT_SCOPES[rel] | {"profile:write"}))))
    db.commit()
    audit(db, user.id, "create", "patient", p.id, p.id, request)
    return patient_out(p, user)


@router.get("/patients/{pid}")
def get_patient(pid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:read")
    audit(db, user.id, "view", "patient", pid, pid, request)
    return patient_out(p, user)


@router.patch("/patients/{pid}")
def update_patient(pid: int, data: PatientUpdate, request: Request, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:write")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); audit(db, user.id, "update", "patient", pid, pid, request)
    return patient_out(p, user)


@router.get("/patients/{pid}/record")
def get_record(pid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "records:read")
    audit(db, user.id, "view_full_record", "patient", pid, pid, request)
    return full_record(db, p)


# ---- Care team / consent-backed sharing ----
@router.get("/patients/{pid}/grants")
def list_grants(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:read")
    if not can_manage_sharing(db, user, p):
        raise HTTPException(403, "Only the patient or their record owner can view sharing")
    rows = db.scalars(select(CareGrant).where(CareGrant.patient_id == pid).order_by(desc(CareGrant.id)))
    out = []
    for g in rows:
        u = db.get(User, g.grantee_id)
        out.append({"id": g.id, "grantee": {"id": u.id, "name": u.name, "email": u.email, "role": u.role},
                    "relationship": g.relationship, "scopes": g.scopes.split(","), "expires_at": g.expires_at,
                    "revoked_at": g.revoked_at, "created_at": g.created_at})
    return out


@router.post("/patients/{pid}/grants", status_code=201)
def create_grant(pid: int, data: GrantIn, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:read")
    if not can_manage_sharing(db, user, p):
        raise HTTPException(403, "Only the patient can share their record")
    grantee = db.scalar(select(User).where(User.email == data.grantee_email.lower(), User.is_active.is_(True)))
    if not grantee or grantee.id == user.id:
        raise HTTPException(404, "No eligible user with that email")
    if data.relationship == "clinician" and grantee.role != "clinician":
        raise HTTPException(400, "That account is not a clinician")
    if grantee.role == "admin":
        raise HTTPException(400, "Administrators cannot receive clinical grants")
    scopes = set(data.scopes or DEFAULT_GRANT_SCOPES[data.relationship])
    if not scopes <= SCOPES:
        raise HTTPException(422, "Unknown scope")
    scopes &= ROLE_CAPABILITIES.get(grantee.role, set())
    consent = Consent(patient_id=pid, kind="data_sharing", policy_version="2026-01", granted=True, recorded_by=user.id,
                      detail=f"Shared with user {grantee.id} as {data.relationship}: {','.join(sorted(scopes))}")
    db.add(consent); db.commit()
    existing = db.scalar(select(CareGrant).where(CareGrant.patient_id == pid, CareGrant.grantee_id == grantee.id))
    if existing:
        existing.scopes, existing.relationship, existing.revoked_at = ",".join(sorted(scopes)), data.relationship, None
        existing.expires_at, existing.consent_id, existing.granted_by = data.expires_at, consent.id, user.id
        g = existing
    else:
        g = CareGrant(patient_id=pid, grantee_id=grantee.id, relationship=data.relationship,
                      scopes=",".join(sorted(scopes)), granted_by=user.id, consent_id=consent.id, expires_at=data.expires_at)
        db.add(g)
    db.commit()
    audit(db, user.id, "grant_access", "care_grant", g.id, pid, request)
    return {"id": g.id, "scopes": sorted(scopes)}


@router.delete("/patients/{pid}/grants/{gid}")
def revoke_grant(pid: int, gid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:read")
    g = db.get(CareGrant, gid)
    if not g or g.patient_id != pid:
        raise HTTPException(404, "Grant not found")
    if not (can_manage_sharing(db, user, p) or g.grantee_id == user.id):
        raise HTTPException(403, "Not permitted")
    g.revoked_at = utcnow(); db.commit()
    audit(db, user.id, "revoke_access", "care_grant", gid, pid, request)
    return {"ok": True}


@router.get("/patients/{pid}/consents")
def list_consents(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "profile:read")
    return [{"id": c.id, "kind": c.kind, "granted": c.granted, "policy_version": c.policy_version, "detail": c.detail,
             "created_at": c.created_at, "withdrawn_at": c.withdrawn_at}
            for c in db.scalars(select(Consent).where(Consent.patient_id == pid).order_by(desc(Consent.id)))]


@router.post("/patients/{pid}/consents", status_code=201)
def record_consent(pid: int, data: ConsentIn, request: Request, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = require_patient(db, user, pid, "profile:read")
    if not can_manage_sharing(db, user, p):
        raise HTTPException(403, "Only the patient can change consent")
    c = Consent(patient_id=pid, recorded_by=user.id, **data.model_dump())
    db.add(c); db.commit()
    if data.kind == "data_sharing" and not data.granted:  # withdrawal revokes all third-party access
        for g in db.scalars(select(CareGrant).where(CareGrant.patient_id == pid, CareGrant.revoked_at.is_(None),
                                                    CareGrant.grantee_id != user.id)):
            g.revoked_at = utcnow()
        db.commit()
    audit(db, user.id, "consent_" + ("grant" if data.granted else "withdraw"), "consent", c.id, pid, request)
    return {"id": c.id}


def has_consent(db: Session, pid: int, kind: str) -> bool:
    c = db.scalar(select(Consent).where(Consent.patient_id == pid, Consent.kind == kind).order_by(desc(Consent.id)).limit(1))
    return bool(c and c.granted)


# ---- Health records: allergies & conditions ----
@router.get("/patients/{pid}/allergies")
def allergies(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "records:read")
    return [allergy_out(a) for a in db.scalars(select(Allergy).where(Allergy.patient_id == pid))]


@router.post("/patients/{pid}/allergies", status_code=201)
def add_allergy(pid: int, data: AllergyIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "records:write")
    a = Allergy(patient_id=pid, recorded_by=user.id, **data.model_dump()); db.add(a); db.commit()
    audit(db, user.id, "create", "allergy", a.id, pid, request)
    return allergy_out(a)


@router.get("/patients/{pid}/conditions")
def conditions(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "records:read")
    return [condition_out(c) for c in db.scalars(select(Condition).where(Condition.patient_id == pid))]


@router.post("/patients/{pid}/conditions", status_code=201)
def add_condition(pid: int, data: ConditionIn, request: Request, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    require_patient(db, user, pid, "records:write")
    c = Condition(patient_id=pid, recorded_by=user.id, **data.model_dump()); db.add(c); db.commit()
    audit(db, user.id, "create", "condition", c.id, pid, request)
    return condition_out(c)


@router.get("/patients/{pid}/fhir")
def fhir_export(pid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Minimal FHIR R4 Bundle for interoperability (Patient, AllergyIntolerance, Condition, MedicationStatement, Observation)."""
    p = require_patient(db, user, pid, "records:read")
    entries = [{"resource": {"resourceType": "Patient", "id": str(p.id), "name": [{"text": p.name}],
                             **({"birthDate": p.date_of_birth.isoformat()} if p.date_of_birth else {})}}]
    for a in db.scalars(select(Allergy).where(Allergy.patient_id == pid)):
        entries.append({"resource": {"resourceType": "AllergyIntolerance", "id": f"a{a.id}", "patient": {"reference": f"Patient/{p.id}"},
                                     "code": {"text": a.substance}, "criticality": "high" if a.severity == "severe" else "low"}})
    for c in db.scalars(select(Condition).where(Condition.patient_id == pid)):
        entries.append({"resource": {"resourceType": "Condition", "id": f"c{c.id}", "subject": {"reference": f"Patient/{p.id}"},
                                     "code": {"text": c.name, **({"coding": [{"code": c.code}]} if c.code else {})},
                                     "clinicalStatus": {"text": c.status}}})
    for m in db.scalars(select(Medication).where(Medication.patient_id == pid)):
        entries.append({"resource": {"resourceType": "MedicationStatement", "id": f"m{m.id}", "subject": {"reference": f"Patient/{p.id}"},
                                     "status": "active" if m.status == "active" else "stopped",
                                     "medicationCodeableConcept": {"text": m.name}, "dosage": [{"text": f"{m.dose} {m.frequency}"}]}})
    for r in db.scalars(select(Reading).where(Reading.patient_id == pid).order_by(desc(Reading.recorded_at)).limit(500)):
        entries.append({"resource": {"resourceType": "Observation", "id": f"o{r.id}", "status": "final",
                                     "subject": {"reference": f"Patient/{p.id}"}, "code": {"text": r.kind},
                                     "effectiveDateTime": r.recorded_at.isoformat() + "Z",
                                     "valueQuantity": {"value": r.value, "unit": r.unit}}})
    audit(db, user.id, "export_fhir", "patient", pid, pid, request)
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}
