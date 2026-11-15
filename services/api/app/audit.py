import hashlib, json
from fastapi import Request
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from .models import AuditLog, utcnow


def _digest(prev: str, fields: dict) -> str:
    return hashlib.sha256((prev + json.dumps(fields, sort_keys=True, default=str)).encode()).hexdigest()


def audit(db: Session, user_id: int | None, action: str, entity: str, entity_id: int | None = None,
          patient_id: int | None = None, request: Request | None = None, outcome: str = "success") -> None:
    prev = db.scalar(select(AuditLog.hash).order_by(desc(AuditLog.id)).limit(1)) or ""
    ip = (request.client.host if request and request.client else "") or ""
    rid = getattr(request.state, "request_id", "") if request else ""
    created = utcnow()
    fields = dict(user_id=user_id, patient_id=patient_id, action=action, entity=entity, entity_id=entity_id,
                  outcome=outcome, ip=ip, request_id=rid, created_at=created.isoformat())
    db.add(AuditLog(**{**fields, "created_at": created}, prev_hash=prev, hash=_digest(prev, fields)))
    db.commit()


def verify_chain(db: Session) -> dict:
    prev = ""
    count = 0
    for row in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        fields = dict(user_id=row.user_id, patient_id=row.patient_id, action=row.action, entity=row.entity,
                      entity_id=row.entity_id, outcome=row.outcome, ip=row.ip, request_id=row.request_id,
                      created_at=row.created_at.isoformat())
        if row.prev_hash != prev or row.hash != _digest(prev, fields):
            return {"valid": False, "broken_at_id": row.id, "checked": count}
        prev = row.hash
        count += 1
    return {"valid": True, "checked": count}
