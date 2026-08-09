"""Single official Knowledge Pipeline for Intent OS v2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from intent_kernel.contracts import (
    ConstitutionDecision,
    ConstitutionEngine,
    ConstitutionVerdict,
    EventPublisher,
    KnowledgeEvent,
    KnowledgeLifecycle,
    KnowledgeStore,
)
from intent_kernel.pkb.canonical_curator import (
    CanonicalKnowledgeCurator,
    CurationAction,
    KnowledgeAuditEntry,
)
from intent_kernel.types import utcnow


@dataclass(slots=True)
class KnowledgeIngestReport:
    total: int = 0
    approved: int = 0
    candidate: int = 0
    transient: int = 0
    rejected: int = 0
    conflicts: int = 0
    merged: int = 0
    event_ids: list[str] = field(default_factory=list)
    audit: list[KnowledgeAuditEntry] = field(default_factory=list)


class KnowledgePipeline:
    """Constitution → Curator → Score → Conflict → Store → Audit."""

    def __init__(
        self,
        store: KnowledgeStore,
        curator: CanonicalKnowledgeCurator,
        constitution: ConstitutionEngine | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        self.store = store
        self.curator = curator
        self.constitution = constitution
        self.event_publisher = event_publisher
        self._audit_log: list[KnowledgeAuditEntry] = []

    async def ingest(
        self,
        events: list[KnowledgeEvent],
    ) -> KnowledgeIngestReport:
        report = KnowledgeIngestReport(total=len(events))
        existing = await self.store.query({"limit": 1000})

        for event in events:
            verdict = await self._evaluate_constitution(event)
            decision = await self.curator.curate(
                event,
                existing,
                verdict,
            )
            report.audit.append(decision.audit)
            self._audit_log.append(decision.audit)
            await self._publish_audit(decision.audit)

            if decision.action is CurationAction.DISCARD:
                report.transient += 1
                continue
            if decision.action is CurationAction.REJECT:
                report.rejected += 1
                continue
            if decision.action is CurationAction.CONFLICT:
                report.conflicts += 1
                report.rejected += 1
                continue
            if decision.action is CurationAction.MERGE:
                if await self._merge(decision.event, decision.existing_event):
                    report.merged += 1
                    if decision.existing_event is not None:
                        report.event_ids.append(decision.existing_event.id)
                continue

            self._transition(event, decision.lifecycle, decision.audit.reason)
            if decision.action is CurationAction.CANDIDATE:
                report.candidate += 1
            else:
                report.approved += 1

            event_id = await self.store.append(event)
            report.event_ids.append(event_id)
            existing.append(deepcopy(event))

        return report

    async def query(
        self,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeEvent]:
        return await self.store.query(filters or {})

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        return await self.store.get(event_id)

    async def delete(self, event_id: str) -> bool:
        return await self.store.delete(event_id)

    async def snapshot(self, event_id: str) -> Any | None:
        return await self.store.snapshot(event_id)

    async def rollback(self, snapshot_id: str) -> bool:
        return await self.store.rollback(snapshot_id)

    async def export(self) -> bytes:
        return await self.store.export()

    async def delete_all(self) -> bool:
        return await self.store.delete_all()

    async def count(
        self,
        filters: dict[str, Any] | None = None,
    ) -> int:
        return await self.store.count(filters)

    def get_audit_log(self) -> list[KnowledgeAuditEntry]:
        return list(self._audit_log)

    async def _evaluate_constitution(
        self,
        event: KnowledgeEvent,
    ) -> ConstitutionVerdict:
        if self.constitution is None:
            return ConstitutionVerdict(
                decision=ConstitutionDecision.ALLOW,
                reason="No Constitution engine configured",
            )
        return await self.constitution.evaluate(
            "knowledge.ingest",
            asdict(event),
            {
                "session_id": event.session_id,
                "correlation_id": event.correlation_id,
            },
        )

    async def _merge(
        self,
        incoming: KnowledgeEvent,
        existing: KnowledgeEvent | None,
    ) -> bool:
        if existing is None:
            return False
        merged = deepcopy(existing)
        merged.content = deepcopy(incoming.content)
        merged.summary = incoming.summary or existing.summary
        merged.confidence = max(existing.confidence, incoming.confidence)
        merged.version += 1
        merged.parent_event_id = existing.id
        merged.updated_at = utcnow()
        return await self.store.update(merged)

    @staticmethod
    def _transition(
        event: KnowledgeEvent,
        target: KnowledgeLifecycle,
        reason: str,
    ) -> None:
        previous = event.lifecycle
        transition_reason = {
            KnowledgeLifecycle.CANDIDATE: "Curator: candidate",
            KnowledgeLifecycle.APPROVED: "Curator: approved",
        }.get(target, reason)
        event.lifecycle_history.append(
            {
                "from_status": previous.value,
                "to_status": target.value,
                "reason": transition_reason,
                "timestamp": utcnow(),
            }
        )
        event.lifecycle = target
        event.updated_at = utcnow()

    async def _publish_audit(
        self,
        audit: KnowledgeAuditEntry,
    ) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.publish(
            "knowledge.audit",
            {
                "event_id": audit.event_id,
                "action": audit.action.value,
                "reason": audit.reason,
                "score": audit.score,
                "timestamp": audit.timestamp,
                "conflict_with": audit.conflict_with,
            },
            correlation_id=audit.event_id,
        )
