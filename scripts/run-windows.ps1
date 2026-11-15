$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root 'services/api'
$WebDir = Join-Path $Root 'apps/web'
$ApiVenvPython = Join-Path $ApiDir '.venv/Scripts/python.exe'
$ApiScript = Join-Path $PSScriptRoot 'start-api-windows.ps1'
$WebScript = Join-Path $PSScriptRoot 'start-web-windows.ps1'

Write-Host '=== CareSync AI local launcher ===' -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python Launcher (py) was not found. Install Python 3.12 from https://www.python.org/downloads/ and tick Add Python to PATH.'
}
$py312 = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 is required for the pinned backend dependencies. Install it from https://www.python.org/downloads/release/python-31210/ then reopen VS Code.'
}
Write-Host "Using $py312" -ForegroundColor Green

if (-not (Test-Path $ApiVenvPython)) {
    Write-Host 'Creating backend virtual environment...' -ForegroundColor Yellow
    & py -3.12 -m venv (Join-Path $ApiDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
Write-Host 'Installing/checking backend packages...' -ForegroundColor Yellow
& $ApiVenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not upgrade pip.' }
& $ApiVenvPython -m pip install -r (Join-Path $ApiDir 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed. See the error above.' }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js/npm was not found. Install the current Node.js LTS release from https://nodejs.org/ and reopen VS Code.'
}
if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
    Write-Host 'Installing frontend packages (first run only)...' -ForegroundColor Yellow
    Push-Location $WebDir
    npm install
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) { throw 'Frontend dependency installation failed.' }
}

$envFile = Join-Path $WebDir '.env.local'
$apiLine = 'NEXT_PUBLIC_API_URL=http://localhost:8000'
if (Test-Path $envFile) {
    $envText = Get-Content $envFile -Raw
    if ($envText -match '(?m)^NEXT_PUBLIC_API_URL=.*$') {
        $envText = [regex]::Replace($envText, '(?m)^NEXT_PUBLIC_API_URL=.*$', $apiLine)
    } else {
        $envText = $envText.TrimEnd() + "`r`n" + $apiLine + "`r`n"
    }
    Set-Content -Path $envFile -Value $envText -Encoding ascii
} else {
    Set-Content -Path $envFile -Value $apiLine -Encoding ascii
}

# Reuse an already-running CareSync server; otherwise start each service in its own terminal.
$apiUp = $false
try { $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2; $apiUp = $true } catch {}
if (-not $apiUp) {
    Write-Host 'Starting FastAPI backend in a new terminal...' -ForegroundColor Yellow
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $ApiDir -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',"`"$ApiScript`"") | Out-Null
}

$webUp = $false
try { $null = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2; $webUp = $true } catch {}
if (-not $webUp) {
    Write-Host 'Starting Next.js frontend in a new terminal...' -ForegroundColor Yellow
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $WebDir -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',"`"$WebScript`"") | Out-Null
}

Write-Host 'Waiting for backend and frontend...' -ForegroundColor Yellow
$apiReady = $false
$webReady = $false
for ($i = 0; $i -lt 90; $i++) {
    if (-not $apiReady) { try { $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2; $apiReady = $true } catch {} }
    if (-not $webReady) { try { $null = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2; $webReady = $true } catch {} }
    if ($apiReady -and $webReady) { break }
    Start-Sleep -Seconds 2
}
if (-not $apiReady) { throw 'Backend did not become ready. Check the CareSync API terminal for its error.' }
if (-not $webReady) { throw 'Frontend did not become ready. Check the CareSync web terminal for its error.' }
Write-Host 'CareSync AI is ready at http://localhost:3000' -ForegroundColor Green
Write-Host 'API docs: http://localhost:8000/docs' -ForegroundColor Green
