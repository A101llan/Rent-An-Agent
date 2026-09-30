# Create AgentHub PostgreSQL role, database, and extensions (Windows local dev)
# Requires PostgreSQL 17+ running on localhost:5432

param(
    [string]$PostgresPassword = "postgres",
    [string]$AppUser = "agenthub",
    [string]$AppPassword = "agenthub",
    [string]$Database = "agenthub"
)

$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (-not (Test-Path $psql)) {
    Write-Error "PostgreSQL not found at $psql. Install with: winget install PostgreSQL.PostgreSQL.17"
    exit 1
}

$env:PGPASSWORD = $PostgresPassword

Write-Host "Creating role $AppUser..." -ForegroundColor Cyan
& $psql -U postgres -h localhost -w -c @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$AppUser') THEN
    CREATE ROLE $AppUser LOGIN PASSWORD '$AppPassword';
  END IF;
END `$`$;
"@

$dbExists = & $psql -U postgres -h localhost -w -t -c "SELECT 1 FROM pg_database WHERE datname='$Database';" 2>$null
if ($dbExists -match "1") {
    Write-Host "Database $Database already exists." -ForegroundColor Yellow
} else {
    Write-Host "Creating database $Database..." -ForegroundColor Cyan
    & $psql -U postgres -h localhost -w -c "CREATE DATABASE $Database OWNER $AppUser;"
}

Write-Host "Enabling extensions..." -ForegroundColor Cyan
@'
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
'@ | & $psql -U postgres -h localhost -w -d $Database

$env:PGPASSWORD = $AppPassword
& $psql -U $AppUser -h localhost -w -d $Database -c "SELECT current_user AS user, current_database() AS database;"
Write-Host "Database ready: postgresql://$AppUser`:$AppPassword@localhost:5432/$Database" -ForegroundColor Green
