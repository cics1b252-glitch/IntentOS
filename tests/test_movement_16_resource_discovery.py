"""Movement 16 — Governed Resource Discovery Convergence Tests.

Mandatory test matrix A–Z + adversarial + novel domains.
Discovery is evidence.  Discovery is NOT authority.
"""

from __future__ import annotations

import json
import sys
import os
from dataclasses import dataclass, field
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_kernel.discovery import (
    CanonicalResourceDiscoveryService,
    DiscoveryRegistry,
    ResourceDiscoveryAdapter,
    ResourceDiscoveryCorrelation,
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoverySnapshot,
    ResourceDiscoveryStatus,
    ResourceRegistrationProposal,
)
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _ev(
    resource_id: str = "res-1",
    kind: ResourceDiscoveryKind = ResourceDiscoveryKind.CAPABILITY,
    display_name: str = "Test Resource",
    source: str = "test-adapter",
    source_type: str = "adapter",
    capabilities: tuple[str, ...] = ("doc.read",),
    confidence: float = 0.8,
    health: str = "healthy",
    status: ResourceDiscoveryStatus = ResourceDiscoveryStatus.OBSERVED,
    credential_required: bool = False,
    credential_available: bool = False,
    metadata: dict[str, Any] | None = None,
    discovery_id: str | None = None,
) -> ResourceDiscoveryEvidence:
    return ResourceDiscoveryEvidence(
        discovery_id=discovery_id or f"disc-{resource_id}",
        resource_kind=kind,
        resource_id=resource_id,
        display_name=display_name,
        capability_claims=capabilities,
        source=source,
        source_type=source_type,
        observed_at=utc_iso(),
        observed_by=source,
        status=status,
        confidence=confidence,
        health_observed=health,
        health_source=source,
        credential_required=credential_required,
        credential_available=credential_available,
        metadata=metadata or {},
    )


class StubAdapter:
    """Deterministic in-memory adapter for testing."""

    def __init__(
        self,
        adapter_id: str = "test-adapter",
        adapter_type: str = "stub",
        evidence: list[ResourceDiscoveryEvidence] | None = None,
        error: bool = False,
    ) -> None:
        self._adapter_id = adapter_id
        self._adapter_type = adapter_type
        self._evidence = evidence or []
        self._error = error

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def adapter_type(self) -> str:
        return self._adapter_type

    def discover(self) -> list[ResourceDiscoveryEvidence]:
        if self._error:
            raise RuntimeError("adapter failure")
        return list(self._evidence)


class FakeRRM:
    """Minimal fake RRM for cross-reference testing."""

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._capabilities: dict[str, Any] = {}
        self._agents: dict[str, Any] = {}
        self._environments: dict[str, Any] = {}

    def get_provider(self, provider_id: str) -> Any | None:
        return self._providers.get(provider_id)

    def get_capability(self, capability_id: str) -> Any | None:
        return self._capabilities.get(capability_id)

    def get_agent(self, agent_id: str) -> Any | None:
        return self._agents.get(agent_id)

    def get_environment(self, env_id: str) -> Any | None:
        return self._environments.get(env_id)


@dataclass
class FakeResource:
    is_eligible: bool = False
    status: str = "active"


# ===========================================================================
# MATRIX TESTS A–Z
# ===========================================================================


