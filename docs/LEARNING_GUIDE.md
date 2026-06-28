# 📖 Learning Guide — Understanding the Asset Management System

> **Who is this for?** If you have about 3 months of Python experience and want to understand *why* this project is built the way it is — not just *what* it does — this guide is for you. We'll walk through every major decision, one concept at a time.

---

## 🗺️ How to Use This Guide

Don't try to read this all at once. Here's a suggested path:

1. **Start here** → Read Sections 1–3 to understand the big picture
2. **Pick a feature** → Follow the request flow for that feature (Section 4)
3. **Go deeper** → Read the referenced design docs for full detail

---

## 1. What Is This Project? (The "Why")

Imagine a cybersecurity team that needs to track every digital asset of a company:
- All their domain names (`acme.io`, `api.acme.io`)
- Their servers and IPs (`93.184.216.34`)
- SSL certificates, services, technologies in use

This project is the system that stores, organizes, and queries all of that. It needs to:
- Handle **multiple companies** (called "tenants") in one system
- Import **millions of records** without slowing down
- Let users ask questions in **plain English** ("show me stale certificates")
- Be **secure** — no company should ever see another company's data

---

## 2. The Folder Structure — What Goes Where and Why

```
AssetManagementSystem/
├── app/                 ← ALL the Python application code lives here
├── alembic/             ← Database migration scripts (version control for your DB schema)
├── tests/               ← Automated tests
├── data/                ← Sample data files for testing
├── docs/                ← All documentation (you are here!)
│   ├── PROJECT_MAP.md
│   ├── benchmarking/    ← Performance test scripts and results
│   └── design/          ← Architecture and design documents
├── .github/workflows/   ← CI/CD automation (runs tests on GitHub automatically)
├── docker-compose.yml   ← Defines all the services (database, cache, app, etc.)
├── Dockerfile           ← Instructions to build the app into a container
├── mypy.ini             ← Config for mypy (the type checker tool)
├── pytest.ini           ← Config for pytest (the testing tool)
├── entrypoint.sh        ← The script that runs when Docker starts the app
└── requirements*.txt    ← Python package dependencies
```

### Why is the app code inside `app/`?

This is a Python convention. By putting all your code inside a folder called `app/`, Python treats it as a **package** (a collection of modules). This lets you import things cleanly:

```python
from app.auth.service import verify_token     # ✅ clean, clear
import service                                 # ❌ confusing, which service?
```

---

## 3. Inside `app/` — The Layered Architecture

This is the most important concept in the whole project. Every feature follows the same 4-layer pattern:

```
Router Layer    →   Service Layer    →    Repository Layer    →    Database
(HTTP in/out)       (business logic)      (database queries)        (PostgreSQL)
```

### Why layers? Why not just put everything in one file?

**Without layers** (spaghetti code):
```python
@app.post("/assets")
async def create_asset(data, db, token):
    user = db.execute("SELECT * FROM users WHERE token=?", token)  # auth logic
    if user.role != "admin":                                        # RBAC logic
        raise HTTPException(403)
    existing = db.execute("SELECT * FROM assets WHERE value=?", data.value)  # DB query
    if existing:
        db.execute("UPDATE assets SET tags=...", ...)               # business logic
    else:
        db.execute("INSERT INTO assets ...", ...)                   # DB query
    # ... 200 more lines
```

**With layers** (what this project does):
```python
# router.py — only HTTP concerns
@router.post("/assets")
async def create_asset(data: AssetCreate, user=Depends(require_analyst), db=Depends(get_db)):
    return await asset_service.upsert(db, user.org_id, data)

# service.py — only business logic
async def upsert(db, org_id, data):
    repo = AssetRepository(db, org_id)
    asset, created = await repo.upsert(data.model_dump())
    return asset

# repository.py — only database queries
async def upsert(self, data):
    stmt = pg_insert(Asset).values(org_id=self.org_id, **data).on_conflict_do_update(...)
    result = await self.db.execute(stmt)
    return result.scalar_one()
```

