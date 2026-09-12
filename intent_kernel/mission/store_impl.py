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

from intent_kernel.mission.mission_record import MissionRecord, detach_json_value
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

    def commit(self, expected_revision: int, record: MissionRecord) -> DurableCommitResult:
        """Atomically commit a MissionRecord update with durable anchoring.

        Loads the CURRENT durable record immediately before commit and
        requires: file exists; durable revision == expected_revision;
        candidate revision == expected_revision + 1; immutable mission
        identity unchanged (mission/installation/runtime/digest/definition/
        plan/created_at). Detects sequential/restart stale writers. No
        silent retry, no last-writer-wins, no mutation before durability.
        """
        with self._lock:
            self._check_poisoned()

            if not isinstance(record, MissionRecord):
                raise MissionRecordValidationError("Invalid candidate state type")
            # Validate candidate (structure, enums, digest, installation).
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
            self._require_immutable_identity(record, durable_data)

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
        self, record: MissionRecord, durable_data: Dict[str, Any]
    ) -> None:
        """Reject candidates that change mission meaning under the same ID."""
        candidate = record.to_dict()
        for field in self._IMMUTABLE_IDENTITY_FIELDS:
            if candidate.get(field) != durable_data.get(field):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
                )
        # mission_definition and plan content are frozen by the contract:
        # compare canonical forms, not object identity.
        for field in ("mission_definition", "plan"):
            if detach_json_value(candidate.get(field)) != detach_json_value(
                durable_data.get(field)
            ):
                raise MissionRecordValidationError(
                    f"Immutable mission identity field changed: {field}"
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