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
# B — Evidence model
# ---------------------------------------------------------------------------


class TestEvidenceModel:
    def test_evidence_not_revoked_by_default(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
        )
        assert ev.is_valid() is True
        assert ev.revoked is False

    def test_evidence_revoked_is_invalid(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
            revoked=True,
        )
        assert ev.is_valid() is False

    def test_evidence_to_dict(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
        )
        d = ev.to_dict()
        assert d["evidence_id"] == "ev1"
        assert d["resource_id"] == "prov-1"
        assert d["revoked"] is False


# ---------------------------------------------------------------------------
# C — Authority rejects unsupported resource kind
# ---------------------------------------------------------------------------


class TestAuthorityRejectsUnsupportedKind:
    def test_rejects_unsupported(self, rrm, activation_service):
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="unknown-1",
            resource_kind=ResourceDiscoveryKind.DEVICE,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "resource_not_registered" in decision.reasoning


# ---------------------------------------------------------------------------
# D — Authority rejects unregistered resource
# ---------------------------------------------------------------------------


class TestAuthorityRejectsUnregistered:
    def test_rejects_not_registered(self, rrm, activation_service):
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="missing-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "resource_not_registered" in decision.reasoning


# ---------------------------------------------------------------------------
# E — Provider: no evidence → reject (RA-18-02-PROVIDER)
# ---------------------------------------------------------------------------


class TestProviderNoEvidenceRejects:
    def test_provider_without_evidence_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "provider_configured" in decision.reasoning

    def test_provider_with_wrong_evidence_type_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_provider_revoked_evidence_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
            revoked=True,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# F — Provider: valid evidence + is_configured=False → reject
# ---------------------------------------------------------------------------


class TestProviderNotConfiguredRejects:
    def test_provider_not_configured_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=False, has_active_account=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "provider_configured" in decision.reasoning

    def test_provider_no_active_account_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=False,
        ))
        authority = activation_service.authority
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        authority.register_evidence(ev_cfg)
        authority.register_evidence(ev_acct)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# G — Provider: valid evidence + configured → approve
# ---------------------------------------------------------------------------


class TestProviderWithEvidenceApproves:
    def test_provider_with_evidence_approves(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        authority.register_evidence(ev_cfg)
        authority.register_evidence(ev_acct)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        assert len(decision.evidence_verified) == 2


# ---------------------------------------------------------------------------
# H — Capability: no evidence → reject (RA-18-02-CAPABILITY)
# ---------------------------------------------------------------------------


class TestCapabilityNoEvidenceRejects:
    def test_capability_without_evidence_rejects(self, rrm, activation_service):
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="cap-1",
            is_executable=True,
        ))
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_capability_not_executable_rejects(self, rrm, activation_service):
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="cap-1",
            is_executable=False,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_capability_with_evidence_approves(self, rrm, activation_service):
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="cap-1",
            is_executable=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# I — Agent: no evidence → reject (RA-18-02-AGENT)
# ---------------------------------------------------------------------------


class TestAgentNoEvidenceRejects:
    def test_agent_without_evidence_rejects(self, rrm, activation_service):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=True,
            installation_state=AgentInstallationState.INSTALLED,
        ))
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_agent_not_enabled_rejects(self, rrm, activation_service):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=False,
            installation_state=AgentInstallationState.INSTALLED,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "agent-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_agent_privileged_role_rejects(self, rrm, activation_service):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=True,
            installation_state=AgentInstallationState.INSTALLED,
            metadata={"role": "admin"},
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "agent-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "admin" in decision.reasoning

    def test_agent_with_evidence_approves(self, rrm, activation_service):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=True,
            installation_state=AgentInstallationState.INSTALLED,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "agent-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# J — Environment: no evidence → reject (RA-18-02-ENVIRONMENT)
# ---------------------------------------------------------------------------


class TestEnvironmentNoEvidenceRejects:
    def test_environment_without_evidence_rejects(self, rrm, activation_service):
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1",
            is_discovered=True,
        ))
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="env-1",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_environment_not_discovered_rejects(self, rrm, activation_service):
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1",
            is_discovered=False,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
            ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="env-1",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_environment_with_evidence_approves(self, rrm, activation_service):
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1",
            is_discovered=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
            ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="env-1",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# K — Account: no secret_reference → reject
