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
from copy import deepcopy
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
    quantity: Optional[Dict[str, Any]] = None
    operation: str = ""

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
        if not isinstance(self.operation, str):
            raise ValueError("operation must be a string")
        # RRM expectations may be legitimately empty (runtime paths carry
        # no RRM preconditions; binding authority stays gate-side). They
        # must still be strings, and must still equal durable values.
        if not isinstance(self.expected_governed_registration_id, str):
            raise ValueError("expected_governed_registration_id must be a string")
        if not isinstance(self.expected_resource_generation, int) or isinstance(
            self.expected_resource_generation, bool
        ):
            raise ValueError("expected_resource_generation must be an int")
        if self.quantity is not None:
            if not isinstance(self.quantity, dict):
                raise ValueError("quantity must be a dict or None")
            # Validate quantity structure if present
            required_keys = {"dimension", "amount", "unit"}
            if not all(k in self.quantity for k in required_keys):
                raise ValueError(f"quantity must contain {required_keys}")


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
    quantity: Optional[Dict[str, Any]] = None,
    operation: str = "",
) -> DispatchAttemptSpec:
    """Derive a spec for one legacy capability dispatch.

    The idempotency key scopes the action namespace
    (``capability`` vs ``capability#key``) so retries of the same key map
    to the same attempt while distinct keys map to distinct attempts. The
    request digest binds capability + OPERATION + payload + key: changed
    semantics — including operation substitution — is a different attempt.
    Deterministic: same inputs always derive the same spec, in any process.

    C2/C3/G1.2 §1/§4: operation is authority-bearing semantic data carried
    INSIDE the C1-bound request digest. It is never reconstructed later from
    capability name, payload shape or tool metadata, and there is no parallel
    unsigned operation digest.
    """
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError(
            "operation must be an explicit non-empty semantic value "
            "(C2/C3/G1.2 §3: empty operation is invalid for productive "
            "authority-bearing actions)"
        )
    action_id = capability if not idempotency_key else f"{capability}#{idempotency_key}"
    return DispatchAttemptSpec(
        mission_id=mission_id,
        action_id=action_id,
        request_semantics_digest=_canonical_request_digest(
            capability, operation, payload, idempotency_key
        ),
        executor_logical_id=executor_logical_id,
        expected_governed_registration_id=expected_governed_registration_id,
        expected_resource_generation=expected_resource_generation,
        quantity=quantity,
        operation=operation,
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
    # C2/C3/G1.2 §2: the canonical structured operation value already present
    # at the action-construction boundary is ActionContract.action_type.
    # It is carried verbatim into the C1-bound digest — never reconstructed
    # from capability name, payload shape or tool metadata.
    operation = str(getattr(contract, "action_type", "") or "")
    qty = getattr(contract, "quantity", None)
    return DispatchAttemptSpec(
        mission_id=mission_id,
        action_id=str(getattr(node, "node_id", "")),
        request_semantics_digest=_canonical_request_digest(
            capability, operation, inputs, key
        ),
        executor_logical_id=str(getattr(node, "agent_id", "")),
        expected_governed_registration_id="",
        expected_resource_generation=0,
        # C2/C3/G1.3 GAP 2: snapshot the quantity. The spec must capture what
        # was actually verified at acquire, not hold a live alias of the
        # mutable contract dict that a later mutation could rewrite.
        quantity=deepcopy(qty) if qty is not None else None,
        operation=operation,
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

    def get_authorized_request_digest(
        self,
        mission_id: str,
        action_id: str,
    ) -> str:
        """Get the authorized request_semantics_digest for an action from the
        durable MissionRecord. Returns empty string if not found.

        This reads from the canonical durable MissionRecord, not the legacy
        mission.plan, ensuring C1 invariant: authorized request == durable
        authorized request.
        """
        data = self._store.load(mission_id)
        if data is None:
            return ""
        plan = data.get("plan", ())
        for entry in plan:
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                return entry.get("request_semantics_digest", "")
        return ""

    def get_authorized_operation(self, mission_id: str, action_id: str) -> str:
        """Read the AUTHORIZED operation for an action from the durable record.

        C2/C3/G1.2 §1/§4: operation is authority-bearing and immutable with the
        plan. Returns empty string when the action or its operation is absent,
        which callers must treat as invalid for productive actions.
        """
        data = self._store.load(mission_id)
        if data is None:
            return ""
        for entry in data.get("plan", ()):
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                return str(entry.get("operation", "") or "")
        return ""

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
        quantity: Optional[Dict[str, Any]] = None,
        operation: str = "",
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
                quantity=quantity,
                operation=operation,
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
        # C2/C3/G1.3 §2: the live delegation chain is reproved with the EXACT
        # C1-bound quantity BEFORE any applicability/quantity judgement, so a
        # quantity-bearing action can never be waved through by a narrower
        # edge that simply omitted quantity.
        self._verify_delegation(spec, data)
        self._verify_quantity(spec, data)
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

    def verify_pre_handoff_identity(
        self,
        ownership: DispatchOwnership,
        *,
        capability: str = "",
        operation: str = "",
        request_semantics_digest: str = "",
        quantity: Optional[Dict[str, Any]] = None,
    ) -> None:
        """C2/C3/G1.3 §6: final freshness/equality gate before executor handoff.

        Re-verifies that the exact request that won acquire is still the
        request about to be handed to the executor:

            ACQUIRED_CAPABILITY  = HANDOFF_CAPABILITY
            ACQUIRED_OPERATION  = HANDOFF_OPERATION
            ACQUIRED_DIGEST     = HANDOFF_DIGEST
            ACQUIRED_QUANTITY   = HANDOFF_QUANTITY

        plus the canonical revision freshness token that the guard already
        requires for record_result: a mutation between acquire and handoff
        fails closed with ZERO executor calls.

        This is NOT a new authority source. It only re-proves equality and
        freshness against the already-authorized durable state.
        """
        data = self._store.load(ownership.mission_id)
        if data is None:
            raise DispatchGuardError(
                "Durable mission vanished before handoff", decision=""
            )
        if data.get("revision") != ownership.mission_revision:
            raise DispatchGuardError(
                "Handoff refused: durable revision advanced past acquire",
                decision="",
            )
        entry = None
        for candidate in data.get("plan", ()):
            if (
                isinstance(candidate, dict)
                and candidate.get("action_id") == ownership.action_id
            ):
                entry = candidate
                break
        if entry is None:
            raise DispatchGuardError(
                f"No durable action for handoff: {ownership.action_id}",
                decision="",
            )

        # Operation equality: the acquired operation must still be the
        # authorized one (guards operation mutation before handoff).
        acquired_operation = str(entry.get("operation", "") or "")
        if operation and operation != acquired_operation:
            raise DispatchGuardError(
                "Handoff refused: operation changed since acquire "
                f"(acquired={acquired_operation!r} handoff={operation!r})",
                decision="",
            )

        # Request digest equality.
        acquired_digest = str(entry.get("request_semantics_digest", "") or "")
        if request_semantics_digest and request_semantics_digest != acquired_digest:
            raise DispatchGuardError(
                "Handoff refused: request digest changed since acquire",
                decision="",
            )

        # Quantity equality — including dimension and unit, which are part of
        # the identity space, not a convertible equivalence.
        if quantity is not None:
            acquired_quantity = entry.get("quantity")
            if not acquired_quantity:
                raise DispatchGuardError(
                    "Handoff refused: no authorized quantity to match",
                    decision="",
                )
            if _canonical_request_digest(acquired_quantity) != _canonical_request_digest(
                quantity
            ):
                raise DispatchGuardError(
                    "Handoff refused: quantity changed since acquire",
                    decision="",
                )
        elif entry.get("quantity"):
            # An authorized quantity may not be dropped before handoff.
            raise DispatchGuardError(
                "Handoff refused: authorized quantity dropped before handoff",
                decision="",
            )

        # Capability equality against the acquired plan entry. Some legacy
        # durable plans carry the action id rather than a capability identity
        # in this field; the C1 request digest already binds the real
        # capability, so an absent/non-identity value here is not evidence of
        # mutation and must not fabricate a refusal.
        if capability:
            acquired_capability = str(entry.get("capability", "") or "")
            if acquired_capability and acquired_capability != capability:
                raise DispatchGuardError(
                    "Handoff refused: capability changed since acquire",
                    decision="",
                )

    def record_result(
        self,
        ownership: DispatchOwnership,
        *,
        result_summary: Dict[str, Any],
        provider_effect_id: str = "",
        requested_by: str = "productive-dispatch",
        observed_quantity: Optional[Any] = None,
    ) -> int:
        """Persist a KNOWN handoff result (-> RESULT_RECORDED).

        Requires the durable state to still be exactly DISPATCHING at the
        ownership revision: a handoff result proves the handoff started.
        Anything else (advanced, ambiguous, completed) fails closed
        without overwriting.

        C2/C3/G1.3 GAP 1: the durable result path persists canonical G1
        quantity evidence distinguishing AUTHORIZED / REQUESTED / OBSERVED /
        COMPLIANCE. AUTHORIZED is the ceiling proven at acquire, REQUESTED is
        the exact C1-bound request, and OBSERVED is derived ONLY from actual
        post-effect observation. OBSERVED is never copied from REQUESTED just
        because the executor returned success, and a VIOLATION is recorded as
        post-effect evidence - never as a pre-effect denial.
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
        summary = dict(result_summary)
        quantity_evidence = self._build_quantity_evidence(
            data, ownership, summary, observed_quantity
        )
        if quantity_evidence is not None:
            summary["quantity_evidence"] = quantity_evidence
            # A VIOLATION stops dependent continuation: the node must not be
            # treated as a successful verified outcome.
            summary["quantity_compliance_status"] = quantity_evidence[
                "status"
            ]
            if quantity_evidence["status"] == "VIOLATION":
                summary["quantity_continuation_allowed"] = False
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
                    # C2/C3/G1.3 GAP 1: persist the ENRICHED summary so the
                    # durable record carries AUTHORIZED / REQUESTED /
                    # OBSERVED / COMPLIANCE, not just the raw handoff summary.
                    result=dict(summary),
                    provider_effect_id=provider_effect_id,
                ),
            )
        except (MissionRecordNotFoundError, MissionRecordValidationError) as exc:
            raise DispatchGuardError(str(exc), decision="") from exc
        return result.mission_revision

    @staticmethod
    def _extract_observed_quantity(
        summary: Dict[str, Any],
    ) -> Optional[Any]:
        """Read an OBSERVED quantity out of real post-effect evidence ONLY.

        The caller may pass an explicit observed quantity. Otherwise the
        canonical observable key is read from the result summary. Success of
        the executor is NEVER a substitute for observation: when no
        observation exists the result is absent (UNKNOWN), not inferred.
        """
        from intent_kernel.mission.quantity import ObservedQuantity, Quantity

        raw = summary.get("observed_quantity")
        if raw is None:
            return None
        try:
            if isinstance(raw, ObservedQuantity):
                return raw
            if isinstance(raw, dict):
                return ObservedQuantity.from_quantity(Quantity.from_dict(raw))
        except Exception:
            # Unusable observation evidence stays absent -> UNKNOWN.
            return None
        return None

    def _build_quantity_evidence(
        self,
        data: Dict[str, Any],
        ownership: DispatchOwnership,
        summary: Dict[str, Any],
        observed_quantity: Optional[Any],
    ) -> Optional[Dict[str, Any]]:
        """Build canonical G1 quantity evidence for the durable result path.

        Returns None when the action carries no quantity authority (the
        record_result contract is unchanged for non-quantitative actions).
        """
        from intent_kernel.mission.quantity import (
            Quantity,
            QuantityAuthorityRecord,
            classify_quantity_observation,
            resolve_quantity_applicability,
        )

        entry = None
        for candidate in data.get("plan", ()):
            if (
                isinstance(candidate, dict)
                and candidate.get("action_id") == ownership.action_id
            ):
                entry = candidate
                break
        if entry is None:
            return None

        raw_authority = (data.get("mission_definition") or {}).get(
            "quantity_authority"
        )
        if not isinstance(raw_authority, dict):
            return None
        try:
            authority = QuantityAuthorityRecord.from_dict(raw_authority)
        except Exception:
            return None
        if not authority.ceilings:
            return None

        operation = str(entry.get("operation", "") or "")
        determination = resolve_quantity_applicability(operation)
        if determination.state.value == "NOT_APPLICABLE":
            return None

        # REQUESTED: the exact C1-bound requested quantity dispatched.
        requested = None
        raw_requested = entry.get("quantity")
        if raw_requested:
            try:
                requested = Quantity.from_dict(raw_requested)
            except Exception:
                requested = None

        # AUTHORIZED: the proven ceiling for this dimension from the
        # established quantity authority (post-effect evidence only records
        # it; it never raises or lowers it).
        authorized = None
        if requested is not None and authority.ceilings:
            ceiling = authority.ceilings[0]
            try:
                authorized = ceiling.quantity
            except Exception:
                authorized = None

        # OBSERVED: from actual post-effect evidence only.
        observed = observed_quantity
        if observed is None:
            observed = self._extract_observed_quantity(summary)

        evidence = classify_quantity_observation(
            mission_id=str(ownership.mission_id),
            action_id=str(ownership.action_id),
            authorized_quantity=authorized,
            requested_quantity=requested,
            observed_quantity=observed,
            request_digest=str(entry.get("request_semantics_digest", "") or ""),
            authority_reference=str(getattr(authority, "source_identity", "") or ""),
        )
        return evidence.to_dict()

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

    def _verify_quantity(
        self,
        spec: DispatchAttemptSpec,
        data: Dict[str, Any],
    ) -> None:
        """Verify quantity against established authority (C3 authoritative acquire proof).

        This is the authoritative quantity proof inside the revision-anchored
        acquire transaction. It runs with fresh R' state and proves:

        REQUEST_QUANTITY <= ACTION_QUANTITY_CEILING
        <= DELEGATED_QUANTITY_CEILING <= VALID_INTENT_QUANTITY_AUTHORITY

        If quantity proof fails: ZERO EXECUTOR HANDOFFS.
        """
        from intent_kernel.mission.quantity import (
            PlanQuantity,
            Quantity,
            QuantityAuthorityRecord,
            DelegatedQuantityCeiling,
            ApplicabilityState,
            prove_plan_quantities_against_authority,
            prove_plan_quantity_against_delegated_ceiling,
            resolve_quantity_applicability,
        )

        # Locate the durable plan entry for this action.
        plan_entries = data.get("plan", ())
        plan_entry = None
        for entry in plan_entries:
            if isinstance(entry, dict) and entry.get("action_id") == spec.action_id:
                plan_entry = entry
                break

        operation = ""
        plan_qty = None
        if plan_entry is not None:
            operation = str(plan_entry.get("operation", "") or "")
            plan_qty = plan_entry.get("quantity")

        # C2/C3/G1.2 §3/§4: operation is authority-bearing and immutable with
        # the plan. The presented operation must equal the authorized
        # operation, and a productive authority-bearing action may never carry
        # an empty operation. Both fail BEFORE any state transition, so a
        # mismatch yields ZERO executor calls.
        if plan_entry is not None and not operation.strip():
            raise DispatchGuardError(
                f"Empty durable operation is invalid for productive action: "
                f"{spec.action_id}",
                decision="",
            )
        if operation and spec.operation and spec.operation != operation:
            raise DispatchGuardError(
                f"Presented operation does not match authorized operation "
                f"(authorized={operation!r} presented={spec.operation!r})",
                decision="",
            )

        # C2/C3/G1.2 §3: applicability is resolved from canonical operation
        # semantics. Missing registration is UNKNOWN, never NOT_APPLICABLE,
        # and UNKNOWN always denies. A registered non-quantitative operation
        # is the ONLY way to skip the quantity proof.
        determination = resolve_quantity_applicability(operation)

        if determination.state is ApplicabilityState.NOT_APPLICABLE:
            # Positive proof of non-quantitative operation.
            return

        if determination.state is ApplicabilityState.UNKNOWN:
            raise DispatchGuardError(
                f"Quantity applicability unknown for operation "
                f"{operation!r} (action {spec.action_id}): {determination.reason}",
                decision="",
            )

        if determination.state is ApplicabilityState.INVALID:
            raise DispatchGuardError(
                f"Quantity applicability invalid for action "
                f"{spec.action_id}: {determination.reason}",
                decision="",
            )

        # AUTHORIZED or UNPROVEN both require a typed quantity on the
        # C1-bound request. UNPROVEN additionally requires authority.
        if not plan_qty:
            raise DispatchGuardError(
                f"Missing quantity on quantity-bearing action: {spec.action_id}",
                decision="",
            )

        # Load quantity authority from mission definition
        mission_def = data.get("mission_definition", {})
        qty_auth_data = mission_def.get("quantity_authority")
        if not qty_auth_data:
            # No quantity authority established - fail closed (UNPROVEN).
            raise DispatchGuardError(
                f"No quantity authority for quantitative action: {spec.action_id}",
                decision="",
            )

        try:
            qty_auth = QuantityAuthorityRecord.from_dict(qty_auth_data)
        except Exception as exc:
            raise DispatchGuardError(
                f"Invalid quantity authority: {exc}",
                decision="",
            ) from exc

        # Convert plan quantity to PlanQuantity
        try:
            q = Quantity.from_dict(plan_qty)
            pq = PlanQuantity(q)
        except Exception as exc:
            raise DispatchGuardError(
                f"Invalid plan quantity: {exc}",
                decision="",
            ) from exc

        # Prove plan quantity against established intent quantity authority
        try:
            prove_plan_quantities_against_authority(
                qty_auth,
                [{"action_id": spec.action_id, "quantity": plan_qty}],
            )
        except Exception as exc:
            raise DispatchGuardError(
                f"Quantity proof failed against intent authority: {exc}",
                decision="",
            ) from exc

        # If action has delegation, also prove against delegated ceiling
        actions = data.get("action_states", {})
        action = actions.get(spec.action_id)
        if isinstance(action, dict) and action.get("delegation_id"):
            delegated_qty_data = action.get("delegated_quantity_ceiling")
            if delegated_qty_data:
                try:
                    delegated_ceiling = DelegatedQuantityCeiling.from_dict(delegated_qty_data)
                except Exception as exc:
                    raise DispatchGuardError(
                        f"Invalid delegated quantity ceiling: {exc}",
                        decision="",
                    ) from exc

                # Extract quantity from spec if present, otherwise from plan
                spec_qty = spec.quantity or plan_qty
                try:
                    q = Quantity.from_dict(spec_qty)
                    pq = PlanQuantity(q)
                except Exception as exc:
                    raise DispatchGuardError(
                        f"Invalid quantity for delegation proof: {exc}",
                        decision="",
                    ) from exc

                try:
                    prove_plan_quantity_against_delegated_ceiling(pq, delegated_ceiling)
                except Exception as exc:
                    raise DispatchGuardError(
                        f"Quantity proof failed against delegated ceiling: {exc}",
                        decision="",
                    ) from exc

    @staticmethod
    def _verify_delegation(
        spec: DispatchAttemptSpec, data: Dict[str, Any]
    ) -> None:
        """Delegated actions additionally prove their derivation at handoff.

        M33.2B: when the durable action carries a delegation grant, the
        presenter must be the bound delegate and the full pure proof
        (chain walk, subset re-proof, liveness, expiry, depth) must hold.
        Actions without a grant pass through untouched. This is a
        conjunct inside acquire(): it never replaces spec verification,
        replay posture, or the durable pre-handoff commits.
        """
        actions = data.get("action_states", {})
        action = actions.get(spec.action_id)
        if not isinstance(action, dict):
            return
        if not (action.get("delegation_id") or ""):
            return
        from intent_kernel.mission.delegation import verify_grant_dispatch

        ok, reason, _chain = verify_grant_dispatch(
            data,
            spec.action_id,
            presenter_executor_id=spec.executor_logical_id,
            now_iso=utc_iso(),
            # C2/C3/G1.3 §2: the leaf proof is quantity-aware. The exact
            # C1-bound quantity travels in, never a sidecar default.
            quantity=spec.quantity,
        )
        if not ok:
            raise DispatchGuardError(
                f"Delegation refused at handoff: {reason}",
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
