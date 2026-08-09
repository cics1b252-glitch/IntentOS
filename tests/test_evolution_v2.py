"""Test: Evolution Engine v2 — Cognitive Profile, Knowledge Value, Drift."""

import pytest
from intent_kernel.evolution.v2 import (
    CognitiveProfileEngine,
    KnowledgeValueEngine,
    CognitiveDriftDetector,
    CognitiveProfile,
    KnowledgeValue,
    CognitiveDrift,
)
from intent_kernel.kernel import Kernel


@pytest.fixture
def profile_engine():
    return CognitiveProfileEngine(Kernel())


@pytest.fixture
def value_engine():
    return KnowledgeValueEngine(Kernel())


@pytest.fixture
def drift_detector():
    return CognitiveDriftDetector(Kernel())


# ---------------------------------------------------------------------------
# Cognitive Profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_profile(profile_engine):
    profile = await profile_engine.build_profile()
    assert isinstance(profile, CognitiveProfile)
    assert profile.maturity_score >= 0
    assert profile.domain_diversity >= 0


@pytest.mark.asyncio
async def test_profile_no_kernel():
    engine = CognitiveProfileEngine()
    profile = await engine.build_profile()
    assert profile.project_count == 0


def test_consistency_calc(profile_engine):
    from intent_kernel.pkb.models import KnowledgeEvent
    from intent_kernel.types import Domain, EventType

    # Same confidence = high consistency
    events = [
        KnowledgeEvent(type=EventType.DECISION, domain=Domain.FINANCE, title="D1", content={}, summary="", confidence=0.8),
        KnowledgeEvent(type=EventType.DECISION, domain=Domain.FINANCE, title="D2", content={}, summary="", confidence=0.8),
    ]
    consistency = profile_engine._calc_consistency(events)
    assert consistency > 0.8


# ---------------------------------------------------------------------------
# Knowledge Value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calculate_values(value_engine):
    values = await value_engine.calculate_values()
    assert isinstance(values, list)


@pytest.mark.asyncio
async def test_calculate_values_no_kernel():
    engine = KnowledgeValueEngine()
    values = await engine.calculate_values()
    assert values == []


def test_knowledge_value_dataclass():
    kv = KnowledgeValue(event_id="test", title="Test", value_score=85.0)
    assert kv.value_score == 85.0


# ---------------------------------------------------------------------------
# Cognitive Drift
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_drift(drift_detector):
    drifts = await drift_detector.detect()
    assert isinstance(drifts, list)


@pytest.mark.asyncio
async def test_detect_drift_no_kernel():
    detector = CognitiveDriftDetector()
    drifts = await detector.detect()
    assert drifts == []


def test_drift_dataclass():
    d = CognitiveDrift(title="Test", drift_type="abandonment", severity="medium")
    assert d.drift_type == "abandonment"


# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------

def test_profile_defaults():
    p = CognitiveProfile()
    assert p.learning_style == "unknown"
    assert p.maturity_score == 0.0
    assert p.preferred_domains == []
