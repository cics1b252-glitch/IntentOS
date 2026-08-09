"""Test: JsonFileStore persistence."""

import pytest
import tempfile
from pathlib import Path
from intent_kernel.pkb.json_store import JsonFileStore
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import Domain, EventLifecycle, EventType, QueryFilters


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield JsonFileStore(path=tmpdir)


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


@pytest.mark.asyncio
async def test_append_and_get(store):
    """Can append and retrieve an event."""
    event = _make_event()
    event_id = await store.append(event)
    retrieved = await store.get(event_id)
    assert retrieved is not None
    assert retrieved.id == event_id
    assert retrieved.title == "Test Decision"


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    """Getting nonexistent event returns None."""
    result = await store.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_query_filters(store):
    """Query respects filters."""
    await store.append(_make_event(type=EventType.DECISION, domain=Domain.FINANCE))
    await store.append(_make_event(type=EventType.GOAL, domain=Domain.EDUCATION))

    # Filter by type
    filters = QueryFilters(event_type=EventType.DECISION)
    results = await store.query(filters)
    assert len(results) == 1
    assert results[0].type == EventType.DECISION

    # Filter by domain
    filters = QueryFilters(domain=Domain.EDUCATION)
    results = await store.query(filters)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_update(store):
    """Can update an event."""
    event = _make_event()
    await store.append(event)

    event.title = "Updated Title"
    updated = await store.update(event)
    assert updated is True

    retrieved = await store.get(event.id)
    assert retrieved.title == "Updated Title"


@pytest.mark.asyncio
async def test_delete(store):
    """Can delete an event (real delete — Soberania)."""
    event = _make_event()
    await store.append(event)
    deleted = await store.delete(event.id)
    assert deleted is True
    assert await store.get(event.id) is None


@pytest.mark.asyncio
async def test_count(store):
    """Count works."""
    assert await store.count() == 0
    await store.append(_make_event())
    assert await store.count() == 1
    await store.append(_make_event(title="Another"))
    assert await store.count() == 2


@pytest.mark.asyncio
async def test_export_all(store):
    """Export all events."""
    await store.append(_make_event())
    await store.append(_make_event(title="Event 2"))
    data = await store.export_all()
    assert len(data) > 0
    import json
    events = json.loads(data)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_delete_all(store):
    """Delete all events (Soberania)."""
    await store.append(_make_event())
    await store.append(_make_event(title="Event 2"))
    await store.delete_all()
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_version_snapshot(store):
    """Can create and use version snapshots."""
    event = _make_event()
    await store.append(event)

    snapshot = await store.version_snapshot(event.id)
    assert snapshot is not None
    assert snapshot.event_id == event.id
    assert snapshot.version == 1


@pytest.mark.asyncio
async def test_query_search_text(store):
    """Query by search text."""
    await store.append(_make_event(title="Investment Decision"))
    await store.append(_make_event(title="Study Plan"))

    filters = QueryFilters(search_text="investment")
    results = await store.query(filters)
    assert len(results) == 1
    assert "Investment" in results[0].title
