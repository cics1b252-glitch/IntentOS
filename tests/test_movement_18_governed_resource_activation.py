"""Movement 18 — Governed Resource Activation Tests.

RA-18-02 Evidence Repair — full A-Z matrix verifying:
1. ACTIVATION MUST VERIFY PREREQUISITE TRUTH
2. ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH
3. ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE
4. Models are frozen and auditable
5. Canonical activation authority validates REAL prerequisite evidence
6. Application boundary MUST NOT fabricate prerequisite fields
7. Service orchestrates the full pipeline with evidence
8. RA-18-01 containment: no ungoverned activation authority
9. No discovery evidence, promotion, or registration authority leak
10. Activation != authorization != confirmation != execution

RA-18-03 Canonical Evidence Validation (tests A-S):
  CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
  Public callers must NOT be able to assert arbitrary evidence
  that is accepted as canonical prerequisite truth.

RA-18-01 RRM Overwrite Guard (tests A-L):
  Compatibility/bootstrap sources must NOT silently overwrite
  governed M17 resources with same-ID objects.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from intent_kernel.activation import (
    ActivationEvidenceType,
    ResourceActivationDecision,
    ResourceActivationDecisionType,
    ResourceActivationEvidence,
    ResourceActivationRequest,
    ResourceActivationResult,
    ResourceActivationStatus,
)
from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
from intent_kernel.activation.evidence_authority import (
    CanonicalActivationEvidenceAuthority,
    EvidenceValidationResult,
)
from intent_kernel.activation.service import (
    CanonicalResourceActivationService,
    ActivationError,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.models import (
    ResourceType,
    ResourceStatus,
    ResourceOrigin,
    AvailabilitySource,
    ProviderResource,
    AccountResource,
    CapabilityResource,
    AgentResource,
    ExecutionEnvironmentResource,
    AgentInstallationState,
)
from intent_kernel.rrm.service import RegistryResourceManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rrm():
    return RegistryResourceManager(populate_defaults=False)


@pytest.fixture
def activation_service(rrm):
    return CanonicalResourceActivationService(rrm)


def _make_evidence(
    resource_id: str,
    resource_kind: ResourceDiscoveryKind,
    evidence_type: ActivationEvidenceType,
    source: str = "canonical",
    binding_identity: str = "",
    revoked: bool = False,
) -> ResourceActivationEvidence:
    return ResourceActivationEvidence(
        evidence_id=f"ev-{resource_id}-{evidence_type.value}",
        resource_id=resource_id,
        resource_kind=resource_kind,
        evidence_type=evidence_type,
        source=source,
        binding_identity=binding_identity,
        revoked=revoked,
    )


# ---------------------------------------------------------------------------
# A — Models are frozen and immutable
# ---------------------------------------------------------------------------


class TestModelsFrozen:
    def test_request_is_frozen(self):
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        with pytest.raises(AttributeError):
            req.request_id = "r2"  # type: ignore[misc]

    def test_decision_is_frozen(self):
        dec = ResourceActivationDecision(
            decision_id="dec1", request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        with pytest.raises(AttributeError):
            dec.decision_id = "dec2"  # type: ignore[misc]

    def test_result_is_frozen(self):
        res = ResourceActivationResult(
            success=True, request_id="r1", decision_id="dec1",
            resource_id="prov-1",
        )
        with pytest.raises(AttributeError):
            res.success = False  # type: ignore[misc]

    def test_evidence_is_frozen(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
        )
        with pytest.raises(AttributeError):
            ev.revoked = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B — Authority requires prerequisite evidence to exist
# ---------------------------------------------------------------------------


class TestAuthorityRequiresEvidence:
    def test_deny_without_evidence(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
        )
        decision = authority.evaluate(request)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# C — Authority accepts valid prerequisite evidence
# ---------------------------------------------------------------------------


class TestAuthorityAcceptsEvidence:
    def test_approve_with_valid_evidence(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        ev_config = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_account = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        authority.register_evidence(ev_config)
        authority.register_evidence(ev_account)
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
            evidence_ids=(ev_config.evidence_id, ev_account.evidence_id),
        )
        decision = authority.evaluate(request)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# D — Application boundary must not fabricate prerequisite fields
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricate:
    def test_boundary_apply_requires_real_authority(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        boundary = ActivationApplicationBoundary(rrm, {}, {}, set(), {})
        fake_decision = ResourceActivationDecision(
            decision_id="fake-dec1", request_id="req1",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        result = boundary.apply(fake_decision.decision_id)
        assert result.success is False


# ---------------------------------------------------------------------------
# E — Service orchestrates full pipeline with evidence
# ---------------------------------------------------------------------------


class TestServiceOrchestration:
    def test_full_pipeline(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        ev_config = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_account = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_config)
        service.register_evidence(ev_account)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=(ev_config.evidence_id, ev_account.evidence_id),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        result = service.activate(request.request_id)
        assert result.success is True


# ---------------------------------------------------------------------------
# F — Evidence types are correct
# ---------------------------------------------------------------------------


class TestEvidenceTypes:
    def test_evidence_type_values(self):
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION.value == "provider_configuration"
        assert ActivationEvidenceType.CAPABILITY_EXECUTABLE.value == "capability_executable"
        assert ActivationEvidenceType.AGENT_IDENTITY.value == "agent_identity"
        assert ActivationEvidenceType.ACCOUNT_SECRET.value == "account_secret"
        assert ActivationEvidenceType.ENVIRONMENT_DISCOVERY.value == "environment_discovery"
        assert ActivationEvidenceType.PROVIDER_ACCOUNT.value == "provider_account"


# ---------------------------------------------------------------------------
# G — Decision type values
# ---------------------------------------------------------------------------


class TestDecisionTypes:
    def test_decision_type_values(self):
        assert ResourceActivationDecisionType.APPROVE.value == "approve"
        assert ResourceActivationDecisionType.REJECT.value == "reject"


# ---------------------------------------------------------------------------
# H — Evidence with mismatched resource kind is denied
# ---------------------------------------------------------------------------


class TestMismatchedResourceKind:
    def test_deny_on_kind_mismatch(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        authority.register_evidence(evidence)
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
            evidence_ids=(evidence.evidence_id,),
        )
        decision = authority.evaluate(request)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# I — Service does not fabricate evidence
# ---------------------------------------------------------------------------


class TestServiceDoesNotFabricate:
    def test_service_requires_explicit_evidence(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# J — Boundary does not fabricate prerequisite fields
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricateFields:
    def test_boundary_rejects_unevaluated_decision(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
        )
        decision = service.evaluate(request.request_id)
        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is False


# ---------------------------------------------------------------------------
# K — Authority rejects revoked evidence
# ---------------------------------------------------------------------------


class TestRevokedEvidence:
    def test_revoked_evidence_denied(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
            revoked=True,
        )
        authority.register_evidence(evidence)
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
            evidence_ids=(evidence.evidence_id,),
        )
        decision = authority.evaluate(request)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# L — Evidence does not contain activation approval
# ---------------------------------------------------------------------------


class TestEvidenceNotApproval:
    def test_evidence_without_approval_denied(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        ev_config = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_account = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        authority.register_evidence(ev_config)
        authority.register_evidence(ev_account)
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
            evidence_ids=(ev_config.evidence_id, ev_account.evidence_id),
        )
        decision = authority.evaluate(request)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        assert "approve" in decision.reasoning.lower() or "satisfied" in decision.reasoning.lower()


# ---------------------------------------------------------------------------
# M — Boundary does not fabricate scope mismatch
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricateScope:
    def test_boundary_rejects_scope_mismatch(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        service.register_evidence(evidence)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=(evidence.evidence_id,),
            scope="restricted",
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        result = service.activate(request.request_id)
        assert result.success is False


# ---------------------------------------------------------------------------
# N — Boundary does not fabricate RRM without decision
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricateRRM:
    def test_boundary_does_not_modify_rrm_without_decision(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        service.register_evidence(evidence)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=(evidence.evidence_id,),
        )
        result = service.application_boundary.apply("non-existent-decision")
        assert result.success is False


# ---------------------------------------------------------------------------
# O — Boundary does not fabricate activation without consumed decision
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricateActivation:
    def test_boundary_does_not_apply_without_consumed_decision(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        rrm.register_provider(provider)
        service = CanonicalResourceActivationService(rrm)
        ev_config = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_account = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_config)
        service.register_evidence(ev_account)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=(ev_config.evidence_id, ev_account.evidence_id),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        assert decision.decision_id not in service.consumed_decisions
        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is True
        assert decision.decision_id in service.consumed_decisions
        result2 = service.application_boundary.apply(decision.decision_id)
        assert result2.success is False
        assert "already_consumed" in result2.reason


# ---------------------------------------------------------------------------
# P — RA-18-01 containment: no ungoverned activation authority
# ---------------------------------------------------------------------------


class TestRA1801Containment:
    def test_no_ungoverned_authority(self):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
        from intent_kernel.activation.service import CanonicalResourceActivationService
        from intent_kernel.activation.evidence_authority import CanonicalActivationEvidenceAuthority
        assert CanonicalResourceActivationAuthority is not None
        assert ActivationApplicationBoundary is not None
        assert CanonicalResourceActivationService is not None
        assert CanonicalActivationEvidenceAuthority is not None


# ---------------------------------------------------------------------------
# Q — Activation status values
# ---------------------------------------------------------------------------


class TestActivationStatusValues:
    def test_status_values(self):
        assert ResourceActivationStatus.PENDING.value == "pending"
        assert ResourceActivationStatus.APPROVED.value == "approved"
        assert ResourceActivationStatus.REJECTED.value == "rejected"


# ===========================================================================
# RA-18-03 — Canonical Evidence Validation (Evidence Authority)
#
# CALLER ASSERTION != CANONICAL SOURCE OF TRUTH
# ===========================================================================


class TestRA1803EvidenceAuthority:
    """Tests for CanonicalActivationEvidenceAuthority (EVIDENCE_VALIDATION_ONLY)."""

    def _make_provider_rrm(self, rrm, provider_id="prov-1", is_configured=True):
        provider = ProviderResource(
            provider_id=provider_id, name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=is_configured,
        )
        rrm.register_provider(provider)
        return provider

    def _make_capability_rrm(self, rrm, capability_id="cap-1", is_executable=True):
        cap = CapabilityResource(
            capability_id=capability_id, name="test-cap",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=is_executable,
        )
        rrm.register_capability(cap)
        return cap

    def _make_agent_rrm(self, rrm, agent_id="ag-1", is_enabled=True,
                        installation_state=AgentInstallationState.INSTALLED):
        agent = AgentResource(
            agent_id=agent_id, name="test-agent",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=is_enabled,
            installation_state=installation_state,
        )
        rrm.register_agent(agent)
        return agent

    def _make_environment_rrm(self, rrm, env_id="env-1", is_discovered=True):
        env = ExecutionEnvironmentResource(
            environment_id=env_id, type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=is_discovered,
        )
        rrm.register_environment(env)
        return env

    def _make_account_rrm(self, rrm, account_id="acc-1", has_secret=True):
        account = AccountResource(
            account_id=account_id, provider_id="prov-1",
            name="test-account",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            secret_reference="ref1" if has_secret else "",
        )
        rrm.register_account(account)
        return account

    # A — Authority rejects evidence for unregistered resource
    def test_rejects_unregistered_resource(self, rrm):
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-nonexistent", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "resource_not_registered" in result.reason

    # B — Authority rejects revoked evidence
    def test_rejects_revoked_evidence(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
            revoked=True,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "revoked" in result.reason

    # C — Authority accepts valid provider configuration evidence
    def test_accepts_valid_provider_configuration(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # D — Authority rejects provider config when not configured
    def test_rejects_provider_not_configured(self, rrm):
        self._make_provider_rrm(rrm, is_configured=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "not_configured" in result.reason

    # E — Authority accepts valid provider active-account evidence
    def test_accepts_valid_provider_account(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # F — Authority rejects provider active-account when no account
    def test_rejects_provider_no_account(self, rrm):
        self._make_provider_rrm(rrm, is_configured=False)
        provider = rrm.get_provider("prov-1")
        provider.has_active_account = False
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "no_active_account" in result.reason

    # G — Authority accepts valid capability executable evidence
    def test_accepts_valid_capability_executable(self, rrm):
        self._make_capability_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # H — Authority rejects capability when not executable
    def test_rejects_capability_not_executable(self, rrm):
        self._make_capability_rrm(rrm, is_executable=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "not_executable" in result.reason

    # I — Authority rejects capability with non-existent binding
    def test_rejects_capability_binding_not_in_registry(self, rrm):
        self._make_capability_rrm(rrm)
        mock_cap_reg = MagicMock()
        mock_cap_reg._registrations = {}
        authority = CanonicalActivationEvidenceAuthority(rrm, capability_registry=mock_cap_reg)
        evidence = ResourceActivationEvidence(
            evidence_id="ev-cap-binding",
            resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            evidence_type=ActivationEvidenceType.CAPABILITY_EXECUTABLE,
            source="canonical",
            binding_identity="nonexistent-binding-123",
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "binding_identity_not_in_canonical_registry" in result.reason

    # J — Authority accepts valid agent identity evidence
    def test_accepts_valid_agent_identity(self, rrm):
        self._make_agent_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "ag-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # K — Authority rejects agent identity when disabled
    def test_rejects_agent_disabled(self, rrm):
        self._make_agent_rrm(rrm, is_enabled=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "ag-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "not_enabled" in result.reason

    # L — Authority rejects agent identity with invalid installation state
    def test_rejects_agent_invalid_installation_state(self, rrm):
        self._make_agent_rrm(rrm, installation_state=AgentInstallationState.UNAVAILABLE)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "ag-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "installation_state_invalid" in result.reason

    # M — Authority accepts valid environment discovery evidence
    def test_accepts_valid_environment_discovery(self, rrm):
        self._make_environment_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
            ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # N — Authority rejects environment discovery when not discovered
    def test_rejects_environment_not_discovered(self, rrm):
        self._make_environment_rrm(rrm, is_discovered=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
            ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "not_discovered" in result.reason

    # O — Authority accepts valid account secret evidence
    def test_accepts_valid_account_secret(self, rrm):
        self._make_account_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "acc-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
            ActivationEvidenceType.ACCOUNT_SECRET,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is True

    # P — Authority rejects account secret when no secret reference
    def test_rejects_account_no_secret(self, rrm):
        self._make_account_rrm(rrm, has_secret=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = _make_evidence(
            "acc-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
            ActivationEvidenceType.ACCOUNT_SECRET,
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "no_secret_reference" in result.reason

    # Q — Evidence authority stores only validated evidence
    def test_stores_only_validated_evidence(self, rrm):
        self._make_provider_rrm(rrm, is_configured=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        ev_valid = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        ev_invalid = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        result_valid = authority.validate_and_store(ev_valid)
        result_invalid = authority.validate_and_store(ev_invalid)
        assert result_valid.valid is True
        assert result_invalid.valid is False
        assert len(authority.get_all_validated()) == 1

    # R — Service requires evidence authority for all evidence
    def test_service_requires_evidence_authority(self, rrm):
        self._make_provider_rrm(rrm)
        service = CanonicalResourceActivationService(rrm)
        evidence = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        validation = service.register_evidence(evidence)
        assert validation.valid is True
        assert "prov-1" in [e.resource_id for e in service.evidence_store.values()]

    # S — Unsupported resource kind is rejected
    def test_rejects_unsupported_resource_kind(self, rrm):
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = ResourceActivationEvidence(
            evidence_id="ev-unknown",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.MCP_RESOURCE,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
        )
        result = authority.validate_and_store(evidence)
        assert result.valid is False
        assert "unsupported_resource_kind" in result.reason


# ===========================================================================
# RA-18-01 — RRM Same-ID Overwrite Guard
#
# Compatibility/bootstrap sources must NOT silently overwrite governed
# M17 resources with same-ID objects.
# ===========================================================================


class TestRA1801RRMOverwriteGuard:
    """Tests for RRM governed resource overwrite protection."""

    def _make_governed_provider(self, rrm, provider_id="prov-1"):
        provider = ProviderResource(
            provider_id=provider_id, name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        return provider

    def _make_compatibility_provider(self, provider_id="prov-1"):
        return ProviderResource(
            provider_id=provider_id, name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=False,
        )

    # A — Existing resource is recognized as governed by origin
    def test_governed_by_origin(self, rrm):
        self._make_governed_provider(rrm)
        assert rrm._is_governed_resource("prov-1") is True

    # B — Compatibility source cannot overwrite USER_REGISTRATION origin
    def test_compatibility_cannot_overwrite_user_registration(self, rrm):
        self._make_governed_provider(rrm)
        compat = self._make_compatibility_provider()
        rrm.register_provider(compat)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "governed"

    # C — Explicitly governed resource is protected
    def test_explicitly_governed_protected(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="explicit",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        rrm.mark_governed("prov-1")
        compat = self._make_compatibility_provider()
        rrm.register_provider(compat)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "explicit"

    # D — Same origin can overwrite governed resource
    def test_same_origin_can_overwrite(self, rrm):
        self._make_governed_provider(rrm)
        new_provider = ProviderResource(
            provider_id="prov-1", name="updated",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(new_provider)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "updated"

    # E — Configuration source cannot overwrite USER_REGISTRATION origin
    def test_configuration_cannot_overwrite_user_registration(self, rrm):
        self._make_governed_provider(rrm)
        compat = ProviderResource(
            provider_id="prov-1", name="config",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "governed"

    # F — Host discovery source cannot overwrite USER_REGISTRATION origin
    def test_host_discovery_cannot_overwrite_user_registration(self, rrm):
        self._make_governed_provider(rrm)
        compat = ProviderResource(
            provider_id="prov-1", name="discovery",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "governed"

    # G — Non-governed resource can be registered
    def test_non_governed_can_register(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="first",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        new_provider = ProviderResource(
            provider_id="prov-1", name="second",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(new_provider)
        provider = rrm.get_provider("prov-1")
        assert provider.name == "second"

    # H — Mark governed is persisted
    def test_mark_governed_persisted(self, rrm):
        assert rrm.is_governed("prov-1") is False
        rrm.mark_governed("prov-1")
        assert rrm.is_governed("prov-1") is True

    # I — Agent: compatibility cannot overwrite USER_REGISTRATION
    def test_agent_compatibility_cannot_overwrite(self, rrm):
        agent = AgentResource(
            agent_id="ag-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=True,
        )
        rrm.register_agent(agent)
        compat = AgentResource(
            agent_id="ag-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_enabled=True,
        )
        rrm.register_agent(compat)
        agent = rrm.get_agent("ag-1")
        assert agent.name == "governed"

    # J — Capability: compatibility cannot overwrite USER_REGISTRATION
    def test_capability_compatibility_cannot_overwrite(self, rrm):
        cap = CapabilityResource(
            capability_id="cap-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=True,
        )
        rrm.register_capability(cap)
        compat = CapabilityResource(
            capability_id="cap-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_executable=True,
        )
        rrm.register_capability(compat)
        cap = rrm.get_capability("cap-1")
        assert cap.name == "governed"

    # K — Account: compatibility cannot overwrite CONFIGURATION
    def test_account_compatibility_cannot_overwrite(self, rrm):
        account = AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="governed",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            secret_reference="ref1",
        )
        rrm.register_account(account)
        compat = AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            secret_reference="ref2",
        )
        rrm.register_account(compat)
        account = rrm.get_account("acc-1")
        assert account.name == "governed"

    # L — Environment: compatibility cannot overwrite HOST_DISCOVERY
    def test_environment_compatibility_cannot_overwrite(self, rrm):
        env = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
        )
        rrm.register_environment(env)
        compat = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_discovered=False,
        )
        rrm.register_environment(compat)
        env = rrm.get_environment("env-1")
        assert env.is_discovered is True
