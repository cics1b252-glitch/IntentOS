"""Sprint 4 tests for the single canonical Constitution."""

from __future__ import annotations

import pytest

from intent_kernel.adapters import (
    LegacyConstitutionEngineAdapter,
    LegacyGuardianAdapter,
)
from intent_kernel.application import KernelBuilder
from intent_kernel.constitution import (
    CanonicalConstitutionEngine,
    ConstitutionPipeline,
    create_default_constitution,
)
from intent_kernel.contracts import (
    ConstitutionDecision,
    Domain,
    KnowledgeEvent,
    Mission,
)


def _knowledge_data(**overrides):
    data = {
        "id": "ke-sprint-4",
        "event_type": "FACT",
        "content": {"raw": "Quero investir em ETFs"},
        "confidence": 1.0,
        "source": "conversation",
        "lifecycle": "transient",
        "metadata": {},
    }
    data.update(overrides)
    return data


def test_official_engine_has_six_unique_guardian_contracts():
    engine = CanonicalConstitutionEngine(create_default_constitution())

    assert [guardian.name for guardian in engine.guardians] == [
        "security",
        "policy",
        "continuity",
        "memory",
        "integrity",
        "audit",
    ]
    assert len({guardian.responsibility for guardian in engine.guardians}) == 6


@pytest.mark.asyncio
async def test_clean_action_uses_canonical_verdict():
    engine = CanonicalConstitutionEngine(create_default_constitution())

    verdict = await engine.evaluate("process", "hello")

    assert verdict.decision is ConstitutionDecision.ALLOW
    assert verdict.allowed is True
    assert verdict.constitution_version == "1.0.0"
    assert len(verdict.metadata["guardian_results"]) == 6


@pytest.mark.asyncio
async def test_sensitive_knowledge_is_advisory_as_before():
    engine = CanonicalConstitutionEngine(create_default_constitution())
    data = _knowledge_data(content={"raw": "api_key: sk-example"})

    verdict = await engine.evaluate("knowledge.ingest", data)

    assert verdict.decision is ConstitutionDecision.ALLOW_WITH_CONDITIONS
    assert verdict.allowed is True
    assert verdict.conditions


@pytest.mark.asyncio
async def test_low_confidence_inferred_decision_is_denied():
    engine = CanonicalConstitutionEngine(create_default_constitution())
    data = _knowledge_data(
        event_type="DECISION",
        source="inference",
        confidence=0.4,
    )

    verdict = await engine.evaluate("knowledge.ingest", data)

    assert verdict.decision is ConstitutionDecision.DENY
    assert verdict.violated_rule == "validity"


@pytest.mark.asyncio
async def test_every_decision_is_audited_and_published(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    engine = components.constitution_engine

    verdict = await engine.evaluate(
        "process",
        "hello",
        {"correlation_id": "corr-4"},
    )
    audit = engine.get_audit_log()
    published = components.kernel.event_bus.get_history(
        "constitution.audit"
    )

    assert verdict.metadata["audit_id"] == audit[0].audit_id
    assert audit[0].correlation_id == "corr-4"
    assert len(published) == 1
    assert published[0]["data"]["correlation_id"] == "corr-4"


@pytest.mark.asyncio
async def test_constitution_pipeline_stops_denied_operation():
    engine = CanonicalConstitutionEngine(create_default_constitution())
    pipeline = ConstitutionPipeline(engine)
    mission = Mission(objective="Store knowledge")
    called = False

    async def operation():
        nonlocal called
        called = True
        return "done"

    data = _knowledge_data(
        event_type="DECISION",
        source="inference",
        confidence=0.1,
    )
    verdict, result = await pipeline.execute(
        mission,
        "knowledge.ingest",
        operation,
        data,
    )

    assert verdict.decision is ConstitutionDecision.DENY
    assert result is None
    assert called is False


@pytest.mark.asyncio
async def test_constitution_pipeline_allows_operation():
    engine = CanonicalConstitutionEngine(create_default_constitution())
    pipeline = ConstitutionPipeline(engine)
    mission = Mission(objective="Process request")

    async def operation():
        return "done"

    verdict, result = await pipeline.execute(
        mission,
        "process",
        operation,
    )

    assert verdict.allowed is True
    assert result == "done"


@pytest.mark.asyncio
async def test_pkb_uses_official_constitution_and_audit(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    event = KnowledgeEvent(
        event_type="fact",
        domain=Domain.ENGINEERING,
        title="Safe",
        content={"raw": "characterized"},
        summary="characterized",
        confidence=0.8,
        session_id="sprint-4",
    )

    report = await components.kernel.knowledge.pipeline.ingest(
        [event]
    )

    assert report.approved == 1
    assert components.constitution_engine.get_audit_log()
    assert components.kernel.event_bus.get_history("constitution.audit")
    assert components.kernel.event_bus.get_history("knowledge.audit")


@pytest.mark.asyncio
async def test_legacy_constitution_adapter_remains_compatible():
    legacy = LegacyConstitutionEngineAdapter(
        create_default_constitution()
    )

    verdict = await legacy.evaluate("process", "hello")

    assert verdict.decision is ConstitutionDecision.ALLOW
    assert verdict.allowed is True


def test_official_guardian_has_legacy_compatibility_adapter():
    engine = CanonicalConstitutionEngine(create_default_constitution())
    adapter = LegacyGuardianAdapter(engine.guardians[0])

    verdict = adapter.validate(
        {"content": {"raw": "api_key: sk-example"}}
    )

    assert verdict.decision == "flagged"
    assert adapter.status()["adapter"] == "canonical"


def test_factory_exposes_one_official_constitution_pipeline(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()

    assert isinstance(
        components.constitution_engine,
        CanonicalConstitutionEngine,
    )
    assert isinstance(
        components.constitution_pipeline,
        ConstitutionPipeline,
    )
    assert (
        components.kernel.constitution_engine
        is components.constitution_engine
    )
