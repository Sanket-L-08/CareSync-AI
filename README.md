# CareSync AI v2 — Secure Connected Care

Care coordination platform for patients, caregivers and clinicians: health records, medication management,
health monitoring with alerts, appointments, clinical notes, care tasks, encrypted documents and a guarded AI assistant.

> **Clinical safety:** CareSync is care-coordination software, not a medical device. Alerts and AI output are
> informational. Before real patient use you must complete a clinical safety review, a privacy/DPIA assessment,
> penetration testing and any regulatory obligations in your country (e.g. HIPAA, GDPR, UK DSPT, India DPDP).

## Architecture
| Area | Implementation |
|---|---|
| Frontend | Next.js 14 (`apps/web`), standalone container, strict security headers & CSP |
| Backend | FastAPI (`services/api`), Gunicorn + Uvicorn workers |
| Database | PostgreSQL 16, schema managed by Alembic migrations |
| File storage | Private S3-compatible object storage (AWS S3, GCS, MinIO, others); AES-256-GCM app-level encryption **plus** bucket SSE/KMS |
| Cache / jobs | Redis (rate limiting) + RQ worker (alert delivery, missed-dose scan) |
| Deployment | Docker Compose with Caddy automatic HTTPS; images portable to any cloud/Kubernetes |
| CI/CD | GitHub Actions: tests, Bandit, pip-audit, npm audit, image build, Trivy scan, gated deploy |
| Security | RBAC + patient-level, consent-backed, scoped, revocable grants |
| International | UTC storage, per-user timezone & locale, configurable data region, FHIR R4 export |
| Mobile | Excluded (removed) |

## Security features
- Argon2 password hashing, password policy, account lockout, per-IP auth rate limits
- 15-min access tokens + rotating refresh tokens with reuse (theft) detection; "sign out everywhere"
- TOTP multi-factor authentication, **mandatory for clinicians and admins**
- No clinician self-signup; admins create staff and verify clinician licences before they can write notes, verify medicines or set thresholds
- Patient-level access: the patient (or the creating caregiver for people without an account) grants scoped access (caregiver / family view-only / clinician) with optional expiry; withdrawing data-sharing consent revokes everyone instantly
- Admins have **no clinical data access**; emergency "break-glass" read access requires written justification, expires in 4 hours and is audited
- Inaccessible records return 404 (prevents record enumeration)
- Hash-chained, tamper-evident audit log for every read/write of patient data; patients can see who accessed their record
- Sensitive free text (notes, instructions, reactions, emergency contacts, MFA secrets) encrypted in the database
- Uploads: size limit, real file-type sniffing, encrypted before storage, SHA-256 integrity check on download
- AI: consent required, de-identified payloads (no names/DOB/notes), prompt-injection guard, never prescribes
- Production refuses to start with weak secrets, SQLite, local storage, wildcard CORS/hosts or demo data
- API docs disabled in production; generic error responses (no stack traces or PHI)
- Containers: non-root, read-only filesystem, all capabilities dropped; databases on an internal network

## Healthcare features
- **Health records:** profile, allergies (severity), conditions (ICD-10/SNOMED code), FHIR R4 export, personal data export
- **Medications:** schedules & reminder times, dose logging, adherence %, allergy and duplicate warnings, clinician verification; verified prescriptions can only be changed by a clinician
- **Monitoring:** 10 vital types, 14-day summaries, clinician-set patient-specific thresholds with safety-net defaults, urgent alerts, acknowledgement, webhook notification
- **Appointments:** in-person/video/phone, double-booking prevention, cancel/complete
- **Clinical workflows:** draft → signed clinical notes (immutable, corrections via amendments), care tasks, missed-dose detection worker

## Quick start

**If you only want to run the app in VS Code and keep getting “Not Found”, open `START_HERE.md` first.**

### Local (no Docker)
```bash
# Terminal 1 – API
cd services/api
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
APP_ENV=development SEED_DEMO=true REQUIRE_MFA_FOR_STAFF=false uvicorn app.main:app --reload --port 8000

# Terminal 2 – Frontend
cd apps/web
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev
```
Then open **http://localhost:3000**

Demo accounts (password `CareSyncDemo!2026`):  
`demo@example.com` · `caregiver@example.com` · `clinician@example.com` · `admin@example.com`

### Docker with published ports (easiest in VS Code)
```bash
docker compose -f docker-compose.dev.yml up --build
```
→ http://localhost:3000 (web) · http://localhost:8000 (API) · http://localhost:8000/docs

### Production-style (Caddy + HTTPS)
See **docs/DEPLOYMENT.md** and **docs/SECURITY.md**.  
```bash
cp .env.example .env   # set strong secrets
docker compose up -d --build
```
Then open **https://localhost**

Run tests: `cd services/api && pytest`