Each layer only knows about the layer below it. This makes code:
- **Testable** — you can test the service without a real database
- **Readable** — each file has one clear job
- **Changeable** — you can swap PostgreSQL for another DB by only changing `repository.py`

---

## 4. Deep Dives — Following a Request

### 4.1 "How does a user log in?"

**File path:** `app/auth/router.py` → `app/auth/service.py`

When a user sends `POST /api/v1/auth/login`:

**Step 1 — Router receives the request** (`app/auth/router.py`)
```python
@router.post("/login")
async def login(data: LoginRequest, db=Depends(get_db)):
    return await auth_service.login(db, data.email, data.password)
```
The router's only job is to receive the HTTP request and pass it to the service.

**Step 2 — Service verifies the password** (`app/auth/service.py`)
```python
async def login(db, email, password):
    user = await get_user_by_email(db, email)
    bcrypt.verify(password, user.password_hash)  # constant-time comparison
    access_token = create_jwt(user)
    refresh_token = generate_refresh_token()
    await redis.set(sha256(refresh_token), user.id, ttl=7*24*3600)
    return {"access_token": access_token, "refresh_token": refresh_token}
```

**Why bcrypt?** Regular hashing (MD5, SHA-256) is designed to be *fast*. bcrypt is designed to be *slow* — making it hard for attackers to guess passwords by brute force.

**Why two tokens?** The `access_token` is short-lived (15 minutes). If stolen, damage is limited. The `refresh_token` is long-lived (7 days) but stored securely in Redis and can be revoked instantly.

**Why store the refresh token hash in Redis, not the token itself?** If an attacker gains access to the Redis database, they can't use the hashes directly — they need the original token. This is the same reason passwords are stored as hashes.

---

### 4.2 "How does asset creation work?"

**File path:** `app/assets/router.py` → `app/assets/service.py` → `app/assets/repository.py`

**Why "upsert" instead of just "insert"?**

If a scanner finds `api.acme.io` today and again tomorrow, we don't want two records. We want *one* record that gets updated. This is called an "upsert" (update + insert):

```sql
INSERT INTO assets (org_id, type, value, ...)
VALUES (...)
ON CONFLICT (org_id, type, value)    -- if this combination already exists...
DO UPDATE SET                         -- ...update instead of failing
    last_seen = NOW(),
    tags = ARRAY(SELECT DISTINCT unnest(assets.tags || excluded.tags))
```

The unique key is `(org_id, type, value)` — meaning "for this company, this type of asset with this value". This is enforced at the *database level*, not just in Python code, so it can never be bypassed.

**Why merge tags instead of replacing them?**

If Monday's scan found `["prod"]` and Tuesday's scan found `["api"]`, the merge gives `["prod", "api"]`. If we replaced, we'd lose historical tags. The union approach never loses data.

---

### 4.3 "How does bulk import work?"

**File path:** `app/assets/router.py` → `app/jobs/tasks.py` (via Celery)

When you import 100,000 records, you can't do it in the HTTP request — that would time out. Instead:

```
Client sends → API creates a job → Returns job_id immediately → Worker processes in background
```

**Why Celery?** Celery is a task queue. Think of it like a to-do list that workers pick tasks from. The API writes to the list, the worker reads from it. Redis acts as the shared "list" between them.

**Why chunk into 5,000 records?**
- 1 record at a time = 1M database calls (too slow)
- 1M records at once = one massive transaction that could fail completely
- 5,000 per chunk = good balance: fast enough, and if one chunk fails, only 5,000 records need to be retried

**How do you check progress?** After each chunk, the worker writes to Redis:
```python
redis.hset(f"job:{job_id}", "imported", 5000)  # update count
```
The client polls `GET /jobs/{job_id}` which reads from Redis — so you get live updates.

---

### 4.4 "How does the AI query work?"

**File path:** `app/ai/router.py` → `app/ai/chains.py`

This is the trickiest part. The key question is: **how do you prevent the AI from making up assets that don't exist?**

The answer: **the LLM never returns assets. It only returns a filter.**

