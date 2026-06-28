# DarkAtlas — Asset Management System
# PROJECT_MAP.md — Living architecture document. Updated with every milestone.
# Last updated: 2026-06-28

---

## [TECH_STACK]

| Layer | Technology | Version |
|---|---|---|
| Runtime | Python | 3.12 |
| Web Framework | FastAPI | 0.138.0 |
| ASGI Server | Uvicorn | 0.49.0 |
| Validation | Pydantic v2 | 2.13.4 |
| ORM | SQLAlchemy (async) | 2.0.51 |
| Migrations | Alembic | 1.18.4 |
| DB Driver | asyncpg | 0.31.0 |
| Database | PostgreSQL | 16 |
| Auth | RS256 JWT + bcrypt-12 | — |
| Cache + Broker | Redis | 8.0.1 |
| Task Queue | Celery | 5.6.3 |
| Job Monitor | Flower | 2.0.1 |
| Rate Limiting | slowapi | 0.1.10 |
| AI / LLM | langchain-google-genai (Gemini 2.0 Flash) | 4.2.5 |
| Scheduling | APScheduler | 3.11.2 |
| Logging | structlog (JSON) | 26.1.0 |
| SAST | bandit | 1.9.4 |
| CVE Scan | pip-audit | 2.10.1 |
| Linting | ruff | 0.11.13 |
| Type Check | mypy | 1.16.1 |
| Test Coverage | pytest-cov | 6.2.1 |

---

## [SYSTEM_FLOW]

```
HTTP Request
  → Request-ID middleware  (inject uuid, bind structlog)
  → Security Headers       (OWASP: HSTS, X-Frame-Options, CSP, ...)
  → CORS middleware
  → Rate Limiter           (slowapi, per-endpoint)
  → FastAPI Router
    → Auth dependency      (decode RS256 JWT → User + org_id)
    → RBAC dependency      (admin / analyst / readonly)
    → Request handler
      → Service layer      (business logic: dedup, merge, lifecycle)
        → Repository layer (org-scoped parameterized SQL via SQLAlchemy async)
          → PostgreSQL 16  (GIN indexes, upsert ON CONFLICT)
  → Response (sanitized — no stack traces, no secrets)

Bulk Import Flow:
  POST /assets/bulk-import
  → Validate schema (Pydantic) → Create ImportJob (DB, status=queued)
  → Enqueue Celery task (Redis broker) → Return {job_id, status: "queued"}
  Celery Worker:
    → Chunk records (5,000/chunk)
    → asyncpg executemany upsert (ON CONFLICT DO UPDATE)
    → Update progress in Redis HSET after each chunk
    → Sync ImportJob in DB on completion
  GET /jobs/{job_id}
  → Read Redis HSET (live) or DB ImportJob (fallback after TTL)

NL Query Flow:
  POST /ai/query { "query": "stale certs on prod" }
  → Gemini (temp=0) → outputs JSON filter (NOT asset data)
  → Pydantic validates filter schema  ← hallucination guard
  → Repository.list_assets(validated_filter)
  → Return real DB records only (LLM cannot invent assets)

Lifecycle Flow (hourly cron):
  APScheduler → _mark_stale_job()
  → UPDATE assets SET status='stale'
    WHERE status='active' AND last_seen < NOW() - INTERVAL 'N days'
  → Re-imported assets auto-reactivate (status='active' wins on upsert)
```

---

## [ARCHITECTURE]

```
┌─────────────────────────────────────────────────────────┐
│                     HTTP Layer                          │
│  FastAPI · Uvicorn · Middleware (headers, request-id,   │
│  CORS, Rate Limiter)                                    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    Router Layer                         │
│  /auth  /assets  /ai  /graph  /jobs                     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Service Layer                         │
│  AssetService · AuthService · GraphService · AIChains   │
│  Business logic: dedup, lifecycle, merge strategy       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 Repository Layer                        │
│  AssetRepository — all SQL queries live here            │
│  org_id-scoped on every query (no cross-tenant leaks)   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              PostgreSQL 16 (primary store)              │
│  GIN indexes on tags[], metadata JSONB                  │
│  Composite unique: (org_id, type, value)                │
│  Composite B-tree: (org_id, type), (org_id, status),   │
│                    (org_id, last_seen)                  │
└─────────────────────────────────────────────────────────┘

Cross-cutting:
  Auth ─────── JWT RS256 + bcrypt-12 + Redis refresh tokens (hashed)
  Logging ──── structlog JSON, request_id + org_id on every line
  Rate Limit ── slowapi (Redis-backed counters)
  Queue ─────── Celery + Redis (bulk import jobs, broker DB1)
  Scheduler ─── APScheduler AsyncIOScheduler (stale job, hourly, max_instances=1)
```

