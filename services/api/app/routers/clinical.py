"""Medications, doses, appointments, monitoring, alerts, notes, tasks."""
import json
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from ..audit import audit
from ..db import get_db
from ..jobs import enqueue, notify_alert
from ..models import (Medication, DoseEvent, Appointment, Reading, AlertThreshold, Alert, ClinicalNote, CareTask,
                      Allergy, User, utcnow)
from ..permissions import require_patient
from ..schemas import (MedicationIn, MedicationUpdate, DoseIn, AppointmentIn, AppointmentUpdate, ReadingIn, ThresholdIn,
                       NoteIn, TaskIn, TaskUpdate)
from ..security import current_user

router = APIRouter(tags=["clinical"])

# Conservative, generic safety-net thresholds used only when no clinician threshold exists.
# They are NOT clinical guidance; deployers must review them with their clinical safety officer.
SAFETY_NET = {"spo2": (90, None), "heart_rate": (40, 130), "temperature_c": (35.0, 39.5),
              "blood_pressure_systolic": (90, 180), "blood_pressure_diastolic": (None, 120),
              "blood_glucose_mmol": (4.0, 20.0), "blood_glucose_mgdl": (70, 360), "respiratory_rate": (8, 28)}


def med_out(m: Medication):
    return {"id": m.id, "patient_id": m.patient_id, "name": m.name, "dose": m.dose, "route": m.route,
            "frequency": m.frequency, "schedule_times": m.schedule_times, "instructions": m.instructions,
            "prescriber": m.prescriber, "start_date": m.start_date, "end_date": m.end_date, "status": m.status,
            "verified": m.verified_by is not None}


# ---- Medications ----
@router.get("/medications")
def medications(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "meds:read")
    return [med_out(m) for m in db.scalars(select(Medication).where(Medication.patient_id == patient_id).order_by(desc(Medication.id)))]


@router.post("/medications", status_code=201)
def add_medication(data: MedicationIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, data.patient_id, "meds:write")
    m = Medication(**data.model_dump(), created_by=user.id)
    db.add(m); db.commit()
    warnings = [f"Recorded allergy to {a.substance} — confirm this medication with a clinician or pharmacist."
                for a in db.scalars(select(Allergy).where(Allergy.patient_id == data.patient_id))
                if a.substance.lower() in m.name.lower() or m.name.lower() in a.substance.lower()]
    active = db.scalars(select(Medication).where(Medication.patient_id == data.patient_id, Medication.status == "active",
                                                 Medication.id != m.id)).all()
    if any(x.name.strip().lower() == m.name.strip().lower() for x in active):
        warnings.append("A medication with the same name is already active — possible duplicate.")
    audit(db, user.id, "create", "medication", m.id, data.patient_id, request)
    return {**med_out(m), "warnings": warnings}


