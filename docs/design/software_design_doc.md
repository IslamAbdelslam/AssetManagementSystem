# Software Design Document
## DarkAtlas — Asset Management System

**Version:** 1.0  
**Date:** June 2026  
**Author:** Islam Abdelslam

---

## 1. Introduction

### 1.1 Purpose
This document describes the software design of the DarkAtlas Asset Management System (AMS) — a production-grade, multi-tenant cybersecurity asset management platform. It covers architectural decisions, module responsibilities, data models, and security design.

### 1.2 Scope
The system provides:
- Full CRUD and idempotent upsert for cybersecurity assets (domains, IPs, services, certificates, technologies)
- Asynchronous bulk import supporting millions of records
- Asset relationship graph with BFS traversal and D3.js visualization
- AI-powered natural language querying with a Pydantic hallucination guard
- Multi-tenant isolation at the row or database level
- RS256 JWT authentication with RBAC

---

## 2. System Architecture

### 2.1 Layered Architecture

The system follows a strict 4-layer architecture:

```
┌─────────────────────────────────────────┐
│            Router Layer (FastAPI)        │  HTTP in/out, auth/RBAC deps
├─────────────────────────────────────────┤
│            Service Layer                │  Business logic, orchestration
├─────────────────────────────────────────┤
│           Repository Layer              │  Org-scoped SQL, no leaks
├─────────────────────────────────────────┤
│       Infrastructure (DB / Redis)       │  PostgreSQL 16, Redis 8
└─────────────────────────────────────────┘
```

**Why this layering?**
- **Router** never touches the database directly — it only calls service functions.
- **Service** never constructs SQL — it only calls repository methods.
- **Repository** always scopes queries to `org_id` — cross-tenant leaks are impossible even if the service layer passes the wrong org.

### 2.2 Component Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│                       FastAPI Application                          │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌────────┐ │
│  │ auth/router │  │assets/router │  │graph/router │  │ai/rtr  │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  └───┬────┘ │
│         │                │                  │              │      │
│  ┌──────▼──────┐  ┌──────▼───────┐  ┌──────▼──────┐  ┌───▼────┐ │
│  │ auth/service│  │assets/service│  │graph/service│  │chains  │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  └───┬────┘ │
│         │                │                  │              │      │
│         └────────────────┴──────────────────┘              │      │
│                          │                                 │      │
│              ┌───────────▼────────────┐                   │      │
│              │   AssetRepository      │◄──────────────────┘      │
│              │   (org_id scoped)      │                          │
│              └───────────┬────────────┘                          │
└──────────────────────────┼────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼────────┐     ┌──────────▼────────┐
     │  PostgreSQL 16  │     │     Redis 8        │
     │                 │     │                    │
     │  - assets       │     │  - session cache   │
     │  - users        │     │  - job progress    │
     │  - orgs         │     │  - celery broker   │
     │  - import_jobs  │     │  - rate limit state│
     └─────────────────┘     └────────────────────┘
```

---

## 3. Module Design

### 3.1 `app/auth/`

**Responsibility:** Authentication and authorization.

| File | Purpose |
|---|---|
| `models.py` | `Organization`, `User` ORM models |
| `schemas.py` | `RegisterRequest`, `LoginRequest`, `TokenResponse` |
| `service.py` | JWT signing/verification, bcrypt, RBAC dependencies |
| `router.py` | `/register`, `/login`, `/refresh`, `/me` endpoints |

**Key Design Decisions:**
- **RS256 asymmetric** — private key signs, public key verifies. Verifying services never need the signing key.
- **Refresh token rotation** — old token invalidated on use (prevents replay attacks).
- **Redis storage** — refresh tokens stored as `SHA-256(token)` hash. Instant revocation without DB query.
- **Constant-time verify** — prevents timing oracle even for non-existent users.

### 3.2 `app/assets/`

**Responsibility:** Core asset management.

| File | Purpose |
|---|---|
| `models.py` | `Asset`, `AssetRelationship`, `ImportJob` ORM models |
| `schemas.py` | All Pydantic schemas with validators and sanitization |
| `repository.py` | All DB operations scoped to `org_id` |
| `service.py` | Business logic: dedup, merge strategy, lifecycle |
| `router.py` | All asset CRUD, bulk-import, relationships, graph endpoints |

**Upsert / Dedup Strategy:**
```sql
INSERT INTO assets (id, org_id, type, value, ...)
VALUES (...)
ON CONFLICT ON CONSTRAINT uq_asset_org_type_value
DO UPDATE SET
  last_seen = NOW(),
  status    = CASE WHEN excluded.status = 'active' THEN 'active' ELSE assets.status END,
  tags      = ARRAY(SELECT DISTINCT unnest(assets.tags || excluded.tags)),
  metadata  = assets.metadata || excluded.metadata;
```
- **Dedup key:** `(org_id, type, value)` — enforced by PostgreSQL UNIQUE constraint.
- **Tag merge:** union (no data loss).
- **Metadata merge:** incoming wins per-key (JSONB `||` operator).
- **Status reactivation:** stale assets become active again if re-imported as active.

### 3.3 `app/jobs/`

**Responsibility:** Async bulk import via Celery.

```
POST /assets/bulk-import
  → Create ImportJob (DB)
  → celery.delay(job_id, org_id, records)
     → Chunk into 5,000-record batches
     → asyncpg executemany upsert per chunk
     → hset(job_id, imported=N, error_count=M) after each chunk
     → Sync ImportJob in DB on completion
