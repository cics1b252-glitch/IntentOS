"""KnowledgeStore backed by PersistenceEngine.

This replaces the JsonFileStore with a backend-agnostic implementation
that uses the PersistenceEngine interface. Any engine that implements
the Protocol can be swapped in.

This is the "Persistence abstraída" from Sprint 1.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.persistence import MemoryPersistenceEngine
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import (
    Domain,
    EpistemicStatus,
    EventLifecycle,
    EventType,
    QueryFilters,
    VersionSnapshot,
    new_id,
    utcnow,
)


class PersistenceKnowledgeStore:
    """KnowledgeStore backed by any PersistenceEngine.

    This implementation is backend-agnostic — it works with
    JsonFile, PostgreSQL, SQLite, Memory, or any future engine.

    Soberania: export_all and delete_all use the engine's methods.
    Knowledge Heritage: all data is in the engine's native format.
    Continuity: swapping engines doesn't change this class.
    """

    def __init__(self, engine: Any = None):
        self.engine = engine or MemoryPersistenceEngine()
        self._prefix = "ke:"  # knowledge event prefix

    async def append(self, event: KnowledgeEvent) -> str:
        """Add an event to the store."""
        key = f"{self._prefix}{event.id}"
        data = self._serialize(event)
        await self.engine.write(key, data)
        return event.id

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        """Get an event by ID."""
        key = f"{self._prefix}{event_id}"
        data = await self.engine.read(key)
        if data is None:
            return None
        return self._deserialize(data)

    async def query(self, filters: QueryFilters) -> list[KnowledgeEvent]:
        """Query events with filters."""
        all_data = await self.engine.query(prefix=self._prefix)
        results = []

        for data in all_data:
            event = self._deserialize(data)
            if self._matches_filters(event, filters):
                results.append(event)

        # Sort
        reverse = filters.sort_order == "desc"
        if filters.sort_by == "created_at":
            results.sort(key=lambda e: e.created_at, reverse=reverse)
        elif filters.sort_by == "confidence":
            results.sort(key=lambda e: e.confidence, reverse=reverse)
        elif filters.sort_by == "version":
            results.sort(key=lambda e: e.version, reverse=reverse)

        return results[filters.offset : filters.offset + filters.limit]

    async def update(self, event: KnowledgeEvent) -> bool:
        """Update an existing event."""
        key = f"{self._prefix}{event.id}"
        existing = await self.engine.read(key)
        if existing is None:
            return False
        event.updated_at = utcnow()
        data = self._serialize(event)
        await self.engine.write(key, data)
        return True

    async def delete(self, event_id: str) -> bool:
        """Delete an event (real delete — Soberania)."""
        key = f"{self._prefix}{event_id}"
        return await self.engine.delete(key)

    async def count(self, filters: QueryFilters | None = None) -> int:
        """Count events."""
        if filters is None:
            return await self.engine.count(prefix=self._prefix)
        results = await self.query(filters)
        return len(results)

    async def version_snapshot(self, event_id: str) -> VersionSnapshot | None:
        """Create a snapshot of an event."""
        event = await self.get(event_id)
        if event is None:
            return None
        snapshot = VersionSnapshot(
            id=new_id(),
            event_id=event.id,
            version=event.version,
            content=event.content,
            reason="snapshot",
        )
        snap_key = f"snap:{snapshot.id}"
        await self.engine.write(snap_key, {
            "id": snapshot.id,
            "event_id": snapshot.event_id,
            "version": snapshot.version,
            "content": snapshot.content,
            "created_at": snapshot.created_at.isoformat(),
            "reason": snapshot.reason,
        })
        return snapshot

    async def rollback(self, snapshot_id: str) -> bool:
        """Rollback an event to a previous snapshot."""
        snap_key = f"snap:{snapshot_id}"
        snap_data = await self.engine.read(snap_key)
        if snap_data is None:
            return False
        event = await self.get(snap_data["event_id"])
        if event is None:
            return False
        event.content = snap_data["content"]
        event.version += 1
        event.parent_event_id = event.id
        event.updated_at = utcnow()
        return await self.update(event)

    async def export_all(self, format: str = "json") -> bytes:
        """Export all events (Soberania)."""
        return await self.engine.export_all(format)

    async def delete_all(self) -> bool:
        """Delete all events (real delete — Soberania)."""
        return await self.engine.clear()

    async def health_check(self) -> dict[str, Any]:
        """Health check for Monitor."""
        engine_health = await self.engine.health_check()
        event_count = await self.engine.count(prefix=self._prefix)
        return {
            "backend": self.engine.backend_type,
            "engine_healthy": engine_health.get("healthy", False),
            "events_stored": event_count,
        }

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def _serialize(self, event: KnowledgeEvent) -> dict:
        return {
            "id": event.id,
            "type": event.type.value,
            "domain": event.domain.value,
            "title": event.title,
            "content": event.content,
            "summary": event.summary,
            "confidence": event.confidence,
            "epistemic_status": event.epistemic_status.value,
            "lifecycle": event.lifecycle.value,
            "lifecycle_history": [
                {
                    "from_status": t.from_status.value,
                    "to_status": t.to_status.value,
                    "reason": t.reason,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in event.lifecycle_history
            ],
            "version": event.version,
            "parent_event_id": event.parent_event_id,
            "root_event_id": event.root_event_id,
            "source": event.source,
            "session_id": event.session_id,
            "tags": event.tags,
            "metadata": event.metadata,
            "created_at": event.created_at.isoformat(),
            "updated_at": event.updated_at.isoformat(),
            "expires_at": event.expires_at.isoformat() if event.expires_at else None,
        }

    def _deserialize(self, data: dict) -> KnowledgeEvent:
        from intent_kernel.pkb.models import LifecycleTransition
        return KnowledgeEvent(
            id=data["id"],
            type=EventType(data["type"]),
            domain=Domain(data["domain"]),
            title=data["title"],
            content=data["content"],
            summary=data["summary"],
            confidence=data["confidence"],
            epistemic_status=EpistemicStatus(data["epistemic_status"]),
            lifecycle=EventLifecycle(data["lifecycle"]),
            lifecycle_history=[
                LifecycleTransition(
                    from_status=EventLifecycle(t["from_status"]),
                    to_status=EventLifecycle(t["to_status"]),
                    reason=t["reason"],
                    timestamp=utcnow(),
                )
                for t in data.get("lifecycle_history", [])
            ],
            version=data["version"],
            parent_event_id=data.get("parent_event_id"),
            root_event_id=data.get("root_event_id"),
            source=data["source"],
            session_id=data["session_id"],
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=utcnow(),
            updated_at=utcnow(),
        )

    def _matches_filters(self, event: KnowledgeEvent, filters: QueryFilters) -> bool:
        if filters.domain and event.domain != filters.domain:
            return False
        if filters.event_type and event.type != filters.event_type:
            return False
        if filters.lifecycle and event.lifecycle != filters.lifecycle:
            return False
        if filters.min_confidence and event.confidence < filters.min_confidence:
            return False
        if filters.source and event.source != filters.source:
            return False
        if filters.tags:
            if not any(t in event.tags for t in filters.tags):
                return False
        if filters.search_text:
            text = filters.search_text.lower()
            if text not in event.title.lower() and text not in event.summary.lower():
                return False
        return True
