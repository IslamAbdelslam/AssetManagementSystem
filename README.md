<div align="center">

# ⬡ DarkAtlas Asset Management System

**A module of the DarkAtlas Attack Surface Monitoring (ASM) platform**  
_Built for Buguard · Internship Engineering Task_

[![CI](https://github.com/IslamAbdelslam/AssetManagementSystem/actions/workflows/ci.yml/badge.svg)](https://github.com/IslamAbdelslam/AssetManagementSystem/actions)
![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)
![Redis](https://img.shields.io/badge/Redis-8.0-DC382D?logo=redis)
![Celery](https://img.shields.io/badge/Celery-5.6-37814A?logo=celery)
![Gemini](https://img.shields.io/badge/Gemini-2.0--flash-4285F4?logo=google)

</div>

---

## 📖 Overview

DarkAtlas ASM continuously discovers and tracks an organization's internet-facing assets — domains, subdomains, IP addresses, exposed services, TLS certificates, and the technologies running on them.

This module is the **system of record** at the heart of the platform:

- **Ingests** discovered assets, removes duplicates, tracks each asset's lifecycle
- **Scales** to 1M+ records via Redis-backed Celery bulk import
- **Analyzes** the attack surface with a mandatory Gemini AI layer
- **Visualizes** asset relationships as an interactive D3.js force-directed graph
- **Isolates** tenant data via dual-mode multi-tenancy (row or database)

---

## 🏗️ Architecture

```
HTTP Request
  → Request-ID middleware  (inject uuid, bind structlog)
  → Security Headers       (OWASP: CSP, HSTS, X-Frame-Options…)
  → FastAPI Router         (/auth · /assets · /ai · /graph · /jobs)
    → Auth dependency      (RS256 JWT → User + org_id)
    → RBAC dependency      (admin / analyst / readonly)
    → Service layer        (dedup, merge, lifecycle)
      → Repository layer   (org-scoped SQL via SQLAlchemy async)
        → PostgreSQL 16    (GIN indexes, upsert ON CONFLICT)

Bulk Import (async):
  POST /assets/bulk-import → Celery task (Redis broker)
  → 5000 records/chunk → asyncpg upsert → Redis progress
  GET  /jobs/{id}          → live progress (Redis) or DB fallback

AI Layer:
  POST /ai/query → Gemini (temp=0) → Pydantic guard → real DB query
  POST /ai/summarize → fetch DB first → LLM summarizes only
```

### Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Web Framework | FastAPI + Uvicorn | 0.138 / 0.49 |
| ORM | SQLAlchemy (async) | 2.0 |
| Migrations | Alembic | 1.18 |
| Database | PostgreSQL | 16 |
| Cache / Broker | Redis | 8.0 |
| Task Queue | Celery + Flower | 5.6 |
| Auth | RS256 JWT + bcrypt-12 | — |
| AI / LLM | LangChain + Gemini 2.0 Flash | — |
| Scheduler | APScheduler | 3.11 |
| Logging | structlog (JSON) | 26.1 |
| CI Gates | bandit (SAST) + pip-audit (CVE) | — |

---

## 🔐 Security Highlights

| Concern | Implementation |
|---|---|
| Auth | RS256 asymmetric JWT · 15m access / 7d refresh |
| Password | bcrypt rounds=12 (OWASP minimum: 10) |
| Token revocation | SHA-256 hashed refresh tokens in Redis |
| Timing attacks | Constant-time verify even for non-existent users |
| Enumeration | Generic error messages on login failure |
| Input | Null-byte rejection · lowercase normalization · 64KB metadata guard |
| Headers | X-Content-Type-Options, X-Frame-Options, HSTS (prod), Referrer-Policy |
| SAST | bandit `-ll` blocks HIGH severity findings in CI |
| CVE | pip-audit blocks known vulnerabilities in CI |

---

## 🚀 Quick Start

### 1. Prerequisites

- Docker + Docker Compose
- A Gemini API key ([get one free](https://aistudio.google.com/app/apikey))
- An RSA key pair for JWT signing

### 2. Generate RSA keys

```bash
# Generate RS256 key pair
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem

# Base64 encode for .env
base64 -w 0 private.pem
base64 -w 0 public.pem
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   JWT_PRIVATE_KEY_B64  ← base64 of private.pem
#   JWT_PUBLIC_KEY_B64   ← base64 of public.pem
#   GEMINI_API_KEY       ← your Gemini API key
```

### 4. Start all services

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| API (Swagger) | http://localhost:8000/docs |
| Asset Graph | http://localhost:8000/graph |
| Celery Monitor | http://localhost:5555 |
| Health check | http://localhost:8000/health |

### 5. Run migrations

```bash
docker compose exec app alembic upgrade head
```

### 6. Load sample data (optional)

Set `SEED_ON_STARTUP=true` in `.env` or run:

```bash
docker compose exec app python -c "
import asyncio
from app.assets.service import seed_sample_data
asyncio.run(seed_sample_data())
"
```

---

## 📡 API Reference

### Auth

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Register org + admin user | — |
| POST | `/api/v1/auth/login` | Login, get tokens | — |
| POST | `/api/v1/auth/refresh` | Rotate refresh token | — |
| GET | `/api/v1/auth/me` | Current user info | Bearer |

### Assets

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/api/v1/assets` | List with filters + pagination | readonly+ |
| POST | `/api/v1/assets` | Create / upsert asset | analyst+ |
| GET | `/api/v1/assets/{id}` | Get by ID | readonly+ |
| PATCH | `/api/v1/assets/{id}` | Update asset | analyst+ |
| DELETE | `/api/v1/assets/{id}` | Archive (soft delete) | admin |
| POST | `/api/v1/assets/bulk-import` | Import up to 1M records | analyst+ |
| POST | `/api/v1/assets/mark-stale` | Force stale marking | admin |

### Jobs

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/jobs/{job_id}` | Live import job progress |

### Relationships & Graph

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/assets/{id}/relationships` | Create relationship |
| GET | `/api/v1/assets/{id}/relationships` | List relationships |
| DELETE | `/api/v1/relationships/{id}` | Delete relationship |
| GET | `/api/v1/assets/{id}/graph` | BFS graph (depth 1-5) |
| GET | `/api/v1/graph/data` | Full org graph (D3 feed) |
| GET | `/api/v1/graph` | Interactive D3 visualization |

### AI

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/ai/query` | Natural language asset query |
| POST | `/api/v1/ai/summarize` | AI attack surface summary |

---

## 💡 Example Usage

### Register & Login

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "org": {"name": "Acme Corp", "slug": "acme"},
    "email": "admin@acme.com",
    "password": "SecurePass123!"
  }'

# Save the token
TOKEN="<access_token from response>"
```

### Bulk Import (1M records)

```bash
# Submit job
curl -X POST http://localhost:8000/api/v1/assets/bulk-import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"records": [
    {"type": "domain", "value": "techcorp.io", "source": "scan", "tags": ["root"]},
    {"type": "subdomain", "value": "api.techcorp.io", "source": "scan", "tags": ["prod", "api"]}
  ]}'

# Poll progress
curl http://localhost:8000/api/v1/jobs/<job_id> \
  -H "Authorization: Bearer $TOKEN"
```

### AI Natural Language Query

```bash
curl -X POST http://localhost:8000/api/v1/ai/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all expired certificates on production subdomains"}'
```

---

## 🏢 Multi-Tenancy

Control via `TENANT_ISOLATION` in `.env`:

| Mode | Description | Use case |
|---|---|---|
| `row` (default) | Shared DB, `org_id` FK isolation | Cost-efficient, standard SaaS |
| `database` | Separate PostgreSQL DB per org | Compliance, data sovereignty |

---

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v --asyncio-mode=auto

# With coverage
pytest tests/ --cov=app --cov-report=html
```

---

## 🌿 Branch Strategy

| Branch | Purpose | Protection |
|---|---|---|
| `main` | Production — stable releases | PRs only from `dev` · CI must pass |
| `dev` | Active development | PRs from feature branches |
| `feat/*` | New features | Merged into `dev` |
| `fix/*` | Bug fixes | Merged into `dev` |

---

## 📁 Project Structure

```
AssetManagementSystem/
├── app/
│   ├── main.py              # FastAPI factory + middleware
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # Async engine + TenantConnectionManager
│   ├── core/
│   │   ├── exceptions.py    # Typed HTTP exceptions
│   │   ├── logging.py       # structlog JSON
│   │   ├── pagination.py    # Generic PagedResponse[T]
│   │   └── security.py      # Input sanitization + metadata guards
│   ├── auth/                # JWT · bcrypt · RBAC
│   ├── assets/              # CRUD · upsert · bulk import
│   ├── jobs/                # Celery tasks (chunked async upsert)
│   ├── graph/               # BFS traversal · D3.js page
│   ├── lifecycle/           # APScheduler (mark-stale cron)
│   ├── ai/                  # Gemini chains · NL query · summarize
│   └── static/              # graph.html (D3.js visualization)
├── alembic/                 # Async migrations
├── tests/                   # pytest · httpx · mocked LLM
├── data/                    # sample_dataset.json (60 records)
├── .github/workflows/       # CI: lint → type-check → SAST → CVE → test
├── docker-compose.yml
├── Dockerfile
└── PROJECT_MAP.md           # Living architecture document
```

---

<div align="center">

Built with ❤️ by **Islam Abdelslam**  
DarkAtlas · Buguard Internship Engineering Task · 2026

</div>
