from .conftest import make_user, PW

def own_patient(client, h):
    return client.get("/patients", headers=h).json()[0]["id"]


def test_requires_auth(client):
    assert client.get("/patients").status_code == 401


def test_weak_password_rejected(client):
    r = client.post("/auth/register", json={"name": "x", "email": "weak@x.io", "password": "alllowercase1",
                                            "role": "patient", "accept_terms": True})
    assert r.status_code == 422


def test_clinician_self_signup_blocked(client):
    r = client.post("/auth/register", json={"name": "x", "email": "doc@x.io", "password": PW, "role": "clinician",
                                            "accept_terms": True})
    assert r.status_code in (403, 422)


def test_patient_cannot_see_other_patient(client):
    a = make_user(client, "a@x.io"); b = make_user(client, "b@x.io")
    pid_a = own_patient(client, a)
    assert client.get(f"/medications?patient_id={pid_a}", headers=b).status_code == 404
    assert len(client.get("/patients", headers=b).json()) == 1


def test_caregiver_needs_grant_and_revocation_works(client):
    p = make_user(client, "p1@x.io"); c = make_user(client, "c1@x.io", "caregiver")
    pid = own_patient(client, p)
    assert client.get(f"/readings?patient_id={pid}", headers=c).status_code == 404
    g = client.post(f"/patients/{pid}/grants", headers=p, json={"grantee_email": "c1@x.io", "relationship": "caregiver"})
    assert g.status_code == 201
    assert client.get(f"/readings?patient_id={pid}", headers=c).status_code == 200
    # caregiver cannot read the patient's access log or manage sharing
    assert client.get(f"/patients/{pid}/access-log", headers=c).status_code == 403
    assert client.delete(f"/patients/{pid}/grants/{g.json()['id']}", headers=p).status_code == 200
    assert client.get(f"/readings?patient_id={pid}", headers=c).status_code == 404


def test_family_scope_is_read_only(client):
    p = make_user(client, "p2@x.io"); f = make_user(client, "f2@x.io", "caregiver")
    pid = own_patient(client, p)
    client.post(f"/patients/{pid}/grants", headers=p, json={"grantee_email": "f2@x.io", "relationship": "family"})
    assert client.get(f"/medications?patient_id={pid}", headers=f).status_code == 200
    r = client.post("/medications", headers=f, json={"patient_id": pid, "name": "X", "dose": "1", "frequency": "daily"})
    assert r.status_code == 403


def test_consent_withdrawal_revokes_all_access(client):
    p = make_user(client, "p3@x.io"); c = make_user(client, "c3@x.io", "caregiver")
    pid = own_patient(client, p)
    client.post(f"/patients/{pid}/grants", headers=p, json={"grantee_email": "c3@x.io", "relationship": "caregiver"})
    client.post(f"/patients/{pid}/consents", headers=p, json={"kind": "data_sharing", "granted": False, "policy_version": "2026-01"})
    assert client.get(f"/readings?patient_id={pid}", headers=c).status_code == 404


def test_admin_has_no_clinical_access_without_break_glass(client):
    p = make_user(client, "p4@x.io"); adm = make_user(client, "adm4@x.io", "admin")
    pid = own_patient(client, p)
    assert client.get(f"/readings?patient_id={pid}", headers=adm).status_code == 404
    assert client.post("/admin/break-glass", headers=adm, json={"patient_id": pid, "reason": "short"}).status_code == 422
    r = client.post("/admin/break-glass", headers=adm, json={"patient_id": pid, "reason": "Patient unresponsive, emergency team request"})
    assert r.status_code == 201
    assert client.get(f"/readings?patient_id={pid}", headers=adm).status_code == 200
    assert client.post("/readings", headers=adm, json={"patient_id": pid, "kind": "spo2", "value": 97, "unit": "%"}).status_code == 403


def test_only_verified_clinician_can_write_notes(client):
    p = make_user(client, "p5@x.io"); d = make_user(client, "d5@x.io", "clinician", verified=False)
    pid = own_patient(client, p)
    client.post(f"/patients/{pid}/grants", headers=p, json={"grantee_email": "d5@x.io", "relationship": "clinician"})
    assert client.post(f"/patients/{pid}/notes", headers=d, json={"body": "x"}).status_code == 403
    assert client.post(f"/patients/{pid}/notes", headers=p, json={"body": "x"}).status_code == 403


