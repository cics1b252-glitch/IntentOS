"""Movement 18 — Governed Resource Activation Tests.

Full A-Z matrix + adversarial scenarios verifying:
1. Models are frozen and auditable
2. Canonical activation authority evaluates prerequisites per resource kind
3. Activation application boundary applies TOCTOU revalidation
4. Service orchestrates the full pipeline
5. Composition wiring works
6. RA-18-01 containment: no ungoverned activation authority
7. No discovery evidence, promotion, or registration authority leak
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from intent_kernel.activation import (
    ResourceActivationDecision,
    ResourceActivationDecisionType,
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


# ---------------------------------------------------------------------------
# B — Status lifecycle enums
# ---------------------------------------------------------------------------


class TestActivationStatusLifecycle:
    def test_status_values(self):
        assert ResourceActivationStatus.PENDING.value == "pending"
        assert ResourceActivationStatus.APPROVED.value == "approved"
        assert ResourceActivationStatus.REJECTED.value == "rejected"
        assert ResourceActivationStatus.EXPIRED.value == "expired"
        assert ResourceActivationStatus.REVOKED.value == "revoked"
        assert ResourceActivationStatus.CONSUMED.value == "consumed"

    def test_decision_type_values(self):
        assert ResourceActivationDecisionType.APPROVE.value == "approve"
        assert ResourceActivationDecisionType.REJECT.value == "reject"


# ---------------------------------------------------------------------------
# C — Authority-bearing field rejection
# ---------------------------------------------------------------------------


class TestAuthorityBearingFieldRejection:
    def test_prohibited_fields_exist(self):
        from intent_kernel.activation.models import _ACTIVATION_AUTHORITY_FIELDS
        assert "authorized" in _ACTIVATION_AUTHORITY_FIELDS
        assert "execute" in _ACTIVATION_AUTHORITY_FIELDS
        assert "verified" in _ACTIVATION_AUTHORITY_FIELDS
        assert "bypass" in _ACTIVATION_AUTHORITY_FIELDS
        assert "override" in _ACTIVATION_AUTHORITY_FIELDS
        assert "eligible" in _ACTIVATION_AUTHORITY_FIELDS


# ---------------------------------------------------------------------------
# D — Canonical activation authority: Provider prerequisites
# ---------------------------------------------------------------------------


class TestProviderActivationAuthority:
    def test_provider_all_prerequisites_met(self, rrm):
        provider = ProviderResource(
            provider_id="prov-1", name="Test Provider",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.ACTIVE, is_template=False,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE
        assert "prerequisites_not_satisfied" not in decision.reasoning

    def test_provider_not_configured_approved_by_authority(self, rrm):
        """Authority approves — activation fields are what activation fixes."""
        provider = ProviderResource(
            provider_id="prov-nc", name="NC Provider",
            is_configured=False, has_active_account=True,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r2", resource_id="prov-nc",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d2", registration_id="reg2",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_provider_no_active_account_approved_by_authority(self, rrm):
        """Authority approves — activation fields are what activation fixes."""
        provider = ProviderResource(
            provider_id="prov-na", name="NA Provider",
            is_configured=True, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r3", resource_id="prov-na",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d3", registration_id="reg3",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_provider_template_rejected(self, rrm):
        provider = ProviderResource(
            provider_id="prov-tpl", name="Template Provider",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.ACTIVE, is_template=True,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r4", resource_id="prov-tpl",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d4", registration_id="reg4",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "not_template" in decision.reasoning

    def test_provider_not_active_rejected(self, rrm):
        provider = ProviderResource(
            provider_id="prov-un", name="Unavailable Provider",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.UNAVAILABLE,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r5", resource_id="prov-un",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d5", registration_id="reg5",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "status_active" in decision.reasoning

    def test_provider_not_registered_rejected(self, rrm):
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r6", resource_id="prov-missing",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d6", registration_id="reg6",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "resource_not_registered" in decision.reasoning


# ---------------------------------------------------------------------------
# E — Canonical activation authority: Capability prerequisites
# ---------------------------------------------------------------------------


class TestCapabilityActivationAuthority:
    def test_capability_all_prerequisites_met(self, rrm):
        cap = CapabilityResource(
            capability_id="cap-1", name="Test Capability",
            is_executable=True, status=ResourceStatus.ACTIVE,
        )
        rrm.register_capability(cap)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="cap-1",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_capability_not_executable_approved_by_authority(self, rrm):
        """Authority approves — is_executable is what activation fixes."""
        cap = CapabilityResource(
            capability_id="cap-ne", name="NE Capability",
            is_executable=False, status=ResourceStatus.ACTIVE,
        )
        rrm.register_capability(cap)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r2", resource_id="cap-ne",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d2", registration_id="reg2",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# F — Canonical activation authority: Agent prerequisites
# ---------------------------------------------------------------------------


class TestAgentActivationAuthority:
    def test_agent_all_prerequisites_met(self, rrm):
        agent = AgentResource(
            agent_id="ag-1", name="Test Agent",
            is_enabled=True, status=ResourceStatus.ACTIVE,
            installation_state=AgentInstallationState.INSTALLED,
        )
        rrm.register_agent(agent)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="ag-1",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_agent_not_enabled_approved_by_authority(self, rrm):
        """Authority approves — is_enabled/installation_state are what activation fixes."""
        agent = AgentResource(
            agent_id="ag-ne", name="NE Agent",
            is_enabled=False, status=ResourceStatus.ACTIVE,
            installation_state=AgentInstallationState.DEFINED,
        )
        rrm.register_agent(agent)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r2", resource_id="ag-ne",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d2", registration_id="reg2",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_agent_invalid_installation_state_approved_by_authority(self, rrm):
        """Authority approves — installation_state is what activation fixes."""
        agent = AgentResource(
            agent_id="ag-def", name="Defined Agent",
            is_enabled=True, status=ResourceStatus.ACTIVE,
            installation_state=AgentInstallationState.DEFINED,
        )
        rrm.register_agent(agent)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r3", resource_id="ag-def",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d3", registration_id="reg3",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# G — Canonical activation authority: Environment prerequisites
# ---------------------------------------------------------------------------


class TestEnvironmentActivationAuthority:
    def test_environment_all_prerequisites_met(self, rrm):
        env = ExecutionEnvironmentResource(
            environment_id="env-1",
            is_discovered=True, status=ResourceStatus.ACTIVE,
        )
        rrm.register_environment(env)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="env-1",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_environment_not_discovered_approved_by_authority(self, rrm):
        """Authority approves — is_discovered is what activation fixes."""
        env = ExecutionEnvironmentResource(
            environment_id="env-nd",
            is_discovered=False, status=ResourceStatus.ACTIVE,
        )
        rrm.register_environment(env)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r2", resource_id="env-nd",
            resource_kind=ResourceDiscoveryKind.ENVIRONMENT,
            discovery_id="d2", registration_id="reg2",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# H — Canonical activation authority: Account prerequisites
# ---------------------------------------------------------------------------


class TestAccountActivationAuthority:
    def test_account_all_prerequisites_met(self, rrm):
        acct = AccountResource(
            account_id="acct-1", provider_id="prov-1",
            name="Test Account",
            is_configured=True, secret_reference="secret-1",
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_account(acct)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="acct-1",
            resource_kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_account_no_secret_approved_by_authority(self, rrm):
        """Authority approves — secret_reference/is_configured are what activation fixes."""
        acct = AccountResource(
            account_id="acct-ns", provider_id="prov-1",
            name="NS Account",
            is_configured=True, secret_reference=None,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_account(acct)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r2", resource_id="acct-ns",
            resource_kind=ResourceDiscoveryKind.CONNECTED_SERVICE,
            discovery_id="d2", registration_id="reg2",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE


# ---------------------------------------------------------------------------
# I — Unsupported resource kind
# ---------------------------------------------------------------------------


class TestUnsupportedResourceKind:
    def test_unsupported_kind_rejected(self, rrm):
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="x-1",
            resource_kind=ResourceDiscoveryKind.TOOL,
            discovery_id="d1", registration_id="reg1",
        )
        decision = authority.evaluate(req)
        assert decision.decision_type == ResourceActivationDecisionType.REJECT
        assert "unsupported_resource_kind" in decision.reasoning


# ---------------------------------------------------------------------------
# J — Application boundary: Decision not found
# ---------------------------------------------------------------------------


class TestApplicationBoundaryDecisionNotFound:
    def test_nonexistent_decision_rejected(self, rrm):
        boundary = ActivationApplicationBoundary(
            rrm, {}, {}, set(),
        )
        result = boundary.apply("nonexistent-decision")
        assert result.success is False
        assert result.reason == "decision_not_found"


# ---------------------------------------------------------------------------
# K — Application boundary: Decision already consumed
# ---------------------------------------------------------------------------


class TestApplicationBoundaryDecisionConsumed:
    def test_consumed_decision_rejected(self, rrm):
        decision = ResourceActivationDecision(
            decision_id="dec-consumed", request_id="r1",
            resource_id="prov-1", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {}, {"dec-consumed": decision}, {"dec-consumed"},
        )
        result = boundary.apply("dec-consumed")
        assert result.success is False
        assert result.reason == "decision_already_consumed"


# ---------------------------------------------------------------------------
# L — Application boundary: Decision not approved
# ---------------------------------------------------------------------------


class TestApplicationBoundaryDecisionNotApproved:
    def test_rejected_decision_not_applied(self, rrm):
        decision = ResourceActivationDecision(
            decision_id="dec-rej", request_id="r1",
            resource_id="prov-1", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.REJECT,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {}, {"dec-rej": decision}, set(),
        )
        result = boundary.apply("dec-rej")
        assert result.success is False
        assert result.reason == "decision_not_approved"


# ---------------------------------------------------------------------------
# M — Application boundary: Request not found
# ---------------------------------------------------------------------------


class TestApplicationBoundaryRequestNotFound:
    def test_missing_request_rejected(self, rrm):
        decision = ResourceActivationDecision(
            decision_id="dec-nr", request_id="r-missing",
            resource_id="prov-1", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {}, {"dec-nr": decision}, set(),
        )
        result = boundary.apply("dec-nr")
        assert result.success is False
        assert result.reason == "request_not_found"


# ---------------------------------------------------------------------------
# N — Application boundary: TOCTOU revalidation — resource not registered
# ---------------------------------------------------------------------------


class TestApplicationBoundaryResourceNotRegistered:
    def test_resource_removed_before_apply(self, rrm):
        request = ResourceActivationRequest(
            request_id="r1", resource_id="prov-gone",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-gr", request_id="r1",
            resource_id="prov-gone", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-gr": decision}, set(),
        )
        result = boundary.apply("dec-gr")
        assert result.success is False
        assert result.reason == "resource_not_registered"


# ---------------------------------------------------------------------------
# O — Application boundary: TOCTOU revalidation — resource became template
# ---------------------------------------------------------------------------


class TestApplicationBoundaryResourceBecameTemplate:
    def test_template_resource_rejected_at_apply(self, rrm):
        provider = ProviderResource(
            provider_id="prov-tpl2", name="TPL2",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.ACTIVE, is_template=True,
        )
        rrm.register_provider(provider)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="prov-tpl2",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-tpl", request_id="r1",
            resource_id="prov-tpl2", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-tpl": decision}, set(),
        )
        result = boundary.apply("dec-tpl")
        assert result.success is False
        assert result.reason == "resource_is_template"


# ---------------------------------------------------------------------------
# P — Application boundary: TOCTOU revalidation — resource not active
# ---------------------------------------------------------------------------


class TestApplicationBoundaryResourceNotActive:
    def test_inactive_resource_rejected_at_apply(self, rrm):
        provider = ProviderResource(
            provider_id="prov-deg", name="DEG",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.DEGRADED,
        )
        rrm.register_provider(provider)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="prov-deg",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-deg", request_id="r1",
            resource_id="prov-deg", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-deg": decision}, set(),
        )
        result = boundary.apply("dec-deg")
        assert result.success is False
        assert result.reason == "resource_not_active"


# ---------------------------------------------------------------------------
# Q — Application boundary: Successful activation application
# ---------------------------------------------------------------------------


class TestApplicationBoundarySuccessfulActivation:
    def test_provider_activation_applied(self, rrm):
        provider = ProviderResource(
            provider_id="prov-ok", name="OK Provider",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="prov-ok",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-ok", request_id="r1",
            resource_id="prov-ok", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-ok": decision}, set(),
        )
        result = boundary.apply("dec-ok")
        assert result.success is True
        assert result.reason == "activation_applied"
        assert "is_configured" in result.fields_updated
        assert "has_active_account" in result.fields_updated
        assert "dec-ok" in boundary._consumed  # type: ignore[attr-defined]

    def test_capability_activation_applied(self, rrm):
        cap = CapabilityResource(
            capability_id="cap-ok", name="OK Cap",
            is_executable=False, status=ResourceStatus.ACTIVE,
        )
        rrm.register_capability(cap)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="cap-ok",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-cap", request_id="r1",
            resource_id="cap-ok", resource_kind=ResourceDiscoveryKind.CAPABILITY,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-cap": decision}, set(),
        )
        result = boundary.apply("dec-cap")
        assert result.success is True
        assert "is_executable" in result.fields_updated

    def test_agent_activation_applied(self, rrm):
        agent = AgentResource(
            agent_id="ag-ok", name="OK Agent",
            is_enabled=False, status=ResourceStatus.ACTIVE,
            installation_state=AgentInstallationState.DEFINED,
        )
        rrm.register_agent(agent)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="ag-ok",
            resource_kind=ResourceDiscoveryKind.AGENT,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-ag", request_id="r1",
            resource_id="ag-ok", resource_kind=ResourceDiscoveryKind.AGENT,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-ag": decision}, set(),
        )
        result = boundary.apply("dec-ag")
        assert result.success is True
        assert "is_enabled" in result.fields_updated
        assert "installation_state" in result.fields_updated


# ---------------------------------------------------------------------------
# R — Application boundary: Single-use enforcement
# ---------------------------------------------------------------------------


class TestApplicationBoundarySingleUse:
    def test_decision_cannot_be_reused(self, rrm):
        provider = ProviderResource(
            provider_id="prov-reuse", name="Reuse Provider",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        request = ResourceActivationRequest(
            request_id="r1", resource_id="prov-reuse",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        decision = ResourceActivationDecision(
            decision_id="dec-reuse", request_id="r1",
            resource_id="prov-reuse", resource_kind=ResourceDiscoveryKind.PROVIDER,
            decision_type=ResourceActivationDecisionType.APPROVE,
        )
        consumed: set[str] = set()
        boundary = ActivationApplicationBoundary(
            rrm, {"r1": request}, {"dec-reuse": decision}, consumed,
        )
        result1 = boundary.apply("dec-reuse")
        assert result1.success is True
        result2 = boundary.apply("dec-reuse")
        assert result2.success is False
        assert result2.reason == "decision_already_consumed"


# ---------------------------------------------------------------------------
# S — Service: Full pipeline
# ---------------------------------------------------------------------------


class TestActivationServicePipeline:
    def test_create_request(self, activation_service):
        req = activation_service.create_request(
            resource_id="prov-1",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        assert req.resource_id == "prov-1"
        assert req.request_id in activation_service.requests

    def test_evaluate(self, activation_service, rrm):
        provider = ProviderResource(
            provider_id="prov-ev", name="EV Provider",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        req = activation_service.create_request(
            resource_id="prov-ev",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        decision = activation_service.evaluate(req.request_id)
        assert decision.decision_type == ResourceActivationDecisionType.APPROVE

    def test_evaluate_missing_request_raises(self, activation_service):
        with pytest.raises(ActivationError, match="not found"):
            activation_service.evaluate("nonexistent")

    def test_full_activate(self, activation_service, rrm):
        provider = ProviderResource(
            provider_id="prov-fa", name="FA Provider",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        req = activation_service.create_request(
            resource_id="prov-fa",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        result = activation_service.activate(req.request_id)
        assert result.success is True
        assert "is_configured" in result.fields_updated

    def test_full_activate_rejected(self, activation_service, rrm):
        provider = ProviderResource(
            provider_id="prov-rej", name="REJ Provider",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.UNAVAILABLE,
        )
        rrm.register_provider(provider)
        req = activation_service.create_request(
            resource_id="prov-rej",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        result = activation_service.activate(req.request_id)
        assert result.success is False


# ---------------------------------------------------------------------------
# T — Service: Decision consumption tracking
# ---------------------------------------------------------------------------


class TestActivationServiceConsumptionTracking:
    def test_consumed_decision_tracked(self, activation_service, rrm):
        provider = ProviderResource(
            provider_id="prov-ct", name="CT Provider",
            is_configured=True, has_active_account=True,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        req = activation_service.create_request(
            resource_id="prov-ct",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        # activate() calls evaluate() internally, producing a decision
        # that gets consumed. Track the decision from the service's
        # internal store after activation.
        pre_consumed = activation_service.consumed_decisions
        result = activation_service.activate(req.request_id)
        assert result.success is True
        post_consumed = activation_service.consumed_decisions
        # A new decision was consumed
        new_consumed = post_consumed - pre_consumed
        assert len(new_consumed) == 1
        consumed_id = next(iter(new_consumed))
        # The consumed decision matches the result
        assert consumed_id == result.decision_id


# ---------------------------------------------------------------------------
# U — Adversarial: No mutation without authority
# ---------------------------------------------------------------------------


class TestAdversarialNoMutationWithoutAuthority:
    def test_request_does_not_mutate_rrm(self, activation_service, rrm):
        provider = ProviderResource(
            provider_id="prov-noauth", name="NoAuth",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        activation_service.create_request(
            resource_id="prov-noauth",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1",
            registration_id="reg1",
        )
        p = rrm.get_provider("prov-noauth")
        assert p is not None
        assert p.is_configured is False
        assert p.has_active_account is False

    def test_authority_does_not_mutate_rrm(self, rrm):
        provider = ProviderResource(
            provider_id="prov-noauth2", name="NoAuth2",
            is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(provider)
        authority = CanonicalResourceActivationAuthority(rrm)
        req = ResourceActivationRequest(
            request_id="r1", resource_id="prov-noauth2",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            discovery_id="d1", registration_id="reg1",
        )
        authority.evaluate(req)
        p = rrm.get_provider("prov-noauth2")
        assert p is not None
        assert p.is_configured is False
        assert p.has_active_account is False


# ---------------------------------------------------------------------------
# V — Adversarial: No discovery authority leak
# ---------------------------------------------------------------------------


class TestAdversarialNoDiscoveryLeak:
    def test_activation_authority_has_no_discovery(self):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        assert not hasattr(CanonicalResourceActivationAuthority, 'discover')
        assert not hasattr(CanonicalResourceActivationAuthority, 'create_evidence')


# ---------------------------------------------------------------------------
# W — Adversarial: No promotion authority leak
# ---------------------------------------------------------------------------


class TestAdversarialNoPromotionLeak:
    def test_activation_authority_has_no_promotion(self):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        assert not hasattr(CanonicalResourceActivationAuthority, 'propose')
        assert not hasattr(CanonicalResourceActivationAuthority, 'approve_proposal')


# ---------------------------------------------------------------------------
# X — Adversarial: No registration authority leak
# ---------------------------------------------------------------------------


class TestAdversarialNoRegistrationLeak:
    def test_activation_authority_has_no_registration(self):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        assert not hasattr(CanonicalResourceActivationAuthority, 'register_provider')
        assert not hasattr(CanonicalResourceActivationAuthority, 'register_capability')


# ---------------------------------------------------------------------------
# Y — Composition wiring
# ---------------------------------------------------------------------------


class TestCompositionWiring:
    def test_activation_service_wired(self):
        from intent_kernel.application.composition import KernelBuilder
        builder = KernelBuilder()
        components = builder.build()
        assert hasattr(components, 'resource_activation_service')
        assert isinstance(
            components.resource_activation_service,
            CanonicalResourceActivationService,
        )

    def test_activation_authority_wired(self):
        from intent_kernel.application.composition import KernelBuilder
        builder = KernelBuilder()
        components = builder.build()
        assert isinstance(
            components.resource_activation_service.authority,
            CanonicalResourceActivationAuthority,
        )

    def test_activation_boundary_wired(self):
        from intent_kernel.application.composition import KernelBuilder
        builder = KernelBuilder()
        components = builder.build()
        assert isinstance(
            components.resource_activation_service.application_boundary,
            ActivationApplicationBoundary,
        )


# ---------------------------------------------------------------------------
# Z — Adversarial: No execution authority leak
# ---------------------------------------------------------------------------


class TestAdversarialNoExecutionLeak:
    def test_activation_authority_has_no_execution(self):
        from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
        assert not hasattr(CanonicalResourceActivationAuthority, 'execute')
        assert not hasattr(CanonicalResourceActivationAuthority, 'dispatch')
        assert not hasattr(CanonicalResourceActivationAuthority, 'confirm')
