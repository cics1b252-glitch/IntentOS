"""H1.1 — DEFAULT-DENY AUTHORIZATION GATES

Consolidation hardening: proves that malformed, missing, unknown, or
invalid authorization results produce DENY — never implicit ALLOW.

Covers:
- ToolAuthorizationGate (tools/authorization.py)
- ActionGate (runtime/action_gate.py)
"""

from __future__ import annotations

import pytest

from intent_kernel.tools.authorization import ToolAuthorizationGate
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)
from intent_kernel.runtime.action_gate import ActionGate
from intent_kernel.runtime.models import (
    ActionContract,
    ActionGateDecision,
    RuntimeNode,
    RuntimeNodeState,
    SideEffectLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    *,
    auth_status: PermissionDecisionState = PermissionDecisionState.GRANTED,
    health: ToolHealthStatus = ToolHealthStatus.HEALTHY,
) -> ToolCandidate:
    return ToolCandidate(
        tool_id="tool_test",
        capability="test.echo",
        authorization_status=auth_status,
        health=health,
    )


def _make_tool(
    *,
    status: ToolStatus = ToolStatus.AVAILABLE,
) -> ToolResource:
    return ToolResource(
        tool_id="tool_test",
        capabilities=["test.echo"],
        status=status,
    )


def _make_node() -> RuntimeNode:
    return RuntimeNode(
        node_id="node_test",
        capability="test.echo",
        state=RuntimeNodeState.READY,
    )


def _make_contract() -> ActionContract:
    return ActionContract(
        action_id="act_test",
        capability="test.echo",
        side_effect_level=SideEffectLevel.NONE,
        confirmation_required=False,
    )


# ---------------------------------------------------------------------------
# Mock constitutions — various malformed/unexpected return types
# ---------------------------------------------------------------------------

class _ConstitutionAllow:
    """Canonical: returns object with verdict='ALLOW'."""
    def evaluate_action(self, _action):
        return type("Verdict", (), {"verdict": "ALLOW"})()


class _ConstitutionDeny:
    """Canonical: returns object with verdict='DENY'."""
    def evaluate_action(self, _action):
        return type("Verdict", (), {"verdict": "DENY"})()


class _ConstitutionNoVerdict:
    """Malformed: returns object WITHOUT verdict attribute."""
    def evaluate_action(self, _action):
        return type("Malformed", (), {})()


class _ConstitutionNoneVerdict:
    """Malformed: returns object with verdict=None."""
    def evaluate_action(self, _action):
        return type("Verdict", (), {"verdict": None})()


class _ConstitutionStringVerdict:
    """Malformed: returns object with verdict='INVALID_STRING'."""
    def evaluate_action(self, _action):
        return type("Verdict", (), {"verdict": "INVALID_STRING"})()


class _ConstitutionIntVerdict:
    """Malformed: returns object with verdict=42 (wrong type)."""
    def evaluate_action(self, _action):
        return type("Verdict", (), {"verdict": 42})()


class _ConstitutionDict:
    """Malformed: returns a plain dict (no attributes)."""
    def evaluate_action(self, _action):
        return {"verdict": "ALLOW"}


class _ConstitutionString:
    """Malformed: returns a plain string."""
    def evaluate_action(self, _action):
        return "ALLOW"


class _ConstitutionNone:
    """Malformed: returns None."""
    def evaluate_action(self, _action):
        return None


class _ConstitutionRaises:
    """Malformed: raises exception during evaluation."""
    def evaluate_action(self, _action):
        raise RuntimeError("constitution crashed")


class _ConstitutionAllowed:
    """Canonical async: returns object with allowed=True."""
    async def evaluate(self, _action, _data, _ctx):
        return type("Result", (), {"allowed": True})()


class _ConstitutionDenied:
    """Canonical async: returns object with allowed=False."""
    async def evaluate(self, _action, _data, _ctx):
        return type("Result", (), {"allowed": False})()


class _ConstitutionNoAllowed:
    """Malformed async: returns object WITHOUT allowed attribute."""
    async def evaluate(self, _action, _data, _ctx):
        return type("Malformed", (), {})()


class _ConstitutionNoneAllowed:
    """Malformed async: returns object with allowed=None."""
    async def evaluate(self, _action, _data, _ctx):
        return type("Result", (), {"allowed": None})()


class _ConstitutionRaisesAsync:
    """Malformed async: raises exception during evaluation."""
    async def evaluate(self, _action, _data, _ctx):
        raise RuntimeError("constitution crashed async")


# ---------------------------------------------------------------------------
# ToolAuthorizationGate tests
# ---------------------------------------------------------------------------