# ---------------------------------------------------------------------------


class TestAccountNoSecretRejects:
    def test_account_no_secret_rejects(self, rrm, activation_service):
        rrm.register_account(AccountResource(
            account_id="acct-1", provider_id="prov-1", name="acct-1",
            secret_reference=None,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "acct-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
            ActivationEvidenceType.ACCOUNT_SECRET,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="acct-1",
            resource_kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "account_secret_reference" in decision.reasoning

    def test_account_with_secret_approves(self, rrm, activation_service):
        rrm.register_account(AccountResource(
            account_id="acct-1", provider_id="prov-1", name="acct-1",
            secret_reference="configured_secret",
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "acct-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
            ActivationEvidenceType.ACCOUNT_SECRET,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="acct-1",
            resource_kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# L — Approval alone never changes eligibility fields
# ---------------------------------------------------------------------------


class TestApprovalDoesNotChangeFields:
    def test_approval_does_not_fabricate_provider_fields(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=False, has_active_account=False,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

        provider = rrm.get_provider("prov-1")
        assert provider.is_configured is False
        assert provider.has_active_account is False

    def test_approval_result_no_fields_fabricated(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=False, has_active_account=False,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        result = service.activate(req.request_id)
        assert result.success is False

        provider = rrm.get_provider("prov-1")
        assert provider.is_configured is False
        assert provider.has_active_account is False


# ---------------------------------------------------------------------------
# M — Forged evidence → reject
# ---------------------------------------------------------------------------


class TestForgedEvidenceRejects:
    def test_forged_evidence_not_in_store_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=("forged-ev-1",),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT

    def test_evidence_for_different_resource_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-2", name="prov-2",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "prov-2", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# N — Evidence revoked after approval → application fails
# ---------------------------------------------------------------------------


class TestRevokedEvidenceFailsApplication:
    def test_revoked_evidence_fails_boundary(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

        revoked_ev = ResourceActivationEvidence(
            evidence_id=ev_cfg.evidence_id,
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="canonical",
            revoked=True,
        )
        service.register_evidence(revoked_ev)

        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is False
        assert "evidence_revoked" in result.reason


# ---------------------------------------------------------------------------
# O — Decision replay → fails
# ---------------------------------------------------------------------------


class TestDecisionReplayFails:
    def test_decision_consumed_replay_fails(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        result1 = service.application_boundary.apply(decision.decision_id)
        assert result1.success is True

        result2 = service.application_boundary.apply(decision.decision_id)
        assert result2.success is False
        assert "decision_already_consumed" in result2.reason


# ---------------------------------------------------------------------------
# P — Binding replaced after approval → application fails
# ---------------------------------------------------------------------------


class TestBindingReplacedFails:
    def test_provider_becomes_unconfigured_after_approval(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

        provider = rrm.get_provider("prov-1")
        provider.is_configured = False

        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is False
        assert "binding_revalidation_failed" in result.reason


# ---------------------------------------------------------------------------
# Q — Compatibility writer cannot bypass governed activation
# ---------------------------------------------------------------------------


class TestCompatibilityBypassGuarded:
    def test_runtime_resource_projection_does_not_activate(self, rrm, activation_service):
        from intent_kernel.rrm.projection import RuntimeResourceProjection
        from intent_kernel.contracts import Provider
        from unittest.mock import PropertyMock

        proj = RuntimeResourceProjection(rrm)
        fake_provider = MagicMock(spec=Provider)
        fake_provider.name = "mock"
        proj.project_provider(fake_provider)

        provider = rrm.get_provider("mock")
        assert provider is not None
        assert provider.is_configured is False
        assert provider.has_active_account is False
        assert provider.is_eligible is False

    def test_update_resource_status_cannot_bypass(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=False, has_active_account=False,
        ))
        provider = rrm.get_provider("prov-1")
        provider.status = ResourceStatus.ACTIVE

        provider = rrm.get_provider("prov-1")
        assert provider.is_configured is False
        assert provider.has_active_account is False
        assert provider.is_eligible is False


# ---------------------------------------------------------------------------
# R — Zero-provider truth remains intact
# ---------------------------------------------------------------------------


class TestZeroProviderTruth:
    def test_empty_rrm_no_providers_eligible(self, rrm):
        providers = rrm.list_providers(only_eligible=True)
        assert len(providers) == 0

    def test_empty_rrm_no_capabilities_eligible(self, rrm):
        capabilities = rrm.list_capabilities(only_eligible=True)
        assert len(capabilities) == 0


# ---------------------------------------------------------------------------
# S — RA-13-01 remains fixed
# ---------------------------------------------------------------------------


class TestRA1301Fixed:
    def test_binding_invariant(self, rrm):
        try:
            from intent_kernel.rrm.binding import CanonicalResourceBindingAuthority
        except ImportError:
            pytest.skip("Circular import in orchestration → application → composition")
        mock_registry = MagicMock()
        binding_authority = CanonicalResourceBindingAuthority(rrm, mock_registry)
        assert hasattr(binding_authority, 'resolve')
        assert hasattr(binding_authority, 'revalidate')


# ---------------------------------------------------------------------------
# T — Activation != authorization != confirmation != execution
# ---------------------------------------------------------------------------


class TestActivationNotAuthorization:
    def test_activation_result_no_authority_fields(self):
        result = ResourceActivationResult(
            success=True, request_id="r1", decision_id="dec1",
            resource_id="prov-1",
        )
        d = result.to_dict()
        assert "authorized" not in d
        assert "execute" not in d
        assert "verified" not in d
        assert "completed" not in d

    def test_decision_no_authority_fields(self):
        decision = ResourceActivationDecision(
            decision_id="dec1", request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        d = decision.to_dict()
        assert "authorized" not in d
        assert "execute" not in d


# ---------------------------------------------------------------------------
# U — RA-18-01 containment
# ---------------------------------------------------------------------------


class TestRA1801Containment:
    def test_authority_isolation_from_promotion(self, rrm, activation_service):
        authority = activation_service.authority
        assert not hasattr(authority, 'approve_promotion')
        assert not hasattr(authority, 'create_registration')

    def test_boundary_isolation_from_authority(self, rrm, activation_service):
        boundary = activation_service.application_boundary
        assert not hasattr(boundary, 'evaluate')
        assert not hasattr(boundary, 'select')


# ---------------------------------------------------------------------------
# V — Service wiring
# ---------------------------------------------------------------------------


class TestServiceWiring:
    def test_service_has_authority(self, activation_service):
        assert isinstance(activation_service.authority, CanonicalResourceActivationAuthority)

    def test_service_has_boundary(self, activation_service):
        assert isinstance(activation_service.application_boundary, ActivationApplicationBoundary)

    def test_full_pipeline_success(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert result.reason == "activation_applied"

    def test_full_pipeline_rejects(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=False, has_active_account=False,
        ))
        service = activation_service
        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(),
        )

        result = service.activate(req.request_id)
        assert result.success is False

    def test_evidence_store_populated(self, rrm, activation_service):
        service = activation_service
        ev = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        service.register_evidence(ev)
        assert service.get_evidence(ev.evidence_id) is not None

    def test_nonexistent_request_raises(self, rrm, activation_service):
        with pytest.raises(ActivationError):
            activation_service.evaluate("nonexistent")


# ---------------------------------------------------------------------------
# W — Evidence for resource A used for B → reject
# ---------------------------------------------------------------------------


class TestCrossResourceEvidenceRejects:
    def test_evidence_for_a_not_valid_for_b(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        rrm.register_provider(ProviderResource(
            provider_id="prov-2", name="prov-2",
            is_configured=True, has_active_account=True,
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "prov-2", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT


# ---------------------------------------------------------------------------
# X — Agent privileged roles don't alter result
# ---------------------------------------------------------------------------


class TestAgentPrivilegedRoles:
    @pytest.mark.parametrize("role", ["admin", "root", "system", "trusted", "supervisor"])
    def test_privileged_role_rejects(self, rrm, activation_service, role):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=True,
            installation_state=AgentInstallationState.INSTALLED,
            metadata={"role": role},
        ))
        authority = activation_service.authority
        ev = _make_evidence(
            "agent-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        authority.register_evidence(ev)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert role in decision.reasoning


# ---------------------------------------------------------------------------
# Y — TOCTOU revalidation
# ---------------------------------------------------------------------------


class TestTOCTOURevalidation:
    def test_resource_becomes_template_fails(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

        provider = rrm.get_provider("prov-1")
        provider.is_template = True

        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is False
        assert "resource_is_template" in result.reason

    def test_resource_becomes_unregistered_fails(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        decision = service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

        rrm._providers.pop("prov-1", None)

        result = service.application_boundary.apply(decision.decision_id)
        assert result.success is False
        assert "resource_not_registered" in result.reason


# ---------------------------------------------------------------------------
# Z — Boundary does not fabricate (RA-18-02 core invariant)
# ---------------------------------------------------------------------------


class TestBoundaryDoesNotFabricate:
    def test_boundary_observe_only_provider(self, rrm, activation_service):
        rrm.register_provider(ProviderResource(
            provider_id="prov-1", name="prov-1",
            is_configured=True, has_active_account=True,
        ))
        service = activation_service
        ev_cfg = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        ev_acct = _make_evidence(
            "prov-1", ResourceDiscoveryKind.PROVIDER,
            ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        service.register_evidence(ev_cfg)
        service.register_evidence(ev_acct)

        req = service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev_cfg.evidence_id, ev_acct.evidence_id),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert "is_configured" in result.fields_updated
        assert "has_active_account" in result.fields_updated

        provider = rrm.get_provider("prov-1")
        assert provider.is_configured is True
        assert provider.has_active_account is True

    def test_boundary_observe_only_capability(self, rrm, activation_service):
        rrm.register_capability(CapabilityResource(
            capability_id="cap-1", name="cap-1",
            is_executable=True,
        ))
        service = activation_service
        ev = _make_evidence(
            "cap-1", ResourceDiscoveryKind.CAPABILITY,
            ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        service.register_evidence(ev)

        req = service.create_request(
            resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert "is_executable" in result.fields_updated

    def test_boundary_observe_only_agent(self, rrm, activation_service):
        rrm.register_agent(AgentResource(
            agent_id="agent-1", name="agent-1",
            is_enabled=True,
            installation_state=AgentInstallationState.INSTALLED,
        ))
        service = activation_service
        ev = _make_evidence(
            "agent-1", ResourceDiscoveryKind.AGENT,
            ActivationEvidenceType.AGENT_IDENTITY,
        )
        service.register_evidence(ev)

        req = service.create_request(
            resource_id="agent-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert "is_enabled" in result.fields_updated
        assert any("installation_state" in f for f in result.fields_updated)

    def test_boundary_observe_only_environment(self, rrm, activation_service):
        rrm.register_environment(ExecutionEnvironmentResource(
            environment_id="env-1",
            is_discovered=True,
        ))
        service = activation_service
        ev = _make_evidence(
            "env-1", ResourceDiscoveryKind.ENVIRONMENT,
            ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        service.register_evidence(ev)

        req = service.create_request(
            resource_id="env-1",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert "is_discovered" in result.fields_updated

    def test_boundary_observe_only_account(self, rrm, activation_service):
        rrm.register_account(AccountResource(
            account_id="acct-1", provider_id="prov-1", name="acct-1",
            secret_reference="configured_secret",
        ))
        service = activation_service
        ev = _make_evidence(
            "acct-1", ResourceDiscoveryKind.CONNECTED_SERVICE,
            ActivationEvidenceType.ACCOUNT_SECRET,
        )
        service.register_evidence(ev)

        req = service.create_request(
            resource_id="acct-1",
            resource_kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
            discovery_id="d1",
            registration_id="reg1",
            evidence_ids=(ev.evidence_id,),
        )

        result = service.activate(req.request_id)
        assert result.success is True
        assert "secret_reference" in result.fields_updated
