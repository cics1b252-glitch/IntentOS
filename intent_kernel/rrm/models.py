"""Registry & Resource Manager (RRM) — Canonical Resource Models (RFC-0013).

Defines the canonical data structures for Providers, Accounts, Execution Environments,
Capabilities, Agents, and Projects within Intent OS.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from intent_kernel.rrm.generation import LEGACY_UNVERSIONED, normalize_for_restore
from intent_kernel.time_utils import utc_iso


class ResourceType(str, Enum):
    """Supported canonical resource entity types in RRM."""
    PROVIDER = "provider"
    ACCOUNT = "account"
    EXECUTION_ENVIRONMENT = "execution_environment"
    CAPABILITY = "capability"
    AGENT = "agent"
    PROJECT = "project"


class ResourceStatus(str, Enum):
    """Lifecycle and operational status for RRM registered resources."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    THROTTLED = "throttled"
    EXHAUSTED = "exhausted"
    ARCHIVED = "archived"
    DRAFT = "draft"
    UNCONFIGURED = "unconfigured"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


class ResourceOrigin(str, Enum):
    """Explicit origin and provenance tracking for registered resources."""
    TEMPLATE = "template"
    CONFIGURATION = "configuration"
    HOST_DISCOVERY = "host_discovery"
    PROVIDER_DISCOVERY = "provider_discovery"
    USER_REGISTRATION = "user_registration"
    ORGANIZATION_POLICY = "organization_policy"
    MIGRATION = "migration"


class AvailabilitySource(str, Enum):
    """Source mechanism verifying operational availability of a resource."""
    HEALTH_CHECK = "health_check"
    CONFIGURATION = "configuration"
    RUNTIME_DISCOVERY = "runtime_discovery"
    UNKNOWN = "unknown"


class AgentInstallationState(str, Enum):
    """Lifecycle installation states for Agents in RRM."""
    DEFINED = "defined"
    INSTALLED = "installed"
    ENABLED = "enabled"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ExecutionEnvironmentType(str, Enum):
    """Supported types of execution environments."""
    LOCAL_PROCESS = "local_process"
    DESKTOP = "desktop"
    BROWSER = "browser"
    MOBILE = "mobile"
    SERVER = "server"
    CLOUD = "cloud"
    EDGE = "edge"
    REMOTE = "remote"


# --- Canonical Resource Entity Data Contracts ---

@dataclass
class ProviderResource:
    """Canonical AI Provider Profile resource."""
    provider_id: str
    name: str
    reasoning_score: float = 0.85  # 0.0 to 1.0
    tool_use_support: bool = True
    context_window: int = 128000
    cost_per_1k_tokens: float = 0.002
    privacy_tier: str = "standard"  # "standard", "high", "airgapped"
    availability: float = 1.0  # 0.0 to 1.0
    multimodal: bool = False
    status: ResourceStatus = ResourceStatus.ACTIVE
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_configured: bool = True
    has_active_account: bool = True
    endpoint_url: Optional[str] = None
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Determines if provider is eligible for execution selection."""
        if self.is_template or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        if self.status != ResourceStatus.ACTIVE:
            return False
        return self.is_configured and self.has_active_account

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProviderResource:
        d = dict(data)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


@dataclass
class AccountResource:
    """Canonical Service Account descriptor resource."""
    account_id: str
    provider_id: str
    name: str
    quota_remaining: float = 100000.0
    rate_limit_rpm: int = 1000
    rate_limit_tpm: int = 100000
    priority: int = 5  # 1 (low) to 10 (high)
    cost_multiplier: float = 1.0
    status: ResourceStatus = ResourceStatus.ACTIVE
    secret_reference: Optional[str] = "configured_secret"
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_configured: bool = True
    allowed_policies: List[str] = field(default_factory=list)
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Determines if account is eligible for provider routing."""
        if self.is_template or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        if self.status != ResourceStatus.ACTIVE:
            return False
        return bool(self.secret_reference) and self.is_configured

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AccountResource:
        d = dict(data)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


