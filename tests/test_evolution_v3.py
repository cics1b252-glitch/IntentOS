"""Test: Evolution Engine v3 — personality of Intent OS."""

import pytest
from intent_kernel.evolution.v3 import (
    EvolutionEngineV3,
    OpportunityEngine,
    RiskEngine,
    GoalEvolutionEngine,
    CognitiveCoach,
)
from intent_kernel.kernel import Kernel


@pytest.fixture
def engine():
    return EvolutionEngineV3(Kernel())


@pytest.fixture
def engine_no_kernel():
    return EvolutionEngineV3()


# ---------------------------------------------------------------------------
# Opportunity Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opportunities_no_kernel(engine_no_kernel):
    opps = await engine_no_kernel.opportunities.detect()
    assert opps == []


@pytest.mark.asyncio
async def test_opportunities(engine):
    opps = await engine.opportunities.detect()
    assert isinstance(opps, list)


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_risks_no_kernel(engine_no_kernel):
    risks = await engine_no_kernel.risks.detect()
    assert risks == []


@pytest.mark.asyncio
async def test_risks(engine):
    risks = await engine.risks.detect()
    assert isinstance(risks, list)


# ---------------------------------------------------------------------------
# Goal Evolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_goal_evolution_no_kernel(engine_no_kernel):
    suggestions = await engine_no_kernel.goals.analyze()
    assert suggestions == []


@pytest.mark.asyncio
async def test_goal_evolution(engine):
    suggestions = await engine.goals.analyze()
    assert isinstance(suggestions, list)


# ---------------------------------------------------------------------------
# Cognitive Coach
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coach_no_kernel(engine_no_kernel):
    messages = await engine_no_kernel.coach.generate_messages()
    assert messages == []


@pytest.mark.asyncio
async def test_coach(engine):
    messages = await engine.coach.generate_messages()
    assert isinstance(messages, list)


# ---------------------------------------------------------------------------
# Full Analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_analysis(engine):
    result = await engine.full_analysis()
    assert "opportunities" in result
    assert "risks" in result
    assert "goal_suggestions" in result
    assert "coach_messages" in result


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_engine_name(engine):
    assert engine.name == "evolution_engine_v3"
