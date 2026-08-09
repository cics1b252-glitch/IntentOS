"""Test: PersistenceKnowledgeStore — backend-agnostic KnowledgeStore."""

import pytest
from intent_kernel.persistence import MemoryPersistenceEngine
from intent_kernel.pkb.persistence_store import PersistenceKnowledgeStore
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import Domain, EventLifecycle, EventType, QueryFilters


@pytest.fixture
def store():
    engine = MemoryPersistenceEngine()
    return PersistenceKnowledgeStore(engine)


def _make_event(**kwargs) -> KnowledgeEvent:
    defaults = {
        "type": EventType.DECISION,
        "domain": Domain.FINANCE,
        "title": "Test Decision",
        "content": {"question": "test", "chosen": "option A"},
        "summary": "Test summary",
        "confidence": 0.8,
    }
    defaults.update(kwargs)
    return KnowledgeEvent(**defaults)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_and_get(store):
    event = _make_event()
    await store.append(event)
    retrieved = await store.get(event.id)
    assert retrieved is not None
    assert retrieved.id == event.id
    assert retrieved.title == "Test Decision"


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update(store):
    event = _make_event()
    await store.append(event)
    event.title = "Updated Title"
    updated = await store.update(event)
    assert updated is True
    retrieved = await store.get(event.id)
    assert retrieved.title == "Updated Title"


@pytest.mark.asyncio
async def test_delete(store):
    event = _make_event()
    await store.append(event)
    deleted = await store.delete(event.id)
    assert deleted is True
    assert await store.get(event.id) is None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_filters(store):
    await store.append(_make_event(type=EventType.DECISION, domain=Domain.FINANCE))
    await store.append(_make_event(type=EventType.GOAL, domain=Domain.EDUCATION))

    filters = QueryFilters(event_type=EventType.DECISION)
    results = await store.query(filters)
    assert len(results) == 1
    assert results[0].type == EventType.DECISION


@pytest.mark.asyncio
async def test_query_by_domain(store):
    await store.append(_make_event(domain=Domain.FINANCE))
    await store.append(_make_event(domain=Domain.EDUCATION))
    filters = QueryFilters(domain=Domain.EDUCATION)
    results = await store.query(filters)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_query_search_text(store):
    await store.append(_make_event(title="Investment Decision"))
    await store.append(_make_event(title="Study Plan"))
    filters = QueryFilters(search_text="investment")
    results = await store.query(filters)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count(store):
    assert await store.count() == 0
    await store.append(_make_event())
    assert await store.count() == 1


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_version_snapshot(store):
    event = _make_event()
    await store.append(event)
    snapshot = await store.version_snapshot(event.id)
    assert snapshot is not None
    assert snapshot.event_id == event.id


# ---------------------------------------------------------------------------
# Export/Delete all (Soberania)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_all(store):
    await store.append(_make_event())
    await store.append(_make_event(title="Event 2"))
    data = await store.export_all()
    assert len(data) > 0


@pytest.mark.asyncio
async def test_delete_all(store):
    await store.append(_make_event())
    await store.append(_make_event(title="Event 2"))
    await store.delete_all()
    assert await store.count() == 0


# ---------------------------------------------------------------------------
# Health check (Monitor)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(store):
    health = await store.health_check()
    assert health["engine_healthy"] is True
    assert health["events_stored"] == 0


# ---------------------------------------------------------------------------
# Backend swap — proves abstraction works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backend_swap():
    """Same store logic, different engine — proves abstraction."""
    engine1 = MemoryPersistenceEngine()
    engine2 = MemoryPersistenceEngine()

    store1 = PersistenceKnowledgeStore(engine1)
    store2 = PersistenceKnowledgeStore(engine2)

    event = _make_event()
    await store1.append(event)

    # store1 has the event, store2 doesn't
    assert await store1.get(event.id) is not None
    assert await store2.get(event.id) is None
