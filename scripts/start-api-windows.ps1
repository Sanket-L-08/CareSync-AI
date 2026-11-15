$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root 'services/api'
Set-Location $ApiDir

$env:APP_ENV = 'development'
$env:SEED_DEMO = 'true'
$env:REQUIRE_MFA_FOR_STAFF = 'false'
$env:DATABASE_URL = 'sqlite:///./caresync.db'
$env:STORAGE_BACKEND = 'local'
$env:LOCAL_STORAGE_DIR = (Join-Path $ApiDir 'private-storage')
$env:CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:ALLOWED_HOSTS = 'localhost,127.0.0.1'

& (Join-Path $ApiDir '.venv/Scripts/Activate.ps1')
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
