from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
import pyotp
from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..models import User, Patient, Consent, CareGrant, utcnow
from ..permissions import DEFAULT_GRANT_SCOPES
from ..schemas import RegisterIn, LoginIn, RefreshIn, MfaCodeIn
from ..security import (hash_password, verify_password, password_policy, make_access_token, issue_refresh,
                        rotate_refresh, revoke_all, new_totp_secret, verify_totp, register_failed_login,
                        current_user, STAFF_ROLES)

router = APIRouter(prefix="/auth", tags=["auth"])
POLICY_VERSION = "2026-01"


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "mfa_enabled": u.mfa_enabled,
            "is_verified_clinician": u.is_verified_clinician, "locale": u.locale, "timezone": u.timezone}


def session(db, user, mfa):
    return {"access_token": make_access_token(user, mfa), "refresh_token": issue_refresh(db, user),
            "token_type": "bearer", "mfa_satisfied": mfa, "user": user_out(user)}


@router.post("/register", status_code=201)
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not data.accept_terms:
        raise HTTPException(422, "Terms and privacy notice must be accepted")
    password_policy(data.password)
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        # Generic response avoids account enumeration.
        raise HTTPException(400, "Registration could not be completed")
    if data.role == "clinician" and not get_settings().allow_clinician_self_signup:
        raise HTTPException(403, "Clinician accounts are created by an administrator")
    user = User(name=data.name, email=email, password_hash=hash_password(data.password), role=data.role,
                locale=data.locale, timezone=data.timezone)
    db.add(user); db.commit()
    if user.role == "patient":
        p = Patient(name=user.name, owner_id=user.id, created_by=user.id)
        db.add(p); db.commit()
        db.add(Consent(patient_id=p.id, kind="data_sharing", policy_version=POLICY_VERSION, granted=True,
                       recorded_by=user.id, detail="Accepted privacy notice at registration"))
        db.commit()
    audit(db, user.id, "register", "user", user.id, request=request)
    return session(db, user, mfa=False)


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user and user.locked_until and user.locked_until > utcnow():
        audit(db, user.id, "login", "user", user.id, request=request, outcome="locked")
        raise HTTPException(423, "Account temporarily locked. Try again later.")
    if not verify_password(data.password, user.password_hash if user else None) or not user or not user.is_active:
        if user:
            register_failed_login(db, user)
            audit(db, user.id, "login", "user", user.id, request=request, outcome="failure")
        raise HTTPException(401, "Incorrect email or password")
    mfa = False
    if user.mfa_enabled:
        if not data.totp:
            raise HTTPException(401, "MFA code required")
        if not verify_totp(user.mfa_secret, data.totp):
            register_failed_login(db, user)
            raise HTTPException(401, "Invalid MFA code")
        mfa = True
    user.failed_logins = 0; user.locked_until = None; db.commit()
    audit(db, user.id, "login", "user", user.id, request=request)
    out = session(db, user, mfa)
    out["mfa_setup_required"] = user.role in STAFF_ROLES and not user.mfa_enabled and get_settings().require_mfa_for_staff
    return out


@router.post("/refresh")
def refresh(data: RefreshIn, db: Session = Depends(get_db)):
    user, new_refresh = rotate_refresh(db, data.refresh_token)
    return {"access_token": make_access_token(user, user.mfa_enabled), "refresh_token": new_refresh,
            "token_type": "bearer", "user": user_out(user)}


@router.post("/logout")
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    revoke_all(db, user)
    audit(db, user.id, "logout_all", "user", user.id, request=request)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(400, "MFA already enabled")
    user.mfa_secret = new_totp_secret(); db.commit()
    return {"secret": user.mfa_secret,
            "otpauth_uri": pyotp.TOTP(user.mfa_secret).provisioning_uri(user.email, issuer_name="CareSync AI")}


@router.post("/mfa/enable")
def mfa_enable(data: MfaCodeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_totp(user.mfa_secret, data.code):
        raise HTTPException(400, "Invalid code")
    user.mfa_enabled = True
    revoke_all(db, user)  # force re-login with MFA
    audit(db, user.id, "mfa_enable", "user", user.id, request=request)
    return {"ok": True, "message": "MFA enabled. Please sign in again."}


@router.get("/my-data-export")
def export_my_data(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Data portability (GDPR Art. 20 style) for the signed-in patient."""
    from .patients import full_record
    pats = db.scalars(select(Patient).where(Patient.owner_id == user.id)).all()
    audit(db, user.id, "export", "user", user.id, request=request)
    return {"user": user_out(user), "patients": [full_record(db, p) for p in pats],
            "grants_held": [{"patient_id": g.patient_id, "relationship": g.relationship}
                            for g in db.scalars(select(CareGrant).where(CareGrant.grantee_id == user.id))]}
