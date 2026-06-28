# 🛡️ DarkAtlas — Asset Management System

> A production-grade, multi-tenant cybersecurity asset management platform with AI-powered querying, async bulk import, and real-time graph visualization.

[![CI](https://github.com/IslamAbdelslam/AssetManagementSystem/actions/workflows/ci.yml/badge.svg)](https://github.com/IslamAbdelslam/AssetManagementSystem/actions)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.138-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)
![Redis](https://img.shields.io/badge/Redis-8.0-red)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 📚 Documentation

| Document | Description |
|---|---|
| [Software Design Doc](docs/design/software_design_doc.md) | Layered architecture, module design, data model, security design, RBAC matrix |
| [System Design](docs/design/system_design.md) | Infrastructure diagram, data flow diagrams, multi-tenancy, scalability |
| [UML Diagrams](docs/design/uml_diagrams/diagrams.md) | Class, sequence, state, deployment, and component diagrams |
| [Project Map](docs/PROJECT_MAP.md) | Living architecture reference (tech stack, system flow, tenant isolation) |
| [Benchmark Report](docs/benchmarking/benchmark_report.md) | Bulk import and API load test results |
| [Learning Guide](docs/LEARNING_GUIDE.md) | Beginner-friendly walkthrough — why every component is where it is |

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔐 **Auth & RBAC** | RS256 JWT · 15m access / 7d refresh · bcrypt-12 · 3 roles (admin / analyst / readonly) |
| 🗂️ **Asset CRUD** | Idempotent upsert with tag-merge · soft delete · full filtering & pagination |
| ⚡ **Bulk Import** | Async Celery jobs · 5,000 records/chunk · live Redis progress · 1M record support |
| 🕸️ **Graph Traversal** | BFS up to 5 hops · D3.js interactive visualization · relationship CRUD |
| 🤖 **AI / NL Query** | Gemini 2.0 Flash (temp=0) · Pydantic hallucination guard · attack surface summarization |
| 🔄 **Lifecycle** | APScheduler cron auto-marks stale assets · reactivation on re-import |
| 🏢 **Multi-Tenancy** | Row-level isolation (default) or separate DB per org |
| 🚦 **Rate Limiting** | Per-endpoint via slowapi (configurable) |
| 📊 **Observability** | structlog JSON · request-ID tracing · Flower task monitor |
| 🛡️ **Security** | OWASP headers · SAST (bandit) · CVE scan (pip-audit) · input sanitization |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client / Browser                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │ HTTP / REST
┌─────────────────────▼───────────────────────────────────────────┐
│            FastAPI Application  (:8000)                          │
│                                                                  │
│  Middleware stack:                                               │
│    Request-ID → Security Headers → CORS → Rate Limiter          │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   Auth   │ │  Assets  │ │  Graph   │ │    AI    │           │
│  │  Router  │ │  Router  │ │  Router  │ │  Router  │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       └────────────┴────────────┴────────────┘                  │
│                         │ Service / Repository layers            │
└─────────────────────────┼───────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
┌─────────▼──────┐ ┌──────▼──────┐ ┌─────▼────────────┐
│  PostgreSQL 16 │ │   Redis 8   │ │   Celery Worker  │
│  (:5433)       │ │  (:6379)    │ │  (Bulk Import)   │
│                │ │             │ │                  │
│  - assets      │ │  - cache    │ └──────────────────┘
│  - users       │ │  - sessions │
│  - orgs        │ │  - job prog │ ┌──────────────────┐
│  - rels        │ │  - broker   │ │  Flower Monitor  │
│  - import_jobs │ └─────────────┘ │  (:5555)         │
└────────────────┘                 └──────────────────┘
```

### Request Lifecycle

```
HTTP Request
  → Request-ID middleware  (inject UUID, bind structlog context)
  → Security Headers       (OWASP: X-Frame-Options, HSTS, CSP, etc.)
  → CORS middleware
  → Rate Limiter           (slowapi, per-endpoint limits)
  → FastAPI Router
    → Auth dependency      (decode RS256 JWT → User + org_id)
    → RBAC dependency      (role check: admin / analyst / readonly)
    → Service layer        (business logic: dedup, merge, lifecycle)
      → Repository layer   (org-scoped parameterized SQL via SQLAlchemy async)
        → PostgreSQL 16    (GIN indexes, upsert ON CONFLICT)
  → Response               (sanitized — no stack traces, no secrets)
```

### Bulk Import Flow

```
POST /assets/bulk-import
  → Validate schema (Pydantic)
  → Create ImportJob record in DB
  → Dispatch Celery task (Redis broker)
     → Chunk into 5,000-record batches
     → asyncpg executemany upsert (ON CONFLICT DO UPDATE)
     → Write progress to Redis hset after each chunk
     → Sync DB record on completion
GET /jobs/{id}
  → Read from Redis (live) or DB (fallback after TTL)
```

### AI Query Flow

```
POST /ai/query  { "query": "show stale prod certs" }
  → Gemini (temp=0) → outputs JSON filter (NOT asset data)
  → Pydantic validates filter schema  ← hallucination guard
  → Real DB query with validated filter
  → Return actual DB records
```

---

## 🛠️ Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Runtime | Python | 3.12 |
| Web Framework | FastAPI + Uvicorn | 0.138 / 0.49 |
| Validation | Pydantic v2 | 2.13 |
| ORM | SQLAlchemy (async) | 2.0 |
| DB Driver | asyncpg | 0.31 |
| Migrations | Alembic | 1.18 |
| Database | PostgreSQL | 16 |
| Cache / Broker | Redis | 8.0 |
| Task Queue | Celery + Flower | 5.6 |
| Rate Limiting | slowapi | 0.1.10 |
| Auth | RS256 JWT + bcrypt-12 | — |
| AI / LLM | LangChain + Gemini 2.0 Flash | — |
| Scheduler | APScheduler | 3.11 |
| Logging | structlog (JSON) | 26.1 |
| CI / SAST | ruff · mypy · bandit · pip-audit | — |

---

## 🔐 Security Highlights

| Concern | Implementation |
|---|---|
| Auth | RS256 asymmetric JWT · 15m access / 7d refresh tokens |
| Password | bcrypt rounds=12 (OWASP minimum: 10) |
| Token revocation | SHA-256 hashed refresh tokens stored in Redis (revocable) |
| Timing attacks | Constant-time verification even for non-existent users |
| User enumeration | Generic error messages on login failure |
| Input | Null-byte rejection · lowercase normalization · 64KB metadata guard |
| OWASP Headers | X-Content-Type-Options · X-Frame-Options · HSTS (prod) · Referrer-Policy · CSP |
| SAST | `bandit -ll` blocks HIGH severity findings in CI |
| CVE scan | `pip-audit` blocks known vulnerabilities in CI |
| Tenant isolation | All queries are `org_id`-scoped at the repository layer |

---

## 🚀 Quick Start

### Prerequisites

- Docker + Docker Compose
- A Gemini API key ([get one free](https://aistudio.google.com/app/apikey))

### 1. Clone & Configure

```bash
git clone git@github.com:IslamAbdelslam/AssetManagementSystem.git
cd AssetManagementSystem
cp .env.example .env
```

### 2. Generate RSA keys for JWT

```bash
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem

# Base64-encode and paste into .env
echo "JWT_PRIVATE_KEY_B64=$(base64 -w 0 private.pem)"
echo "JWT_PUBLIC_KEY_B64=$(base64 -w 0 public.pem)"
```

Edit `.env` and fill in `JWT_PRIVATE_KEY_B64`, `JWT_PUBLIC_KEY_B64`, and `GEMINI_API_KEY`.

### 3. Start all services

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| API (Swagger) | http://localhost:8000/docs |
| Interactive Graph | http://localhost:8000/graph |
| Celery Monitor | http://localhost:5555 |
| Health check | http://localhost:8000/health |

### 4. Run migrations & seed data

```bash
docker compose exec app alembic upgrade head

# Optional: load 60 sample records (2 orgs, 6 asset types)
# Set SEED_ON_STARTUP=true in .env  OR:
docker compose exec app python -c "
import asyncio; from app.assets.service import seed_sample_data
asyncio.run(seed_sample_data())
"
```

---

## 📡 API Reference

### Auth

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Register org + admin user | — |
| POST | `/api/v1/auth/login` | Login, receive tokens | — |
| POST | `/api/v1/auth/refresh` | Rotate refresh token | — |
| GET  | `/api/v1/auth/me` | Current user profile | Bearer |

### Assets

| Method | Endpoint | Description | Min Role |
|---|---|---|---|
| GET | `/api/v1/assets` | List with filters + pagination | readonly |
| POST | `/api/v1/assets` | Create / upsert asset | analyst |
| GET | `/api/v1/assets/{id}` | Get by ID | readonly |
| PATCH | `/api/v1/assets/{id}` | Update asset | analyst |
| DELETE | `/api/v1/assets/{id}` | Archive (soft delete) | admin |
| GET | `/api/v1/assets/stats` | Asset counts by type & status | readonly |
| POST | `/api/v1/assets/bulk-import` | Async import (up to 1M records) | analyst |
| POST | `/api/v1/assets/mark-stale` | Force stale marking | admin |
| GET | `/api/v1/jobs/{id}` | Live import job progress | analyst |

### Relationships & Graph

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/assets/{id}/relationships` | Create relationship |
| GET | `/api/v1/assets/{id}/relationships` | List relationships |
| DELETE | `/api/v1/relationships/{id}` | Delete relationship |
| GET | `/api/v1/assets/{id}/graph` | BFS subgraph (depth 1–5) |
| GET | `/api/v1/graph/data` | Full org graph (D3.js feed) |
| GET | `/api/v1/graph` | Interactive D3.js visualization |

### AI

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/ai/query` | Natural language asset query |
| POST | `/api/v1/ai/summarize` | AI attack surface summary |

### Asset Types & Values

| Type | Example values |
|---|---|
| `domain` | `techcorp.io` |
| `subdomain` | `api.techcorp.io` |
| `ip_address` | `93.184.216.34` |
| `service` | `https://api.techcorp.io:443` |
| `certificate` | `sha256:abc123...` |
| `technology` | `nginx/1.24` |

**Status values:** `active` · `stale` · `archived`  
**Source values:** `scan` · `import` · `manual`  
**Relationship types:** `subdomain_of` · `resolves_to` · `covered_by` · `runs_on` · `belongs_to`

---

## 💡 Example Usage

### Register & Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "org": {"name": "Acme Corp", "slug": "acme"},
    "email": "admin@acme.com",
    "password": "SecurePass123!"
  }'

TOKEN="<access_token from response>"
```

### Upsert a Single Asset

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "domain",
    "value": "acme.io",
    "source": "scan",
    "tags": ["root", "prod"]
  }'
```

### Bulk Import (async, supports 1M+)

```bash
# Submit job
curl -X POST http://localhost:8000/api/v1/assets/bulk-import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"records": [
    {"type": "domain",    "value": "acme.io",     "source": "scan", "tags": ["root"]},
    {"type": "subdomain", "value": "api.acme.io", "source": "scan", "tags": ["prod"]}
  ]}'

# Poll live progress
curl http://localhost:8000/api/v1/jobs/<job_id> \
  -H "Authorization: Bearer $TOKEN"
```

### AI Natural Language Query

```bash
curl -X POST http://localhost:8000/api/v1/ai/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all stale certificates on production subdomains"}'
```

### BFS Graph Traversal

```bash
curl "http://localhost:8000/api/v1/assets/<id>/graph?depth=2" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🏢 Multi-Tenancy

Control via `TENANT_ISOLATION` in `.env`:

| Mode | Description | Use case |
|---|---|---|
| `row` (default) | Shared DB · `org_id` FK isolation at repo layer | Cost-efficient SaaS |
| `database` | Separate PostgreSQL DB per org | Compliance, data sovereignty |

---

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests (uses Docker Compose Postgres + Redis)
pytest tests/ -v --asyncio-mode=auto

# With coverage report
pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html
```

> **Note:** Tests require Docker Compose services to be running (`docker compose up postgres redis`), or set `DATABASE_URL` and `REDIS_URL` environment variables to point to your instances.

---

## 🌿 Branch Strategy

| Branch | Purpose | Protection |
|---|---|---|
| `main` | Production — stable releases | CI must pass · merge from `dev` only |
| `dev` | Active development | Feature branches merged here |
| `feat/*` | New features | Merged into `dev` via PR |
| `fix/*` | Bug fixes | Merged into `dev` via PR |

---

## 📁 Project Structure

```
AssetManagementSystem/
├── app/
│   ├── main.py              # FastAPI factory + middleware stack
│   ├── config.py            # Settings (pydantic-settings + env)
│   ├── database.py          # Async engine + TenantConnectionManager
│   ├── core/
│   │   ├── exceptions.py    # Typed HTTP exceptions
│   │   ├── logging.py       # structlog JSON logger
│   │   ├── pagination.py    # Generic PagedResponse[T]
│   │   ├── rate_limit.py    # slowapi limiter instance
│   │   └── security.py      # Input sanitization + metadata guards
│   ├── auth/                # JWT RS256 · bcrypt · RBAC dependencies
│   ├── assets/              # CRUD · upsert · bulk-import · schemas
│   ├── jobs/                # Celery app + chunked async upsert task
│   ├── graph/               # BFS traversal · D3.js page
│   ├── lifecycle/           # APScheduler (mark-stale cron)
│   ├── ai/                  # Gemini chains · NL query · summarize
│   └── static/              # graph.html (D3.js visualization)
├── alembic/                 # Async database migrations
│   └── versions/            # Migration scripts
├── tests/                   # pytest-asyncio · httpx · mocked LLM
├── data/                    # sample_dataset.json (60 records)
├── docs/                    # All documentation
│   ├── PROJECT_MAP.md       # Living architecture reference
│   ├── benchmarking/        # Locust load tests + benchmark report
│   └── design/
│       ├── software_design_doc.md
│       ├── system_design.md
│       └── uml_diagrams/diagrams.md
├── .github/workflows/
│   └── ci.yml               # Lint → Type-check → SAST → CVE → Test
├── mypy.ini                 # mypy configuration
├── pytest.ini               # pytest configuration
├── docker-compose.yml       # 5 services: app · postgres · redis · celery · flower
├── Dockerfile               # Multi-stage · non-root user
└── entrypoint.sh            # Alembic migrate + uvicorn start
```

---

## 📈 Performance

Based on local benchmarks (see [`docs/benchmarking/benchmark_report.md`](docs/benchmarking/benchmark_report.md)):

| Operation | Throughput |
|---|---|
| Bulk import (1M records) | ~7 min on local hardware |
| Single asset upsert | < 5ms P99 |
| Filtered list (10K assets) | < 20ms P99 (GIN indexes) |
| BFS graph traversal (depth 3) | < 50ms P99 |

---

<div align="center">

Built with ❤️ by **Islam Abdelslam**  
DarkAtlas · Buguard Internship Engineering Task · 2026

</div>
