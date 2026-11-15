"""Authentication: Argon2 passwords, short-lived JWT access tokens, rotating refresh tokens, TOTP MFA, lockout."""
import hashlib, secrets, uuid
from datetime import datetime, timedelta, timezone
import jwt, pyotp
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .config import get_settings
from .db import get_db
from .models import User, RefreshToken, utcnow

_ph = PasswordHash.recommended()
ALGORITHM = "HS256"
ISSUER = "caresync-api"
bearer = HTTPBearer(auto_error=False)
STAFF_ROLES = ("clinician", "admin")
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-password")


def hash_password(p: str) -> str:
    return _ph.hash(p)


def verify_password(p: str, h: str | None) -> bool:
    try:
        return _ph.verify(p, h or _DUMMY_HASH) and h is not None
    except Exception:
        return False


def password_policy(p: str) -> None:
    if len(p) < 12 or p.lower() == p or p.upper() == p or not any(c.isdigit() for c in p):
        raise HTTPException(422, "Password must be 12+ characters with upper, lower case and a digit")


def make_access_token(user: User, mfa: bool) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role, "tv": user.token_version, "mfa": mfa,
               "iss": ISSUER, "iat": now, "exp": now + timedelta(minutes=s.access_ttl_min), "jti": uuid.uuid4().hex}
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh(db: Session, user: User, family: str | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(RefreshToken(user_id=user.id, token_hash=_h(raw), family=family or uuid.uuid4().hex,
                        expires_at=utcnow() + timedelta(days=get_settings().refresh_ttl_days)))
    db.commit()
    return raw


def rotate_refresh(db: Session, raw: str) -> tuple[User, str]:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _h(raw)))
    if not row or row.expires_at < utcnow():
        raise HTTPException(401, "Session expired")
    if row.revoked:  # reuse of a rotated token -> revoke the whole family (theft detection)
        db.execute(update(RefreshToken).where(RefreshToken.family == row.family).values(revoked=True))
        db.commit()
        raise HTTPException(401, "Session revoked")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Session expired")
    row.revoked = True
    db.commit()
    return user, issue_refresh(db, user, row.family)


def revoke_all(db: Session, user: User) -> None:
    user.token_version += 1
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True))
    db.commit()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str | None, code: str | None) -> bool:
    return bool(secret and code and pyotp.TOTP(secret).verify(code.strip(), valid_window=1))


def register_failed_login(db: Session, user: User) -> None:
    s = get_settings()
    user.failed_logins += 1
    if user.failed_logins >= s.max_failed_logins:
        user.locked_until = utcnow() + timedelta(minutes=s.lockout_minutes)
        user.failed_logins = 0
    db.commit()


def current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(401, "Authentication required")
    try:
        data = jwt.decode(credentials.credentials, get_settings().secret_key, algorithms=[ALGORITHM],
                          issuer=ISSUER, options={"require": ["exp", "sub", "iss"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active or data.get("tv") != user.token_version:
        raise HTTPException(401, "Invalid or expired session")
    if (user.role in STAFF_ROLES and get_settings().require_mfa_for_staff and not data.get("mfa")
            and not request.url.path.startswith("/auth/mfa")):
        raise HTTPException(403, "Multi-factor authentication required for staff accounts")
    request.state.user_id = user.id
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Insufficient role permissions")
        return user
    return checker
