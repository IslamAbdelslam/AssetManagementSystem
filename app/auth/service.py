"""
Auth service: JWT RS256, bcrypt hashing, RBAC dependencies.
Security notes:
  - RS256 asymmetric signing (private key signs, public key verifies)
  - bcrypt rounds=12 (OWASP minimum for bcrypt)
  - Refresh tokens stored hashed in Redis (revocable)
  - Constant-time comparison to prevent timing attacks
  - Generic error messages to prevent user enumeration
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import redis.asyncio as aioredis
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Organization, User
from app.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.database import get_db

settings = get_settings()

# ── Crypto context ─────────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)

ALGORITHM = "RS256"


# ── Password helpers ───────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except ValueError:
        return False


# ── JWT helpers ────────────────────────────────────────────────────────────────
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, org_id: str, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    expire = _now_utc() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": _now_utc(),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_private_key, algorithm=ALGORITHM)
    return token, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


async def create_refresh_token(user_id: str, redis: aioredis.Redis) -> str:
    """Generates an opaque refresh token stored hashed in Redis."""
    raw = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.setex(f"refresh:{token_hash}", ttl, user_id)
    return raw


async def rotate_refresh_token(raw_token: str, redis: aioredis.Redis) -> tuple[str, str]:
    """Validates old refresh token, invalidates it, returns (user_id, new_raw_token)."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    user_id = await redis.get(f"refresh:{token_hash}")
    if not user_id:
        raise UnauthorizedError("Refresh token is invalid or expired.")
    await redis.delete(f"refresh:{token_hash}")
    new_raw = await create_refresh_token(user_id, redis)
    return user_id, new_raw


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_public_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type.")
        return payload
    except JWTError:
        raise UnauthorizedError("Token is invalid or expired.")


# ── FastAPI dependencies ───────────────────────────────────────────────────────
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not credentials:
        raise UnauthorizedError()
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User account not found or inactive.")
    return user


def require_role(*roles: str):
    """Dependency factory: raises 403 if user's role is not in allowed roles."""
    async def dependency(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in roles:
            raise ForbiddenError(
                f"This action requires one of: {', '.join(roles)}."
            )
        return current_user
    return dependency


# ── Org registration ───────────────────────────────────────────────────────────
async def register_org_and_admin(
    org_name: str,
    org_slug: str,
    email: str,
    plain_password: str,
    db: AsyncSession,
) -> tuple[Organization, User]:
    # Check slug uniqueness
    existing = await db.execute(select(Organization).where(Organization.slug == org_slug))
    if existing.scalar_one_or_none():
        from app.core.exceptions import ConflictError
        raise ConflictError(f"Organization slug '{org_slug}' is already taken.")

    org = Organization(name=org_name, slug=org_slug)
    db.add(org)
    await db.flush()  # get org.id

    hashed_pwd = await asyncio.to_thread(hash_password, plain_password)
    user = User(
        org_id=org.id,
        email=email,
        hashed_password=hashed_pwd,
        role="admin",
    )
    db.add(user)
    await db.flush()
    return org, user


async def authenticate_user(email: str, plain_password: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Constant-time: always verify even if user not found (prevents timing oracle)
    dummy_hash = "$2b$12$f.Ei7YdE4QYjKp9.gThXmuWUAs0vg.9qRGb8r/x1lrwSSp55V0VAu"
    password_ok = await asyncio.to_thread(verify_password, plain_password, user.hashed_password if user else dummy_hash)
    if not user or not password_ok or not user.is_active:
        raise UnauthorizedError("Invalid credentials.")
    return user
