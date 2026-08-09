"""Test: PersistenceEngine — interface + MemoryPersistenceEngine."""

import pytest
from intent_kernel.persistence import MemoryPersistenceEngine


@pytest.fixture
def engine():
    return MemoryPersistenceEngine()


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_and_read(engine):
    await engine.write("k1", {"id": "k1", "value": "hello"})
    result = await engine.read("k1")
    assert result == {"id": "k1", "value": "hello"}


@pytest.mark.asyncio
async def test_read_nonexistent(engine):
    result = await engine.read("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_delete(engine):
    await engine.write("k1", {"id": "k1"})
    deleted = await engine.delete("k1")
    assert deleted is True
    assert await engine.read("k1") is None


@pytest.mark.asyncio
async def test_delete_nonexistent(engine):
    deleted = await engine.delete("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_exists(engine):
    await engine.write("k1", {"id": "k1"})
    assert await engine.exists("k1") is True
    assert await engine.exists("k2") is False


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_all(engine):
    await engine.write("a1", {"id": "a1", "type": "fact"})
    await engine.write("a2", {"id": "a2", "type": "decision"})
    results = await engine.query()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_query_prefix(engine):
    await engine.write("ke-001", {"id": "ke-001"})
    await engine.write("ke-002", {"id": "ke-002"})
    await engine.write("snap-001", {"id": "snap-001"})
    results = await engine.query(prefix="ke-")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_query_filters(engine):
    await engine.write("k1", {"id": "k1", "domain": "finance"})
    await engine.write("k2", {"id": "k2", "domain": "education"})
    results = await engine.query(filters={"domain": "finance"})
    assert len(results) == 1
    assert results[0]["domain"] == "finance"


@pytest.mark.asyncio
async def test_query_limit(engine):
    for i in range(5):
        await engine.write(f"k{i}", {"id": f"k{i}"})
    results = await engine.query(limit=3)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_all(engine):
    await engine.write("k1", {"id": "k1"})
    await engine.write("k2", {"id": "k2"})
    assert await engine.count() == 2


@pytest.mark.asyncio
async def test_count_prefix(engine):
    await engine.write("ke-001", {"id": "ke-001"})
    await engine.write("ke-002", {"id": "ke-002"})
    await engine.write("snap-001", {"id": "snap-001"})
    assert await engine.count(prefix="ke-") == 2


# ---------------------------------------------------------------------------
# Export/Import
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_json(engine):
    await engine.write("k1", {"id": "k1", "value": "hello"})
    data = await engine.export_all(format="json")
    import json
    parsed = json.loads(data)
    assert "k1" in parsed


@pytest.mark.asyncio
async def test_export_jsonl(engine):
    await engine.write("k1", {"id": "k1"})
    await engine.write("k2", {"id": "k2"})
    data = await engine.export_all(format="jsonl")
    lines = data.decode().strip().split("\n")
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_import_json(engine):
    import json
    data = json.dumps({"k1": {"id": "k1", "value": "hello"}}).encode()
    count = await engine.import_data(data, format="json")
    assert count == 1
    assert await engine.read("k1") == {"id": "k1", "value": "hello"}


@pytest.mark.asyncio
async def test_import_jsonl(engine):
    import json
    lines = [json.dumps({"id": "k1"}), json.dumps({"id": "k2"})]
    data = "\n".join(lines).encode()
    count = await engine.import_data(data, format="jsonl")
    assert count == 2


# ---------------------------------------------------------------------------
# Clear (Soberania — real delete)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear(engine):
    await engine.write("k1", {"id": "k1"})
    await engine.write("k2", {"id": "k2"})
    await engine.clear()
    assert await engine.count() == 0


# ---------------------------------------------------------------------------
# Health check (Monitor)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(engine):
    await engine.write("k1", {"id": "k1"})
    health = await engine.health_check()
    assert health["healthy"] is True
    assert health["backend"] == "memory"
    assert health["records"] == 1


# ---------------------------------------------------------------------------
# Backend type
# ---------------------------------------------------------------------------

def test_backend_type(engine):
    assert engine.backend_type == "memory"


# ---------------------------------------------------------------------------
# Overwrite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overwrite(engine):
    await engine.write("k1", {"id": "k1", "value": "v1"})
    await engine.write("k1", {"id": "k1", "value": "v2"})
    result = await engine.read("k1")
    assert result["value"] == "v2"
