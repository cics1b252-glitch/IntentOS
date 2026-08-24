"""Mission Runtime Models — RFC-0015 (STUDIO 10.2).

Defines canonical data models for Mission Runtime states, node states, action contracts,
side-effect classifications, confirmation requests, checkpoints, traces, and execution reports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from intent_kernel.time_utils import utc_iso


class MissionRuntimeState(str, Enum):
    """Execution state transitions for MissionRuntimeInstance."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    WAITING_USER_CONFIRMATION = "WAITING_USER_CONFIRMATION"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    WAITING_VERIFICATION = "WAITING_VERIFICATION"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RuntimeNodeState(str, Enum):
    """Execution state transitions for individual execution graph nodes."""
    PENDING = "PENDING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    WAITING_VERIFICATION = "WAITING_VERIFICATION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class SideEffectLevel(str, Enum):
    """Side-effect impact classification for actions."""
    NONE = "NONE"
    LOCAL_REVERSIBLE = "LOCAL_REVERSIBLE"
    LOCAL_IRREVERSIBLE = "LOCAL_IRREVERSIBLE"
    EXTERNAL_REVERSIBLE = "EXTERNAL_REVERSIBLE"
    EXTERNAL_IRREVERSIBLE = "EXTERNAL_IRREVERSIBLE"


