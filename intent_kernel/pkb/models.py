"""KnowledgeEvent models — the heart of the PKB."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from intent_kernel.types import (
    Domain,
    EpistemicStatus,
    EventLifecycle,
    EventType,
    ImpactLevel,
    new_id,
    utcnow,
)


@dataclass
class LifecycleTransition:
    """Record of a lifecycle change."""
    from_status: EventLifecycle
    to_status: EventLifecycle
    reason: str
    timestamp: datetime = field(default_factory=utcnow)


@dataclass
class KnowledgeEvent:
    """A single knowledge event in the PKB."""

    # Identity
    id: str = field(default_factory=new_id)
    type: EventType = EventType.EVENT
    domain: Domain = Domain.OTHER

    # Content
    title: str = ""
    content: dict = field(default_factory=dict)
    summary: str = ""

    # Epistemic classification
    confidence: float = 0.5
    epistemic_status: EpistemicStatus = EpistemicStatus.CONCLUSION

    # Lifecycle
    lifecycle: EventLifecycle = EventLifecycle.TRANSIENT
    lifecycle_history: list[LifecycleTransition] = field(default_factory=list)

    # Versioning
    version: int = 1
    parent_event_id: str | None = None
    root_event_id: str | None = None

    # Metadata
    source: str = "system"
    session_id: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # Temporal
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None

    def transition(self, to: EventLifecycle, reason: str = "") -> None:
        """Transition to a new lifecycle status."""
        self.lifecycle_history.append(
            LifecycleTransition(
                from_status=self.lifecycle,
                to_status=to,
                reason=reason,
            )
        )
        self.lifecycle = to
        self.updated_at = utcnow()

    def create_new_version(self, content: dict) -> KnowledgeEvent:
        """Create a new version of this event."""
        return KnowledgeEvent(
            id=new_id(),
            type=self.type,
            domain=self.domain,
            title=self.title,
            content=content,
            summary=self.summary,
            confidence=self.confidence,
            epistemic_status=self.epistemic_status,
            lifecycle=self.lifecycle,
            version=self.version + 1,
            parent_event_id=self.id,
            root_event_id=self.root_event_id or self.id,
            source=self.source,
            session_id=self.session_id,
            tags=list(self.tags),
            metadata=dict(self.metadata),
        )


# ---------------------------------------------------------------------------
# Content Schemas (typed dataclasses for each EventType)
# ---------------------------------------------------------------------------

@dataclass
class DecisionContent:
    """Schema for DECISION events."""
    question: str = ""
    chosen: str = ""
    alternatives: list[str] = field(default_factory=list)
    rationale: str = ""
    constraints: list[str] = field(default_factory=list)
    reversible: bool = True
    impact: ImpactLevel = ImpactLevel.MEDIUM

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "chosen": self.chosen,
            "alternatives": self.alternatives,
            "rationale": self.rationale,
            "constraints": self.constraints,
            "reversible": self.reversible,
            "impact": self.impact.value,
        }


@dataclass
class GoalContent:
    """Schema for GOAL events."""
    description: str = ""
    success_criteria: list[str] = field(default_factory=list)
    deadline: datetime | None = None
    progress: float = 0.0
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "success_criteria": self.success_criteria,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "progress": self.progress,
            "dependencies": self.dependencies,
        }


@dataclass
class ArchitectureContent:
    """Schema for ARCHITECTURE events."""
    decision: str = ""
    alternatives_considered: list[str] = field(default_factory=list)
    chosen_approach: str = ""
    tradeoffs: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "alternatives_considered": self.alternatives_considered,
            "chosen_approach": self.chosen_approach,
            "tradeoffs": self.tradeoffs,
            "related_events": self.related_events,
        }


@dataclass
class MemoryContent:
    """Schema for MEMORY events (user profile data)."""
    category: str = "preference"   # preference / habit / constraint / context
    key: str = ""
    value: object = None
    confidence: float = 0.5
    observation_count: int = 1

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "observation_count": self.observation_count,
        }


@dataclass
class LessonContent:
    """Schema for LESSON events."""
    what: str = ""
    why: str = ""
    context: str = ""
    applicable_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "what": self.what,
            "why": self.why,
            "context": self.context,
            "applicable_to": self.applicable_to,
        }
