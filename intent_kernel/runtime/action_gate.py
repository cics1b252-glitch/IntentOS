"""Action Gate - RFC-0015 (STUDIO 10.2).

Evaluates action contracts prior to execution against Constitution, ExecutionPolicy,
MissionConstraints, resource eligibility, required permissions, user confirmation, and idempotency.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from intent_kernel.instructions import MissionConstraint
from intent_kernel.runtime.models import (
    ActionContract,
    ActionGateDecision,
    ExecutionConfirmationRequest,
    RuntimeNode,
    SideEffectLevel,
)


class ActionGate:
    """Pre-execution validation gate for Action Contracts."""

    def __init__(
        self,
        rrm_service: Optional[Any] = None,
        constitution: Optional[Any] = None,
        replay_policy: Optional[Callable[[str, str], Optional[str]]] = None,
    ) -> None:
        self._rrm = rrm_service
        self._constitution = constitution
        self._replay_policy = replay_policy
        self._executed_idempotency_keys: set = set()

    def mark_idempotency_key_executed(self, key: str) -> None:
        """Record an idempotency key as executed."""
        if key:
            self._executed_idempotency_keys.add(key)

    def is_idempotency_key_executed(self, key: str) -> bool:
        """Check if an idempotency key was previously executed."""
        return bool(key and key in self._executed_idempotency_keys)

    async def evaluate(
        self,
        node: RuntimeNode,
        contract: ActionContract,
        mission_constraints: Optional[List[MissionConstraint]] = None,
        execution_policy: Optional[Dict[str, Any]] = None,
        confirmation: Optional[ExecutionConfirmationRequest] = None,
        *,
        durable_confirmation_required: bool = False,
    ) -> ActionGateDecision:
        """Evaluate an action against the strict precedence hierarchy."""

        # 1. Constitution / Safety Check - fail-closed
        if self._constitution is None:
            return ActionGateDecision.DENY
        if hasattr(self._constitution, "evaluate_action"):
            res = self._constitution.evaluate_action(contract.to_dict())
            verdict = getattr(res, "verdict", None)
            if verdict != "ALLOW":
                return ActionGateDecision.DENY
        elif hasattr(self._constitution, "evaluate"):
            res = await self._constitution.evaluate(
                "action.execute", contract.to_dict(), {}
            )
            if not getattr(res, "allowed", False):
                return ActionGateDecision.DENY

        # 2. Explicit Deny Policy Check
        policy = execution_policy or {}
        denied_capabilities = policy.get("denied_capabilities", [])
        if contract.capability in denied_capabilities:
            return ActionGateDecision.DENY

        # 3. Persistent Mission Constraints Check
        constraints = mission_constraints or []
        for mc in constraints:
            if mc.blocking and mc.constraint_type == "DENY_CAPABILITY":
                if mc.expected_behavior == contract.capability:
                    return ActionGateDecision.DENY

        # 4. User Confirmation Requirement
        requires_user_approval = (
            contract.confirmation_required
            or contract.side_effect_level in (SideEffectLevel.EXTERNAL_IRREVERSIBLE, SideEffectLevel.EXTERNAL_REVERSIBLE)
        )

        # M32B-3 durable confirmation requirement
        if durable_confirmation_required:
            requires_user_approval = True

        if requires_user_approval:
            if confirmation is None or confirmation.approved is None:
                return ActionGateDecision.REQUIRE_CONFIRMATION
            if confirmation.approved is False:
                return ActionGateDecision.DENY

        # 5. Resource Eligibility Revalidation (via RRM)
        if self._rrm:
            if hasattr(self._rrm, "get_agent"):
                agent_res = self._rrm.get_agent(node.agent_id)
                if agent_res and not getattr(agent_res, "is_eligible", False):
                    return ActionGateDecision.WAIT_RESOURCE
            if hasattr(self._rrm, "get_environment"):
                env_res = self._rrm.get_environment(node.environment_id)
                if env_res and getattr(env_res, "status", "INACTIVE") != "ACTIVE":
                    return ActionGateDecision.WAIT_RESOURCE

        # 6. Idempotency / Replay Check
        if contract.idempotency_key and self.is_idempotency_key_executed(contract.idempotency_key):
            return self._resolve_replay(node, contract)

        # 7. Normal Execution Allowed
        return ActionGateDecision.ALLOW

    def _resolve_replay(
        self,
        node: RuntimeNode,
        contract: ActionContract,
    ) -> ActionGateDecision:
        """Map durable replay posture for a known-executed key to a decision."""
        if self._replay_policy is None:
            return ActionGateDecision.DENY
        try:
            posture = self._replay_policy(
                str(getattr(node, "node_id", "")),
                str(contract.idempotency_key or ""),
            )
        except Exception:
            return ActionGateDecision.DENY
        if posture == "MAY_DISPATCH":
            return ActionGateDecision.ALLOW
        if posture == "RECONFIRMATION_REQUIRED":
            return ActionGateDecision.REQUIRE_CONFIRMATION
        return ActionGateDecision.DENY
