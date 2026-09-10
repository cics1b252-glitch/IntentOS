"""M32A — JSON File RRM Authority State Store.

Implements MODEL_F2: single authority file at ~/.intent-os/rrm/authority.json

Atomic commit protocol:
1. serialize validated candidate
2. write temporary file in same directory/filesystem
3. flush
4. fsync temporary file
5. os.replace(temp, authority.json)
6. perform parent-directory durability flush where safely supported

Windows: Do NOT claim stronger power-loss durability than actual APIs provide.
Atomic replacement is required. Directory fsync may remain PLATFORM_BOUNDED.
No database.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from intent_kernel.rrm.models import (
    ActiveGovernedIdentityRecord,
    DurableCommitOutcome,
    DurableCommitResult,
    DurableFirstGovernanceRecord,
    DurableRRMState,
)
from intent_kernel.rrm.models import (
    ActiveGovernedIdentityRecord as AGIR,
    DurableFirstGovernanceRecord as DFGR,
    DurableRRMState,
    DurableCommitOutcome,
    DurableCommitResult,
    DurableCommitOutcome,
)
from intent_kernel.rrm.ports import RRMStateStorePort
from intent_kernel.rrm.models import (
    ResourceTombstone,
    ResourceLineageConsumption,
    DurableFirstGovernanceRecord,
    ActiveGovernedIdentityRecord,
)
from intent_kernel.rrm.models import ResourceTombstone, ResourceLineageConsumption, DurableFirstGovernanceRecord, ActiveGovernedIdentityRecord
from intent_kernel.rrm.models import ResourceType, ResourceStatus, is_valid_generation
from intent_kernel.time_utils import utc_iso
import uuid


class JsonFileRRMStateStore:
    """M32A — JSON File RRM Authority State Store (MODEL_F2).

    Single authority file at ~/.intent-os/rrm/authority.json
    Atomic commit with revision-based optimistic locking.
    """

    # Platform durability bounds
    PLATFORM_WINDOWS = os.name == "nt"

    def __init__(
        self,
        authority_file: Optional[Path] = None,
        continuity_file: Optional[Path] = None,
    ) -> None:
        # Default authority file: ~/.intent-os/rrm/authority.json
        if authority_file is None:
            home = Path.home()
            self._authority_file = home / ".intent-os" / "rrm" / "authority.json"
        else:
            self._authority_file = authority_file

        # Continuity identity file: ~/.intent-os/continuity/identity.json
        if continuity_file is None:
            home = Path.home()
            self._continuity_file = home / ".intent-os" / "continuity" / "identity.json"
        else:
            self._continuity_file = continuity_file

        # Ensure parent directories exist
        self._authority_file.parent.mkdir(parents=True, exist_ok=True)
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
            raise RuntimeError(f"RRM authority store poisoned: {self._poison_reason}")

    # --- Load / Commit ---

    def load(self) -> Optional[Dict[str, Any]]:
        """Load durable RRM authority state from file.

        Returns None if file does not exist (cold start).
        Raises on corruption / validation failure.
        """
        with self._lock:
            self._check_poisoned()

            if not self._authority_file.exists():
                return None

            try:
                with open(self._authority_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Corrupt authority file: invalid JSON: {e}") from e
            except OSError as e:
                raise ValueError(f"Cannot read authority file: {e}") from e

            # Validate structure
            self._validate_loaded_state(data)
            return data

    def commit(
        self,
        expected_revision: int,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Atomically commit new durable state with revision check.

        P2 protocol step 5-6: verify expected_revision, then atomic commit.
        Returns the commit result dict (outcome, revision, reason).
        """
        with self._lock:
            self._check_poisoned()

            # Validate candidate state
            self._validate_candidate_state(state)

            # Revision check: candidate must have revision = expected_revision + 1
            current_revision = state.get("revision", 0)
            expected_candidate_revision = expected_revision + 1
            if current_revision != expected_candidate_revision:
                return {
                    "outcome": "revision_mismatch",
                    "revision": current_revision,
                    "reason": f"Expected candidate revision {expected_candidate_revision}, got {current_revision}",
                }

            # Compare against the actual durable revision, not just the candidate.
            # The store lock serializes this single-process writer.
            durable = self.load()
            durable_revision = durable["revision"] if durable is not None else 0
            if durable_revision != expected_revision:
                return {
                    "outcome": "revision_mismatch",
                    "revision": durable_revision,
                    "reason": f"Expected durable revision {expected_revision}, got {durable_revision}",
                }

            # Atomic write: temp file → flush → fsync → os.replace
            temp_path = None
            try:
                # Serialize
                json_bytes = json.dumps(
                    state,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")

                # Write to temp file in same directory
                dir_path = self._authority_file.parent
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=dir_path,
                    prefix=".authority.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp:
                    tmp.write(json_bytes)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    temp_path = Path(tmp.name)

                # Atomic replace
                os.replace(temp_path, self._authority_file)

                # Platform-bounded directory durability
                self._sync_parent_directory()

                return {
                    "outcome": "committed",
                    "revision": state["revision"],
                    "reason": "",
                }

            except OSError as e:
                # Cleanup temp file on failure
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                return {
                    "outcome": "io_error",
                    "revision": state.get("revision", 0),
                    "reason": f"I/O error during commit: {e}",
                }
            except Exception as e:
                # Cleanup temp file on failure
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                return {
                    "outcome": "validation_failed",
                    "revision": state.get("revision", 0),
                    "reason": f"Unexpected error: {e}",
                }

    # --- Validation ---

    def _validate_loaded_state(self, data: Dict[str, Any]) -> None:
        """Validate loaded authority state (fail closed on corruption)."""
        # Empty file
        if not data:
            raise ValueError("Empty authority file")

        # Required top-level fields
        required_fields = ["schema_version", "installation_id", "revision",
                          "tombstones", "consumptions", "first_governances", "active_governed"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Schema version
        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise ValueError(f"Invalid schema_version: {schema_version}")

        # Installation ID
        installation_id = data.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id.strip():
            raise ValueError("installation_id must be non-empty string")

        # Revision
        revision = data.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError(f"Invalid revision: {revision}")

        # Installation identity continuity check
        continuity_id = self._load_continuity_identity()
        if installation_id != continuity_id:
            # Allow mismatch only if no authority state existed before (fresh install)
            # but here we're loading existing state, so it must match
            raise ValueError(
                f"Installation identity mismatch: authority has {installation_id}, "
                f"continuity has {continuity_id}"
            )

        # Validate tombstones
        self._validate_tombstones(data.get("tombstones", []))

        # Validate consumptions
        self._validate_consumptions(data.get("consumptions", []))

        # Validate first-governance records
        self._validate_first_governances(data.get("first_governances", []))

        # Validate active governed
        self._validate_active_governed(data.get("active_governed", []))

        # Cross-validation: tombstone/active conflicts
        self._validate_tombstone_active_consistency(
            data.get("tombstones", []),
            data.get("active_governed", []),
        )

        # Cross-validation: consumption/active consistency
        self._validate_consumption_active_consistency(
            data.get("consumptions", []),
            data.get("active_governed", []),
        )

    def _validate_candidate_state(self, state: Dict[str, Any]) -> None:
        """Validate candidate state before commit (same as load validation)."""
        # Same validation as loaded state
        self._validate_loaded_state(state)

    def _validate_tombstones(self, tombstones: List[Dict[str, Any]]) -> None:
        seen = set()
        for ts in tombstones:
            # Required fields
            for field in ["resource_kind", "resource_id", "governed_registration_id", "observed_generation"]:
                if field not in ts:
                    raise ValueError(f"Tombstone missing field: {field}")

            # Validate types
            if not isinstance(ts["resource_kind"], str):
                raise ValueError("Tombstone resource_kind must be string")
            try:
                ResourceType(ts["resource_kind"])
            except ValueError:
                raise ValueError(f"Invalid resource_kind: {ts['resource_kind']}")

            if not isinstance(ts["resource_id"], str) or not ts["resource_id"].strip():
                raise ValueError("Tombstone resource_id must be non-empty string")
            if not isinstance(ts["governed_registration_id"], str) or not ts["governed_registration_id"].strip():
                raise ValueError("Tombstone governed_registration_id must be non-empty string")
            if not isinstance(ts["observed_generation"], int) or isinstance(ts["observed_generation"], bool):
                raise ValueError("Tombstone observed_generation must be int")
            if not is_valid_generation(ts["observed_generation"]):
                raise ValueError(f"Invalid observed_generation: {ts['observed_generation']}")

            # Duplicate lineage check
            key = (ts["resource_kind"], ts["resource_id"], ts["governed_registration_id"])
            if key in seen:
                raise ValueError(f"Duplicate tombstone lineage: {key}")
            seen.add(key)

    def _validate_consumptions(self, consumptions: List[Dict[str, Any]]) -> None:
        seen = set()
        for c in consumptions:
            required = ["resource_kind", "resource_id", "predecessor_governed_registration_id",
                       "predecessor_observed_generation", "successor_governed_registration_id",
                       "successor_candidate_proposal_id", "successor_candidate_decision_id",
                       "successor_materialization_descriptor"]
            for field in required:
                if field not in c:
                    raise ValueError(f"Consumption missing field: {field}")

            if not isinstance(c["resource_kind"], str):
                raise ValueError("Consumption resource_kind must be string")
            try:
                ResourceType(c["resource_kind"])
            except ValueError:
                raise ValueError(f"Invalid resource_kind: {c['resource_kind']}")

            if not isinstance(c["resource_id"], str) or not c["resource_id"].strip():
                raise ValueError("Consumption resource_id must be non-empty string")
            if not isinstance(c["predecessor_governed_registration_id"], str) or not c["predecessor_governed_registration_id"].strip():
                raise ValueError("Consumption predecessor_governed_registration_id must be non-empty")
            if not isinstance(c["predecessor_observed_generation"], int) or isinstance(c["predecessor_observed_generation"], bool):
                raise ValueError("Consumption predecessor_observed_generation must be int")
            if not is_valid_generation(c["predecessor_observed_generation"]):
                raise ValueError(f"Invalid predecessor_observed_generation: {c['predecessor_observed_generation']}")
            if not isinstance(c["successor_governed_registration_id"], str) or not c["successor_governed_registration_id"].strip():
                raise ValueError("Consumption successor_governed_registration_id must be non-empty")
            if not isinstance(c["successor_candidate_proposal_id"], str) or not c["successor_candidate_proposal_id"].strip():
                raise ValueError("Consumption successor_candidate_proposal_id must be non-empty")
            if not isinstance(c["successor_candidate_decision_id"], str) or not c["successor_candidate_decision_id"].strip():
                raise ValueError("Consumption successor_candidate_decision_id must be non-empty")
            if not isinstance(c["successor_materialization_descriptor"], dict):
                raise ValueError("Consumption successor_materialization_descriptor must be dict")

            key = (c["resource_kind"], c["resource_id"], c["predecessor_governed_registration_id"])
            if key in seen:
                raise ValueError(f"Duplicate consumption lineage: {key}")
            seen.add(key)

    def _validate_first_governances(self, first_governances: List[Dict[str, Any]]) -> None:
        seen = set()
        for fg in first_governances:
            required = ["resource_kind", "resource_id", "proposal_id", "decision_id",
                       "governed_registration_id", "resulting_generation"]
            for field in required:
                if field not in fg:
                    raise ValueError(f"First-governance missing field: {field}")

            if not isinstance(fg["resource_kind"], str):
                raise ValueError("First-governance resource_kind must be string")
            try:
                ResourceType(fg["resource_kind"])
            except ValueError:
                raise ValueError(f"Invalid resource_kind: {fg['resource_kind']}")

            if not isinstance(fg["resource_id"], str) or not fg["resource_id"].strip():
                raise ValueError("First-governance resource_id must be non-empty string")
            if not isinstance(fg["proposal_id"], str) or not fg["proposal_id"].strip():
                raise ValueError("First-governance proposal_id must be non-empty string")
            if not isinstance(fg["decision_id"], str) or not fg["decision_id"].strip():
                raise ValueError("First-governance decision_id must be non-empty string")
            if not isinstance(fg["governed_registration_id"], str) or not fg["governed_registration_id"].strip():
                raise ValueError("First-governance governed_registration_id must be non-empty string")
            if not isinstance(fg["resulting_generation"], int) or isinstance(fg["resulting_generation"], bool):
                raise ValueError("First-governance resulting_generation must be int")

            # Validate generation
            from intent_kernel.rrm.models import is_valid_generation
            if not is_valid_generation(fg["resulting_generation"]):
                raise ValueError(f"Invalid resulting_generation: {fg['resulting_generation']}")

            key = (fg["resource_kind"], fg["resource_id"])
            if key in seen:
                raise ValueError(f"Duplicate first-governance for resource: {key}")
            seen.add(key)

    def _validate_active_governed(self, active_governed: List[Dict[str, Any]]) -> None:
        seen = set()
        for ag in active_governed:
            required = ["resource_kind", "resource_id", "governed_registration_id", "generation", "status"]
            for field in required:
                if field not in ag:
                    raise ValueError(f"Active governed missing field: {field}")

            if not isinstance(ag["resource_kind"], str):
                raise ValueError("Active governed resource_kind must be string")
            try:
                ResourceType(ag["resource_kind"])
            except ValueError:
                raise ValueError(f"Invalid resource_kind: {ag['resource_kind']}")

            if not isinstance(ag["resource_id"], str) or not ag["resource_id"].strip():
                raise ValueError("Active governed resource_id must be non-empty string")
            if not isinstance(ag["governed_registration_id"], str) or not ag["governed_registration_id"].strip():
                raise ValueError("Active governed governed_registration_id must be non-empty string")
            if not isinstance(ag["generation"], int) or isinstance(ag["generation"], bool):
                raise ValueError("Active governed generation must be int")
            if not is_valid_generation(ag["generation"]):
                raise ValueError(f"Invalid generation: {ag['generation']}")
            try:
                ResourceStatus(ag["status"])
            except ValueError:
                raise ValueError(f"Invalid ResourceStatus: {ag['status']}")

            key = (ag["resource_kind"], ag["resource_id"])
            if key in seen:
                raise ValueError(f"Duplicate active governed identity: {key}")
            seen.add(key)

    def _validate_tombstone_active_consistency(
        self, tombstones: List[Dict[str, Any]], active_governed: List[Dict[str, Any]]
    ) -> None:
        """A tombstone for a lineage and an active governed for the same (kind, id, grid) cannot coexist."""
        tombstone_keys = {(ts["resource_kind"], ts["resource_id"], ts["governed_registration_id"])
                          for ts in tombstones}
        active_keys = {(ag["resource_kind"], ag["resource_id"], ag["governed_registration_id"])
                       for ag in active_governed}
        conflicts = tombstone_keys & active_keys
        if conflicts:
            raise ValueError(f"Tombstone/active conflict for lineages: {conflicts}")

    def _validate_consumption_active_consistency(
        self, consumptions: List[Dict[str, Any]], active_governed: List[Dict[str, Any]]
    ) -> None:
        """A consumption for a predecessor lineage and an active governed for the same
        (kind, id, predecessor_grid) cannot coexist (predecessor consumed)."""
        consumption_keys = {(c["resource_kind"], c["resource_id"], c["predecessor_governed_registration_id"])
                           for c in consumptions}
        # Note: active governed key is (kind, id, grid) where grid is the CURRENT grid
        # A consumption for predecessor_grid means that predecessor is consumed.
        # If there's an active with the SAME grid as the predecessor, that's a conflict.
        active_by_grid = {(ag["resource_kind"], ag["resource_id"], ag["governed_registration_id"])
                          for ag in active_governed}
        conflicts = consumption_keys & active_by_grid
        if conflicts:
            raise ValueError(f"Consumption/active conflict: predecessor still active for {conflicts}")

    def _sync_parent_directory(self) -> None:
        """Best-effort parent directory fsync for durability.

        PLATFORM_BOUNDED: Windows does not support directory fsync via standard APIs.
        On Unix, fsync the parent directory to ensure the rename is durable.
        """
        if self.PLATFORM_WINDOWS:
            # Windows: no standard directory fsync; rely on atomic replace
            return

        try:
            dir_fd = os.open(str(self._authority_file.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Best effort; ignore failures
            pass

    # --- Migration Support ---

    def has_prior_installation_evidence(self) -> bool:
        """Inspect only this explicitly configured installation, without creating identity."""
        if self._continuity_file.exists():
            return True
        install_root = self._continuity_file.parent.parent
        for name in ("pkb", "missions", "logs", "ame_memory"):
            path = install_root / name
            if path.is_file() or (path.is_dir() and any(path.iterdir())):
                return True
        return False

    def initialize_fresh(self) -> Dict[str, Any]:
        """Create initial clean authority state ready for first commit (revision 1).

        The returned state has revision 1 because the first commit will verify
        that the candidate revision = expected_revision + 1 = 0 + 1 = 1.
        Uses the store's continuity identity.
        """
        installation_id = self.get_continuity_identity()
        return {
            "schema_version": 1,
            "installation_id": installation_id,
            "revision": 1,
            "tombstones": [],
            "consumptions": [],
            "first_governances": [],
            "active_governed": [],
        }

    def create_from_live_rrm(
        self,
        installation_id: str,
        tombstones: List[Dict[str, Any]],
        consumptions: List[Dict[str, Any]],
        first_governances: List[Dict[str, Any]],
        active_governed: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create durable state from live RRM snapshot (live migration)."""
        state = {
            "schema_version": 1,
            "installation_id": installation_id,
            "revision": 1,
            "tombstones": tombstones,
            "consumptions": consumptions,
            "first_governances": first_governances,
            "active_governed": active_governed,
        }
        self._validate_loaded_state(state)
        return state

    def is_poisoned_state(self) -> bool:
        return self._poisoned

    def get_poison_reason(self) -> str:
        return self._poison_reason


def create_json_file_rrm_state_store(
    authority_file: Optional[str] = None,
    continuity_file: Optional[str] = None,
) -> 'JsonFileRRMStateStore':
    """Factory function for JsonFileRRMStateStore."""
    af = Path(authority_file) if authority_file else None
    cf = Path(continuity_file) if continuity_file else None
    return JsonFileRRMStateStore(authority_file=af, continuity_file=cf)