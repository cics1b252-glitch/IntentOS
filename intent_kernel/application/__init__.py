"""Application composition API for architecture v2.0."""

from intent_kernel.application.composition import (
    ApplicationComponents,
    ApplicationFactory,
    KernelBuilder,
)
from intent_kernel.application.mission_engine import (
    MissionCompletionEvidenceError,
    MissionEngine,
    MissionTransitionError,
)
from intent_kernel.application.migration import MigrationTelemetry
from intent_kernel.application.mission_service import (
    CanonicalMissionService,
    MissionAuthorizationBoundary,
)
from intent_kernel.application.memory_service import (
    CanonicalMemoryService,
    MemoryAuthorityContract,
)

__all__ = [
    "ApplicationComponents",
    "ApplicationFactory",
    "KernelBuilder",
    "MissionEngine",
    "MissionCompletionEvidenceError",
    "MissionTransitionError",
    "CanonicalMissionService",
    "MissionAuthorizationBoundary",
    "MigrationTelemetry",
    "CanonicalMemoryService",
    "MemoryAuthorityContract",
]
