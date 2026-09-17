"""M32B-2 — Durable action authority: typed transitions + replay decisions.

MissionActionAuthority is the single narrow API for durable per-action
state movement and local replay prevention. It owns NO execution, NO
gate authority, NO confirmation policy, and NO executor rebinding:

- transition_action() moves one action along the canonical table and
  persists via the MissionRecord store (durable-anchored, N -> N+1).
- decide_replay() answers, read-only, whether one durable action identity
  may dispatch, must not redispatch, needs reconciliation, needs fresh
  confirmation, or is already complete.
- execution_identity_for() derives the canonical local execution identity
  from durable state.

Claim ceiling: LOCAL_DUPLICATE_REDISPATCH_PREVENTION. Nothing here proves
external exactly-once; provider effect identity is stored distinctly and
its absence means exactly-once remains unprovable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from intent_kernel.mission.execution_identity import (
    compute_local_execution_identity,
    effect_identity_digest_for,
)
from intent_kernel.mission.mission_record import (
    ActionState,
    MissionRecord,
    detach_json_value,
)
from intent_kernel.mission.store import (
    MissionRecordNotFoundError,
    MissionRecordStorePort,
)
from intent_kernel.mission.transitions import (
    ActionTransitionError,
    require_legal_action_transition,
    restart_posture_for as _posture_for,
)
from intent_kernel.runtime.verification import ActionVerificationProof
from intent_kernel.time_utils import utc_iso


# Verification freshness verdicts (durable-layer view; TTL policy, if any,
# belongs to the gate/resume contract, never invented here).
FRESH_DETERMINISTIC = "FRESH_DETERMINISTIC"
REQUIRES_REVALIDATION = "REQUIRES_REVALIDATION"
NOT_VERIFIED = "NOT_VERIFIED"


class ReplayDecision(str, Enum):
    """Read-only dispatch verdicts for one durable action identity."""
    MAY_DISPATCH = "MAY_DISPATCH"
    DO_NOT_REDISPATCH = "DO_NOT_REDISPATCH"
    AMBIGUOUS_RECONCILIATION_REQUIRED = "AMBIGUOUS_RECONCILIATION_REQUIRED"
    RECONFIRMATION_REQUIRED = "RECONFIRMATION_REQUIRED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"


@dataclass(frozen=True, slots=True)
class ActionTransitionEvidence:
    """Typed evidence carried by one durable action transition.

    Audit strings only (requested_by/reason) plus strictly gated payload:
    result attaches ONLY on -> RESULT_RECORDED; error ONLY on -> FAILED;
    verification fields ONLY on -> VERIFICATION_REQUIRED/VERIFIED;
    provider_effect_id binds once ("" -> token) and never changes after.
    No tokens, sessions, callbacks, or executable authority may be carried.
    """

    requested_by: str
    reason: str
    provider_effect_id: str = ""
    result: Any = None
    error: Optional[str] = None
    verification_status: str = ""
    verification_evidence: Optional[Dict[str, Any]] = None
    verification_proof: Optional[ActionVerificationProof] = None
    completion_basis: Optional[ActionVerificationProof] = None
    confirmation_basis_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.requested_by, str) or not self.requested_by.strip():
            raise ValueError("requested_by must be a non-empty string")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(self.provider_effect_id, str):
            raise ValueError("provider_effect_id must be a string")
        if not isinstance(self.verification_status, str):
            raise ValueError("verification_status must be a string")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error must be a string or None")
        if self.verification_proof is not None and not isinstance(
            self.verification_proof, ActionVerificationProof
        ):
            raise ValueError(
                "verification_proof must be an ActionVerificationProof or None"
            )
        if self.completion_basis is not None and not isinstance(
            self.completion_basis, ActionVerificationProof
        ):
            raise ValueError(
                "completion_basis must be an ActionVerificationProof or None"
            )
        if self.verification_evidence is not None and not isinstance(
            self.verification_evidence, dict
        ):
            raise ValueError("verification_evidence must be a dict or None")
        object.__setattr__(self, "result", detach_json_value(self.result))
        if self.verification_evidence is not None:
            object.__setattr__(
                self,
                "verification_evidence",
                detach_json_value(self.verification_evidence),
            )


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Detached outcome of one committed durable action transition."""

    mission_id: str
    action_id: str
    previous_state: ActionState
    new_state: ActionState
    mission_revision: int
    record: MissionRecord


