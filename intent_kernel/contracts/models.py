"""Infrastructure-independent canonical contracts for Intent OS v2.0.

These models intentionally coexist with the legacy types during migration.
They contain no FastAPI, provider SDK, persistence, or UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class MissionId:
    """Stable, validated identity for a mission."""

    value: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        UUID(self.value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AgentId:
    """Stable logical identity for a registered agent."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("AgentId cannot be empty")

    def __str__(self) -> str:
        return self.value


class MissionStatus(str, Enum):
    CREATED = "created"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    WAITING_FOR_INFORMATION = "waiting_for_information"
    WAITING_FOR_DECISION = "waiting_for_decision"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED_RECOVERABLE = "failed_recoverable"
    FAILED_FINAL = "failed_final"


class Domain(str, Enum):
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


class IntentMode(str, Enum):
    QUICK = "quick"
    BASIC = "basic"
    DETAIL = "detail"
    EXPERT = "expert"
    ARCHITECT = "architect"


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    MISSING_INFORMATION = "missing_information"
    DECISION_REQUIRED = "decision_required"
    PERMISSION_REQUIRED = "permission_required"
    POLICY_DENIED = "policy_denied"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    PERSISTENCE_FAILURE = "persistence_failure"
    EXECUTION_FAILURE = "execution_failure"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class EffectType(str, Enum):
    READ = "read"
    COMPUTE = "compute"
    GENERATE = "generate"
    PERSIST = "persist"
    EXTERNAL_CHANGE = "external_change"
    IRREVERSIBLE = "irreversible"


@dataclass(slots=True)
class MissionContext:
    session_id: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    actor: str = "user"
    domain: Domain = Domain.OTHER
    mode: IntentMode = IntentMode.BASIC
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Mission:
    objective: str
    id: MissionId = field(default_factory=MissionId)
    status: MissionStatus = MissionStatus.CREATED
    context: MissionContext = field(default_factory=MissionContext)
    success_criteria: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0
    blockers: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    schema_version: str = "2.0"


@dataclass(slots=True)
class MissionResult:
    mission_id: MissionId
    status: MissionStatus
    output: str = ""
    success: bool = False
    error_code: ErrorCode | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str = ""
    version: str = "1.0"
    domains: tuple[Domain, ...] = ()
    tags: tuple[str, ...] = ()
    requires_network: bool = False
    requirements: tuple[str, ...] = ()
    effect: EffectType = EffectType.COMPUTE
    requires_confirmation: bool = False


@dataclass(slots=True)
class CapabilityResult:
    capability: str
    success: bool
    output: Any = None
    confidence: float = 0.0
    error_code: ErrorCode | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityRequest:
    """Canonical request sent by the Capability Router to a Core App."""

    mission: Mission
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentLimits:
    timeout_seconds: float = 30.0
    max_output_chars: int = 20_000
    max_attempts: int = 1


@dataclass(slots=True)
class AgentRequest:
    mission: Mission
    capability: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    limits: AgentLimits = field(default_factory=AgentLimits)


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: str
    content: str


@dataclass(slots=True)
class ProviderRequest:
    messages: list[ProviderMessage]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    required_capabilities: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"
    error_code: ErrorCode | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeLifecycle(str, Enum):
    OBSERVED = "observed"
    TRANSIENT = "transient"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    CONSTITUTIONAL = "constitutional"
    ARCHIVED = "archived"
    MERGED = "merged"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


@dataclass(slots=True)
class KnowledgeEvent:
    event_type: str
    title: str
    content: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    domain: Domain = Domain.OTHER
    summary: str = ""
    confidence: float = 0.5
    epistemic_status: str = "conclusion"
    lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.OBSERVED
    source: str = "system"
    mission_id: MissionId | None = None
    session_id: str = ""
    correlation_id: str = ""
    relations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    lifecycle_history: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    parent_event_id: str | None = None
    root_event_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    schema_version: str = "2.0"


class ConstitutionDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_CONDITIONS = "allow_with_conditions"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DEFER = "defer"
    DENY = "deny"


@dataclass(slots=True)
class ConstitutionVerdict:
    decision: ConstitutionDecision
    reason: str = ""
    code: str = ""
    violated_rule: str | None = None
    conditions: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    constitution_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision in {
            ConstitutionDecision.ALLOW,
            ConstitutionDecision.ALLOW_WITH_CONDITIONS,
        }
