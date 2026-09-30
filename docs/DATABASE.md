# AgentHub — Database Schema

PostgreSQL is the authoritative transactional database. SQLAlchemy 2.x is the ORM/data-access layer.

## Entity Relationship Diagram

```mermaid
erDiagram
    users ||--o| developer_profiles : has
    users ||--o| customer_profiles : has
    users ||--o{ refresh_tokens : has
    users ||--o{ api_keys : owns

    developer_profiles ||--o{ agents : publishes
    agents ||--o{ agent_versions : has
    agent_versions ||--|| agent_artifacts : has
    agent_versions ||--o{ agent_capabilities : defines
    agent_versions ||--o{ agent_permissions : requires
    agent_versions ||--o{ agent_pricing_plans : offers
    agents ||--o{ agent_reviews : receives

    customer_profiles ||--o{ rentals : creates
    agents ||--o{ rentals : rented
    agent_versions ||--o{ rentals : version_locked
    agent_pricing_plans ||--o{ rentals : priced_by

    rentals ||--o{ rental_sessions : contains
    rental_sessions ||--o| runtime_instances : provisions
    rental_sessions ||--o{ agent_executions : runs
    rental_sessions ||--o{ agent_credentials : scoped

    agent_executions ||--o{ usage_records : meters
    rentals ||--o{ transactions : billed
    transactions ||--|| platform_fees : splits

    users ||--o{ audit_logs : actor
    users ||--o{ security_events : subject
    users ||--o{ notifications : receives

    users {
        uuid id PK
        string email UK
        string password_hash
        enum role
        bool is_active
        bool is_verified
        int failed_login_attempts
        timestamp locked_until
        timestamp created_at
        timestamp updated_at
    }

    developer_profiles {
        uuid id PK
        uuid user_id FK UK
        string display_name
        string company_name
        string bio
        enum status
        timestamp approved_at
    }

    customer_profiles {
        uuid id PK
        uuid user_id FK UK
        string display_name
        string organization
    }

    agents {
        uuid id PK
        uuid developer_id FK
        string slug UK
        string name
        text description
        string category
        string icon_url
        enum status
        bool is_featured
        bool is_verified
        float avg_rating
        int review_count
        timestamp published_at
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }

    agent_versions {
        uuid id PK
        uuid agent_id FK
        string version UK
        jsonb manifest
        jsonb runtime_requirements
        jsonb configuration
        enum status
        timestamp created_at
    }

    agent_artifacts {
        uuid id PK
        uuid agent_version_id FK UK
        string image_registry
        string image_name
        string image_digest UK
        string manifest_url
        enum verification_status
        jsonb scan_results
        timestamp verified_at
    }

    rentals {
        uuid id PK
        uuid customer_id FK
        uuid agent_id FK
        uuid agent_version_id FK
        uuid pricing_plan_id FK
        enum status
        timestamp started_at
        timestamp expires_at
        int total_cost_minor
        string currency
        string idempotency_key UK
        timestamp created_at
    }

    rental_sessions {
        uuid id PK
        uuid rental_id FK
        string token_hash UK
        enum status
        timestamp started_at
        timestamp expires_at
        timestamp last_activity_at
        uuid runtime_instance_id FK
    }

    runtime_instances {
        uuid id PK
        uuid session_id FK
        uuid agent_version_id FK
        string runtime_provider
        string runtime_identifier
        enum status
        int cpu_limit
        int memory_limit_mb
        enum network_policy
        timestamp created_at
        timestamp started_at
        timestamp terminated_at
    }

    agent_executions {
        uuid id PK
        uuid session_id FK
        uuid agent_version_id FK
        enum status
        jsonb input_metadata
        jsonb output_metadata
        jsonb usage_summary
        int duration_ms
        string request_id
        timestamp created_at
        timestamp completed_at
    }

    transactions {
        uuid id PK
        uuid customer_id FK
        uuid rental_id FK
        uuid session_id FK
        enum type
        int gross_amount_minor
        int developer_amount_minor
        int platform_fee_minor
        string currency
        enum status
        string idempotency_key UK
        string external_ref
        timestamp created_at
    }
```

