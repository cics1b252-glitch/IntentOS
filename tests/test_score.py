"""Test: Knowledge Score Calculator — RFC-0003 Section 6."""

import pytest
from datetime import datetime, timezone, timedelta

from intent_kernel.pkb.score import (
    KnowledgeScoreCalculator,
    KnowledgeScoreBreakdown,
    WEIGHTS,
    SCORE_THRESHOLDS,
    RECALC_COOLDOWN_MS,
    score_relevance,
    score_persistence,
    score_reuse,
    score_impact,
    score_goal_alignment,
)


@pytest.fixture
def calc():
    return KnowledgeScoreCalculator()


# ---------------------------------------------------------------------------
# Basic calculation
# ---------------------------------------------------------------------------

def test_weights_sum_to_one():
    """Weights must sum to 1.0."""
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 0.001


def test_calculate_all_zeros(calc):
    """All zeros = 0."""
    b = KnowledgeScoreBreakdown()
    assert calc.calculate(b) == 0.0


def test_calculate_all_100(calc):
    """All 100 = 100."""
    b = KnowledgeScoreBreakdown(relevance=100, persistence=100, reuse=100, impact=100, goalAlignment=100)
    assert calc.calculate(b) == 100.0


def test_calculate_known_values(calc):
    """Verify with known input/output pairs."""
    # RFC-0003 Section 12.1 example
    b = KnowledgeScoreBreakdown(
        relevance=95, persistence=85, reuse=80, impact=90, goalAlignment=90
    )
    score = calc.calculate(b)
    expected = 95*0.30 + 85*0.25 + 80*0.20 + 90*0.15 + 90*0.10
    assert abs(score - expected) < 0.01


def test_calculate_rounds_to_two_decimals(calc):
    """Score is rounded to 2 decimal places."""
    b = KnowledgeScoreBreakdown(relevance=33, persistence=44, reuse=55, impact=66, goalAlignment=77)
    score = calc.calculate(b)
    assert score == round(score, 2)


# ---------------------------------------------------------------------------
# Breakdown clamping
# ---------------------------------------------------------------------------

def test_breakdown_clamp(calc):
    """Values outside 0-100 are clamped."""
    b = KnowledgeScoreBreakdown(relevance=150, persistence=-10, reuse=50, impact=50, goalAlignment=50)
    score = calc.calculate(b)
    assert b.relevance == 100
    assert b.persistence == 0
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# Target levels — RFC-0003 Section 6.4
# ---------------------------------------------------------------------------

def test_level_discard(calc):
    """Score 0-29 → DISCARD."""
    assert calc.get_target_level(0) == "DISCARD"
    assert calc.get_target_level(29) == "DISCARD"


def test_level_candidate(calc):
    """Score 30-69 → CANDIDATE."""
    assert calc.get_target_level(30) == "CANDIDATE"
    assert calc.get_target_level(50) == "CANDIDATE"
    assert calc.get_target_level(69) == "CANDIDATE"


def test_level_approved(calc):
    """Score 70-89 → APPROVED."""
    assert calc.get_target_level(70) == "APPROVED"
    assert calc.get_target_level(80) == "APPROVED"
    assert calc.get_target_level(89) == "APPROVED"


def test_level_constitutional(calc):
    """Score 90+ → CONSTITUTIONAL."""
    assert calc.get_target_level(90) == "CONSTITUTIONAL"
    assert calc.get_target_level(100) == "CONSTITUTIONAL"


# ---------------------------------------------------------------------------
# Build score
# ---------------------------------------------------------------------------

def test_build_score(calc):
    """build_score returns complete KnowledgeScore."""
    b = KnowledgeScoreBreakdown(relevance=80, persistence=70, reuse=60, impact=50, goalAlignment=40)
    score = calc.build_score(b)
    assert score.value > 0
    assert score.calculated_at  # not empty
    assert score.recalculations == []
    assert score.breakdown.relevance == 80


# ---------------------------------------------------------------------------
# Recalculation — RFC-0003 Section 6.5
# ---------------------------------------------------------------------------

def test_can_recalculate_after_cooldown(calc):
    """Recalc allowed after 24h cooldown."""
    past = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert calc.can_recalculate(past, "FACT") is True


def test_cannot_recalculate_within_cooldown(calc):
    """Recalc blocked within 24h cooldown."""
    recent = datetime.now(timezone.utc).isoformat()
    assert calc.can_recalculate(recent, "FACT") is False


def test_correction_bypasses_cooldown(calc):
    """CORRECTION events bypass cooldown."""
    recent = datetime.now(timezone.utc).isoformat()
    assert calc.can_recalculate(recent, "CORRECTION") is True


def test_can_recalculate_invalid_date(calc):
    """Invalid date string allows recalc."""
    assert calc.can_recalculate("not-a-date", "FACT") is True


# ---------------------------------------------------------------------------
# Merge — RFC-0003 Section 7.3
# ---------------------------------------------------------------------------

def test_calculate_merged(calc):
    """Merge takes max + bonus."""
    # max(80, 70) + min(10, 2*2) = 80 + 4 = 84
    merged = calc.calculate_merged(80, 70, 2)
    assert merged == 84.0


def test_calculate_merged_cap_100(calc):
    """Merged score capped at 100."""
    merged = calc.calculate_merged(95, 90, 10)
    assert merged == 100.0


def test_calculate_merged_single_confirmation(calc):
    """Single confirmation adds 2 points."""
    merged = calc.calculate_merged(70, 60, 1)
    assert merged == 72.0


# ---------------------------------------------------------------------------
# Scoring heuristics
# ---------------------------------------------------------------------------

def test_score_relevance_decision():
    """DECISION with user declaration = high relevance."""
    assert score_relevance("DECISION", has_user_declaration=True, domain_relevance="high") >= 90


def test_score_relevance_ephemeral():
    """EPHEMERAL = low relevance."""
    assert score_relevance("EPHEMERAL", has_user_declaration=False, domain_relevance="low") < 20


def test_score_persistence_correction():
    """CORRECTION = high persistence."""
    assert score_persistence("CORRECTION", is_permanent_data=False) >= 80


def test_score_persistence_ephemeral():
    """EPHEMERAL = low persistence."""
    assert score_persistence("EPHEMERAL", is_permanent_data=False) < 15


def test_score_reuse_high():
    """80%+ session ratio = high reuse."""
    assert score_reuse(domain_sessions=80, total_sessions=100) >= 90


def test_score_reuse_low():
    """<10% session ratio = low reuse."""
    assert score_reuse(domain_sessions=1, total_sessions=100) < 30


def test_score_impact_critical():
    """Critical memory failure = high impact."""
    assert score_impact("critical") >= 90


def test_score_impact_none():
    """No impact = low."""
    assert score_impact("none") < 15


def test_score_goal_alignment_strong():
    """Active goal + strong match = high alignment."""
    assert score_goal_alignment(True, "strong") >= 90


def test_score_goal_alignment_none():
    """No goal = low alignment."""
    assert score_goal_alignment(False) < 30


# ---------------------------------------------------------------------------
# Thresholds defined correctly
# ---------------------------------------------------------------------------

def test_thresholds_ordering():
    """Thresholds are in ascending order."""
    assert SCORE_THRESHOLDS["DISCARD"] < SCORE_THRESHOLDS["CANDIDATE"]
    assert SCORE_THRESHOLDS["CANDIDATE"] < SCORE_THRESHOLDS["APPROVED"]
    assert SCORE_THRESHOLDS["APPROVED"] < SCORE_THRESHOLDS["CONSTITUTIONAL"]
