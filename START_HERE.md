# CareSync AI — How to run in VS Code (fix the “Not Found” problem)

The most common reason you see **Not Found** is that you opened the **API** URL in the browser  
(`http://localhost:8000`) or a URL that has no page. The real UI is the **Next.js frontend**.

---

## Windows: one-key VS Code launch (recommended)

This repository includes a VS Code launch profile. Install **Python 3.12** and **Node.js LTS**, open this project root in VS Code, then press **F5** and choose **CareSync AI: Run website (F5)**. VS Code will run `scripts/run-windows.ps1`, prepare dependencies, start the API and web frontend in separate terminals, wait until both are ready, and open `http://localhost:3000` in Chrome.

This local launcher uses SQLite and local private file storage, so Docker is not required for the local demo. It is not a production deployment. See `scripts/README-WINDOWS.md` for details.

## Option 1 — Fastest local run (no Docker)

### 1. Start the API

Open a terminal in VS Code:

```bash
cd services/api
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements-dev.txt

# Start with demo data and MFA turned off for convenience
set APP_ENV=development
set SEED_DEMO=true
set REQUIRE_MFA_FOR_STAFF=false
# On macOS/Linux use export instead of set:
# export APP_ENV=development SEED_DEMO=true REQUIRE_MFA_FOR_STAFF=false

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check it works:
- Open http://localhost:8000          → you should see a JSON welcome message (not a bare 404)
- Open http://localhost:8000/health   → `{"status":"ok"}`
- Open http://localhost:8000/docs     → interactive API docs

### 2. Start the frontend (new terminal)

```bash
cd apps/web
npm install

# Make sure the frontend talks to the local API
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local

npm run dev
```

### 3. Open the app

**→ http://localhost:3000**

Demo logins (password for all: `CareSyncDemo!2026`):

| Email                     | Role      |
|---------------------------|-----------|
| demo@example.com          | patient   |
| caregiver@example.com     | caregiver |
| clinician@example.com     | clinician |
| admin@example.com         | admin     |

---

## Option 2 — Docker (ports published — easy for VS Code)

```bash
# From the project root (CareSync-AI folder)
docker compose -f docker-compose.dev.yml up --build
```

Then open:

- **Web UI** → http://localhost:3000
- **API**    → http://localhost:8000
- **API docs** → http://localhost:8000/docs

This version publishes ports 3000 and 8000 so you never need Caddy or special hostnames.

---

## Option 3 — Full production-style stack (Caddy + HTTPS)

```bash
cp .env.example .env
# edit .env and set strong secrets
docker compose up -d --build
```

Then open **https://localhost** (Caddy terminates TLS).  
Do **not** open port 3000 or 8000 — they are not published in the production compose file.

---

## Quick troubleshooting

| Symptom                        | Cause / Fix |
|--------------------------------|-------------|
| Browser shows “Not Found” on port 8000 | You opened the API. Use **http://localhost:3000** for the UI. |
| Frontend loads but login fails | Check `NEXT_PUBLIC_API_URL=http://localhost:8000` in `apps/web/.env.local` and that the API is running. |
| CORS errors in browser console | API must allow `http://localhost:3000` (default in development). |
| “Unsafe production configuration” | You set `APP_ENV=production` without proper secrets. Use `APP_ENV=development` for local work. |
| Docker “connection refused” on :3000/:8000 | You used the production `docker-compose.yml`. Use `docker-compose.dev.yml` instead. |

---

After the first successful run you should see the CareSync login screen at **http://localhost:3000**.
