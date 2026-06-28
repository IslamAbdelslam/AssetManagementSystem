import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_healthcheck(client: AsyncClient):
    """Test the healthcheck endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data
    assert "redis" in data
