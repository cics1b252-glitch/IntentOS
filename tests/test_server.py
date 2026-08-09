"""Test: FastAPI server endpoints."""

import pytest
try:
    from httpx import AsyncClient, ASGITransport
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    AsyncClient = None
    ASGITransport = None
try:
    from intent_kernel.server.app import app, get_kernel
    HAS_SERVER = True
except ImportError:
    HAS_SERVER = False
    app = None
    get_kernel = None
from intent_kernel.kernel import Kernel
import tempfile


@pytest.fixture(autouse=True)
def override_kernel():
    """Override kernel with temp directory for tests."""
    if not HAS_SERVER:
        yield
        return
    import intent_kernel.server.app as server_module
    with tempfile.TemporaryDirectory() as tmpdir:
        server_module._kernel = Kernel(pkb_path=f"{tmpdir}/pkb")
        yield
        server_module._kernel = None


@pytest.mark.asyncio
async def test_status_endpoint():
    """GET /api/v1/status returns kernel info."""
    if not HAS_HTTPX or not HAS_SERVER:
        return
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.1.0"
    assert "mock" in data["providers"]
    assert "core" in data["modules"]


@pytest.mark.asyncio
async def test_process_endpoint():
    """POST /api/v1/process processes an intent."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/process", json={
            "text": "Quero investir 5000 por mês",
            "mode": "auto",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"]
    assert data["mode"] in ("quick", "basic", "detail", "expert", "architect")
    assert data["domain"]
    assert 0.0 <= data["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_process_finance():
    """POST /api/v1/process handles finance intent."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/process", json={
            "text": "Como investir em ETFs conservador?",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "finance"


@pytest.mark.asyncio
async def test_query_endpoint():
    """GET /api/v1/query queries the PKB."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/query", params={"q": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_list_events():
    """GET /api/v1/pkb/events lists events."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/pkb/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_delete_nonexistent_event():
    """DELETE /api/v1/pkb/events/{id} returns 404 for missing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/pkb/events/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_pkb():
    """DELETE /api/v1/pkb clears all events."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/pkb")
    assert resp.status_code == 200
    assert resp.json()["cleared"] is True
