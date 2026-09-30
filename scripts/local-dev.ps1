# AgentHub local development (no Docker)
# Requires: Python 3.12+, Node.js, PostgreSQL, Redis
# Usage: .\scripts\local-dev.ps1 [-SetupOnly] [-CheckOnly]

param(
    [switch]$SetupOnly,
    [switch]$CheckOnly
)

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Test-Port($port) {
    (Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded
}

function Write-Status($label, $ok, $hint = "") {
    $icon = if ($ok) { "[OK]" } else { "[--]" }
    Write-Host "$icon $label" -ForegroundColor $(if ($ok) { "Green" } else { "Yellow" })
    if ($hint -and -not $ok) { Write-Host "    $hint" -ForegroundColor DarkGray }
}

Write-Host ""
Write-Host "AgentHub Local Dev Check" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host ""

$py = Get-Command python -ErrorAction SilentlyContinue
$node = Get-Command node -ErrorAction SilentlyContinue
$pg = Test-Port 5432
$redis = Test-Port 6379

Write-Status "Python" ($null -ne $py) "Install Python 3.12+"
Write-Status "Node.js" ($null -ne $node) "Install Node.js 20+"
Write-Status "PostgreSQL :5432" $pg "winget install PostgreSQL.PostgreSQL.17"
Write-Status "Redis :6379" $redis "winget install Redis.Redis  (or Memurai.MemuraiDeveloper)"

$vt = $false
try {
    $vt = (Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled
} catch {}
Write-Status "VT-x (for Docker)" $vt "Enable Virtualization Technology in BIOS (F10 on HP EliteBook)"

if ($CheckOnly) { exit 0 }

if (-not $pg) {
    Write-Host ""
    Write-Host "Install PostgreSQL: winget install PostgreSQL.PostgreSQL.17" -ForegroundColor Yellow
    exit 1
}

if (-not $redis) {
    Write-Host ""
    Write-Host "Install Redis (Memurai): winget install Memurai.MemuraiDeveloper" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Setting up database..." -ForegroundColor Cyan
& "$PSScriptRoot\setup-db.ps1"
if ($LASTEXITCODE -ne 0) { exit 1 }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.local.example" ".env"
    Write-Host "Created .env from .env.local.example" -ForegroundColor Green
}

Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
Set-Location "$Root\apps\api"
python -m pip install -q -r requirements.txt
Set-Location "$Root\apps\runtime-manager"
python -m pip install -q -r requirements.txt

Write-Host "Running migrations and seed..." -ForegroundColor Cyan
Set-Location "$Root\apps\api"
$env:DATABASE_URL = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"
$env:DATABASE_URL_SYNC = "postgresql://agenthub:agenthub@localhost:5432/agenthub"
$env:REDIS_URL = "redis://localhost:6379/0"
alembic upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.scripts.seed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($SetupOnly) {
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
    Write-Host "Setup complete. Start services manually." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Starting services in new windows..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\apps\runtime-manager'; `$env:RUNTIME_PROVIDER='mock'; `$env:REDIS_URL='redis://localhost:6379/0'; uvicorn app.main:app --reload --port 8001"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\apps\api'; `$env:DATABASE_URL='postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub'; `$env:REDIS_URL='redis://localhost:6379/0'; uvicorn app.main:app --reload --port 8000"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\apps\web'; `$env:NEXT_PUBLIC_API_URL='http://localhost:8000'; npm run dev"
}

Write-Host ""
Write-Host "Ready:" -ForegroundColor Green
Write-Host "  Web:     http://localhost:3000"
Write-Host "  API:     http://localhost:8000/docs"
Write-Host "  Runtime: http://localhost:8001/health  (mock provider)"
Write-Host ""
Write-Host "Login: customer@agenthub.dev / Customer123!"
Write-Host ""
Write-Host "For Docker: enable VT-x in BIOS, install WSL, then docker compose up --build"
