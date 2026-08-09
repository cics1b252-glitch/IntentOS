"""Intent OS Kernel — Base Types.

All fundamental types used across the Kernel. No external dependencies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Mode(str, Enum):
    """Processing mode — determines pipeline path and depth."""
    QUICK = "quick"
    BASIC = "basic"
    DETAIL = "detail"
    EXPERT = "expert"
    ARCHITECT = "architect"


class Domain(str, Enum):
    """Task domain classification."""
    WRITING = "writing"
    PROGRAMMING = "programming"
    RESEARCH = "research"
    PLANNING = "planning"
    BUSINESS = "business"
    MARKETING = "marketing"
    DATA = "data"
    ENGINEERING = "engineering"
    FINANCE = "finance"
    EDUCATION = "education"
    CREATIVITY = "creativity"
    LEGAL = "legal"
    LIFE = "life"
    OTHER = "other"


class EpistemicStatus(str, Enum):
    """Epistemic classification of output — Pillar II (Verdade)."""
    FACT = "fact"
    ESTIMATE = "estimate"
    CONCLUSION = "conclusion"
    ASSUMPTION = "assumption"
    DK = "dk"  # Don't Know


class Severity(str, Enum):
    """Constraint severity level."""
    BLOCK = "block"
    WARN = "warn"


class EventType(str, Enum):
    """Type of KnowledgeEvent."""
    DECISION = "decision"
    STRATEGY = "strategy"
    FACT = "fact"
    INSIGHT = "insight"
    LESSON = "lesson"
    REQUIREMENT = "requirement"
    GOAL = "goal"
    MISSION = "mission"
    PARAMETER = "parameter"
    RFC = "rfc"
    ARCHITECTURE = "architecture"
    DOCUMENT = "document"
    ARTIFACT = "artifact"
    PLUGIN = "plugin"
    MEMORY = "memory"
    EVENT = "event"


class EventLifecycle(str, Enum):
    """Lifecycle stage of a KnowledgeEvent."""
    TRANSIENT = "transient"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    CONSTITUTIONAL = "constitutional"


class ImpactLevel(str, Enum):
    """Impact level for decisions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    """Generate a new UUID v4."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Current UTC time."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Core Data Classes
# ---------------------------------------------------------------------------

@dataclass
class UserProfile:
    """Dynamic user profile — inferred during conversation."""
    risk_tolerance: str = "medium"          # low / medium / high
    depth_preference: str = "auto"          # brief / auto / deep
    recurring_domains: list[str] = field(default_factory=list)
    temporal_horizon: str = "medium"        # short / medium / long
    decision_style: str = "balanced"        # conservative / balanced / aggressive


@dataclass
class IntentInput:
    """Input to the Kernel — what the user wants."""
    text: str
    context: dict[str, Any] = field(default_factory=dict)
    user_profile: UserProfile | None = None
    session_id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=utcnow)
    domain: Domain = Domain.OTHER  # set by IntentEngine after parsing


@dataclass
class ParsedIntent:
    """Result of intent parsing — classified and structured."""
    raw_text: str
    intent: str
    domain: Domain
    mode: Mode
    entities: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)


@dataclass
class IntentOutput:
    """Output from the Kernel — the response."""
    text: str
    mode: Mode
    domain: Domain
    confidence: float
    epistemic_status: EpistemicStatus
    alternatives: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    events: list[KnowledgeEvent] = field(default_factory=list)
    reasoning: str | None = None


# Forward reference for KnowledgeEvent (defined in pkb/models.py)
# We import it at runtime; this is just for type checking.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from intent_kernel.pkb.models import KnowledgeEvent


@dataclass
class CompletionResult:
    """Result from an LLM provider."""
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


@dataclass
class Message:
    """A message in a conversation (for LLM providers)."""
    role: str            # "system" | "user" | "assistant"
    content: str


@dataclass
class Action:
    """An action to validate against the Constitution."""
    type: str            # "process" | "install_module" | "access_data" | etc.
    data: Any = None


@dataclass
class ConstitutionVerdict:
    """Result of Constitution validation."""
    allowed: bool
    violated_constraint: str | None = None
    reason: str | None = None


@dataclass
class PipelineNode:
    """A node in the processing pipeline DAG."""
    name: str
    fn: Any              # Callable[[PipelineContext], Awaitable[PipelineContext]]


@dataclass
class PipelineContext:
    """Context passed through pipeline nodes."""
    intent: ParsedIntent
    mode: Mode
    data: dict[str, Any] = field(default_factory=dict)
    output_text: str = ""
    events: list[Any] = field(default_factory=list)
    confidence: float = 0.0
    epistemic_status: EpistemicStatus = EpistemicStatus.CONCLUSION


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    context: PipelineContext
    output_text: str
    mode: Mode
    domain: Domain
    confidence: float
    epistemic_status: EpistemicStatus
    events: list[Any] = field(default_factory=list)


@dataclass
class VersionSnapshot:
    """Snapshot of an event at a point in time."""
    id: str = field(default_factory=new_id)
    event_id: str = ""
    version: int = 1
    content: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    reason: str = "snapshot"


@dataclass
class IngestResult:
    """Result of ingesting events into the PKB."""
    total: int = 0
    approved: int = 0
    candidate: int = 0
    transient: int = 0
    rejected: int = 0
    event_ids: list[str] = field(default_factory=list)


@dataclass
class QueryFilters:
    """Filters for querying the PKB."""
    domain: Domain | None = None
    event_type: EventType | None = None
    lifecycle: EventLifecycle | None = None
    tags: list[str] | None = None
    since: datetime | None = None
    until: datetime | None = None
    min_confidence: float | None = None
    source: str | None = None
    search_text: str | None = None
    limit: int = 100
    offset: int = 0
    sort_by: str = "created_at"
    sort_order: str = "desc"
