import os, sys, tempfile, pathlib
_tmp = tempfile.mkdtemp()
os.environ.update(APP_ENV="test", DATABASE_URL=f"sqlite:///{_tmp}/t.db", LOCAL_STORAGE_DIR=f"{_tmp}/store",
                  SECRET_KEY="test-secret-key-test-secret-key-test-secret-key", REDIS_URL="",
                  SEED_DEMO="false", RATE_LIMIT_PER_MINUTE="10000", AUTH_RATE_LIMIT_PER_MINUTE="10000",
                  REQUIRE_MFA_FOR_STAFF="false", ALLOWED_HOSTS="testserver")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import User
from app.security import hash_password

PW = "StrongPassw0rd!"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def make_user(client, email, role="patient", verified=False):
    if role in ("patient", "caregiver"):
        r = client.post("/auth/register", json={"name": email.split("@")[0], "email": email, "password": PW,
                                                "role": role, "accept_terms": True})
        assert r.status_code == 201, r.text
    else:
        with SessionLocal() as db:
            db.add(User(name=email, email=email, password_hash=hash_password(PW), role=role, is_verified_clinician=verified))
            db.commit()
    tok = client.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}
