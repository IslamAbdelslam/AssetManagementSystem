"""Auth router: /auth/register, /auth/login, /auth/refresh, /auth/me"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.auth import schemas, service
from app.auth.models import User
from app.database import get_db, get_redis

router = APIRouter()


@router.post(
    "/register",
    response_model=schemas.TokenResponse,
    status_code=201,
    summary="Register new organization and admin user",
)
async def register(
    body: schemas.RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> schemas.TokenResponse:
    org, user = await service.register_org_and_admin(
        org_name=body.org.name,
        org_slug=body.org.slug,
        email=body.email,
        plain_password=body.password,
        db=db,
    )
    access_token, expires_in = service.create_access_token(
        str(user.id), str(org.id), user.role
    )
    refresh_token = await service.create_refresh_token(str(user.id), redis)
    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/login", response_model=schemas.TokenResponse, summary="Login")
async def login(
    body: schemas.LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> schemas.TokenResponse:
    user = await service.authenticate_user(body.email, body.password, db)
    access_token, expires_in = service.create_access_token(
        str(user.id), str(user.org_id), user.role
    )
    refresh_token = await service.create_refresh_token(str(user.id), redis)
    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=schemas.TokenResponse, summary="Refresh access token")
async def refresh(
    body: schemas.RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> schemas.TokenResponse:
    from sqlalchemy import select
    import uuid

    user_id, new_refresh = await service.rotate_refresh_token(body.refresh_token, redis)
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        from app.core.exceptions import UnauthorizedError
        raise UnauthorizedError("User not found.")

    access_token, expires_in = service.create_access_token(
        str(user.id), str(user.org_id), user.role
    )
    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=expires_in,
    )


@router.get("/me", response_model=schemas.UserResponse, summary="Current user info")
async def me(
    current_user: Annotated[User, Depends(service.get_current_user)],
) -> schemas.UserResponse:
    return schemas.UserResponse.model_validate(current_user)