---

## [TENANT_ISOLATION]

```
TENANT_ISOLATION=row (default):
  - Single PostgreSQL DB
  - Every table has org_id UUID FK → organizations
  - All queries: WHERE org_id = :current_org_id (enforced at repo layer)
  - Migrations: single Alembic head

TENANT_ISOLATION=database:
  - Separate PostgreSQL DB per organization
  - TenantConnectionManager: LRU cache of AsyncEngines (max 50)
  - Connection string: postgresql+asyncpg://.../{org_slug}_db
```

---

## [SECURITY_POSTURE]

- JWT: RS256 asymmetric · Access TTL 15min · Refresh TTL 7d (revocable via Redis)
- Passwords: bcrypt rounds=12 (OWASP minimum: 10)
- Refresh tokens stored as SHA-256 hash in Redis (never raw token in DB)
- Constant-time bcrypt verify (even for non-existent users)
- Generic error messages on auth failure (prevents enumeration)
- Error responses: never expose stack traces, DB errors, or internal paths
- Input: null-byte rejection, lowercase normalization, metadata 64KB guard
- OWASP headers: X-Content-Type-Options, X-Frame-Options, HSTS, Referrer-Policy, CSP
- CI gates: ruff (lint) → mypy (types) → bandit -ll (SAST) → pip-audit (CVE) → pytest

---

## [CI_PIPELINE]

```
git push → GitHub Actions (.github/workflows/ci.yml)
  1. ruff check app/ tests/        — linting (fail on any error)
  2. mypy app/ --ignore-missing-imports  — type checking
  3. bandit -r app/ -ll            — SAST (fail on HIGH severity)
  4. pip-audit --desc on           — CVE scan (fail on known vulns)
  5. pytest tests/ -v              — functional tests (real PG + Redis)
  6. upload-artifact               — test results uploaded
```

---

## [PROJECT_STRUCTURE]

```
AssetManagementSystem/
├── app/                         # Application code
│   ├── main.py                  # FastAPI factory + middleware
│   ├── config.py                # Settings (pydantic-settings)
│   ├── database.py              # Async engine + TenantConnectionManager
│   ├── core/                    # Shared utilities
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   ├── pagination.py
│   │   ├── rate_limit.py
│   │   └── security.py
│   ├── auth/                    # JWT · bcrypt · RBAC
│   ├── assets/                  # CRUD · upsert · bulk-import
│   ├── jobs/                    # Celery app + chunked upsert task
│   ├── graph/                   # BFS traversal · D3.js page
│   ├── lifecycle/               # APScheduler (stale cron)
│   ├── ai/                      # Gemini chains · NL query
│   └── static/                  # graph.html (D3.js)
├── alembic/                     # DB migrations
├── tests/                       # pytest suite + OWASP proofs
├── docs/benchmarking/            # Locust load tests + report
├── data/                        # sample_dataset.json (60 records)
├── docs/                        # Design documentation
│   ├── PROJECT_MAP.md           # This file
│   └── design/
│       ├── software_design_doc.md
│       ├── system_design.md
│       └── uml_diagrams/diagrams.md
├── .github/workflows/ci.yml     # CI pipeline
├── docker-compose.yml           # 5-service stack
├── Dockerfile                   # Multi-stage, non-root
├── entrypoint.sh                # Alembic migrate + uvicorn
├── mypy.ini                     # mypy config
├── pytest.ini                   # pytest config
└── requirements*.txt
```

---

## [ORPHANS & PENDING]

- [ ] WebSocket support for real-time asset push notifications
- [ ] PostgreSQL pg_trgm full-text search (currently ILIKE)
- [ ] Asset audit/history log table (who changed what, when)
- [ ] Cloud deployment config (Railway / Render / GCP)
- [ ] Rate limiting on GET endpoints (currently only write + AI)
- [ ] Swagger UI custom theme (DarkAtlas brand colors)
