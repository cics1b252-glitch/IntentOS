"""Capability & Tool Access Layer Models — RFC-0016 (STUDIO 10.3).

Defines canonical data models for tools, tool statuses, origins, types, permission scopes,
permission decisions, health statuses, candidate rankings, credential references, dry run contracts,
and tool selection traces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from intent_kernel.time_utils import utc_iso


class ToolStatus(str, Enum):
    """Lifecycle and availability status of a tool."""
    DISCOVERED = "DISCOVERED"
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNAUTHORIZED = "UNAUTHORIZED"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"
    UNSUPPORTED = "UNSUPPORTED"


class ToolOrigin(str, Enum):
    """Origin taxonomy for registered tools."""
    BUILT_IN = "BUILT_IN"
    USER_INSTALLED = "USER_INSTALLED"
    SYSTEM_DISCOVERED = "SYSTEM_DISCOVERED"
    PLUGIN = "PLUGIN"
    CONNECTOR = "CONNECTOR"
    LOCAL_APPLICATION = "LOCAL_APPLICATION"
    REMOTE_SERVICE = "REMOTE_SERVICE"
    ENTERPRISE_MANAGED = "ENTERPRISE_MANAGED"


class ToolType(str, Enum):
    """Categorization taxonomy for tools."""
    MEMORY = "MEMORY"
    FILESYSTEM = "FILESYSTEM"
    EMAIL = "EMAIL"
    CALENDAR = "CALENDAR"
    CONTACTS = "CONTACTS"
    BROWSER = "BROWSER"
    SEARCH = "SEARCH"
    DATABASE = "DATABASE"
    API = "API"
    CODE_EXECUTION = "CODE_EXECUTION"
    DOCUMENT = "DOCUMENT"
    SPREADSHEET = "SPREADSHEET"
    MEDIA = "MEDIA"
    DEVICE = "DEVICE"
    OPERATING_SYSTEM = "OPERATING_SYSTEM"
    COMMUNICATION = "COMMUNICATION"
    CUSTOM = "CUSTOM"


class PermissionScope(str, Enum):
    """Persistence boundaries for granted tool permissions."""
    ONCE = "ONCE"
    MISSION = "MISSION"
    SESSION = "SESSION"
    PROJECT = "PROJECT"
    USER = "USER"
    INSTALLATION = "INSTALLATION"
    ORGANIZATION = "ORGANIZATION"


class PermissionDecisionState(str, Enum):
    """Verdict state for permission evaluation."""
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REQUIRES_USER_AUTHORIZATION = "REQUIRES_USER_AUTHORIZATION"
    REQUIRES_ADMIN_AUTHORIZATION = "REQUIRES_ADMIN_AUTHORIZATION"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"


class ToolHealthStatus(str, Enum):
    """Health check state of a tool."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN = "UNKNOWN"


