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

    #: Action states from which a delegation may be derived (M33.2B).
    #: The parent authority must be live: authorized and operating, never
    #: history. PENDING never authorized anything; RECONFIRMATION_REQUIRED
    #: awaits fresh confirmation (deriving from it would launder
    #: unconfirmed authority); post-dispatch states (RESULT_RECORDED and
    #: beyond) are spent history, not current authority; FAILED /
    #: AMBIGUOUS_EFFECT / COMPLETED are terminally closed.
    _DELEGATION_PARENT_LIVE_STATES = frozenset({
        ActionState.AUTHORIZED,
        ActionState.DISPATCH_INTENT_RECORDED,
        ActionState.DISPATCHING,
    })

    def __init__(
        self,
        store: MissionRecordStorePort,
        confirmation_service: ConfirmationAuthority | None = None,
    ) -> None:
        self._store = store
        self._confirmation_service = confirmation_service

    # NOTE (G7): no public setter is provided on purpose. The T36
    # authority-surface guard pins the exact public method set of this
    # class; the composition root attaches the confirmation service via
    # direct assignment (see composition.build) because constructor
    # injection is impossible there (service needs runtime needs guard
    # needs this authority).

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

        # Determine if this transition involves confirmation field changes.
        # Only these three transitions modify confirmation fields:
        # - PENDING -> RECONFIRMATION_REQUIRED (sets confirmation_required=True + basis)
        # - RECONFIRMATION_REQUIRED -> AUTHORIZED (clears both)
        # - RECONFIRMATION_REQUIRED -> FAILED (clears both)
        is_confirmation_transition = (
            (current is ActionState.PENDING and target_action_state is ActionState.RECONFIRMATION_REQUIRED)
            or (current is ActionState.RECONFIRMATION_REQUIRED and target_action_state is ActionState.AUTHORIZED)
            or (current is ActionState.RECONFIRMATION_REQUIRED and target_action_state is ActionState.FAILED)
        )

        if is_confirmation_transition:
            # Confirmation transition: use transition_confirmation for confirmation fields.
            new_confirmation_required = updated.get("confirmation_required", False)
            new_confirmation_basis_digest = updated.get("confirmation_basis_digest", "")

            outcome = self._store.transition_confirmation(
                mission_id,
                action_id,
                expected_mission_revision,
                expected_action_state,
                target_action_state,
                new_confirmation_required,
                new_confirmation_basis_digest,
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
        else:
            # Non-confirmation transition: use ordinary commit.
            # The updated dict already contains all field changes (including
            # local_execution_identity, provider_effect_id, result, etc.).
            # Confirmation fields are unchanged, so ordinary commit accepts it.
            candidate = detach_json_value(data)
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

            outcome = self._store.commit(expected_mission_revision, candidate_record)
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

    # -- governed delegation (M33.2B) -----------------------------------------

    def grant_delegation(
        self,
        mission_id: str,
        child_action_id: str,
        expected_mission_revision: int,
        *,
        parent_action_id: str,
        delegate_agent_id: str,
        delegate_governed_registration_id: str = "",
        allowed_capabilities: Any = (),
        allowed_resources: Any = (),
        allowed_targets: Any = (),
        max_risk_level: str = "",
        max_timeout_seconds: float = 0.0,
        require_verification: Optional[bool] = None,
        max_side_effect: str = "",
        expires_at: str = "",
    ) -> TransitionResult:
        """Derive a non-escalating delegation grant for one action.

        AUTHORITY(CHILD) ⊆ AUTHORITY(PARENT): every narrowed dimension is
        proven mechanically before anything is persisted. Delegation is
        mission-scoped (parent and child live in the same record;
        cross-mission delegation is structurally rejected) and derived
        only from a live-authorized parent action — planners, capability
        registrations, agent identity, memory, or presented approval
        artifacts can never create it. The delegation identity is minted
        here, never caller-supplied. Direct record injection cannot
        create usable delegation authority: ordinary commit() rejects
        delegation field changes, and enforcement re-proves the
        derivation at every handoff.
        """
        from intent_kernel.mission import delegation as _delegation

        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ActionTransitionError("mission_id must be a non-empty string")
        if not isinstance(child_action_id, str) or not child_action_id.strip():
            raise ActionTransitionError("child_action_id must be a non-empty string")
        if not isinstance(parent_action_id, str) or not parent_action_id.strip():
            raise ActionTransitionError("parent_action_id must be a non-empty string")
        if child_action_id == parent_action_id:
            raise ActionTransitionError(
                "delegation parent and child must be distinct actions"
            )
        if not isinstance(delegate_agent_id, str) or not delegate_agent_id.strip():
            raise ActionTransitionError(
                "delegate_agent_id must be a non-empty governed agent id "
                "(V1 delegates to governed agents only)"
            )
        if not isinstance(delegate_governed_registration_id, str) or not (
            delegate_governed_registration_id or ""
        ).strip():
            raise ActionTransitionError(
                "delegate_governed_registration_id must be non-empty: V1 "
                "delegates to governed agents only, and the delegate "
                "registration is pinned at creation for handoff revalidation"
            )

        data = self._load_data(mission_id)
        durable_revision = data.get("revision")
        if durable_revision != expected_mission_revision:
            raise ActionTransitionError(
                f"Durable mission revision is {durable_revision}, "
                f"caller expected {expected_mission_revision}"
            )
        action_states = data.get("action_states", {})
        child = action_states.get(child_action_id)
        if not isinstance(child, dict):
            raise ActionTransitionError(
                f"No durable child action: {child_action_id}"
            )
        if (child.get("delegation_id") or "") != "":
            raise ActionTransitionError(
                f"Action already carries a delegation grant: {child_action_id} "
                "(one grant per action; revoke-then-regrant is not permitted)"
            )
        parent = action_states.get(parent_action_id)
        if not isinstance(parent, dict):
            raise ActionTransitionError(
                f"No durable parent action: {parent_action_id} "
                "(unknown parents fail closed)"
            )
        parent_state = self._parse_state(parent.get("state"), parent_action_id)
        if parent_state not in self._DELEGATION_PARENT_LIVE_STATES:
            raise ActionTransitionError(
                f"Parent action is not live-authorized: {parent_action_id} "
                f"is {parent_state.value}"
            )

        now_iso = utc_iso()
        # Stillborn grants (already expired at creation) are rejected:
        # authority is never manufactured already-dead.
        if (expires_at or "") != "" and (expires_at or "") <= now_iso:
            raise ActionTransitionError(
                "Delegation expires_at is already past: stillborn grants "
                "fail closed"
            )
        # Nested edge: the parent grant itself must be currently valid.
        # Root edge (parent carries no grant): the parent action is the root.
        parent_grant = None
        parent_chain: list = []
        parent_grant_id = str(parent.get("delegation_id") or "")
        if parent_grant_id:
            ok, reason, parent_chain = _delegation.verify_grant_dispatch(
                data,
                parent_action_id,
                presenter_executor_id=None,
                now_iso=now_iso,
            )
            if not ok:
                raise ActionTransitionError(
                    f"Parent delegation is not currently valid: {reason}"
                )
            parent_grant = _delegation.grant_view(parent)
            if parent_grant is None:
                raise ActionTransitionError("Parent grant unreadable")
            if str(parent_grant.get("delegation_id") or "") != parent_grant_id:
                raise ActionTransitionError("Parent grant identity mismatch")
            if len(parent_chain) + 1 > _delegation.MAX_DELEGATION_DEPTH:
                raise ActionTransitionError(
                    "Delegation nesting depth overflow: the new grant "
                    "would exceed the bound"
                )
        # Ceiling inheritance is resolved here, at creation: empty means
        # "inherit parent effective" on nested edges (root edges must be
        # explicit — enforced by the edge proof). Stored grants are
        # therefore always explicit; handoff re-proof needs no resolution.
        if not isinstance(max_timeout_seconds, (int, float)) or isinstance(
            max_timeout_seconds, bool
        ):
            raise ActionTransitionError("max_timeout_seconds must be numeric")
        if require_verification is not None and not isinstance(
            require_verification, bool
        ):
            raise ActionTransitionError(
                "require_verification must be a bool or None"
            )
        if parent_grant is not None:
            effective = _delegation.resolve_effective_ceilings(parent_chain)
            if effective is None:
                raise ActionTransitionError(
                    "Parent ceilings are malformed; cannot derive"
                )
            if not max_risk_level:
                max_risk_level = str(effective.get("max_risk_level", "") or "")
            if not max_timeout_seconds or max_timeout_seconds <= 0:
                filled_timeout = effective.get("max_timeout_seconds", 0)
                max_timeout_seconds = filled_timeout
            if require_verification is None:
                require_verification = effective.get("require_verification", None)
            if not max_side_effect:
                max_side_effect = str(effective.get("max_side_effect", "") or "")

        # Delegator identity is DERIVED from the parent durable binding,
        # never caller-supplied: the holder of the parent authority.
        delegator_grid = str(
            parent.get("expected_governed_registration_id", "") or ""
        )
        delegator_agent = str(
            parent.get("expected_executor_logical_id", "") or ""
        )
        # Root snapshot pins the original ceiling against chain splicing.
        if parent_grant is None:
            root_mission_id = mission_id
            root_action_id = parent_action_id
            root_grid = delegator_grid
            try:
                root_gen = int(parent.get("expected_resource_generation", 0) or 0)
            except (TypeError, ValueError):
                raise ActionTransitionError(
                    "Parent resource generation is malformed"
                )
        else:
            root_mission_id = str(
                parent_grant.get("delegation_root_mission_id", "") or ""
            )
            root_action_id = str(
                parent_grant.get("delegation_root_action_id", "") or ""
            )
            root_grid = str(
                parent_grant.get("delegation_root_governed_registration_id", "")
                or ""
            )
            try:
                root_gen = int(
                    parent_grant.get("delegation_root_generation", 0) or 0
                )
            except (TypeError, ValueError):
                raise ActionTransitionError("Parent root generation is malformed")
            if not root_mission_id or not root_action_id:
                raise ActionTransitionError("Parent root reference is malformed")

        grant = {
            "delegation_id": _delegation.mint_delegation_id(),
            "delegation_parent_mission_id": mission_id,
            "delegation_parent_action_id": parent_action_id,
            "delegation_parent_delegation_id": parent_grant_id,
            "delegation_root_mission_id": root_mission_id,
            "delegation_root_action_id": root_action_id,
            "delegation_root_governed_registration_id": root_grid,
            "delegation_root_generation": root_gen,
            "delegation_delegator_grid": delegator_grid,
            "delegation_delegator_agent_id": delegator_agent,
            "delegation_delegate_agent_id": delegate_agent_id,
            "delegation_delegate_grid": str(
                delegate_governed_registration_id or ""
            ),
            "delegation_allowed_capabilities": list(allowed_capabilities or ()),
            "delegation_allowed_resources": [
                dict(r) if isinstance(r, dict) else r
                for r in (allowed_resources or ())
            ],
            "delegation_allowed_targets": list(allowed_targets or ()),
            "delegation_max_risk_level": str(max_risk_level or ""),
            "delegation_max_timeout_seconds": max_timeout_seconds,
            "delegation_require_verification": require_verification,
            "delegation_max_side_effect": str(max_side_effect or ""),
            "delegation_created_at": now_iso,
            "delegation_expires_at": str(expires_at or ""),
            "delegation_state": "ACTIVE",
            "delegation_revoked_at": "",
            "delegation_revoke_reason": "",
        }
        # Shape validation first (fail fast on malformed proposals),
        # then normalize to the canonical JSON-safe grant mapping.
        try:
            grant = _delegation.DelegationGrant.from_dict(grant).to_dict()
        except _delegation.DelegationError as exc:
            raise ActionTransitionError(
                f"Malformed delegation proposal: {exc}"
            ) from exc

        # Prove child ⊆ parent against the effective parent view.
        parent_view = _delegation.resolve_parent_view(
            parent, self._plan_capability(data, parent_action_id), parent_grant
        )
        if parent_grant is not None:
            # Nested edge: resolve inherit-empty ceilings against the
            # parent effective values so the stored grant is always
            # explicit (handoff re-proof needs no resolution).
            effective = _delegation.resolve_effective_ceilings(parent_chain)
            if effective is None:
                raise ActionTransitionError(
                    "Parent ceilings are malformed; cannot derive"
                )
            filled = dict(grant)
            if not filled["delegation_max_risk_level"]:
                filled["delegation_max_risk_level"] = str(
                    effective.get("max_risk_level", "") or ""
                )
            if (
                not filled["delegation_max_timeout_seconds"]
                or filled["delegation_max_timeout_seconds"] <= 0
            ):
                filled["delegation_max_timeout_seconds"] = effective.get(
                    "max_timeout_seconds", 0
                )
            if filled["delegation_require_verification"] is None:
                filled["delegation_require_verification"] = effective.get(
                    "require_verification", None
                )
            if not filled["delegation_max_side_effect"]:
                filled["delegation_max_side_effect"] = str(
                    effective.get("max_side_effect", "") or ""
                )
            try:
                grant = _delegation.DelegationGrant.from_dict(filled).to_dict()
            except _delegation.DelegationError as exc:
                raise ActionTransitionError(
                    f"Malformed derived delegation: {exc}"
                ) from exc
        child_view = {
            "capability": self._plan_capability(data, child_action_id) or None,
            "resource_id": str(child.get("expected_resource_id", "") or ""),
            "grid": str(child.get("expected_governed_registration_id", "") or ""),
            "generation": child.get("expected_resource_generation", 0),
            "target": str(child.get("expected_resource_id", "") or ""),
        }
        try:
            child_view["generation"] = int(child_view["generation"] or 0)
        except (TypeError, ValueError):
            raise ActionTransitionError("Child resource generation is malformed")
        proved, reason = _delegation.prove_edge(grant, child_view, parent_view)
        if not proved:
            raise ActionTransitionError(
                f"Delegation would escalate authority: {reason}"
            )

        outcome = self._store.transition_delegation_grant(
            mission_id, child_action_id, expected_mission_revision, grant
        )
        if outcome.outcome != "committed":
            raise ActionTransitionError(
                f"Durable delegation commit failed: {outcome.outcome} "
                f"(rev={outcome.revision}): {outcome.reason}"
            )
        reloaded = self._load_data(mission_id)
        current = self._parse_state(
            reloaded.get("action_states", {}).get(child_action_id, {}).get("state"),
            child_action_id,
        )
        return TransitionResult(
            mission_id=mission_id,
            action_id=child_action_id,
            previous_state=current,
            new_state=current,
            mission_revision=durable_revision + 1,
            record=MissionRecord.from_dict(reloaded),
        )

    def revoke_delegation(
        self,
        mission_id: str,
        action_id: str,
        expected_mission_revision: int,
        reason: str = "",
    ) -> TransitionResult:
        """Revoke a delegation grant (ACTIVE -> REVOKED, terminal).

        Already-revoked grants return an idempotent result with no state
        change and no revision bump: retries can never recreate authority
        and history is preserved. Actions without a grant are rejected.
        """
        data = self._load_data(mission_id)
        durable_revision = data.get("revision")
        if durable_revision != expected_mission_revision:
            raise ActionTransitionError(
                f"Durable mission revision is {durable_revision}, "
                f"caller expected {expected_mission_revision}"
            )
        action = self._action(data, action_id)
        if not (action.get("delegation_id") or ""):
            raise ActionTransitionError(
                f"Action carries no delegation grant: {action_id}"
            )
        current = self._parse_state(action.get("state"), action_id)
        outcome = self._store.transition_delegation_revoke(
            mission_id, action_id, expected_mission_revision, str(reason or "")
        )
        if outcome.outcome == "already_revoked":
            return TransitionResult(
                mission_id=mission_id,
                action_id=action_id,
                previous_state=current,
                new_state=current,
                mission_revision=durable_revision,
                record=MissionRecord.from_dict(data),
            )
        if outcome.outcome != "committed":
            raise ActionTransitionError(
                f"Durable revocation commit failed: {outcome.outcome} "
                f"(rev={outcome.revision}): {outcome.reason}"
            )
        reloaded = self._load_data(mission_id)
        return TransitionResult(
            mission_id=mission_id,
            action_id=action_id,
            previous_state=current,
            new_state=current,
            mission_revision=durable_revision + 1,
            record=MissionRecord.from_dict(reloaded),
        )

    def _plan_capability(self, data: Dict[str, Any], action_id: str) -> str:
        """Plan capability for one action (tolerant; "" when absent)."""
        try:
            for entry in data.get("plan", []) or ():
                if isinstance(entry, dict) and entry.get("action_id") == action_id:
                    return str(entry.get("capability", "") or "")
        except (TypeError, AttributeError):
            pass
        return ""

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

        # M33.2B: a revoked, expired, or otherwise invalid delegation
        # can never dispatch, regardless of action state. Direct callers
        # of decide_replay get the same verdict as the guard path.
        if (action.get("delegation_id") or "") != "":
            from intent_kernel.mission import delegation as _delegation
            _ok, _reason, _chain = _delegation.verify_grant_dispatch(
                data,
                action_id,
                presenter_executor_id=None,
                now_iso=utc_iso(),
            )
            if not _ok:
                return ReplayDecision.DO_NOT_REDISPATCH

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