@router.patch("/medications/{mid}")
def update_medication(mid: int, data: MedicationUpdate, request: Request, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    m = db.get(Medication, mid)
    if not m:
        raise HTTPException(404, "Medication not found")
    changes = data.model_dump(exclude_unset=True)
    clinical_fields = {"dose", "frequency", "instructions"} & changes.keys()
    require_patient(db, user, m.patient_id, "meds:verify" if clinical_fields and m.verified_by else "meds:write")
    for k, v in changes.items():
        setattr(m, k, v)
    db.commit(); audit(db, user.id, "update", "medication", mid, m.patient_id, request)
    return med_out(m)


@router.post("/medications/{mid}/verify")
def verify_medication(mid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Medication, mid)
    if not m:
        raise HTTPException(404, "Medication not found")
    require_patient(db, user, m.patient_id, "meds:verify")
    m.verified_by = user.id; db.commit()
    audit(db, user.id, "verify", "medication", mid, m.patient_id, request)
    return med_out(m)


@router.post("/medications/{mid}/doses", status_code=201)
def record_dose(mid: int, data: DoseIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Medication, mid)
    if not m:
        raise HTTPException(404, "Medication not found")
    require_patient(db, user, m.patient_id, "doses:write")
    e = DoseEvent(medication_id=mid, recorded_by=user.id, status=data.status,
                  scheduled_at=data.scheduled_at.replace(tzinfo=None), note=data.note)
    db.add(e); db.commit(); audit(db, user.id, "record_dose", "dose_event", e.id, m.patient_id, request)
    return {"id": e.id, "status": e.status}


@router.get("/doses")
def doses(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "meds:read")
    ids = list(db.scalars(select(Medication.id).where(Medication.patient_id == patient_id)))
    if not ids:
        return []
    return [{"id": x.id, "medication_id": x.medication_id, "status": x.status, "scheduled_at": x.scheduled_at,
             "recorded_at": x.recorded_at, "note": x.note}
            for x in db.scalars(select(DoseEvent).where(DoseEvent.medication_id.in_(ids)).order_by(desc(DoseEvent.scheduled_at)).limit(500))]


@router.get("/adherence")
def adherence(patient_id: int, days: int = 30, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "meds:read")
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    ids = list(db.scalars(select(Medication.id).where(Medication.patient_id == patient_id)))
    events = db.scalars(select(DoseEvent).where(DoseEvent.medication_id.in_(ids or [-1]), DoseEvent.scheduled_at >= since)).all()
    taken = sum(1 for e in events if e.status == "taken")
    return {"days": days, "recorded": len(events), "taken": taken,
            "adherence_pct": round(100 * taken / len(events), 1) if events else None}


# ---- Appointments ----
def appt_out(a):
    return {"id": a.id, "clinician": a.clinician, "purpose": a.purpose, "location": a.location, "mode": a.mode,
            "scheduled_at": a.scheduled_at, "duration_min": a.duration_min, "status": a.status, "notes": a.notes}


@router.get("/appointments")
def appointments(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "appointments:read")
    return [appt_out(a) for a in db.scalars(select(Appointment).where(Appointment.patient_id == patient_id).order_by(Appointment.scheduled_at))]


@router.post("/appointments", status_code=201)
def add_appointment(data: AppointmentIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, data.patient_id, "appointments:write")
    start = data.scheduled_at.replace(tzinfo=None) if data.scheduled_at.tzinfo is None else \
        data.scheduled_at.astimezone(tz=None).replace(tzinfo=None)
    end = start + timedelta(minutes=data.duration_min)
    for a in db.scalars(select(Appointment).where(Appointment.patient_id == data.patient_id, Appointment.status == "scheduled")):
        if a.scheduled_at < end and start < a.scheduled_at + timedelta(minutes=a.duration_min):
            raise HTTPException(409, "This overlaps another scheduled appointment")
    a = Appointment(**{**data.model_dump(), "scheduled_at": start}, created_by=user.id,
                    clinician_user_id=user.id if user.role == "clinician" else None)
    db.add(a); db.commit(); audit(db, user.id, "create", "appointment", a.id, data.patient_id, request)
    return appt_out(a)


@router.patch("/appointments/{aid}")
def update_appointment(aid: int, data: AppointmentUpdate, request: Request, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    a = db.get(Appointment, aid)
    if not a:
        raise HTTPException(404, "Appointment not found")
    require_patient(db, user, a.patient_id, "appointments:write")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(a, k, v.replace(tzinfo=None) if k == "scheduled_at" and v else v)
    db.commit(); audit(db, user.id, "update", "appointment", aid, a.patient_id, request)
    return appt_out(a)


# ---- Monitoring ----
@router.get("/readings")
def readings(patient_id: int, kind: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "vitals:read")
    q = select(Reading).where(Reading.patient_id == patient_id)
    if kind:
        q = q.where(Reading.kind == kind)
    return [{"id": r.id, "kind": r.kind, "value": r.value, "unit": r.unit, "context": r.context, "source": r.source,
             "recorded_at": r.recorded_at} for r in db.scalars(q.order_by(desc(Reading.recorded_at)).limit(500))]


@router.get("/readings/summary")
def readings_summary(patient_id: int, days: int = 14, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "vitals:read")
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    rows = db.scalars(select(Reading).where(Reading.patient_id == patient_id, Reading.recorded_at >= since)).all()
    out: dict[str, dict] = {}
    for r in rows:
        s = out.setdefault(r.kind, {"count": 0, "min": r.value, "max": r.value, "sum": 0.0, "unit": r.unit, "latest": None})
        s["count"] += 1; s["min"] = min(s["min"], r.value); s["max"] = max(s["max"], r.value); s["sum"] += r.value
        if s["latest"] is None or r.recorded_at > s["latest"][1]:
            s["latest"] = (r.value, r.recorded_at)
    return {k: {"count": v["count"], "min": v["min"], "max": v["max"], "avg": round(v["sum"] / v["count"], 1),
                "unit": v["unit"], "latest": v["latest"][0]} for k, v in out.items()}


@router.post("/readings", status_code=201)
def add_reading(data: ReadingIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, data.patient_id, "vitals:write")
    r = Reading(**{**data.model_dump(exclude={"recorded_at"}), "recorded_at": (data.recorded_at or utcnow()).replace(tzinfo=None)},
                recorded_by=user.id)
    db.add(r); db.commit(); audit(db, user.id, "create", "reading", r.id, data.patient_id, request)
    alert = evaluate_reading(db, r)
    return {"id": r.id, "alert": alert,
            "message": "Reading saved. Alerts are informational and require clinical validation."}


def evaluate_reading(db: Session, r: Reading) -> dict | None:
    t = db.scalar(select(AlertThreshold).where(AlertThreshold.patient_id == r.patient_id, AlertThreshold.kind == r.kind))
    low, high, source = (t.low, t.high, "clinician threshold") if t else (*SAFETY_NET.get(r.kind, (None, None)), "default safety-net")
    breach = (low is not None and r.value < low) or (high is not None and r.value > high)
    if not breach:
        return None
    a = Alert(patient_id=r.patient_id, severity="urgent_review", source="reading",
              message=(f"{r.kind} {r.value} {r.unit} is outside the {source} range. Seek clinical guidance; "
                       "if this may be an emergency, contact local emergency services now."))
    db.add(a); db.commit()
    enqueue(notify_alert, a.id, a.patient_id, a.severity)
    return {"id": a.id, "severity": a.severity, "message": a.message}


@router.get("/patients/{pid}/thresholds")
def thresholds(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "vitals:read")
    custom = {t.kind: {"low": t.low, "high": t.high, "source": "clinician"}
              for t in db.scalars(select(AlertThreshold).where(AlertThreshold.patient_id == pid))}
    return {k: custom.get(k, {"low": v[0], "high": v[1], "source": "safety_net"}) for k, v in SAFETY_NET.items()} | custom


@router.put("/patients/{pid}/thresholds")
def set_threshold(pid: int, data: ThresholdIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "thresholds:write")
    if data.low is not None and data.high is not None and data.low >= data.high:
        raise HTTPException(422, "low must be less than high")
    t = db.scalar(select(AlertThreshold).where(AlertThreshold.patient_id == pid, AlertThreshold.kind == data.kind))
    if not t:
        t = AlertThreshold(patient_id=pid, kind=data.kind, set_by=user.id); db.add(t)
    t.low, t.high, t.set_by, t.updated_at = data.low, data.high, user.id, utcnow()
    db.commit(); audit(db, user.id, "set_threshold", "alert_threshold", t.id, pid, request)
    return {"kind": t.kind, "low": t.low, "high": t.high}


@router.get("/alerts")
def alerts(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "alerts:read")
    return [{"id": a.id, "severity": a.severity, "message": a.message, "source": a.source,
             "acknowledged": a.acknowledged_at is not None, "acknowledged_at": a.acknowledged_at, "created_at": a.created_at}
            for a in db.scalars(select(Alert).where(Alert.patient_id == patient_id).order_by(desc(Alert.created_at)).limit(200))]


@router.post("/alerts/{aid}/acknowledge")
def acknowledge(aid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, aid)
    if not a:
        raise HTTPException(404, "Alert not found")
    require_patient(db, user, a.patient_id, "alerts:ack")
    a.acknowledged_by, a.acknowledged_at = user.id, utcnow(); db.commit()
    audit(db, user.id, "acknowledge", "alert", aid, a.patient_id, request)
    return {"ok": True}


# ---- Clinical notes (signed notes are immutable; corrections are amendments) ----
def note_out(n):
    return {"id": n.id, "kind": n.kind, "body": n.body, "status": n.status, "author_id": n.author_id,
            "signed_at": n.signed_at, "amends_id": n.amends_id, "created_at": n.created_at}


@router.get("/patients/{pid}/notes")
def notes(pid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "notes:read")
    rows = db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id == pid).order_by(desc(ClinicalNote.id))).all()
    if user.role != "clinician":
        rows = [n for n in rows if n.status != "draft"]
    audit(db, user.id, "view", "clinical_notes", None, pid, request)
    return [note_out(n) for n in rows]


