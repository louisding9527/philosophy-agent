# One-click dev startup: middleware containers (PostgreSQL / Qdrant / Neo4j) + FastAPI backend
# Usage: .\start-dev.ps1   (if blocked by ExecutionPolicy: powershell -ExecutionPolicy Bypass -File .\start-dev.ps1)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Test-DockerEngine {
    docker info 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Wait-Port([int]$Port, [int]$TimeoutSec = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $client.Connect("127.0.0.1", $Port)
            $client.Dispose()
            return $true
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker CLI not found. Install Docker Desktop first."
}

# [1/3] Docker engine: auto-start Docker Desktop if it is not running
Write-Host "[1/3] Checking Docker engine..." -ForegroundColor Cyan
if (-not (Test-DockerEngine)) {
    Write-Host "Docker engine not running. Starting Docker Desktop..." -ForegroundColor Yellow
    $desktop = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $desktop) {
        throw "Docker Desktop not found. Start it manually."
    }
    Start-Process $desktop
    $up = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-DockerEngine) { $up = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $up) {
        throw "Docker engine did not come up within 90s. Check Docker Desktop."
    }
}
Write-Host "Docker engine ready." -ForegroundColor Green

# [2/3] Middleware containers
Write-Host "[2/3] Starting middleware containers (docker compose)..." -ForegroundColor Cyan
Push-Location "$Root\docker"
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "docker compose up failed (exit $LASTEXITCODE)."
}
Pop-Location

# Dependencies ready before backend: postgres healthcheck + neo4j Bolt warm-up
Write-Host "Waiting for postgres (healthy)..." -ForegroundColor DarkGray
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    $status = docker inspect --format '{{.State.Health.Status}}' philosophy-postgres 2>$null
    if ($status -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $healthy) {
    throw "postgres did not become healthy within 90s."
}

Write-Host "Waiting for neo4j Bolt (port 7687)..." -ForegroundColor DarkGray
if (-not (Wait-Port 7687)) {
    throw "neo4j Bolt not ready within 90s."
}

# [3/3] FastAPI backend — skip if something already listens on 8000
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port 8000 already in use - backend seems to be running. Skipping backend start." -ForegroundColor Yellow
    exit 0
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found. Install it (https://docs.astral.sh/uv) before starting the backend."
}

Write-Host "[3/3] Starting FastAPI backend at http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Write-Host "Ctrl+C stops the backend only. Containers keep running." -ForegroundColor Yellow
Push-Location "$Root\backend"
uv run uvicorn app.main:app --reload
Pop-Location