@dataclass
class ExecutionEnvironmentResource:
    """Canonical Execution Environment descriptor resource."""
    environment_id: str
    type: ExecutionEnvironmentType = ExecutionEnvironmentType.LOCAL_PROCESS
    status: ResourceStatus = ResourceStatus.ACTIVE
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_discovered: bool = True
    capabilities: List[str] = field(default_factory=list)
    available_tools: List[str] = field(default_factory=list)
    network_access: bool = True
    privacy_level: str = "standard"  # "standard", "high", "airgapped"
    latency_class: str = "low"  # "ultra_low", "low", "medium", "high"
    cost_class: str = "free"  # "free", "low", "medium", "high"
    resource_limits: Dict[str, Any] = field(default_factory=dict)
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Determines if execution environment is eligible for execution dispatch."""
        if self.is_template or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        if self.status != ResourceStatus.ACTIVE:
            return False
        return self.is_discovered

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["type"] = self.type.value if isinstance(self.type, Enum) else str(self.type)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionEnvironmentResource:
        d = dict(data)
        if "type" in d and isinstance(d["type"], str):
            d["type"] = ExecutionEnvironmentType(d["type"])
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


@dataclass
class CapabilityResource:
    """Canonical Capability descriptor resource."""
    capability_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    provided_by_agents: List[str] = field(default_factory=list)
    effect: str = "compute"  # "read", "compute", "generate", "persist", "external_change", "irreversible"
    requires_network: bool = False
    requires_confirmation: bool = False
    status: ResourceStatus = ResourceStatus.ACTIVE
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_executable: bool = True
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Capability is eligible/executable if active and backed by an executable executor."""
        if self.is_template or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        if self.status != ResourceStatus.ACTIVE:
            return False
        return self.is_executable

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityResource:
        d = dict(data)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


