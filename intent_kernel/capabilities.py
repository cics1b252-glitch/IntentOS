"""Capability Registry — official capabilities provided by the Kernel.

Every Core App consults the Registry before implementing any functionality.
If a capability exists, reuse it. If not, propose it as a Kernel capability.

This prevents duplication and enables automatic reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Capability:
    """A registered Kernel capability."""
    name: str
    description: str
    module: str           # which Kernel module provides it
    version: str = "1.0.0"
    interface: Any = None  # the actual callable/interface
    tags: list[str] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)  # Core Apps using this

    def expose(self) -> Any:
        """Return the capability interface for consumption."""
        return self.interface


class CapabilityRegistry:
    """Central registry of all Kernel capabilities.

    Core Apps query this before implementing new functionality.
    The Kernel populates it at startup.
    """

    def __init__(self, *, read_only: bool = False):
        self._capabilities: dict[str, Capability] = {}
        self._read_only = read_only

    def freeze(self) -> None:
        """Prevent new historical registrations after compatibility loading."""
        self._read_only = True

    def register(
        self,
        name: str,
        description: str,
        module: str,
        interface: Any = None,
        version: str = "1.0.0",
        tags: list[str] | None = None,
    ) -> Capability:
        """Register a capability."""
        if self._read_only:
            raise RuntimeError(
                "Historical CapabilityRegistry is read-only; "
                "use CanonicalCapabilityRegistry"
            )
        cap = Capability(
            name=name,
            description=description,
            module=module,
            version=version,
            interface=interface,
            tags=tags or [],
        )
        self._capabilities[name] = cap
        return cap

    def get(self, name: str) -> Capability | None:
        """Get a capability by name."""
        return self._capabilities.get(name)

    def has(self, name: str) -> bool:
        """Check if a capability exists."""
        return name in self._capabilities

    def query(self, tags: str | None = None) -> list[Capability]:
        """Query capabilities by tag."""
        results = list(self._capabilities.values())
        if tags:
            results = [c for c in results if tags in c.tags]
        return results

    def record_usage(self, capability_name: str, core_app: str) -> None:
        """Record that a Core App is using a capability."""
        cap = self._capabilities.get(capability_name)
        if cap and core_app not in cap.used_by:
            cap.used_by.append(core_app)

    def list_all(self) -> list[dict]:
        """List all capabilities."""
        return [
            {
                "name": c.name,
                "description": c.description,
                "module": c.module,
                "version": c.version,
                "tags": c.tags,
                "used_by": c.used_by,
            }
            for c in self._capabilities.values()
        ]

    def status(self) -> dict[str, Any]:
        """Get registry status for Monitor."""
        return {
            "total": len(self._capabilities),
            "capabilities": [
                {
                    "name": c.name,
                    "module": c.module,
                    "used_by_count": len(c.used_by),
                }
                for c in self._capabilities.values()
            ],
        }


# ---------------------------------------------------------------------------
# Default capabilities provided by the Kernel
# ---------------------------------------------------------------------------

def register_default_capabilities(registry: CapabilityRegistry) -> None:
    """Register the default Kernel capabilities."""

    registry.register(
        name="memory",
        description="User memory and profile management",
        module="intent_kernel.pkb",
        tags=["memory", "profile", "user"],
    )

    registry.register(
        name="knowledge",
        description="Knowledge Core read/write/query operations",
        module="intent_kernel.pkb",
        tags=["knowledge", "persistence", "query"],
    )

    registry.register(
        name="decision",
        description="Decision recording, versioning, and review",
        module="intent_kernel.pkb",
        tags=["decision", "versioning", "review"],
    )

    registry.register(
        name="planning",
        description="Project creation, status tracking, and organization",
        module="intent_kernel.pkb",
        tags=["project", "planning", "organization"],
    )

    registry.register(
        name="simulation",
        description="Scenario simulation and projection",
        module="intent_kernel.pkb",
        tags=["simulation", "projection", "scenario"],
    )

    registry.register(
        name="research",
        description="Research sessions with sources, findings, and conclusions",
        module="intent_kernel.pkb",
        tags=["research", "sources", "findings"],
    )

    registry.register(
        name="versioning",
        description="Entity versioning with snapshots and rollback",
        module="intent_kernel.pkb",
        tags=["versioning", "snapshot", "rollback"],
    )

    registry.register(
        name="search",
        description="Full-text search across documents and notes",
        module="intent_kernel.pkb",
        tags=["search", "fulltext", "query"],
    )

    registry.register(
        name="guardians",
        description="Constitutional validation via 6 Guardians",
        module="intent_kernel.constitution",
        tags=["constitution", "validation", "guardians"],
    )

    registry.register(
        name="event_bus",
        description="Internal pub/sub event system",
        module="intent_kernel.bus",
        tags=["events", "pubsub", "communication"],
    )