class ToolAuthorizationDecisionState(str, Enum):
    """Verdict returned by ToolAuthorizationGate."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUEST_PERMISSION = "REQUEST_PERMISSION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    WAIT_TOOL = "WAIT_TOOL"
    RESELECT_TOOL = "RESELECT_TOOL"


@dataclass
class CredentialReference:
    """Safe, non-sensitive reference to external credentials."""
    reference_id: str = field(default_factory=lambda: f"cred_ref_{uuid4().hex[:8]}")
    credential_type: str = "OAUTH2"
    provider_family: str = "google"
    scope: str = "calendar.readonly"
    status: str = "VALID"
    created_at: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResource:
    """Canonical model describing a registered tool in the Tool Registry."""
    tool_id: str = field(default_factory=lambda: f"tool_{uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    provider_family: str = "local"
    tool_type: ToolType = ToolType.CUSTOM
    capabilities: List[str] = field(default_factory=list)
    status: ToolStatus = ToolStatus.DISCOVERED
    origin: ToolOrigin = ToolOrigin.BUILT_IN
    version: str = "1.0.0"
    execution_environment_types: List[str] = field(default_factory=lambda: ["local_env"])
    required_permissions: List[str] = field(default_factory=list)
    supported_action_types: List[str] = field(default_factory=lambda: ["READ", "WRITE"])
    risk_profile: str = "low"  # low, medium, high, critical
    side_effect_profile: str = "NONE"  # NONE, LOCAL_REVERSIBLE, LOCAL_IRREVERSIBLE, EXTERNAL_REVERSIBLE, EXTERNAL_IRREVERSIBLE
    supports_dry_run: bool = True
    supports_verification: bool = True
    supports_idempotency: bool = True
    credential_reference_required: bool = False
    credential_reference: Optional[CredentialReference] = None
    health_status: ToolHealthStatus = ToolHealthStatus.UNKNOWN
    last_health_check: str = field(default_factory=utc_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["origin"] = self.origin.value if isinstance(self.origin, Enum) else str(self.origin)
        res["tool_type"] = self.tool_type.value if isinstance(self.tool_type, Enum) else str(self.tool_type)
        res["health_status"] = self.health_status.value if isinstance(self.health_status, Enum) else str(self.health_status)
        if self.credential_reference:
            res["credential_reference"] = self.credential_reference.to_dict()
        return res


@dataclass
class CapabilityToolMapping:
    """Mapping between an abstract capability and eligible candidate tool IDs."""
    capability: str = ""
    tool_ids: List[str] = field(default_factory=list)
    default_tool_id: Optional[str] = None
    updated_at: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCandidate:
    """Evaluated tool candidate ranked for capability execution."""
    tool_id: str = ""
    capability: str = ""
    eligibility: bool = True
    authorization_status: PermissionDecisionState = PermissionDecisionState.GRANTED
    health: ToolHealthStatus = ToolHealthStatus.HEALTHY
    environment_match: bool = True
    permission_match: bool = True
    risk_score: float = 0.1
    cost_score: float = 0.0
    latency_score: float = 0.1
    verification_support: bool = True
    idempotency_support: bool = True
    selection_score: float = 1.0
    reason: str = "Optimal candidate match"

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["authorization_status"] = self.authorization_status.value if isinstance(self.authorization_status, Enum) else str(self.authorization_status)
        res["health"] = self.health.value if isinstance(self.health, Enum) else str(self.health)
        return res


@dataclass
class PermissionDecision:
    """Result of a tool permission authorization evaluation."""
    permission_id: str = field(default_factory=lambda: f"perm_dec_{uuid4().hex[:8]}")
    tool_id: str = ""
    permission: str = ""
    state: PermissionDecisionState = PermissionDecisionState.NOT_CONFIGURED
    scope: PermissionScope = PermissionScope.MISSION
    project_id: str = "GLOBAL"
    reason: str = ""
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["state"] = self.state.value if isinstance(self.state, Enum) else str(self.state)
        res["scope"] = self.scope.value if isinstance(self.scope, Enum) else str(self.scope)
        return res


@dataclass
class DryRunRequest:
    """Contract requesting a dry run preview of an action without executing side-effects."""
    tool_id: str = ""
    capability: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    project_id: str = "GLOBAL"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DryRunResult:
    """Structured response from a tool dry run simulation."""
    tool_id: str = ""
    capability: str = ""
    intended_action: str = ""
    affected_resource: str = ""
    expected_effect: str = ""
    required_permissions: List[str] = field(default_factory=list)
    risk_level: str = "low"
    reversibility: bool = True
    confirmation_required: bool = False
    simulated_output: Any = None
    executed: bool = False  # Always False for dry run!

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolSelectionTrace:
    """Auditable trace of tool routing and selection decisions."""
    trace_id: str = field(default_factory=lambda: f"tl_trc_{uuid4().hex[:8]}")
    requested_capability: str = ""
    project_id: str = "GLOBAL"
    candidate_count: int = 0
    selected_tool_id: Optional[str] = None
    rejected_tool_ids: List[str] = field(default_factory=list)
    reason: str = ""
    permission_decision: str = ""
    health_status: str = ""
    timestamp: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
