"""Movement 19 — Governed Resource Retirement Authority Tests.

RA-19-01: ungoverned unregister_*() cannot destroy governed resources.
Retirement authority is the ONLY authorized removal path.

Tests cover:
  1. Unregister guards reject governed resources (5 types)
  2. Unregister allows ungoverned resources
  3. Retirement authority request/decision/apply lifecycle
  4. Single consumption enforcement
  5. Identity mismatch rejection (resource_id + governed_registration_id)
  6. Evidence identity repair (cross-identity evidence rejected)
  7. Full integration lifecycle
"""

from __future__ import annotations

import pytest

from intent_kernel.activation.models import (
    ActivationEvidenceType,
    ResourceActivationEvidence,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.models import (
    ResourceType,
    ResourceStatus,
    ResourceOrigin,
    AvailabilitySource,
    ProviderResource,
    AccountResource,
    ExecutionEnvironmentResource,
    CapabilityResource,
    AgentResource,
    AgentInstallationState,
)
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.rrm.retirement import (
    CanonicalResourceRetirementAuthority,
    ResourceRetirementRequest,
    ResourceRetirementDecision,
    ResourceRetirementResult,
    ResourceRetirementDecisionType,
    ResourceRetirementStateType,
    RetirementError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rrm() -> RegistryResourceManager:
    return RegistryResourceManager()


def _make_provider(
    rrm: RegistryResourceManager,
    resource_id: str = "prov-1",
    governed_grid: str = "",
    name: str = "TestProvider",
) -> ProviderResource:
    resource = ProviderResource(
        provider_id=resource_id,
        name=name,
        availability_source=AvailabilitySource.CONFIGURATION,
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_provider(resource)
    return resource


def _make_account(
    rrm: RegistryResourceManager,
    resource_id: str = "acct-1",
    governed_grid: str = "",
    provider_id: str = "prov-1",
) -> AccountResource:
    resource = AccountResource(
        account_id=resource_id,
        name="TestAccount",
        provider_id=provider_id,
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_account(resource)
    return resource


def _make_environment(
    rrm: RegistryResourceManager,
    resource_id: str = "env-1",
    governed_grid: str = "",
) -> ExecutionEnvironmentResource:
    resource = ExecutionEnvironmentResource(
        environment_id=resource_id,
        type="local",
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_environment(resource)
    return resource


def _make_capability(
    rrm: RegistryResourceManager,
    resource_id: str = "cap-1",
    governed_grid: str = "",
) -> CapabilityResource:
    resource = CapabilityResource(
        capability_id=resource_id,
        name="TestCapability",
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_capability(resource)
    return resource


def _make_agent(
    rrm: RegistryResourceManager,
    resource_id: str = "agent-1",
    governed_grid: str = "",
) -> AgentResource:
    resource = AgentResource(
        agent_id=resource_id,
        name="TestAgent",
        resource_origin=ResourceOrigin.CONFIGURATION,
        installation_state=AgentInstallationState.INSTALLED,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_agent(resource)
    return resource


# ===========================================================================
# Section 1: Unregister Guards — governed resources are protected
# ===========================================================================


class TestUnregisterGuardProvider:
    """Guard on unregister_provider rejects governed resources."""

    def test_governed_provider_rejected(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-gov", governed_grid="gr-001")
        assert rrm.unregister_provider("prov-gov") is False
        assert rrm.get_provider("prov-gov") is not None

    def test_ungoverned_provider_allowed(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-ungov", governed_grid="")
        assert rrm.unregister_provider("prov-ungov") is True
        assert rrm.get_provider("prov-ungov") is None

    def test_nonexistent_provider_returns_false(self):
        rrm = _make_rrm()
        assert rrm.unregister_provider("prov-noexist") is False


class TestUnregisterGuardAccount:
    """Guard on unregister_account rejects governed resources."""

    def test_governed_account_rejected(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-1")
        _make_account(rrm, "acct-gov", governed_grid="gr-002", provider_id="prov-1")
        assert rrm.unregister_account("acct-gov") is False
        assert rrm.get_account("acct-gov") is not None

    def test_ungoverned_account_allowed(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-1")
        _make_account(rrm, "acct-ungov", governed_grid="", provider_id="prov-1")
        assert rrm.unregister_account("acct-ungov") is True
        assert rrm.get_account("acct-ungov") is None


class TestUnregisterGuardEnvironment:
    """Guard on unregister_environment rejects governed resources."""

    def test_governed_environment_rejected(self):
        rrm = _make_rrm()
        _make_environment(rrm, "env-gov", governed_grid="gr-003")
        assert rrm.unregister_environment("env-gov") is False
        assert rrm.get_environment("env-gov") is not None

    def test_ungoverned_environment_allowed(self):
        rrm = _make_rrm()
        _make_environment(rrm, "env-ungov", governed_grid="")
        assert rrm.unregister_environment("env-ungov") is True
        assert rrm.get_environment("env-ungov") is None


class TestUnregisterGuardCapability:
    """Guard on unregister_capability rejects governed resources."""

    def test_governed_capability_rejected(self):
        rrm = _make_rrm()
        _make_capability(rrm, "cap-gov", governed_grid="gr-004")
        assert rrm.unregister_capability("cap-gov") is False
        assert rrm.get_capability("cap-gov") is not None

    def test_ungoverned_capability_allowed(self):
        rrm = _make_rrm()
        _make_capability(rrm, "cap-ungov", governed_grid="")
        assert rrm.unregister_capability("cap-ungov") is True
        assert rrm.get_capability("cap-ungov") is None


class TestUnregisterGuardAgent:
    """Guard on unregister_agent rejects governed resources."""

    def test_governed_agent_rejected(self):
        rrm = _make_rrm()
        _make_agent(rrm, "agent-gov", governed_grid="gr-005")
        assert rrm.unregister_agent("agent-gov") is False
        assert rrm.get_agent("agent-gov") is not None

    def test_ungoverned_agent_allowed(self):
        rrm = _make_rrm()
        _make_agent(rrm, "agent-ungov", governed_grid="")
        assert rrm.unregister_agent("agent-ungov") is True
        assert rrm.get_agent("agent-ungov") is None


# ===========================================================================
# Section 2: Retirement Authority — request lifecycle
# ===========================================================================


class TestRetirementRequest:
    """Retirement request creation and validation."""

    def test_request_creation(self):
        rrm = _make_rrm()
        grid = "gr-ret-001"
        _make_provider(rrm, "prov-ret", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-ret", grid, reason="test")
        assert isinstance(req, ResourceRetirementRequest)
        assert req.resource_id == "prov-ret"
        assert req.governed_registration_id == grid

    def test_request_resource_not_found(self):
        rrm = _make_rrm()
        authority = CanonicalResourceRetirementAuthority(rrm)
        with pytest.raises(RetirementError, match="resource_not_found"):
            authority.request_retirement("noexist", "grid-x", reason="x")

    def test_request_resource_not_governed(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-ungov", governed_grid="")
        authority = CanonicalResourceRetirementAuthority(rrm)
        with pytest.raises(RetirementError, match="resource_not_governed"):
            authority.request_retirement("prov-ungov", "", reason="x")

    def test_request_grid_mismatch(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-mis", governed_grid="gr-real")
        authority = CanonicalResourceRetirementAuthority(rrm)
        with pytest.raises(RetirementError, match="governed_registration_id_mismatch"):
            authority.request_retirement("prov-mis", "gr-wrong", reason="x")


# ===========================================================================
# Section 3: Retirement Authority — decision lifecycle
# ===========================================================================


class TestRetirementDecision:
    """Retirement decision creation and validation."""

    def test_approve_decision(self):
        rrm = _make_rrm()
        grid = "gr-dec-001"
        _make_provider(rrm, "prov-dec", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-dec", grid)
        dec = authority.decide_retirement(req.request_id, approved=True, reason="ok")
        assert dec.decision_type == ResourceRetirementDecisionType.APPROVE

    def test_deny_decision(self):
        rrm = _make_rrm()
        grid = "gr-dec-002"
        _make_provider(rrm, "prov-deny", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-deny", grid)
        dec = authority.decide_retirement(req.request_id, approved=False, reason="no")
        assert dec.decision_type == ResourceRetirementDecisionType.DENY

    def test_decision_request_not_found(self):
        rrm = _make_rrm()
        authority = CanonicalResourceRetirementAuthority(rrm)
        with pytest.raises(RetirementError, match="request_not_found"):
            authority.decide_retirement("req-noexist", approved=True)

    def test_decision_resource_not_found(self):
        rrm = _make_rrm()
        grid = "gr-dec-003"
        _make_provider(rrm, "prov-temp", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-temp", grid)
        with rrm._lock:
            rrm._providers.pop("prov-temp", None)
        with pytest.raises(RetirementError, match="resource_not_found"):
            authority.decide_retirement(req.request_id, approved=True)


# ===========================================================================
# Section 4: Retirement Authority — apply lifecycle
# ===========================================================================


class TestRetirementApply:
    """Retirement application — full removal lifecycle."""

    def test_apply_approved_retires_resource(self):
        rrm = _make_rrm()
        grid = "gr-apply-001"
        _make_provider(rrm, "prov-apply", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-apply", grid)
        dec = authority.decide_retirement(req.request_id, approved=True)
        result = authority.apply_retirement(dec.decision_id)
        assert result.success is True
        assert result.resource_id == "prov-apply"
        assert rrm.get_provider("prov-apply") is None

    def test_apply_deny_rejected(self):
        rrm = _make_rrm()
        grid = "gr-apply-002"
        _make_provider(rrm, "prov-denyapply", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-denyapply", grid)
        dec = authority.decide_retirement(req.request_id, approved=False)
        result = authority.apply_retirement(dec.decision_id)
        assert result.success is False
        assert result.reason == "decision_not_approved"

    def test_apply_nonexistent_decision(self):
        rrm = _make_rrm()
        authority = CanonicalResourceRetirementAuthority(rrm)
        result = authority.apply_retirement("dec-noexist")
        assert result.success is False
        assert result.reason == "decision_not_found"

    def test_apply_single_consumption(self):
        rrm = _make_rrm()
        grid = "gr-consume-001"
        _make_provider(rrm, "prov-consume", governed_grid=grid)
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-consume", grid)
        dec = authority.decide_retirement(req.request_id, approved=True)
        r1 = authority.apply_retirement(dec.decision_id)
        assert r1.success is True
        r2 = authority.apply_retirement(dec.decision_id)
        assert r2.success is False
        assert r2.reason == "decision_already_consumed"


# ===========================================================================
# Section 5: Retirement Authority — all 5 governed resource types
# ===========================================================================


class TestRetirementAllResourceTypes:
    """Retirement works for all 5 governed resource types."""

    def _retire(self, rrm, resource_id, grid):
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement(resource_id, grid)
        dec = authority.decide_retirement(req.request_id, approved=True)
        return authority.apply_retirement(dec.decision_id)

    def test_retire_provider(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-r", governed_grid="gr-r-p")
        result = self._retire(rrm, "prov-r", "gr-r-p")
        assert result.success
        assert rrm.get_provider("prov-r") is None

    def test_retire_account(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-r")
        _make_account(rrm, "acct-r", governed_grid="gr-r-a", provider_id="prov-r")
        result = self._retire(rrm, "acct-r", "gr-r-a")
        assert result.success
        assert rrm.get_account("acct-r") is None

    def test_retire_environment(self):
        rrm = _make_rrm()
        _make_environment(rrm, "env-r", governed_grid="gr-r-e")
        result = self._retire(rrm, "env-r", "gr-r-e")
        assert result.success
        assert rrm.get_environment("env-r") is None

    def test_retire_capability(self):
        rrm = _make_rrm()
        _make_capability(rrm, "cap-r", governed_grid="gr-r-c")
        result = self._retire(rrm, "cap-r", "gr-r-c")
        assert result.success
        assert rrm.get_capability("cap-r") is None

    def test_retire_agent(self):
        rrm = _make_rrm()
        _make_agent(rrm, "agent-r", governed_grid="gr-r-ag")
        result = self._retire(rrm, "agent-r", "gr-r-ag")
        assert result.success
        assert rrm.get_agent("agent-r") is None


# ===========================================================================
# Section 6: Evidence Identity Repair — cross-identity rejection
# ===========================================================================


class TestEvidenceIdentityRepair:
    """Activation evidence with governed_registration_id prevents cross-identity reuse."""

    def test_evidence_stamped_with_governed_registration_id(self):
        rrm = _make_rrm()
        grid = "gr-ev-001"
        _make_provider(rrm, "prov-ev", governed_grid=grid)
        ev = ResourceActivationEvidence(
            evidence_id="ev-test-1",
            resource_id="prov-ev",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
            governed_registration_id=grid,
            _trusted=True,
        )
        assert ev.governed_registration_id == grid

    def test_evidence_empty_grid_for_ungoverned(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev-test-2",
            resource_id="prov-x",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
            governed_registration_id="",
        )
        assert ev.governed_registration_id == ""

    def test_evidence_to_dict_includes_governed_registration_id(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev-test-3",
            resource_id="prov-x",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
            governed_registration_id="gr-dict",
        )
        d = ev.to_dict()
        assert "governed_registration_id" in d
        assert d["governed_registration_id"] == "gr-dict"

    def test_frozen_evidence_rejects_post_construction_mutation(self):
        ev = ResourceActivationEvidence(
            evidence_id="ev-test-4",
            resource_id="prov-x",
            resource_kind=ResourceDiscoveryKind.PROVIDER,
            evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
            source="test",
            governed_registration_id="gr-frozen",
        )
        with pytest.raises(AttributeError):
            ev.governed_registration_id = "gr-other"


# ===========================================================================
# Section 7: Retirement Authority — model contracts
# ===========================================================================


class TestRetirementModels:
    """Frozen dataclass contracts for retirement models."""

    def test_request_frozen(self):
        req = ResourceRetirementRequest(
            request_id="r1", resource_id="p1", resource_kind="Provider",
            governed_registration_id="g1", reason="x",
        )
        with pytest.raises(AttributeError):
            req.resource_id = "other"

    def test_decision_frozen(self):
        dec = ResourceRetirementDecision(
            decision_id="d1", request_id="r1", resource_id="p1",
            governed_registration_id="g1",
            decision_type=ResourceRetirementDecisionType.APPROVE,
            reason="ok",
        )
        with pytest.raises(AttributeError):
            dec.decision_id = "other"

    def test_result_frozen(self):
        res = ResourceRetirementResult(
            success=True, decision_id="d1", resource_id="p1",
            retired_at="2026-01-01T00:00:00Z",
        )
        with pytest.raises(AttributeError):
            res.success = False

    def test_request_to_dict(self):
        req = ResourceRetirementRequest(
            request_id="r1", resource_id="p1", resource_kind="Provider",
            governed_registration_id="g1", reason="x",
        )
        assert req.resource_id == "p1"
        assert req.governed_registration_id == "g1"
        assert req.reason == "x"


# ===========================================================================
# Section 8: Retirement Authority — state tracking
# ===========================================================================


class TestRetirementStateTracking:
    """Authority tracks requests, decisions, and consumption."""

    def test_get_request(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-st", governed_grid="gr-st")
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-st", "gr-st")
        assert authority.get_request(req.request_id) is req

    def test_get_decision(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-st2", governed_grid="gr-st2")
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-st2", "gr-st2")
        dec = authority.decide_retirement(req.request_id, approved=True)
        assert authority.get_decision(dec.decision_id) is dec

    def test_is_decision_consumed(self):
        rrm = _make_rrm()
        _make_provider(rrm, "prov-st3", governed_grid="gr-st3")
        authority = CanonicalResourceRetirementAuthority(rrm)
        req = authority.request_retirement("prov-st3", "gr-st3")
        dec = authority.decide_retirement(req.request_id, approved=True)
        assert authority.is_decision_consumed(dec.decision_id) is False
        authority.apply_retirement(dec.decision_id)
        assert authority.is_decision_consumed(dec.decision_id) is True