@dataclass(frozen=True, slots=True)
class RestartPostureView:
    """Read-only restart posture for one durable action state."""

    safe_automatic_next_step: str
    auto_redispatch_allowed: bool
    reconciliation_required: bool
    fresh_verification_required: bool


@runtime_checkable
class ConfirmationAuthority(Protocol):
    """Canonical confirmation authority for M32B-3.

    Validates that a fresh canonical confirmation exists for the
    exact expected mission, action, and confirmation basis digest.
    Returns True only when the confirmation is CONFIRMED, not
    consumed/invalidated/expired/rejected, and its bound basis
    matches the expected digest.
    """

    def validate_confirmation(
        self,
        *,
        mission_id: str,
        action_id: str,
        confirmation_basis_digest: str,
    ) -> bool: ...


class MissionActionAuthority:
    """Narrow durable action-state authority over a MissionRecord store.

    M32B-3: confirmation_service is an optional canonical confirmation
    authority that produces fresh transient confirmation authority.
    It is NOT a durable storage of approval; it validates fresh
    confirmation requests through the canonical path. When set, the
    RECONFIRMATION_REQUIRED -> AUTHORIZED transition requires fresh
    confirmation validated by this service. Without it, the
    transition is rejected: a matching deterministic digest alone
    MUST NOT authorize an action.
    """

    def __init__(
        self,
        store: MissionRecordStorePort,
        confirmation_service: ConfirmationAuthority | None = None,
    ) -> None:
        self._store = store
        self._confirmation_service = confirmation_service

    # -- internal load helpers (no mutation) -------------------------------

    def _load_data(self, mission_id: str) -> Dict[str, Any]:
        data = self._store.load(mission_id)
        if data is None:
            raise MissionRecordNotFoundError(
                f"No durable MissionRecord: {mission_id} (NON_RESUMABLE)"
            )
        return data

    @staticmethod
    def _action(data: Dict[str, Any], action_id: str) -> Dict[str, Any]:
        action = data.get("action_states", {}).get(action_id)
        if not isinstance(action, dict):
            raise MissionRecordNotFoundError(
                f"No durable action: {action_id}"
            )
        return action

    @staticmethod
    def _plan_entry(data: Dict[str, Any], action_id: str) -> Dict[str, Any]:
        for entry in data.get("plan", []):
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                return entry
        raise MissionRecordNotFoundError(
            f"No durable plan entry for action: {action_id}"
        )

    @staticmethod
    def _parse_state(raw: Any, action_id: str) -> ActionState:
        try:
            return ActionState(raw)
        except ValueError as exc:
            raise ActionTransitionError(
                f"Unknown durable action state for {action_id}: {raw!r}"
            ) from exc

    # -- identity -----------------------------------------------------------

    def execution_identity_for(self, mission_id: str, action_id: str) -> str:
        """Canonical MODEL E2 local execution identity from durable state.

        Pre-dispatch fields only; post-dispatch effect binding never
        redefines it.
        """
        data = self._load_data(mission_id)
        action = self._action(data, action_id)
        plan_entry = self._plan_entry(data, action_id)
        request_digest = plan_entry.get("request_semantics_digest", "")
        if not isinstance(request_digest, str) or not request_digest:
            raise ActionTransitionError(
                f"Missing request_semantics_digest for action: {action_id}"
            )
        return compute_local_execution_identity(
            mission_id,
            action_id,
            request_digest,
            action.get("expected_executor_logical_id", ""),
            action.get("expected_governed_registration_id", ""),
            action.get("expected_resource_generation", 0),
        )

    @staticmethod
    def _expected_identity(data: Dict[str, Any], action_id: str) -> str:
        """Recompute E2 identity from durable file content (stamp/verify)."""
        request_digest = ""
        for entry in data.get("plan", []):
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                request_digest = entry.get("request_semantics_digest", "")
                break
        if not isinstance(request_digest, str) or not request_digest:
            raise ActionTransitionError(
                f"Missing request_semantics_digest for action: {action_id}"
            )
        action = data.get("action_states", {}).get(action_id, {})
        return compute_local_execution_identity(
            data.get("mission_id", ""),
            action_id,
            request_digest,
            action.get("expected_executor_logical_id", ""),
            action.get("expected_governed_registration_id", ""),
            action.get("expected_resource_generation", 0),
        )

    def _require_proof_binding(
        self,
        proof: ActionVerificationProof,
        mission_id: str,
        action_id: str,
        data: Dict[str, Any],
    ) -> None:
        """Validate a gate proof against durable mission authority."""
        if not isinstance(proof, ActionVerificationProof):
            raise ActionTransitionError(
                "Canonical ActionVerificationProof required; arbitrary "
                "caller dicts or values are never sufficient"
            )
        if not proof.authority_complete:
            raise ActionTransitionError(
                "Verification proof is not gate-complete "
                "(VERIFIED_SUCCESS + VerificationGate source + authority)"
            )
        if proof.mission_id != mission_id or proof.action_id != action_id:
            raise ActionTransitionError(
                "Verification proof binds another mission/action"
            )
        plan_entry = self._plan_entry(data, action_id)
        if proof.request_semantics_digest != plan_entry.get(
            "request_semantics_digest", ""
        ):
            raise ActionTransitionError(
                "Verification proof contract does not match durable plan"
            )

    @staticmethod
    def _proof_evidence_record(proof: ActionVerificationProof) -> Dict[str, Any]:
        """Persistable verification record derived strictly from the proof."""
        record = proof.to_dict()
        record["proof_digest"] = proof.proof_digest()
        return detach_json_value(record)

    # -- durable transition --------------------------------------------------

    def transition_action(
        self,
        mission_id: str,
        action_id: str,
        expected_mission_revision: int,
        expected_action_state: ActionState,
        target_action_state: ActionState,
        evidence: ActionTransitionEvidence,
    ) -> TransitionResult:
        """Move one action along the canonical table, durably anchored.

        1. load current durable MissionRecord (absent -> fail closed);
        2. require durable revision == expected_mission_revision;
        3. locate exact action (absent -> fail closed);
        4. require durable state == expected_action_state;
        5. require the edge in the canonical table;
        6. derive the candidate strictly from durable state (plan,
           expectations, mission status, and all other actions untouched);
        7. commit revision N -> N+1 (durable-anchored inside the store);
        8. reload from disk and return the detached committed record.

        No memory mutation exists to order: this authority holds no
        process-local mission state. No silent retry, no revision jump.
        """
        if not isinstance(expected_action_state, ActionState):
            raise ActionTransitionError(
                f"expected_action_state must be an ActionState: "
                f"{expected_action_state!r}"
            )
        if not isinstance(target_action_state, ActionState):
            raise ActionTransitionError(
                f"target_action_state must be an ActionState: "
                f"{target_action_state!r}"
            )
        if not isinstance(evidence, ActionTransitionEvidence):
            raise ActionTransitionError("evidence must be ActionTransitionEvidence")

        data = self._load_data(mission_id)
        durable_revision = data.get("revision")
        if durable_revision != expected_mission_revision:
            raise ActionTransitionError(
                f"Durable mission revision is {durable_revision}, "
                f"caller expected {expected_mission_revision}"
            )
        action = self._action(data, action_id)
        current = self._parse_state(action.get("state"), action_id)
        if current != expected_action_state:
            raise ActionTransitionError(
                f"Durable action state is {current.value}, caller expected "
                f"{expected_action_state.value}"
            )
        require_legal_action_transition(current, target_action_state)

        # M32B-3: durable confirmation state validation
        # (fail-closed for security-significant fields).
        durable_confirmation_required = bool(
            action.get("confirmation_required", False)
        )
        durable_confirmation_basis = action.get(
            "confirmation_basis_digest", ""
        )
        # Fail-closed: confirmation_required=True with empty or
        # missing confirmation_basis_digest is malformed current-
        # schema state and must not be interpreted as confirmation-
        # required=False merely because the field is empty.
        if durable_confirmation_required and (
            not durable_confirmation_basis
            or not isinstance(durable_confirmation_basis, str)
        ):
            raise ActionTransitionError(
                "Malformed durable confirmation state: "
                "confirmation_required=True requires a non-empty "
                "confirmation_basis_digest"
            )

        candidate = detach_json_value(data)
        updated = dict(action)
        updated["state"] = target_action_state.value

        # M32B-3: RECONFIRMATION_REQUIRED -> AUTHORIZED requires
        # fresh canonical confirmation produced through the
        # canonical confirmation service. A matching deterministic
        # digest alone MUST NOT authorize. The canonical
        # confirmation service must validate the fresh confirmation
        # request and produce transient authority.
        if current is ActionState.RECONFIRMATION_REQUIRED and target_action_state is ActionState.AUTHORIZED:
            if not durable_confirmation_required:
                raise ActionTransitionError(
                    "RECONFIRMATION_REQUIRED -> AUTHORIZED requires a "
                    "durable confirmation requirement"
                )
            # Fail-closed: empty confirmation basis is rejected.
            if not evidence.confirmation_basis_digest:
                raise ActionTransitionError(
                    "RECONFIRMATION_REQUIRED -> AUTHORIZED requires "
                    "fresh confirmation basis digest in evidence"
                )
            # Verify digest matches the durable confirmation basis.
            if durable_confirmation_basis != evidence.confirmation_basis_digest:
                raise ActionTransitionError(
                    "Confirmation basis digest mismatch: request "
                    "semantics changed, fresh confirmation required"
                )
            # Require fresh canonical confirmation from the
            # confirmation service. The digest alone is insufficient.
            if self._confirmation_service is not None:
                fresh_confirmed = self._confirmation_service.validate_confirmation(
                    mission_id=mission_id,
                    action_id=action_id,
                    confirmation_basis_digest=evidence.confirmation_basis_digest,
                )
                if not fresh_confirmed:
                    raise ActionTransitionError(
                        "RECONFIRMATION_REQUIRED -> AUTHORIZED requires "
                        "fresh canonical confirmation from the "
                        "confirmation service"
                    )
            else:
                # Without a confirmation service, reject the
                # transition: digest alone cannot authorize.
                raise ActionTransitionError(
                    "RECONFIRMATION_REQUIRED -> AUTHORIZED requires "
                    "a canonical confirmation service to validate "
                    "fresh confirmation"
                )
            # Authorization granted only after fresh canonical
            # confirmation. Clear confirmation requirement fields.
            updated["confirmation_required"] = False
            updated["confirmation_basis_digest"] = ""

        # M32B-3: PENDING -> AUTHORIZED is blocked when
        # durable confirmation_required=True (restart invalidation).
        # Only RECONFIRMATION_REQUIRED -> AUTHORIZED with fresh
        # confirmation is allowed.
        if current is ActionState.PENDING and target_action_state is ActionState.AUTHORIZED:
            if durable_confirmation_required:
                raise ActionTransitionError(
                    "PENDING -> AUTHORIZED blocked: durable confirmation "
                    "required; fresh confirmation needed"
                )

        # MODEL E2 identity stamp/verify: bind once from durable content,
        # then immutable. Post-dispatch effect binding never redefines it.
        durable_ident = action.get("local_execution_identity", "") or ""
        recomputed_ident = self._expected_identity(data, action_id)
        if durable_ident:
            if durable_ident != recomputed_ident:
                raise ActionTransitionError(
                    "Durable local_execution_identity does not match "
                    "recomputation (tamper)"
                )
            stamped_ident = durable_ident
        else:
            stamped_ident = recomputed_ident
        updated["local_execution_identity"] = stamped_ident

        # Typed evidence application. Anything outside the per-target
        # allowance below is rejected, never ignored.
        if evidence.provider_effect_id:
            durable_effect = action.get("provider_effect_id", "") or ""
            if not durable_effect:
                updated["provider_effect_id"] = evidence.provider_effect_id
                updated["effect_identity_digest"] = effect_identity_digest_for(
                    evidence.provider_effect_id
                )
            elif durable_effect != evidence.provider_effect_id:
                raise ActionTransitionError(
                    "provider_effect_id already bound; refusing replacement"
                )
        if evidence.result is not None:
            if target_action_state is not ActionState.RESULT_RECORDED:
                raise ActionTransitionError(
                    "result may only attach on -> RESULT_RECORDED"
                )
            updated["result"] = detach_json_value(evidence.result)
        if evidence.error is not None:
            if target_action_state is not ActionState.FAILED:
                raise ActionTransitionError(
                    "error may only attach on -> FAILED"
                )
            updated["error_message"] = evidence.error
        if evidence.verification_status or evidence.verification_evidence:
            if target_action_state not in (
                ActionState.VERIFICATION_REQUIRED,
                ActionState.VERIFIED,
            ):
                raise ActionTransitionError(
                    "verification fields may only attach on "
                    "-> VERIFICATION_REQUIRED / VERIFIED"
                )
            if target_action_state is ActionState.VERIFIED:
                raise ActionTransitionError(
                    "target VERIFIED requires a canonical "
                    "ActionVerificationProof, never legacy fields"
                )
            if evidence.verification_status:
                updated["verification_status"] = evidence.verification_status
            if evidence.verification_evidence is not None:
                updated["verification_evidence"] = detach_json_value(
                    evidence.verification_evidence
                )

        # AUTHORITY_SENSITIVE targets: canonical typed proof required.
        if target_action_state is ActionState.VERIFIED:
            if evidence.verification_proof is None:
                raise ActionTransitionError(
                    "target VERIFIED requires a canonical "
                    "ActionVerificationProof; arbitrary caller evidence "
                    "is never sufficient"
                )
            self._require_proof_binding(
                evidence.verification_proof, mission_id, action_id, data
            )
            proof = evidence.verification_proof
            updated["verification_status"] = proof.verification_status
            updated["verification_evidence"] = self._proof_evidence_record(proof)
            updated["verification_proof_digest"] = proof.proof_digest()
        if target_action_state is ActionState.COMPLETED:
            basis = evidence.completion_basis
            if basis is None:
                raise ActionTransitionError(
                    "target COMPLETED requires the canonical "
                    "verification proof basis; arbitrary callers cannot "
                    "write action COMPLETED"
                )
            self._require_proof_binding(basis, mission_id, action_id, data)
            if basis.proof_digest() != (
                action.get("verification_proof_digest", "") or ""
            ):
                raise ActionTransitionError(
                    "completion basis is superseded or foreign: it is not "
                    "the proof that authorized current VERIFIED state"
                )

        candidate["action_states"] = dict(candidate.get("action_states", {}))
        candidate["action_states"][action_id] = updated
        candidate["revision"] = durable_revision + 1
        candidate["updated_at"] = utc_iso()
        try:
            candidate_record = MissionRecord.from_dict(candidate)
        except (ValueError, KeyError, TypeError) as exc:
            raise ActionTransitionError(
                f"Invalid transition candidate: {exc}"
            ) from exc

        outcome = self._store.transition_confirmation(
            expected_mission_revision, candidate_record,
        )
        if outcome.outcome != "committed":
            raise ActionTransitionError(
                f"Durable action commit failed: {outcome.outcome} "
                f"(rev={outcome.revision}): {outcome.reason}"
            )

        # Return the reloaded committed record: proof of durability, detached.
        reloaded = self._load_data(mission_id)
        return TransitionResult(
            mission_id=mission_id,
            action_id=action_id,
            previous_state=current,
            new_state=target_action_state,
            mission_revision=durable_revision + 1,
            record=MissionRecord.from_dict(reloaded),
        )

    # -- replay decision (read-only) ------------------------------------------

    def decide_replay(
        self,
        mission_id: str,
        action_id: str,
        *,
        confirmation_required: bool = False,
        expected_execution_identity: Optional[str] = None,
    ) -> ReplayDecision:
        """Decide, read-only, whether one durable identity may dispatch.

        Derives strictly from durable canonical action state (+ optional
        caller-presented execution identity, which must match the
        durable-derived identity or the call fails closed). Performs no
        dispatch, mutates nothing, consults no RRM, gate, or registry.

        M32B-3 restart invalidation: the durable confirmation_required
        field on the action takes precedence over caller-presented state.
        After restart, old in-memory confirmation approval is never
        reused; a durable confirmation requirement forces
        RECONFIRMATION_REQUIRED for pre-dispatch states.
        """
        data = self._load_data(mission_id)
        action = self._action(data, action_id)
        state = self._parse_state(action.get("state"), action_id)
        # Durable confirmation requirement: the action itself records
        # that confirmation is needed. After restart, this persists and
        # invalidates any stale in-memory approval.
        durable_confirmation_required = bool(
            action.get("confirmation_required", False)
        )
        effective_confirmation_required = (
            durable_confirmation_required or confirmation_required
        )

        if expected_execution_identity is not None:
            current_identity = self.execution_identity_for(mission_id, action_id)
            if current_identity != expected_execution_identity:
                raise ActionTransitionError(
                    "Presented execution identity does not match durable "
                    "authority (stale or mismatched intent)"
                )

        if state is ActionState.PENDING:
            if effective_confirmation_required:
                return ReplayDecision.RECONFIRMATION_REQUIRED
            return ReplayDecision.MAY_DISPATCH
        if state is ActionState.AUTHORIZED:
            if effective_confirmation_required:
                return ReplayDecision.RECONFIRMATION_REQUIRED
            return ReplayDecision.MAY_DISPATCH
        if state is ActionState.RECONFIRMATION_REQUIRED:
            return ReplayDecision.RECONFIRMATION_REQUIRED
        if state in (
            ActionState.DISPATCH_INTENT_RECORDED,
            ActionState.DISPATCHING,
            ActionState.AMBIGUOUS_EFFECT,
        ):
            return ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED
        if state is ActionState.COMPLETED:
            return ReplayDecision.ALREADY_COMPLETED
        # RESULT_RECORDED, VERIFICATION_REQUIRED, VERIFIED, FAILED: the exact
        # identity already crossed (or terminally closed) the dispatch
        # boundary — duplicate redispatch is prohibited. Next steps belong
        # to the verification/completion gates or explicit recovery, never
        # to automatic redispatch.
        return ReplayDecision.DO_NOT_REDISPATCH

    def verification_freshness_for(
        self, mission_id: str, action_id: str
    ) -> str:
        """Durable verification-freshness verdict (M28.2.1 boundary).

        FRESH_DETERMINISTIC: VERIFIED with deterministic content-bound
        evidence only (no provider observations); timeless.
        REQUIRES_REVALIDATION: VERIFIED but the authorizing evidence
        involves point-in-time provider observations. A restart (or any
        productive reuse) must re-observe through the gate contract;
        history is never converted into freshness here.
        NOT_VERIFIED: durable state is not VERIFIED.
        No TTL policy is invented: the verdict reports what durable
        authority knows; revalidation itself belongs to the gate/resume
        contract.
        """
        data = self._load_data(mission_id)
        action = self._action(data, action_id)
        state = self._parse_state(action.get("state"), action_id)
        if state is not ActionState.VERIFIED:
            return NOT_VERIFIED
        evidence = action.get("verification_evidence") or {}
        if not isinstance(evidence, dict):
            return REQUIRES_REVALIDATION
        observations = evidence.get("external_observations") or []
        if observations or evidence.get("external_evidence_required") is True:
            return REQUIRES_REVALIDATION
        return FRESH_DETERMINISTIC

    # -- crash posture (read-only view over the canonical matrix) --------------

    @staticmethod
    def restart_posture_for(state: ActionState) -> RestartPostureView:
        """Restart posture for one durable state. Unknown states fail closed."""
        posture = _posture_for(state)
        return RestartPostureView(
            safe_automatic_next_step=posture.safe_automatic_next_step,
            auto_redispatch_allowed=posture.auto_redispatch_allowed,
            reconciliation_required=posture.reconciliation_required,
            fresh_verification_required=posture.fresh_verification_required,
        )
