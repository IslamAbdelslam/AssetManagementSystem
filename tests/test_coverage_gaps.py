import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import Request

from app.database import get_db
from app.main import create_app

@pytest.mark.asyncio
async def test_get_db_rollback_on_exception():
    """Verify that get_db rolls back the transaction on exception."""
    mock_session = AsyncMock()
    # We need an async context manager for the factory call
    class MockSessionCtx:
        async def __aenter__(self):
            return mock_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
            
    mock_factory = MagicMock(return_value=MockSessionCtx())
    
    with patch("app.database.get_session_factory", return_value=mock_factory):
        gen = get_db()
        await gen.__anext__()
        
        # Simulate an exception in the route
        with pytest.raises(ValueError, match="Test error"):
            await gen.athrow(ValueError("Test error"))
            
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_exception_handler():
    """Verify the global exception handler in main.py."""
    app = create_app()
    
    # Create a dummy request with a custom X-Request-ID
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"x-request-id", b"test-req-id-123")],
    }
    request = Request(scope)
    
    # Retrieve the registered Exception handler
    handler = app.exception_handlers.get(Exception)
    if handler is None:
        pytest.fail("Global exception handler not found")
        
    import typing
    # Call the handler directly
    response = await typing.cast(typing.Any, handler)(request, RuntimeError("Something exploded"))
    
    assert response.status_code == 500
    data = json.loads(bytes(response.body))
    assert data["error"] == "internal_error"
    assert data["message"] == "An unexpected error occurred."
    assert data["request_id"] == "test-req-id-123"
