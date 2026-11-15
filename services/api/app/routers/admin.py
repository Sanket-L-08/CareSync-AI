from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from ..audit import audit, verify_chain
from ..db import get_db
from ..models import User, AuditLog, CareGrant, Patient, utcnow
from ..permissions import require_patient, DEFAULT_GRANT_SCOPES
from ..schemas import AdminUserUpdate, BreakGlassIn, RegisterIn
from ..security import require_roles, current_user, hash_password, password_policy, revoke_all

router = APIRouter(tags=["admin"])
admin_only = require_roles("admin")


@router.get("/admin/users")
def users(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active,
             "mfa_enabled": u.mfa_enabled, "is_verified_clinician": u.is_verified_clinician}
            for u in db.scalars(select(User).order_by(User.id))]


@router.post("/admin/users", status_code=201)
def create_staff(data: RegisterIn, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    password_policy(data.password)
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise HTTPException(409, "Email already registered")
    u = User(name=data.name, email=data.email.lower(), password_hash=hash_password(data.password), role=data.role)
    db.add(u); db.commit(); audit(db, admin.id, "create_user", "user", u.id, request=request)
    return {"id": u.id}


@router.patch("/admin/users/{uid}")
def update_user(uid: int, data: AdminUserUpdate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (data.role or data.is_active is False):
        raise HTTPException(400, "Admins cannot demote or deactivate themselves")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    if data.is_active is False or data.role:
        revoke_all(db, u)
    audit(db, admin.id, "update_user", "user", uid, request=request)
    return {"ok": True}


@router.post("/admin/break-glass", status_code=201)
def break_glass(data: BreakGlassIn, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Emergency 4-hour read access with mandatory justification; always audited for review."""
    if not db.get(Patient, data.patient_id):
        raise HTTPException(404, "Patient not found")
    g = db.scalar(select(CareGrant).where(CareGrant.patient_id == data.patient_id, CareGrant.grantee_id == admin.id))
    scopes = ",".join(sorted(s for s in DEFAULT_GRANT_SCOPES["clinician"] if s.endswith(":read")))
    if g:
        g.relationship, g.scopes, g.revoked_at, g.expires_at = "break_glass", scopes, None, utcnow() + timedelta(hours=4)
    else:
        g = CareGrant(patient_id=data.patient_id, grantee_id=admin.id, relationship="break_glass", scopes=scopes,
                      granted_by=admin.id, expires_at=utcnow() + timedelta(hours=4)); db.add(g)
    db.commit()
    audit(db, admin.id, f"break_glass:{data.reason[:80]}", "care_grant", g.id, data.patient_id, request)
    return {"grant_id": g.id, "expires_at": g.expires_at}


def audit_out(x):
    return {"id": x.id, "user_id": x.user_id, "patient_id": x.patient_id, "action": x.action, "entity": x.entity,
            "entity_id": x.entity_id, "outcome": x.outcome, "ip": x.ip, "created_at": x.created_at}


@router.get("/admin/audit")
def audit_logs(limit: int = 300, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [audit_out(x) for x in db.scalars(select(AuditLog).order_by(desc(AuditLog.id)).limit(min(limit, 2000)))]


@router.get("/admin/audit/verify")
def audit_verify(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return verify_chain(db)


@router.get("/patients/{pid}/access-log")
def patient_access_log(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Patients can see who accessed their record (transparency)."""
    require_patient(db, user, pid, "audit:read")
    rows = db.scalars(select(AuditLog).where(AuditLog.patient_id == pid).order_by(desc(AuditLog.id)).limit(500))
    names = {u.id: u.name for u in db.scalars(select(User))}
    return [{**{k: v for k, v in audit_out(x).items() if k != "ip"}, "user_name": names.get(x.user_id, "system")} for x in rows]