class ActionGateDecision(str, Enum):
    """Decision produced by ActionGate prior to node execution."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    WAIT_RESOURCE = "WAIT_RESOURCE"
    REORCHESTRATE = "REORCHESTRATE"
    ABORT = "ABORT"


class ConfirmationState(str, Enum):
    """Typed lifecycle of a user confirmation requirement (Movement 14).

    Explicit typed states are required so that ``WAITING_CONFIRMATION`` is
    distinguishable from ``CONFIRMED``, ``REJECTED``, ``EXPIRED``, ``STALE``
    (invalidated) and ``CONSUMED`` (already applied). No lexical shortcut may
    bypass these states.
    """
    NO_CONFIRMATION_REQUIRED = "NO_CONFIRMATION_REQUIRED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    STALE = "STALE"
    CONSUMED = "CONSUMED"


class FailureCategory(str, Enum):
    """Taxonomy of runtime node and mission execution failures."""
    TRANSIENT = "TRANSIENT"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    POLICY_BLOCK = "POLICY_BLOCK"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    TIMEOUT = "TIMEOUT"
    USER_DENIED = "USER_DENIED"
    CANCELLED = "CANCELLED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class VerificationStatus(str, Enum):
    """Status of action result verification."""
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"
    REQUIRES_USER_VERIFICATION = "REQUIRES_USER_VERIFICATION"


@dataclass
class ActionContract:
    """Canonical contract describing a requested action before execution."""
    action_id: str = field(default_factory=lambda: f"act_{uuid4().hex[:8]}")
    capability: str = "test.echo"
    action_type: str = "READ"
    inputs_reference: Dict[str, Any] = field(default_factory=dict)
    expected_output: Any = None
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    reversibility: bool = True
    risk_level: str = "low"  # low, medium, high, critical
    required_permissions: List[str] = field(default_factory=list)
    confirmation_required: bool = False
    verification_required: bool = True
    verification_type: Optional[str] = None  # "EXACT" | "STRUCTURAL" | None (defaults EXACT)
    verification_schema: Optional[Dict[str, Any]] = None  # structural contract for STRUCTURAL mode
    timeout: float = 30.0
    retry_policy: Dict[str, Any] = field(default_factory=lambda: {"max_attempts": 3, "backoff": "exponential"})
    idempotency_key: str = field(default_factory=lambda: f"idemp_{uuid4().hex[:8]}")
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def inputs(self) -> Dict[str, Any]:
        return self.inputs_reference

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["side_effect_level"] = self.side_effect_level.value if isinstance(self.side_effect_level, Enum) else str(self.side_effect_level)
        return res


@dataclass
class ExecutionConfirmationRequest:
    """Canonical request for user approval of side-effecting or sensitive actions."""
    confirmation_id: str = field(default_factory=lambda: f"conf_{uuid4().hex[:8]}")
    mission_id: str = ""
    action_id: str = ""
    description: str = ""
    effect: str = ""
    reversibility: bool = False
    risk_level: str = "high"
    expires_at: Optional[str] = None
    approved: Optional[bool] = None
    approved_at: Optional[str] = None
    state: ConfirmationState = ConfirmationState.WAITING_CONFIRMATION
    runtime_id: str = ""
    confirmation_token: str = ""
    session_id: str = ""
    project_id: str = "GLOBAL"
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeNode:
    """Runtime tracking model for a node in the execution graph."""
    node_id: str = field(default_factory=lambda: f"node_{uuid4().hex[:8]}")
    capability: str = "test.echo"
    state: RuntimeNodeState = RuntimeNodeState.PENDING
    agent_id: str = "agent_default"
    provider_id: str = "local"
    account_id: str = "default"
    environment_id: str = "local_env"
    dependencies: List[str] = field(default_factory=list)
    action_contract: Optional[ActionContract] = None
    result: Any = None
    verification_result: Optional[VerificationStatus] = None
    attempt_count: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["state"] = self.state.value if isinstance(self.state, Enum) else str(self.state)
        res["verification_result"] = self.verification_result.value if isinstance(self.verification_result, Enum) else str(self.verification_result) if self.verification_result else None
        return res


@dataclass
class MissionCheckpoint:
    """Snapshot of Mission Runtime state for persistence, pause, and resume."""
    checkpoint_id: str = field(default_factory=lambda: f"chk_{uuid4().hex[:8]}")
    runtime_id: str = ""
    mission_id: str = ""
    timestamp: str = field(default_factory=utc_iso)
    runtime_status: MissionRuntimeState = MissionRuntimeState.RUNNING
    completed_nodes: List[str] = field(default_factory=list)
    pending_nodes: List[str] = field(default_factory=list)
    failed_nodes: List[str] = field(default_factory=list)
    results_reference: Dict[str, Any] = field(default_factory=dict)
    verification_state: Dict[str, Any] = field(default_factory=dict)
    completion_evidence: List[Dict[str, Any]] = field(default_factory=list)  # H1.4
    retry_state: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["runtime_status"] = self.runtime_status.value if isinstance(self.runtime_status, Enum) else str(self.runtime_status)
        return res


@dataclass
class RuntimeTraceRecord:
    """Auditable trace record of execution events within Mission Runtime."""
    record_id: str = field(default_factory=lambda: f"trc_{uuid4().hex[:8]}")
    runtime_id: str = ""
    mission_id: str = ""
    node_id: str = ""
    action: str = ""
    state_before: str = ""
    state_after: str = ""
    timestamp: str = field(default_factory=utc_iso)
    duration: float = 0.0
    result_status: str = ""
    verification_status: str = ""
    evidence_reference: Optional[str] = None
    correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FailureReport:
    """Canonical failure report produced by Mission Runtime for ECC consumption."""
    report_id: str = field(default_factory=lambda: f"fail_{uuid4().hex[:8]}")
    runtime_id: str = ""
    mission_id: str = ""
    node_id: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN_FAILURE
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    timestamp: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["category"] = self.category.value if isinstance(self.category, Enum) else str(self.category)
        return res


@dataclass
class MissionRuntimeInstance:
    """Active instance of Mission Runtime managing graph execution."""
    runtime_id: str = field(default_factory=lambda: f"mr_{uuid4().hex[:8]}")
    mission_id: str = ""
    execution_graph_id: str = ""
    project_id: str = "GLOBAL"
    status: MissionRuntimeState = MissionRuntimeState.CREATED
    nodes: Dict[str, RuntimeNode] = field(default_factory=dict)
    completed_nodes: List[str] = field(default_factory=list)
    failed_nodes: List[str] = field(default_factory=list)
    blocked_nodes: List[str] = field(default_factory=list)
    pending_nodes: List[str] = field(default_factory=list)
    checkpoint_id: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=utc_iso)
    completed_at: Optional[str] = None
    execution_policy: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: f"corr_{uuid4().hex[:8]}")
    retry_count: int = 0
    recovery_count: int = 0
    verification_status: VerificationStatus = VerificationStatus.INCONCLUSIVE
    completion_evidence: List[Dict[str, Any]] = field(default_factory=list)
    completion_authority: Optional[str] = None
    lifecycle_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["nodes"] = {k: v.to_dict() for k, v in self.nodes.items()}
        res["verification_status"] = self.verification_status.value if isinstance(self.verification_status, Enum) else str(self.verification_status)
        return res
