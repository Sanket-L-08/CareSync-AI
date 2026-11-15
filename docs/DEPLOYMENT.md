# Deployment guide

## Option A — single cloud VM (any provider)
1. Create a VM (2 vCPU / 4 GB+), install Docker. Point DNS `app.<domain>` and `api.<domain>` to it. Open ports 80/443 only.
2. `cp .env.example .env` and fill every value. Generate secrets:
   - `SECRET_KEY`: `python -c "import secrets;print(secrets.token_urlsafe(64))"`
   - `DATA_ENCRYPTION_KEY`: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
   - Keep the encryption key in a secrets manager too — **losing it makes encrypted data unrecoverable.**
3. `docker compose up -d --build` — runs migrations, creates a private encrypted bucket, and Caddy obtains HTTPS certificates.
4. Create the first admin:
   `docker compose run --rm api python -c "from app.db import SessionLocal;from app.models import User;from app.security import hash_password;db=SessionLocal();db.add(User(name='Admin',email='you@org.com',password_hash=hash_password('CHANGE-Me-123456'),role='admin'));db.commit()"`
   Sign in, enable MFA, then create and verify clinician accounts from the admin screen.

## Option B — managed cloud services (recommended for scale)
Use the same images and environment variables, replacing self-hosted parts:
| Component | AWS | Google Cloud | Azure |
|---|---|---|---|
| Containers | ECS Fargate / EKS | Cloud Run / GKE | Container Apps / AKS |
| PostgreSQL | RDS (encrypted, Multi-AZ) | Cloud SQL | Azure Database for PostgreSQL |
| Redis | ElastiCache (TLS) | Memorystore | Azure Cache for Redis |
| Object storage | S3 + KMS, Block Public Access | GCS (S3 interop) + CMEK | Blob via S3-compatible gateway |
| Secrets | Secrets Manager | Secret Manager | Key Vault |

Set `DATABASE_URL` (with `sslmode=require`), `REDIS_URL` (`rediss://`), `S3_*`, and run `alembic upgrade head` as a one-off task before each release. Run the worker as a separate service with `python -m app.worker`.

## International readiness
- Choose the hosting region to match data-residency law; set `DATA_REGION` (shown on `/ready`).
- All timestamps are stored in UTC; each user has a timezone and locale.
- FHIR R4 export enables exchange with other health systems.

## CI/CD
`.github/workflows/ci.yml` tests, scans and builds on every push; on `main` it pushes images to GHCR, scans them with Trivy,
and (when `DEPLOY_HOST` is set) deploys over SSH after approval in the `production` environment.
Required: repo variables `PUBLIC_API_URL`, `DEPLOY_HOST`; secrets `DEPLOY_USER`, `DEPLOY_SSH_KEY`.

## Operations checklist
- Daily encrypted database backups with point-in-time recovery; test restores quarterly
- Bucket versioning + lifecycle rules; never enable public access
- Central logging; alert on 5xx rate and failed logins
- Review the audit log and break-glass events weekly; `GET /admin/audit/verify` checks tamper-evidence
- Rotate `SECRET_KEY` (forces re-login) and cloud credentials regularly
