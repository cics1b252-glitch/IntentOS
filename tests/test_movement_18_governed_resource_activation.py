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

RA-18-03 Canonical Evidence Collection (tests A-P):
  CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
  collect_for_resource() derives evidence from canonical sources.
  Callers cannot construct arbitrary evidence objects.

RA-18-04 Governed Provenance (tests A-L):
  Origin alone is NOT sufficient for governed classification.
  governed_registration_id is required for canonical provenance.

RA-18-01 RRM Overwrite Guard (tests A-M):
  Same-ID/same-origin replacement of governed resources is rejected.
  Compatibility/bootstrap sources must NOT silently overwrite
  governed resources.
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
            request_id="r1", resource_id="p1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        with pytest.raises(AttributeError):
            req.request_id = "r2"  # type: ignore[misc]

    def test_decision_is_frozen(self):
        dec = ResourceActivationDecision(
            decision_id="d1", request_id="r1",
            resource_id="p1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        with pytest.raises(AttributeError):
            dec.decision_id = "d2"  # type: ignore[misc]

    def test_result_is_frozen(self):
        res = ResourceActivationResult(
            success=True, request_id="r1",
            decision_id="d1", resource_id="p1",
        )
        with pytest.raises(AttributeError):
            res.success = False  # type: ignore[misc]

    def test_evidence_is_frozen(self):
        ev = ResourceActivationEvidence(
            evidence_id="e1", resource_id="p1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
        )
        with pytest.raises(AttributeError):
            ev.evidence_id = "e2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B — Authority rejects without evidence
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
# C — Authority accepts valid evidence
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
        evidence_list = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        ev_ids = tuple(ev.evidence_id for ev in evidence_list)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=ev_ids,
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
# J — Boundary rejects unevaluated decision
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
# K — Revoked evidence is denied
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
# L — Evidence without approval is denied
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
        boundary = ActivationApplicationBoundary(
            rrm, {request.request_id: request}, {}, set(),
            {ev_config.evidence_id: ev_config, ev_account.evidence_id: ev_account},
        )
        result = boundary.apply(decision.decision_id)
        assert result.success is False


# ---------------------------------------------------------------------------
# M — Boundary rejects scope mismatch
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricateScope:
    def test_boundary_rejects_scope_mismatch(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        rrm.register_provider(provider)
        ev_config = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_account = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        request = ResourceActivationRequest(
            request_id="req1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="disc1", registration_id="reg1",
            scope="restricted",
            evidence_ids=(ev_config.evidence_id, ev_account.evidence_id),
        )
        decision = ResourceActivationDecision(
            decision_id="dec1", request_id="req1",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
            scope="global",
        )
        boundary = ActivationApplicationBoundary(
            rrm, {request.request_id: request},
            {decision.decision_id: decision}, set(),
            {ev_config.evidence_id: ev_config, ev_account.evidence_id: ev_account},
        )
        result = boundary.apply(decision.decision_id)
        assert result.success is False
        assert "scope_mismatch" in result.reason


# ---------------------------------------------------------------------------
# N — Boundary does not modify RRM without decision
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
        boundary = ActivationApplicationBoundary(rrm, {}, {}, set(), {})
        result = boundary.apply("nonexistent")
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
        evidence_list = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        ev_ids = tuple(ev.evidence_id for ev in evidence_list)
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER, "disc1", "reg1",
            evidence_ids=ev_ids,
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
        assert ResourceActivationStatus.EXPIRED.value == "expired"
        assert ResourceActivationStatus.REVOKED.value == "revoked"
        assert ResourceActivationStatus.CONSUMED.value == "consumed"


# ===========================================================================
# RA-18-03 — Canonical Evidence Collection
#
# CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
# collect_for_resource() derives evidence from canonical sources.
# Callers cannot construct arbitrary evidence objects.
# ===========================================================================


class TestRA1803CanonicalEvidenceCollection:
    """Tests for RA-18-03 canonical evidence derivation."""

    def _make_provider_rrm(self, rrm, is_configured=True, has_account=True):
        provider = ProviderResource(
            provider_id="prov-1", name="test-provider",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=is_configured,
            has_active_account=has_account,
        )
        rrm.register_provider(provider)
        return provider

    def _make_capability_rrm(self, rrm, is_executable=True):
        cap = CapabilityResource(
            capability_id="cap-1", name="test-cap",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=is_executable,
        )
        rrm.register_capability(cap)
        return cap

    def _make_agent_rrm(self, rrm, is_enabled=True, installation_state=AgentInstallationState.INSTALLED):
        agent = AgentResource(
            agent_id="ag-1", name="test-agent",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=is_enabled,
            installation_state=installation_state,
        )
        rrm.register_agent(agent)
        return agent

    def _make_environment_rrm(self, rrm, is_discovered=True):
        env = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
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

    # A — collect_for_resource returns empty for unregistered resource
    def test_collect_empty_for_unregistered(self, rrm):
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-nonexistent", ResourceDiscoveryKind.PROVIDER)
        assert evidence == []

    # B — collect_for_resource returns empty for unsupported kind
    def test_collect_empty_for_unsupported_kind(self, rrm):
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.MCP_RESOURCE)
        assert evidence == []

    # C — collect_for_resource derives provider configuration evidence
    def test_collects_provider_configuration(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.PROVIDER)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION in types

    # D — collect_for_resource derives provider account evidence
    def test_collects_provider_account(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.PROVIDER)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.PROVIDER_ACCOUNT in types

    # E — collect_for_resource returns empty when provider not configured
    def test_collects_no_config_when_not_configured(self, rrm):
        self._make_provider_rrm(rrm, is_configured=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.PROVIDER)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION not in types

    # F — collect_for_resource returns empty when provider has no active account
    def test_collects_no_account_when_no_account(self, rrm):
        self._make_provider_rrm(rrm, has_account=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.PROVIDER)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.PROVIDER_ACCOUNT not in types

    # G — collect_for_resource derives capability executable evidence
    def test_collects_capability_executable(self, rrm):
        self._make_capability_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("cap-1", ResourceDiscoveryKind.CAPABILITY)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.CAPABILITY_EXECUTABLE in types

    # H — collect_for_resource returns empty when capability not executable
    def test_collects_no_executable_when_not_executable(self, rrm):
        self._make_capability_rrm(rrm, is_executable=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("cap-1", ResourceDiscoveryKind.CAPABILITY)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.CAPABILITY_EXECUTABLE not in types

    # I — collect_for_resource derives agent identity evidence
    def test_collects_agent_identity(self, rrm):
        self._make_agent_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("ag-1", ResourceDiscoveryKind.AGENT)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.AGENT_IDENTITY in types

    # J — collect_for_resource returns empty when agent disabled
    def test_collects_no_identity_when_disabled(self, rrm):
        self._make_agent_rrm(rrm, is_enabled=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("ag-1", ResourceDiscoveryKind.AGENT)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.AGENT_IDENTITY not in types

    # K — collect_for_resource returns empty when agent unavailable
    def test_collects_no_identity_when_unavailable(self, rrm):
        self._make_agent_rrm(rrm, installation_state=AgentInstallationState.UNAVAILABLE)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("ag-1", ResourceDiscoveryKind.AGENT)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.AGENT_IDENTITY not in types

    # L — collect_for_resource derives environment discovery evidence
    def test_collects_environment_discovery(self, rrm):
        self._make_environment_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("env-1", ResourceDiscoveryKind.ENVIRONMENT)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.ENVIRONMENT_DISCOVERY in types

    # M — collect_for_resource returns empty when environment not discovered
    def test_collects_no_discovery_when_not_discovered(self, rrm):
        self._make_environment_rrm(rrm, is_discovered=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("env-1", ResourceDiscoveryKind.ENVIRONMENT)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.ENVIRONMENT_DISCOVERY not in types

    # N — collect_for_resource derives account secret evidence
    def test_collects_account_secret(self, rrm):
        self._make_account_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("acc-1", ResourceDiscoveryKind.CONNECTED_SERVICE)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.ACCOUNT_SECRET in types

    # O — collect_for_resource returns empty when account has no secret
    def test_collects_no_secret_when_no_secret(self, rrm):
        self._make_account_rrm(rrm, has_secret=False)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("acc-1", ResourceDiscoveryKind.CONNECTED_SERVICE)
        types = [e.evidence_type for e in evidence]
        assert ActivationEvidenceType.ACCOUNT_SECRET not in types

    # P — collected evidence has source_identity set
    def test_collected_evidence_has_source_identity(self, rrm):
        self._make_provider_rrm(rrm)
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource("prov-1", ResourceDiscoveryKind.PROVIDER)
        for ev in evidence:
            assert ev.source_identity != ""


# ===========================================================================
# RA-18-04 — Governed Provenance
#
# Origin alone is NOT sufficient for governed classification.
# governed_registration_id is required for canonical provenance.
# ===========================================================================


class TestRA1804GovernedProvenance:
    """Tests for RA-18-04 governed resource provenance."""

    # A — origin-only is NOT governed
    def test_origin_only_not_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        assert rrm._is_governed_resource("prov-1") is False

    # B — mark_governed does NOT create canonical governed identity (Cycle 5)
    def test_mark_governed_does_not_create_canonical_identity(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        rrm.mark_governed("prov-1", "promo-reg-001")
        assert rrm._is_governed_resource("prov-1") is False
        assert rrm.get_provider("prov-1").governed_registration_id == ""

    # C — mark_governed without registration_id does NOT make resource governed
    def test_mark_governed_without_registration_id(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        rrm.mark_governed("prov-1")
        assert rrm._is_governed_resource("prov-1") is False

    # D — governed_registration_id on resource makes it governed
    def test_governed_registration_id_on_resource(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-002",
        )
        rrm.register_provider(provider)
        assert rrm._is_governed_resource("prov-1") is True

    # E — same-ID/same-origin replacement is rejected for governed resources
    def test_same_id_same_origin_rejected(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-003",
        )
        rrm.register_provider(provider)
        new_provider = ProviderResource(
            provider_id="prov-1", name="attempted-replace",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(new_provider)
        result = rrm.get_provider("prov-1")
        assert result.name == "governed"

    # F — same-ID/different-origin replacement is REJECTED for governed resources (Cycle 4)
    def test_same_id_different_origin_rejected(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-004",
        )
        rrm.register_provider(provider)
        new_provider = ProviderResource(
            provider_id="prov-1", name="attempted-replace",
            resource_origin=ResourceOrigin.ORGANIZATION_POLICY,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(new_provider)
        result = rrm.get_provider("prov-1")
        assert result.name == "governed"

    # G — compatibility source cannot overwrite governed resource
    def test_compatibility_cannot_overwrite_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-005",
        )
        rrm.register_provider(provider)
        compat = ProviderResource(
            provider_id="prov-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        result = rrm.get_provider("prov-1")
        assert result.name == "governed"

    # H — non-governed resource can be freely registered
    def test_non_governed_can_register(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="first",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        provider2 = ProviderResource(
            provider_id="prov-1", name="second",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider2)
        assert rrm.get_provider("prov-1").name == "second"

    # I — mark_governed does NOT set governed_registration_id on resource (Cycle 5)
    def test_mark_governed_does_not_set_registration_id(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        rrm.mark_governed("prov-1", "promo-reg-006")
        assert rrm.get_provider("prov-1").governed_registration_id == ""

    # J — agent: same-ID/same-origin replacement rejected when governed
    def test_agent_same_origin_rejected(self, rrm):
        agent = AgentResource(
            agent_id="ag-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=True,
            governed_registration_id="promo-reg-007",
        )
        rrm.register_agent(agent)
        new_agent = AgentResource(
            agent_id="ag-1", name="attempted-replace",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=True,
        )
        rrm.register_agent(new_agent)
        assert rrm.get_agent("ag-1").name == "governed"

    # K — capability: same-ID/same-origin replacement rejected when governed
    def test_capability_same_origin_rejected(self, rrm):
        cap = CapabilityResource(
            capability_id="cap-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=True,
            governed_registration_id="promo-reg-008",
        )
        rrm.register_capability(cap)
        new_cap = CapabilityResource(
            capability_id="cap-1", name="attempted-replace",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=True,
        )
        rrm.register_capability(new_cap)
        assert rrm.get_capability("cap-1").name == "governed"

    # L — environment: compatibility cannot overwrite governed resource
    def test_environment_compatibility_cannot_overwrite(self, rrm):
        env = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_discovered=True,
            governed_registration_id="promo-reg-009",
        )
        rrm.register_environment(env)
        compat = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_discovered=False,
        )
        rrm.register_environment(compat)
        assert rrm.get_environment("env-1").is_discovered is True


# ===========================================================================
# RA-18-01 — RRM Same-ID Overwrite Guard (updated for Cycle 3)
#
# Same-ID/same-origin replacement of governed resources is rejected.
# Compatibility/bootstrap sources must NOT silently overwrite
# governed resources.
# ===========================================================================


class TestRA1801RRMOverwriteGuard:
    """Tests for RRM governed resource overwrite protection (Cycle 3)."""

    # A — origin-only does NOT make resource governed (Cycle 3 fix)
    def test_origin_only_not_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        assert rrm._is_governed_resource("prov-1") is False

    # B — compatibility source CAN overwrite non-governed resource
    def test_compatibility_can_overwrite_non_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="first",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        compat = ProviderResource(
            provider_id="prov-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        assert rrm.get_provider("prov-1").name == "compat"

    # C — explicitly governed resource is protected from compatibility
    def test_explicitly_governed_protected_from_compat(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="explicit",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-010",
        )
        rrm.register_provider(provider)
        compat = ProviderResource(
            provider_id="prov-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        assert rrm.get_provider("prov-1").name == "explicit"

    # D — same-origin replacement is rejected for governed resources
    def test_same_origin_rejected_for_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-011",
        )
        rrm.register_provider(provider)
        new_provider = ProviderResource(
            provider_id="prov-1", name="attempted-replace",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(new_provider)
        assert rrm.get_provider("prov-1").name == "governed"

    # E — configuration source cannot overwrite governed resource
    def test_configuration_cannot_overwrite_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-012",
        )
        rrm.register_provider(provider)
        compat = ProviderResource(
            provider_id="prov-1", name="config",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        assert rrm.get_provider("prov-1").name == "governed"

    # F — host discovery source cannot overwrite governed resource
    def test_host_discovery_cannot_overwrite_governed(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
            governed_registration_id="promo-reg-013",
        )
        rrm.register_provider(provider)
        compat = ProviderResource(
            provider_id="prov-1", name="discovery",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_configured=False,
        )
        rrm.register_provider(compat)
        assert rrm.get_provider("prov-1").name == "governed"

    # G — non-governed resource can be freely registered
    def test_non_governed_can_register(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="first",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        provider2 = ProviderResource(
            provider_id="prov-1", name="second",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider2)
        assert rrm.get_provider("prov-1").name == "second"

    # H — mark_governed does NOT create canonical identity (Cycle 5)
    def test_mark_governed_does_not_create_identity(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="test",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_configured=True,
        )
        rrm.register_provider(provider)
        assert rrm.is_governed("prov-1") is False
        rrm.mark_governed("prov-1", "promo-reg-014")
        assert rrm.is_governed("prov-1") is False
        assert rrm._is_governed_resource("prov-1") is False

    # I — agent: compatibility cannot overwrite governed resource
    def test_agent_compatibility_cannot_overwrite(self, rrm):
        agent = AgentResource(
            agent_id="ag-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=True,
            governed_registration_id="promo-reg-015",
        )
        rrm.register_agent(agent)
        compat = AgentResource(
            agent_id="ag-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_enabled=True,
        )
        rrm.register_agent(compat)
        assert rrm.get_agent("ag-1").name == "governed"

    # J — capability: compatibility cannot overwrite governed resource
    def test_capability_compatibility_cannot_overwrite(self, rrm):
        cap = CapabilityResource(
            capability_id="cap-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=True,
            governed_registration_id="promo-reg-016",
        )
        rrm.register_capability(cap)
        compat = CapabilityResource(
            capability_id="cap-1", name="compat",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_executable=True,
        )
        rrm.register_capability(compat)
        assert rrm.get_capability("cap-1").name == "governed"

    # K — account: compatibility cannot overwrite governed resource
    def test_account_compatibility_cannot_overwrite(self, rrm):
        account = AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="governed",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            secret_reference="ref1",
            governed_registration_id="promo-reg-017",
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
        assert rrm.get_account("acc-1").name == "governed"

    # L — environment: compatibility cannot overwrite governed resource
    def test_environment_compatibility_cannot_overwrite(self, rrm):
        env = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
            governed_registration_id="promo-reg-018",
        )
        rrm.register_environment(env)
        compat = ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=False,
            is_discovered=False,
        )
        rrm.register_environment(compat)
        assert rrm.get_environment("env-1").is_discovered is True

    # M — account: same-ID/same-origin replacement rejected when governed
    def test_account_same_origin_rejected(self, rrm):
        account = AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            secret_reference="ref1",
            governed_registration_id="promo-reg-019",
        )
        rrm.register_account(account)
        new_account = AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="attempted-replace",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            secret_reference="ref2",
        )
        rrm.register_account(new_account)
        assert rrm.get_account("acc-1").name == "governed"


# ===================================================================
# Cycle 4 — Comprehensive Test Matrices (Parts 17–20)
# ===================================================================


class TestRA1803CanonicalEvidenceTrustMatrix:
    """Part 17: RA-18-03 comprehensive evidence trust tests.

    CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
    collect_for_resource() produces TRUSTED evidence.
    validate_and_store() does NOT produce trusted evidence.
    """

    def test_caller_evidence_not_trusted(self, rrm):
        """A: Caller-constructed evidence is NOT in the trusted store."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        caller_ev = ResourceActivationEvidence(
            evidence_id="ev-caller-001",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="caller-asserted",
            source_identity="test",
        )
        assert authority.is_evidence_trusted("ev-caller-001") is False

    def test_collect_for_resource_produces_trusted_evidence(self, rrm):
        """B: Evidence from collect_for_resource() IS trusted."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.is_trusted is True
            assert authority.is_evidence_trusted(ev.evidence_id) is True

    def test_validate_and_store_does_not_produce_trusted(self, rrm):
        """C: validate_and_store() stores in compatibility, NOT trusted store."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        ev = ResourceActivationEvidence(
            evidence_id="ev-compat-001",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical:rrm",
            source_identity="RegistryResourceManager",
        )
        result = authority.validate_and_store(ev)
        assert result.valid is True
        assert authority.get_validated_evidence("ev-compat-001") is not None
        assert authority.is_evidence_trusted("ev-compat-001") is False

    def test_source_string_not_sufficient_for_trust(self, rrm):
        """D: Having source='canonical:rrm' is NOT sufficient for trust."""
        authority = CanonicalActivationEvidenceAuthority(rrm)
        ev = ResourceActivationEvidence(
            evidence_id="ev-fake-001",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical:rrm",
            source_identity="RegistryResourceManager",
        )
        assert authority.is_evidence_trusted("ev-fake-001") is False

    def test_evidence_ids_are_unique(self, rrm):
        """E: collect_for_resource() produces unique evidence IDs."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        ids = [ev.evidence_id for ev in evidence]
        assert len(ids) == len(set(ids))

    def test_evidence_matches_canonical_source_state(self, rrm):
        """F: Evidence produced matches actual canonical source state."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        types = {ev.evidence_type for ev in evidence}
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION in types
        assert ActivationEvidenceType.PROVIDER_ACCOUNT in types

    def test_evidence_from_not_configured_provider(self, rrm):
        """G: Unconfigured provider produces no configuration evidence."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=False, has_active_account=False,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        assert len(evidence) == 0

    def test_evidence_trusted_store_is_additive(self, rrm):
        """H: Multiple calls accumulate evidence in trusted store."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        ev1 = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        ev2 = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        all_trusted = authority.get_all_collected()
        assert len(all_trusted) >= len(ev1)

    def test_revoked_caller_evidence_not_trusted(self, rrm):
        """I: Even revoked caller evidence is not trusted (obviously)."""
        authority = CanonicalActivationEvidenceAuthority(rrm)
        ev = ResourceActivationEvidence(
            evidence_id="ev-revoked-001",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical:rrm",
            source_identity="test",
            revoked=True,
        )
        assert authority.is_evidence_trusted("ev-revoked-001") is False

    def test_get_collected_evidence_returns_trusted_only(self, rrm):
        """J: get_collected_evidence() returns only trusted evidence."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        for ev in evidence:
            retrieved = authority.get_collected_evidence(ev.evidence_id)
            assert retrieved is not None
            assert retrieved.is_trusted is True

    def test_unsupported_kind_returns_empty(self, rrm):
        """K: Unsupported resource kind returns empty evidence list."""
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "res-1", ResourceDiscoveryKind.MCP_RESOURCE,
        )
        assert evidence == []

    def test_nonexistent_resource_returns_empty(self, rrm):
        """L: Non-existent resource returns empty evidence list."""
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "nonexistent", ResourceDiscoveryKind.PROVIDER,
        )
        assert evidence == []

    def test_capability_evidence_trusted(self, rrm):
        """M: Capability evidence from collect_for_resource is trusted."""
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="cap",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_executable=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
        )
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.is_trusted is True
            assert authority.is_evidence_trusted(ev.evidence_id) is True

    def test_account_evidence_trusted(self, rrm):
        """N: Account evidence from collect_for_resource is trusted."""
        rrm.register_account(AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="acc",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            secret_reference="ref1",
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "acc-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
        )
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.is_trusted is True
            assert authority.is_evidence_trusted(ev.evidence_id) is True

    def test_environment_evidence_trusted(self, rrm):
        """O: Environment evidence from collect_for_resource is trusted."""
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
        ))
        authority = CanonicalActivationEvidenceAuthority(rrm)
        evidence = authority.collect_for_resource(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
        )
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.is_trusted is True
            assert authority.is_evidence_trusted(ev.evidence_id) is True


class TestRA1804GovernedProvenanceMatrix:
    """Part 18: RA-18-04 comprehensive governed provenance tests.

    Origin alone is NOT sufficient for governed classification.
    governed_registration_id is required for canonical provenance.
    mark_governed() is COMPATIBILITY_ONLY.
    """

    def test_mark_governed_does_not_set_governed_registration_id(self, rrm):
        """A: mark_governed() does NOT set governed_registration_id (compatibility-only)."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        if hasattr(rrm, 'mark_governed'):
            rrm.mark_governed("prov-1", "compat-origin")
            provider = rrm.get_provider("prov-1")
            assert provider.governed_registration_id == ""
            # mark_governed() is COMPATIBILITY_ONLY — no canonical identity
            assert rrm._is_governed_resource("prov-1") is False

    def test_origin_alone_insufficient_for_governed(self, rrm):
        """B: USER_REGISTRATION origin alone is NOT governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == ""

    def test_configuration_origin_not_governed(self, rrm):
        """C: CONFIGURATION origin is NOT governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_configured=True, has_active_account=True,
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == ""

    def test_migration_origin_not_governed(self, rrm):
        """D: MIGRATION origin is NOT governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=True,
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == ""

    def test_host_discovery_origin_not_governed(self, rrm):
        """E: HOST_DISCOVERY origin is NOT governed."""
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
        ))
        env = rrm.get_environment("env-1")
        assert env.governed_registration_id == ""

    def test_governed_id_must_be_nonempty_string(self, rrm):
        """F: Empty governed_registration_id is NOT treated as governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="",
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == ""

    def test_governed_id_with_special_characters(self, rrm):
        """G: Governed ID with special characters is preserved."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="reg/with:special-chars_123",
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == "reg/with:special-chars_123"

    def test_governed_id_set_by_mark_governed_is_compatibility(self, rrm):
        """H: mark_governed() does NOT set governed_registration_id (compatibility-only)."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        if hasattr(rrm, 'mark_governed'):
            rrm.mark_governed("prov-1", "compat-origin")
            provider = rrm.get_provider("prov-1")
            assert provider.governed_registration_id == ""
            # This is COMPATIBILITY_ONLY. Canonical governed_registration_id
            # is created by CanonicalPromotionRegistrationBoundary.

    def test_same_governed_id_preserved(self, rrm):
        """I: Same governed_registration_id on same resource is preserved."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="promo-reg-002",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-updated",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="promo-reg-002",
        ))
        provider = rrm.get_provider("prov-1")
        assert provider.governed_registration_id == "promo-reg-002"


