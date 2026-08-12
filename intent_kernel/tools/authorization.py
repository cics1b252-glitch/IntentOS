"""Tool Authorization Gate — RFC-0016 (STUDIO 10.3).

Evaluates candidate tools prior to execution against Constitution, ExecutionPolicy,
MissionConstraints, permission requirements, tool health, and side-effect profiles.
Formally distinguishes AUTHORIZATION from CONFIRMATION.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from intent_kernel.instructions import MissionConstraint
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)


class ToolAuthorizationGate:
    """Pre-execution authorization gate for concrete tools."""

    def __init__(self, constitution: Optional[Any] = None) -> None:
        self._constitution = constitution

    async def evaluate_tool(
        self,
        candidate: ToolCandidate,
        tool: ToolResource,
        mission_constraints: Optional[List[MissionConstraint]] = None,
        execution_policy: Optional[Dict[str, Any]] = None,
        project_id: str = "GLOBAL",
    ) -> ToolAuthorizationDecisionState:
        """Evaluate if a selected tool candidate is authorized to execute."""

        # 1. Check Tool Status & Health
        if tool.status in (ToolStatus.UNAUTHORIZED, ToolStatus.REVOKED, ToolStatus.DISABLED, ToolStatus.UNAVAILABLE):
            return ToolAuthorizationDecisionState.DENY

        if candidate.health == ToolHealthStatus.UNAVAILABLE:
            return ToolAuthorizationDecisionState.WAIT_TOOL

        # 2. Check Permission Decision State
        if candidate.authorization_status in (PermissionDecisionState.NOT_CONFIGURED, PermissionDecisionState.REQUIRES_USER_AUTHORIZATION):
            return ToolAuthorizationDecisionState.REQUEST_PERMISSION

        if candidate.authorization_status in (PermissionDecisionState.DENIED, PermissionDecisionState.REVOKED, PermissionDecisionState.BLOCKED_BY_POLICY):
            return ToolAuthorizationDecisionState.DENY

        # 3. Constitution Check
        if self._constitution and hasattr(self._constitution, "evaluate_action"):
            res = self._constitution.evaluate_action({"capability": candidate.capability, "tool_id": tool.tool_id})
            if getattr(res, "verdict", "ALLOW") == "DENY":
                return ToolAuthorizationDecisionState.DENY
        elif self._constitution and hasattr(self._constitution, "evaluate"):
            res = await self._constitution.evaluate(
                "tool.authorize",
                {"capability": candidate.capability, "tool_id": tool.tool_id},
                {"project_id": project_id},
            )
            if not getattr(res, "allowed", True):
                return ToolAuthorizationDecisionState.DENY

        # 4. Mission Constraints Check
        constraints = mission_constraints or []
        for mc in constraints:
            if mc.blocking and mc.constraint_type == "DENY_TOOL":
                if mc.expected_behavior == tool.tool_id:
                    return ToolAuthorizationDecisionState.DENY

        # 5. Check Side Effect Profile vs User Confirmation
        # Note: Tool Authorization passes if permissions exist. Action Gate will handle specific action confirmation!
        if candidate.authorization_status == PermissionDecisionState.GRANTED:
            return ToolAuthorizationDecisionState.ALLOW

        return ToolAuthorizationDecisionState.DENY
