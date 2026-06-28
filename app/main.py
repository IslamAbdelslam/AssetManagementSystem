"""
FastAPI application factory.
Handles: lifespan, middleware (security headers, request-id, CORS), routers.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database import close_redis, get_engine, get_redis, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from redis import asyncio as aioredis
from app.lifecycle.scheduler import start_scheduler, stop_scheduler

log = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    # ── Startup ────────────────────────────────────────────────────────────
    configure_logging(debug=settings.APP_DEBUG)
    log.info("darkatlas.startup", env=settings.APP_ENV, tenant_mode=settings.TENANT_ISOLATION)

    # Verify DB connectivity
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        log.info("darkatlas.db.connected")
    except Exception as exc:
        log.error("darkatlas.db.connection_failed", error=str(exc))
        raise

    # Verify Redis connectivity
    redis = get_redis()
    try:
        await redis.ping()
        log.info("darkatlas.redis.connected")
    except Exception as exc:
        log.error("darkatlas.redis.connection_failed", error=str(exc))
        raise

    # Start lifecycle scheduler
    start_scheduler()
    log.info("darkatlas.scheduler.started")

    # Optional: seed sample data
    if settings.SEED_ON_STARTUP:
        from app.assets.service import seed_sample_data
        await seed_sample_data()

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    stop_scheduler()
    await close_redis()
    await get_engine().dispose()
    log.info("darkatlas.shutdown")


def create_app() -> FastAPI:
    docs_url = "/docs" if settings.DOCS_ENABLED else None
    redoc_url = "/redoc" if settings.DOCS_ENABLED else None

    application = FastAPI(
        title="DarkAtlas Asset Management System",
        description=(
            "ASM module for tracking internet-facing assets: domains, subdomains, "
            "IPs, services, certificates, and technologies."
        ),
        version="1.0.0",
        contact={
            "name": "Buguard Support",
            "url": "https://buguard.io",
            "email": "support@buguard.io",
        },
        license_info={
            "name": "Proprietary",
            "url": "https://buguard.io/terms",
        },
        openapi_tags=[
            {"name": "Auth", "description": "Authentication and organization management"},
            {"name": "Assets", "description": "Asset CRUD, filtering, and bulk operations"},
            {"name": "Graph", "description": "Asset relationship graphing and visualization"},
            {"name": "AI", "description": "Natural language query interface"},
            {"name": "System", "description": "System health and status"},
        ],
        docs_url=docs_url,
        redoc_url=redoc_url,
        lifespan=lifespan,
    )

    # ── CORS ───────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # ── Security Headers Middleware ─────────────────────────────────────────
    @application.middleware("http")
    async def security_headers(request: Request, call_next: object):  # type: ignore[type-arg]
        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    # ── Request ID + Structured Logging Middleware ─────────────────────────
    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next: object):  # type: ignore[type-arg]
        import time
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        response: Response = await call_next(request)  # type: ignore[operator]
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Global Exception Handler ───────────────────────────────────────────
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID", "unknown")
        log.error("darkatlas.unhandled_exception", error=type(exc).__name__, request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )

    # ── Health Endpoint ────────────────────────────────────────────────────
    @application.get("/health", tags=["System"], summary="Health check", response_description="System status including DB and Redis connectivity.")
    async def health(
        db: AsyncSession = Depends(get_db),
        redis: aioredis.Redis = Depends(get_redis)
    ) -> dict:
        status = {"status": "ok", "env": settings.APP_ENV, "db": "unknown", "redis": "unknown"}
        try:
            await db.execute(__import__("sqlalchemy").text("SELECT 1"))
            status["db"] = "ok"
        except Exception:
            status["db"] = "error"
            status["status"] = "degraded"
        
        try:
            await redis.ping()
            status["redis"] = "ok"
        except Exception:
            status["redis"] = "error"
            status["status"] = "degraded"
            
        return status

    # ── Static Files (D3 Graph) ────────────────────────────────────────────
    application.mount("/static", StaticFiles(directory="app/static"), name="static")

    # ── Routers ────────────────────────────────────────────────────────────
    from app.auth.router import router as auth_router
    from app.assets.router import router as assets_router
    from app.graph.router import router as graph_router
    from app.ai.router import router as ai_router
    
    # ── Rate Limiting Setup ────────────────────────────────────────────────
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    from app.core.rate_limit import limiter

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(SlowAPIMiddleware)

    application.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    application.include_router(assets_router, prefix="/api/v1", tags=["Assets"])
    application.include_router(graph_router, prefix="/api/v1", tags=["Graph"])
    application.include_router(ai_router, prefix="/api/v1/ai", tags=["AI"])

    return application


app = create_app()