---

## Tables

### Core Identity

#### `users`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| email | VARCHAR(255) | UNIQUE, NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| role | user_role ENUM | NOT NULL, default 'customer' |
| is_active | BOOLEAN | NOT NULL, default true |
| is_verified | BOOLEAN | NOT NULL, default false |
| failed_login_attempts | INTEGER | NOT NULL, default 0 |
| locked_until | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |
| updated_at | TIMESTAMPTZ | NOT NULL, default now() |

**Indexes:** `idx_users_email`, `idx_users_role`

#### `developer_profiles`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users, UNIQUE |
| display_name | VARCHAR(255) | NOT NULL |
| company_name | VARCHAR(255) | |
| bio | TEXT | |
| status | developer_status ENUM | NOT NULL, default 'pending' |
| approved_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `customer_profiles`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users, UNIQUE |
| display_name | VARCHAR(255) | |
| organization | VARCHAR(255) | |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `refresh_tokens`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users |
| token_hash | VARCHAR(255) | UNIQUE, NOT NULL |
| expires_at | TIMESTAMPTZ | NOT NULL |
| revoked_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | NOT NULL |

**Indexes:** `idx_refresh_tokens_user_id`, `idx_refresh_tokens_hash`

---

### Agents & Marketplace

#### `agents`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| developer_id | UUID | FK → developer_profiles |
| slug | VARCHAR(255) | UNIQUE, NOT NULL |
| name | VARCHAR(255) | NOT NULL |
| description | TEXT | NOT NULL |
| category | VARCHAR(100) | NOT NULL |
| icon_url | VARCHAR(500) | |
| status | agent_status ENUM | NOT NULL, default 'draft' |
| is_featured | BOOLEAN | default false |
| is_verified | BOOLEAN | default false |
| avg_rating | NUMERIC(3,2) | default 0 |
| review_count | INTEGER | default 0 |
| published_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |
| deleted_at | TIMESTAMPTZ | soft delete |

**Indexes:** `idx_agents_slug`, `idx_agents_developer_id`, `idx_agents_category`, `idx_agents_status`, `idx_agents_featured` (partial WHERE is_featured), `idx_agents_published` (partial WHERE status = 'published')

#### `agent_versions`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_id | UUID | FK → agents |
| version | VARCHAR(50) | NOT NULL |
| manifest | JSONB | NOT NULL |
| runtime_requirements | JSONB | |
| configuration | JSONB | |
| status | version_status ENUM | NOT NULL, default 'draft' |
| created_at | TIMESTAMPTZ | NOT NULL |

**Unique:** `(agent_id, version)`

#### `agent_artifacts`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_version_id | UUID | FK → agent_versions, UNIQUE |
| image_registry | VARCHAR(500) | NOT NULL |
| image_name | VARCHAR(255) | NOT NULL |
| image_digest | VARCHAR(128) | UNIQUE, NOT NULL |
| manifest_url | VARCHAR(500) | |
| verification_status | verification_status ENUM | default 'pending' |
| scan_results | JSONB | |
| verified_at | TIMESTAMPTZ | |

#### `agent_capabilities`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_version_id | UUID | FK → agent_versions |
| capability | VARCHAR(100) | NOT NULL |

**Unique:** `(agent_version_id, capability)`

#### `agent_permissions`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_version_id | UUID | FK → agent_versions |
| permission | VARCHAR(100) | NOT NULL |
| requires_approval | BOOLEAN | default false |

#### `agent_pricing_plans`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_version_id | UUID | FK → agent_versions |
| name | VARCHAR(100) | NOT NULL |
| pricing_model | pricing_model ENUM | NOT NULL |
| price_minor | INTEGER | NOT NULL |
| currency | VARCHAR(3) | NOT NULL, default 'USD' |
| duration_minutes | INTEGER | for time-based |
| is_active | BOOLEAN | default true |