@dataclass
class AgentResource:
    """Canonical Agent descriptor resource."""
    agent_id: str
    name: str
    capabilities: List[str] = field(default_factory=list)
    specialization: List[str] = field(default_factory=list)
    availability: float = 1.0  # 0.0 to 1.0
    status: ResourceStatus = ResourceStatus.ACTIVE
    installation_state: AgentInstallationState = AgentInstallationState.INSTALLED
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_enabled: bool = True
    version: str = "1.0.0"
    historical_confidence: float = 0.90  # 0.0 to 1.0
    cost_tier: float = 0.01  # Normalized cost metric
    latency_tier: float = 0.2  # Normalized latency in seconds
    supported_domains: List[str] = field(default_factory=list)
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Agent is eligible if installed, enabled, active, and not a bare template."""
        if self.is_template or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        if self.status != ResourceStatus.ACTIVE or not self.is_enabled:
            return False
        valid_states = (
            AgentInstallationState.INSTALLED,
            AgentInstallationState.ENABLED,
            AgentInstallationState.AVAILABLE,
        )
        return self.installation_state in valid_states

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["installation_state"] = self.installation_state.value if isinstance(self.installation_state, Enum) else str(self.installation_state)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentResource:
        d = dict(data)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "installation_state" in d and isinstance(d["installation_state"], str):
            d["installation_state"] = AgentInstallationState(d["installation_state"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


@dataclass
class ProjectResource:
    """Canonical Project workspace & domain definition resource."""
    project_id: str
    name: str
    domain: str = "general"
    description: str = ""
    owner_id: str = "user_primary"
    status: ResourceStatus = ResourceStatus.ACTIVE
    resource_origin: ResourceOrigin = ResourceOrigin.USER_REGISTRATION
    availability_source: AvailabilitySource = AvailabilitySource.UNKNOWN
    is_template: bool = False
    is_demo: bool = False
    retention_class: str = "permanent"  # "permanent", "episodic", "temporary"
    access_scope: str = "project"  # "private", "project", "organization", "public"
    assigned_agents: List[str] = field(default_factory=list)
    assigned_environments: List[str] = field(default_factory=list)
    budget_limit: float = 1000.0
    consumed_budget: float = 0.0
    governed_registration_id: str = ""
    generation: int = LEGACY_UNVERSIONED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def is_eligible(self) -> bool:
        """Project is eligible if active, not template/demo."""
        if self.is_template or self.is_demo or self.resource_origin == ResourceOrigin.TEMPLATE:
            return False
        return self.status == ResourceStatus.ACTIVE

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        res["resource_origin"] = self.resource_origin.value if isinstance(self.resource_origin, Enum) else str(self.resource_origin)
        res["availability_source"] = self.availability_source.value if isinstance(self.availability_source, Enum) else str(self.availability_source)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectResource:
        d = dict(data)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = ResourceStatus(d["status"])
        if "resource_origin" in d and isinstance(d["resource_origin"], str):
            d["resource_origin"] = ResourceOrigin(d["resource_origin"])
        if "availability_source" in d and isinstance(d["availability_source"], str):
            d["availability_source"] = AvailabilitySource(d["availability_source"])
        d.setdefault("governed_registration_id", "")
        d["generation"] = normalize_for_restore(d.get("generation", LEGACY_UNVERSIONED))
        return cls(**d)


# --- Query & Health Filter Contracts ---

@dataclass
class ResourceQueryFilter:
    """Canonical query filter for multi-criteria resource discovery across RRM."""
    resource_type: Optional[ResourceType] = None
    status: Optional[ResourceStatus] = None
    domain: Optional[str] = None
    capability: Optional[str] = None
    provider_id: Optional[str] = None
    privacy_level: Optional[str] = None
    min_confidence: Optional[float] = None
    max_cost_tier: Optional[float] = None
    required_tags: List[str] = field(default_factory=list)
    text_search: Optional[str] = None
    only_eligible: bool = False
    include_templates: bool = True
    origin: Optional[ResourceOrigin] = None

    def matches(self, resource_type: ResourceType, obj: Any) -> bool:
        """Evaluates whether an entity object satisfies the filter conditions."""
        if self.resource_type and self.resource_type != resource_type:
            return False

        if self.only_eligible and not getattr(obj, "is_eligible", False):
            return False

        if not self.include_templates:
            if getattr(obj, "is_template", False):
                return False
            if getattr(obj, "resource_origin", None) == ResourceOrigin.TEMPLATE:
                return False

        if self.origin:
            res_origin = getattr(obj, "resource_origin", None)
            if res_origin != self.origin:
                return False

        status_val = getattr(obj, "status", None)
        if self.status:
            if isinstance(status_val, Enum) and status_val != self.status:
                return False
            elif isinstance(status_val, str) and status_val != self.status.value:
                return False

        if self.domain:
            domains = getattr(obj, "supported_domains", []) or getattr(obj, "domains", []) or [getattr(obj, "domain", None)]
            if self.domain not in domains and "all" not in domains:
                return False

        if self.capability:
            caps = getattr(obj, "capabilities", [])
            if self.capability not in caps and not any(self.capability in c for c in caps):
                return False

        if self.provider_id:
            pid = getattr(obj, "provider_id", None)
            if pid and pid != self.provider_id:
                return False

        if self.privacy_level:
            plevel = getattr(obj, "privacy_tier", None) or getattr(obj, "privacy_level", None)
            if plevel and plevel != self.privacy_level and plevel != "airgapped":
                return False

        if self.min_confidence is not None:
            conf = getattr(obj, "historical_confidence", None) or getattr(obj, "reasoning_score", None)
            if conf is not None and conf < self.min_confidence:
                return False

        if self.max_cost_tier is not None:
            cost = getattr(obj, "cost_tier", None) or getattr(obj, "cost_per_1k_tokens", None)
            if cost is not None and cost > self.max_cost_tier:
                return False

        if self.required_tags:
            tags = getattr(obj, "tags", []) or getattr(obj, "specialization", [])
            if not any(tag in tags for tag in self.required_tags):
                return False

        if self.text_search:
            query = self.text_search.lower()
            name = (getattr(obj, "name", "") or "").lower()
            desc = (getattr(obj, "description", "") or "").lower()
            rid = (getattr(obj, "provider_id", None) or getattr(obj, "account_id", None) or getattr(obj, "agent_id", None) or getattr(obj, "project_id", None) or getattr(obj, "capability_id", None) or getattr(obj, "environment_id", None) or "").lower()
            if query not in name and query not in desc and query not in rid:
                return False

        return True


@dataclass
class ResourceHealthReport:
    """Canonical health status report produced by RRM."""
    is_healthy: bool
    status: str
    total_resources: int
    active_providers: int
    active_accounts: int
    active_environments: int
    active_capabilities: int
    active_agents: int
    active_projects: int
    exhausted_accounts: int
    degraded_resources: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RRMRegistryMetrics:
    """High-level metrics summary of RRM state."""
    resource_counts: Dict[str, int]
    status_counts: Dict[str, int]
    providers_count: int
    accounts_count: int
    environments_count: int
    capabilities_count: int
    agents_count: int
    projects_count: int
    last_updated: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
