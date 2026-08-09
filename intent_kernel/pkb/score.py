"""Knowledge Score Calculator — RFC-0003 Section 6.

Score-based decision mechanism for the Knowledge Curator.
5 weighted variables, thresholds for lifecycle classification.

This is the core decision mechanism that replaces confidence-based classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from intent_kernel.types import new_id


# ---------------------------------------------------------------------------
# Score Breakdown — the 5 weighted variables
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeScoreBreakdown:
    """The 5 variables that compose the Knowledge Score.

    Each variable is 0-100. Weights sum to 1.0.
    """
    relevance: float = 0.0      # How directly the KE connects to user objectives
    persistence: float = 0.0    # How long the data remains valid
    reuse: float = 0.0          # How often the KE would be consulted
    impact: float = 0.0         # Consequence of not remembering this data
    goalAlignment: float = 0.0  # How much it contributes to active projects/goals

    def clamp(self) -> None:
        """Clamp all values to 0-100."""
        self.relevance = max(0, min(100, self.relevance))
        self.persistence = max(0, min(100, self.persistence))
        self.reuse = max(0, min(100, self.reuse))
        self.impact = max(0, min(100, self.impact))
        self.goalAlignment = max(0, min(100, self.goalAlignment))


# ---------------------------------------------------------------------------
# Weights — RFC-0003 Section 6.1
# ---------------------------------------------------------------------------

WEIGHTS = {
    "relevance": 0.30,
    "persistence": 0.25,
    "reuse": 0.20,
    "impact": 0.15,
    "goalAlignment": 0.10,
}

# ---------------------------------------------------------------------------
# Thresholds — RFC-0003 Section 6.4
# ---------------------------------------------------------------------------

SCORE_THRESHOLDS = {
    "DISCARD": 0,       # 0-29: discarded
    "CANDIDATE": 30,    # 30-69: candidate queue
    "APPROVED": 70,     # 70-89: approved to KC
    "CONSTITUTIONAL": 90,  # 90+: permanent in KC
}

# Recalc cooldown: 24 hours (except CORRECTION)
RECALC_COOLDOWN_MS = 24 * 60 * 60 * 1000


# ---------------------------------------------------------------------------
# Score Data
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeScore:
    """A computed Knowledge Score with breakdown and history."""
    value: float = 0.0
    breakdown: KnowledgeScoreBreakdown = field(default_factory=KnowledgeScoreBreakdown)
    calculated_at: str = ""
    recalculations: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class KnowledgeScoreCalculator:
    """Calculates Knowledge Score from breakdown variables.

    Usage:
        calc = KnowledgeScoreCalculator()
        breakdown = KnowledgeScoreBreakdown(
            relevance=85, persistence=80, reuse=70, impact=75, goalAlignment=90
        )
        score = calc.build_score(breakdown)
        # score.value = 79.25
        # calc.get_target_level(79.25) → "APPROVED"
    """

    def calculate(self, breakdown: KnowledgeScoreBreakdown) -> float:
        """Calculate weighted score from breakdown.

        Formula: Σ (weight × value)
        = relevance × 0.30
        + persistence × 0.25
        + reuse × 0.20
        + impact × 0.15
        + goalAlignment × 0.10
        """
        breakdown.clamp()
        score = (
            breakdown.relevance * WEIGHTS["relevance"]
            + breakdown.persistence * WEIGHTS["persistence"]
            + breakdown.reuse * WEIGHTS["reuse"]
            + breakdown.impact * WEIGHTS["impact"]
            + breakdown.goalAlignment * WEIGHTS["goalAlignment"]
        )
        return round(score, 2)

    def build_score(self, breakdown: KnowledgeScoreBreakdown) -> KnowledgeScore:
        """Build a complete KnowledgeScore from breakdown."""
        return KnowledgeScore(
            value=self.calculate(breakdown),
            breakdown=KnowledgeScoreBreakdown(
                relevance=breakdown.relevance,
                persistence=breakdown.persistence,
                reuse=breakdown.reuse,
                impact=breakdown.impact,
                goalAlignment=breakdown.goalAlignment,
            ),
            calculated_at=datetime.now(timezone.utc).isoformat(),
            recalculations=[],
        )

    def get_target_level(self, score: float) -> str:
        """Determine target lifecycle level from score.

        Returns: 'DISCARD' | 'CANDIDATE' | 'APPROVED' | 'CONSTITUTIONAL'
        """
        if score >= SCORE_THRESHOLDS["CONSTITUTIONAL"]:
            return "CONSTITUTIONAL"
        elif score >= SCORE_THRESHOLDS["APPROVED"]:
            return "APPROVED"
        elif score >= SCORE_THRESHOLDS["CANDIDATE"]:
            return "CANDIDATE"
        else:
            return "DISCARD"

    def can_recalculate(
        self,
        last_calculated_at: str,
        event_type: str,
        now: datetime | None = None,
    ) -> bool:
        """Check if recalculation is allowed (cooldown check).

        CORRECTION events bypass cooldown.
        """
        if event_type == "CORRECTION":
            return True

        if now is None:
            now = datetime.now(timezone.utc)

        try:
            last = datetime.fromisoformat(last_calculated_at)
            elapsed_ms = (now - last).total_seconds() * 1000
            return elapsed_ms >= RECALC_COOLDOWN_MS
        except (ValueError, TypeError):
            return True  # If we can't parse, allow recalc

    def calculate_merged(
        self,
        score_a: float,
        score_b: float,
        confirmation_count: int,
    ) -> float:
        """Calculate merged score when two KEs are combined.

        Formula: min(100, max(a, b) + min(10, count * 2))
        Each confirmation adds up to 10 points (2 per confirmation).
        """
        bonus = min(10, confirmation_count * 2)
        merged = max(score_a, score_b) + bonus
        return round(min(100, merged), 2)


# ---------------------------------------------------------------------------
# Scoring Heuristics — RFC-0003 Section 6.3
# ---------------------------------------------------------------------------

def score_relevance(event_type: str, has_user_declaration: bool, domain_relevance: str) -> float:
    """Score relevance based on event characteristics.

    Heuristics from RFC-0003:
    - 90-100: Explicit user decision with direct consequence
    - 70-89: Declared preference or essential fact
    - 50-69: Contextually relevant information
    - 30-49: Peripheral but related data
    - 0-29: Generic or low-value information
    """
    if event_type == "DECISION" and has_user_declaration:
        return 95.0
    if event_type == "PREFERENCE" and has_user_declaration:
        return 85.0
    if event_type in ("FACT", "CORRECTION") and has_user_declaration:
        return 80.0
    if event_type == "CONTEXT":
        return 55.0
    if event_type == "PATTERN":
        return 60.0
    if event_type == "EPHEMERAL":
        return 15.0
    return 50.0  # default


def score_persistence(event_type: str, is_permanent_data: bool) -> float:
    """Score persistence based on data longevity.

    Heuristics from RFC-0003:
    - 90-100: Permanent data (timezone, name, profile)
    - 70-89: Valid for months or until explicit change
    - 50-69: Valid for current project/cycle
    - 30-49: Valid for session or task
    - 0-29: Ephemeral, no future value
    """
    if is_permanent_data:
        return 95.0
    if event_type in ("DECISION", "PREFERENCE", "CORRECTION"):
        return 85.0
    if event_type == "FACT":
        return 75.0
    if event_type in ("PATTERN", "CONTEXT"):
        return 55.0
    if event_type == "EPHEMERAL":
        return 10.0
    return 50.0


def score_reuse(
    domain_sessions: int = 0,
    total_sessions: int = 1,
) -> float:
    """Score reuse based on how often the KE would be consulted.

    Heuristics from RFC-0003:
    - 90-100: Consulted in 80%+ of domain sessions
    - 70-89: Frequently consulted in similar sessions
    - 50-69: Useful in specific recurring contexts
    - 30-49: Little reuse expected
    - 0-29: Single use, no future application
    """
    if total_sessions == 0:
        return 50.0
    ratio = domain_sessions / total_sessions
    if ratio >= 0.8:
        return 90.0
    if ratio >= 0.5:
        return 75.0
    if ratio >= 0.3:
        return 60.0
    if ratio >= 0.1:
        return 40.0
    return 20.0


def score_impact(
    memory_failure_severity: str = "medium",
) -> float:
    """Score impact based on consequence of forgetting.

    Heuristics from RFC-0003:
    - 90-100: Memory failure causes harmful decision
    - 70-89: Would cause rework or confusion
    - 50-69: Minor inconvenience
    - 30-49: Barely noticeable
    - 0-29: No measurable impact
    """
    severity_map = {
        "critical": 95.0,
        "high": 80.0,
        "medium": 55.0,
        "low": 35.0,
        "none": 10.0,
    }
    return severity_map.get(memory_failure_severity, 50.0)


def score_goal_alignment(
    has_active_goal: bool,
    goal_match_strength: str = "weak",
) -> float:
    """Score goal alignment based on contribution to active goals.

    Heuristics from RFC-0003:
    - 90-100: Directly tied to active project/goal
    - 70-89: Related to declared objective
    - 50-69: Aligned with general user interests
    - 30-49: Weak connection to known goals
    - 0-29: No connection to any goal
    """
    if has_active_goal and goal_match_strength == "strong":
        return 95.0
    if has_active_goal and goal_match_strength == "medium":
        return 75.0
    if has_active_goal:
        return 60.0
    return 25.0