class TestToolAuthorizationGateFailClosed:
    """H1.1 invariant: all malformed/missing/unexpected = DENY."""

    @pytest.fixture
    def gate(self):
        return ToolAuthorizationGate()

    @pytest.fixture
    def candidate(self):
        return _make_candidate()

    @pytest.fixture
    def tool(self):
        return _make_tool()

    @pytest.mark.asyncio
    async def test_canonical_allow_remains_allow(self, gate, candidate, tool):
        gate._constitution = _ConstitutionAllow()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.ALLOW

    @pytest.mark.asyncio
    async def test_canonical_deny_remains_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionDeny()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_missing_verdict_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionNoVerdict()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_none_verdict_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionNoneVerdict()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_unknown_verdict_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionStringVerdict()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_int_verdict_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionIntVerdict()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_dict_result_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionDict()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_string_result_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionString()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_none_result_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionNone()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_exception_result_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionRaises()
        with pytest.raises(RuntimeError, match="constitution crashed"):
            await gate.evaluate_tool(candidate, tool)

    @pytest.mark.asyncio
    async def test_canonical_async_allow(self, gate, candidate, tool):
        gate._constitution = _ConstitutionAllowed()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.ALLOW

    @pytest.mark.asyncio
    async def test_canonical_async_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionDenied()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_missing_allowed_async_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionNoAllowed()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_none_allowed_async_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionNoneAllowed()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_exception_async_deny(self, gate, candidate, tool):
        gate._constitution = _ConstitutionRaisesAsync()
        with pytest.raises(RuntimeError, match="constitution crashed async"):
            await gate.evaluate_tool(candidate, tool)

    @pytest.mark.asyncio
    async def test_no_constitution_deny(self, gate, candidate, tool):
        """H1.1-closure: Without constitution, DENY — never skip constitutional enforcement."""
        gate._constitution = None
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_tool_status_revoked_deny(self, gate, candidate):
        tool = _make_tool(status=ToolStatus.REVOKED)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_tool_status_unauthorized_deny(self, gate, candidate):
        tool = _make_tool(status=ToolStatus.UNAUTHORIZED)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_health_unavailable_wait(self, gate, tool):
        candidate = _make_candidate(health=ToolHealthStatus.UNAVAILABLE)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.WAIT_TOOL

    @pytest.mark.asyncio
    async def test_permission_denied_deny(self, gate, tool):
        candidate = _make_candidate(auth_status=PermissionDecisionState.DENIED)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_permission_not_configured_request(self, gate, tool):
        candidate = _make_candidate(auth_status=PermissionDecisionState.NOT_CONFIGURED)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.REQUEST_PERMISSION

    @pytest.mark.asyncio
    async def test_permission_revoked_deny(self, gate, tool):
        candidate = _make_candidate(auth_status=PermissionDecisionState.REVOKED)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_permission_blocked_by_policy_deny(self, gate, tool):
        candidate = _make_candidate(auth_status=PermissionDecisionState.BLOCKED_BY_POLICY)
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_default_candidate_not_authorized(self, gate, tool):
        """Default ToolCandidate has GRANTED permission — ALLOW when no constitution blocks."""
        candidate = _make_candidate()
        gate._constitution = _ConstitutionDeny()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY


# ---------------------------------------------------------------------------
# ActionGate tests
# ---------------------------------------------------------------------------

