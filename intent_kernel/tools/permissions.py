"""Tool Permissions Manager — RFC-0016 (STUDIO 10.3).

Manages tool permission decisions, scopes (ONCE, MISSION, SESSION, PROJECT, USER),
project isolation, expiration tracking, and revocations.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from intent_kernel.time_utils import utc_iso
from intent_kernel.tools.models import (
    PermissionDecision,
    PermissionDecisionState,
    PermissionScope,
)


class PermissionManager:
    """Manages permissions for tools across scopes and projects."""

    def __init__(self) -> None:
        # Key: (tool_id, permission, project_id)
        self._grants: Dict[Tuple[str, str, str], PermissionDecision] = {}

    def grant_permission(
        self,
        tool_id: str,
        permission: str,
        scope: PermissionScope = PermissionScope.PROJECT,
        project_id: str = "GLOBAL",
        reason: str = "User granted permission",
    ) -> PermissionDecision:
        """Grant a permission to a tool for a specific scope and project."""
        decision = PermissionDecision(
            tool_id=tool_id,
            permission=permission,
            state=PermissionDecisionState.GRANTED,
            scope=scope,
            project_id=project_id,
            reason=reason,
            granted_at=utc_iso(),
        )
        self._grants[(tool_id, permission, project_id)] = decision
        return decision

    def revoke_permission(
        self,
        tool_id: str,
        permission: str,
        project_id: str = "GLOBAL",
        reason: str = "Permission revoked by user or system",
    ) -> PermissionDecision:
        """Revoke a previously granted permission."""
        decision = PermissionDecision(
            tool_id=tool_id,
            permission=permission,
            state=PermissionDecisionState.REVOKED,
            scope=PermissionScope.PROJECT,
            project_id=project_id,
            reason=reason,
        )
        self._grants[(tool_id, permission, project_id)] = decision
        return decision

    def evaluate_permission(
        self,
        tool_id: str,
        permission: str,
        project_id: str = "GLOBAL",
    ) -> PermissionDecision:
        """Evaluate if a tool holds an active permission for a given project."""
        # Check exact project match
        key = (tool_id, permission, project_id)
        if key in self._grants:
            return self._grants[key]

        # Fallback to GLOBAL project grant
        global_key = (tool_id, permission, "GLOBAL")
        if global_key in self._grants:
            return self._grants[global_key]

        # Default NOT_CONFIGURED
        return PermissionDecision(
            tool_id=tool_id,
            permission=permission,
            state=PermissionDecisionState.NOT_CONFIGURED,
            scope=PermissionScope.PROJECT,
            project_id=project_id,
            reason=f"Permission {permission} not configured for tool {tool_id}",
        )
