import httpx
import pytest

from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_root_describes_service() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "FinAssist AI"
    assert response.json()["docs"] == "/docs"


@pytest.mark.anyio
async def test_liveness_does_not_require_external_services() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.anyio
@pytest.mark.parametrize("available", [True, False])
async def test_readiness_includes_ollama(monkeypatch, available):
    from app.routers import health

    async def up():
        return health.DependencyHealth(status="up")

    async def ollama():
        return health.DependencyHealth(
            status="up" if available else "down",
            detail=None if available else "Start Ollama",
        )

    monkeypatch.setattr(health, "check_postgres", up)
    monkeypatch.setattr(health, "check_chroma", up)
    monkeypatch.setattr(health, "check_ollama", ollama)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health/ready")
    assert response.status_code == (200 if available else 503)
    assert response.json()["services"]["ollama"]["status"] == (
        "up" if available else "down"
    )
