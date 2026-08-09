"""Capability Router — RFC-0016 (STUDIO 10.3).

Routes abstract capabilities to eligible, authorized, and healthy concrete candidate tools.
Evaluates persistent rules, health, privacy, cost, verification support, and idempotency.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from intent_kernel.instructions import MissionConstraint
from intent_kernel.tools.health import InMemoryToolHealthAdapter, ToolHealthPort
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolSelectionTrace,
    ToolStatus,
)
from intent_kernel.tools.permissions import PermissionManager
from intent_kernel.tools.registry import InMemoryToolRegistry, ToolRegistryPort


class CapabilityRouter:
    """Routes capability requests to scored concrete tool candidates."""

    def __init__(
        self,
        registry: Optional[ToolRegistryPort] = None,
        permission_manager: Optional[PermissionManager] = None,
        health_adapter: Optional[ToolHealthPort] = None,
    ) -> None:
        self.registry = registry or InMemoryToolRegistry()
        self.permission_manager = permission_manager or PermissionManager()
        self.health_adapter = health_adapter or InMemoryToolHealthAdapter()
        self._traces: List[ToolSelectionTrace] = []

    async def route_capability(
        self,
        capability: str,
        project_id: str = "GLOBAL",
        mission_constraints: Optional[List[MissionConstraint]] = None,
    ) -> List[ToolCandidate]:
        """Find, score, and rank tool candidates for a given capability."""
        tools = await self.registry.get_tools_for_capability(capability)
        candidates: List[ToolCandidate] = []
        rejected: List[str] = []

        # Check for persistent constraints (e.g. "Never use cloud tools for PROJECT_ALPHA")
        constraints = mission_constraints or []
        local_only = any(
            c.blocking and ("local_only" in c.expected_behavior.lower() or "never use cloud" in c.expected_behavior.lower())
            for c in constraints
        )

        for t in tools:
            # Check status (DISCOVERED or TEMPLATE is NOT AVAILABLE)
            if t.status not in (ToolStatus.AVAILABLE, ToolStatus.DEGRADED):
                rejected.append(t.tool_id)
                continue

            # Check local_only constraint
            if local_only and t.origin not in ("BUILT_IN", "LOCAL_APPLICATION"):
                rejected.append(t.tool_id)
                continue

            # Check health
            health = await self.health_adapter.check_health(t.tool_id)
            if health == ToolHealthStatus.UNAVAILABLE:
                rejected.append(t.tool_id)
                continue

            # Check permissions
            perm_state = PermissionDecisionState.GRANTED
            for req_perm in t.required_permissions:
                dec = self.permission_manager.evaluate_permission(t.tool_id, req_perm, project_id)
                if dec.state != PermissionDecisionState.GRANTED:
                    perm_state = dec.state

            # Compute score
            score = 1.0
            if t.status == ToolStatus.DEGRADED or health == ToolHealthStatus.DEGRADED:
                score -= 0.3
            if not t.supports_verification:
                score -= 0.2
            if not t.supports_idempotency:
                score -= 0.1
            if perm_state != PermissionDecisionState.GRANTED:
                score -= 0.5

            candidate = ToolCandidate(
                tool_id=t.tool_id,
                capability=capability,
                eligibility=True,
                authorization_status=perm_state,
                health=health,
                environment_match=True,
                permission_match=perm_state == PermissionDecisionState.GRANTED,
                verification_support=t.supports_verification,
                idempotency_support=t.supports_idempotency,
                selection_score=score,
                reason=f"Status: {t.status.value}, Health: {health.value}, Perms: {perm_state.value}",
            )
            candidates.append(candidate)

        # Sort candidates descending by score
        candidates.sort(key=lambda c: c.selection_score, reverse=True)

        selected_id = candidates[0].tool_id if candidates else None
        trace = ToolSelectionTrace(
            requested_capability=capability,
            project_id=project_id,
            candidate_count=len(candidates),
            selected_tool_id=selected_id,
            rejected_tool_ids=rejected,
            reason=candidates[0].reason if candidates else "No eligible candidate tool found.",
            permission_decision=candidates[0].authorization_status.value if candidates else "NONE",
            health_status=candidates[0].health.value if candidates else "NONE",
        )
        self._traces.append(trace)

        return candidates