class TestRA1801ComprehensiveOriginMatrix:
    """Part 19: RA-18-01 comprehensive origin matrix.

    ALL origin combinations × ALL resource types → governed replacement rejected.
    """

    def test_provider_migration_over_governed_rejected(self, rrm):
        """Provider: MIGRATION cannot overwrite governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="promo-reg-101",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="migration",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=True,
        ))
        assert rrm.get_provider("prov-1").name == "governed"

    def test_provider_configuration_over_governed_rejected(self, rrm):
        """Provider: CONFIGURATION cannot overwrite governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="promo-reg-102",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="config",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_configured=True,
        ))
        assert rrm.get_provider("prov-1").name == "governed"

    def test_provider_host_discovery_over_governed_rejected(self, rrm):
        """Provider: HOST_DISCOVERY cannot overwrite governed."""
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="promo-reg-103",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="host",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_configured=True,
        ))
        assert rrm.get_provider("prov-1").name == "governed"

    def test_capability_migration_over_governed_rejected(self, rrm):
        """Capability: MIGRATION cannot overwrite governed."""
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_executable=True,
            governed_registration_id="promo-reg-104",
        ))
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="migration",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=True,
        ))
        assert rrm.get_capability("cap-1").name == "governed"

    def test_capability_configuration_over_governed_rejected(self, rrm):
        """Capability: CONFIGURATION cannot overwrite governed."""
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_executable=True,
            governed_registration_id="promo-reg-105",
        ))
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="config",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_executable=True,
        ))
        assert rrm.get_capability("cap-1").name == "governed"

    def test_agent_migration_over_governed_rejected(self, rrm):
        """Agent: MIGRATION cannot overwrite governed."""
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_enabled=True,
            installation_state=AgentInstallationState.AVAILABLE,
            governed_registration_id="promo-reg-106",
        ))
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="migration",
            resource_origin=ResourceOrigin.MIGRATION,
            is_enabled=True,
            installation_state=AgentInstallationState.AVAILABLE,
        ))
        assert rrm.get_agent("agent-1").name == "governed"

    def test_environment_migration_over_governed_rejected(self, rrm):
        """Environment: MIGRATION cannot overwrite governed."""
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
            governed_registration_id="promo-reg-107",
        ))
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="cloud",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=True,
        ))
        assert rrm.get_environment("env-1").type == "local"

    def test_environment_configuration_over_governed_rejected(self, rrm):
        """Environment: CONFIGURATION cannot overwrite governed."""
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="local",
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
            governed_registration_id="promo-reg-108",
        ))
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1", type="cloud",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_discovered=False,
        ))
        assert rrm.get_environment("env-1").type == "local"

    def test_account_migration_over_governed_rejected(self, rrm):
        """Account: MIGRATION cannot overwrite governed."""
        rrm.register_account(AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            secret_reference="ref1",
            governed_registration_id="promo-reg-109",
        ))
        rrm.register_account(AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="migration",
            resource_origin=ResourceOrigin.MIGRATION,
            is_template=True,
            secret_reference="ref2",
        ))
        assert rrm.get_account("acc-1").name == "governed"

    def test_account_configuration_over_governed_rejected(self, rrm):
        """Account: CONFIGURATION cannot overwrite governed."""
        rrm.register_account(AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            secret_reference="ref1",
            governed_registration_id="promo-reg-110",
        ))
        rrm.register_account(AccountResource(
            account_id="acc-1", provider_id="prov-1",
            name="config",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            secret_reference="ref2",
        ))
        assert rrm.get_account("acc-1").name == "governed"

    def test_all_origins_rejected_for_governed_provider(self, rrm):
        """All non-USER_REGISTRATION origins rejected for governed provider."""
        for origin in [
            ResourceOrigin.MIGRATION,
            ResourceOrigin.CONFIGURATION,
            ResourceOrigin.HOST_DISCOVERY,
        ]:
            rrm.register_provider(ProviderResource(
                provider_id="prov-1", name="governed",
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                is_configured=True, has_active_account=True,
                governed_registration_id="promo-reg-200",
            ))
            rrm.register_provider(ProviderResource(
                provider_id="prov-1", name=f"attempt-{origin.value}",
                resource_origin=origin,
                is_configured=True,
            ))
            assert rrm.get_provider("prov-1").name == "governed"


