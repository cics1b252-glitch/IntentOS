"""Mission Record Store Port — M32B Durable Mission Authority.

Passive storage port for MissionRecord persistence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from intent_kernel.mission.mission_record import MissionRecord


class MissionRecordStorePort(ABC):
    """Passive storage port for MissionRecord durability.

    Synchronous contract (matches JsonFileMissionRecordStore and the RRM
    store precedent). Results are returned as DurableCommitResult values;
    structural problems raise MissionRecordValidationError. The store is
    passive — it must not:
    - authorize actions
    - transition mission state
    - rebind executors
    - verify evidence
    - invoke external effects
    """

    @abstractmethod
    def create(self, record: MissionRecord) -> "DurableCommitResult":
        """Create a new MissionRecord at revision 1.

        Fails closed with outcome "already_exists" if the durable mission
        file already exists. Never overwrites existing authority.
        """
        ...

    @abstractmethod
    def load(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Load a MissionRecord by mission_id.

        Returns None if not found (NON_RESUMABLE). Raises
        MissionRecordValidationError on corruption / validation failure.
        """
        ...

    @abstractmethod
    def commit(
        self, expected_revision: int, record: MissionRecord
    ) -> "DurableCommitResult":
        """Atomically commit a MissionRecord update anchored to durable state.

        Requires the durable record to exist at expected_revision and the
        candidate at expected_revision + 1 with immutable identity intact.
        Ordinary commit cannot mutate confirmation fields.
        """
        ...

    @abstractmethod
    def transition_confirmation(
        self, expected_revision: int, record: MissionRecord
    ) -> "DurableCommitResult":
        """Canonical confirmation-state transition.

        Only callable by MissionActionAuthority. Allows confirmation
        field changes while enforcing all other immutability guards.
        """
        ...

    @abstractmethod
    def exists(self, mission_id: str) -> bool:
        """Check if a canonical mission file exists (no content read)."""
        ...


class DurableCommitResult:
    """Result of a durable commit operation."""

    def __init__(self, outcome: str, revision: int, reason: str = ""):
        self.outcome = outcome  # "committed", "revision_mismatch", "validation_failed", "io_error"
        self.revision = revision
        self.reason = reason

    @property
    def is_success(self) -> bool:
        return self.outcome == "committed"


class MissionRecordCommitError(Exception):
    """Raised when a durable commit fails."""

    def __init__(self, outcome: str, revision: int, reason: str = ""):
        self.outcome = outcome
        self.revision = revision
        self.reason = reason
        super().__init__(f"MissionRecord commit failed: {outcome} (rev={revision}): {reason}")


class MissionRecordNotFoundError(Exception):
    """Raised when a mission record is not found."""
    pass


class MissionRecordConflictError(Exception):
    """Raised when a mission record already exists."""
    pass


class MissionRecordValidationError(Exception):
    """Raised when a mission record fails validation."""
    pass