```
User query: "show me stale certificates"
       ↓
Gemini (AI) outputs: { "type": "certificate", "status": "stale" }
       ↓
Pydantic validates: is "certificate" a valid type? is "stale" a valid status?
       ↓
Repository runs: SELECT * FROM assets WHERE type='certificate' AND status='stale'
       ↓
Real database records returned to user
```

The AI acts as a "query translator" — it turns English into a structured filter. The actual data always comes from your database.

**Why temperature=0?** The AI's "temperature" controls how creative/random its output is. Temperature=0 means completely deterministic — the same question always gets the same filter. You don't want the AI to be "creative" when querying your security data.

---

## 5. The Database — Why PostgreSQL and Why These Indexes

### 5.1 Why PostgreSQL over simpler options?

| Feature needed | PostgreSQL solution |
|---|---|
| Store tags as a list | Native `ARRAY` type |
| Store flexible metadata | Native `JSONB` type |
| Fast array/JSON search | `GIN` index |
| "Insert or update" in one query | `ON CONFLICT DO UPDATE` |
| No duplicate assets | `UNIQUE` constraint |
| Multi-tenant safety | Row-level filtering by `org_id` |

SQLite (the simple option) doesn't support most of these.

### 5.2 What is a GIN index and why do we need it?

A regular B-tree index works for exact lookups (`WHERE type = 'domain'`). A GIN (Generalized Inverted Index) index works for *containment* — "does this array contain this value?":

```sql
-- Without GIN index: scans every row (slow for 1M records)
SELECT * FROM assets WHERE tags @> ARRAY['prod'];

-- With GIN index: jumps directly to matching rows (fast!)
CREATE INDEX ix_asset_tags_gin ON assets USING gin(tags);
```

### 5.3 What are migrations? (Alembic)

Imagine your database is live and has 1 million records. You need to add a new column. You can't just drop the database and recreate it. Migrations are the solution — they're versioned scripts that change the database schema incrementally:

```
Version 0001: Create tables (organizations, users, assets)
Version 0002: Add updated_at column to assets
Version 0003: (your next change)
```

Alembic manages these scripts. `alembic upgrade head` runs all pending migrations in order.

---

## 6. Security — Why Each Decision Matters

### 6.1 JWT (JSON Web Tokens)

After login, every request includes a token in the header:
```
Authorization: Bearer eyJhbGciOiJSUzI1NiJ9...
```

The server can *verify* this token without a database lookup — it just checks the cryptographic signature. This makes the API stateless and scalable.

**RS256 vs HS256:** HS256 uses one shared secret key (everyone who verifies must have the secret). RS256 uses a *key pair*: the private key signs, the public key verifies. Verifying services never need the private key — much safer.

### 6.2 RBAC (Role-Based Access Control)

Three roles, least-privilege principle:

| Role | Can do |
|---|---|
| `readonly` | Only read assets |
| `analyst` | Read + write assets, run bulk imports |
| `admin` | Everything including delete and force-stale |

In the code, these are FastAPI **dependencies**:
```python
@router.delete("/{id}")
async def delete(id, user=Depends(require_admin)):  # ← enforced at router level
    ...
```

If `require_admin` fails, FastAPI returns 403 automatically — the handler never runs.

### 6.3 Why sanitize inputs?

A "null byte" (`\x00`) is an invisible character that can confuse some systems. For example, `"domain\x00.evil.com"` might be stored as `"domain"` in C-based systems but treated as the full string in Python — causing inconsistencies that attackers can exploit.

```python
def sanitize_string(value: str) -> str:
    return value.replace('\x00', '').lower().strip()
```

---

## 7. Testing — Why and How

### 7.1 Why write tests?

Every time you change code, you risk breaking something else. Tests are a safety net that catches these breaks automatically. In this project:

- Tests run automatically on every `git push` (CI/CD)
- If tests fail, the merge to `main` is blocked

### 7.2 What is `conftest.py`?

`conftest.py` is pytest's special setup file. It defines **fixtures** — reusable pieces of test setup. For example, `client` gives every test an HTTP client connected to the test database:

