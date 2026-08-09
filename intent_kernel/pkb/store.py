"""KnowledgeStore — interface for PKB persistence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import (
    Domain,
    EventLifecycle,
    EventType,
    QueryFilters,
    VersionSnapshot,
)


@runtime_checkable
class KnowledgeStore(Protocol):
    """Interface for knowledge persistence.

    Implementations: JsonFileStore, PostgresStore, etc.
    """

    async def append(self, event: KnowledgeEvent) -> str:
        """Add an event to the store. Returns event_id."""
        ...

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        """Get an event by ID."""
        ...

    async def query(self, filters: QueryFilters) -> list[KnowledgeEvent]:
        """Query events with filters."""
        ...

    async def update(self, event: KnowledgeEvent) -> bool:
        """Update an existing event (version bump)."""
        ...

    async def delete(self, event_id: str) -> bool:
        """Delete an event (real delete — Soberania)."""
        ...

    async def count(self, filters: QueryFilters | None = None) -> int:
        """Count events matching filters."""
        ...

    async def version_snapshot(self, event_id: str) -> VersionSnapshot | None:
        """Create a snapshot of an event at its current version."""
        ...

    async def rollback(self, snapshot_id: str) -> bool:
        """Rollback an event to a previous snapshot."""
        ...

    async def export_all(self, format: str = "json") -> bytes:
        """Export all events (Soberania — user owns their data)."""
        ...

    async def delete_all(self) -> bool:
        """Delete all events (real delete — Soberania)."""
        ...
