# DarkAtlas — Asset Management System
# PROJECT_MAP.md — Living architecture document. Updated with every milestone.
# Last updated: 2026-06-24

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
| Auth | python-jose RS256 + passlib bcrypt-12 | 3.5.0 / 1.7.4 |
| Cache + Broker | Redis | 8.0.1 |
| Task Queue | Celery | 5.6.3 |
| Job Monitor | Flower | 2.0.1 |
| Rate Limiting | slowapi | 0.1.10 |
| AI / LLM | langchain-google-genai (Gemini) | 4.2.5 |
| Scheduling | APScheduler | 3.11.2 |
| Logging | structlog | 26.1.0 |
| SAST | bandit | 1.9.4 |
| CVE Scan | pip-audit | 2.10.1 |
| Linting | ruff | 0.11.13 |
| Type Check | mypy | 1.16.1 |

---

## [SYSTEM_FLOW]

```
HTTP Request
  → Request-ID middleware (inject uuid, bind structlog)
  → Security Headers middleware (OWASP headers)
  → CORS middleware
  → FastAPI Router
    → Auth dependency (decode RS256 JWT → User + org_id)
    → RBAC dependency (role check)
    → Request handler
      → Service layer (business logic: dedup, merge, lifecycle)
        → Repository layer (parameterized SQL via SQLAlchemy)
          → PostgreSQL (org-scoped queries)
  → Response (sanitized — no stack traces)

Bulk Import Flow:
  POST /assets/bulk-import
  → Validate sample → Create ImportJob (DB)
  → Enqueue Celery task (Redis broker)
  → Return {job_id, status: "queued"}
  Celery Worker:
    → Chunk records (5000/chunk)
    → asyncpg executemany upsert (ON CONFLICT DO UPDATE)
    → Update progress in Redis hset
    → Update ImportJob in DB on completion
  GET /jobs/{job_id}
  → Redis hgetall (live) or DB fallback

NL Query Flow:
  POST /ai/query
  → LangChain LCEL: ChatPromptTemplate | Gemini(temp=0) | JsonOutputParser
  → Pydantic validate(AssetFilterSchema)   ← hallucination guard
  → Repository.list_assets(validated_filter)
  → Post-filter (e.g. expired certs: metadata.expires < today)
  → Return real DB records only

Lifecycle Flow (hourly cron):
  APScheduler → _mark_stale_job()
  → UPDATE assets SET status='stale'
    WHERE status='active' AND last_seen < NOW() - INTERVAL 'N days'
```

---

## [ARCHITECTURE]

```
┌─────────────────────────────────────────────────────────┐
│                     HTTP Layer                          │
│  FastAPI · Uvicorn · Middleware (headers, request-id)   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    Router Layer                         │
│  /auth  /assets  /ai  /graph  /jobs                     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Service Layer                         │
│  AssetService · AuthService · GraphService              │
│  Business logic: dedup, lifecycle, merge strategy       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 Repository Layer                        │
│  AssetRepository — all SQL queries live here            │
│  org_id-scoped on every query                           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              PostgreSQL 16 (primary store)              │
│  GIN indexes on tags[], metadata JSONB                  │
│  Composite unique: (org_id, type, value)                │
└─────────────────────────────────────────────────────────┘

Cross-cutting:
  Auth ─────── JWT RS256 + bcrypt-12 + Redis refresh tokens
  Logging ──── structlog JSON, request_id + org_id on every line
  Rate Limit ── slowapi (Redis-backed)
  Cache ─────── Redis (GET /assets/{id} TTL 60s)
  Queue ─────── Celery + Redis (bulk import jobs)
  Scheduler ─── APScheduler (stale job, hourly)
```

---

## [TENANT_ISOLATION]

```
TENANT_ISOLATION=row (default):
  - Single PostgreSQL DB
  - Every table has org_id UUID FK → organizations
  - All queries: WHERE org_id = :current_org_id
  - Migrations: single Alembic head

TENANT_ISOLATION=database:
  - Meta DB (darkatlas_meta): stores organizations table + per-org DSN
  - Each org gets: darkatlas_{slug} PostgreSQL database
  - TenantConnectionManager: LRU cache of AsyncEngines (max 50)
  - On org creation: CREATE DATABASE + alembic upgrade on new DB
  - Requires PostgreSQL superuser privileges
```

---

## [SECURITY_POSTURE]

- OWASP API Security Top 10: all items addressed (see implementation_plan.md §11)
- JWT: RS256 asymmetric · Access TTL 15min · Refresh TTL 7d (revocable via Redis)
- Passwords: bcrypt rounds=12
- Error responses: never expose stack traces, DB errors, or internal paths
- Input: null-byte rejection, lowercase normalization, metadata size/depth guards
- CI gates: bandit SAST + pip-audit CVE scan on every push

---

## [ORPHANS & PENDING]

- [ ] WebSocket support for real-time asset push notifications
- [ ] PostgreSQL pg_trgm full-text search (currently ILIKE)
- [ ] Asset audit/history log table (who changed what, when)
- [ ] Cloud deployment config (Railway / Render / GCP)
- [ ] Rate limiting on GET endpoints (currently only write + AI)
- [ ] Swagger UI custom theme (DarkAtlas brand colors)
