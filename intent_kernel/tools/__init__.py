"""Capability & Tool Access Layer Package — RFC-0016 (STUDIO 10.3).

Exports canonical models, registry, router, permissions, authorization gate,
secret resolver, health adapter, and safe simulation tool adapters.
"""

from intent_kernel.tools.adapters import (
    BrowserSimulationTool,
    CalendarSimulationTool,
    EmailSimulationTool,
    FilesystemSimulationTool,
    InMemoryToolAdapter,
    ToolAccessExecutorAdapter,
)
from intent_kernel.tools.authorization import ToolAuthorizationGate
from intent_kernel.tools.health import InMemoryToolHealthAdapter, ToolHealthPort
from intent_kernel.tools.models import (
    CapabilityToolMapping,
    CredentialReference,
    DryRunRequest,
    DryRunResult,
    PermissionDecision,
    PermissionDecisionState,
    PermissionScope,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolOrigin,
    ToolResource,
    ToolSelectionTrace,
    ToolStatus,
    ToolType,
)
from intent_kernel.tools.permissions import PermissionManager
from intent_kernel.tools.registry import InMemoryToolRegistry, ToolRegistryPort
from intent_kernel.tools.router import CapabilityRouter
from intent_kernel.tools.secret_resolver import FakeSecretResolver, SecretResolverPort

__all__ = [
    "ToolStatus",
    "ToolOrigin",
    "ToolType",
    "PermissionScope",
    "PermissionDecisionState",
    "ToolHealthStatus",
    "ToolAuthorizationDecisionState",
    "CredentialReference",
    "ToolResource",
    "CapabilityToolMapping",
    "ToolCandidate",
    "PermissionDecision",
    "DryRunRequest",
    "DryRunResult",
    "ToolSelectionTrace",
    "ToolRegistryPort",
    "InMemoryToolRegistry",
    "PermissionManager",
    "CapabilityRouter",
    "ToolAuthorizationGate",
    "SecretResolverPort",
    "FakeSecretResolver",
    "ToolHealthPort",
    "InMemoryToolHealthAdapter",
    "InMemoryToolAdapter",
    "EmailSimulationTool",
    "CalendarSimulationTool",
    "FilesystemSimulationTool",
    "BrowserSimulationTool",
    "ToolAccessExecutorAdapter",
]
