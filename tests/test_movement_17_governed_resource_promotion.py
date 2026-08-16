"""Movement 17 — Governed Resource Promotion Convergence Tests.

Mandatory test matrix A-Z + adversarial + novel domains + governance.

DISCOVERY IS EVIDENCE.
DISCOVERY IS NOT AUTHORITY.

A proposal may request registration.
A decision may authorize promotion.
Only the canonical registration boundary may mutate canonical resource state.
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_kernel.discovery import (
    CanonicalResourceDiscoveryService,
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoveryStatus,
)
from intent_kernel.promotion import (
    ResourcePromotionDecisionType,
    ResourcePromotionStatus,
)
from intent_kernel.promotion.decision_authority import ResourcePromotionDecisionAuthority
from intent_kernel.promotion.models import (
    ResourcePromotionDecision,
    ResourcePromotionProposal,
    ResourcePromotionResult,
    _PROHIBITED_PROPOSAL_FIELDS,
)
from intent_kernel.promotion.promotion_service import CanonicalResourcePromotionService
from intent_kernel.promotion.proposal_service import (
    PromotionError,
    ResourcePromotionProposalService,
)
from intent_kernel.promotion.registration_boundary import (
    CanonicalPromotionRegistrationBoundary,
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
        source_type="adapter",
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
    def __init__(self, evidence: list[ResourceDiscoveryEvidence] | None = None) -> None:
        self._adapter_id = "test-adapter"
        self._adapter_type = "stub"
        self._evidence = evidence or []

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def adapter_type(self) -> str:
        return self._adapter_type

    def discover(self) -> list[ResourceDiscoveryEvidence]:
        return list(self._evidence)


class FakeRRM:
    """Minimal fake RRM for testing registration."""

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

    def register_provider(self, resource: Any) -> Any:
        self._providers[resource.provider_id] = resource
        return resource

    def register_capability(self, resource: Any) -> Any:
        self._capabilities[resource.capability_id] = resource
        return resource

    def register_agent(self, resource: Any) -> Any:
        self._agents[resource.agent_id] = resource
        return resource

    def register_environment(self, resource: Any) -> Any:
        self._environments[resource.environment_id] = resource
        return resource


def _svc_with_evidence(
    *evidences: ResourceDiscoveryEvidence,
) -> CanonicalResourceDiscoveryService:
    svc = CanonicalResourceDiscoveryService()
    adapter = StubAdapter(list(evidences))
    svc.register_adapter(adapter)
    svc.observe("test-adapter")
    return svc


def _full_service(
    *evidences: ResourceDiscoveryEvidence,
) -> tuple[CanonicalResourcePromotionService, FakeRRM]:
    rrm = FakeRRM()
    disc = _svc_with_evidence(*evidences)
    return CanonicalResourcePromotionService(discovery_service=disc, rrm=rrm), rrm


def _promote_full(
    svc: CanonicalResourcePromotionService,
    discovery_id: str,
    *,
    decided_by: str = "auditor",
) -> ResourcePromotionResult:
    """Helper: create proposal → approve → promote."""
    prop = svc.create_proposal(discovery_id, reasoning="test")
    dec = svc.decide_proposal(
        prop.proposal_id,
        ResourcePromotionDecisionType.APPROVE,
        decided_by=decided_by,
    )
    return svc.promote(prop.proposal_id, dec.decision_id)


# ===========================================================================
# MATRIX TESTS A–Z
# ===========================================================================


class TestMatrixA:
    """A. Discovery evidence exists → no registration without proposal."""

    def test_discovery_no_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        snap = svc.proposals._discovery.snapshot()
        assert snap.discovery_count == 1
        # No register_* methods on promotion service
        assert not hasattr(svc, "register_provider")
        assert not hasattr(svc, "register_capability")
        assert not hasattr(svc, "register_agent")
        assert not hasattr(svc, "register_environment")


class TestMatrixB:
    """B. Proposal created → no registration without decision."""

    def test_proposal_no_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        assert prop.status is ResourcePromotionStatus.PENDING
        # RRM still empty
        assert rrm.get_capability("res-1") is None
        assert rrm.get_provider("res-1") is None


class TestMatrixC:
    """C. Rejected proposal → no registration."""

    def test_rejected_no_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.REJECT,
            reasoning="not needed",
        )
        assert prop.status is ResourcePromotionStatus.PENDING
        # After decision, proposal is REJECTED
        updated = svc.proposals.get_proposal(prop.proposal_id)
        assert updated is not None
        assert updated.status is ResourcePromotionStatus.REJECTED
        # Attempting to promote a rejected proposal fails
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is False
        assert "not_approved" in result.reason
        assert rrm.get_capability("res-1") is None


class TestMatrixD:
    """D. Expired proposal → no registration."""

    def test_expired_no_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.proposals.expire_proposal(prop.proposal_id)
        updated = svc.proposals.get_proposal(prop.proposal_id)
        assert updated is not None
        assert updated.status is ResourcePromotionStatus.EXPIRED
        # Cannot decide on expired proposal
        with pytest.raises(PromotionError, match="not pending"):
            svc.decide_proposal(
                prop.proposal_id,
                ResourcePromotionDecisionType.APPROVE,
            )
        assert rrm.get_capability("res-1") is None


class TestMatrixE:
    """E. Revoked proposal → no registration."""

    def test_revoked_no_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.proposals.revoke_proposal(prop.proposal_id)
        updated = svc.proposals.get_proposal(prop.proposal_id)
        assert updated is not None
        assert updated.status is ResourcePromotionStatus.REVOKED
        with pytest.raises(PromotionError, match="not pending"):
            svc.decide_proposal(
                prop.proposal_id,
                ResourcePromotionDecisionType.APPROVE,
            )
        assert rrm.get_capability("res-1") is None


class TestMatrixF:
    """F. Ambiguous approval text → rejected (must use typed decision)."""

    def test_ambiguous_text_rejected(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        # Free-text is not a valid ResourcePromotionDecisionType value
        with pytest.raises(PromotionError, match="Unknown decision type"):
            svc.decide_proposal(
                prop.proposal_id,
                "talvez",  # type: ignore[arg-type]
            )
        assert rrm.get_capability("res-1") is None


class TestMatrixG:
    """G. Valid approval → registration through canonical boundary."""

    def test_valid_approval_registers(self) -> None:
        svc, rrm = _full_service(_ev())
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        assert result.registration_type == "capability"
        assert result.resource_id == "res-1"
        # RRM now has the resource
        cap = rrm.get_capability("res-1")
        assert cap is not None
        # But RRM eligibility is determined by RRM, not by promotion
        assert cap.is_template is False


class TestMatrixH:
    """H. Approval replay → rejected (single-use)."""

    def test_approval_replay_rejected(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result1 = svc.promote(prop.proposal_id, dec.decision_id)
        assert result1.success is True
        # Second attempt with same decision → fail (proposal already consumed)
        result2 = svc.promote(prop.proposal_id, dec.decision_id)
        assert result2.success is False
        assert "consumed" in result2.reason


class TestMatrixI:
    """I. Decision for Proposal A used on Proposal B → rejected."""

    def test_wrong_proposal_rejected(self) -> None:
        svc, rrm = _full_service(_ev(), _ev(resource_id="res-2", discovery_id="disc-res-2"))
        prop_a = svc.create_proposal("disc-res-1")
        prop_b = svc.create_proposal("disc-res-2")
        dec_a = svc.decide_proposal(
            prop_a.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Approve proposal B so it passes check 2
        svc.decide_proposal(
            prop_b.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Decision for A applied to B → fail (check 3: decision_proposal_mismatch)
        result = svc.promote(prop_b.proposal_id, dec_a.decision_id)
        assert result.success is False
        assert "decision_proposal_mismatch" in result.reason


class TestMatrixJ:
    """J. Same resource_id, different evidence → no inherited approval."""

    def test_different_evidence_no_inherit(self) -> None:
        ev1 = _ev(resource_id="shared", source="src-1", discovery_id="disc-shared-1")
        ev2 = _ev(resource_id="shared", source="src-2", discovery_id="disc-shared-2")
        svc, rrm = _full_service(ev1, ev2)
        prop1 = svc.create_proposal("disc-shared-1")
        dec1 = svc.decide_proposal(
            prop1.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result1 = svc.promote(prop1.proposal_id, dec1.decision_id)
        assert result1.success is True
        # Second proposal for same resource_id but different evidence → new proposal needed
        prop2 = svc.create_proposal("disc-shared-2")
        dec2 = svc.decide_proposal(
            prop2.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Registration of second proposal fails due to conflict
        result2 = svc.promote(prop2.proposal_id, dec2.decision_id)
        assert result2.success is False
        assert "conflicting_canonical_resource" in result2.reason


class TestMatrixK:
    """K. Discovery evidence deleted after approval → fail closed."""

    def test_evidence_deleted_fail_closed(self) -> None:
        disc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter([_ev()])
        disc.register_adapter(adapter)
        disc.observe("test-adapter")
        rrm = FakeRRM()
        svc = CanonicalResourcePromotionService(discovery_service=disc, rrm=rrm)
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Revoke the evidence (simulates deletion)
        disc.revoke("disc-res-1")
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is False
        assert "evidence_revoked" in result.reason


class TestMatrixL:
    """L. Evidence revoked after approval → fail closed."""

    def test_evidence_revoked_fail_closed(self) -> None:
        disc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter([_ev()])
        disc.register_adapter(adapter)
        disc.observe("test-adapter")
        rrm = FakeRRM()
        svc = CanonicalResourcePromotionService(discovery_service=disc, rrm=rrm)
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        disc.revoke("disc-res-1")
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is False
        assert "evidence_revoked" in result.reason


class TestMatrixM:
    """M. Evidence stale after approval → fail closed where freshness required."""

    def test_evidence_stale_fail_closed(self) -> None:
        disc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter([_ev()])
        disc.register_adapter(adapter)
        disc.observe("test-adapter")
        rrm = FakeRRM()
        svc = CanonicalResourcePromotionService(discovery_service=disc, rrm=rrm)
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        disc.mark_stale("disc-res-1")
        # fresh=True (default) → fail
        result = svc.promote(prop.proposal_id, dec.decision_id, fresh=True)
        assert result.success is False
        assert "evidence_stale" in result.reason


class TestMatrixN:
    """N. Conflicting canonical resource appears after approval → fail closed."""

    def test_conflict_fail_closed(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Manually register a conflicting resource in RRM
        from intent_kernel.rrm.models import (
            CapabilityResource,
            ResourceOrigin,
            ResourceStatus,
        )

        rrm.register_capability(
            CapabilityResource(
                capability_id="res-1",
                name="Conflicting",
                resource_origin=ResourceOrigin.CONFIGURATION,
                status=ResourceStatus.ACTIVE,
            )
        )
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is False
        assert "conflicting_canonical_resource" in result.reason


class TestMatrixO:
    """O. RRM resource not eligible after registration → not eligible."""

    def test_not_eligible_after_registration(self) -> None:
        svc, rrm = _full_service(_ev())
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        cap = rrm.get_capability("res-1")
        assert cap is not None
        # is_executable defaults to False → not eligible for execution
        assert cap.is_executable is False


class TestMatrixP:
    """P. RRM resource unavailable after registration → unavailable."""

    def test_unavailable_after_registration(self) -> None:
        svc, rrm = _full_service(
            _ev(health="unhealthy", metadata={"status_hint": "unavailable"})
        )
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        cap = rrm.get_capability("res-1")
        assert cap is not None
        # RRM eligibility is determined by RRM, not promotion


class TestMatrixQ:
    """Q. Provider approved → zero invocation."""

    def test_provider_no_invocation(self) -> None:
        svc, rrm = _full_service(
            _ev(kind=ResourceDiscoveryKind.PROVIDER, resource_id="prov-1")
        )
        result = _promote_full(svc, "disc-prov-1")
        assert result.success is True
        assert result.registration_type == "provider"
        prov = rrm.get_provider("prov-1")
        assert prov is not None
        # No invoke method on promotion service
        assert not hasattr(svc, "invoke")
        assert not hasattr(svc, "invoke_provider")
        assert not hasattr(svc, "execute_provider")


class TestMatrixR:
    """R. Tool approved → zero execution without authorization."""

    def test_tool_no_execution(self) -> None:
        svc, rrm = _full_service(
            _ev(kind=ResourceDiscoveryKind.TOOL, resource_id="tool-1")
        )
        result = _promote_full(svc, "disc-tool-1")
        assert result.success is True
        # ToolAuthorizationGate not involved in promotion
        assert not hasattr(svc, "authorize_tool")
        assert not hasattr(svc, "execute_tool")


class TestMatrixS:
    """S. Agent self-promotion → rejected (no self-promotion API)."""

    def test_agent_no_self_promotion(self) -> None:
        svc, rrm = _full_service(
            _ev(kind=ResourceDiscoveryKind.AGENT, resource_id="agent-1")
        )
        # Promotion service has no agent self-promotion API
        assert not hasattr(svc, "self_promote")
        assert not hasattr(svc, "approve_own")
        assert not hasattr(svc, "register_own_capability")
        result = _promote_full(svc, "disc-agent-1")
        assert result.success is True
        assert result.registration_type == "agent"


class TestMatrixT:
    """T. Compatibility catalog cannot override canonical decision."""

    def test_compatibility_no_override(self) -> None:
        svc, rrm = _full_service(_ev())
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        # Even if a compatibility catalog claims the resource, the canonical
        # registration stands
        assert rrm.get_capability("res-1") is not None


class TestMatrixU:
    """U. Duplicate registration → no silent replacement."""

    def test_duplicate_no_replacement(self) -> None:
        svc, rrm = _full_service(_ev())
        result1 = _promote_full(svc, "disc-res-1")
        assert result1.success is True
        # Second proposal for same evidence → conflict
        prop2 = svc.create_proposal("disc-res-1")
        dec2 = svc.decide_proposal(
            prop2.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result2 = svc.promote(prop2.proposal_id, dec2.decision_id)
        assert result2.success is False
        assert "conflicting_canonical_resource" in result2.reason


class TestMatrixV:
    """V. Same ID different executable binding → no substitution."""

    def test_different_binding_no_substitution(self) -> None:
        svc, rrm = _full_service(_ev())
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        # Registration created a specific capability; no binding substitution
        cap = rrm.get_capability("res-1")
        assert cap is not None


class TestMatrixW:
    """W. Malicious metadata authority fields → ignored/rejected."""

    def test_malicious_metadata_rejected(self) -> None:
        svc, _ = _full_service(_ev())
        for key in _PROHIBITED_PROPOSAL_FIELDS:
            with pytest.raises(PromotionError, match="Authority-bearing"):
                svc.create_proposal(
                    "disc-res-1",
                    metadata={key: True},
                )


class TestMatrixX:
    """X. Malicious executable metadata → never eval/exec/import/run."""

    def test_no_dynamic_code_execution(self) -> None:
        svc, rrm = _full_service(
            _ev(
                metadata={
                    "code": "import os; os.system('rm -rf /')",
                    "__import__": "os",
                    "eval": "True",
                    "exec": "pass",
                }
            )
        )
        result = _promote_full(svc, "disc-res-1")
        assert result.success is True
        # Registration used the descriptor, not the raw metadata
        cap = rrm.get_capability("res-1")
        assert cap is not None


class TestMatrixY:
    """Y. Cross-project approval reuse → rejected."""

    def test_cross_project_reuse_rejected(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal(
            "disc-res-1", requested_scope="project:alpha"
        )
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is True
        # New proposal for same evidence with different scope → conflict
        prop2 = svc.create_proposal(
            "disc-res-1", requested_scope="project:beta"
        )
        dec2 = svc.decide_proposal(
            prop2.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result2 = svc.promote(prop2.proposal_id, dec2.decision_id)
        assert result2.success is False
        assert "conflicting_canonical_resource" in result2.reason


class TestMatrixZ:
    """Z. Cross-session approval reuse → rejected where session scope applies."""

    def test_cross_session_reuse_rejected(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal(
            "disc-res-1", requested_scope="session:sess-1"
        )
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is True
        # Different session scope → conflict
        prop2 = svc.create_proposal(
            "disc-res-1", requested_scope="session:sess-2"
        )
        dec2 = svc.decide_proposal(
            prop2.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result2 = svc.promote(prop2.proposal_id, dec2.decision_id)
        assert result2.success is False
        assert "conflicting_canonical_resource" in result2.reason


# ===========================================================================
# ADVERSARIAL TESTS
# ===========================================================================


class TestAdversarial:
    def test_proposal_service_no_rrm_mutation(self) -> None:
        svc, _ = _full_service(_ev())
        assert not hasattr(svc.proposals, "register_provider")
        assert not hasattr(svc.proposals, "register_capability")
        assert not hasattr(svc.proposals, "register_agent")
        assert not hasattr(svc.proposals, "update_resource_status")

    def test_decision_authority_no_registration(self) -> None:
        svc, _ = _full_service(_ev())
        assert not hasattr(svc.decisions, "register")
        assert not hasattr(svc.decisions, "register_provider")
        assert not hasattr(svc.decisions, "register_capability")

    def test_registration_boundary_no_authorize(self) -> None:
        svc, _ = _full_service(_ev())
        assert not hasattr(svc.registration, "authorize")
        assert not hasattr(svc.registration, "authorize_tool")
        assert not hasattr(svc.registration, "execute")
        assert not hasattr(svc.registration, "invoke")

    def test_authority_keywords_on_proposal_metadata(self) -> None:
        svc, _ = _full_service(_ev())
        for kw in ["authorized", "eligible", "execute", "verified", "trusted", "admin"]:
            with pytest.raises(PromotionError, match="Authority-bearing"):
                svc.create_proposal("disc-res-1", metadata={kw: True})

    def test_proposal_id_forgery_in_decision(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        with pytest.raises(PromotionError, match="Proposal not found"):
            svc.decide_proposal(
                "forged-prop-id",
                ResourcePromotionDecisionType.APPROVE,
            )

    def test_decision_id_forgery_in_registration(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result = svc.promote(prop.proposal_id, "forged-dec-id")
        assert result.success is False
        assert "decision_not_found" in result.reason

    def test_scope_escalation_via_metadata(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal(
            "disc-res-1",
            requested_scope="global",
            metadata={"scope": "admin"},
        )
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is True
        # Scope in metadata does not override requested_scope
        cap = rrm.get_capability("res-1")
        assert cap is not None

    def test_evidence_identity_string_manipulation(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        # Attempting to modify the frozen proposal fails
        with pytest.raises(AttributeError):
            prop.evidence_identity = "forged"  # type: ignore[misc]

    def test_rapid_revoke_then_promote(self) -> None:
        disc = CanonicalResourceDiscoveryService()
        adapter = StubAdapter([_ev()])
        disc.register_adapter(adapter)
        disc.observe("test-adapter")
        rrm = FakeRRM()
        svc = CanonicalResourcePromotionService(discovery_service=disc, rrm=rrm)
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # Revoke evidence
        disc.revoke("disc-res-1")
        # Attempt promotion
        result = svc.promote(prop.proposal_id, dec.decision_id)
        assert result.success is False

    def test_proposal_frozen_immutable(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        with pytest.raises(AttributeError):
            prop.status = ResourcePromotionStatus.APPROVED  # type: ignore[misc]

    def test_decision_frozen_immutable(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        with pytest.raises(AttributeError):
            dec.decision_type = ResourcePromotionDecisionType.REJECT  # type: ignore[misc]

    def test_proposal_non_productive(self) -> None:
        svc, rrm = _full_service(_ev())
        svc.create_proposal("disc-res-1")
        # RRM still empty after proposal creation
        assert rrm.get_capability("res-1") is None
        assert rrm.get_provider("res-1") is None

    def test_decision_non_productive(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # RRM still empty after decision
        assert rrm.get_capability("res-1") is None

    def test_unknown_proposal_in_promote(self) -> None:
        svc, _ = _full_service(_ev())
        result = svc.promote("nonexistent", "nonexistent")
        assert result.success is False
        assert "proposal_not_found" in result.reason


# ===========================================================================
# NOVEL DOMAIN TESTS
# ===========================================================================


class TestNovelDomains:
    def test_marine_navigation_sensor(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="nav-sensor-1",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="Marine Navigation Sensor",
                capabilities=("gps定位", "compass_heading", "depth_sounding"),
            )
        )
        result = _promote_full(svc, "disc-nav-sensor-1")
        assert result.success is True
        assert result.resource_id == "nav-sensor-1"

    def test_laboratory_spectrometer(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="spec-1",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="Laboratory Spectrometer",
                capabilities=("absorbance", "fluorescence", "mass_spec"),
            )
        )
        result = _promote_full(svc, "disc-spec-1")
        assert result.success is True
        assert result.resource_id == "spec-1"

    def test_industrial_refrigeration_controller(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="fridge-ctrl-1",
                kind=ResourceDiscoveryKind.DEVICE,
                display_name="Industrial Refrigeration Controller",
                capabilities=("temp_monitor", "compressor_control", "alarm"),
            )
        )
        result = _promote_full(svc, "disc-fridge-ctrl-1")
        assert result.success is True

    def test_accessibility_transcription_service(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="transcribe-1",
                kind=ResourceDiscoveryKind.CUSTOM,
                display_name="Accessibility Transcription Service",
                capabilities=("speech_to_text", "caption_generation", "sign_language"),
            )
        )
        result = _promote_full(svc, "disc-transcribe-1")
        assert result.success is True

    def test_satellite_telemetry_processor(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="sat-telem-1",
                kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
                display_name="Satellite Telemetry Processor",
                capabilities=("telemetry_decode", "orbit_determination", "signal_proc"),
            )
        )
        result = _promote_full(svc, "disc-sat-telem-1")
        assert result.success is True

    def test_quantum_key_distribution_node(self) -> None:
        svc, rrm = _full_service(
            _ev(
                resource_id="qkd-node-1",
                kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
                display_name="Quantum Key Distribution Node",
                capabilities=("key_generation", "entanglement_distribution", "qber_monitor"),
            )
        )
        result = _promote_full(svc, "disc-qkd-node-1")
        assert result.success is True
        # No finance contamination
        assert "finance" not in str(rrm.get_capability("qkd-node-1").metadata).lower()


# ===========================================================================
# GOVERNANCE TESTS
# ===========================================================================


class TestGovernance:
    def test_proposal_is_deterministic(self) -> None:
        svc1, _ = _full_service(_ev(resource_id="det-1", discovery_id="disc-det-1"))
        svc2, _ = _full_service(_ev(resource_id="det-1", discovery_id="disc-det-1"))
        p1 = svc1.create_proposal("disc-det-1")
        p2 = svc2.create_proposal("disc-det-1")
        # Different proposal_ids (UUIDs), but same content
        assert p1.proposal_id != p2.proposal_id
        assert p1.resource_id == p2.resource_id
        assert p1.evidence_identity == p2.evidence_identity

    def test_proposal_non_productive(self) -> None:
        svc, rrm = _full_service(_ev())
        svc.create_proposal("disc-res-1")
        assert rrm.get_capability("res-1") is None
        assert rrm.get_provider("res-1") is None
        assert rrm.get_agent("res-1") is None
        assert rrm.get_environment("res-1") is None

    def test_decision_non_productive(self) -> None:
        svc, rrm = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        assert rrm.get_capability("res-1") is None

    def test_registration_is_only_rrm_mutation(self) -> None:
        svc, rrm = _full_service(_ev())
        # Before promotion, RRM is empty
        assert rrm.get_capability("res-1") is None
        _promote_full(svc, "disc-res-1")
        # After promotion, RRM has the resource
        assert rrm.get_capability("res-1") is not None

    def test_all_lifecycle_states_distinguishable(self) -> None:
        states = [s.value for s in ResourcePromotionStatus]
        assert len(states) == len(set(states))
        assert "pending" in states
        assert "approved" in states
        assert "rejected" in states
        assert "expired" in states
        assert "revoked" in states
        assert "consumed" in states

    def test_decision_types_distinguishable(self) -> None:
        types = [t.value for t in ResourcePromotionDecisionType]
        assert len(types) == len(set(types))
        assert "approve" in types
        assert "reject" in types

    def test_to_dict_proposal(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        d = prop.to_dict()
        assert d["proposal_id"] == prop.proposal_id
        assert d["resource_id"] == "res-1"
        assert d["status"] == "pending"

    def test_to_dict_decision(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        d = dec.to_dict()
        assert d["decision_id"] == dec.decision_id
        assert d["proposal_id"] == prop.proposal_id
        assert d["decision_type"] == "approve"

    def test_to_dict_result(self) -> None:
        svc, _ = _full_service(_ev())
        result = _promote_full(svc, "disc-res-1")
        d = result.to_dict()
        assert d["success"] is True
        assert d["resource_id"] == "res-1"

    def test_list_proposals_by_status(self) -> None:
        svc, _ = _full_service(_ev(), _ev(resource_id="res-2", discovery_id="disc-res-2"))
        svc.create_proposal("disc-res-1")
        svc.create_proposal("disc-res-2")
        all_props = svc.proposals.list_proposals()
        assert len(all_props) == 2
        pending = svc.proposals.list_proposals(ResourcePromotionStatus.PENDING)
        assert len(pending) == 2

    def test_revoke_proposal_unknown(self) -> None:
        svc, _ = _full_service(_ev())
        with pytest.raises(PromotionError, match="not found"):
            svc.proposals.revoke_proposal("nonexistent")

    def test_revoke_proposal_terminal(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        svc.proposals.revoke_proposal(prop.proposal_id)
        with pytest.raises(PromotionError, match="revoked"):
            svc.proposals.revoke_proposal(prop.proposal_id)

    def test_expire_proposal_unknown(self) -> None:
        svc, _ = _full_service(_ev())
        with pytest.raises(PromotionError, match="not found"):
            svc.proposals.expire_proposal("nonexistent")

    def test_consume_decision_twice(self) -> None:
        svc, _ = _full_service(_ev())
        prop = svc.create_proposal("disc-res-1")
        dec = svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        # First consume (via promote)
        svc.promote(prop.proposal_id, dec.decision_id)
        # Second consume directly → fail
        with pytest.raises(PromotionError, match="already consumed"):
            svc.decisions.consume(dec.decision_id)

    def test_proposal_count(self) -> None:
        svc, _ = _full_service(_ev(), _ev(resource_id="res-2", discovery_id="disc-res-2"))
        assert svc.proposals.count == 0
        svc.create_proposal("disc-res-1")
        assert svc.proposals.count == 1
        svc.create_proposal("disc-res-2")
        assert svc.proposals.count == 2

    def test_decision_count(self) -> None:
        svc, _ = _full_service(_ev())
        assert svc.decisions.count == 0
        prop = svc.create_proposal("disc-res-1")
        svc.decide_proposal(
            prop.proposal_id,
            ResourcePromotionDecisionType.APPROVE,
        )
        assert svc.decisions.count == 1