```python
@pytest_asyncio.fixture
async def client(setup_db):
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
```

### 7.3 Why a separate test database?

You never want tests to run against your real database — tests insert and delete data. The test database is created fresh for each test run and thrown away after.

### 7.4 What is mocking?

The AI tests don't actually call Gemini (that would cost money and require internet). Instead, we "mock" the API — replace it with a fake that returns a preset response:

```python
with patch("app.ai.chains.ChatGoogleGenerativeAI") as mock_llm:
    mock_llm.return_value.invoke.return_value = '{"type": "domain"}'
    response = await client.post("/ai/query", json={"query": "show domains"})
```

---

## 8. Docker — Why Containers?

### 8.1 The "works on my machine" problem

Without Docker: "It works on my laptop but fails on the server" — because the server has a different Python version, different OS libraries, etc.

With Docker: The exact same container image runs everywhere. No surprises.

### 8.2 What is `docker-compose.yml`?

It defines all 5 services that need to run together:

| Service | What it does |
|---|---|
| `postgres` | The database |
| `redis` | Cache, message broker, session store |
| `app` | The FastAPI application |
| `celery_worker` | Processes background jobs |
| `flower` | Dashboard to monitor Celery jobs |

Each service runs in its own container but they can talk to each other by service name (`redis://redis:6379`, `postgresql://postgres:5432`).

### 8.3 Why multi-stage Dockerfile?

```dockerfile
# Stage 1: Build (has all build tools)
FROM python:3.12 AS builder
RUN pip install -r requirements.txt

# Stage 2: Production (small, only runtime)
FROM python:3.12-slim AS production
COPY --from=builder /app /app
```

Stage 1 has compilers and build tools (large). Stage 2 only copies the final result — no build tools needed at runtime. This makes the production image much smaller (faster to download, smaller attack surface).

---

## 9. CI/CD — Automated Quality Checks

Every time you push code to GitHub, this pipeline runs automatically:

```
1. ruff check     → Is the code formatted correctly? Any obvious bugs?
2. mypy           → Are the types correct? (Python type hints validation)
3. bandit         → Any known security vulnerabilities in the code?
4. pip-audit      → Any known CVEs (vulnerabilities) in our dependencies?
5. pytest         → Do all the tests pass?
```

If any step fails → the push is flagged, and merging to `main` is blocked.

**Why this order?** Cheap checks (linting takes 1s) run first. Expensive checks (tests take minutes) run last. If linting fails, we don't waste time running tests.

---

## 10. What to Study Next

If you want to go deeper on specific topics:

| Topic | Where to learn |
|---|---|
| FastAPI basics | [fastapi.tiangolo.com](https://fastapi.tiangolo.com) |
| SQLAlchemy async | [docs.sqlalchemy.org/asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) |
| How JWT works | [jwt.io/introduction](https://jwt.io/introduction/) |
| Docker for beginners | [docs.docker.com/get-started](https://docs.docker.com/get-started/) |
| PostgreSQL indexing | [Postgres docs: indexes](https://www.postgresql.org/docs/current/indexes.html) |
| Celery task queue | [docs.celeryq.dev](https://docs.celeryq.dev/en/stable/getting-started/introduction.html) |
| LangChain + Gemini | [python.langchain.com](https://python.langchain.com/docs/integrations/llms/google_ai/) |

### Design Documents in This Project

| Document | Good for learning |
|---|---|
| [System Design](design/system_design.md) | Overall architecture, data flow diagrams |
| [Software Design Doc](design/software_design_doc.md) | Module-by-module decisions, security design |
| [UML Diagrams](design/uml_diagrams/diagrams.md) | Visual sequence/class/state diagrams |
| [Project Map](PROJECT_MAP.md) | Quick-reference tech stack and flows |
| [Benchmark Report](benchmarking/benchmark_report.md) | Performance results and methodology |

---

> 💡 **Tip:** The best way to learn is to run the project locally, then change one small thing and see what breaks. Read the error. Fix it. That's how real-world development works.

Built with ❤️ by **Islam Abdelslam** — DarkAtlas · 2026
