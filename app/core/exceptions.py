"""Typed HTTP exceptions with consistent error response structure."""
from __future__ import annotations

from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"{resource} '{resource_id}' not found."},
        )


class ConflictError(HTTPException):
    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "conflict", "message": message},
        )


class UnauthorizedError(HTTPException):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": message},
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(HTTPException):
    def __init__(self, message: str = "Insufficient permissions.") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": message},
        )


class ValidationError(HTTPException):
    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "validation_error", "message": message},
        )


class ServiceUnavailableError(HTTPException):
    def __init__(self, service: str) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "service_unavailable", "message": f"{service} is currently unavailable."},
        )
