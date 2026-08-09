"""Evolution Engine v2 — Cognitive Profile, Knowledge Value, Drift Detection.

A live model of how the user learns, decides, and organizes.
Tracks longitudinal intelligence and cognitive drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CognitiveProfile:
    """A living model of the user's cognitive patterns."""
    # Learning patterns
    preferred_domains: list[str] = field(default_factory=list)
    learning_style: str = "unknown"  # example-driven, theory-first, mixed
    decision_speed: str = "unknown"  # fast, measured, slow
    completion_rate: float = 0.0     # % of started things completed
    review_tendency: float = 0.0     # how often they review decisions

    # Decision patterns
    avg_confidence: float = 0.0
    decision_consistency: float = 0.0  # how consistent decisions are
    reversible_preference: float = 0.0  # preference for reversible decisions

    # Organization patterns
    project_count: int = 0
    avg_project_duration_days: float = 0.0
    abandonment_rate: float = 0.0

    # Evolution metrics
    knowledge_growth_rate: float = 0.0   # events per week
    domain_diversity: float = 0.0        # 0-1, how spread across domains
    maturity_score: float = 0.0          # 0-100, overall cognitive maturity

    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class KnowledgeValue:
    """Value score for a piece of knowledge."""
    event_id: str = ""
    title: str = ""
    value_score: float = 0.0       # 0-100
    usage_frequency: float = 0.0   # how often referenced
    decision_impact: float = 0.0   # how many decisions it influenced
    connection_count: int = 0      # how many related events
    confirmation_count: int = 0    # times confirmed over time
    domain: str = ""


@dataclass
class CognitiveDrift:
    """A detected cognitive drift."""
    id: str = ""
    title: str = ""
    description: str = ""
    drift_type: str = ""    # goal_conflict, strategy_change, abandonment, inconsistency
    severity: str = ""      # low, medium, high
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CognitiveProfileEngine:
    """Builds and maintains the Cognitive Profile from Knowledge Core data."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def build_profile(self) -> CognitiveProfile:
        """Build/update the Cognitive Profile from KC data."""
        profile = CognitiveProfile()

        if not self.kernel:
            return profile

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=1000))

            if not events:
                return profile

            # Domain analysis
            domains = {}
            for e in events:
                d = e.domain.value
                domains[d] = domains.get(d, 0) + 1
            profile.preferred_domains = sorted(domains.keys(), key=lambda d: domains[d], reverse=True)[:3]
            profile.domain_diversity = len(domains) / 5.0  # normalized by max domains

            # Confidence analysis
            confidences = [e.confidence for e in events]
            profile.avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            # Decision analysis
            decisions = [e for e in events if e.type.value == "decision"]
            if decisions:
                profile.decision_consistency = self._calc_consistency(decisions)

            # Project analysis
            goals = [e for e in events if e.type.value == "goal"]
            profile.project_count = len(goals)

            # Growth rate (events per week approximation)
            profile.knowledge_growth_rate = len(events) / max(1, 4)  # assume 4 weeks of data

            # Maturity score
            profile.maturity_score = self._calc_maturity(profile, len(events), len(decisions))

            profile.updated_at = datetime.now(timezone.utc).isoformat()

        except Exception:
            pass

        return profile

    def _calc_consistency(self, decisions: list) -> float:
        """How consistent are the user's decisions?"""
        if len(decisions) < 2:
            return 0.5
        confidences = [d.confidence for d in decisions]
        avg = sum(confidences) / len(confidences)
        variance = sum((c - avg) ** 2 for c in confidences) / len(confidences)
        # Lower variance = higher consistency
        return max(0, min(1, 1 - variance))

    def _calc_maturity(self, profile: CognitiveProfile, total_events: int, total_decisions: int) -> float:
        """Calculate cognitive maturity score."""
        score = 0
        score += min(30, total_events * 0.5)        # up to 30 for knowledge volume
        score += min(20, total_decisions * 2)         # up to 20 for decision experience
        score += profile.domain_diversity * 20        # up to 20 for diversity
        score += profile.decision_consistency * 15    # up to 15 for consistency
        score += min(15, profile.knowledge_growth_rate * 3)  # up to 15 for growth
        return round(min(100, score), 1)


class KnowledgeValueEngine:
    """Calculates the value of knowledge in the KC."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def calculate_values(self, limit: int = 100) -> list[KnowledgeValue]:
        """Calculate knowledge value scores."""
        values = []
        if not self.kernel:
            return values

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=limit))

            for event in events:
                # Value formula
                usage = min(1.0, event.confidence)  # confidence as proxy for usage
                impact = 1.0 if event.type.value == "decision" else 0.5
                connections = 1.0  # simplified
                confirmation = 1.0 if event.lifecycle.value == "approved" else 0.5

                value_score = (usage * 0.3 + impact * 0.3 + connections * 0.2 + confirmation * 0.2) * 100

                values.append(KnowledgeValue(
                    event_id=event.id,
                    title=event.title[:40],
                    value_score=round(value_score, 1),
                    usage_frequency=usage,
                    decision_impact=impact,
                    connection_count=1,
                    confirmation_count=1,
                    domain=event.domain.value,
                ))

            # Sort by value
            values.sort(key=lambda v: v.value_score, reverse=True)

        except Exception:
            pass

        return values


class CognitiveDriftDetector:
    """Detects cognitive drift — when behavior contradicts stated goals."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def detect(self) -> list[CognitiveDrift]:
        """Detect cognitive drifts."""
        drifts = []
        if not self.kernel:
            return drifts

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            # Detect: goals without decisions
            goals = [e for e in events if e.type.value == "goal"]
            decisions = [e for e in events if e.type.value == "decision"]
            if goals and not decisions:
                drifts.append(CognitiveDrift(
                    id="goals_no_decisions",
                    title="Objetivos sem decisões",
                    description="Existem objetivos registrados mas nenhuma decisão tomada para alcançá-los.",
                    drift_type="abandonment",
                    severity="medium",
                ))

            # Detect: low confidence in decisions
            low_conf_decisions = [d for d in decisions if d.confidence < 0.5]
            if low_conf_decisions and len(low_conf_decisions) > len(decisions) * 0.3:
                drifts.append(CognitiveDrift(
                    id="low_confidence_decisions",
                    title="Muitas decisões com baixa confiança",
                    description=f"{len(low_conf_decisions)} de {len(decisions)} decisões têm confiança < 0.5.",
                    drift_type="inconsistency",
                    severity="medium",
                ))

            # Detect: domain concentration
            domains = {}
            for e in events:
                d = e.domain.value
                domains[d] = domains.get(d, 0) + 1
            if domains:
                top_domain = max(domains, key=domains.get)
                top_pct = domains[top_domain] / len(events)
                if top_pct > 0.8:
                    drifts.append(CognitiveDrift(
                        id="domain_overconcentration",
                        title=f"Concentração excessiva em '{top_domain}'",
                        description=f"{top_pct*100:.0f}% do conhecimento está em um único domínio.",
                        drift_type="inconsistency",
                        severity="low",
                    ))

        except Exception:
            pass

        return drifts
