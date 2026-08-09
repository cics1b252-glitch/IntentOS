"""The single official Curator for canonical KnowledgeEvents."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from intent_kernel.contracts import (
    ConstitutionVerdict,
    KnowledgeEvent,
    KnowledgeLifecycle,
)
from intent_kernel.pkb.score import (
    KnowledgeScore,
    KnowledgeScoreBreakdown,
    KnowledgeScoreCalculator,
)
from intent_kernel.types import utcnow


class CurationAction(str, Enum):
    DISCARD = "discard"
    CANDIDATE = "candidate"
    APPROVE = "approve"
    MERGE = "merge"
    CONFLICT = "conflict"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class KnowledgeAuditEntry:
    event_id: str
    action: CurationAction
    reason: str
    score: float
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())
    session_id: str = ""
    conflict_with: str | None = None


@dataclass(slots=True)
class CurationDecision:
    event: KnowledgeEvent
    action: CurationAction
    lifecycle: KnowledgeLifecycle
    score: KnowledgeScore
    audit: KnowledgeAuditEntry
    existing_event: KnowledgeEvent | None = None


class CanonicalKnowledgeCurator:
    """Combines v1 lifecycle compatibility with v2 score/conflict rules."""

    def __init__(
        self,
        score_calculator: KnowledgeScoreCalculator | None = None,
        *,
        enforce_nonempty: bool = False,
    ):
        self.score_calculator = (
            score_calculator or KnowledgeScoreCalculator()
        )
        self.enforce_nonempty = enforce_nonempty

    async def curate(
        self,
        event: KnowledgeEvent,
        existing_events: list[KnowledgeEvent] | None = None,
        verdict: ConstitutionVerdict | None = None,
    ) -> CurationDecision:
        existing = existing_events or []
        score = self.score_calculator.build_score(
            self._score_breakdown(event)
        )

        if verdict is not None and not verdict.allowed:
            return self._decision(
                event,
                CurationAction.REJECT,
                KnowledgeLifecycle.REJECTED,
                score,
                f"Constitution denied: {verdict.reason}",
            )

        if self.enforce_nonempty and not event.title and not event.summary:
            return self._decision(
                event,
                CurationAction.REJECT,
                KnowledgeLifecycle.REJECTED,
                score,
                "Event has no title or summary",
            )

        duplicate = self._find_duplicate(event, existing)
        conflict = self._find_conflict(event, existing)

        if event.event_type.lower() == "correction" and conflict:
            return self._decision(
                event,
                CurationAction.MERGE,
                conflict.lifecycle,
                score,
                f"Correction merges with {conflict.id}",
                conflict,
            )

        if conflict:
            return self._decision(
                event,
                CurationAction.CONFLICT,
                KnowledgeLifecycle.CANDIDATE,
                score,
                f"Conflicts with {conflict.id}",
                conflict,
            )

        if event.event_type.lower() == "memory":
            return self._decision(
                event,
                CurationAction.APPROVE,
                KnowledgeLifecycle.APPROVED,
                score,
                "Memory events are retained",
            )

        if duplicate:
            return self._decision(
                event,
                CurationAction.CANDIDATE,
                KnowledgeLifecycle.CANDIDATE,
                score,
                f"Duplicate candidate for {duplicate.id}",
                duplicate,
            )

        if isinstance(event.metadata.get("score_breakdown"), dict):
            target = self.score_calculator.get_target_level(score.value)
            if target == "DISCARD":
                action = CurationAction.DISCARD
                lifecycle = KnowledgeLifecycle.TRANSIENT
            elif target == "CANDIDATE":
                action = CurationAction.CANDIDATE
                lifecycle = KnowledgeLifecycle.CANDIDATE
            elif target == "CONSTITUTIONAL":
                action = CurationAction.APPROVE
                lifecycle = KnowledgeLifecycle.CONSTITUTIONAL
            else:
                action = CurationAction.APPROVE
                lifecycle = KnowledgeLifecycle.APPROVED
            return self._decision(
                event,
                action,
                lifecycle,
                score,
                f"Explicit score {score.value} maps to {target}",
            )

        # Compatibility thresholds are deliberately the characterized v1
        # boundaries. Score is canonical evidence, not a behavior change.
        if score.value < 30:
            return self._decision(
                event,
                CurationAction.DISCARD,
                KnowledgeLifecycle.TRANSIENT,
                score,
                f"Score {score.value} below retention threshold",
            )
        if score.value < 60:
            return self._decision(
                event,
                CurationAction.CANDIDATE,
                KnowledgeLifecycle.CANDIDATE,
                score,
                f"Score {score.value} requires confirmation",
            )
        return self._decision(
            event,
            CurationAction.APPROVE,
            KnowledgeLifecycle.APPROVED,
            score,
            f"Score {score.value} meets approval threshold",
        )

    async def should_promote(self, event: KnowledgeEvent) -> bool:
        return (
            event.confidence >= 0.5
            or event.event_type.lower() in {"decision", "goal"}
        )

    async def should_archive(self, event: KnowledgeEvent) -> bool:
        return False

    def _score_breakdown(
        self,
        event: KnowledgeEvent,
    ) -> KnowledgeScoreBreakdown:
        supplied = event.metadata.get("score_breakdown")
        if isinstance(supplied, dict):
            return KnowledgeScoreBreakdown(
                relevance=float(supplied.get("relevance", 0)),
                persistence=float(supplied.get("persistence", 0)),
                reuse=float(supplied.get("reuse", 0)),
                impact=float(supplied.get("impact", 0)),
                goalAlignment=float(
                    supplied.get(
                        "goalAlignment",
                        supplied.get("goal_alignment", 0),
                    )
                ),
            )
        compatible = event.confidence * 100
        return KnowledgeScoreBreakdown(
            relevance=compatible,
            persistence=compatible,
            reuse=compatible,
            impact=compatible,
            goalAlignment=compatible,
        )

    @staticmethod
    def _find_duplicate(
        event: KnowledgeEvent,
        existing: list[KnowledgeEvent],
    ) -> KnowledgeEvent | None:
        for candidate in existing:
            if (
                candidate.event_type == event.event_type
                and candidate.domain == event.domain
                and candidate.title == event.title
            ):
                return candidate
        return None

    def _find_conflict(
        self,
        event: KnowledgeEvent,
        existing: list[KnowledgeEvent],
    ) -> KnowledgeEvent | None:
        if event.event_type.lower() not in {"fact", "correction"}:
            return None
        normalized = self._normalize_content(event.content)
        for candidate in existing:
            if candidate.id == event.id:
                continue
            if candidate.domain != event.domain:
                continue
            if candidate.event_type.lower() not in {"fact", "correction"}:
                continue
            if candidate.title == event.title:
                # Exact v1 duplicate handling takes precedence.
                continue
            if self._normalize_content(candidate.content) != normalized:
                return candidate
        return None

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, dict):
            value = content.get("normalized", content.get("raw", content))
        else:
            value = content
        return str(value).lower().strip()

    @staticmethod
    def _decision(
        event: KnowledgeEvent,
        action: CurationAction,
        lifecycle: KnowledgeLifecycle,
        score: KnowledgeScore,
        reason: str,
        existing: KnowledgeEvent | None = None,
    ) -> CurationDecision:
        audit = KnowledgeAuditEntry(
            event_id=event.id,
            action=action,
            reason=reason,
            score=score.value,
            session_id=event.session_id,
            conflict_with=existing.id if existing else None,
        )
        return CurationDecision(
            event=event,
            action=action,
            lifecycle=lifecycle,
            score=score,
            audit=audit,
            existing_event=existing,
        )
