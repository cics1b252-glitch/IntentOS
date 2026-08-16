"""Discovery Registry — stores discovery evidence only (Movement 16).

DISCOVERY_REGISTRY_ONLY

Presence in this registry means: "observed".
It does NOT mean: "registered for runtime", "available", "eligible",
"authorized", "bound", or "trusted".
"""

from __future__ import annotations

from intent_kernel.discovery.models import (
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoveryStatus,
)


class DiscoveryRegistry:
    """In-memory store for discovery evidence records."""

    def __init__(self) -> None:
        self._evidence: dict[str, ResourceDiscoveryEvidence] = {}
        self._dedup: set[tuple[str, str, str]] = set()

    def add(self, evidence: ResourceDiscoveryEvidence) -> bool:
        """Store evidence, deduplicating on (kind, resource_id, source).

        Returns True if stored (new or updated); False if duplicate rejected.
        When a different source observes the same resource_id, a unique
        discovery_id is generated to prevent silent overwrites.
        """
        dedup_key = (
            evidence.resource_kind.value,
            evidence.resource_id,
            evidence.source,
        )
        if dedup_key in self._dedup:
            return False
        if evidence.discovery_id in self._evidence:
            existing = self._evidence[evidence.discovery_id]
            existing_dedup = (
                existing.resource_kind.value,
                existing.resource_id,
                existing.source,
            )
            if existing_dedup != dedup_key:
                import uuid as _uuid
                unique_id = f"{evidence.discovery_id}-{_uuid.uuid4().hex[:8]}"
                evidence = ResourceDiscoveryEvidence(
                    discovery_id=unique_id,
                    resource_kind=evidence.resource_kind,
                    resource_id=evidence.resource_id,
                    display_name=evidence.display_name,
                    capability_claims=evidence.capability_claims,
                    source=evidence.source,
                    source_type=evidence.source_type,
                    observed_at=evidence.observed_at,
                    observed_by=evidence.observed_by,
                    status=evidence.status,
                    confidence=evidence.confidence,
                    health_observed=evidence.health_observed,
                    health_source=evidence.health_source,
                    credential_required=evidence.credential_required,
                    credential_available=evidence.credential_available,
                    metadata=dict(evidence.metadata),
                )
        self._evidence[evidence.discovery_id] = evidence
        self._dedup.add(dedup_key)
        return True

    def get(self, discovery_id: str) -> ResourceDiscoveryEvidence | None:
        return self._evidence.get(discovery_id)

    def list_all(self) -> tuple[ResourceDiscoveryEvidence, ...]:
        return tuple(self._evidence.values())

    def list_by_kind(
        self, kind: ResourceDiscoveryKind
    ) -> tuple[ResourceDiscoveryEvidence, ...]:
        return tuple(
            e for e in self._evidence.values() if e.resource_kind is kind
        )

    def list_by_source(
        self, source: str
    ) -> tuple[ResourceDiscoveryEvidence, ...]:
        return tuple(e for e in self._evidence.values() if e.source == source)

    def list_active(self) -> tuple[ResourceDiscoveryEvidence, ...]:
        """Return evidence that has not been revoked or marked stale."""
        return tuple(
            e
            for e in self._evidence.values()
            if e.status
            in (
                ResourceDiscoveryStatus.OBSERVED,
                ResourceDiscoveryStatus.UNKNOWN,
            )
        )

    def revoke(self, discovery_id: str) -> bool:
        """Mark evidence as REVOKED.  Returns True if found and revoked."""
        evidence = self._evidence.get(discovery_id)
        if evidence is None:
            return False
        self._evidence[discovery_id] = ResourceDiscoveryEvidence(
            discovery_id=evidence.discovery_id,
            resource_kind=evidence.resource_kind,
            resource_id=evidence.resource_id,
            display_name=evidence.display_name,
            capability_claims=evidence.capability_claims,
            source=evidence.source,
            source_type=evidence.source_type,
            observed_at=evidence.observed_at,
            observed_by=evidence.observed_by,
            status=ResourceDiscoveryStatus.REVOKED,
            confidence=evidence.confidence,
            health_observed=evidence.health_observed,
            health_source=evidence.health_source,
            credential_required=evidence.credential_required,
            credential_available=evidence.credential_available,
            metadata=dict(evidence.metadata),
        )
        return True

    def mark_stale(self, discovery_id: str) -> bool:
        """Mark evidence as STALE.  Returns True if found and updated."""
        evidence = self._evidence.get(discovery_id)
        if evidence is None:
            return False
        self._evidence[discovery_id] = ResourceDiscoveryEvidence(
            discovery_id=evidence.discovery_id,
            resource_kind=evidence.resource_kind,
            resource_id=evidence.resource_id,
            display_name=evidence.display_name,
            capability_claims=evidence.capability_claims,
            source=evidence.source,
            source_type=evidence.source_type,
            observed_at=evidence.observed_at,
            observed_by=evidence.observed_by,
            status=ResourceDiscoveryStatus.STALE,
            confidence=evidence.confidence,
            health_observed=evidence.health_observed,
            health_source=evidence.health_source,
            credential_required=evidence.credential_required,
            credential_available=evidence.credential_available,
            metadata=dict(evidence.metadata),
        )
        return True

    @property
    def count(self) -> int:
        return len(self._evidence)