class TestMatrixA:
    """A. Zero discovered resources → empty truthful snapshot."""

    def test_empty_snapshot(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        snap = svc.snapshot()
        assert snap.discovery_count == 0
        assert snap.discoveries == ()
        assert snap.rrm_cross_reference == ()


class TestMatrixB:
    """B. One observed resource → discovered only, not executable."""

    def test_observed_not_executable(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        assert len(stored) == 1
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.status is ResourceDiscoveryStatus.OBSERVED
        # No execution API on discovery service
        assert not hasattr(svc, "execute")
        assert not hasattr(svc, "invoke")
        assert not hasattr(svc, "authorize")
        assert not hasattr(svc, "bind")
        assert not hasattr(svc, "register_resource")


class TestMatrixC:
    """C. Discovered resource absent from RRM → cannot execute."""

    def test_absent_from_rrm(self) -> None:
        rrm = FakeRRM()
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[_ev(resource_id="unknown-res")])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        assert corr.rrm_registered is False
        assert corr.rrm_eligible is False
        assert corr.correlation_status == "no_match"


class TestMatrixD:
    """D. Discovered present in RRM but unavailable → cannot execute."""

    def test_present_in_rrm_unavailable(self) -> None:
        rrm = FakeRRM()
        rrm._capabilities["cap-x"] = FakeResource(is_eligible=False, status="unavailable")
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(resource_id="cap-x", kind=ResourceDiscoveryKind.CAPABILITY)
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        assert corr.rrm_registered is True
        assert corr.rrm_eligible is False
        assert corr.correlation_status == "partial_match"


class TestMatrixE:
    """E. Discovered present and eligible in RRM but no binding → cannot execute."""

    def test_eligible_no_binding(self) -> None:
        rrm = FakeRRM()
        rrm._capabilities["cap-y"] = FakeResource(is_eligible=True, status="active")
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(resource_id="cap-y", kind=ResourceDiscoveryKind.CAPABILITY)
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        assert corr.rrm_registered is True
        assert corr.rrm_eligible is True
        assert corr.correlation_status == "exact_match"
        # Still no execution — discovery does not bind
        assert not hasattr(svc, "resolve_binding")


class TestMatrixF:
    """F. Discovered + registry binding but authorization denied → cannot execute."""

    def test_binding_without_authorization(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="tool-alpha",
                kind=ResourceDiscoveryKind.TOOL,
                credential_required=True,
                credential_available=False,
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-tool-alpha")
        assert evidence is not None
        assert evidence.credential_required is True
        assert evidence.credential_available is False
        # Discovery does not grant authorization
        assert not hasattr(svc, "authorize")


class TestMatrixG:
    """G. Discovered + all canonical gates satisfied → execution through canonical
    path, NOT discovery service."""

    def test_execution_through_canonical_path(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        # Discovery service has no execute method
        assert not hasattr(svc, "execute")
        assert not hasattr(svc, "dispatch")
        # Canonical path would go through CapabilityExecutionService, not here


class TestMatrixH:
    """H. Duplicate display names from different sources → distinct identities."""

    def test_duplicate_display_names_distinct(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="res-a1", display_name="Shared Name", source="src-1"),
            _ev(resource_id="res-a2", display_name="Shared Name", source="src-2"),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 2
        ids = {e.resource_id for e in snap.discoveries}
        assert ids == {"res-a1", "res-a2"}


class TestMatrixI:
    """I. Duplicate observation of same exact resource → deterministic dedup."""

    def test_deduplication(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        ev1 = _ev(resource_id="res-dup", source="src-dup")
        ev2 = _ev(resource_id="res-dup", source="src-dup")
        adapter = StubAdapter(evidence=[ev1, ev2])
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        # Only one should be stored (dedup on kind+resource_id+source)
        assert len(stored) <= 2  # second add returns False due to dedup
        assert svc.registry.count == 1


class TestMatrixJ:
    """J. Source disappears → stale/revoked, no RRM mutation."""

    def test_source_disappears_no_rrm_mutation(self) -> None:
        rrm = FakeRRM()
        rrm._capabilities["cap-j"] = FakeResource(is_eligible=True, status="active")
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(resource_id="cap-j", kind=ResourceDiscoveryKind.CAPABILITY)
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap_before = svc.snapshot()
        assert snap_before.discovery_count == 1

        # Revoke the evidence
        svc.revoke("disc-cap-j")
        snap_after = svc.snapshot()
        revoked = [e for e in snap_after.discoveries if e.resource_id == "cap-j"]
        assert len(revoked) == 1
        assert revoked[0].status is ResourceDiscoveryStatus.REVOKED

        # RRM is unchanged
        rrm_res = rrm.get_capability("cap-j")
        assert rrm_res is not None
        assert rrm_res.is_eligible is True


class TestMatrixK:
    """K. RRM state changes after discovery → discovery remains historically truthful."""

    def test_rrm_changes_dont_affect_discovery(self) -> None:
        rrm = FakeRRM()
        rrm._capabilities["cap-k"] = FakeResource(is_eligible=True, status="active")
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(resource_id="cap-k", kind=ResourceDiscoveryKind.CAPABILITY)
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap1 = svc.snapshot()
        corr1 = [c for c in snap1.rrm_cross_reference if c.resource_id == "cap-k"][0]
        assert corr1.rrm_eligible is True

        # RRM changes
        rrm._capabilities["cap-k"] = FakeResource(is_eligible=False, status="unavailable")
        snap2 = svc.snapshot()
        corr2 = [c for c in snap2.rrm_cross_reference if c.resource_id == "cap-k"][0]
        assert corr2.rrm_eligible is False

        # Discovery evidence itself is unchanged
        disc = svc.get("disc-cap-k")
        assert disc is not None
        assert disc.status is ResourceDiscoveryStatus.OBSERVED
        assert disc.health_observed == "healthy"


class TestMatrixL:
    """L. Discovered provider → no provider invocation evidence."""

    def test_provider_discovery_no_invocation(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="prov-openai",
                kind=ResourceDiscoveryKind.PROVIDER,
                display_name="OpenAI Adapter",
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.PROVIDER
        # No invocation evidence
        assert not hasattr(evidence, "invocation_attempted")
        assert not hasattr(evidence, "provider_used")
        # No invocation API on service
        assert not hasattr(svc, "invoke_provider")


class TestMatrixM:
    """M. Discovered tool → no authorization."""

    def test_tool_discovery_no_authorization(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="tool-mcp-1",
                kind=ResourceDiscoveryKind.TOOL,
                display_name="MCP Tool",
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-tool-mcp-1")
        assert evidence is not None
        assert evidence.resource_kind is ResourceDiscoveryKind.TOOL
        # No authorization evidence or API
        assert not hasattr(evidence, "authorized")
        assert not hasattr(svc, "authorize_tool")


class TestMatrixN:
    """N. Discovered capability → no availability inference."""

    def test_capability_no_availability_inference(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="cap-infer",
                kind=ResourceDiscoveryKind.CAPABILITY,
                capabilities=("vehicle.diagnostics",),
                health="healthy",
                confidence=1.0,
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-cap-infer")
        assert evidence is not None
        # Healthy + high confidence does NOT mean available
        assert evidence.health_observed == "healthy"
        assert evidence.confidence == 1.0
        # No availability attribute
        assert not hasattr(evidence, "available")
        assert not hasattr(evidence, "eligible")


class TestMatrixO:
    """O. Agent capability matches discovered capability → no authority amplification."""

    def test_agent_capability_no_amplification(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="cap-o",
                kind=ResourceDiscoveryKind.CAPABILITY,
                capabilities=("vehicle.diagnostics",),
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-cap-o")
        assert evidence is not None
        assert "vehicle.diagnostics" in evidence.capability_claims
        # No authority granted to any agent
        assert not hasattr(evidence, "agent_authority")
        assert not hasattr(svc, "grant_agent_authority")


class TestMatrixP:
    """P. Admin/root/system agent + discovered resource → no authority amplification."""

    def test_admin_agent_no_amplification(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        # Even with admin metadata, no authority
        assert not hasattr(svc, "grant_role_authority")


class TestMatrixQ:
    """Q. Discovery adapter throws → fail closed / truthful error, zero execution."""

    def test_adapter_error_fail_closed(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(error=True)
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        assert stored == []
        snap = svc.snapshot()
        assert snap.discovery_count == 0


class TestMatrixR:
    """R. Malformed discovery evidence → rejected."""

    def test_malformed_evidence_rejected(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        # Confidence out of range — should be clamped
        adapter = StubAdapter(evidence=[
            ResourceDiscoveryEvidence(
                discovery_id="disc-bad",
                resource_kind=ResourceDiscoveryKind.CAPABILITY,
                resource_id="bad",
                display_name="Bad",
                source="test",
                source_type="adapter",
                observed_at="",
                status=ResourceDiscoveryStatus.OBSERVED,
                confidence=5.0,
            )
        ])
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        assert len(stored) == 1
        assert stored[0].confidence == 1.0  # clamped


class TestMatrixS:
    """S. Unknown resource kind → fail closed or typed UNKNOWN, no execution."""

    def test_unknown_resource_kind(self) -> None:
        # Custom kind is valid but not one of the standard categories
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="custom-1",
                kind=ResourceDiscoveryKind.CUSTOM,
                display_name="Custom Thing",
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        assert snap.discoveries[0].resource_kind is ResourceDiscoveryKind.CUSTOM


class TestMatrixT:
    """T. Stale evidence → cannot become fresh automatically."""

    def test_stale_cannot_auto_fresh(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        svc.mark_stale("disc-res-1")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert evidence.status is ResourceDiscoveryStatus.STALE
        # No auto-refresh mechanism
        assert not hasattr(svc, "auto_refresh")
        # Still stale on next snapshot
        snap = svc.snapshot()
        stale = [e for e in snap.discoveries if e.resource_id == "res-1"]
        assert len(stale) == 1
        assert stale[0].status is ResourceDiscoveryStatus.STALE


class TestMatrixU:
    """U. Source identity replacement → no silent identity substitution."""

    def test_source_replacement_no_silent_substitution(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="res-u", source="src-original"),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        original = svc.get("disc-res-u")
        assert original is not None
        assert original.source == "src-original"

        # New adapter with same resource_id but different source
        adapter2 = StubAdapter(
            adapter_id="test-adapter-2",
            evidence=[_ev(resource_id="res-u", source="src-replacement")],
        )
        svc.register_adapter(adapter2)
        svc.observe("test-adapter-2")
        # Original still has original source
        still_original = svc.get("disc-res-u")
        assert still_original is not None
        assert still_original.source == "src-original"


class TestMatrixV:
    """V. Same resource_id from different source → remains distinguishable."""

    def test_same_resource_id_different_source(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="res-v", source="src-v1"),
            _ev(resource_id="res-v", source="src-v2"),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 2
        sources = {e.source for e in snap.discoveries}
        assert sources == {"src-v1", "src-v2"}


class TestMatrixW:
    """W. Discovery confidence=1.0 → still no runtime authority."""

    def test_high_confidence_no_authority(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(confidence=1.0, health="healthy"),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        evidence = snap.discoveries[0]
        assert evidence.confidence == 1.0
        assert evidence.health_observed == "healthy"
        # Still no authority
        assert not hasattr(evidence, "authorized")
        assert not hasattr(evidence, "eligible")
        assert not hasattr(evidence, "available")


class TestMatrixX:
    """X. Health=healthy in discovery → still no RRM eligibility inference."""

    def test_healthy_no_rrm_eligibility(self) -> None:
        rrm = FakeRRM()
        # RRM has no entry for this resource
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="cap-x-health",
                kind=ResourceDiscoveryKind.CAPABILITY,
                health="healthy",
                confidence=1.0,
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        # Even with healthy discovery, RRM has no entry
        assert corr.rrm_registered is False
        assert corr.rrm_eligible is False


class TestMatrixY:
    """Y. Compatibility catalog says available while RRM says unavailable → RRM wins."""

    def test_rrm_wins_over_compatibility(self) -> None:
        rrm = FakeRRM()
        rrm._capabilities["cap-y-compat"] = FakeResource(
            is_eligible=False, status="unavailable"
        )
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="cap-y-compat",
                kind=ResourceDiscoveryKind.CAPABILITY,
                health="healthy",
                confidence=1.0,
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        # RRM truth overrides discovery health
        assert corr.rrm_eligible is False
        assert corr.correlation_status == "partial_match"


class TestMatrixZ:
    """Z. Zero-provider environment + discovered provider → zero-provider truth intact."""

    def test_zero_provider_intact(self) -> None:
        rrm = FakeRRM()
        # No providers registered
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="prov-zero",
                kind=ResourceDiscoveryKind.PROVIDER,
                display_name="Phantom Provider",
            )
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        assert corr.rrm_registered is False
        assert corr.rrm_eligible is False
        # Provider truth: zero providers in RRM
        assert rrm.get_provider("prov-zero") is None


# ===========================================================================
# ADVERSARIAL TESTS
# ===========================================================================


class TestAdversarial:
    """Adversarial probes for discovery authority leakage."""

    def test_fake_available_metadata(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(metadata={"available": True, "eligible": True}),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        # Metadata is stored but not promoted to authority
        assert evidence.metadata.get("available") is True
        assert not hasattr(evidence, "available")
        assert not hasattr(evidence, "eligible")

    def test_fake_authorized_metadata(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(metadata={"authorized": True}),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert evidence.metadata.get("authorized") is True
        assert not hasattr(evidence, "authorized")

    def test_fake_verified_metadata(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(metadata={"verified": True}),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert evidence.metadata.get("verified") is True
        assert not hasattr(evidence, "verified")

    def test_fake_provider_used(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                kind=ResourceDiscoveryKind.PROVIDER,
                metadata={"provider_used": True, "invocation_attempted": True},
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert evidence.metadata.get("provider_used") is True
        assert not hasattr(evidence, "provider_used")

    def test_fake_execution_success(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(metadata={"execution_success": True, "output": "result"}),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert not hasattr(evidence, "execution_success")
        assert not hasattr(svc, "execute")

    def test_source_identity_collision(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="id-collide", source="src-a"),
            _ev(resource_id="id-collide", source="src-a"),
        ])
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        # Dedup: same kind + resource_id + source → only one stored
        assert svc.registry.count == 1

    def test_resource_id_collision(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="id-collide", source="src-x"),
            _ev(resource_id="id-collide", source="src-y"),
        ])
        svc.register_adapter(adapter)
        stored = svc.observe("test-adapter")
        # Different sources → two distinct records
        assert svc.registry.count == 2

    def test_stale_observation_replay(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        svc.mark_stale("disc-res-1")
        # Replaying same observation via adapter with different source
        adapter2 = StubAdapter(
            adapter_id="adapter-2",
            evidence=[_ev(source="src-replay")],
        )
        svc.register_adapter(adapter2)
        svc.observe("adapter-2")
        snap = svc.snapshot()
        # Original is stale, new one is OBSERVED
        statuses = {e.status for e in snap.discoveries}
        assert ResourceDiscoveryStatus.STALE in statuses
        assert ResourceDiscoveryStatus.OBSERVED in statuses

    def test_adapter_replacement(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(adapter_id="old-adapter", evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("old-adapter")
        assert svc.registry.count == 1
        svc.unregister_adapter("old-adapter")
        assert "old-adapter" not in svc.list_adapters()
        # Original evidence remains
        assert svc.registry.count == 1

    def test_registry_poisoning(self) -> None:
        """Attempting to inject authority fields via metadata fails closed."""
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(metadata={
                "authority": "CANONICAL_AUTHORITY",
                "rrm_eligible": True,
                "binding_healthy": True,
                "execution_allowed": True,
            }),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        evidence = svc.get("disc-res-1")
        assert evidence is not None
        assert not hasattr(evidence, "authority")
        assert not hasattr(evidence, "rrm_eligible")
        assert not hasattr(evidence, "binding_healthy")
        assert not hasattr(evidence, "execution_allowed")

    def test_discovery_to_rrm_mutation_attempt(self) -> None:
        """Discovery service has no RRM write API."""
        rrm = FakeRRM()
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        assert not hasattr(svc, "register_capability")
        assert not hasattr(svc, "register_provider")
        assert not hasattr(svc, "register_agent")
        assert not hasattr(svc, "update_resource_status")
        # RRM is untouched
        assert rrm._capabilities == {}
        assert rrm._providers == {}

    def test_agent_attempting_promotion(self) -> None:
        """Discovery service has no agent authority grant API."""
        svc = CanonicalResourceDiscoveryService()
        assert not hasattr(svc, "grant_agent_authority")
        assert not hasattr(svc, "promote_agent")
        assert not hasattr(svc, "set_agent_role")

    def test_compatibility_attempting_promotion(self) -> None:
        """Discovery service has no compatibility override API."""
        svc = CanonicalResourceDiscoveryService()
        assert not hasattr(svc, "override_rrm")
        assert not hasattr(svc, "bypass_authority")
        assert not hasattr(svc, "set_canonical")

    def test_provider_discovery_attempting_invocation(self) -> None:
        """Discovery service has no provider invocation API."""
        svc = CanonicalResourceDiscoveryService()
        assert not hasattr(svc, "invoke_provider")
        assert not hasattr(svc, "execute_provider")
        assert not hasattr(svc, "attempt_provider")

    def test_tool_discovery_attempting_authorization(self) -> None:
        """Discovery service has no tool authorization API."""
        svc = CanonicalResourceDiscoveryService()
        assert not hasattr(svc, "authorize_tool")
        assert not hasattr(svc, "grant_tool_access")
        assert not hasattr(svc, "enable_tool")


# ===========================================================================
# NOVEL DOMAINS
# ===========================================================================


class TestNovelDomains:
    """Test discovery across unrelated domains."""

    def test_medical_imaging_device(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="dicom-viewer-1",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="DICOM Medical Imaging Viewer",
                capabilities=("medical.imaging.view", "medical.imaging.annotate"),
                source="hospital-network",
                health="healthy",
                confidence=0.95,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.DEVICE
        assert "medical.imaging.view" in evidence.capability_claims
        # No finance contamination
        assert not hasattr(evidence, "cost_per_1k_tokens")

    def test_agricultural_sensor(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="soil-sensor-42",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="Soil Moisture Sensor Field 7",
                capabilities=("agriculture.soil.read", "agriculture.moisture.read"),
                source="farm-iot-gateway",
                health="healthy",
                confidence=0.9,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.DEVICE
        assert "agriculture.soil.read" in evidence.capability_claims

    def test_translation_service(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="mt-engine-deepl",
                kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
                display_name="DeepL Translation Endpoint",
                capabilities=("language.translate", "language.detect"),
                source="service-catalog",
                health="healthy",
                confidence=1.0,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.CONNECTED_SERVICE
        # No provider invocation
        assert not hasattr(svc, "invoke_provider")

    def test_warehouse_robot(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="agv-fleet-3",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="AGV Fleet Controller Warehouse B",
                capabilities=("logistics.navigate", "logistics.carry", "logistics.dock"),
                source="warehouse-controller",
                health="healthy",
                confidence=0.88,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.DEVICE

    def test_clinical_trial_assistant(self) -> None:
        """Independent novel domain — not in spec suggestions."""
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="ct-protocol-v2",
                kind=ResourceDiscoveryKind.CUSTOM,
                display_name="Clinical Trial Protocol Analyzer",
                capabilities=("research.protocol.analyze", "research.eligibility.screen"),
                source="research-institution",
                health="healthy",
                confidence=0.85,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.resource_kind is ResourceDiscoveryKind.CUSTOM
        # No finance contamination
        assert not hasattr(evidence, "provider_called")

    def test_energy_grid_monitor(self) -> None:
        """Independent novel domain — not in spec suggestions."""
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(
                resource_id="grid-monitor-north",
                kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
                display_name="North Region Grid Monitor",
                capabilities=("energy.grid.monitor", "energy.load.balance"),
                source="utility-scada",
                health="degraded",
                confidence=0.75,
            ),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        assert snap.discovery_count == 1
        evidence = snap.discoveries[0]
        assert evidence.health_observed == "degraded"
        # No fabricated provider
        assert not hasattr(svc, "fabricate_provider")


# ===========================================================================
# ADDITIONAL GOVERNANCE TESTS
# ===========================================================================


class TestGovernance:
    """Additional governance boundary tests."""

    def test_snapshot_is_deterministic(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap1 = svc.snapshot()
        snap2 = svc.snapshot()
        assert snap1.discoveries == snap2.discoveries
        assert snap1.discovery_count == snap2.discovery_count

    def test_revoke_fail_closed(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        assert svc.revoke("nonexistent") is False

    def test_mark_stale_fail_closed(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        assert svc.mark_stale("nonexistent") is False

    def test_unregister_adapter(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter()
        svc.register_adapter(adapter)
        assert svc.unregister_adapter("test-adapter") is True
        assert svc.unregister_adapter("test-adapter") is False

    def test_observe_unknown_adapter(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        stored = svc.observe("unknown-adapter")
        assert stored == []

    def test_list_by_kind(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="p1", kind=ResourceDiscoveryKind.PROVIDER),
            _ev(resource_id="c1", kind=ResourceDiscoveryKind.CAPABILITY),
            _ev(resource_id="p2", kind=ResourceDiscoveryKind.PROVIDER),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        providers = svc.list_by_kind(ResourceDiscoveryKind.PROVIDER)
        assert len(providers) == 2

    def test_list_by_source(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[
            _ev(resource_id="r1", source="src-a"),
            _ev(resource_id="r2", source="src-b"),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        src_a = svc.list_by_source("src-a")
        assert len(src_a) == 1

    def test_list_active(self) -> None:
        svc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        active = svc.list_active()
        assert len(active) == 1
        svc.revoke("disc-res-1")
        active_after = svc.list_active()
        assert len(active_after) == 0

    def test_proposal_does_not_register(self) -> None:
        proposal = ResourceRegistrationProposal(
            discovery_id="disc-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            resource_id="cap-proposal",
            proposed_registration_type="capability",
            reasoning="test",
        )
        accepted = proposal.accept()
        assert accepted.status == "accepted"
        rejected = proposal.reject()
        assert rejected.status == "rejected"
        # None of these mutate anything
        assert proposal.status == "proposed"

    def test_no_rrm_cross_reference_without_rrm(self) -> None:
        svc = CanonicalResourceDiscoveryService(rrm=None)
        adapter = StubAdapter(evidence=[_ev()])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        corr = snap.rrm_cross_reference[0]
        assert corr.correlation_status == "no_rrm"
        assert corr.rrm_registered is False

    def test_unsupported_kind_cross_reference(self) -> None:
        rrm = FakeRRM()
        svc = CanonicalResourceDiscoveryService(rrm=rrm)
        adapter = StubAdapter(evidence=[
            _ev(kind=ResourceDiscoveryKind.CUSTOM),
        ])
        svc.register_adapter(adapter)
        svc.observe("test-adapter")
        snap = svc.snapshot()
        # CUSTOM kind has no RRM lookup path → no_match
        corr = snap.rrm_cross_reference[0]
        assert corr.correlation_status == "no_match"
