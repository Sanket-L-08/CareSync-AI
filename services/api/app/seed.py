"""Synthetic demo data for local development only (refused in production by config validation)."""
from datetime import timedelta
from sqlalchemy import select
from .db import SessionLocal
from .models import User, Patient, Medication, Appointment, Reading, Allergy, Condition, Consent, CareGrant, utcnow
from .permissions import DEFAULT_GRANT_SCOPES
from .security import hash_password

PW = "CareSyncDemo!2026"


def seed():
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.email == "demo@example.com")):
            return
        pat = User(name="Alex Morgan", email="demo@example.com", password_hash=hash_password(PW), role="patient")
        cg = User(name="Sam Carer", email="caregiver@example.com", password_hash=hash_password(PW), role="caregiver")
        doc = User(name="Dr. Demo", email="clinician@example.com", password_hash=hash_password(PW), role="clinician",
                   is_verified_clinician=True)
        adm = User(name="Admin", email="admin@example.com", password_hash=hash_password(PW), role="admin")
        db.add_all([pat, cg, doc, adm]); db.commit()
        p = Patient(name="Alex Morgan", owner_id=pat.id, created_by=pat.id, notes="Synthetic demo patient")
        db.add(p); db.commit()
        db.add_all([Consent(patient_id=p.id, kind="data_sharing", policy_version="2026-01", granted=True, recorded_by=pat.id),
                    Consent(patient_id=p.id, kind="ai_processing", policy_version="2026-01", granted=True, recorded_by=pat.id)])
        db.add_all([CareGrant(patient_id=p.id, grantee_id=cg.id, relationship="caregiver", granted_by=pat.id,
                              scopes=",".join(sorted(DEFAULT_GRANT_SCOPES["caregiver"]))),
                    CareGrant(patient_id=p.id, grantee_id=doc.id, relationship="clinician", granted_by=pat.id,
                              scopes=",".join(sorted(DEFAULT_GRANT_SCOPES["clinician"])))])
        db.add_all([
            Allergy(patient_id=p.id, substance="Penicillin", reaction="Rash", severity="moderate", recorded_by=pat.id),
            Condition(patient_id=p.id, name="Hypertension", code="I10", recorded_by=doc.id),
            Medication(patient_id=p.id, name="Example medication A", dose="1 tablet", frequency="Once daily",
                       schedule_times="08:00", created_by=doc.id, verified_by=doc.id),
            Appointment(patient_id=p.id, clinician="Dr. Demo", purpose="Routine review", created_by=pat.id,
                        scheduled_at=utcnow() + timedelta(days=3)),
            Reading(patient_id=p.id, kind="heart_rate", value=72, unit="bpm", recorded_by=pat.id),
            Reading(patient_id=p.id, kind="spo2", value=98, unit="%", recorded_by=pat.id),
            Reading(patient_id=p.id, kind="blood_pressure_systolic", value=128, unit="mmHg", recorded_by=pat.id),
        ])
        db.commit()
    finally:
        db.close()