#### `agent_reviews`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| agent_id | UUID | FK → agents |
| customer_id | UUID | FK → customer_profiles |
| rental_id | UUID | FK → rentals |
| rating | SMALLINT | CHECK 1-5 |
| title | VARCHAR(255) | |
| body | TEXT | |
| created_at | TIMESTAMPTZ | NOT NULL |

**Unique:** `(agent_id, customer_id, rental_id)`

---

### Rentals & Sessions

#### `rentals`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| customer_id | UUID | FK → customer_profiles |
| agent_id | UUID | FK → agents |
| agent_version_id | UUID | FK → agent_versions |
| pricing_plan_id | UUID | FK → agent_pricing_plans |
| status | rental_status ENUM | NOT NULL |
| started_at | TIMESTAMPTZ | |
| expires_at | TIMESTAMPTZ | |
| total_cost_minor | INTEGER | NOT NULL |
| currency | VARCHAR(3) | NOT NULL |
| idempotency_key | VARCHAR(255) | UNIQUE |
| created_at | TIMESTAMPTZ | NOT NULL |

**Indexes:** `idx_rentals_customer_id`, `idx_rentals_status`, `idx_rentals_expires`

#### `rental_sessions`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| rental_id | UUID | FK → rentals |
| token_hash | VARCHAR(255) | UNIQUE, NOT NULL |
| status | session_status ENUM | NOT NULL |
| started_at | TIMESTAMPTZ | |
| expires_at | TIMESTAMPTZ | NOT NULL |
| last_activity_at | TIMESTAMPTZ | |
| runtime_instance_id | UUID | FK → runtime_instances, nullable |

**Indexes:** `idx_sessions_rental_id`, `idx_sessions_status_expires` (partial WHERE status = 'active')

#### `runtime_instances`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| session_id | UUID | FK → rental_sessions |
| agent_version_id | UUID | FK → agent_versions |
| runtime_provider | VARCHAR(50) | NOT NULL, default 'docker' |
| runtime_identifier | VARCHAR(255) | container ID |
| status | runtime_status ENUM | NOT NULL |
| cpu_limit | INTEGER | NOT NULL |
| memory_limit_mb | INTEGER | NOT NULL |
| network_policy | network_policy ENUM | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| started_at | TIMESTAMPTZ | |
| terminated_at | TIMESTAMPTZ | |

---

### Executions & Usage

#### `agent_executions`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| session_id | UUID | FK → rental_sessions |
| agent_version_id | UUID | FK → agent_versions |
| status | execution_status ENUM | NOT NULL |
| input_metadata | JSONB | |
| output_metadata | JSONB | |
| usage_summary | JSONB | |
| duration_ms | INTEGER | |
| request_id | VARCHAR(64) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| completed_at | TIMESTAMPTZ | |

#### `usage_records`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| session_id | UUID | FK → rental_sessions |
| execution_id | UUID | FK → agent_executions, nullable |
| metric_type | VARCHAR(50) | NOT NULL |
| quantity | NUMERIC(20,6) | NOT NULL |
| unit | VARCHAR(20) | NOT NULL |
| recorded_at | TIMESTAMPTZ | NOT NULL |

---

### Billing

#### `transactions`

All amounts in **integer minor units** (cents).

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| customer_id | UUID | FK → customer_profiles |
| rental_id | UUID | FK → rentals, nullable |
| session_id | UUID | FK → rental_sessions, nullable |
| type | transaction_type ENUM | NOT NULL |
| gross_amount_minor | INTEGER | NOT NULL |
| developer_amount_minor | INTEGER | NOT NULL |
| platform_fee_minor | INTEGER | NOT NULL |
| currency | VARCHAR(3) | NOT NULL |
| status | transaction_status ENUM | NOT NULL |
| idempotency_key | VARCHAR(255) | UNIQUE |
| external_ref | VARCHAR(255) | |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `platform_fees`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| transaction_id | UUID | FK → transactions, UNIQUE |
| fee_rate_bps | INTEGER | basis points at time of transaction |
| platform_amount_minor | INTEGER | NOT NULL |
| developer_amount_minor | INTEGER | NOT NULL |

