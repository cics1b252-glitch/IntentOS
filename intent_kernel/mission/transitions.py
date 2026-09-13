"""M32B-2 — Durable action state machine: transition table + crash postures.

The transition table is the single canonical authority for legal
per-action state movement. Transitions are typed and fail closed: no
arbitrary caller-supplied transition is ever accepted.

Deliberate M32B-2 boundaries (documented, not accidental):
- VERIFIED -> FAILED has NO edge. No explicit canonical semantics were
  found permitting a verified action to fail afterwards; rejected fail
  closed. A future movement may add it only with an explicit contract.
- RECONFIRMATION_REQUIRED has NO exits in M32B-2. Re-authorization after
  fresh confirmation is owned by M32B-3.
- AMBIGUOUS_EFFECT has NO exits in M32B-2. No automatic (and no manual)
  dispatch/completion transition exists yet; reconciliation flows belong to
  future movements. Ambiguity is preserved, never guessed away.
- COMPLETED / FAILED are terminal: no exits without an explicit recovery
  contract, of which M32B-2 implements none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet

from intent_kernel.mission.mission_record import ActionState
from intent_kernel.mission.store import MissionRecordValidationError


class ActionTransitionError(MissionRecordValidationError):
    """A durable action transition or replay decision failed closed."""


class IllegalActionTransitionError(ActionTransitionError):
    """A requested action-state transition is not in the canonical table."""


# Canonical legal graph: current state -> allowed target states.
ACTION_TRANSITIONS: Dict[ActionState, FrozenSet[ActionState]] = {
    ActionState.PENDING: frozenset({
        ActionState.AUTHORIZED,
        ActionState.RECONFIRMATION_REQUIRED,
        ActionState.FAILED,
    }),
    ActionState.AUTHORIZED: frozenset({
        ActionState.DISPATCH_INTENT_RECORDED,
        ActionState.RECONFIRMATION_REQUIRED,
        ActionState.FAILED,
    }),
    ActionState.DISPATCH_INTENT_RECORDED: frozenset({
        ActionState.DISPATCHING,
        ActionState.AMBIGUOUS_EFFECT,
        ActionState.FAILED,
    }),
    ActionState.DISPATCHING: frozenset({
        ActionState.RESULT_RECORDED,
        ActionState.AMBIGUOUS_EFFECT,
        ActionState.FAILED,
    }),
    ActionState.RESULT_RECORDED: frozenset({
        ActionState.VERIFICATION_REQUIRED,
        ActionState.AMBIGUOUS_EFFECT,
        ActionState.FAILED,
    }),
    ActionState.VERIFICATION_REQUIRED: frozenset({
        ActionState.VERIFIED,
        ActionState.AMBIGUOUS_EFFECT,
        ActionState.FAILED,
    }),
    ActionState.VERIFIED: frozenset({
        ActionState.COMPLETED,
    }),
    ActionState.RECONFIRMATION_REQUIRED: frozenset(),
    ActionState.AMBIGUOUS_EFFECT: frozenset(),
    ActionState.COMPLETED: frozenset(),
    ActionState.FAILED: frozenset(),
}


def is_legal_action_transition(
    current: ActionState, target: ActionState
) -> bool:
    """Typed table lookup. Unknown states fail closed (False, never guess)."""
    if not isinstance(current, ActionState) or not isinstance(
        target, ActionState
    ):
        return False
    return target in ACTION_TRANSITIONS.get(current, frozenset())


def require_legal_action_transition(
    current: ActionState, target: ActionState
) -> None:
    """Raise IllegalActionTransitionError unless the edge is canonical."""
    if not is_legal_action_transition(current, target):
        current_name = (
            current.value if isinstance(current, ActionState) else repr(current)
        )
        target_name = (
            target.value if isinstance(target, ActionState) else repr(target)
        )
        raise IllegalActionTransitionError(
            f"Illegal action transition: {current_name} -> {target_name}"
        )


# ---------------------------------------------------------------------------
# Crash-window restart postures (M32B-2 §17 matrix)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RestartPosture:
    """What a fresh process may do automatically for one durable state."""
    safe_automatic_next_step: str
    auto_redispatch_allowed: bool
    reconciliation_required: bool
    fresh_verification_required: bool


# No durable state in M32B-2 permits automatic redispatch. The dispatch
# boundary may only be crossed by explicit authorization in a live process
# (PENDING/AUTHORIZED via the normal path); every post-intent state either
# reconciles, verifies through the gate, or stands as history.
RESTART_POSTURES: Dict[ActionState, RestartPosture] = {
    ActionState.PENDING: RestartPosture(
        safe_automatic_next_step="normal authorization path only",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=False,
    ),
    ActionState.AUTHORIZED: RestartPosture(
        safe_automatic_next_step=(
            "authorization revalidation; RECONFIRMATION_REQUIRED where "
            "confirmation-dependent"
        ),
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=False,
    ),
    ActionState.RECONFIRMATION_REQUIRED: RestartPosture(
        safe_automatic_next_step="fresh confirmation flow (M32B-3 contract)",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=False,
    ),
    # C2: durable intent, no reliable proof the provider accepted effect.
    ActionState.DISPATCH_INTENT_RECORDED: RestartPosture(
        safe_automatic_next_step="reconciliation only (provider lookup / "
        "effect token / fresh observation / operator)",
        auto_redispatch_allowed=False,
        reconciliation_required=True,
        fresh_verification_required=False,
    ),
    # C2/C3 boundary: effect may have occurred externally without local proof.
    ActionState.DISPATCHING: RestartPosture(
        safe_automatic_next_step="reconciliation only; external effect "
        "unknown, never assumed absent or present",
        auto_redispatch_allowed=False,
        reconciliation_required=True,
        fresh_verification_required=False,
    ),
    ActionState.AMBIGUOUS_EFFECT: RestartPosture(
        safe_automatic_next_step="reconciliation only; ambiguity preserved",
        auto_redispatch_allowed=False,
        reconciliation_required=True,
        fresh_verification_required=False,
    ),
    # C4: local result proof exists; verification gate path next.
    ActionState.RESULT_RECORDED: RestartPosture(
        safe_automatic_next_step="VerificationGate path only",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=True,
    ),
    # C5: gate path next.
    ActionState.VERIFICATION_REQUIRED: RestartPosture(
        safe_automatic_next_step="VerificationGate path only",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=True,
    ),
    # C6: historical verified state; mutable provider evidence must still
    # pass M28.2.1 freshness at productive use (gate-owned, not decided here).
    ActionState.VERIFIED: RestartPosture(
        safe_automatic_next_step="completion path via gates; revalidate "
        "mutable evidence freshness before productive use",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=True,
    ),
    # C7: historical completion only; mission gate owns mission completion.
    ActionState.COMPLETED: RestartPosture(
        safe_automatic_next_step="none automatic; historical record only",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=False,
    ),
    ActionState.FAILED: RestartPosture(
        safe_automatic_next_step="none automatic; terminal without an "
        "explicit recovery contract",
        auto_redispatch_allowed=False,
        reconciliation_required=False,
        fresh_verification_required=False,
    ),
}


def restart_posture_for(state: ActionState) -> RestartPosture:
    """Posture for one durable state. Unknown states fail closed."""
    if not isinstance(state, ActionState):
        raise IllegalActionTransitionError(
            f"Unknown action state for restart posture: {state!r}"
        )
    return RESTART_POSTURES[state]
