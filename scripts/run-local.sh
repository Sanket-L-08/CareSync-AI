#!/usr/bin/env bash
# One-command local start helper (API + web). Run from project root.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Starting API on :8000"
cd "$ROOT/services/api"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  . .venv/bin/activate
  pip install -r requirements-dev.txt
else
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
export APP_ENV=development SEED_DEMO=true REQUIRE_MFA_FOR_STAFF=false
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
API_PID=$!

echo "==> Starting Web on :3000"
cd "$ROOT/apps/web"
[ -f .env.local ] || echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local
npm install --silent
npm run dev &
WEB_PID=$!

echo ""
echo "API  → http://localhost:8000"
echo "Web  → http://localhost:3000"
echo "Docs → http://localhost:8000/docs"
echo "Press Ctrl+C to stop both."
trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT
wait