---

### Security & Audit

#### `audit_logs` (append-only)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| actor_id | UUID | FK → users, nullable |
| action | VARCHAR(100) | NOT NULL |
| resource_type | VARCHAR(50) | NOT NULL |
| resource_id | UUID | |
| metadata | JSONB | |
| request_id | VARCHAR(64) | |
| ip_address | INET | |
| created_at | TIMESTAMPTZ | NOT NULL |

**Indexes:** `idx_audit_logs_actor`, `idx_audit_logs_action`, `idx_audit_logs_created`

#### `security_events`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users, nullable |
| event_type | VARCHAR(100) | NOT NULL |
| severity | VARCHAR(20) | NOT NULL |
| metadata | JSONB | |
| request_id | VARCHAR(64) | |
| created_at | TIMESTAMPTZ | NOT NULL |

#### `agent_credentials` (session-scoped)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| session_id | UUID | FK → rental_sessions |
| credential_type | VARCHAR(50) | NOT NULL |
| encrypted_value | BYTEA | NOT NULL |
| expires_at | TIMESTAMPTZ | NOT NULL |
| revoked_at | TIMESTAMPTZ | |

---

### Future: Vector Search (pgvector)

```sql
-- Prepared but not enabled in MVP
-- ALTER TABLE agents ADD COLUMN description_embedding vector(1536);
-- CREATE INDEX idx_agents_embedding ON agents USING ivfflat (description_embedding vector_cosine_ops);
```

Abstraction: `VectorSearchProvider` interface in API layer.

---

## ENUM Types

```sql
CREATE TYPE user_role AS ENUM ('customer', 'developer', 'admin');
CREATE TYPE developer_status AS ENUM ('pending', 'approved', 'suspended', 'rejected');
CREATE TYPE agent_status AS ENUM ('draft', 'pending_review', 'published', 'suspended', 'archived');
CREATE TYPE version_status AS ENUM ('draft', 'pending_verification', 'verified', 'disabled');
CREATE TYPE verification_status AS ENUM ('pending', 'scanning', 'testing', 'passed', 'failed');
CREATE TYPE pricing_model AS ENUM ('per_minute', 'per_hour', 'per_task', 'per_request', 'subscription');
CREATE TYPE rental_status AS ENUM ('pending', 'active', 'paused', 'expired', 'cancelled', 'terminated', 'failed');
CREATE TYPE session_status AS ENUM ('pending', 'active', 'expired', 'terminated');
CREATE TYPE runtime_status AS ENUM ('provisioning', 'starting', 'running', 'stopping', 'terminated', 'failed');
CREATE TYPE network_policy AS ENUM ('none', 'internet_read', 'internet_full', 'allowlist');
CREATE TYPE execution_status AS ENUM ('pending', 'running', 'completed', 'failed', 'waiting_for_approval', 'cancelled');
CREATE TYPE transaction_type AS ENUM ('charge', 'refund', 'extension', 'subscription');
CREATE TYPE transaction_status AS ENUM ('pending', 'completed', 'failed', 'refunded');
```

---

## Transaction Boundaries

**Hold DB transaction:**
- Rental creation (validate + create rental + create transaction)
- Session creation (validate + create session + record audit)
- Payment processing

**Do NOT hold DB transaction:**
- Docker container provisioning (use state machine + retry)
- External billing API calls
- File uploads to object storage

---

## Idempotency Keys

Required on:
- `rentals.idempotency_key`
- `transactions.idempotency_key`
- Session creation (header: `Idempotency-Key`)
- Runtime provisioning (derived from session ID)

---

## Seed Data (Development)

| Entity | Count |
|--------|-------|
| Admin user | 1 |
| Developer user | 1 |
| Customer user | 1 |
| Demo agents | 5 |
| Reviews | 20 |
| Demo rentals | 10 |
| Demo transactions | 20 |

Credentials documented in `.env.example` comments only.
