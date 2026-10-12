# AgentHub

**Rent AI agents that get work done.**

A secure AI agent marketplace and rental platform where developers publish executable agents and customers discover, hire, rent, execute, monitor, and pay for them.

## Quick Start

### With Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

> **Docker won't start?** Enable **Intel VT-x** in BIOS, then enable **Virtual Machine Platform** + **WSL** in Windows. See troubleshooting below.

### Without Docker (local dev)

Requires PostgreSQL and Redis installed locally:

```powershell
winget install PostgreSQL.PostgreSQL.17
winget install Redis.Redis
Copy-Item .env.local.example .env
.\scripts\local-dev.ps1 -CheckOnly   # verify prerequisites
.\scripts\local-dev.ps1 -SetupOnly   # DB + migrations + seed
.\scripts\local-dev.ps1              # start api, runtime-manager, web
```

Uses `RUNTIME_PROVIDER=mock` — no container virtualization needed. Redis on Windows 3.x is supported (the API client uses RESP2).

**Renter API:** See [docs/RENTER_API.md](docs/RENTER_API.md) and `scripts/examples/rent-and-execute.py`.

**Local runtime contract:** See [docs/local-runtime-contract.md](docs/local-runtime-contract.md).

- **Web:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Runtime manager:** http://localhost:8001/health

## Human Approval Demo

In the workspace, send: *"Please send email to supplier@example.com"*

The agent pauses and shows **Approve Once**, **Approve For Session**, or **Deny**.

## Docker Runtime

With Docker available:

```bash
RUNTIME_PROVIDER=docker docker compose up --build
```

Agent containers use hardened security settings (non-root, read-only FS, dropped caps).

## Observability

Set `OTEL_ENDPOINT=http://jaeger:4317` to enable OpenTelemetry tracing (Jaeger config commented in docker-compose.yml).

## End-to-End Demo

1. Log in as `customer@agenthub.dev` / `Customer123!`
2. Browse **Marketplace** → **Invoice Analyzer**
3. Click **HIRE AGENT** → select 30 minutes → **AUTHORIZE & START**
4. Open **Workspace** → send an invoice analysis request
5. Watch usage recorded; session expires when timer reaches 00:00

## MVP Features

- User auth (register, login, JWT + refresh rotation)
- Marketplace with search, filters, agent detail, reviews
- Developer dashboard and agent publishing
- Rental + session lifecycle with billing (mock provider)
- Runtime manager with MockRuntimeProvider + DockerRuntimeProvider
- Human approval workflow for high-risk agent actions
- OpenTelemetry instrumentation (optional via OTEL_ENDPOINT)
- Agent workspace with timer, execution, usage
- Cross-tenant security tests
- 5 demo agents with seed data

## Docker Troubleshooting

If Docker Desktop reports **virtualization not detected**:

1. **BIOS** — Enable **Intel Virtualization Technology (VT-x)** (HP EliteBook: F10 → Advanced → System Options)
2. **Reboot** and verify: `Get-CimInstance Win32_Processor | Select VirtualizationFirmwareEnabled` → `True`
3. **Admin PowerShell** — Enable VM Platform + WSL, then reboot:
   ```powershell
   dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   wsl --install
   ```
4. Start **Docker Desktop**, then `docker compose up --build`

Until VT-x is enabled, use **local dev** (see above).

Full step-by-step: [docs/ENABLE_VTX.md](docs/ENABLE_VTX.md)

Verify after BIOS change:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-virtualization.ps1
```

## Development Credentials

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@agenthub.dev | Admin123! |
| Developer | dev@agenthub.dev | Dev123! |
| Customer | customer@agenthub.dev | Customer123! |

> Development only. Never use in production.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design, service boundaries, and security model.

## Database

See [docs/DATABASE.md](docs/DATABASE.md) for ERD and schema documentation.

## Implementation Plan

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for phased delivery roadmap.

## Project Structure

```
apps/
  web/                 Next.js frontend
  api/                 FastAPI backend
  runtime-manager/     Container orchestration
  worker/              Background jobs (Celery)
packages/
  agent-sdk/           Python SDK for agent developers
  shared-types/          Shared TypeScript types
agents/                  Demo agent implementations
infra/                   Docker, K8s, Terraform
docs/                    Architecture & security docs
```

## Tech Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS, shadcn/ui
- **Backend:** Python 3.13+, FastAPI, SQLAlchemy 2, Alembic, asyncpg
- **Database:** PostgreSQL 16
- **Cache/Jobs:** Redis, Celery
- **Storage:** MinIO (dev) / S3-compatible (prod)
- **Runtime:** Docker (MVP)

## License

Proprietary — All rights reserved.
