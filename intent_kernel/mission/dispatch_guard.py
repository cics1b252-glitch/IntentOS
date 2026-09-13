"""M32B-2 — Productive dispatch guard: durable ownership for handoffs.

ProductiveDispatchGuard is the narrow productive FACADE over
MissionActionAuthority. It is NOT a third idempotency authority and NOT a
dispatch mechanism: it answers, durably, whether one canonical local
execution attempt may be handed to an executor/provider, records the
handoff intent BEFORE the handoff, and records the outcome afterwards.

Canonical local attempt identity remains the stable E2 six-field
identity. Provider/effect identity stays separate and post-dispatch.

Ownership protocol per attempt (all steps durable-anchored, N -> N+1):

    acquire()           PENDING -> AUTHORIZED -> DISPATCH_INTENT_RECORDED
                        -> DISPATCHING (single call; each edge committed
                        before the next; INTENT is committed before the
                        handoff gate DISPATCHING, which is committed
                        before any external handoff)
    record_result()     DISPATCHING -> RESULT_RECORDED
    record_ambiguity()  DISPATCH_INTENT_RECORDED or DISPATCHING
                        -> AMBIGUOUS_EFFECT

Two callers racing the same attempt from the same durable revision cannot
both win: the store's durable revision anchor admits exactly one committer
per revision (same-process serialized by lock; sequential cross-process
stale writers detected). The loser reloads and follows replay posture.
No silent retry ever converts ambiguity into redispatch.

The guard NEVER creates missions or actions. An absent record/action fails
closed: productive binding of attempts to durable authority is owned by
later movements (M32B-4). Callers without a bound attempt must not use
this guard.

Cross-process limitation (honest boundary): the file store detects
sequential stale writers but does not implement simultaneous multiprocess
compare-and-swap. Truly simultaneous writers are outside the contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from intent_kernel.mission.action_authority import (
    ActionTransitionEvidence,
    MissionActionAuthority,
    ReplayDecision,
)
from intent_kernel.mission.mission_record import ActionState
from intent_kernel.mission.store import (
    MissionRecordNotFoundError,
    MissionRecordStorePort,
    MissionRecordValidationError,
)
from intent_kernel.time_utils import utc_iso


class DispatchGuardError(MissionRecordValidationError):
    """A productive dispatch-ownership request failed closed.

    Carries the replay ``decision`` (ReplayDecision value string) when the
    refusal derives from durable replay posture, so callers can map it to
    replay results or errors without redispatching.
    """

    def __init__(self, message: str, decision: str = "") -> None:
        super().__init__(message)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class DispatchAttemptSpec:
    """Caller-presented local attempt intent (pre-dispatch fields only)."""

    mission_id: str
    action_id: str
    request_semantics_digest: str
    executor_logical_id: str
    expected_governed_registration_id: str
    expected_resource_generation: int

    def __post_init__(self) -> None:
        for label in (
            "mission_id",
            "action_id",
            "request_semantics_digest",
            "executor_logical_id",
        ):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        # RRM expectations may be legitimately empty (runtime paths carry
        # no RRM preconditions; binding authority stays gate-side). They
        # must still be strings, and must still equal durable values.
        if not isinstance(self.expected_governed_registration_id, str):
            raise ValueError("expected_governed_registration_id must be a string")
        if not isinstance(self.expected_resource_generation, int) or isinstance(
            self.expected_resource_generation, bool
        ):
            raise ValueError("expected_resource_generation must be an int")


@dataclass(frozen=True, slots=True)
class DispatchOwnership:
    """Proof that this caller won durable dispatch ownership."""

    mission_id: str
    action_id: str
    local_execution_identity: str
    mission_revision: int
    acquired_at: str


def _canonical_request_digest(*components: Any) -> str:
    """Deterministic digest binding request semantics (no timestamps)."""
    return hashlib.sha256(
        json.dumps(
            list(components),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def spec_for_legacy_dispatch(
    *,
    mission_id: str,
    capability: str,
    payload: Dict[str, Any],
    idempotency_key: str,
    executor_logical_id: str,
    expected_governed_registration_id: str,
    expected_resource_generation: int,
) -> DispatchAttemptSpec:
    """Derive a spec for one legacy capability dispatch.

    The idempotency key scopes the action namespace
    (``capability`` vs ``capability#key``) so retries of the same key map
    to the same attempt while distinct keys map to distinct attempts. The
    request digest binds capability + payload + key: changed semantics is
    a different attempt. Deterministic: same inputs always derive the same
    spec, in any process.
    """
    action_id = capability if not idempotency_key else f"{capability}#{idempotency_key}"
    return DispatchAttemptSpec(
        mission_id=mission_id,
        action_id=action_id,
        request_semantics_digest=_canonical_request_digest(
            capability, payload, idempotency_key
        ),
        executor_logical_id=executor_logical_id,
        expected_governed_registration_id=expected_governed_registration_id,
        expected_resource_generation=expected_resource_generation,
    )


def spec_for_runtime_node(mission_id: str, node: Any) -> DispatchAttemptSpec:
    """Derive a spec for one MissionRuntime node.

    Binds node identity + capability + contract inputs + idempotency key.
    Executor identity is the node's declared agent identity (exact-object
    revalidation stays with the gate/binding path). Duck-typed: no runtime
    imports, so this module never creates an import cycle.
    """
    contract = getattr(node, "action_contract", None)
    capability = str(getattr(node, "capability", ""))
    inputs = getattr(contract, "inputs_reference", {}) or {}
    key = getattr(contract, "idempotency_key", "") or ""
    return DispatchAttemptSpec(
        mission_id=mission_id,
        action_id=str(getattr(node, "node_id", "")),
        request_semantics_digest=_canonical_request_digest(
            capability, inputs, key
        ),
        executor_logical_id=str(getattr(node, "agent_id", "")),
        expected_governed_registration_id="",
        expected_resource_generation=0,
    )


class ProductiveDispatchGuard:
    """Durable dispatch-ownership authority for productive handoffs."""

    def __init__(
        self,
        authority: MissionActionAuthority,
        store: MissionRecordStorePort,
    ) -> None:
        self._authority = authority
        self._store = store

    # -- reads -------------------------------------------------------------

    def decide(
        self,
        spec: DispatchAttemptSpec,
        *,
        confirmation_required: bool = False,
    ) -> ReplayDecision:
        """Read-only replay posture for one presented attempt."""
        data = self._store.load(spec.mission_id)
        if data is None:
            raise DispatchGuardError(
                f"No durable mission for attempt: {spec.mission_id}",
                decision="",
            )
        self._verify_spec_against_durable(spec, data)
        # Field-by-field verification above is the binding check; the
        # authority additionally enforces table + revision + identity.
        return self._authority.decide_replay(
            spec.mission_id,
            spec.action_id,
            confirmation_required=confirmation_required,
        )

    # -- ownership ----------------------------------------------------------

    def acquire_for_legacy(
        self,
        *,
        mission_id: str,
        capability: str,
        payload: Dict[str, Any],
        idempotency_key: str,
        executor_logical_id: str,
        expected_governed_registration_id: str,
        expected_resource_generation: int,
        requested_by: str = "productive-dispatch",
        confirmation_required: bool = False,
    ) -> DispatchOwnership:
        """Build the legacy attempt spec (no imports needed) and acquire."""
        return self.acquire(
            spec_for_legacy_dispatch(
                mission_id=mission_id,
                capability=capability,
                payload=payload,
                idempotency_key=idempotency_key,
                executor_logical_id=executor_logical_id,
                expected_governed_registration_id=(
                    expected_governed_registration_id
                ),
                expected_resource_generation=expected_resource_generation,
            ),
            requested_by=requested_by,
            confirmation_required=confirmation_required,
        )

    def acquire_for_node(
        self,
        mission_id: str,
        node: Any,
        *,
        requested_by: str = "productive-dispatch",
        confirmation_required: bool = False,
    ) -> DispatchOwnership:
        """Build the runtime-node attempt spec (no imports needed)."""
        return self.acquire(
            spec_for_runtime_node(mission_id, node),
            requested_by=requested_by,
            confirmation_required=confirmation_required,
        )

    def acquire(
        self,
        spec: DispatchAttemptSpec,
        *,
        requested_by: str = "productive-dispatch",
        confirmation_required: bool = False,
    ) -> DispatchOwnership:
        """Win durable dispatch ownership (PENDING -> ... -> DISPATCHING).

        Fails closed (DispatchGuardError, ZERO DISPATCH) when: no durable
        record/action; presented spec mismatches durable identity;
        replay posture is not MAY_DISPATCH; a concurrent winner advanced
        first. On success the DISPATCH_INTENT_RECORDED commit AND the
        DISPATCHING handoff-gate commit are both durable BEFORE the caller
        may hand off.
        """
        data = self._store.load(spec.mission_id)
        if data is None:
            raise DispatchGuardError(
                f"No durable mission for attempt: {spec.mission_id}",
                decision="",
            )
        self._verify_spec_against_durable(spec, data)
        try:
            decision = self._authority.decide_replay(
                spec.mission_id,
                spec.action_id,
                confirmation_required=confirmation_required,
                expected_execution_identity=(
                    self._authority.execution_identity_for(
                        spec.mission_id, spec.action_id
                    )
                ),
            )
        except (MissionRecordNotFoundError, MissionRecordValidationError) as exc:
            raise DispatchGuardError(str(exc), decision="") from exc
        if decision is not ReplayDecision.MAY_DISPATCH:
            raise DispatchGuardError(
                f"Replay posture forbids dispatch: {decision.value}",
                decision=decision.value,
            )
        evidence = ActionTransitionEvidence(
            requested_by=requested_by, reason="dispatch-ownership-acquire"
        )
        current = self._current_state(data, spec.action_id)
        try:
            revision = data["revision"]
            if current is ActionState.PENDING:
                first = self._authority.transition_action(
                    spec.mission_id,
                    spec.action_id,
                    revision,
                    ActionState.PENDING,
                    ActionState.AUTHORIZED,
                    evidence,
                )
                revision = first.mission_revision
                current = ActionState.AUTHORIZED
            if current is ActionState.AUTHORIZED:
                second = self._authority.transition_action(
                    spec.mission_id,
                    spec.action_id,
                    revision,
                    ActionState.AUTHORIZED,
                    ActionState.DISPATCH_INTENT_RECORDED,
                    evidence,
                )
                revision = second.mission_revision
                current = ActionState.DISPATCH_INTENT_RECORDED
            if current is ActionState.DISPATCH_INTENT_RECORDED:
                third = self._authority.transition_action(
                    spec.mission_id,
                    spec.action_id,
                    revision,
                    ActionState.DISPATCH_INTENT_RECORDED,
                    ActionState.DISPATCHING,
                    evidence,
                )
                revision = third.mission_revision
            else:  # pragma: no cover - decide() already excluded the rest
                raise DispatchGuardError(
                    f"State {current.value} cannot acquire dispatch ownership",
                    decision=decision.value,
                )
        except (MissionRecordNotFoundError, MissionRecordValidationError) as exc:
            # Includes the lost race: a concurrent winner advanced first.
            raise DispatchGuardError(str(exc), decision="") from exc
        return DispatchOwnership(
            mission_id=spec.mission_id,
            action_id=spec.action_id,
            local_execution_identity=(
                self._authority.execution_identity_for(
                    spec.mission_id, spec.action_id
                )
            ),
            mission_revision=revision,
            acquired_at=utc_iso(),
        )

    def record_result(
        self,
        ownership: DispatchOwnership,
        *,
        result_summary: Dict[str, Any],
        provider_effect_id: str = "",
        requested_by: str = "productive-dispatch",
    ) -> int:
        """Persist a KNOWN handoff result (-> RESULT_RECORDED).

        Requires the durable state to still be exactly DISPATCHING at the
        ownership revision: a handoff result proves the handoff started.
        Anything else (advanced, ambiguous, completed) fails closed
        without overwriting.
        """
        data = self._store.load(ownership.mission_id)
        if data is None:
            raise DispatchGuardError("Durable mission vanished", decision="")
        if data.get("revision") != ownership.mission_revision:
            raise DispatchGuardError(
                "Ownership is stale: durable revision advanced", decision=""
            )
        current = self._current_state(data, ownership.action_id)
        if current is not ActionState.DISPATCHING:
            raise DispatchGuardError(
                f"Cannot record result from state {current.value}",
                decision="",
            )
        try:
            result = self._authority.transition_action(
                ownership.mission_id,
                ownership.action_id,
                ownership.mission_revision,
                ActionState.DISPATCHING,
                ActionState.RESULT_RECORDED,
                ActionTransitionEvidence(
                    requested_by=requested_by,
                    reason="handoff-result-recorded",
                    result=dict(result_summary),
                    provider_effect_id=provider_effect_id,
                ),
            )
        except (MissionRecordNotFoundError, MissionRecordValidationError) as exc:
            raise DispatchGuardError(str(exc), decision="") from exc
        return result.mission_revision

    def record_ambiguity(
        self,
        ownership: DispatchOwnership,
        *,
        reason: str = "handoff-uncertain",
        requested_by: str = "productive-dispatch",
    ) -> int:
        """Persist uncertain handoff (-> AMBIGUOUS_EFFECT, fail closed).

        Accepted from DISPATCHING (handoff started, outcome unknown) or
        DISPATCH_INTENT_RECORDED (ownership won but handoff never began,
        e.g. crash between the two gate commits). Never returns to
        PENDING, never redispatches.
        """
        data = self._store.load(ownership.mission_id)
        if data is None:
            raise DispatchGuardError("Durable mission vanished", decision="")
        if data.get("revision") != ownership.mission_revision:
            raise DispatchGuardError(
                "Ownership is stale: durable revision advanced", decision=""
            )
        current = self._current_state(data, ownership.action_id)
        if current not in (
            ActionState.DISPATCH_INTENT_RECORDED,
            ActionState.DISPATCHING,
        ):
            raise DispatchGuardError(
                f"Cannot record ambiguity from state {current.value}",
                decision="",
            )
        try:
            result = self._authority.transition_action(
                ownership.mission_id,
                ownership.action_id,
                ownership.mission_revision,
                current,
                ActionState.AMBIGUOUS_EFFECT,
                ActionTransitionEvidence(
                    requested_by=requested_by, reason=reason
                ),
            )
        except (MissionRecordNotFoundError, MissionRecordValidationError) as exc:
            raise DispatchGuardError(str(exc), decision="") from exc
        return result.mission_revision

    # -- internals -----------------------------------------------------------

    def _verify_spec_against_durable(
        self, spec: DispatchAttemptSpec, data: Dict[str, Any]
    ) -> None:
        """Presented intent must equal durable identity (no substitution)."""
        actions = data.get("action_states", {})
        if spec.action_id not in actions:
            raise DispatchGuardError(
                f"No durable action for attempt: {spec.action_id}",
                decision="",
            )
        plan_digest = ""
        for entry in data.get("plan", []):
            if isinstance(entry, dict) and entry.get("action_id") == spec.action_id:
                plan_digest = entry.get("request_semantics_digest", "")
                break
        if plan_digest != spec.request_semantics_digest:
            raise DispatchGuardError(
                "Presented request digest does not match durable plan",
                decision="",
            )
        action = actions[spec.action_id]
        for label, presented in (
            ("expected_governed_registration_id",
             spec.expected_governed_registration_id),
            ("expected_resource_generation",
             spec.expected_resource_generation),
            ("expected_executor_logical_id", spec.executor_logical_id),
        ):
            if action.get(label) != presented:
                raise DispatchGuardError(
                    f"Presented {label} does not match durable authority",
                    decision="",
                )

    @staticmethod
    def _current_state(data: Dict[str, Any], action_id: str) -> ActionState:
        from intent_kernel.mission.mission_record import ActionState as AS

        raw = data.get("action_states", {}).get(action_id, {}).get("state")
        try:
            return AS(raw)
        except ValueError as exc:
            raise DispatchGuardError(
                f"Unknown durable action state: {raw!r}"
            ) from exc