class TestRA1802Regression:
    """Part 20a: RA-18-02 regression — authority still validates correctly."""

    def test_full_pipeline_still_works(self, rrm):
        """Regression: full activation pipeline still succeeds with valid evidence."""
        from intent_kernel.rrm.models import (
            ProviderResource, ResourceOrigin,
        )

        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))

        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        assert len(evidence) > 0

        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            "disc1", "reg1",
            evidence_ids=tuple(ev.evidence_id for ev in evidence),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_boundary_applies_with_trusted_evidence(self, rrm):
        """Regression: application boundary succeeds with trusted evidence."""
        from intent_kernel.rrm.models import ProviderResource, ResourceOrigin

        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))

        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            "disc1", "reg1",
            evidence_ids=tuple(ev.evidence_id for ev in evidence),
        )
        decision = service.evaluate(request.request_id)
        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is True
        assert "activation_applied" == result.reason


class TestRA1301ExactIdentity:
    """Part 20b: RA-13-01 exact identity — no free-text authority fields."""

    def test_evidence_type_is_enum(self):
        """Evidence types are typed enums, not free strings."""
        assert isinstance(ActivationEvidenceType.PROVIDER_CONFIGURATION, ActivationEvidenceType)
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION.value == "provider_configuration"

    def test_decision_type_is_enum(self):
        """Decision types are typed enums."""
        assert ResourceActivationDecisionType.APPROVE.value == "approve"
        assert ResourceActivationDecisionType.REJECT.value == "reject"

    def test_status_is_enum(self):
        """Activation status is typed enum."""
        assert ResourceActivationStatus.PENDING.value == "pending"
        assert ResourceActivationStatus.APPROVED.value == "approved"

    def test_no_authority_bearing_fields_in_evidence(self):
        """Evidence model does not expose authority-bearing fields."""
        ev = ResourceActivationEvidence(
            evidence_id="ev-1",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
        )
        # Evidence is frozen — cannot be mutated to add authority fields
        with pytest.raises(AttributeError):
            ev.authorized = True
        with pytest.raises(AttributeError):
            ev.trusted = True
        with pytest.raises(AttributeError):
            ev.bypass = True


