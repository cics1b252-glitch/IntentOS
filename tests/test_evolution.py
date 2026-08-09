"""Test: Evolution Engine — the brain that makes Intent OS evolve."""

import pytest
from intent_kernel.evolution import EvolutionEngine, Insight, ReflectionResult
from intent_kernel.kernel import Kernel


@pytest.fixture
def engine():
    kernel = Kernel()
    return EvolutionEngine(kernel)


@pytest.fixture
def engine_no_kernel():
    return EvolutionEngine()


# ---------------------------------------------------------------------------
# Pattern Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_no_kernel(engine_no_kernel):
    patterns = await engine_no_kernel.detect_patterns()
    assert patterns == []


@pytest.mark.asyncio
async def test_detect_patterns(engine):
    patterns = await engine.detect_patterns()
    assert isinstance(patterns, list)


# ---------------------------------------------------------------------------
# Cognitive Insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_insights_no_kernel(engine_no_kernel):
    insights = await engine_no_kernel.generate_insights()
    assert insights == []


@pytest.mark.asyncio
async def test_generate_insights(engine):
    insights = await engine.generate_insights()
    assert isinstance(insights, list)


def test_get_insights(engine_no_kernel):
    insights = engine_no_kernel.get_insights()
    assert isinstance(insights, list)


# ---------------------------------------------------------------------------
# Reflection Cycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reflection_cycle(engine):
    result = await engine.run_reflection()
    assert isinstance(result, ReflectionResult)
    assert result.timestamp
    assert result.redundancies_found >= 0
    assert result.gaps_found >= 0


@pytest.mark.asyncio
async def test_reflection_no_kernel(engine_no_kernel):
    result = await engine_no_kernel.run_reflection()
    assert result.redundancies_found == 0


@pytest.mark.asyncio
async def test_reflection_history(engine):
    await engine.run_reflection()
    history = engine.get_reflection_history()
    assert len(history) == 1


# ---------------------------------------------------------------------------
# Meta Knowledge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_knowledge_no_kernel(engine_no_kernel):
    mk = await engine_no_kernel.get_meta_knowledge()
    assert mk == {}


@pytest.mark.asyncio
async def test_meta_knowledge(engine):
    mk = await engine.get_meta_knowledge()
    assert "total_events" in mk


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommendations(engine):
    recs = await engine.get_recommendations()
    assert isinstance(recs, list)


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_engine_name(engine):
    assert engine.name == "evolution_engine"
