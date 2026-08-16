"""Canonical Resource Discovery Service — Movement 16.

DISCOVERY_ONLY

Responsibilities:
- accept discovery adapters
- request observations
- normalize discovery evidence
- deduplicate observations
- preserve provenance, timestamps, source identity, confidence
- return deterministic discovery snapshots
- expose discovery truth for inspection

Must NOT:
- execute, invoke providers/tools/resources
- create Missions, authorize, confirm, verify, complete
- bind executable resources, mutate RRM eligibility
- declare resources AVAILABLE/ELIGIBLE
- create provider usage or execution evidence
"""

from __future__ import annotations

from typing import Any

from intent_kernel.discovery.adapter import ResourceDiscoveryAdapter
from intent_kernel.discovery.models import (
    ResourceDiscoveryCorrelation,
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoverySnapshot,
    ResourceDiscoveryStatus,
)
from intent_kernel.discovery.registry import DiscoveryRegistry
from intent_kernel.time_utils import utc_iso


class CanonicalResourceDiscoveryService:
    """Read-only governed discovery service.

    Accepts adapters, orchestrates observations, maintains the discovery
    registry, and produces deterministic snapshots.  Discovery results
    never cross into RRM authority.
    """

    def __init__(self, rrm: Any = None) -> None:
        self._adapters: dict[str, ResourceDiscoveryAdapter] = {}
        self._registry = DiscoveryRegistry()
        self._rrm = rrm

    @property
    def registry(self) -> DiscoveryRegistry:
        return self._registry

    def register_adapter(self, adapter: ResourceDiscoveryAdapter) -> None:
        self._adapters[adapter.adapter_id] = adapter

    def unregister_adapter(self, adapter_id: str) -> bool:
        return self._adapters.pop(adapter_id, None) is not None

    def list_adapters(self) -> tuple[str, ...]:
        return tuple(self._adapters.keys())

    def observe(self, adapter_id: str) -> list[ResourceDiscoveryEvidence]:
        """Request a single adapter to observe and store evidence."""
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            return []
        try:
            raw = adapter.discover()
        except Exception:
            return []
        stored: list[ResourceDiscoveryEvidence] = []
        for evidence in raw:
            normalized = self._normalize(evidence)
            if self._registry.add(normalized):
                stored.append(normalized)
        return stored

    def observe_all(self) -> list[ResourceDiscoveryEvidence]:
        """Request all adapters to observe and store evidence."""
        stored: list[ResourceDiscoveryEvidence] = []
        for adapter_id in self._adapters:
            stored.extend(self.observe(adapter_id))
        return stored

    def get(self, discovery_id: str) -> ResourceDiscoveryEvidence | None:
        return self._registry.get(discovery_id)

    def list_by_kind(
        self, kind: ResourceDiscoveryKind
    ) -> tuple[ResourceDiscoveryEvidence, ...]:
        return self._registry.list_by_kind(kind)

    def list_by_source(
        self, source: str
    ) -> tuple[ResourceDiscoveryEvidence, ...]:
        return self._registry.list_by_source(source)

    def list_active(self) -> tuple[ResourceDiscoveryEvidence, ...]:
        return self._registry.list_active()

    def revoke(self, discovery_id: str) -> bool:
        return self._registry.revoke(discovery_id)

    def mark_stale(self, discovery_id: str) -> bool:
        return self._registry.mark_stale(discovery_id)

    def snapshot(self) -> ResourceDiscoverySnapshot:
        """Produce a deterministic read-only snapshot with optional RRM cross-reference."""
        discoveries = self._registry.list_all()
        correlations = self._cross_reference(discoveries)
        return ResourceDiscoverySnapshot(
            discoveries=discoveries,
            generated_at=utc_iso(),
            discovery_count=len(discoveries),
            rrm_cross_reference=correlations,
        )

    def _normalize(self, evidence: ResourceDiscoveryEvidence) -> ResourceDiscoveryEvidence:
        """Ensure provenance fields are set; strip invalid status values."""
        if not evidence.observed_at:
            return ResourceDiscoveryEvidence(
                discovery_id=evidence.discovery_id,
                resource_kind=evidence.resource_kind,
                resource_id=evidence.resource_id,
                display_name=evidence.display_name,
                capability_claims=evidence.capability_claims,
                source=evidence.source,
                source_type=evidence.source_type,
                observed_at=utc_iso(),
                observed_by=evidence.observed_by,
                status=evidence.status,
                confidence=max(0.0, min(1.0, evidence.confidence)),
                health_observed=evidence.health_observed,
                health_source=evidence.health_source,
                credential_required=evidence.credential_required,
                credential_available=evidence.credential_available,
                metadata=dict(evidence.metadata),
            )
        clamped = max(0.0, min(1.0, evidence.confidence))
        if clamped == evidence.confidence:
            return evidence
        return ResourceDiscoveryEvidence(
            discovery_id=evidence.discovery_id,
            resource_kind=evidence.resource_kind,
            resource_id=evidence.resource_id,
            display_name=evidence.display_name,
            capability_claims=evidence.capability_claims,
            source=evidence.source,
            source_type=evidence.source_type,
            observed_at=evidence.observed_at,
            observed_by=evidence.observed_by,
            status=evidence.status,
            confidence=clamped,
            health_observed=evidence.health_observed,
            health_source=evidence.health_source,
            credential_required=evidence.credential_required,
            credential_available=evidence.credential_available,
            metadata=dict(evidence.metadata),
        )

    def _cross_reference(
        self, discoveries: tuple[ResourceDiscoveryEvidence, ...]
    ) -> tuple[ResourceDiscoveryCorrelation, ...]:
        """Derive read-only RRM correlation.  Never mutates RRM."""
        if self._rrm is None:
            return tuple(
                ResourceDiscoveryCorrelation(
                    discovery_id=e.discovery_id,
                    resource_id=e.resource_id,
                    resource_kind=e.resource_kind,
                    rrm_registered=False,
                    rrm_available=False,
                    rrm_eligible=False,
                    correlation_status="no_rrm",
                )
                for e in discoveries
            )
        rrm = self._rrm
        correlations: list[ResourceDiscoveryCorrelation] = []
        for e in discoveries:
            registered = False
            available = False
            eligible = False
            if e.resource_kind is ResourceDiscoveryKind.PROVIDER:
                res = rrm.get_provider(e.resource_id) if hasattr(rrm, "get_provider") else None
                if res is not None:
                    registered = True
                    eligible = getattr(res, "is_eligible", False)
                    available = getattr(res, "status", None) is not None
            elif e.resource_kind is ResourceDiscoveryKind.CAPABILITY:
                res = rrm.get_capability(e.resource_id) if hasattr(rrm, "get_capability") else None
                if res is not None:
                    registered = True
                    eligible = getattr(res, "is_eligible", False)
                    available = getattr(res, "status", None) is not None
            elif e.resource_kind is ResourceDiscoveryKind.AGENT:
                res = rrm.get_agent(e.resource_id) if hasattr(rrm, "get_agent") else None
                if res is not None:
                    registered = True
                    eligible = getattr(res, "is_eligible", False)
                    available = getattr(res, "status", None) is not None
            elif e.resource_kind is ResourceDiscoveryKind.ENVIRONMENT:
                res = rrm.get_environment(e.resource_id) if hasattr(rrm, "get_environment") else None
                if res is not None:
                    registered = True
                    eligible = getattr(res, "is_eligible", False)
                    available = getattr(res, "status", None) is not None
            if registered:
                status = "exact_match" if eligible else "partial_match"
            else:
                status = "no_match"
            correlations.append(
                ResourceDiscoveryCorrelation(
                    discovery_id=e.discovery_id,
                    resource_id=e.resource_id,
                    resource_kind=e.resource_kind,
                    rrm_registered=registered,
                    rrm_available=available,
                    rrm_eligible=eligible,
                    correlation_status=status,
                )
            )
        return tuple(correlations)
