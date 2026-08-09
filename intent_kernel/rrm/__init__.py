"""Registry & Resource Manager (RRM) Package — RFC-0013.

Provides canonical registration and resource management for Providers, Accounts,
Execution Environments, Capabilities, Agents, and Projects across Intent OS.
"""

from intent_kernel.rrm.adapter import RRMToCORAdapter
from intent_kernel.rrm.models import (
    AccountResource,
    AgentInstallationState,
    AgentResource,
    AvailabilitySource,
    CapabilityResource,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentType,
    ProjectResource,
    ProviderResource,
    ResourceHealthReport,
    ResourceOrigin,
    ResourceQueryFilter,
    ResourceStatus,
    ResourceType,
    RRMRegistryMetrics,
)
from intent_kernel.rrm.ports import (
    ProjectRegistryPort,
    ResourceQueryPort,
    RRMRegistryPort,
)
from intent_kernel.rrm.service import RegistryResourceManager

__all__ = [
    # Models
    "ResourceType",
    "ResourceStatus",
    "ResourceOrigin",
    "AvailabilitySource",
    "AgentInstallationState",
    "ExecutionEnvironmentType",
    "ProviderResource",
    "AccountResource",
    "ExecutionEnvironmentResource",
    "CapabilityResource",
    "AgentResource",
    "ProjectResource",
    "ResourceQueryFilter",
    "ResourceHealthReport",
    "RRMRegistryMetrics",
    # Ports
    "RRMRegistryPort",
    "ResourceQueryPort",
    "ProjectRegistryPort",
    # Service & Adapter
    "RegistryResourceManager",
    "RRMToCORAdapter",
]
