"""Canonical Confirmation Service — Movement 14.

Owns the typed user-confirmation protocol for controlled Mission resumption.

The service never executes anything: it validates a typed confirmation against
the canonical :class:`MissionEngine` record and the :class:`MissionRuntime`
pending requirement, then hands a validated confirmation back to MissionRuntime
for a single, revalidated resumed execution. Rejection moves the Mission to the
canonical non-executing CANCELLED state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from intent_kernel.contracts import MissionId, MissionStatus
from intent_kernel.runtime.models import (
    ConfirmationState,
    ExecutionConfirmationRequest,
)
from intent_kernel.time_utils import utc_iso
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)


@dataclass(frozen=True, slots=True)
class ConfirmationSubmission:
    """Typed user confirmation for one pending Mission/action requirement."""

    mission_id: str
    confirmation_id: str
    approved: bool
    session_id: str = ""
    project_id: str = "GLOBAL"
    confirmation_token: str = ""


@dataclass(frozen=True, slots=True)
class ConfirmationOutcome:
    """Deterministic outcome of a typed confirmation submission."""

    state: ConfirmationState
    accepted: bool
    reason: str
    mission_id: str | None = None
    confirmation_id: str | None = None
    runtime_id: str | None = None
    mission_status: str | None = None


def rebuild_candidate(data: dict[str, Any]) -> ToolCandidate:
    """Reconstruct a ToolCandidate from its serialized binding snapshot."""
    return ToolCandidate(
        tool_id=str(data.get("tool_id", "")),
        capability=str(data.get("capability", "")),
        authorization_status=PermissionDecisionState(
            str(data.get("authorization_status", "GRANTED"))
        ),
        health=ToolHealthStatus(str(data.get("health", "HEALTHY"))),
    )


def rebuild_tool(data: dict[str, Any]) -> ToolResource:
    """Reconstruct a ToolResource from its serialized binding snapshot."""
    return ToolResource(
        tool_id=str(data.get("tool_id", "")),
        capabilities=list(data.get("capabilities") or []),
        status=ToolStatus(str(data.get("status", "AVAILABLE"))),
        required_permissions=list(data.get("required_permissions") or []),
    )


class CanonicalConfirmationService:
    """Validation authority for typed Mission confirmations (Movement 14)."""

    def __init__(
        self,
        mission_engine: Any,
        mission_runtime: Any,
        tool_authorization_gate: Any = None,
        confirmation_ttl_seconds: float | None = None,
    ) -> None:
        self._engine = mission_engine
        self._runtime = mission_runtime
        self._tool_authorization_gate = tool_authorization_gate
        self._confirmation_ttl_seconds = confirmation_ttl_seconds

    # ------------------------------------------------------------------ bind

    def bind_pending(
        self,
        *,
        confirmation_id: str,
        mission_id: str,
        runtime_id: str,
        action_id: str,
        session_id: str = "",
        project_id: str = "GLOBAL",
        confirmation_token: str = "",
        authorization: dict[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> ExecutionConfirmationRequest:
        """Bind scope, token, expiry and the exact authorization snapshot to a requirement.

        ``authorization`` must be the serialized ``ToolCandidate``/``ToolResource``
        used at planning time so the resumed Mission revalidates the *same*
        binding identity (Movement 13 guarantee) instead of inheriting a replacement.
        """
        conf = self._runtime.get_confirmation(confirmation_id)
        if conf is None or conf.mission_id != mission_id or conf.action_id != action_id:
            raise ValueError(
                "No matching pending confirmation requirement for this Mission/action"
            )
        if conf.state is not ConfirmationState.WAITING_CONFIRMATION:
            raise ValueError(
                f"Confirmation requirement is not waiting: {conf.state.value}"
            )
        conf.runtime_id = runtime_id
        conf.session_id = session_id
        conf.project_id = project_id
        conf.confirmation_token = confirmation_token
        provenance = dict(conf.provenance)
        provenance["authorization"] = dict(authorization or {})
        provenance["bound_at"] = utc_iso()
        conf.provenance = provenance
        ttl = ttl_seconds if ttl_seconds is not None else self._confirmation_ttl_seconds
        if ttl is not None:
            conf.expires_at = utc_iso(
                datetime.now(timezone.utc) + timedelta(seconds=float(ttl))
            )
        return conf

    def get_confirmation(self, confirmation_id: str) -> ExecutionConfirmationRequest | None:
        """Resolve a requirement by its typed confirmation ID."""
        return self._runtime.get_confirmation(confirmation_id)

    def pending_for_mission(self, mission_id: str) -> ExecutionConfirmationRequest | None:
        """Resolve the active WAITING_CONFIRMATION requirement for a Mission."""
        return self._runtime.get_pending_confirmation(mission_id)

    # -------------------------------------------------------------- submission

    async def submit(self, submission: ConfirmationSubmission) -> ConfirmationOutcome:
        """Validate and apply a typed confirmation. Never executes anything."""
        conf = self._runtime.get_confirmation(submission.confirmation_id)
        if conf is None:
            return ConfirmationOutcome(
                ConfirmationState.STALE, False, "confirmation_not_found"
            )
        if conf.mission_id != submission.mission_id:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "mission_mismatch",
                confirmation_id=conf.confirmation_id,
            )

        mission = await self._engine.get(MissionId(submission.mission_id))
        if mission is None:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "mission_not_found",
                mission_id=submission.mission_id,
                confirmation_id=conf.confirmation_id,
            )

        if mission.status is MissionStatus.COMPLETED:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "mission_already_completed",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )
        if mission.status is MissionStatus.CANCELLED:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "mission_already_cancelled",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )
        if mission.status is not MissionStatus.WAITING_FOR_DECISION:
            return ConfirmationOutcome(
                conf.state,
                False,
                f"mission_not_pending:{mission.status.value}",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        if conf.state is not ConfirmationState.WAITING_CONFIRMATION:
            return ConfirmationOutcome(
                conf.state,
                False,
                f"confirmation_state:{conf.state.value}",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        # Scope binding (fail closed on mismatch or omission of a bound scope).
        if conf.session_id and submission.session_id != conf.session_id:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "scope_session_mismatch",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )
        if conf.project_id and submission.project_id != conf.project_id:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "scope_project_mismatch",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        # Token binding.
        if conf.confirmation_token and submission.confirmation_token != conf.confirmation_token:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "token_mismatch",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        # Expiry (same-format ISO UTC strings compare lexicographically).
        if conf.expires_at and utc_iso() > conf.expires_at:
            conf.state = ConfirmationState.EXPIRED
            return ConfirmationOutcome(
                ConfirmationState.EXPIRED,
                False,
                "confirmation_expired",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        # Exact binding identity revalidation (action contract + tool binding).
        if not self._binding_identity_valid(conf):
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "binding_invalid",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )

        if not submission.approved:
            conf.state = ConfirmationState.REJECTED
            await self._engine.reject(MissionId(submission.mission_id))
            self._runtime.cancel_instance(submission.mission_id)
            return ConfirmationOutcome(
                ConfirmationState.REJECTED,
                True,
                "rejected",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=MissionStatus.CANCELLED.value,
            )

        updated = self._runtime.submit_confirmation(conf.confirmation_id, True)
        if updated is None:
            return ConfirmationOutcome(
                ConfirmationState.STALE,
                False,
                "runtime_submit_failed",
                mission_id=str(mission.id),
                confirmation_id=conf.confirmation_id,
                mission_status=mission.status.value,
            )
        conf.state = ConfirmationState.CONFIRMED
        return ConfirmationOutcome(
            ConfirmationState.CONFIRMED,
            True,
            "confirmed",
            mission_id=str(mission.id),
            confirmation_id=conf.confirmation_id,
            runtime_id=conf.runtime_id,
            mission_status=MissionStatus.RUNNING.value,
        )

    def consume(self, confirmation_id: str) -> None:
        """Mark a CONFIRMED requirement as applied after its single resume."""
        conf = self._runtime.get_confirmation(confirmation_id)
        if conf is not None and conf.state is ConfirmationState.CONFIRMED:
            conf.state = ConfirmationState.CONSUMED

    def invalidate(self, confirmation_id: str, reason: str = "") -> None:
        """Mark a requirement STALE (no execution occurred on resume)."""
        conf = self._runtime.get_confirmation(confirmation_id)
        if conf is None:
            return
        if conf.state not in (
            ConfirmationState.WAITING_CONFIRMATION,
            ConfirmationState.CONFIRMED,
        ):
            return
        conf.state = ConfirmationState.STALE
        if reason:
            provenance = dict(conf.provenance)
            provenance["invalidation_reason"] = reason
            conf.provenance = provenance

    # ------------------------------------------------------------ revalidation

    async def recheck_authorization(self, conf: ExecutionConfirmationRequest):
        """Re-run ToolAuthorizationGate for the exact bound tool on resume.

        Returns ``(decision, snapshot)``; ``snapshot`` is empty when no
        authorization was bound or no gate is configured.
        """
        auth = (conf.provenance or {}).get("authorization") or {}
        if not auth or self._tool_authorization_gate is None:
            return None, {}
        candidate = rebuild_candidate(auth.get("candidate") or {})
        tool = rebuild_tool(auth.get("tool") or {})
        project_id = str(auth.get("project_id") or "GLOBAL")
        decision = await self._tool_authorization_gate.evaluate_tool(
            candidate,
            tool,
            project_id=project_id,
        )
        return decision, {
            "candidate": candidate,
            "tool": tool,
            "project_id": project_id,
            "decision": decision,
        }

    # ------------------------------------------------------------- internals

    def _binding_identity_valid(self, conf: ExecutionConfirmationRequest) -> bool:
        """Verify the bound runtime node still matches the exact pending binding."""
        instance = self._runtime.get_instance(conf.runtime_id)
        if instance is None:
            return False
        matched = None
        for node in instance.nodes.values():
            contract = node.action_contract
            if contract is not None and contract.action_id == conf.action_id:
                matched = (node, contract)
                break
        if matched is None:
            return False
        _node, contract = matched
        auth = (conf.provenance or {}).get("authorization") or {}
        tool_snapshot = auth.get("tool") or {}
        bound_tool_id = tool_snapshot.get("tool_id")
        contract_tool_id = (contract.provenance or {}).get("tool_id")
        if bound_tool_id and contract_tool_id and bound_tool_id != contract_tool_id:
            return False
        return True
