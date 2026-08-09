"""Legacy Curator API backed by the official canonical Curator."""

from __future__ import annotations

from intent_kernel.adapters import (
    from_legacy_knowledge_event,
)
from intent_kernel.constitution.models import Constitution
from intent_kernel.contracts import (
    ConstitutionDecision,
    ConstitutionVerdict,
)
from intent_kernel.pkb.canonical_curator import CanonicalKnowledgeCurator
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import EventLifecycle


class LegacyKnowledgeCuratorAdapter:
    """Preserves the Sprint 0 Curator surface and thresholds."""

    def __init__(self, constitution: Constitution | None = None):
        self.constitution = constitution
        self._canonical = CanonicalKnowledgeCurator(
            enforce_nonempty=constitution is not None
        )

    async def evaluate(
        self,
        event: KnowledgeEvent,
        existing_events: list[KnowledgeEvent] | None = None,
    ) -> EventLifecycle:
        canonical = from_legacy_knowledge_event(event)
        existing = [
            from_legacy_knowledge_event(item)
            for item in (existing_events or [])
        ]
        decision = await self._canonical.curate(
            canonical,
            existing,
            ConstitutionVerdict(
                decision=ConstitutionDecision.ALLOW,
                reason="Legacy Curator compatibility",
            ),
        )
        try:
            return EventLifecycle(decision.lifecycle.value)
        except ValueError:
            return EventLifecycle.TRANSIENT

    async def should_promote(self, candidate: KnowledgeEvent) -> bool:
        return await self._canonical.should_promote(
            from_legacy_knowledge_event(candidate)
        )

    async def should_archive(self, approved: KnowledgeEvent) -> bool:
        return await self._canonical.should_archive(
            from_legacy_knowledge_event(approved)
        )


# Public legacy name retained for source compatibility.
KnowledgeCurator = LegacyKnowledgeCuratorAdapter