@router.post("/patients/{pid}/notes", status_code=201)
def add_note(pid: int, data: NoteIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "notes:write")
    n = ClinicalNote(patient_id=pid, author_id=user.id, **data.model_dump()); db.add(n); db.commit()
    audit(db, user.id, "create", "clinical_note", n.id, pid, request)
    return note_out(n)


@router.post("/notes/{nid}/sign")
def sign_note(nid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(ClinicalNote, nid)
    if not n:
        raise HTTPException(404, "Note not found")
    require_patient(db, user, n.patient_id, "notes:write")
    if n.author_id != user.id or n.status != "draft":
        raise HTTPException(403, "Only the author can sign a draft note")
    n.status, n.signed_at = "signed", utcnow(); db.commit()
    audit(db, user.id, "sign", "clinical_note", nid, n.patient_id, request)
    return note_out(n)


@router.post("/notes/{nid}/amend", status_code=201)
def amend_note(nid: int, data: NoteIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    orig = db.get(ClinicalNote, nid)
    if not orig or orig.status == "draft":
        raise HTTPException(400, "Only signed notes can be amended")
    require_patient(db, user, orig.patient_id, "notes:write")
    n = ClinicalNote(patient_id=orig.patient_id, author_id=user.id, kind=data.kind, body=data.body,
                     amends_id=orig.id, status="signed", signed_at=utcnow())
    orig.status = "amended"; db.add(n); db.commit()
    audit(db, user.id, "amend", "clinical_note", n.id, orig.patient_id, request)
    return note_out(n)


# ---- Care tasks ----
@router.get("/patients/{pid}/tasks")
def tasks(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "tasks:read")
    return [{"id": t.id, "title": t.title, "assignee_id": t.assignee_id, "due_at": t.due_at, "status": t.status}
            for t in db.scalars(select(CareTask).where(CareTask.patient_id == pid).order_by(CareTask.status, CareTask.due_at))]


@router.post("/patients/{pid}/tasks", status_code=201)
def add_task(pid: int, data: TaskIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, pid, "tasks:write")
    t = CareTask(patient_id=pid, created_by=user.id, **{**data.model_dump(), "due_at": data.due_at.replace(tzinfo=None) if data.due_at else None})
    db.add(t); db.commit(); audit(db, user.id, "create", "care_task", t.id, pid, request)
    return {"id": t.id}


@router.patch("/tasks/{tid}")
def update_task(tid: int, data: TaskUpdate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(CareTask, tid)
    if not t:
        raise HTTPException(404, "Task not found")
    require_patient(db, user, t.patient_id, "tasks:write")
    t.status = data.status; db.commit(); audit(db, user.id, "update", "care_task", tid, t.patient_id, request)
    return {"ok": True}
