"""Sprint 3 tests for the single canonical PKB flow."""

from __future__ import annotations

from datetime import timedelta

import pytest

import intent_kernel.pkb as pkb
from intent_kernel.adapters import (
    from_legacy_knowledge_event,
    to_legacy_knowledge_event,
)
from intent_kernel.application import KernelBuilder
from intent_kernel.contracts import (
    Domain,
    KnowledgeEvent,
    KnowledgeLifecycle,
)
from intent_kernel.pkb import (
    CanonicalKnowledgeCurator,
    CurationAction,
    KnowledgePipeline,
)
from intent_kernel.pkb.models import KnowledgeEvent as LegacyKnowledgeEvent
from intent_kernel.types import (
    Domain as LegacyDomain,
    EventLifecycle,
    EventType,
    utcnow,
)


def _event(
    *,
    title: str = "Fact",
    content: str = "blue",
    confidence: float = 0.8,
    event_type: str = "fact",
) -> KnowledgeEvent:
    return KnowledgeEvent(
        event_type=event_type,
        domain=Domain.ENGINEERING,
        title=title,
        content={"raw": content},
        summary=content,
        confidence=confidence,
        session_id="sprint-3",
    )


def _pipeline(tmp_path):
    components = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    return (
        KnowledgePipeline(
            store=components.knowledge_store,
            curator=CanonicalKnowledgeCurator(),
            constitution=components.constitution_engine,
            event_publisher=components.event_publisher,
        ),
        components,
    )


def test_pkb_exports_one_official_event_model():
    assert pkb.KnowledgeEvent is KnowledgeEvent
    assert pkb.LegacyKnowledgeEvent is LegacyKnowledgeEvent
    assert pkb.CanonicalKnowledgeCurator is CanonicalKnowledgeCurator


@pytest.mark.asyncio
async def test_official_curator_integrates_score_and_audit():
    curator = CanonicalKnowledgeCurator()

    low = await curator.curate(_event(confidence=0.2))
    candidate = await curator.curate(_event(confidence=0.45))
    approved = await curator.curate(_event(confidence=0.8))

    assert low.action is CurationAction.DISCARD
    assert low.score.value == 20
    assert candidate.action is CurationAction.CANDIDATE
    assert candidate.score.value == 45
    assert approved.action is CurationAction.APPROVE
    assert approved.score.value == 80
    assert approved.audit.event_id == approved.event.id
    assert approved.audit.score == approved.score.value

    explicit = _event(confidence=0.1)
    explicit.metadata["score_breakdown"] = {
        "relevance": 95,
        "persistence": 95,
        "reuse": 95,
        "impact": 95,
        "goalAlignment": 95,
    }
    constitutional = await curator.curate(explicit)
    assert constitutional.score.value == 95
    assert (
        constitutional.lifecycle
        is KnowledgeLifecycle.CONSTITUTIONAL
    )


@pytest.mark.asyncio
async def test_official_curator_preserves_duplicate_behavior():
    curator = CanonicalKnowledgeCurator()
    existing = _event()

    result = await curator.curate(_event(), [existing])

    assert result.action is CurationAction.CANDIDATE
    assert result.existing_event is existing


@pytest.mark.asyncio
async def test_pipeline_persists_and_publishes_audit(tmp_path):
    pipeline, components = _pipeline(tmp_path)

    report = await pipeline.ingest([_event()])
    stored = await pipeline.get(report.event_ids[0])
    audit_events = components.kernel.event_bus.get_history(
        "knowledge.audit"
    )

    assert report.approved == 1
    assert stored is not None
    assert stored.lifecycle is KnowledgeLifecycle.APPROVED
    assert len(stored.lifecycle_history) == 1
    assert report.audit[0].action is CurationAction.APPROVE
    assert len(audit_events) == 1


@pytest.mark.asyncio
async def test_pipeline_detects_fact_conflict_without_overwrite(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    first = _event(title="Color A", content="blue")
    conflicting = _event(title="Color B", content="red")

    await pipeline.ingest([first])
    report = await pipeline.ingest([conflicting])

    assert report.conflicts == 1
    assert report.rejected == 1
    assert await pipeline.count() == 1
    assert report.audit[0].conflict_with == first.id


@pytest.mark.asyncio
async def test_pipeline_merges_explicit_correction(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    original = _event(title="Original", content="blue")
    await pipeline.ingest([original])
    correction = _event(
        title="Correction",
        content="green",
        event_type="correction",
    )

    report = await pipeline.ingest([correction])
    restored = await pipeline.get(original.id)

    assert report.merged == 1
    assert restored is not None
    assert restored.content == {"raw": "green"}
    assert restored.version == 2


@pytest.mark.asyncio
async def test_snapshot_rollback_export_and_delete_use_store_port(tmp_path):
    pipeline, components = _pipeline(tmp_path)
    event = _event()
    await pipeline.ingest([event])
    snapshot = await pipeline.snapshot(event.id)
    assert snapshot is not None

    changed = await pipeline.get(event.id)
    assert changed is not None
    changed.content = {"raw": "changed"}
    assert await components.knowledge_store.update(changed) is True
    assert await pipeline.rollback(snapshot.id) is True

    restored = await pipeline.get(event.id)
    exported = await pipeline.export()
    assert restored is not None
    assert restored.content == {"raw": "blue"}
    assert event.id.encode() in exported
    assert await pipeline.delete(event.id) is True
    assert await pipeline.count() == 0


def test_legacy_event_adapter_preserves_versioning_fields():
    legacy = LegacyKnowledgeEvent(
        type=EventType.FACT,
        domain=LegacyDomain.ENGINEERING,
        title="Legacy",
        summary="Adapter",
        confidence=0.8,
        lifecycle=EventLifecycle.APPROVED,
        expires_at=utcnow() + timedelta(days=1),
    )
    legacy.transition(EventLifecycle.CANDIDATE, "characterized")

    canonical = from_legacy_knowledge_event(legacy)
    restored = to_legacy_knowledge_event(canonical)

    assert restored.id == legacy.id
    assert restored.lifecycle is EventLifecycle.CANDIDATE
    assert restored.expires_at == legacy.expires_at
    assert len(restored.lifecycle_history) == 1
    assert restored.lifecycle_history[0].reason == "characterized"
