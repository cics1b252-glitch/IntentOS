"""JSON File MissionRecord Store — M32B Durable Mission Authority.

MODEL_F1 — One mission file per mission.
File: ~/.intent-os/missions/{mission_id}.json

Atomic commit with revision-based optimistic locking.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from intent_kernel.mission.mission_record import MissionRecord, ActionState, detach_json_value
from intent_kernel.mission.delegation import confirmation_basis_for_grant
from intent_kernel.mission.execution_identity import (
    compute_local_execution_identity,
)
from intent_kernel.mission.transitions import (
    is_legal_action_transition,
)
from intent_kernel.mission.store import (
    DurableCommitResult,
    MissionRecordStorePort,
    MissionRecordValidationError,
)
from intent_kernel.time_utils import utc_iso


SUPPORTED_MISSION_SCHEMA_VERSION = 1


class JsonFileMissionRecordStore(MissionRecordStorePort):
    """M32B — JSON File MissionRecord Store (MODEL_F1).

    Single mission file per mission at ~/.intent-os/missions/{mission_id}.json
    Atomic commit with durable-anchored revision checking.

    CONCURRENCY BOUNDARY (M32B-1): same-process access is serialized by an
    internal lock and sequential stale writers are detected by comparing
    against the durable record loaded immediately before commit. Truly
    simultaneous multiprocess writers are UNSUPPORTED and outside the
    contract — this store does NOT claim cross-process compare-and-swap.
    No file locking is used.
    """

    # Platform durability bounds
    PLATFORM_WINDOWS = os.name == "nt"

    def __init__(
        self,
        missions_dir: Optional[Path] = None,
        continuity_file: Optional[Path] = None,
    ) -> None:
        # Default missions dir: ~/.intent-os/missions/
        if missions_dir is None:
            home = Path.home()
            self._missions_dir = home / ".intent-os" / "missions"
        else:
            self._missions_dir = Path(missions_dir)

        # Continuity identity file: ~/.intent-os/continuity/identity.json
        if continuity_file is None:
            home = Path.home()
            self._continuity_file = home / ".intent-os" / "continuity" / "identity.json"
        else:
            self._continuity_file = Path(continuity_file)

        # Ensure parent directories exist
        self._missions_dir.mkdir(parents=True, exist_ok=True)
        self._continuity_file.parent.mkdir(parents=True, exist_ok=True)

        # In-memory lock for single-process single-writer guarantee
        self._lock = threading.RLock()

        # In-memory continuity identity (loaded on demand)
        self._continuity_identity: Optional[str] = None

        # Poison state for post-commit memory failure
        self._poisoned = False
        self._poison_reason: str = ""

    # --- Continuity Identity ---

    def _load_continuity_identity(self) -> str:
        """Load or create continuity identity."""
        if self._continuity_identity is not None:
            return self._continuity_identity

        if self._continuity_file.exists():
            try:
                with open(self._continuity_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                identity = data.get("installation_id", "")
                if identity:
                    self._continuity_identity = identity
                    return identity
            except (json.JSONDecodeError, OSError, KeyError):
                pass

        # Generate new identity
        import uuid
        identity = f"install-{uuid.uuid4().hex[:16]}"
        try:
            self._continuity_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._continuity_file, "w", encoding="utf-8") as f:
                json.dump({"installation_id": identity, "created_at": utc_iso()}, f)
            os.replace(str(self._continuity_file) + ".tmp", self._continuity_file)
        except OSError:
            pass
        self._continuity_identity = identity
        return identity

    def get_continuity_identity(self) -> str:
        """Get the continuity installation identity."""
        return self._load_continuity_identity()

    # --- Poison / Fail-Stop ---

    def is_poisoned(self) -> bool:
        return self._poisoned

    def poison(self, reason: str) -> None:
        """Permanently poison the store — all subsequent operations fail."""
        self._poisoned = True
        self._poison_reason = reason

    def _check_poisoned(self) -> None:
        if self._poisoned:
            raise RuntimeError(f"MissionRecord store poisoned: {self._poison_reason}")

    # --- Mission File Resolution ---

    def _mission_file(self, mission_id: str) -> Path:
        """Resolve the canonical F1 file for a mission_id, fail closed.

        Rejects empty/whitespace IDs and anything that could escape the
        missions directory (separators, parent traversal, absolute paths,
        drive prefixes). Verifies the resolved path stays contained.
        """
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise MissionRecordValidationError("mission_id must be non-empty string")
        if (
            "/" in mission_id
            or "\\" in mission_id
            or ".." in mission_id
            or ":" in mission_id
            or mission_id != mission_id.strip()
        ):
            raise MissionRecordValidationError(
                f"mission_id escapes missions directory: {mission_id!r}"
            )
        candidate = self._missions_dir / f"{mission_id}.json"
        try:
            resolved_base = self._missions_dir.resolve()
            resolved_candidate = candidate.resolve()
        except OSError as exc:
            raise MissionRecordValidationError(
                f"mission_id cannot be resolved safely: {mission_id!r}: {exc}"
            ) from exc
        if resolved_candidate.parent != resolved_base:
            raise MissionRecordValidationError(
                f"mission_id escapes missions directory: {mission_id!r}"
            )
        return candidate

    def _require_digest_match(self, record: MissionRecord) -> None:
        """Verify the carried digest equals the deterministic recomputation.

        The digest must be derived from the canonical immutable mission
        definition representation (sorted-keys JSON, SHA-256). Timestamps,
        object ids, and process-local values are never part of it unless
        explicitly present in mission semantics.
        """
        expected = record.compute_definition_digest()
        if record.mission_definition_digest != expected:
            raise MissionRecordValidationError(
                "mission_definition_digest does not match "
                "mission_definition content"
            )

    def _expected_identity(
        self, data: Dict[str, Any], action_id: str
    ) -> str:
        """Recompute the MODEL E2 identity from file content itself.

        Raises when the action has no identifiable plan entry (no request
        digest): unidentifiable actions cannot carry bound identity.
        """
        request_digest = ""
        for entry in data.get("plan", []):
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                request_digest = entry.get("request_semantics_digest", "")
                break
        if not isinstance(request_digest, str) or not request_digest:
            raise MissionRecordValidationError(
                f"No identifiable plan entry for action: {action_id}"
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

    def _require_identity_match(
        self, data: Dict[str, Any], action_id: str, identity: str
    ) -> None:
        """Enforce a bound local_execution_identity against recomputation."""
        if not identity:
            return
        if identity != self._expected_identity(data, action_id):
            raise MissionRecordValidationError(
                f"local_execution_identity mismatch for action: {action_id}"
            )

    # --- Load / Create / Commit ---

    def exists(self, mission_id: str) -> bool:
        """Check whether a canonical mission file exists (no content read)."""
        with self._lock:
            self._check_poisoned()
            return self._mission_file(mission_id).exists()

    def load(self, mission_id: str) -> Optional[Any]:
        """Load durable MissionRecord from file.

        Returns None if file does not exist (cold start / NON_RESUMABLE).
        Raises on corruption / validation failure.
        """
        with self._lock:
            self._check_poisoned()

            mission_file = self._mission_file(mission_id)
            if not mission_file.exists():
                return None

            try:
                with open(mission_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                raise MissionRecordValidationError(f"Corrupt mission file: invalid JSON: {e}") from e
            except OSError as e:
                raise MissionRecordValidationError(f"Cannot read mission file: {e}") from e

            # Validate structure
            self._validate_loaded_state(data)
            return data

    def create(self, record: MissionRecord) -> DurableCommitResult:
        """Create a new MissionRecord at revision 1.

        Fails closed (already_exists) if the durable mission file already
        exists — never overwrites, truncates, or resets existing authority.
        """
        with self._lock:
            self._check_poisoned()

            if not isinstance(record, MissionRecord):
                raise MissionRecordValidationError("Invalid candidate state type")
            if record.revision != 1:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=record.revision,
                    reason="Create requires candidate revision 1, "
                    f"got {record.revision}",
                )
            # Validate candidate (structure, enums, digest, installation).
            self._validate_candidate_state(record)

            mission_file = self._mission_file(record.mission_id)
            if mission_file.exists():
                return DurableCommitResult(
                    outcome="already_exists",
                    revision=record.revision,
                    reason=f"Mission already exists: {record.mission_id}",
                )

            return self._atomic_write(record)

    def commit(
        self,
        expected_revision: int,
        record: MissionRecord,
    ) -> DurableCommitResult:
        """Atomically commit a MissionRecord update with durable anchoring.

        Loads the CURRENT durable record immediately before commit and
        requires: file exists; durable revision == expected_revision;
        candidate revision == expected_revision + 1; immutable mission
        identity unchanged (mission/installation/runtime/digest/definition/
        plan/created_at). Detects sequential/restart stale writers. No
        silent retry, no last-writer-wins, no mutation before durability.

        Ordinary commit cannot mutate confirmation fields — use
        transition_confirmation() for canonical MissionActionAuthority
        transitions.
        """
        return self._do_commit(expected_revision, record, False)

    def transition_confirmation(
        self,
        mission_id: str,
        action_id: str,
        expected_revision: int,
        expected_action_state: ActionState,
        target_action_state: ActionState,
        confirmation_required: bool,
        confirmation_basis_digest: str,
    ) -> DurableCommitResult:
        """Canonical confirmation-state transition.

        Only MissionActionAuthority may call this. The store loads the
        authoritative durable state, verifies the action state transition
        is legal, applies the specific confirmation field changes, and commits.
        The caller does not supply a full candidate record or arbitrary field updates.
        """
        with self._lock:
            self._check_poisoned()

            mission_file = self._mission_file(mission_id)
            if not mission_file.exists():
                return DurableCommitResult(
                    outcome="not_found",
                    revision=0,
                    reason=f"No durable mission to update: {mission_id}",
                )

            try:
                with open(mission_file, "r", encoding="utf-8") as f:
                    durable_data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                raise MissionRecordValidationError(
                    f"Cannot anchor commit: durable mission unreadable: {exc}"
                ) from exc
            self._validate_loaded_state(durable_data)

            durable_revision = durable_data.get("revision")
            if durable_revision != expected_revision:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=durable_revision,
                    reason=f"Durable revision is {durable_revision}, "
                    f"writer expected {expected_revision}",
                )

            # Verify action exists
            durable_actions = durable_data.get("action_states", {})
            if action_id not in durable_actions:
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Action not found: {action_id}",
                )

            durable_action = durable_actions[action_id]
            durable_state = durable_action.get("state")

            # Verify current state matches expected
            if durable_state != expected_action_state.value:
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Durable action state is {durable_state}, caller expected {expected_action_state.value}",
                )

            # Verify transition is legal
            if not is_legal_action_transition(expected_action_state, target_action_state):
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Illegal action transition: {expected_action_state.value} -> {target_action_state.value}",
                )

            # Enforce transition-specific confirmation field semantics
            self._validate_confirmation_transition(
                expected_action_state, target_action_state,
                durable_action, confirmation_required, confirmation_basis_digest
            )

            # Build candidate record with the transition applied
            candidate_data = dict(durable_data)
            candidate_data["revision"] = expected_revision + 1
            candidate_data["updated_at"] = utc_iso()

            # Apply state and confirmation field changes to the specific action
            candidate_actions = dict(candidate_data["action_states"])
            candidate_action = dict(durable_action)
            candidate_action["state"] = target_action_state.value
            candidate_action["confirmation_required"] = confirmation_required
            candidate_action["confirmation_basis_digest"] = confirmation_basis_digest
            candidate_actions[action_id] = candidate_action
            candidate_data["action_states"] = candidate_actions

            try:
                candidate_record = MissionRecord.from_dict(candidate_data)
            except (ValueError, KeyError, TypeError) as exc:
                raise MissionRecordValidationError(
                    f"Invalid transition candidate: {exc}"
                ) from exc

            self._validate_candidate_state(candidate_record)
            self._require_immutable_identity(candidate_record, durable_data, True)
            self._validate_transition(candidate_record, durable_data)
            # M33.2B §8: a confirmation bound on a delegated action must
            # carry the canonical delegation-bound digest.
            self._require_delegation_confirmation_basis(
                candidate_record.to_dict(), action_id
            )

            return self._atomic_write(candidate_record)

    def _validate_confirmation_transition(
        self,
        current_state: ActionState,
        target_state: ActionState,
        durable_action: Dict[str, Any],
        confirmation_required: bool,
        confirmation_basis_digest: str,
    ) -> None:
        """Enforce exact confirmation field semantics per transition.

        For each confirmation-related transition, verify the exact required
        before/after values. For all other transitions, confirmation fields
        must remain unchanged.
        """
        durable_confirmation_required = bool(durable_action.get("confirmation_required", False))
        durable_confirmation_basis = durable_action.get("confirmation_basis_digest", "")

        # PENDING -> RECONFIRMATION_REQUIRED: must SET confirmation_required=True and non-empty basis
        if (current_state is ActionState.PENDING and target_state is ActionState.RECONFIRMATION_REQUIRED):
            if confirmation_required is not True:
                raise MissionRecordValidationError(
                    f"PENDING -> RECONFIRMATION_REQUIRED requires confirmation_required=True, "
                    f"got {confirmation_required}"
                )
            if not confirmation_basis_digest or not isinstance(confirmation_basis_digest, str):
                raise MissionRecordValidationError(
                    "PENDING -> RECONFIRMATION_REQUIRED requires a non-empty confirmation_basis_digest"
                )

        # RECONFIRMATION_REQUIRED -> AUTHORIZED: must CLEAR both fields
        elif (current_state is ActionState.RECONFIRMATION_REQUIRED and target_state is ActionState.AUTHORIZED):
            if confirmation_required is not False:
                raise MissionRecordValidationError(
                    f"RECONFIRMATION_REQUIRED -> AUTHORIZED requires confirmation_required=False, "
                    f"got {confirmation_required}"
                )
            if confirmation_basis_digest != "":
                raise MissionRecordValidationError(
                    "RECONFIRMATION_REQUIRED -> AUTHORIZED requires empty confirmation_basis_digest"
                )

        # RECONFIRMATION_REQUIRED -> FAILED: must CLEAR both fields (action failed, no confirmation needed)
        elif (current_state is ActionState.RECONFIRMATION_REQUIRED and target_state is ActionState.FAILED):
            if confirmation_required is not False:
                raise MissionRecordValidationError(
                    f"RECONFIRMATION_REQUIRED -> FAILED requires confirmation_required=False, "
                    f"got {confirmation_required}"
                )
            if confirmation_basis_digest != "":
                raise MissionRecordValidationError(
                    "RECONFIRMATION_REQUIRED -> FAILED requires empty confirmation_basis_digest"
                )

        # All other transitions: confirmation fields must remain UNCHANGED
        else:
            if confirmation_required != durable_confirmation_required:
                raise MissionRecordValidationError(
                    f"Transition {current_state.value} -> {target_state.value} must not change "
                    f"confirmation_required (durable: {durable_confirmation_required}, "
                    f"requested: {confirmation_required})"
                )
            if confirmation_basis_digest != durable_confirmation_basis:
                raise MissionRecordValidationError(
                    f"Transition {current_state.value} -> {target_state.value} must not change "
                    f"confirmation_basis_digest (durable: '{durable_confirmation_basis}', "
                    f"requested: '{confirmation_basis_digest}')"
                )

    # --- Delegation transitions (M33.2B) ---

    #: Delegation fields protected from ordinary commit(); only the
    #: canonical delegation transitions below may mutate them — the same
    #: hardening pattern as confirmation fields (M32B-3).
    _DELEGATION_PROTECTED_FIELDS = (
        "delegation_id",
        "delegation_parent_mission_id",
        "delegation_parent_action_id",
        "delegation_parent_delegation_id",
        "delegation_root_mission_id",
        "delegation_root_action_id",
        "delegation_root_governed_registration_id",
        "delegation_root_generation",
        "delegation_delegator_grid",
        "delegation_delegator_agent_id",
        "delegation_delegate_agent_id",
        "delegation_delegate_grid",
        "delegation_allowed_capabilities",
        "delegation_allowed_resources",
        "delegation_allowed_targets",
        "delegation_max_risk_level",
        "delegation_max_timeout_seconds",
        "delegation_require_verification",
        "delegation_max_side_effect",
        "delegation_created_at",
        "delegation_expires_at",
        "delegation_state",
        "delegation_revoked_at",
        "delegation_revoke_reason",
    )

    def transition_delegation_grant(
        self,
        mission_id: str,
        action_id: str,
        expected_revision: int,
        grant: Dict[str, Any],
    ) -> DurableCommitResult:
        """Attach a delegation grant to one action (M33.2B).

        Only MissionActionAuthority may call this. The store loads the
        authoritative durable state, verifies the action carries no grant
        yet, validates the grant shape, applies the delegation fields (and
        rebinds the confirmation basis to the canonical delegated digest
        when the action requires confirmation), and commits revision
        N -> N+1. The caller does not supply a full candidate record.
        """
        with self._lock:
            self._check_poisoned()

            if not isinstance(grant, dict) or not grant.get("delegation_id"):
                raise MissionRecordValidationError(
                    "Delegation grant must be a mapping with delegation_id"
                )
            try:
                with open(self._mission_file(mission_id), "r", encoding="utf-8") as f:
                    durable_data = json.load(f)
            except FileNotFoundError:
                return DurableCommitResult(
                    outcome="not_found",
                    revision=0,
                    reason=f"No durable mission to update: {mission_id}",
                )
            except (json.JSONDecodeError, OSError) as exc:
                raise MissionRecordValidationError(
                    f"Cannot anchor commit: durable mission unreadable: {exc}"
                ) from exc
            self._validate_loaded_state(durable_data)

            durable_revision = durable_data.get("revision")
            if durable_revision != expected_revision:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=durable_revision,
                    reason=f"Durable revision is {durable_revision}, "
                    f"writer expected {expected_revision}",
                )

            durable_actions = durable_data.get("action_states", {})
            if action_id not in durable_actions:
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Action not found: {action_id}",
                )
            durable_action = durable_actions[action_id]
            if (durable_action.get("delegation_id") or "") != "":
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Action already carries a delegation grant: {action_id}",
                )

            candidate_data = dict(durable_data)
            candidate_data["revision"] = expected_revision + 1
            candidate_data["updated_at"] = utc_iso()
            candidate_actions = dict(candidate_data["action_states"])
            candidate_action = dict(durable_action)
            for key, value in grant.items():
                if key in self._DELEGATION_PROTECTED_FIELDS:
                    candidate_action[key] = detach_json_value(value)
            candidate_action["delegation_state"] = "ACTIVE"
            # M33.2B §8: granting rebinds an outstanding confirmation
            # requirement to the delegated semantics. Approvals issued
            # before the grant (bound to non-delegated semantics) can
            # never satisfy the new basis.
            if candidate_action.get("confirmation_required") is True:
                candidate_action["confirmation_basis_digest"] = (
                    self._canonical_delegation_basis(candidate_data, action_id)
                )
            candidate_actions[action_id] = candidate_action
            candidate_data["action_states"] = candidate_actions

            try:
                candidate_record = MissionRecord.from_dict(candidate_data)
            except (ValueError, KeyError, TypeError) as exc:
                raise MissionRecordValidationError(
                    f"Invalid delegation candidate: {exc}"
                ) from exc

            self._validate_candidate_state(candidate_record)
            self._require_action_unchanged_except_delegation(
                candidate_record, durable_data, action_id
            )
            return self._atomic_write(candidate_record)

    def transition_delegation_revoke(
        self,
        mission_id: str,
        action_id: str,
        expected_revision: int,
        reason: str = "",
    ) -> DurableCommitResult:
        """Revoke a delegation grant (M33.2B: ACTIVE -> REVOKED, terminal).

        Only MissionActionAuthority may call this. Already-revoked grants
        return an explicit already_revoked outcome with no state change
        and no revision bump (idempotent without recreating authority).
        History is preserved: revocation never deletes the grant.
        """
        with self._lock:
            self._check_poisoned()

            try:
                with open(self._mission_file(mission_id), "r", encoding="utf-8") as f:
                    durable_data = json.load(f)
            except FileNotFoundError:
                return DurableCommitResult(
                    outcome="not_found",
                    revision=0,
                    reason=f"No durable mission to update: {mission_id}",
                )
            except (json.JSONDecodeError, OSError) as exc:
                raise MissionRecordValidationError(
                    f"Cannot anchor commit: durable mission unreadable: {exc}"
                ) from exc
            self._validate_loaded_state(durable_data)

            durable_revision = durable_data.get("revision")
            if durable_revision != expected_revision:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=durable_revision,
                    reason=f"Durable revision is {durable_revision}, "
                    f"writer expected {expected_revision}",
                )

            durable_actions = durable_data.get("action_states", {})
            if action_id not in durable_actions:
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Action not found: {action_id}",
                )
            durable_action = durable_actions[action_id]
            if not (durable_action.get("delegation_id") or ""):
                return DurableCommitResult(
                    outcome="validation_failed",
                    revision=durable_revision,
                    reason=f"Action carries no delegation grant: {action_id}",
                )
            if durable_action.get("delegation_state") == "REVOKED":
                return DurableCommitResult(
                    outcome="already_revoked",
                    revision=durable_revision,
                    reason=f"Delegation already revoked: {action_id}",
                )

            candidate_data = dict(durable_data)
            candidate_data["revision"] = expected_revision + 1
            candidate_data["updated_at"] = utc_iso()
            candidate_actions = dict(candidate_data["action_states"])
            candidate_action = dict(durable_action)
            candidate_action["delegation_state"] = "REVOKED"
            candidate_action["delegation_revoked_at"] = utc_iso()
            candidate_action["delegation_revoke_reason"] = str(reason or "")
            candidate_actions[action_id] = candidate_action
            candidate_data["action_states"] = candidate_actions

            try:
                candidate_record = MissionRecord.from_dict(candidate_data)
            except (ValueError, KeyError, TypeError) as exc:
                raise MissionRecordValidationError(
                    f"Invalid revocation candidate: {exc}"
                ) from exc

            self._validate_candidate_state(candidate_record)
            self._require_action_unchanged_except_delegation(
                candidate_record, durable_data, action_id
            )
            return self._atomic_write(candidate_record)

    def _require_action_unchanged_except_delegation(
        self,
        record: MissionRecord,
        durable_data: Dict[str, Any],
        changed_action_id: str,
    ) -> None:
        """Scope a delegation transition's blast radius.

        Mission identity, plan, and every OTHER action must be
        byte-identical (normalized); the changed action may differ only
        in delegation fields (plus the confirmation basis, which the
        canonical delegation-bound digest rule governs separately).
        """
        candidate = record.to_dict()
        for field in self._IMMUTABLE_IDENTITY_FIELDS:
            if candidate.get(field) != durable_data.get(field):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
                )
        for field in ("mission_definition", "plan"):
            if detach_json_value(candidate.get(field)) != detach_json_value(
                durable_data.get(field)
            ):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
                )
        durable_actions = durable_data.get("action_states", {})
        candidate_actions = candidate.get("action_states", {})
        if set(candidate_actions) != set(durable_actions):
            raise MissionRecordValidationError("Immutable action set changed")
        for aid, durable_action in durable_actions.items():
            candidate_action = candidate_actions.get(aid)
            if not isinstance(candidate_action, dict):
                raise MissionRecordValidationError(
                    f"Immutable action missing: {aid}"
                )
            if aid != changed_action_id:
                if detach_json_value(candidate_action) != detach_json_value(
                    durable_action
                ):
                    raise MissionRecordValidationError(
                        f"Delegation transition touched unrelated action: {aid}"
                    )
            else:
                for key in candidate_action:
                    if key in self._DELEGATION_PROTECTED_FIELDS:
                        continue
                    if key in ("confirmation_basis_digest",):
                        continue
                    if detach_json_value(candidate_action.get(key)) != detach_json_value(
                        durable_action.get(key)
                    ):
                        raise MissionRecordValidationError(
                            f"Delegation transition changed non-delegation field: "
                            f"{aid}.{key}"
                        )
                for key in durable_action:
                    if (
                        key not in self._DELEGATION_PROTECTED_FIELDS
                        and key != "confirmation_basis_digest"
                        and key not in candidate_action
                    ):
                        raise MissionRecordValidationError(
                            f"Delegation transition dropped field: {aid}.{key}"
                        )

    def _canonical_delegation_basis(
        self, candidate_data: Dict[str, Any], action_id: str
    ) -> str:
        """Canonical confirmation basis bound to delegated semantics.

        M33.2B §8: recomputed from the CANDIDATE (plan capability +
        action triple + grant fields), so a confirmation issued for a
        different delegate, delegation, target, resource, capability,
        or lifetime can never satisfy it.
        """
        actions = candidate_data.get("action_states", {})
        action = actions.get(action_id, {})
        grant_capability = ""
        for entry in candidate_data.get("plan", []) or ():
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                grant_capability = str(entry.get("capability", "") or "")
                break
        return confirmation_basis_for_grant(
            delegation_id=str(action.get("delegation_id", "") or ""),
            delegate_agent_id=str(action.get("delegation_delegate_agent_id", "") or ""),
            capability=grant_capability,
            governed_registration_id=str(
                action.get("expected_governed_registration_id", "") or ""
            ),
            generation=action.get("expected_resource_generation", 0),
            target=str(action.get("expected_resource_id", "") or ""),
            expires_at=str(action.get("delegation_expires_at", "") or ""),
        )

    def _require_delegation_confirmation_basis(
        self, candidate_data: Dict[str, Any], action_id: str
    ) -> None:
        """Enforce delegation-bound confirmation basis on granted actions.

        Whenever a granted action carries confirmation_required=True, its
        basis must equal the canonical digest bound to the delegated
        semantics — whether the basis is set by the grant transition or
        by a later confirmation transition.
        """
        action = (candidate_data.get("action_states", {}) or {}).get(action_id, {})
        if not isinstance(action, dict):
            return
        if not (action.get("delegation_id") or ""):
            return
        if action.get("confirmation_required") is not True:
            return
        expected = self._canonical_delegation_basis(candidate_data, action_id)
        if action.get("confirmation_basis_digest", "") != expected:
            raise MissionRecordValidationError(
                f"Action {action_id}: confirmation basis on a delegated "
                "action must bind the delegated semantics"
            )

    def _do_commit(
        self,
        expected_revision: int,
        record: MissionRecord,
        allow_confirmation: bool,
    ) -> DurableCommitResult:
        with self._lock:
            self._check_poisoned()

            if not isinstance(record, MissionRecord):
                raise MissionRecordValidationError("Invalid candidate state type")
            self._validate_candidate_state(record)

            mission_file = self._mission_file(record.mission_id)
            if not mission_file.exists():
                return DurableCommitResult(
                    outcome="not_found",
                    revision=record.revision,
                    reason=f"No durable mission to update: {record.mission_id}",
                )

            try:
                with open(mission_file, "r", encoding="utf-8") as f:
                    durable_data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                raise MissionRecordValidationError(
                    f"Cannot anchor commit: durable mission unreadable: {exc}"
                ) from exc
            self._validate_loaded_state(durable_data)

            durable_revision = durable_data.get("revision")
            if durable_revision != expected_revision:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=record.revision,
                    reason=f"Durable revision is {durable_revision}, "
                    f"writer expected {expected_revision}",
                )
            if record.revision != expected_revision + 1:
                return DurableCommitResult(
                    outcome="revision_mismatch",
                    revision=record.revision,
                    reason=f"Expected candidate revision {expected_revision + 1}, "
                    f"got {record.revision}",
                )
            self._require_immutable_identity(record, durable_data, allow_confirmation)
            if allow_confirmation:
                self._validate_transition(record, durable_data)

            return self._atomic_write(record)

    # --- Immutable Identity ---

    #: Fields frozen across revisions; only evolving mission state may change.
    _IMMUTABLE_IDENTITY_FIELDS = (
        "mission_id",
        "installation_id",
        "schema_version",
        "runtime_id",
        "mission_definition_digest",
        "created_at",
    )

    def _require_immutable_identity(
        self, record: MissionRecord, durable_data: Dict[str, Any],
        allow_confirmation: bool = False,
    ) -> None:
        """Reject candidates that change mission meaning under the same ID."""
        candidate = record.to_dict()
        for field in self._IMMUTABLE_IDENTITY_FIELDS:
            if candidate.get(field) != durable_data.get(field):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
                )
        for field in ("mission_definition", "plan"):
            if detach_json_value(candidate.get(field)) != detach_json_value(
                durable_data.get(field)
            ):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
                )
        durable_actions = durable_data.get("action_states", {})
        candidate_actions = candidate.get("action_states", {})
        if set(candidate_actions) != set(durable_actions):
            raise MissionRecordValidationError(
                "Immutable action set changed"
            )
        for aid, durable_action in durable_actions.items():
            candidate_action = candidate_actions.get(aid)
            if not isinstance(candidate_action, dict):
                raise MissionRecordValidationError(
                    f"Immutable action missing: {aid}"
                )
            for field in (
                "node_id",
                "expected_resource_id",
                "expected_governed_registration_id",
                "expected_resource_generation",
                "expected_executor_kind",
                "expected_executor_logical_id",
            ):
                if candidate_action.get(field) != durable_action.get(field):
                    raise MissionRecordValidationError(
                        f"Immutable action identity field changed: "
                        f"{aid}.{field}"
                    )
            durable_ident = durable_action.get("local_execution_identity", "") or ""
            candidate_ident = candidate_action.get(
                "local_execution_identity", "") or ""
            if durable_ident:
                if candidate_ident != durable_ident:
                    raise MissionRecordValidationError(
                        f"Immutable action identity field changed: "
                        f"{aid}.local_execution_identity"
                    )
            elif candidate_ident:
                self._require_identity_match(
                    durable_data, aid, candidate_ident
                )
            # M32B-3: confirmation fields are security-sensitive and
            # may ONLY be modified through transition_confirmation(),
            # which is the sole canonical mechanism held by
            # MissionActionAuthority. Ordinary commit() always
            # rejects confirmation field changes.
            if not allow_confirmation:
                for confirm_field in (
                    "confirmation_required",
                    "confirmation_basis_digest",
                ):
                    if candidate_action.get(confirm_field) != durable_action.get(confirm_field):
                        raise MissionRecordValidationError(
                            f"Confirmation field {aid}.{confirm_field} "
                            "may only be modified through "
                            "transition_confirmation()"
                        )
            # M33.2B: delegation fields are security-sensitive and may
            # ONLY be modified through transition_delegation_grant() /
            # transition_delegation_revoke(). Ordinary commit() always
            # rejects delegation field changes (normalized comparison so
            # tuple/list representation drift can never read as a change).
            for delegation_field in self._DELEGATION_PROTECTED_FIELDS:
                if detach_json_value(
                    candidate_action.get(delegation_field)
                ) != detach_json_value(durable_action.get(delegation_field)):
                    raise MissionRecordValidationError(
                        f"Delegation field {aid}.{delegation_field} "
                        "may only be modified through the canonical "
                        "delegation transitions"
                    )

    def _validate_transition(
        self, candidate: MissionRecord, durable_data: Dict[str, Any],
    ) -> None:
        """Enforce legitimate confirmation transition contract.

        Called only by transition_confirmation(). Validates that:
        - confirmation_required=True has a non-empty basis digest;
        - confirmation_required=False has an empty basis digest;
        - each action's state transition is legal per ACTION_TRANSITIONS.
        """
        candidate_actions = candidate.to_dict().get("action_states", {})
        durable_actions = durable_data.get("action_states", {})
        for aid, candidate_action in candidate_actions.items():
            durable_action = durable_actions.get(aid)
            if durable_action is None:
                continue
            # Confirmation field consistency
            confirm_required = candidate_action.get("confirmation_required")
            confirm_basis = candidate_action.get("confirmation_basis_digest", "")
            if confirm_required is True and (not confirm_basis or not isinstance(confirm_basis, str)):
                raise MissionRecordValidationError(
                    f"Action {aid}: confirmation_required=True requires "
                    "a non-empty confirmation_basis_digest"
                )
            if confirm_required is False and confirm_basis:
                raise MissionRecordValidationError(
                    f"Action {aid}: confirmation_required=False must have "
                    "an empty confirmation_basis_digest"
                )
            # State transition legality
            candidate_state = candidate_action.get("state")
            durable_state = durable_action.get("state")
            if durable_state and candidate_state and durable_state != candidate_state:
                try:
                    dur_state_enum = ActionState(durable_state)
                    cand_state_enum = ActionState(candidate_state)
                except (ValueError, KeyError):
                    raise MissionRecordValidationError(
                        f"Action {aid}: invalid state value"
                    )
                if not is_legal_action_transition(dur_state_enum, cand_state_enum):
                    raise MissionRecordValidationError(
                        f"Action {aid}: illegal state transition "
                        f"{durable_state} -> {candidate_state}"
                    )

    def _atomic_write(self, record: MissionRecord) -> DurableCommitResult:
        """Atomic file replacement: temp file → flush → fsync → os.replace.

        Only invoked after all authority checks pass. On write failure the
        previous durable record remains authoritative; the store holds no
        process-local mission state to advance, so nothing is published.
        """
        # Atomic write: temp file → flush → fsync → os.replace
        temp_path = None
        try:
            # Serialize (fully detached bytes)
            json_bytes = json.dumps(
                record.to_dict(),
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

            # Write to temp file in same directory
            dir_path = self._missions_dir
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=dir_path,
                prefix=f".mission.{record.mission_id}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(json_bytes)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_path = Path(tmp.name)

            # Atomic replace
            mission_file = self._mission_file(record.mission_id)
            os.replace(temp_path, mission_file)

            # Platform-bounded directory durability
            self._sync_parent_directory()

            return DurableCommitResult(
                outcome="committed",
                revision=record.revision,
                reason="",
            )

        except OSError as e:
            # Cleanup temp file on failure
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return DurableCommitResult(
                outcome="io_error",
                revision=record.revision,
                reason=f"I/O error during commit: {e}",
            )
        except Exception as e:
            # Cleanup temp file on failure
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return DurableCommitResult(
                outcome="validation_failed",
                revision=record.revision,
                reason=f"Unexpected error: {e}",
            )

    # --- Validation ---

    def _validate_loaded_state(self, data: Dict[str, Any]) -> None:
        """Validate loaded mission state (fail closed on corruption)."""
        # Empty file
        if not data:
            raise MissionRecordValidationError("Empty mission file")

        # Required top-level fields
        required_fields = [
            "schema_version", "installation_id", "revision",
            "mission_id", "runtime_id", "mission_status",
            "plan", "action_states", "completed_nodes", "failed_nodes",
            "verification_state", "completion_state",
            "created_at", "updated_at",
        ]
        for field in required_fields:
            if field not in data:
                raise MissionRecordValidationError(f"Missing required field: {field}")

        # Schema version: exactly one authority; only the supported
        # version is accepted, unknown/future schemas fail closed.
        schema_version = data.get("schema_version")
        if schema_version != SUPPORTED_MISSION_SCHEMA_VERSION:
            raise MissionRecordValidationError(
                f"Unsupported schema_version: {schema_version}"
            )

        # Installation ID
        installation_id = data.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id.strip():
            raise MissionRecordValidationError("installation_id must be non-empty string")

        # Revision
        revision = data.get("revision")
        if not isinstance(revision, int) or revision < 1:
            raise MissionRecordValidationError(f"Invalid revision: {revision}")

        # Installation identity continuity check
        continuity_id = self._load_continuity_identity()
        if installation_id != continuity_id:
            raise MissionRecordValidationError(
                f"Installation identity mismatch: mission has {installation_id}, "
                f"continuity has {continuity_id}"
            )

        # Validate mission_id
        mission_id = data.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise MissionRecordValidationError("mission_id must be non-empty string")

        # Validate runtime_id
        runtime_id = data.get("runtime_id")
        if not isinstance(runtime_id, str):
            raise MissionRecordValidationError("runtime_id must be string")

        # Validate mission_status
        mission_status = data.get("mission_status")
        try:
            from intent_kernel.mission.mission_record import MissionStatus
            MissionStatus(mission_status)
        except (ValueError, KeyError):
            raise MissionRecordValidationError(f"Invalid mission_status: {mission_status}")

        # Validate plan
        plan = data.get("plan", [])
        if not isinstance(plan, list):
            raise MissionRecordValidationError("plan must be a list")
        for entry in plan:
            if not isinstance(entry, dict):
                raise MissionRecordValidationError("Plan entry must be dict")
            required = ["action_id", "capability", "node_id", "dependencies", "request_semantics_digest"]
            for field in required:
                if field not in entry:
                    raise MissionRecordValidationError(f"Plan entry missing field: {field}")

        # Validate action_states
        action_states = data.get("action_states", {})
        if not isinstance(action_states, dict):
            raise MissionRecordValidationError("action_states must be dict")
        for action_id, state in action_states.items():
            if not isinstance(state, dict):
                raise MissionRecordValidationError(f"Action state for {action_id} must be dict")
            required = ["action_id", "node_id", "state"]
            for field in required:
                if field not in state:
                    raise MissionRecordValidationError(f"Action state {action_id} missing field: {field}")
            try:
                from intent_kernel.mission.mission_record import ActionState
                ActionState(state["state"])
            except (ValueError, KeyError):
                raise MissionRecordValidationError(f"Invalid action state: {state.get('state')}")
            # Bound local execution identity must match recomputation from
            # this same file (MODEL E2). Unbound ("") actions skip.
            self._require_identity_match(
                data, action_id, state.get("local_execution_identity", "") or ""
            )
            # M32B-3 hardening: validate security-significant
            # confirmation fields in candidate state.
            if "confirmation_required" in state:
                if not isinstance(state["confirmation_required"], bool):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: confirmation_required must be bool"
                    )
            if "confirmation_basis_digest" in state:
                if not isinstance(state["confirmation_basis_digest"], str):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: confirmation_basis_digest must be str"
                    )
            if state.get("confirmation_required") is True:
                basis = state.get("confirmation_basis_digest", "")
                if not basis or not isinstance(basis, str):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: confirmation_required=True "
                        "requires non-empty confirmation_basis_digest"
                    )
            # M33.2B hardening: delegation field types on raw loaded state.
            # (Completeness — all-or-nothing grant shape — is enforced by
            # DurableActionState.__post_init__ via from_dict.)
            for label in (
                "delegation_id",
                "delegation_parent_mission_id",
                "delegation_parent_action_id",
                "delegation_parent_delegation_id",
                "delegation_root_mission_id",
                "delegation_root_action_id",
                "delegation_root_governed_registration_id",
                "delegation_delegator_grid",
                "delegation_delegator_agent_id",
                "delegation_delegate_agent_id",
                "delegation_delegate_grid",
                "delegation_max_risk_level",
                "delegation_max_side_effect",
                "delegation_created_at",
                "delegation_expires_at",
                "delegation_state",
                "delegation_revoked_at",
                "delegation_revoke_reason",
            ):
                if label in state and not isinstance(state[label], str):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: {label} must be str"
                    )
            if "delegation_root_generation" in state and (
                not isinstance(state["delegation_root_generation"], int)
                or isinstance(state["delegation_root_generation"], bool)
            ):
                raise MissionRecordValidationError(
                    f"Action state {action_id}: delegation_root_generation "
                    "must be an int"
                )
            if "delegation_max_timeout_seconds" in state and (
                not isinstance(state["delegation_max_timeout_seconds"], (int, float))
                or isinstance(state["delegation_max_timeout_seconds"], bool)
            ):
                raise MissionRecordValidationError(
                    f"Action state {action_id}: delegation_max_timeout_seconds "
                    "must be numeric"
                )
            if "delegation_require_verification" in state and (
                state["delegation_require_verification"] is not None
                and not isinstance(state["delegation_require_verification"], bool)
            ):
                raise MissionRecordValidationError(
                    f"Action state {action_id}: delegation_require_verification "
                    "must be a bool or None"
                )
            for label in (
                "delegation_allowed_capabilities",
                "delegation_allowed_resources",
                "delegation_allowed_targets",
            ):
                if label in state and not isinstance(state[label], (list, tuple)):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: {label} must be a sequence"
                    )
            if "delegation_state" in state and state["delegation_state"] not in (
                "NONE",
                "ACTIVE",
                "REVOKED",
            ):
                raise MissionRecordValidationError(
                    f"Action state {action_id}: delegation_state must be "
                    "NONE, ACTIVE, or REVOKED"
                )
            # M33.2B: a durable grant must be complete, not partial. A
            # delegation_id with missing scope/identity fields is corrupt
            # state and fails load loudly (handoff enforcement re-proves
            # the same shape, but corruption must not travel that far).
            if isinstance(state.get("delegation_id"), str) and state.get(
                "delegation_id"
            ):
                for label in (
                    "delegation_parent_mission_id",
                    "delegation_parent_action_id",
                    "delegation_root_mission_id",
                    "delegation_root_action_id",
                    "delegation_delegator_grid",
                    "delegation_delegate_agent_id",
                ):
                    if not state.get(label) or not isinstance(
                        state.get(label), str
                    ):
                        raise MissionRecordValidationError(
                            f"Action state {action_id}: partial delegation "
                            f"grant is corrupt ({label} missing)"
                        )
                caps = state.get("delegation_allowed_capabilities", [])
                if (
                    not isinstance(caps, (list, tuple))
                    or not caps
                    or not all(isinstance(c, str) and c for c in caps)
                ):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: partial delegation "
                        "grant is corrupt (capabilities missing)"
                    )
                resources = state.get("delegation_allowed_resources", [])
                if not isinstance(resources, (list, tuple)) or not resources:
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: partial delegation "
                        "grant is corrupt (resources missing)"
                    )
                if state.get("delegation_state") not in ("ACTIVE", "REVOKED"):
                    raise MissionRecordValidationError(
                        f"Action state {action_id}: granted delegation_state "
                        "must be ACTIVE or REVOKED"
                    )

        # Validate completed_nodes / failed_nodes
        for field in ["completed_nodes", "failed_nodes"]:
            val = data.get(field, [])
            if not isinstance(val, list):
                raise MissionRecordValidationError(f"{field} must be a list")
            for item in val:
                if not isinstance(item, str):
                    raise MissionRecordValidationError(f"{field} items must be strings")

        # Validate verification_state
        verification_state = data.get("verification_state", {})
        if not isinstance(verification_state, dict):
            raise MissionRecordValidationError("verification_state must be dict")
        for k, v in verification_state.items():
            if not isinstance(v, dict):
                raise MissionRecordValidationError(f"Verification state for {k} must be dict")
            if "verification_status" not in v:
                raise MissionRecordValidationError(f"Verification state for {k} missing verification_status")

        # Validate completion_state
        completion_state = data.get("completion_state", {})
        if not isinstance(completion_state, dict):
            raise MissionRecordValidationError("completion_state must be dict")
        if "completion_state" not in completion_state:
            raise MissionRecordValidationError("completion_state missing completion_state field")

    def _validate_candidate_state(self, state: Any) -> None:
        """Validate candidate state before commit (same as loaded state).

        Also verifies the carried digest is deterministically derived from
        the candidate definition — the store never carries an unchecked digest.
        """
        if isinstance(state, MissionRecord):
            # Convert to dict and validate
            self._validate_loaded_state(state.to_dict())
            self._require_digest_match(state)
        elif isinstance(state, dict):
            self._validate_loaded_state(state)
            try:
                record = MissionRecord.from_dict(detach_json_value(state))
            except (ValueError, KeyError, TypeError) as exc:
                raise MissionRecordValidationError(
                    f"Invalid candidate record: {exc}"
                ) from exc
            self._require_digest_match(record)
        else:
            raise MissionRecordValidationError("Invalid candidate state type")

    # --- Validation Helpers ---

    def _sync_parent_directory(self) -> None:
        """Best-effort parent directory fsync for durability.

        PLATFORM_BOUNDED: Windows does not support directory fsync via standard APIs.
        On Unix, fsync the parent directory to ensure the rename is durable.
        """
        if self.PLATFORM_WINDOWS:
            # Windows: no standard directory fsync; rely on atomic replace
            return

        try:
            dir_fd = os.open(str(self._missions_dir), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Best effort; ignore failures
            pass

    # --- Poison State ---

    def is_poisoned_state(self) -> bool:
        return self._poisoned

    def get_poison_reason(self) -> str:
        return self._poison_reason


def create_json_file_mission_record_store(
    missions_dir: Optional[str] = None,
    continuity_file: Optional[str] = None,
) -> JsonFileMissionRecordStore:
    """Factory function for JsonFileMissionRecordStore."""
    md = Path(missions_dir) if missions_dir else None
    cf = Path(continuity_file) if continuity_file else None
    return JsonFileMissionRecordStore(missions_dir=md, continuity_file=cf)