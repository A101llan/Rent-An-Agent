# AgentHub — Implementation Plan

## Current State

- **Repository:** Empty greenfield project at `AgentHub/`
- **Git:** Not initialized
- **Starting phase:** Phase 1 — Foundation

---

## Phase Overview

| Phase | Scope | Exit Criteria |
|-------|-------|---------------|
| **1 — Foundation** | Monorepo, Docker Compose, auth, DB models, RBAC | `docker compose up` works; login/register; health checks pass |
| **2 — Marketplace** | Agent CRUD, marketplace UI, search, reviews, pricing | 5 demo agents visible; agent detail page works |
| **3 — Rental** | Rental/session lifecycle, billing mock, expiration | Full rental → session flow with billing |
| **4 — Runtime** | RuntimeProvider, Docker, SDK, 5 demo agents | Container starts; `/invoke` works |
| **5 — Workspace** | Chat UI, streaming, timer, usage display | End-to-end invoice demo works |
| **6 — Security** | Audit, secrets, approvals, rate limiting, verification | Critical security tests pass |
| **7 — Observability** | OpenTelemetry, metrics, traces | Traces visible in dev |
| **8 — Production** | K8s manifests, CI/CD, signing prep, deployment docs | CI green; deploy docs complete |

---

## Phase 1 — Foundation (Current)

### 1.1 Monorepo Scaffold

```
apps/web/           Next.js 15 + Tailwind + shadcn/ui
apps/api/           FastAPI + SQLAlchemy 2 + Alembic
apps/runtime-manager/   FastAPI stub
apps/worker/        Celery stub
packages/agent-sdk/     Python package stub
packages/shared-types/  TypeScript types
docker-compose.yml
.env.example
```

### 1.2 Infrastructure Services

- PostgreSQL 16 with init script for extensions
- Redis 7
- MinIO
- All services networked via Docker Compose

### 1.3 API Foundation

- [x] FastAPI app with lifespan, CORS, middleware
- [x] SQLAlchemy 2 async engine + session factory
- [x] Alembic migrations for all core tables
- [x] Pydantic settings from environment
- [x] Request ID middleware
- [x] Standard error response format
- [x] `/health` and `/ready` endpoints

### 1.4 Authentication

- [x] Email/password registration
- [x] Argon2 password hashing (via `argon2-cffi`)
- [x] JWT access tokens (15 min)
- [x] Refresh tokens with rotation (HTTP-only cookie)
- [x] Token revocation on logout
- [x] Account lock after failed attempts
- [x] Rate limiting on login/register (Redis)

### 1.5 RBAC

- [x] Roles: CUSTOMER, DEVELOPER, ADMIN
- [x] Dependency injection for role checks
- [x] Server-side enforcement (not UI-only)

### 1.6 Database Models

All tables from DATABASE.md Phase 1 subset:
- users, developer_profiles, customer_profiles
- refresh_tokens, api_keys
- audit_logs, security_events

### 1.7 Web Foundation

- [x] Next.js App Router setup
- [x] Tailwind + shadcn/ui
- [x] Login / Register pages
- [x] Landing page skeleton
- [x] API client with auth token handling
- [x] Route protection middleware

### 1.8 Verification

```bash
docker compose up -d
curl http://localhost:8000/health
curl http://localhost:8000/ready
# Register, login, get profile
pytest apps/api/tests/
```

---

## Phase 2 — Marketplace

### 2.1 Agent Models & Migrations
- agents, agent_versions, agent_artifacts, agent_capabilities, agent_permissions, agent_pricing_plans, agent_reviews

### 2.2 Developer API
- `POST /api/v1/developer/agents` — create agent
- `POST /api/v1/developer/agents/{id}/versions` — create version
- `POST /api/v1/developer/agents/{id}/publish` — submit for review

### 2.3 Marketplace API
- `GET /api/v1/marketplace/agents` — search, filter, sort, paginate
- `GET /api/v1/agents/{slug}` — agent detail

### 2.4 Admin API
- Approve/reject agents and developers

### 2.5 Frontend
- `/marketplace` — search, cards, filters
- `/agents/[slug]` — detail page with HIRE button
- `/developer/*` — developer dashboard

### 2.6 Seed Data
- 5 demo agents with capabilities, pricing, reviews

---

## Phase 3 — Rental & Sessions

### 3.1 Rental API
- `POST /api/v1/rentals` — create with idempotency
- Rental state machine: PENDING → ACTIVE → EXPIRED

### 3.2 Session API
- `POST /api/v1/sessions` — create session for rental
- `POST /api/v1/sessions/{id}/extend` — extend with billing
- Session token (hashed storage)

### 3.3 Billing
- `MockBillingProvider` implementation
- Transaction recording with platform fee split
- Integer minor units throughout

### 3.4 Background Jobs
- `expire_sessions` Celery task (60s interval)
- Session cleanup pipeline

### 3.5 Frontend
- Hiring flow wizard
- `/dashboard/rentals`, `/dashboard/sessions`

---

## Phase 4 — Runtime

### 4.1 Runtime Manager Service
- `RuntimeProvider` protocol
- `DockerRuntimeProvider` with security constraints
- Container lifecycle API

### 4.2 Agent SDK
- `marketplace_sdk.Agent` base class
- Execution context, permissions, usage reporting

### 4.3 Demo Agents (5)
- research-agent, resume-agent, invoice-agent, support-agent, asset-agent
- Docker images with manifests
- Asset agent with structured demo data

### 4.4 Execution API
- Internal `POST /invoke` on runtime
- `POST /api/v1/sessions/{id}/execute` gateway

---

## Phase 5 — Agent Workspace

### 5.1 Workspace UI
- Three-panel layout (info, conversation, runtime status)
- Session timer (display only — backend authoritative)
- Cost tracker
- Execution history

### 5.2 Streaming
- SSE for agent output
- WebSocket for real-time status

### 5.3 End-to-End Demo
- Invoice Analyzer: hire → upload → analyze → expire → reject

---

## Phase 6 — Security

- Secret management abstraction
- Human approval workflow
- File upload security
- Agent verification pipeline
- Rate limiting (all endpoints)
- Critical security tests (cross-tenant, expired session, internal endpoint)

---

## Phase 7 — Observability

- OpenTelemetry SDK integration
- Structured logging with request IDs
- Prometheus metrics endpoint
- Runtime monitoring

---

## Phase 8 — Production Readiness

- Kubernetes manifests
- GitHub Actions CI/CD
- Image signing preparation
- SBOM generation hooks
- DEPLOYMENT.md
- THREAT_MODEL.md finalization

---

## Critical Tests (Must Pass)

### Security Test
```
Customer A → rental → runtime A
Customer B → access runtime A → 403 REJECTED
Expired session → execute → 410 REJECTED
Customer → internal runtime endpoint → 403 REJECTED
```

### Lifecycle Test
```
Create Rental → Session → Runtime → Execute → Usage
→ Session Expires → Runtime Destroyed → Credentials Revoked
→ Audit Event → Subsequent Execute REJECTED
```

---

## Development Workflow

After each phase:

1. Run `pytest apps/api/tests/`
2. Run `npm run lint` in apps/web
3. Run `docker compose build && docker compose up`
4. Manual smoke test of new features
5. Update relevant docs

Never leave core functionality as TODO within a phase.
