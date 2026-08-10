"""Permissioned, declarative system-resource discovery boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class DiscoveredResourceType(str, Enum):
    APPLICATION = "APPLICATION"
    OPERATING_SYSTEM_CAPABILITY = "OPERATING_SYSTEM_CAPABILITY"
    FILESYSTEM = "FILESYSTEM"
    BROWSER = "BROWSER"
    DATABASE = "DATABASE"
    API = "API"
    AI_PROVIDER = "AI_PROVIDER"
    LOCAL_MODEL = "LOCAL_MODEL"
    CONNECTED_SERVICE = "CONNECTED_SERVICE"
    DEVICE = "DEVICE"
    TOOL = "TOOL"
    CUSTOM = "CUSTOM"


class ResourceTruthState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CONFIGURED = "CONFIGURED"
    AUTHORIZED = "AUTHORIZED"
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DiscoveredResourceCandidate:
    resource_id: str
    resource_type: DiscoveredResourceType
    name: str
    capabilities: tuple[str, ...]
    origin: str
    environment: str
    truth_state: ResourceTruthState = ResourceTruthState.DISCOVERED
    health: str = "unknown"
    permission_state: str = "not_configured"
    authorization_required: bool = True
    privacy_class: str = "standard"
    cost_class: str = "unknown"
    latency_class: str = "unknown"
    provenance: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def executable(self) -> bool:
        return (
            self.truth_state is ResourceTruthState.AVAILABLE
            and not self.authorization_required
            and self.permission_state == "granted"
        )


class SystemResourceDiscoveryPort(Protocol):
    async def discover_candidates(
        self, context: dict[str, Any]
    ) -> list[DiscoveredResourceCandidate]: ...

    async def describe_capabilities(
        self, resource_id: str
    ) -> tuple[str, ...]: ...

    async def describe_permissions(
        self, resource_id: str
    ) -> dict[str, Any]: ...

    async def describe_health(self, resource_id: str) -> str: ...
