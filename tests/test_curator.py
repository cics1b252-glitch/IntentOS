"""Test: Knowledge Curator."""

import pytest
from intent_kernel.pkb.curator import KnowledgeCurator
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import Domain, EventLifecycle, EventType


@pytest.fixture
def curator():
    return KnowledgeCurator()


def _make_event(
    confidence: float = 0.5,
    event_type: EventType = EventType.DECISION,
    domain: Domain = Domain.OTHER,
) -> KnowledgeEvent:
    return KnowledgeEvent(
        type=event_type,
        domain=domain,
        title="Test event",
        content={"test": True},
        summary="Test summary",
        confidence=confidence,
    )


@pytest.mark.asyncio
async def test_low_confidence_transient(curator):
    """Low confidence → Transient."""
    event = _make_event(confidence=0.2)
    result = await curator.evaluate(event)
    assert result == EventLifecycle.TRANSIENT


@pytest.mark.asyncio
async def test_medium_confidence_candidate(curator):
    """Medium confidence → Candidate."""
    event = _make_event(confidence=0.45)
    result = await curator.evaluate(event)
    assert result == EventLifecycle.CANDIDATE


@pytest.mark.asyncio
async def test_high_confidence_approved(curator):
    """High confidence → Approved."""
    event = _make_event(confidence=0.8)
    result = await curator.evaluate(event)
    assert result == EventLifecycle.APPROVED


@pytest.mark.asyncio
async def test_decision_high_confidence_priority(curator):
    """DECISION with high confidence → Approved (priority)."""
    event = _make_event(confidence=0.9, event_type=EventType.DECISION)
    result = await curator.evaluate(event)
    assert result == EventLifecycle.APPROVED


@pytest.mark.asyncio
async def test_memory_always_approved(curator):
    """MEMORY events are always Approved."""
    event = _make_event(confidence=0.1, event_type=EventType.MEMORY)
    result = await curator.evaluate(event)
    assert result == EventLifecycle.APPROVED


@pytest.mark.asyncio
async def test_duplicate_detection(curator):
    """Duplicate events are detected."""
    existing = [_make_event(confidence=0.8)]
    event = _make_event(confidence=0.8)  # same title/type/domain
    result = await curator.evaluate(event, existing)
    assert result == EventLifecycle.CANDIDATE  # duplicate → candidate for merge


@pytest.mark.asyncio
async def test_should_promote_high_confidence(curator):
    """High confidence candidate should be promoted."""
    event = _make_event(confidence=0.7)
    assert await curator.should_promote(event) is True


@pytest.mark.asyncio
async def test_should_promote_decision(curator):
    """Decision candidates should be promoted."""
    event = _make_event(confidence=0.4, event_type=EventType.DECISION)
    assert await curator.should_promote(event) is True