def test_signed_note_is_immutable_and_amendable(client):
    p = make_user(client, "p6@x.io"); d = make_user(client, "d6@x.io", "clinician", verified=True)
    pid = own_patient(client, p)
    client.post(f"/patients/{pid}/grants", headers=p, json={"grantee_email": "d6@x.io", "relationship": "clinician"})
    n = client.post(f"/patients/{pid}/notes", headers=d, json={"body": "BP stable"}).json()
    assert client.post(f"/notes/{n['id']}/sign", headers=d).json()["status"] == "signed"
    assert client.post(f"/notes/{n['id']}/sign", headers=d).status_code == 403
    assert client.post(f"/notes/{n['id']}/amend", headers=d, json={"body": "Correction"}).status_code == 201


def test_low_spo2_creates_alert(client):
    p = make_user(client, "p7@x.io"); pid = own_patient(client, p)
    r = client.post("/readings", headers=p, json={"patient_id": pid, "kind": "spo2", "value": 85, "unit": "%"}).json()
    assert r["alert"]["severity"] == "urgent_review"
    ok = client.post("/readings", headers=p, json={"patient_id": pid, "kind": "spo2", "value": 97, "unit": "%"}).json()
    assert ok["alert"] is None


def test_allergy_warning_on_medication(client):
    p = make_user(client, "p8@x.io"); pid = own_patient(client, p)
    client.post(f"/patients/{pid}/allergies", headers=p, json={"substance": "Penicillin", "severity": "severe"})
    r = client.post("/medications", headers=p, json={"patient_id": pid, "name": "Penicillin V", "dose": "250mg", "frequency": "QID"})
    assert r.status_code == 201 and r.json()["warnings"]


def test_overlapping_appointments_rejected(client):
    p = make_user(client, "p9@x.io"); pid = own_patient(client, p)
    body = {"patient_id": pid, "clinician": "Dr X", "purpose": "Review", "scheduled_at": "2030-01-01T10:00:00", "duration_min": 30}
    assert client.post("/appointments", headers=p, json=body).status_code == 201
    assert client.post("/appointments", headers=p, json={**body, "scheduled_at": "2030-01-01T10:15:00"}).status_code == 409


def test_document_encrypted_at_rest_and_type_sniffed(client):
    import os, glob
    p = make_user(client, "p10@x.io"); pid = own_patient(client, p)
    bad = client.post("/reports", headers=p, data={"patient_id": pid}, files={"file": ("x.pdf", b"<html>", "application/pdf")})
    assert bad.status_code == 415
    pdf = b"%PDF-1.4 secret-lab-result"
    r = client.post("/reports", headers=p, data={"patient_id": pid}, files={"file": ("lab.pdf", pdf, "application/pdf")})
    assert r.status_code == 201
    stored = [open(f, "rb").read() for f in glob.glob(os.environ["LOCAL_STORAGE_DIR"] + "/**/*.bin", recursive=True)]
    assert stored and all(b"secret-lab-result" not in s for s in stored)
    assert client.get(f"/reports/{r.json()['id']}/download", headers=p).content == pdf


def test_account_lockout(client):
    make_user(client, "lock@x.io")
    for _ in range(5):
        client.post("/auth/login", json={"email": "lock@x.io", "password": "WrongPassw0rd!"})
    assert client.post("/auth/login", json={"email": "lock@x.io", "password": PW}).status_code == 423


def test_refresh_token_reuse_revokes_family(client):
    client.post("/auth/register", json={"name": "r", "email": "r@x.io", "password": PW, "role": "patient", "accept_terms": True})
    rt = client.post("/auth/login", json={"email": "r@x.io", "password": PW}).json()["refresh_token"]
    new = client.post("/auth/refresh", json={"refresh_token": rt}).json()["refresh_token"]
    assert client.post("/auth/refresh", json={"refresh_token": rt}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": new}).status_code == 401


def test_audit_chain_valid_and_security_headers(client):
    adm = make_user(client, "adm11@x.io", "admin")
    r = client.get("/admin/audit/verify", headers=adm)
    assert r.json()["valid"] is True
    assert r.headers["x-frame-options"] == "DENY" and "max-age" in r.headers["strict-transport-security"]


def test_production_config_fails_closed(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("APP_ENV", "production"); monkeypatch.setenv("SECRET_KEY", "short")
    import pytest
    with pytest.raises(RuntimeError):
        Settings().validate()
