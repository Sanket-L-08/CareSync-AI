$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $Root 'apps/web'
Set-Location $WebDir
npm run dev -- --hostname 127.0.0.1
