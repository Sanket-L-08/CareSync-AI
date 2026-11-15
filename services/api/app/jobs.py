"""Background jobs. Enqueued to Redis (RQ) when available, run inline otherwise."""
import logging
from .config import get_settings
from .notifications import send_webhook_sync

log = logging.getLogger("caresync.jobs")


def enqueue(func, *args):
    s = get_settings()
    if s.redis_url:
        try:
            from redis import Redis
            from rq import Queue
            Queue("caresync", connection=Redis.from_url(s.redis_url)).enqueue(func, *args, retry=None)
            return
        except Exception as e:
            log.warning("enqueue failed, running inline: %s", type(e).__name__)
    func(*args)


def notify_alert(alert_id: int, patient_id: int, severity: str) -> None:
    send_webhook_sync({"type": "caresync_alert", "alert_id": alert_id, "patient_id": patient_id, "severity": severity})


def scan_missed_doses() -> int:
    """Periodic job: create alerts for scheduled doses not recorded within 2 hours."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    from .db import SessionLocal
    from .models import Medication, DoseEvent, Alert, Patient, User, utcnow
    created = 0
    db = SessionLocal()
    try:
        now = utcnow()
        for med in db.scalars(select(Medication).where(Medication.status == "active", Medication.schedule_times != "")):
            patient = db.get(Patient, med.patient_id)
            owner = db.get(User, patient.owner_id) if patient and patient.owner_id else None
            tz = ZoneInfo(owner.timezone if owner else get_settings().default_timezone)
            local_today = datetime.now(tz).date()
            for t in med.schedule_times.split(","):
                hh, mm = map(int, t.split(":"))
                due = datetime(local_today.year, local_today.month, local_today.day, hh, mm, tzinfo=tz)
                due_utc = due.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                if not (due_utc + timedelta(hours=2) < now < due_utc + timedelta(hours=3)):
                    continue
                recorded = db.scalar(select(DoseEvent).where(DoseEvent.medication_id == med.id,
                                                            DoseEvent.scheduled_at >= due_utc - timedelta(hours=1),
                                                            DoseEvent.scheduled_at <= due_utc + timedelta(hours=1)))
                if not recorded:
                    a = Alert(patient_id=med.patient_id, severity="warning", source="missed_dose",
                              message=f"Scheduled dose of {med.name} at {t} has not been recorded.")
                    db.add(a); db.commit(); created += 1
                    notify_alert(a.id, a.patient_id, a.severity)
    finally:
        db.close()
    return created
