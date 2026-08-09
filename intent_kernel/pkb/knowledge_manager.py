"""KnowledgeManager — orchestrates Curator + Store for the PKB."""

from __future__ import annotations

from dataclasses import asdict

from intent_kernel.adapters import (
    LegacyConstitutionEngineAdapter,
    LegacyKnowledgeStoreAdapter,
    from_legacy_knowledge_event,
    to_legacy_knowledge_event,
)
from intent_kernel.constitution.models import Constitution
from intent_kernel.contracts import (
    ConstitutionEngine,
    EventPublisher,
    KnowledgeStore,
)
from intent_kernel.pkb.canonical_curator import CanonicalKnowledgeCurator
from intent_kernel.pkb.json_store import JsonFileStore
from intent_kernel.pkb.knowledge_pipeline import KnowledgePipeline
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import (
    IngestResult,
    QueryFilters,
    VersionSnapshot,
)


class KnowledgeManager:
    """Orchestrates knowledge ingestion, curation, and persistence.

    Flow:
        Events → Curator.evaluate → lifecycle classification
        Approved/Constitutional → Store.append + commit
        Transient → discarded
        Candidate → buffered
    """

    def __init__(
        self,
        store: KnowledgeStore | JsonFileStore | None = None,
        constitution: Constitution | None = None,
        *,
        legacy_store: JsonFileStore | None = None,
        constitution_engine: ConstitutionEngine | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        concrete_store = legacy_store
        if store is None:
            concrete_store = concrete_store or JsonFileStore()
            self._store: KnowledgeStore = LegacyKnowledgeStoreAdapter(
                concrete_store
            )
        elif isinstance(store, KnowledgeStore):
            self._store = store
            concrete_store = concrete_store or getattr(store, "_store", None)
        else:
            concrete_store = store
            self._store = LegacyKnowledgeStoreAdapter(store)

        # Compatibility facade for callers that still access the legacy store.
        self.store = concrete_store or self._store
        self.curator = CanonicalKnowledgeCurator(
            enforce_nonempty=constitution is not None
        )
        if constitution_engine is None and constitution is not None:
            constitution_engine = LegacyConstitutionEngineAdapter(
                constitution
            )
        self.pipeline = KnowledgePipeline(
            store=self._store,
            curator=self.curator,
            constitution=constitution_engine,
            event_publisher=event_publisher,
        )

    async def ingest(self, events: list[KnowledgeEvent]) -> IngestResult:
        """Ingest a batch of events through the Curator into the PKB."""
        canonical = [
            from_legacy_knowledge_event(event)
            for event in events
        ]
        report = await self.pipeline.ingest(canonical)
        return IngestResult(
            total=report.total,
            approved=report.approved,
            candidate=report.candidate,
            transient=report.transient,
            rejected=report.rejected + report.conflicts,
            event_ids=list(report.event_ids),
        )

    async def query(self, filters: QueryFilters) -> list[KnowledgeEvent]:
        """Query the PKB."""
        canonical = await self.pipeline.query(asdict(filters))
        return [to_legacy_knowledge_event(event) for event in canonical]

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        """Get a specific event."""
        event = await self.pipeline.get(event_id)
        return (
            to_legacy_knowledge_event(event)
            if event is not None
            else None
        )

    async def snapshot(self, event_id: str) -> VersionSnapshot | None:
        """Create a snapshot of an event."""
        return await self.pipeline.snapshot(event_id)

    async def rollback(self, snapshot_id: str) -> bool:
        """Rollback an event to a previous version."""
        return await self.pipeline.rollback(snapshot_id)

    async def count(self) -> int:
        """Count all events in the PKB."""
        return await self.pipeline.count()

    async def export(self) -> bytes:
        """Export all events (Soberania)."""
        return await self.pipeline.export()

    async def delete_all(self) -> bool:
        """Delete all events (Soberania)."""
        return await self.pipeline.delete_all()

    async def delete(self, event_id: str) -> bool:
        """Delete one event through the canonical pipeline."""
        return await self.pipeline.delete(event_id)

    def audit_log(self):
        """Return immutable snapshots of the official curation audit."""
        return self.pipeline.get_audit_log()
