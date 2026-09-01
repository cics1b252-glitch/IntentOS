"""Registry & Resource Manager (RRM) — Canonical Resource Models (RFC-0013).

Defines the canonical data structures for Providers, Accounts, Execution Environments,
Capabilities, Agents, and Projects within Intent OS.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Set, Mapping, Union
from uuid import uuid4

from intent_kernel.rrm.generation import (
    LEGACY_UNVERSIONED,
    GENERATION_INITIAL,
    is_valid_generation,
    normalize_for_restore,
)
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

    def to_snapshot(self) -> 'ProviderSnapshot':
        """Create an immutable snapshot of this provider resource."""
        return ProviderSnapshot(
            provider_id=self.provider_id,
            name=self.name,
            reasoning_score=self.reasoning_score,
            tool_use_support=self.tool_use_support,
            context_window=self.context_window,
            cost_per_1k_tokens=self.cost_per_1k_tokens,
            privacy_tier=self.privacy_tier,
            availability=self.availability,
            multimodal=self.multimodal,
            status=_to_status_str(self.status),
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_configured=self.is_configured,
            has_active_account=self.has_active_account,
            endpoint_url=self.endpoint_url,
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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

    def to_snapshot(self) -> 'AccountSnapshot':
        """Create an immutable snapshot of this account resource."""
        return AccountSnapshot(
            account_id=self.account_id,
            provider_id=self.provider_id,
            name=self.name,
            quota_remaining=self.quota_remaining,
            rate_limit_rpm=self.rate_limit_rpm,
            rate_limit_tpm=self.rate_limit_tpm,
            priority=self.priority,
            cost_multiplier=self.cost_multiplier,
            status=_to_status_str(self.status),
            secret_reference=self.secret_reference,
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_configured=self.is_configured,
            allowed_policies=_freeze_list(self.allowed_policies),
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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

    def to_snapshot(self) -> 'ExecutionEnvironmentSnapshot':
        """Create an immutable snapshot of this execution environment resource."""
        return ExecutionEnvironmentSnapshot(
            environment_id=self.environment_id,
            type=_to_execution_env_type_str(self.type),
            status=_to_status_str(self.status),
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_discovered=self.is_discovered,
            capabilities=_freeze_list(self.capabilities),
            available_tools=_freeze_list(self.available_tools),
            network_access=self.network_access,
            privacy_level=self.privacy_level,
            latency_class=self.latency_class,
            cost_class=self.cost_class,
            resource_limits=_freeze_mapping(self.resource_limits),
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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

    def to_snapshot(self) -> 'CapabilitySnapshot':
        """Create an immutable snapshot of this capability resource."""
        return CapabilitySnapshot(
            capability_id=self.capability_id,
            name=self.name,
            description=self.description,
            version=self.version,
            tags=_freeze_list(self.tags),
            domains=_freeze_list(self.domains),
            provided_by_agents=_freeze_list(self.provided_by_agents),
            effect=self.effect,
            requires_network=self.requires_network,
            requires_confirmation=self.requires_confirmation,
            status=_to_status_str(self.status),
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_executable=self.is_executable,
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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

    def to_snapshot(self) -> 'AgentSnapshot':
        """Create an immutable snapshot of this agent resource."""
        return AgentSnapshot(
            agent_id=self.agent_id,
            name=self.name,
            capabilities=_freeze_list(self.capabilities),
            specialization=_freeze_list(self.specialization),
            availability=self.availability,
            status=_to_status_str(self.status),
            installation_state=_to_agent_installation_state_str(self.installation_state),
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_enabled=self.is_enabled,
            version=self.version,
            historical_confidence=self.historical_confidence,
            cost_tier=self.cost_tier,
            latency_tier=self.latency_tier,
            supported_domains=_freeze_list(self.supported_domains),
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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

    def to_snapshot(self) -> 'ProjectSnapshot':
        """Create an immutable snapshot of this project resource."""
        return ProjectSnapshot(
            project_id=self.project_id,
            name=self.name,
            domain=self.domain,
            description=self.description,
            owner_id=self.owner_id,
            status=_to_status_str(self.status),
            resource_origin=_to_resource_origin_str(self.resource_origin),
            availability_source=_to_availability_source_str(self.availability_source),
            is_template=self.is_template,
            is_demo=self.is_demo,
            retention_class=self.retention_class,
            access_scope=self.access_scope,
            assigned_agents=_freeze_list(self.assigned_agents),
            assigned_environments=_freeze_list(self.assigned_environments),
            budget_limit=self.budget_limit,
            consumed_budget=self.consumed_budget,
            governed_registration_id=self.governed_registration_id,
            generation=self.generation,
            metadata=_freeze_mapping(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_eligible=self.is_eligible,
        )

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


# --- Immutable Resource Snapshots (M31.2B-0) ---
# These are immutable snapshots returned by public RRM observation methods.
# They contain no references to mutable canonical objects.

def _freeze_mapping(d: Dict[str, Any]) -> Mapping[str, Any]:
    """Convert a dict to an immutable MappingProxyType.

    RA-31.2B1-03 / M31.2B-0: the mapping is deep-copied so NO mutable nested
    container remains shared with the canonical object. A caller holding a
    public snapshot therefore cannot mutate canonical state through it
    (PUBLIC_SNAPSHOT_NESTED_ALIAS_ESCAPE=NO) while the top level stays immutable.
    """
    return MappingProxyType(copy.deepcopy(dict(d)))


def _freeze_list(lst: List[Any]) -> tuple:
    """Convert a list to an immutable tuple."""
    return tuple(lst)


def _freeze_set(s: Set[Any]) -> frozenset:
    """Convert a set to an immutable frozenset."""
    return frozenset(s)


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """Immutable snapshot of a ProviderResource."""
    provider_id: str
    name: str
    reasoning_score: float
    tool_use_support: bool
    context_window: int
    cost_per_1k_tokens: float
    privacy_tier: str
    availability: float
    multimodal: bool
    status: str  # ResourceStatus as string
    resource_origin: str  # ResourceOrigin as string
    availability_source: str  # AvailabilitySource as string
    is_template: bool
    is_configured: bool
    has_active_account: bool
    endpoint_url: Optional[str]
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for serialization/deserialization."""
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "reasoning_score": self.reasoning_score,
            "tool_use_support": self.tool_use_support,
            "context_window": self.context_window,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "privacy_tier": self.privacy_tier,
            "availability": self.availability,
            "multimodal": self.multimodal,
            "status": self.status,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_configured": self.is_configured,
            "has_active_account": self.has_active_account,
            "endpoint_url": self.endpoint_url,
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
"created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Immutable snapshot of an AccountResource."""
    account_id: str
    provider_id: str
    name: str
    quota_remaining: float
    rate_limit_rpm: int
    rate_limit_tpm: int
    priority: int
    cost_multiplier: float
    status: str
    secret_reference: Optional[str]
    resource_origin: str
    availability_source: str
    is_template: bool
    is_configured: bool
    allowed_policies: tuple
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "provider_id": self.provider_id,
            "name": self.name,
            "quota_remaining": self.quota_remaining,
            "rate_limit_rpm": self.rate_limit_rpm,
            "rate_limit_tpm": self.rate_limit_tpm,
            "priority": self.priority,
            "cost_multiplier": self.cost_multiplier,
            "status": self.status,
            "secret_reference": self.secret_reference,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_configured": self.is_configured,
            "allowed_policies": list(self.allowed_policies),
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ExecutionEnvironmentSnapshot:
    """Immutable snapshot of an ExecutionEnvironmentResource."""
    environment_id: str
    type: str  # ExecutionEnvironmentType as string
    status: str
    resource_origin: str
    availability_source: str
    is_template: bool
    is_discovered: bool
    capabilities: tuple
    available_tools: tuple
    network_access: bool
    privacy_level: str
    latency_class: str
    cost_class: str
    resource_limits: Mapping[str, Any]
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "type": self.type,
            "status": self.status,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_discovered": self.is_discovered,
            "capabilities": list(self.capabilities),
            "available_tools": list(self.available_tools),
            "network_access": self.network_access,
            "privacy_level": self.privacy_level,
            "latency_class": self.latency_class,
            "cost_class": self.cost_class,
            "resource_limits": dict(self.resource_limits),
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Immutable snapshot of a CapabilityResource."""
    capability_id: str
    name: str
    description: str
    version: str
    tags: tuple
    domains: tuple
    provided_by_agents: tuple
    effect: str
    requires_network: bool
    requires_confirmation: bool
    status: str
    resource_origin: str
    availability_source: str
    is_template: bool
    is_executable: bool
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "domains": list(self.domains),
            "provided_by_agents": list(self.provided_by_agents),
            "effect": self.effect,
            "requires_network": self.requires_network,
            "requires_confirmation": self.requires_confirmation,
            "status": self.status,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_executable": self.is_executable,
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    """Immutable snapshot of an AgentResource."""
    agent_id: str
    name: str
    capabilities: tuple
    specialization: tuple
    availability: float
    status: str
    installation_state: str  # AgentInstallationState as string
    resource_origin: str
    availability_source: str
    is_template: bool
    is_enabled: bool
    version: str
    historical_confidence: float
    cost_tier: float
    latency_tier: float
    supported_domains: tuple
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": list(self.capabilities),
            "specialization": list(self.specialization),
            "availability": self.availability,
            "status": self.status,
            "installation_state": self.installation_state,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_enabled": self.is_enabled,
            "version": self.version,
            "historical_confidence": self.historical_confidence,
            "cost_tier": self.cost_tier,
            "latency_tier": self.latency_tier,
            "supported_domains": list(self.supported_domains),
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    """Immutable snapshot of a ProjectResource."""
    project_id: str
    name: str
    domain: str
    description: str
    owner_id: str
    status: str
    resource_origin: str
    availability_source: str
    is_template: bool
    is_demo: bool
    retention_class: str
    access_scope: str
    assigned_agents: tuple
    assigned_environments: tuple
    budget_limit: float
    consumed_budget: float
    governed_registration_id: str
    generation: int
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str
    is_eligible: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status,
            "resource_origin": self.resource_origin,
            "availability_source": self.availability_source,
            "is_template": self.is_template,
            "is_demo": self.is_demo,
            "retention_class": self.retention_class,
            "access_scope": self.access_scope,
            "assigned_agents": list(self.assigned_agents),
            "assigned_environments": list(self.assigned_environments),
            "budget_limit": self.budget_limit,
            "consumed_budget": self.consumed_budget,
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --- M31.2B-1: Typed Conditional Update/Create Operations ---


class ConditionalUpdateOutcome(str, Enum):
    """Outcome of a conditional resource status update."""
    APPLIED = "applied"
    NO_OP = "no_op"
    NOT_FOUND = "not_found"
    REGISTRATION_LINEAGE_MISMATCH = "registration_lineage_mismatch"
    GENERATION_MISMATCH = "generation_mismatch"
    INVALID_TRANSITION = "invalid_transition"


class ConditionalCreateOutcome(str, Enum):
    """Outcome of a conditional resource creation."""
    CREATED = "created"
    CONFLICT_ACTIVE = "conflict_active"
    REJECTED_TOMBSTONED = "rejected_tombstoned"
    RE_REGISTRATION_AUTHORIZED = "re_registration_authorized"


@dataclass(frozen=True, slots=True)
class ConditionalResourceStatusRequest:
    """Typed request for conditional resource status update.
    
    DATA ONLY — no callbacks, no caller-supplied generation.
    """
    resource_type: ResourceType
    resource_id: str
    expected_governed_registration_id: str
    expected_generation: int
    desired_status: ResourceStatus

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("resource_id must not be empty")
        if self.expected_generation < 0:
            raise ValueError("expected_generation must be non-negative")


@dataclass(frozen=True, slots=True)
class ConditionalRegistrationRequest:
    """Typed request for conditional initial resource registration.

    DATA ONLY — no factory callbacks, no caller-supplied generation,
    no caller-supplied governed registration lineage.

    M31.2B-1 supports ONLY genuinely never-registered fresh creates. RRM does
    NOT authorize re-registration: a caller may never supply a governed
    registration lineage or a resulting generation for a create. Authority-bearing
    lineage input fails closed at request construction (ValueError) before any
    productive mutation.
    """
    resource_type: ResourceType
    resource_data: Any  # The full resource model data to register
    expected_absence: bool = True  # M31.2B-1: MUST be True (fresh create only)
    expected_governed_registration_id: str = ""  # Reserved (must be empty in M31.2B-1)
    expected_generation: int = 0  # Reserved (must be zero in M31.2B-1)

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("resource_type must be specified")
        if self.resource_data is None:
            raise ValueError("resource_data must be provided")
        if not self.expected_absence:
            raise ValueError(
                "M31.2B-1 does not authorize re-registration; "
                "expected_absence must be True"
            )

        caller_lineage = getattr(self.resource_data, "governed_registration_id", "") or ""
        if caller_lineage:
            raise ValueError(
                "caller may not supply governed registration lineage for a "
                "conditional create"
            )

        caller_generation = getattr(self.resource_data, "generation", 0)
        if is_valid_generation(caller_generation):
            raise ValueError(
                "caller may not supply a resulting generation for a "
                "conditional create"
            )

        if self.expected_governed_registration_id or self.expected_generation != 0:
            raise ValueError(
                "For expected absence, governed_registration_id and "
                "generation must be empty/zero"
            )


@dataclass(frozen=True, slots=True)
class ConditionalUpdateResult:
    """Immutable result of a conditional resource status update."""
    outcome: ConditionalUpdateOutcome
    resource_type: ResourceType
    resource_id: str
    observed_generation: int
    observed_governed_registration_id: str
    previous_status: Optional[ResourceStatus]
    new_status: Optional[ResourceStatus]
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ConditionalCreateResult:
    """Immutable result of a conditional resource creation."""
    outcome: ConditionalCreateOutcome
    resource_type: ResourceType
    resource_id: str
    observed_governed_registration_id: str
    observed_generation: int
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationOutcome:
    """Complete registration result including creation and re-registration outcomes."""
    outcome: Union[ConditionalCreateOutcome, ConditionalUpdateOutcome]
    resource_type: ResourceType
    resource_id: str
    governed_registration_id: str
    generation: int
    reason: str = ""

    @property
    def is_success(self) -> bool:
        return self.outcome in (
            ConditionalCreateOutcome.CREATED,
            ConditionalCreateOutcome.RE_REGISTRATION_AUTHORIZED,
            ConditionalUpdateOutcome.APPLIED,
            ConditionalUpdateOutcome.NO_OP,
        )

    @property
    def is_conflict(self) -> bool:
        return self.outcome in (
            ConditionalCreateOutcome.CONFLICT_ACTIVE,
            ConditionalCreateOutcome.REJECTED_TOMBSTONED,
        )

    @property
    def is_mismatch(self) -> bool:
        return self.outcome in (
            ConditionalUpdateOutcome.REGISTRATION_LINEAGE_MISMATCH,
            ConditionalUpdateOutcome.GENERATION_MISMATCH,
        )


@dataclass(frozen=True, slots=True)
class ResourceTombstone:
    """M31.2B-2A — Canonical immutable tombstone identity contract.

    DATA ONLY. Defines the structured identity of a retired governed
    registration lineage for FUTURE retirement / re-registration
    integration. This movement MUST NOT activate structured tombstones in
    runtime: the productive tombstone mechanism remains
    ``RegistryResourceManager._tombstones: Set[str]`` and M31.2B-1 tombstone
    rejection semantics are unchanged.

    This type is an identity contract, NOT a canonical state constructor.
    It does NOT generate any identity field and does NOT confer authority:
      - NOT retirement authorization
      - NOT re-registration authorization
      - NOT promotion authorization
      - NOT permission to recreate a resource
      - NOT evidence that a resource was successfully removed

    Canonical lineage primary identity:
        (resource_kind, resource_id, governed_registration_id)

    ``observed_generation`` is freshness/version evidence bound to that
    lineage. It records the canonical generation of the active governed
    registration observed immediately before productive retirement removal /
    transition processing — never a post-retirement, B-2B terminal, or
    re-registration generation. It is NOT part of the lineage primary key.

    It contains no executable / callback fields, no arbitrary mutable
    metadata object, no authority-bearing methods, and no runtime RRM
    reference.
    """
    resource_kind: ResourceType
    resource_id: str
    governed_registration_id: str
    observed_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource_kind, ResourceType):
            raise ValueError(
                "resource_kind must be a canonical ResourceType, "
                f"got {type(self.resource_kind).__name__}"
            )
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id must be a non-empty string")
        if (
            not isinstance(self.governed_registration_id, str)
            or not self.governed_registration_id.strip()
        ):
            raise ValueError("governed_registration_id must be a non-empty string")
        if not is_valid_generation(self.observed_generation):
            raise ValueError(
                "observed_generation must be a governed/versioned generation "
                "(positive int, never bool); legacy/unversioned generations are "
                "NOT silently promoted"
            )

    @property
    def lineage_identity(self) -> tuple:
        """Canonical lineage primary identity (generation excluded)."""
        return (self.resource_kind, self.resource_id, self.governed_registration_id)


# --- Helper functions for snapshot creation ---

def _to_status_str(status: Any) -> str:
    """Convert ResourceStatus enum to string."""
    return status.value if hasattr(status, 'value') else str(status)


def _to_resource_origin_str(origin: Any) -> str:
    """Convert ResourceOrigin enum to string."""
    return origin.value if hasattr(origin, 'value') else str(origin)


def _to_availability_source_str(source: Any) -> str:
    """Convert AvailabilitySource enum to string."""
    return source.value if hasattr(source, 'value') else str(source)


def _to_execution_env_type_str(env_type: Any) -> str:
    """Convert ExecutionEnvironmentType enum to string."""
    return env_type.value if hasattr(env_type, 'value') else str(env_type)


def _to_agent_installation_state_str(state: Any) -> str:
    """Convert AgentInstallationState enum to string."""
    return state.value if hasattr(state, 'value') else str(state)
