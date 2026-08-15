# One-click dev startup: middleware containers (PostgreSQL / Qdrant / Neo4j) + FastAPI backend
# Usage: .\start-dev.ps1   (if blocked by ExecutionPolicy: powershell -ExecutionPolicy Bypass -File .\start-dev.ps1)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "[1/2] Starting middleware containers (docker compose)..." -ForegroundColor Cyan
Push-Location "$Root\docker"
docker compose up -d
Pop-Location

Write-Host "[2/2] Starting FastAPI backend at http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Write-Host "Ctrl+C stops the backend only. Containers keep running." -ForegroundColor Yellow
Push-Location "$Root\backend"
uv run uvicorn app.main:app --reload
Pop-Location
