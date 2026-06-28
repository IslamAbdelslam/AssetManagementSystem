# UML Diagrams
## DarkAtlas — Asset Management System

---

## 1. Class Diagram — Core Domain Models

```mermaid
classDiagram
    class Organization {
        +UUID id
        +str name
        +str slug
        +datetime created_at
    }

    class User {
        +UUID id
        +UUID org_id
        +str email
        +str password_hash
        +str role
        +datetime created_at
    }

    class Asset {
        +UUID id
        +UUID org_id
        +str type
        +str value
        +str status
        +str source
        +list~str~ tags
        +dict metadata
        +datetime first_seen
        +datetime last_seen
    }

    class AssetRelationship {
        +UUID id
        +UUID org_id
        +UUID source_id
        +UUID target_id
        +str rel_type
        +datetime created_at
    }

    class ImportJob {
        +UUID id
        +UUID org_id
        +str status
        +int total
        +int imported
        +int error_count
        +list errors
        +datetime created_at
        +datetime updated_at
    }

    Organization "1" --> "many" User : has
    Organization "1" --> "many" Asset : owns
    Organization "1" --> "many" ImportJob : has
    Asset "1" --> "many" AssetRelationship : source
    Asset "1" --> "many" AssetRelationship : target
```

---

## 2. Sequence Diagram — Bulk Import

```mermaid
sequenceDiagram
    actor Client
    participant API as FastAPI App
    participant DB as PostgreSQL
    participant Redis
    participant Worker as Celery Worker

    Client->>API: POST /assets/bulk-import {records}
    API->>API: Validate schema (Pydantic)
    API->>DB: INSERT ImportJob (status=queued)
    API->>Redis: celery.delay(job_id, records)
    API-->>Client: 202 { job_id, status: "queued" }

    Redis->>Worker: Deliver task
    Worker->>DB: UPDATE ImportJob (status=running)
    
    loop Every 5,000 records
        Worker->>DB: executemany upsert (ON CONFLICT)
        Worker->>Redis: HSET job:{id} imported=N
    end

    Worker->>DB: UPDATE ImportJob (status=done)

    Client->>API: GET /jobs/{job_id}
    API->>Redis: HGET job:{id}
    API-->>Client: { status, imported, total, progress_pct }
```

---

## 3. Sequence Diagram — Authentication

```mermaid
sequenceDiagram
    actor Client
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Redis

    Client->>API: POST /auth/register {org, email, password}
    API->>DB: INSERT Organization
    API->>DB: INSERT User (bcrypt hash, rounds=12)
    API-->>Client: 201 { user_id, org_id }

    Client->>API: POST /auth/login {email, password}
    API->>DB: SELECT User WHERE email=...
    API->>API: bcrypt.verify(password, hash)
    API->>API: RS256 sign access_token (15m TTL)
    API->>API: random 32-byte refresh_token
    API->>Redis: SET sha256(refresh_token) → user_id  TTL=7d
    API-->>Client: { access_token, refresh_token }

    Client->>API: POST /auth/refresh {refresh_token}
    API->>Redis: GET sha256(refresh_token) → user_id
    API->>Redis: DEL sha256(old_refresh_token)
    API->>API: Generate new pair
    API->>Redis: SET sha256(new_refresh_token) TTL=7d
    API-->>Client: { access_token, refresh_token }
```

---

## 4. Sequence Diagram — AI Natural Language Query

```mermaid
sequenceDiagram
    actor Client
    participant API as FastAPI
    participant LLM as Gemini 2.0 Flash
    participant Guard as Pydantic Guard
    participant DB as PostgreSQL

    Client->>API: POST /ai/query { "query": "stale certs on prod" }
    API->>API: Verify JWT, check org_id
    
    API->>LLM: Prompt: generate JSON filter for user query
    Note over LLM: temperature=0 (deterministic)
    LLM-->>API: { "type": "certificate", "status": "stale" }
    
    API->>Guard: Validate filter schema
    alt Filter invalid
        Guard-->>API: ValidationError
        API-->>Client: 422 { "detail": "Could not parse AI response" }
    else Filter valid
        Guard-->>API: Validated filter object
        API->>DB: SELECT assets WHERE org_id=... AND type=... AND status=...
        DB-->>API: Real asset records
        API-->>Client: 200 { assets: [...] }
    end
```

---

## 5. State Diagram — Asset Lifecycle

```mermaid
stateDiagram-v2
    [*] --> active : First import / scan

    active --> stale : last_seen older than threshold\n(APScheduler cron)
    stale --> active : Re-imported with status=active\n(ON CONFLICT DO UPDATE)
    active --> archived : DELETE /assets/{id}\n(soft delete)
    stale --> archived : DELETE /assets/{id}\n(soft delete)
    archived --> [*] : (terminal state)

    note right of active
        Dedup key: (org_id, type, value)
        Tags merged on re-import
        Metadata merged (incoming wins)
    end note
```

---

## 6. State Diagram — Import Job

```mermaid
stateDiagram-v2
    [*] --> queued : POST /assets/bulk-import

    queued --> running : Celery worker picks up task
    running --> done : All chunks processed successfully
    running --> failed : Unrecoverable error in worker

    done --> [*]
    failed --> [*]

    note right of running
        Progress written to Redis
        every 5,000 records
        GET /jobs/{id} reads live progress
    end note
```

---

## 7. Deployment Diagram

```mermaid
graph TB
    subgraph "Docker Compose Network"
        subgraph "App Container :8000"
            FA[FastAPI + Uvicorn]
            APS[APScheduler]
        end

        subgraph "Celery Container"
            CW[Celery Worker\nconcurrency=20]
        end

        subgraph "Flower Container :5555"
            FL[Flower Monitor]
        end

        subgraph "PostgreSQL Container :5432"
            PG[(postgres 16\ndarkatlas_db)]
        end

        subgraph "Redis Container :6379"
            RD[(Redis 8\nDB0: cache\nDB1: broker\nDB2: results)]
        end
    end

    FA -->|asyncpg| PG
    FA -->|redis-py| RD
    FA -->|publish task| RD
    CW -->|consume task| RD
    CW -->|asyncpg upsert| PG
    CW -->|progress hset| RD
    FL -->|inspect| RD
    APS -->|UPDATE stale| PG

    Client([Client]) -->|HTTP :8000| FA
    DevOps([DevOps]) -->|HTTP :5555| FL
```

---

## 8. Component Diagram — Security

```mermaid
graph LR
    subgraph "Request Pipeline"
        Req[HTTP Request] --> RID[Request-ID\nMiddleware]
        RID --> SH[Security Headers\nMiddleware]
        SH --> CORS[CORS\nMiddleware]
        CORS --> RL[Rate Limiter\nslowapi]
        RL --> Auth[JWT Auth\nDependency]
        Auth --> RBAC[RBAC\nDependency]
        RBAC --> Handler[Route\nHandler]
    end

    subgraph "Auth Components"
        Auth --> JWTDec[RS256 Decoder\npublic key only]
        JWTDec --> Claims[Claims:\nuser_id, org_id, role]
    end

    subgraph "Input Sanitization"
        Handler --> San[sanitize_string\nnull-byte strip\nlowercase norm]
        San --> Val[validate_metadata\n64KB guard]
        Val --> Allow[Allowlist check\ntype / status / source]
    end
```