```

**Celery Config Decisions:**
- `task_acks_late=True` — task re-queued if worker crashes mid-batch.
- `worker_prefetch_multiplier=1` — fair dispatch, no worker starvation.
- Errors capped at 500 entries to prevent Redis key size explosion.

### 3.4 `app/graph/`

**Responsibility:** Asset relationship graph.

- **BFS traversal** — iterative (not recursive) to avoid Python stack overflow on deep/cyclic graphs.
- **Depth clamped** to 1–5 hops server-side (prevents unbounded queries).
- **D3.js visualization** — served as a static HTML page from `/graph`, authenticated via JWT.

### 3.5 `app/ai/`

**Responsibility:** AI-powered querying with hallucination guard.

```
POST /ai/query { "query": "expired certs on prod" }
  → Gemini (temp=0) → outputs JSON filter schema
  → Pydantic validates filter fields
  → Repository.list_assets(validated_filter)
  → Return real DB records

POST /ai/summarize
  → Fetch DB data first (real records)
  → Pass JSON data to Gemini
  → LLM generates text summary of provided data only
```

**Why temp=0?** Deterministic, reproducible filter generation — no creative variation in security queries.

**Hallucination guard:** LLM outputs a *filter*, not *assets*. All returned records come exclusively from real DB queries.

### 3.6 `app/lifecycle/`

**Responsibility:** Background lifecycle management.

- **APScheduler AsyncIOScheduler** — in-process, no Celery overhead for a simple cron.
- `max_instances=1` — prevents overlapping stale jobs on slow databases.
- Marks assets `stale` if `last_seen < NOW() - INTERVAL '{threshold} days'` and `status = 'active'`.

---

## 4. Data Model

### 4.1 Entity Relationship Diagram

```
organizations
  ├── id (PK, UUID)
  ├── name
  └── slug (UNIQUE)
        │
        │ 1:N
        ▼
users
  ├── id (PK, UUID)
  ├── org_id (FK → organizations)
  ├── email (UNIQUE per org)
  ├── password_hash
  └── role  (admin | analyst | readonly)

        │
        │ 1:N
        ▼
assets
  ├── id (PK, UUID)
  ├── org_id (FK → organizations)
  ├── type    (domain|subdomain|ip_address|service|certificate|technology)
  ├── value   (max 512 chars)
  ├── status  (active|stale|archived)
  ├── source  (scan|import|manual)
  ├── tags    (ARRAY of text, GIN indexed)
  ├── metadata (JSONB, GIN indexed)
  ├── first_seen (timestamp)
  └── last_seen  (timestamp)
  UNIQUE (org_id, type, value)

asset_relationships
  ├── id (PK, UUID)
  ├── org_id    (FK → organizations)
  ├── source_id (FK → assets)
  ├── target_id (FK → assets)
  └── rel_type  (subdomain_of|resolves_to|covered_by|runs_on|belongs_to)
  UNIQUE (org_id, source_id, target_id, rel_type)

import_jobs
  ├── id (PK, UUID)
  ├── org_id (FK → organizations)
  ├── status  (queued|running|done|failed)
  ├── total
  ├── imported
  └── error_count
```

### 4.2 Database Indexes

| Index | Type | Purpose |
|---|---|---|
| `(org_id, type)` | B-tree composite | Filtered asset list by type |
| `(org_id, status)` | B-tree composite | Lifecycle/status queries |
| `(org_id, last_seen)` | B-tree composite | Stale asset detection |
| `tags` | GIN | Array containment `@>` queries |
| `metadata` | GIN | JSONB key-value queries |
| `(source_id)`, `(target_id)` on relationships | B-tree | BFS traversal |

---

## 5. Security Design

### 5.1 Authentication Flow

```
Login
  → bcrypt.verify(plain, hash)  ← constant-time
  → Generate RS256 access token (15m TTL)
  → Generate 32-byte random refresh token
  → Store SHA-256(refresh_token) in Redis with 7d TTL
  → Return both tokens to client

Refresh
  → Receive refresh token
  → Compute SHA-256(token), lookup in Redis
  → Invalidate old token (rotation)
  → Issue new pair
```

### 5.2 RBAC Matrix

| Endpoint | readonly | analyst | admin |
|---|---|---|---|
| GET assets | ✅ | ✅ | ✅ |
| POST / PATCH assets | ❌ | ✅ | ✅ |
| DELETE assets | ❌ | ❌ | ✅ |
| Bulk import | ❌ | ✅ | ✅ |
| Mark stale | ❌ | ❌ | ✅ |
| AI query | ✅ | ✅ | ✅ |

### 5.3 Input Sanitization

All string inputs pass through `sanitize_string()`:
- Strips null bytes (`\x00`) — prevents null-byte injection
- Normalizes to lowercase
- Enforces max length (512 for values, 64KB for metadata)
- Validates against allowlist for `type`, `status`, `source`, `rel_type`

---

## 6. API Design Principles

- **REST** conventions with versioned prefix `/api/v1/`
- **Idempotent upserts** — `POST /assets` is safe to call multiple times
- **Pagination capped** at 100 records per request (`page_size` max)
- **Soft deletes** — `DELETE` archives, never hard-deletes
- **Structured errors** — all error responses follow `{"detail": "..."}` (no stack traces)
- **Request-ID** — every response includes `X-Request-ID` for tracing

---

## 7. CI / CD Pipeline

```
git push → GitHub Actions CI
  1. ruff check      — linting (F401, E402, ...)
  2. mypy            — static type checking
  3. bandit -ll      — SAST: blocks HIGH severity findings
  4. pip-audit       — CVE scan against NIST NVD
  5. pytest          — functional tests against real PostgreSQL + Redis

All 5 must pass → merge to main allowed
```
