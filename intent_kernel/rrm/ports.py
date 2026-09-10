"""Registry & Resource Manager (RRM) — Canonical Ports (RFC-0013).

Defines typing.Protocol interfaces for RRM registry operations, decoupling caller modules
from concrete implementations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from intent_kernel.rrm.models import (
    AccountResource,
    AgentResource,
    CapabilityResource,
    DurableRRMState,
    DurableCommitResult,
    ExecutionEnvironmentResource,
    FirstGovernanceRequest,
    FirstGovernanceResult,
    ProjectResource,
    ProviderResource,
    ResourceHealthReport,
    ResourceQueryFilter,
    ResourceStatus,
    ResourceType,
    RRMRegistryMetrics,
)


@runtime_checkable
class ResourceQueryPort(Protocol):
    """Port for resource discovery and filtering queries."""

    def query_resources(
        self,
        filter_criteria: ResourceQueryFilter,
    ) -> List[Any]: ...

    def find_agents_for_capabilities(
        self,
        capabilities: List[str],
    ) -> List[AgentResource]: ...


@runtime_checkable
class ProjectRegistryPort(Protocol):
    """Port for project workspace management."""

    def register_project(self, project: ProjectResource) -> ProjectResource: ...

    def get_project(self, project_id: str) -> Optional[ProjectResource]: ...

    def list_projects(self, status: Optional[ResourceStatus] = None) -> List[ProjectResource]: ...

    def unregister_project(self, project_id: str) -> bool: ...


@runtime_checkable
class RRMRegistryPort(Protocol):
    """Canonical primary interface for Registry & Resource Manager (RRM)."""

    # Provider Operations
    def register_provider(self, provider: ProviderResource) -> ProviderResource: ...
    def get_provider(self, provider_id: str) -> Optional[ProviderResource]: ...
    def list_providers(self, status: Optional[ResourceStatus] = None) -> List[ProviderResource]: ...
    def unregister_provider(self, provider_id: str) -> bool: ...

    # Account Operations
    def register_account(self, account: AccountResource) -> AccountResource: ...
    def get_account(self, account_id: str) -> Optional[AccountResource]: ...
    def list_accounts(self, provider_id: Optional[str] = None, status: Optional[ResourceStatus] = None) -> List[AccountResource]: ...
    def unregister_account(self, account_id: str) -> bool: ...

    # Execution Environment Operations
    def register_environment(self, environment: ExecutionEnvironmentResource) -> ExecutionEnvironmentResource: ...
    def get_environment(self, environment_id: str) -> Optional[ExecutionEnvironmentResource]: ...
    def list_environments(self, status: Optional[ResourceStatus] = None) -> List[ExecutionEnvironmentResource]: ...
    def unregister_environment(self, environment_id: str) -> bool: ...

    # Capability Operations
    def register_capability(self, capability: CapabilityResource) -> CapabilityResource: ...
    def get_capability(self, capability_name_or_id: str) -> Optional[CapabilityResource]: ...
    def list_capabilities(self, status: Optional[ResourceStatus] = None) -> List[CapabilityResource]: ...
    def unregister_capability(self, capability_id: str) -> bool: ...

    # Agent Operations
    def register_agent(self, agent: AgentResource) -> AgentResource: ...
    def get_agent(self, agent_id: str) -> Optional[AgentResource]: ...
    def list_agents(self, status: Optional[ResourceStatus] = None) -> List[AgentResource]: ...
    def unregister_agent(self, agent_id: str) -> bool: ...

    # Project Operations
    def register_project(self, project: ProjectResource) -> ProjectResource: ...
    def get_project(self, project_id: str) -> Optional[ProjectResource]: ...
    def list_projects(self, status: Optional[ResourceStatus] = None) -> List[ProjectResource]: ...
    def unregister_project(self, project_id: str) -> bool: ...

    # Query & Status Operations
    def query_resources(self, filter_criteria: ResourceQueryFilter) -> List[Any]: ...
    def update_resource_status(self, resource_type: ResourceType, resource_id: str, status: ResourceStatus) -> bool: ...

    # Registration Lineage Operations
    def conditional_reregister_resource(self, request: Any) -> Any: ...

    # M31.3B-1B: First Governance (atomic, canonical-lineage minting)
    def conditional_govern_existing_resource(
        self, request: FirstGovernanceRequest,
    ) -> FirstGovernanceResult: ...

    # Health & Metrics
    def check_health(self) -> ResourceHealthReport: ...
    def get_metrics(self) -> RRMRegistryMetrics: ...


@runtime_checkable
class RRMStateStorePort(Protocol):
    """M32A — Passive RRM authority-state storage port.

    RRM_STATE_STORE_IS_AUTHORITY=NO
    RRM_REMAINS_SOLE_AUTHORITY=YES

    The store may validate storage-level format/revision but may NOT make
    governance decisions.
    """

    def load(self) -> Optional[Any]: ...

    def commit(
        self,
        expected_revision: int,
        state: Any
    ) -> Any: ...