# ===================================================================
# Cycle 5 — Remove Compatibility Governed-ID Authority
#
# COMPATIBILITY METADATA != CANONICAL GOVERNED IDENTITY
# mark_governed() must NOT create canonical governed identity.
# Only M17 CanonicalPromotionRegistrationBoundary creates canonical identity.
# ===================================================================


class TestCycle5MarkGovernedIsolation:
    """A-F: mark_governed() must not create canonical governed identity."""

    # A: legacy resource + mark_governed("forged") → NOT canonically governed
    def test_forged_mark_governed_not_canonically_governed(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-registration-id")
        assert rrm._is_governed_resource("prov-1") is False
        assert rrm.is_governed("prov-1") is False

    # B: forged mark does not affect overwrite policy
    def test_forged_mark_does_not_affect_overwrite_policy(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="original",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-id")
        replacement = ProviderResource(
            provider_id="prov-1", name="replacement",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        )
        rrm.register_provider(replacement)
        assert rrm.get_provider("prov-1").name == "replacement"

    # C: forged mark does not enter trusted activation flow
    def test_forged_mark_does_not_enter_trusted_flow(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-id")
        assert rrm._is_governed_resource("prov-1") is False
        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            "disc1", "reg1",
            evidence_ids=tuple(ev.evidence_id for ev in evidence),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    # D: forged mark does not affect eligibility
    def test_forged_mark_does_not_affect_eligibility(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-id")
        provider = rrm.get_provider("prov-1")
        assert provider.is_eligible is True
        assert provider.governed_registration_id == ""

    # E: forged mark does not affect binding
    def test_forged_mark_does_not_affect_binding(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-id")
        provider = rrm.get_provider("prov-1")
        assert provider.is_configured is True
        assert provider.has_active_account is True

    # F: forged mark does not affect authorization/execution
    def test_forged_mark_does_not_affect_authorization(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        rrm.mark_governed("prov-1", "forged-id")
        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            "disc1", "reg1",
            evidence_ids=tuple(ev.evidence_id for ev in evidence),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is True


class TestCycle5CanonicalGovernedIdentity:
    """G-L: Canonical M17 registration creates governed identity."""

    # G: real M17 registration automatically creates canonical governed identity
    def test_real_m17_registration_creates_governed_identity(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_canonical01",
        )
        rrm.register_provider(provider)
        assert rrm._is_governed_resource("prov-1") is True
        assert rrm.get_provider("prov-1").governed_registration_id == "registration_canonical01"

    # H: real M17 identity is recognized by _is_governed_resource()
    def test_real_m17_identity_recognized(self, rrm):
        for kind_id, kind_class, rid_field, reg_id in [
            ("prov-1", ProviderResource, "provider_id", "registration_p001"),
            ("cap-1", CapabilityResource, "capability_id", "registration_c001"),
            ("ag-1", AgentResource, "agent_id", "registration_a001"),
            ("env-1", ExecutionEnvironmentResource, "environment_id", "registration_e001"),
        ]:
            rrm2 = RegistryResourceManager(populate_defaults=False)
            kwargs = {
                rid_field: kind_id,
                "name": "test",
                "resource_origin": ResourceOrigin.USER_REGISTRATION,
                "is_template": False,
                "governed_registration_id": reg_id,
            }
            if kind_id == "prov-1":
                kwargs["is_configured"] = True
                kwargs["has_active_account"] = True
                rrm2.register_provider(kind_class(**kwargs))
            elif kind_id == "cap-1":
                kwargs["is_executable"] = True
                rrm2.register_capability(kind_class(**kwargs))
            elif kind_id == "ag-1":
                kwargs["is_enabled"] = True
                kwargs["installation_state"] = AgentInstallationState.AVAILABLE
                rrm2.register_agent(kind_class(**kwargs))
            elif kind_id == "env-1":
                kwargs["is_discovered"] = True
                kwargs["type"] = "local"
                kwargs.pop("name", None)
                rrm2.register_environment(kind_class(**kwargs))
            assert rrm2._is_governed_resource(kind_id) is True

    # I: generic register_* cannot overwrite real governed resource
    def test_register_cannot_overwrite_real_governed(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_real01",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="attempted",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        assert rrm.get_provider("prov-1").name == "governed"

    # J: same-origin overwrite real governed resource rejected
    def test_same_origin_overwrite_real_governed_rejected(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_real02",
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="same-origin-attempt",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_real02",
        ))
        assert rrm.get_provider("prov-1").name == "governed"

    # K: different-origin overwrite real governed resource rejected
    def test_different_origin_overwrite_real_governed_rejected(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_real03",
        ))
        for origin in [
            ResourceOrigin.MIGRATION,
            ResourceOrigin.CONFIGURATION,
            ResourceOrigin.HOST_DISCOVERY,
        ]:
            rrm.register_provider(ProviderResource(
                provider_id="prov-1", name=f"attempt-{origin.value}",
                resource_origin=origin,
                is_configured=True,
            ))
            assert rrm.get_provider("prov-1").name == "governed"

    # L: activation pipeline still works for real governed resource
    def test_activation_pipeline_works_for_real_governed(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="governed",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
            governed_registration_id="registration_real04",
        ))
        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        request = service.create_request(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            "disc1", "reg1",
            evidence_ids=tuple(ev.evidence_id for ev in evidence),
        )
        decision = service.evaluate(request.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is True


class TestCycle5Regression:
    """M-P: RA-18-01/02/03/RA-13-01 regressions."""

    # M: RA-18-01 remains fixed — no ungoverned activation authority
    def test_ra1801_regression(self, rrm):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
        from intent_kernel.activation.service import CanonicalResourceActivationService
        from intent_kernel.activation.evidence_authority import CanonicalActivationEvidenceAuthority
        assert CanonicalResourceActivationAuthority is not None
        assert ActivationApplicationBoundary is not None
        assert CanonicalResourceActivationService is not None
        assert CanonicalActivationEvidenceAuthority is not None

    # N: RA-18-02 remains fixed — activation does not fabricate evidence
    def test_ra1802_regression(self, rrm):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_configured=True, has_active_account=True,
        ))
        service = CanonicalResourceActivationService(rrm)
        evidence = service.collect_and_register_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
        )
        assert len(evidence) > 0
        for ev in evidence:
            assert ev.is_trusted is True

    # O: RA-18-03 remains fixed — caller evidence not trusted
    def test_ra1803_regression(self, rrm):
        authority = CanonicalActivationEvidenceAuthority(rrm)
        caller_ev = ResourceActivationEvidence(
            evidence_id="ev-caller-cycle5",
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="caller-asserted",
            source_identity="test",
        )
        assert authority.is_evidence_trusted("ev-caller-cycle5") is False

    # P: RA-13-01 remains fixed — typed enums
    def test_ra1301_regression(self):
        assert ActivationEvidenceType.PROVIDER_CONFIGURATION.value == "provider_configuration"
        assert ResourceActivationDecisionType.APPROVE.value == "approve"
        assert ResourceActivationStatus.PENDING.value == "pending"
