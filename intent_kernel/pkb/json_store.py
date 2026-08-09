"""JsonFileStore — Sprint 0 persistence implementation."""

from __future__ import annotations

import json
from pathlib import Path

from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import (
    EpistemicStatus,
    EventLifecycle,
    EventType,
    QueryFilters,
    VersionSnapshot,
    new_id,
    utcnow,
)


class JsonFileStore:
    """KnowledgeStore backed by JSON files on disk.

    Structure:
        ~/.intent-os/pkb/
        ├── events/
        │   ├── {uuid}.json
        │   └── ...
        ├── snapshots/
        │   ├── {uuid}.json
        │   └── ...
        └── index.json
    """

    def __init__(self, path: str = "~/.intent-os/pkb"):
        self.base_path = Path(path).expanduser()
        self.events_path = self.base_path / "events"
        self.snapshots_path = self.base_path / "snapshots"
        self.index_path = self.base_path / "index.json"

        self.events_path.mkdir(parents=True, exist_ok=True)
        self.snapshots_path.mkdir(parents=True, exist_ok=True)

    async def append(self, event: KnowledgeEvent) -> str:
        """Add an event to the store."""
        event_path = self.events_path / f"{event.id}.json"
        event_path.write_text(json.dumps(self._serialize(event), ensure_ascii=False, indent=2), encoding="utf-8")
        self._update_index(event)
        return event.id

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        """Get an event by ID."""
        event_path = self.events_path / f"{event_id}.json"
        if not event_path.exists():
            return None
        data = json.loads(event_path.read_text(encoding="utf-8"))
        return self._deserialize(data)

    async def query(self, filters: QueryFilters) -> list[KnowledgeEvent]:
        """Query events with filters."""
        results = []
        for event_path in self.events_path.glob("*.json"):
            data = json.loads(event_path.read_text(encoding="utf-8"))
            event = self._deserialize(data)

            if not self._matches_filters(event, filters):
                continue

            results.append(event)

        # Sort
        reverse = filters.sort_order == "desc"
        if filters.sort_by == "created_at":
            results.sort(key=lambda e: e.created_at, reverse=reverse)
        elif filters.sort_by == "confidence":
            results.sort(key=lambda e: e.confidence, reverse=reverse)
        elif filters.sort_by == "version":
            results.sort(key=lambda e: e.version, reverse=reverse)

        # Paginate
        return results[filters.offset : filters.offset + filters.limit]

    async def update(self, event: KnowledgeEvent) -> bool:
        """Update an existing event."""
        event_path = self.events_path / f"{event.id}.json"
        if not event_path.exists():
            return False
        event.updated_at = utcnow()
        event_path.write_text(json.dumps(self._serialize(event), ensure_ascii=False, indent=2), encoding="utf-8")
        self._update_index(event)
        return True

    async def delete(self, event_id: str) -> bool:
        """Delete an event (real delete — Soberania)."""
        event_path = self.events_path / f"{event_id}.json"
        if not event_path.exists():
            return False
        event_path.unlink()
        self._remove_from_index(event_id)
        return True

    async def count(self, filters: QueryFilters | None = None) -> int:
        """Count events matching filters."""
        if filters is None:
            return len(list(self.events_path.glob("*.json")))
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
        snap_path = self.snapshots_path / f"{snapshot.id}.json"
        snap_path.write_text(json.dumps({
            "id": snapshot.id,
            "event_id": snapshot.event_id,
            "version": snapshot.version,
            "content": snapshot.content,
            "created_at": snapshot.created_at.isoformat(),
            "reason": snapshot.reason,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot

    async def rollback(self, snapshot_id: str) -> bool:
        """Rollback an event to a previous snapshot."""
        snap_path = self.snapshots_path / f"{snapshot_id}.json"
        if not snap_path.exists():
            return False
        snap_data = json.loads(snap_path.read_text(encoding="utf-8"))
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
        events = []
        for event_path in sorted(self.events_path.glob("*.json")):
            events.append(json.loads(event_path.read_text(encoding="utf-8")))
        return json.dumps(events, ensure_ascii=False, indent=2).encode("utf-8")

    async def delete_all(self) -> bool:
        """Delete all events (real delete — Soberania)."""
        for event_path in self.events_path.glob("*.json"):
            event_path.unlink()
        for snap_path in self.snapshots_path.glob("*.json"):
            snap_path.unlink()
        if self.index_path.exists():
            self.index_path.unlink()
        return True

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _serialize(self, event: KnowledgeEvent) -> dict:
        """Serialize event to dict."""
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
        """Deserialize dict to KnowledgeEvent."""
        from intent_kernel.pkb.models import LifecycleTransition
        from intent_kernel.types import Domain, Severity

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
                    timestamp=utcnow(),  # simplified
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
            created_at=utcnow(),  # simplified from ISO string
            updated_at=utcnow(),
        )

    def _matches_filters(self, event: KnowledgeEvent, filters: QueryFilters) -> bool:
        """Check if an event matches the query filters."""
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

    def _update_index(self, event: KnowledgeEvent) -> None:
        """Update the index file."""
        index = self._read_index()
        index[event.id] = {
            "type": event.type.value,
            "domain": event.domain.value,
            "title": event.title,
            "lifecycle": event.lifecycle.value,
            "created_at": event.created_at.isoformat(),
        }
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    def _remove_from_index(self, event_id: str) -> None:
        """Remove an event from the index."""
        index = self._read_index()
        index.pop(event_id, None)
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_index(self) -> dict:
        """Read the index file."""
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return {}