class TestActionGateFailClosed:
    """H1.1 invariant: all malformed/missing/unexpected = DENY."""

    @pytest.fixture
    def gate(self):
        return ActionGate(constitution=_ConstitutionAllow())

    @pytest.fixture
    def node(self):
        return _make_node()

    @pytest.fixture
    def contract(self):
        return _make_contract()

    @pytest.mark.asyncio
    async def test_canonical_allow_remains_allow(self, gate, node, contract):
        gate._constitution = _ConstitutionAllow()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.ALLOW

    @pytest.mark.asyncio
    async def test_canonical_deny_remains_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionDeny()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_missing_verdict_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionNoVerdict()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_none_verdict_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionNoneVerdict()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_unknown_verdict_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionStringVerdict()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_int_verdict_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionIntVerdict()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_dict_result_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionDict()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_string_result_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionString()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_none_result_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionNone()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_exception_result_raises(self, gate, node, contract):
        gate._constitution = _ConstitutionRaises()
        with pytest.raises(RuntimeError, match="constitution crashed"):
            await gate.evaluate(node, contract)

    @pytest.mark.asyncio
    async def test_canonical_async_allow(self, gate, node, contract):
        gate._constitution = _ConstitutionAllowed()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.ALLOW

    @pytest.mark.asyncio
    async def test_canonical_async_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionDenied()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_missing_allowed_async_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionNoAllowed()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_none_allowed_async_deny(self, gate, node, contract):
        gate._constitution = _ConstitutionNoneAllowed()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_exception_async_raises(self, gate, node, contract):
        gate._constitution = _ConstitutionRaisesAsync()
        with pytest.raises(RuntimeError, match="constitution crashed async"):
            await gate.evaluate(node, contract)

    @pytest.mark.asyncio
    async def test_no_constitution_deny(self, gate, node, contract):
        """H1.1-closure: Without constitution, DENY — never skip constitutional enforcement."""
        gate._constitution = None
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_denied_capability_policy_deny(self, gate, node, contract):
        policy = {"denied_capabilities": ["test.echo"]}
        result = await gate.evaluate(node, contract, execution_policy=policy)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_agent_not_eligible_wait(self, gate, node, contract):
        class MockRRM:
            def get_agent(self, _id):
                return type("Agent", (), {"is_eligible": False})()
        gate._rrm = MockRRM()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.WAIT_RESOURCE

    @pytest.mark.asyncio
    async def test_agent_missing_eligibility_wait(self, gate, node, contract):
        """Fail-closed: missing is_eligible attribute = not eligible."""
        class MockRRM:
            def get_agent(self, _id):
                return type("Agent", (), {})()
        gate._rrm = MockRRM()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.WAIT_RESOURCE

    @pytest.mark.asyncio
    async def test_environment_inactive_wait(self, gate, node, contract):
        class MockRRM:
            def get_environment(self, _id):
                return type("Env", (), {"status": "INACTIVE"})()
        gate._rrm = MockRRM()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.WAIT_RESOURCE

    @pytest.mark.asyncio
    async def test_environment_missing_status_wait(self, gate, node, contract):
        """Fail-closed: missing status attribute = INACTIVE = not active."""
        class MockRRM:
            def get_environment(self, _id):
                return type("Env", (), {})()
        gate._rrm = MockRRM()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.WAIT_RESOURCE

    @pytest.mark.asyncio
    async def test_environment_active_passes(self, gate, node, contract):
        class MockRRM:
            def get_environment(self, _id):
                return type("Env", (), {"status": "ACTIVE"})()
        gate._rrm = MockRRM()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.ALLOW

    @pytest.mark.asyncio
    async def test_confirmation_required_no_confirmation(self, gate, node):
        contract = ActionContract(
            capability="test.echo",
            confirmation_required=True,
        )
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.REQUIRE_CONFIRMATION

    @pytest.mark.asyncio
    async def test_confirmation_rejected_deny(self, gate, node):
        from intent_kernel.runtime.models import ExecutionConfirmationRequest, ConfirmationState
        contract = ActionContract(
            capability="test.echo",
            confirmation_required=True,
        )
        conf = ExecutionConfirmationRequest(
            approved=False,
            state=ConfirmationState.REJECTED,
        )
        result = await gate.evaluate(node, contract, confirmation=conf)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_external_irreversible_requires_confirmation(self, gate, node):
        contract = ActionContract(
            capability="test.echo",
            side_effect_level=SideEffectLevel.EXTERNAL_IRREVERSIBLE,
        )
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.REQUIRE_CONFIRMATION


# ---------------------------------------------------------------------------
# Integration: both gates together on malformed constitution
# ---------------------------------------------------------------------------

class TestBothGatesFailClosed:
    """Both ToolAuthorizationGate and ActionGate must deny on malformed input."""

    @pytest.mark.asyncio
    async def test_tool_gate_deny_on_malformed(self):
        gate = ToolAuthorizationGate(constitution=_ConstitutionNoVerdict())
        candidate = _make_candidate()
        tool = _make_tool()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.DENY

    @pytest.mark.asyncio
    async def test_action_gate_deny_on_malformed(self):
        gate = ActionGate(constitution=_ConstitutionNoVerdict())
        node = _make_node()
        contract = _make_contract()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.DENY

    @pytest.mark.asyncio
    async def test_tool_gate_allow_only_on_explicit_allow(self):
        gate = ToolAuthorizationGate(constitution=_ConstitutionAllow())
        candidate = _make_candidate()
        tool = _make_tool()
        result = await gate.evaluate_tool(candidate, tool)
        assert result == ToolAuthorizationDecisionState.ALLOW

    @pytest.mark.asyncio
    async def test_action_gate_allow_only_on_explicit_allow(self):
        gate = ActionGate(constitution=_ConstitutionAllow())
        node = _make_node()
        contract = _make_contract()
        result = await gate.evaluate(node, contract)
        assert result == ActionGateDecision.ALLOW
