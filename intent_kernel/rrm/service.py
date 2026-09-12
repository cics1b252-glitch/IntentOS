"""Registry & Resource Manager (RRM) — Core Implementation (RFC-0013).

Provides thread-safe canonical storage, indexing, lookup, status tracking, and query capabilities
for Providers, Accounts, Execution Environments, Capabilities, Agents, and Projects.
"""

from __future__ import annotations

import dataclasses
import datetime
import threading
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from intent_kernel.rrm.models import (
    AccountResource,
    ActiveGovernedIdentityRecord,
    AgentInstallationState,
    AgentResource,
    AccountSnapshot,
    AgentSnapshot,
    AvailabilitySource,
    CapabilityResource,
    CapabilitySnapshot,
    ConditionalCreateOutcome,
    ConditionalCreateResult,
    ConditionalRegistrationRequest,
    ConditionalResourceStatusRequest,
    ConditionalRetirementOutcome,
    ConditionalRetirementRequest,
    ConditionalRetirementResult,
    ConditionalUpdateOutcome,
    ConditionalUpdateResult,
    DurableFirstGovernanceRecord,
    DurableRRMState,
    DurableCommitOutcome,
    DurableCommitResult,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentSnapshot,
    ExecutionEnvironmentType,
    FirstGovernanceOutcome,
    FirstGovernanceRequest,
    FirstGovernanceResult,
    ProjectResource,
    ProjectSnapshot,
    ProviderResource,
    ProviderSnapshot,
    ResourceHealthReport,
    ResourceLineageConsumption,
    ResourceOrigin,
    ResourceQueryFilter,
    ResourceStatus,
    ResourceTombstone,
    ResourceType,
    RRMRegistryMetrics,
    ConditionalCreateOutcome,
    ConditionalCreateResult,
    ConditionalRegistrationRequest,
    ConditionalResourceStatusRequest,
    ConditionalRetirementOutcome,
    ConditionalRetirementRequest,
    ConditionalRetirementResult,
    ConditionalUpdateOutcome,
    ConditionalUpdateResult,
    FirstGovernanceOutcome,
    FirstGovernanceRequest,
    FirstGovernanceResult,
)
from intent_kernel.rrm.ports import ProjectRegistryPort, ResourceQueryPort, RRMRegistryPort, RRMStateStorePort
from intent_kernel.rrm.persistence import JsonFileRRMStateStore
from intent_kernel.time_utils import utc_iso


def _detach_value(value: Any) -> Any:
    """Recursively clone caller-owned data into fully disconnected structures.

    RA-31.2B1-03: guarantees the canonical mutable object graph shares NO mutable
    container/leaf with the caller input graph. Only the value types actually
    admitted by the canonical resource contracts are copied; any other
    (arbitrary/custom) object is rejected FAIL-CLOSED so that no caller-defined
    executable protocol hook (e.g. __deepcopy__/__reduce__) runs under the RRM
    lock and no caller-owned reference can be smuggled into canonical storage.
    Immutable/effectively-immutable values (str/int/float/bool/bytes, Enum,
    datetime, uuid) are returned as-is — they cannot alias mutable state.
    """
    if value is None or isinstance(value, (str, int, float, bool, bytes, Enum)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, dict):
        return {k: _detach_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_detach_value(v) for v in value)
    if isinstance(value, set):
        return set(_detach_value(v) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_detach_value(v) for v in value)
    raise ValueError(
        "conditional create refuses unsupported value type: "
        f"{type(value).__name__} (must be a plain container or scalar)"
    )


class RegistryResourceManager(RRMRegistryPort, ResourceQueryPort, ProjectRegistryPort):
    """Canonical Registry & Resource Manager (RRM) service implementation."""

    def __init__(
        self,
        populate_defaults: bool = True,
        durable_store: Optional[JsonFileRRMStateStore] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._providers: Dict[str, ProviderResource] = {}
        self._accounts: Dict[str, AccountResource] = {}
        self._environments: Dict[str, ExecutionEnvironmentResource] = {}
        self._capabilities: Dict[str, CapabilityResource] = {}  # keyed by name or capability_id
        self._agents: Dict[str, AgentResource] = {}
        self._projects: Dict[str, ProjectResource] = {}
        self._governed_ids: Set[str] = set()
        # M31.2B-2B: canonical structured tombstone store replacing legacy Set[str].
        # Key: (resource_kind, resource_id, governed_registration_id) → ResourceTombstone
        self._tombstones: Dict[Tuple[ResourceType, str, str], ResourceTombstone] = {}

        # M31.2B-2C: canonical lineage-consumption store. A predecessor lineage is
        # IRREVERSIBLY consumed the moment its ResourceLineageConsumption is
        # recorded — before the successor is visible as active. RRM is the sole
        # governed-lineage-ID authority.
        # Key: (resource_kind, resource_id, predecessor_governed_registration_id)
        #   → ResourceLineageConsumption
        self._consumptions: Dict[Tuple[ResourceType, str, str], Any] = {}

        # M31.3B-1B: canonical first-governance fact store. Keyed by
        # (resource_kind, resource_id) → (proposal_id, decision_id,
        # governed_registration_id, resulting_generation). Written atomically
        # under the RRM lock BEFORE the active resource becomes governed so that
        # an exact retry is idempotent: same lineage, NO second mint, NO further
        # generation advance.
        self._first_governances: Dict[Tuple[ResourceType, str], Tuple[str, str, str, int]] = {}

        # M32B-1: durable provenance of first-governance facts. Keys present in
        # the image loaded from the M32A authority store at initialization.
        # Facts minted in this process (PHASE 2 fresh governance) are NEVER
        # added here, so a same-process second bootstrap_govern still fails
        # closed while a genuine restart reconciliation is recognizable.
        self._durable_loaded_fg_keys: Set[Tuple[ResourceType, str]] = set()

        # M32A: Durable authority state store
        self._durable_store: Optional[JsonFileRRMStateStore] = durable_store
        self._durable_active: Dict[Tuple[ResourceType, str], Dict[str, Any]] = {}
        self._durable_revision: int = 0
        self._poisoned: bool = False
        self._poison_reason: str = ""

        if populate_defaults:
            self.populate_default_catalog()

        # M32A: Load or initialize durable authority state
        if self._durable_store is not None:
            self._load_or_initialize_durable_state()

    # --- M32A: Durable Authority State Methods ---

    def _load_or_initialize_durable_state(self) -> None:
        """Load existing durable state or initialize fresh state.

        COLD PRE-M32 UPGRADE: If continuity identity exists but no authority state,
        FAIL CLOSED — require explicit migration/reset acknowledgement.
        """
        assert self._durable_store is not None

        loaded = self._durable_store.load()
        if loaded is not None:
            # Existing M32A state — load and reconcile
            self._reconcile_durable_state(loaded)
            self._durable_revision = loaded.get("revision", 0)
            return

        # No authority.json — check continuity identity
        # Check if this looks like a pre-M32 installation (has continuity but no authority.json)
        if self._has_pre_m32_artifacts():
            # COLD PRE-M32 UPGRADE — FAIL CLOSED
            raise RuntimeError(
                "COLD PRE-M32 UPGRADE DETECTED: prior installation evidence exists "
                "but no M32A authority state found. Requires explicit migration/reset "
                "acknowledgement. Cannot silently bootstrap new governance."
            )

        # NEW INSTALL — initialize clean authority state
        fresh_state = self._durable_store.initialize_fresh()
        # Persist initial state
        result = self._durable_store.commit(0, fresh_state)
        if result.get("outcome") != "committed":
            raise RuntimeError(f"Failed to initialize fresh authority state: {result.get('reason')}")
        self._durable_revision = result["revision"]

    def _has_pre_m32_artifacts(self) -> bool:
        """Cold startup must never silently replace an existing installation."""
        assert self._durable_store is not None
        return self._durable_store.has_prior_installation_evidence()

    def _reconcile_durable_state(self, loaded: Dict[str, Any]) -> None:
        """Reconcile in-memory state with loaded durable authority state.

        Startup order:
        1. Fresh declarations already loaded via populate_default_catalog
        2. Load durable authority state
        3. Project fresh declarations as pre-governed runtime resources
        3. Reconcile fresh declarations with durable ActiveGovernedIdentityRecord
        4. Preserve exact durable grid/generation/status
        5. Bootstrap only resources that have NEVER been governed
        6. Reject tombstoned logical resources
        7. Preserve successor lineage / consumption state
        """
        # Load tombstones
        self._tombstones.clear()
        for ts_data in loaded.get("tombstones", []):
            ts = ResourceTombstone(
                resource_kind=ResourceType(ts_data["resource_kind"]),
                resource_id=ts_data["resource_id"],
                governed_registration_id=ts_data["governed_registration_id"],
                observed_generation=ts_data["observed_generation"],
            )
            self._tombstones[ts.lineage_identity] = ts

        # Load consumptions
        self._consumptions.clear()
        for c_data in loaded.get("consumptions", []):
            cons = ResourceLineageConsumption(
                resource_kind=ResourceType(c_data["resource_kind"]),
                resource_id=c_data["resource_id"],
                predecessor_governed_registration_id=c_data["predecessor_governed_registration_id"],
                predecessor_observed_generation=c_data["predecessor_observed_generation"],
                successor_governed_registration_id=c_data["successor_governed_registration_id"],
                successor_candidate_proposal_id=c_data["successor_candidate_proposal_id"],
                successor_candidate_decision_id=c_data["successor_candidate_decision_id"],
                successor_materialization_descriptor=c_data.get("successor_materialization_descriptor", {}),
            )
            self._consumptions[cons.consumption_key] = cons

        # Load first-governance records
        self._first_governances.clear()
        for fg_data in loaded.get("first_governances", []):
            key = (ResourceType(fg_data["resource_kind"]), fg_data["resource_id"])
            self._first_governances[key] = (
                fg_data["proposal_id"],
                fg_data["decision_id"],
                fg_data["governed_registration_id"],
                fg_data["resulting_generation"],
            )
        # M32B-1: snapshot durable provenance. Only facts present in this
        # loaded image count as durable-loaded for restart recognition.
        self._durable_loaded_fg_keys = set(self._first_governances.keys())

        # Reconcile active governed identities with in-memory resources
        # Preserve exact durable grid/generation/status
        active_governed = loaded.get("active_governed", [])
        self._durable_active = {
            (ResourceType(record["resource_kind"]), record["resource_id"]): dict(record)
            for record in active_governed
        }
        for ag_data in active_governed:
            resource_kind = ResourceType(ag_data["resource_kind"])
            resource_id = ag_data["resource_id"]
            grid = ag_data["governed_registration_id"]
            generation = ag_data["generation"]
            status = ResourceStatus(ag_data["status"])

            # Find the in-memory resource and update its governed identity
            resource = self._get_resource_for_mutation(resource_kind, resource_id)
            if resource is not None:
                # Preserve exact durable grid/generation/status
                resource.governed_registration_id = grid
                resource.generation = generation
                resource.status = status
            else:
                # Resource not currently in memory but has durable governed identity
                # This is a USER-CREATED ACTIVE IDENTITY WITHOUT DESCRIPTOR
                # Preserve authority as non-executable durable identity placeholder/fact
                # Do NOT fabricate an executable Provider/Agent/Capability/etc.
                pass  # Authority remains reserved; productive binding will fail closed

    def _build_durable_state_snapshot(self) -> Dict[str, Any]:
        """Build complete durable state snapshot for atomic commit (P2 step 3).

        Called under RRM lock. Derives candidate post-state WITHOUT mutating
        canonical memory — only reads current state.
        """
        from intent_kernel.rrm.generation import is_valid_generation
        # Build tombstones
        tombstones = [ts.to_dict() for ts in self._tombstones.values()]

        # Build consumptions
        consumptions = []
        for cons in self._consumptions.values():
            consumptions.append({
                "resource_kind": cons.resource_kind.value,
                "resource_id": cons.resource_id,
                "predecessor_governed_registration_id": cons.predecessor_governed_registration_id,
                "predecessor_observed_generation": cons.predecessor_observed_generation,
                "successor_governed_registration_id": cons.successor_governed_registration_id,
                "successor_candidate_proposal_id": cons.successor_candidate_proposal_id,
                "successor_candidate_decision_id": cons.successor_candidate_decision_id,
                "successor_materialization_descriptor": cons.successor_materialization_descriptor,
            })

        # Build first-governances
        first_governances = []
        for (resource_kind, resource_id), (prop_id, dec_id, grid, gen) in self._first_governances.items():
            first_governances.append({
                "resource_kind": resource_kind.value,
                "resource_id": resource_id,
                "proposal_id": prop_id,
                "decision_id": dec_id,
                "governed_registration_id": grid,
                "resulting_generation": gen,
            })

        # Build active governed identities
        active_by_key = {
            key: dict(record) for key, record in self._durable_active.items()
            if (key[0], key[1], record["governed_registration_id"]) not in self._tombstones
        }
        # Collect from all resource stores
        stores = [
            (ResourceType.PROVIDER, self._providers, "provider_id"),
            (ResourceType.ACCOUNT, self._accounts, "account_id"),
            (ResourceType.EXECUTION_ENVIRONMENT, self._environments, "environment_id"),
            (ResourceType.CAPABILITY, self._capabilities, "capability_id"),
            (ResourceType.AGENT, self._agents, "agent_id"),
            (ResourceType.PROJECT, self._projects, "project_id"),
        ]
        for resource_kind, store, id_field in stores:
            for resource in store.values():
                grid = getattr(resource, "governed_registration_id", "") or ""
                if grid and is_valid_generation(getattr(resource, "generation", 0)):
                    rid = getattr(resource, id_field, "")
                    active_by_key[(resource_kind, rid)] = {
                        "resource_kind": resource_kind.value,
                        "resource_id": rid,
                        "governed_registration_id": grid,
                        "generation": getattr(resource, "generation", 0),
                        "status": resource.status.value,
                    }

        return {
            "schema_version": 1,
            "installation_id": self._durable_store.get_continuity_identity() if self._durable_store else "",
            "revision": self._durable_revision + 1,
            "tombstones": tombstones,
            "consumptions": consumptions,
            "first_governances": first_governances,
            "active_governed": list(active_by_key.values()),
        }

    def _commit_durable_state(self) -> DurableCommitResult:
        """P2 DURABLE-BEFORE-MEMORY PROTOCOL step 5-7.

        1. Acquire RRM lock (already held by caller)
        2. Validate current canonical state (already done by caller)
        3. Derive candidate post-state WITHOUT mutating canonical memory
        4. Validate candidate
        5. Verify expected durable revision
        6. Durable atomic commit candidate
        7. Only after commit succeeds, publish matching in-memory change
           (but memory was already updated before calling this — this is for
           the revision tracking and fail-stop)
        8. Return success

        If durable commit fails: MEMORY_MUTATED=NO (caller must not have mutated yet)
        SUCCESS_RETURNED=NO

        Fail closed.
        """
        if self._durable_store is None:
            return DurableCommitResult(
                outcome=DurableCommitOutcome.COMMITTED,  # No durability required
                revision=self._durable_revision,
                reason="no durable store configured",
            )

        if self._poisoned:
            return DurableCommitResult(
                outcome=DurableCommitOutcome.POISONED,
                revision=self._durable_revision,
                reason=self._poison_reason or "RRM poisoned",
            )

        candidate = self._build_durable_state_snapshot()
        candidate_revision = candidate["revision"]
        expected_revision = self._durable_revision

        # P2 step 5-6: verify expected revision, durable atomic commit
        result = self._durable_store.commit(expected_revision, candidate)
        outcome_str = result.get("outcome", "io_error")
        committed_revision = result.get("revision", self._durable_revision)
        reason = result.get("reason", "")

        if outcome_str == "committed":
            self._durable_revision = committed_revision
            return DurableCommitResult(
                outcome=DurableCommitOutcome.COMMITTED,
                revision=committed_revision,
                reason="",
            )
        elif outcome_str == "revision_mismatch":
            return DurableCommitResult(
                outcome=DurableCommitOutcome.REVISION_MISMATCH,
                revision=committed_revision,
                reason=result.get("reason", "revision mismatch"),
            )
        elif outcome_str == "validation_failed":
            return DurableCommitResult(
                outcome=DurableCommitOutcome.VALIDATION_FAILED,
                revision=committed_revision,
                reason=result.get("reason", "validation failed"),
            )
        elif outcome_str == "io_error":
            return DurableCommitResult(
                outcome=DurableCommitOutcome.IO_ERROR,
                revision=committed_revision,
                reason=result.get("reason", "I/O error"),
            )
        else:
            return DurableCommitResult(
                outcome=DurableCommitOutcome.IO_ERROR,
                revision=committed_revision,
                reason=f"Unknown outcome: {outcome_str}",
            )

    def _poison_rrm(self, reason: str) -> None:
        """Poison the RRM — reject all subsequent authority operations."""
        self._poisoned = True
        self._poison_reason = reason
        if self._durable_store:
            self._durable_store.poison(reason)

    def _check_poisoned(self) -> None:
        if self._poisoned:
            raise RuntimeError(f"RRM poisoned: {self._poison_reason}")

    # --- Provider Operations ---

    def register_provider(self, provider: ProviderResource) -> ProviderResource:
        with self._lock:
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.PROVIDER, provider.provider_id):
                return self._providers.get(provider.provider_id)  # H1.3: reject retired identity
            existing = self._providers.get(provider.provider_id)
            if existing is not None and self._is_governed_resource(provider.provider_id):
                return existing
            self._establish_generation_on_registration(provider, existing)
            provider.updated_at = utc_iso()
            self._providers[provider.provider_id] = provider
            return provider

    def get_provider(self, provider_id: str) -> Optional[ProviderSnapshot]:
        with self._lock:
            self._check_poisoned()
            provider = self._providers.get(provider_id)
            if provider is None:
                return None
            return provider.to_snapshot()

    def has_tombstoned_resource(
        self,
        resource_kind: ResourceType,
        resource_id: str,
    ) -> bool:
        """Public typed read-only tombstone query (B-0 observation surface).

        RA-31.2B2B-09: external observers must NOT inspect the private
        ``_tombstones`` container directly. This is a lock-safe, kind-aware,
        observation-only mechanism that derives from the single canonical
        structured ResourceTombstone store (TS1).

        True iff at least one lineage has
        ``tombstone.resource_kind == resource_kind`` and
        ``tombstone.resource_id == resource_id``.

        Grants NO retirement / re-registration / promotion authority and never
        mutates or exposes the canonical mutable container.
        """
        with self._lock:
            self._check_poisoned()
            return self._is_tombstoned(resource_kind, resource_id)

    def get_resource_tombstone(
        self,
        resource_kind: ResourceType,
        resource_id: str,
        governed_registration_id: str,
    ) -> Optional[ResourceTombstone]:
        """M31.2B-2C — exact-lineage tombstone lookup (read-only).

        Returns the canonical immutable ResourceTombstone whose
        ``(resource_kind, resource_id, governed_registration_id)`` lineage
        identity matches EXACTLY, or None.

        Grants NO re-registration / promotion / retirement authority. This is
        the authoritative predecessor-retirement fact surface used by
        generation-bound re-registration decision authorization.
        """
        with self._lock:
            self._check_poisoned()
            if not isinstance(governed_registration_id, str) or not governed_registration_id:
                return None
            return self._tombstones.get(
                (resource_kind, resource_id, governed_registration_id)
            )

    def _generate_governed_registration_id(
        self,
        resource_kind: ResourceType,
        resource_id: str,
    ) -> str:
        """M31.2B-2C — RRM is the SOLE governed-lineage-ID authority.

        Generates a successor lineage identity for re-registration. The caller
        NEVER supplies a successor lineage; only RRM mints governed lineage IDs.
        Bound to kind + resource identity; unprefixed / unguessable, never
        derived from caller-provided strings.
        """
        from intent_kernel.rrm.models import ResourceType
        kind_str = resource_kind.value.lower() if isinstance(resource_kind, ResourceType) else str(resource_kind)
        return f"gov-{kind_str}-{uuid.uuid4().hex}"

    def _materialize_successor_resource(
        self,
        resource_kind: ResourceType,
        resource_id: str,
        successor_grid: str,
        successor_generation: int,
        descriptor: Dict[str, Any],
    ) -> Optional[Any]:
        """Construct the active successor B resource from the frozen descriptor.

        RRM-internal only — invoked atomically under the RRM lock as WRITE 2 of
        a generation-bound re-registration. Successor lineage ID and generation
        come exclusively from RRM, never from the caller or the descriptor.

        B1 parity note: Project/Account mirror the ordinary-promotion construction
        used for the other families so that all six families share one governed
        re-registration surface.
        """
        from intent_kernel.rrm.models import (
            AccountResource,
            AgentResource,
            AvailabilitySource,
            CapabilityResource,
            ExecutionEnvironmentResource,
            ProviderResource,
            ProjectResource,
            ResourceOrigin,
            ResourceStatus,
        )

        desc = descriptor if isinstance(descriptor, dict) else {}
        display_name = desc.get("display_name", resource_id)
        capabilities = tuple(desc.get("capability_claims", []))

        base_meta: Dict[str, Any] = {
            "promotion_via": "governed_reregistration",
            "canonical_registration_id": successor_grid,
        }

        if resource_kind == ResourceType.PROVIDER:
            return ProviderResource(
                provider_id=resource_id,
                name=display_name,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_configured=False,
                has_active_account=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        if resource_kind == ResourceType.ACCOUNT:
            return AccountResource(
                account_id=resource_id,
                provider_id=desc.get("provider_id", desc.get("parent_id", "")),
                name=display_name,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_configured=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        if resource_kind == ResourceType.EXECUTION_ENVIRONMENT:
            return ExecutionEnvironmentResource(
                environment_id=resource_id,
                type=None,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_discovered=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        if resource_kind == ResourceType.CAPABILITY:
            return CapabilityResource(
                capability_id=resource_id,
                name=display_name,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_executable=False,
                status=ResourceStatus.ACTIVE,
                tags=list(capabilities),
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        if resource_kind == ResourceType.AGENT:
            return AgentResource(
                agent_id=resource_id,
                name=display_name,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_enabled=False,
                installation_state=None,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        if resource_kind == ResourceType.PROJECT:
            return ProjectResource(
                project_id=resource_id,
                name=display_name,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_demo=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=successor_grid,
                generation=successor_generation,
                metadata=base_meta,
            )
        return None

    def _commit_reregistration_successor(
        self, consumption: ResourceLineageConsumption, successor: Any,
        store: Dict[str, Any], id_attr: str,
    ) -> None:
        """Under the RRM lock: commit the exact candidate, then publish memory.

        Reuse the recorded lineage/descriptor on recovery. Any uncertain durable
        or post-commit publication failure poisons authority until restart.
        """
        kind, rid = consumption.resource_kind, consumption.resource_id
        candidate = self._build_durable_state_snapshot()
        candidate["consumptions"] = [
            record for record in candidate["consumptions"]
            if (record["resource_kind"], record["resource_id"],
                record["predecessor_governed_registration_id"]) !=
               (kind.value, rid, consumption.predecessor_governed_registration_id)
        ]
        candidate["consumptions"].append({
            "resource_kind": kind.value,
            "resource_id": rid,
            "predecessor_governed_registration_id": consumption.predecessor_governed_registration_id,
            "predecessor_observed_generation": consumption.predecessor_observed_generation,
            "successor_governed_registration_id": consumption.successor_governed_registration_id,
            "successor_candidate_proposal_id": consumption.successor_candidate_proposal_id,
            "successor_candidate_decision_id": consumption.successor_candidate_decision_id,
            "successor_materialization_descriptor": consumption.successor_materialization_descriptor,
        })
        record = {
            "resource_kind": kind.value, "resource_id": rid,
            "governed_registration_id": successor.governed_registration_id,
            "generation": successor.generation, "status": successor.status.value,
        }
        candidate["active_governed"] = [
            active for active in candidate["active_governed"]
            if (active["resource_kind"], active["resource_id"]) != (kind.value, rid)
        ] + [record]
        if self._durable_store is not None:
            try:
                result = self._durable_store.commit(self._durable_revision, candidate)
                if result.get("outcome") != "committed":
                    raise RuntimeError(f"Durable reregistration failed: {result}")
            except Exception:
                self._poison_rrm("Reregistration durable commit failed")
                raise
        try:
            self._consumptions[consumption.consumption_key] = consumption
            store[getattr(successor, id_attr)] = successor
            if self._durable_store is not None:
                self._durable_active[(kind, rid)] = record
                self._durable_revision = result["revision"]
        except Exception:
            self._poison_rrm("Reregistration memory publication failed after commit")
            raise

    def conditional_reregister_resource(
        self,
        request: "ConditionalReregistrationRequest",
        materialization_descriptor: Optional[Dict[str, Any]] = None,
    ) -> "ConditionalReregistrationResult":
        """M31.2B-2C — RRM-governed generation-bound re-registration.

        M32A P2: Durable-before-memory protocol.

        Executes the frozen MODEL_R2 mutation sequence atomically under the RRM
        lock:

            validate → detach/freeze candidate descriptor → allocate successor
            lineage B → construct consumption(A,B,X) → derive candidate state
            → durable commit candidate → commit → publish canonical changes.

        Exact consumed predecessor = exact approved candidate = exact lineage B.
        Durable commit precedes canonical memory publication.
        RRM is the sole governed-lineage-ID authority; the caller never
        supplies successor lineage or resulting generation.

        Performs NO authorization (the promotion authority decides permission) —
        RRM enforces only state/lifecycle facts. No arbitrary callbacks run
        under the lock.
        """
        from intent_kernel.rrm.models import (
            ConditionalReregistrationOutcome as O,
            ConditionalReregistrationRequest,
            ConditionalReregistrationResult,
            ResourceLineageConsumption,
            ResourceStatus,
            ResourceType,
        )

        with self._lock:
            self._check_poisoned()

            store, id_attr = self._get_store_for_type(request.resource_kind)
            if store is None:
                return ConditionalReregistrationResult(
                    outcome=O.INVALID_RESOURCE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="unsupported_resource_kind",
                )
            if not isinstance(request.resource_id, str) or not request.resource_id.strip():
                return ConditionalReregistrationResult(
                    outcome=O.INVALID_RESOURCE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="blank_resource_id",
                )

            lineage_key = (
                request.resource_kind,
                request.resource_id,
                request.predecessor_governed_registration_id,
            )
            consumption = self._consumptions.get(lineage_key)
            tombstone = self._tombstones.get(lineage_key)

            # ------------------------------------------------------------------
            # PHASE 1: predecessor-retirement fact (fresh re-registration only).
            # ------------------------------------------------------------------
            if consumption is None:
                if tombstone is None:
                    if self._is_tombstoned(
                        request.resource_kind, request.resource_id
                    ):
                        return ConditionalReregistrationResult(
                            outcome=O.TOMBSTONE_LINEAGE_MISMATCH,
                            resource_kind=request.resource_kind,
                            resource_id=request.resource_id,
                            reason="predecessor_lineage_mismatch",
                        )
                    return ConditionalReregistrationResult(
                        outcome=O.NO_TOMBSTONE,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="predecessor_not_retired",
                    )
                if (
                    tombstone.observed_generation
                    != request.predecessor_observed_generation
                ):
                    return ConditionalReregistrationResult(
                        outcome=O.TOMBSTONE_GENERATION_MISMATCH,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="predecessor_generation_mismatch",
                    )

            # ------------------------------------------------------------------
            # PHASE 2: existing consumption → recovery / staleness / applied.
            # ------------------------------------------------------------------
            if consumption is not None:
                if (
                    consumption.successor_candidate_proposal_id
                    != request.proposal_id
                    or consumption.successor_candidate_decision_id
                    != request.decision_id
                ):
                    return ConditionalReregistrationResult(
                        outcome=O.PENDING_SUCCESSOR_MISMATCH,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="pending_successor_mismatch",
                    )

                successor_tombstone_key = (
                    request.resource_kind,
                    request.resource_id,
                    consumption.successor_governed_registration_id,
                )
                if successor_tombstone_key in self._tombstones:
                    return ConditionalReregistrationResult(
                        outcome=O.STALE_RETIRED_LINEAGE,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="successor_already_retired",
                    )

                active = self._get_resource_for_mutation(
                    request.resource_kind, request.resource_id
                )
                if active is not None:
                    active_grid = getattr(
                        active, "governed_registration_id", ""
                    ) or ""
                    if active_grid == consumption.successor_governed_registration_id:
                        return ConditionalReregistrationResult(
                            outcome=O.REREGISTRATION_ALREADY_APPLIED,
                            resource_kind=request.resource_kind,
                            resource_id=request.resource_id,
                            successor_governed_registration_id=active_grid,
                            successor_observed_generation=getattr(
                                active, "generation", 0
                            ),
                            reason="reregistration_already_applied",
                        )
                    return ConditionalReregistrationResult(
                        outcome=O.ACTIVE_RESOURCE_CONFLICT,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="active_resource_conflict",
                    )

                # Recovery: WRITE 1 exists, WRITE 2 missing. Reuse the STORED
                # materialization descriptor (never a retry descriptor).
                stored_descriptor = consumption.successor_materialization_descriptor
                if not isinstance(stored_descriptor, dict) or not stored_descriptor:
                    return ConditionalReregistrationResult(
                        outcome=O.PENDING_SUCCESSOR_MISMATCH,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="missing_materialization_descriptor",
                    )
                successor_grid = consumption.successor_governed_registration_id
                successor_generation = consumption.predecessor_observed_generation + 1
                durable_identity = self._durable_active.get((request.resource_kind, request.resource_id))
                if durable_identity is not None:
                    if durable_identity["governed_registration_id"] != successor_grid:
                        return ConditionalReregistrationResult(
                            outcome=O.ACTIVE_RESOURCE_CONFLICT,
                            resource_kind=request.resource_kind, resource_id=request.resource_id,
                            reason="durable_active_resource_conflict",
                        )
                    successor_generation = durable_identity["generation"]
                successor = self._materialize_successor_resource(
                    request.resource_kind,
                    request.resource_id,
                    successor_grid,
                    successor_generation,
                    stored_descriptor,
                )
                if successor is None:
                    return ConditionalReregistrationResult(
                        outcome=O.INVALID_RESOURCE,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="unsupported_resource_kind",
                    )

                if durable_identity is not None:
                    successor.status = ResourceStatus(durable_identity["status"])
                self._commit_reregistration_successor(
                    consumption, successor, store, id_attr,
                )

                return ConditionalReregistrationResult(
                    outcome=O.REREGISTRATION_RECOVERED,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    successor_governed_registration_id=successor_grid,
                    successor_observed_generation=successor_generation,
                    reason="reregistration_recovered",
                )

            # ------------------------------------------------------------------
            # PHASE 3: fresh re-registration (no consumption yet).
            # ------------------------------------------------------------------
            active = self._get_resource_for_mutation(
                request.resource_kind, request.resource_id
            )
            if active is not None:
                return ConditionalReregistrationResult(
                    outcome=O.ACTIVE_RESOURCE_CONFLICT,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="resource_already_active",
                )

            if not isinstance(materialization_descriptor, dict):
                return ConditionalReregistrationResult(
                    outcome=O.INVALID_RESOURCE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="missing_materialization_descriptor",
                )

            from intent_kernel.rrm.models import _detach_rrm_value

            try:
                frozen_desc = _detach_rrm_value(materialization_descriptor)
            except ValueError:
                return ConditionalReregistrationResult(
                    outcome=O.INVALID_RESOURCE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="unsupported_descriptor_type",
                )

            # RRM enforces lifecycle facts: re-registration into a terminal
            # state is an invalid transition.
            desired_status = frozen_desc.get("status")
            if desired_status is not None:
                try:
                    status_val = (
                        ResourceStatus(desired_status)
                        if isinstance(desired_status, str)
                        else desired_status
                    )
                except ValueError:
                    status_val = None
                if status_val in (
                    ResourceStatus.ARCHIVED,
                    ResourceStatus.UNINSTALLED,
                ):
                    return ConditionalReregistrationResult(
                        outcome=O.INVALID_TRANSITION,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        reason="terminal_successor_state",
                    )

            successor_grid = self._generate_governed_registration_id(
                request.resource_kind, request.resource_id
            )
            successor_generation = request.predecessor_observed_generation + 1

            consumption = ResourceLineageConsumption(
                resource_kind=request.resource_kind,
                resource_id=request.resource_id,
                predecessor_governed_registration_id=(
                    request.predecessor_governed_registration_id
                ),
                predecessor_observed_generation=(
                    request.predecessor_observed_generation
                ),
                successor_governed_registration_id=successor_grid,
                successor_candidate_proposal_id=request.proposal_id,
                successor_candidate_decision_id=request.decision_id,
                successor_materialization_descriptor=frozen_desc,
            )

            successor = self._materialize_successor_resource(
                request.resource_kind, request.resource_id, successor_grid,
                successor_generation, frozen_desc,
            )
            if successor is None:
                return ConditionalReregistrationResult(
                    outcome=O.INVALID_RESOURCE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="unsupported_resource_kind",
                )
            self._commit_reregistration_successor(
                consumption, successor, store, id_attr,
            )

            return ConditionalReregistrationResult(
                outcome=O.REREGISTERED,
                resource_kind=request.resource_kind,
                resource_id=request.resource_id,
                successor_governed_registration_id=successor_grid,
                successor_observed_generation=successor_generation,
                reason="reregistered",
            )

    def conditional_govern_existing_resource(
        self,
        request: FirstGovernanceRequest,
    ) -> FirstGovernanceResult:
        """M31.3B-1B — atomically govern an existing pre-governed resource.

        M32A P2: Durable-before-memory protocol.
        Executes the typed first-governance mutation in a SINGLE critical
        section under ``self._lock``:

            validate → locate → pre-governed lineage check (grid == "")
            → expected pre-governed generation check → RRM-internal lineage
            mint → record governance fact (WRITE 1) → apply governed identity
            + generation N+1 (WRITE 2) → detached immutable result.

        RRM is the SOLE governed-lineage-ID authority and the caller supplies
        NEITHER a new governed registration lineage NOR a resulting generation:
        the governing grid is minted internally via
        ``_generate_governed_registration_id`` and the resulting generation is
        ALWAYS ``expected_pre_governed_generation + 1``.

        Retries are idempotent: an exact same-decision retry returns
        ALREADY_APPLIED_SAME_DECISION with the STORED lineage and generation —
        never a second mint and never a further generation advance. A retry
        whose fact was recorded but whose active write is missing (recovery
        window) is completed with the STORED lineage/generation, never a retry
        mint.

        M32A P2: Durable-before-memory protocol. Durable commit precedes memory mutation.
        Performs NO authorization (the bootstrap decision authority decides
        permission) — RRM enforces only state/lifecycle facts. No arbitrary
        callbacks run under the lock.
        """
        from intent_kernel.rrm.models import (
            ResourceStatus,
            FirstGovernanceOutcome as O,
        )

        with self._lock:
            self._check_poisoned()

            store, _id_attr = self._get_store_for_type(request.resource_kind)
            if store is None:
                return FirstGovernanceResult(
                    outcome=O.INVALID_STATE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="unsupported_resource_kind",
                )
            if not request.expected_ungoverned_lineage:
                return FirstGovernanceResult(
                    outcome=O.INVALID_STATE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="ungoverned_lineage_expected",
                )

            key = (request.resource_kind, request.resource_id)
            record = self._first_governances.get(key)
            existing = store.get(request.resource_id)

            # ------------------------------------------------------------------
            # PHASE 1: recorded first-governance fact → idempotent retry/recovery.
            # ------------------------------------------------------------------
            if record is not None:
                rec_prop, rec_dec, rec_grid, rec_gen = record
                if (rec_prop, rec_dec) == (request.proposal_id, request.decision_id):
                    if existing is None:
                        return FirstGovernanceResult(
                            outcome=O.NOT_FOUND,
                            resource_kind=request.resource_kind,
                            resource_id=request.resource_id,
                            reason="resource_not_found",
                        )
                    active_grid = (
                        getattr(existing, "governed_registration_id", "") or ""
                    )
                    if active_grid == rec_grid:
                        return FirstGovernanceResult(
                            outcome=O.ALREADY_APPLIED_SAME_DECISION,
                            resource_kind=request.resource_kind,
                            resource_id=request.resource_id,
                            governed_registration_id=rec_grid,
                            resulting_generation=rec_gen,
                            reason="first_governance_already_applied",
                        )
                    if active_grid == "":
                        # Recovery: WRITE 1 (fact) exists, WRITE 2 (governed
                        # active) missing. Reuse the STORED lineage/generation —
                        # never a retry mint, never a further advance.
                        # P2: Need durable commit for recovery too
                        candidate_snapshot = self._build_durable_state_snapshot()
                        # Add first-governance record to candidate
                        candidate_snapshot["first_governances"].append({
                            "resource_kind": request.resource_kind.value,
                            "resource_id": request.resource_id,
                            "proposal_id": request.proposal_id,
                            "decision_id": request.decision_id,
                            "governed_registration_id": rec_grid,
                            "resulting_generation": rec_gen,
                        })
                        # Add active governed
                        candidate_snapshot["active_governed"].append({
                            "resource_kind": request.resource_kind.value,
                            "resource_id": request.resource_id,
                            "governed_registration_id": rec_grid,
                            "generation": rec_gen,
                            "status": existing.status.value,
                        })

                        if self._durable_store:
                            self._durable_store._validate_candidate_state(candidate_snapshot)
                        result = self._durable_store.commit(self._durable_revision, candidate_snapshot) if self._durable_store else {"outcome": "committed"}
                        if result.get("outcome") != "committed":
                            if self._durable_store:
                                self._poison_rrm(f"Durable commit failed for first-governance recovery: {result.get('reason')}")
                            return FirstGovernanceResult(
                                outcome=O.INVALID_STATE,
                                resource_kind=request.resource_kind,
                                resource_id=request.resource_id,
                                reason=f"durable_commit_failed: {result.get('reason', 'unknown')}",
                            )

                        existing.governed_registration_id = rec_grid
                        existing.generation = rec_gen
                        existing.updated_at = utc_iso()
                        if self._durable_store:
                            self._durable_revision += 1

                        return FirstGovernanceResult(
                            outcome=O.APPLIED,
                            resource_kind=request.resource_kind,
                            resource_id=request.resource_id,
                            governed_registration_id=rec_grid,
                            resulting_generation=rec_gen,
                            reason="first_governance_recovered",
                        )
                    return FirstGovernanceResult(
                        outcome=O.ALREADY_GOVERNED,
                        resource_kind=request.resource_kind,
                        resource_id=request.resource_id,
                        governed_registration_id=active_grid,
                        resulting_generation=getattr(existing, "generation", 0),
                        reason="governed_by_other_lineage",
                    )
                return FirstGovernanceResult(
                    outcome=O.ALREADY_GOVERNED,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="governed_by_other_decisions",
                )

            # ------------------------------------------------------------------
            # PHASE 2: fresh first governance — state/lifecycle facts only.
            # ------------------------------------------------------------------
            if existing is None:
                return FirstGovernanceResult(
                    outcome=O.NOT_FOUND,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="resource_not_found",
                )

            active_grid = (
                getattr(existing, "governed_registration_id", "") or ""
            )
            if active_grid:
                return FirstGovernanceResult(
                    outcome=O.ALREADY_GOVERNED,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    governed_registration_id=active_grid,
                    resulting_generation=getattr(existing, "generation", 0),
                    reason="resource_already_governed",
                )

            actual_gen = getattr(existing, "generation", 0)
            if actual_gen != request.expected_pre_governed_generation:
                return FirstGovernanceResult(
                    outcome=O.GENERATION_MISMATCH,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    governed_registration_id="",
                    resulting_generation=0,
                    reason="pre_governed_generation_mismatch",
                )

            if existing.status in (
                ResourceStatus.ARCHIVED,
                ResourceStatus.UNINSTALLED,
            ):
                return FirstGovernanceResult(
                    outcome=O.INVALID_STATE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason="terminal_state",
                )

            governed_registration_id = self._generate_governed_registration_id(
                request.resource_kind, request.resource_id
            )
            resulting_generation = request.expected_pre_governed_generation + 1

            # P2 Step 3: Derive candidate post-state WITHOUT mutating canonical memory
            candidate_snapshot = self._build_durable_state_snapshot()
            # Add first-governance record to candidate
            candidate_snapshot["first_governances"].append({
                "resource_kind": request.resource_kind.value,
                "resource_id": request.resource_id,
                "proposal_id": request.proposal_id,
                "decision_id": request.decision_id,
                "governed_registration_id": governed_registration_id,
                "resulting_generation": resulting_generation,
            })
            # Add active governed
            candidate_snapshot["active_governed"].append({
                "resource_kind": request.resource_kind.value,
                "resource_id": request.resource_id,
                "governed_registration_id": governed_registration_id,
                "generation": resulting_generation,
                "status": existing.status.value,
            })

# P2 Step 4: Validate candidate
            if self._durable_store:
                self._durable_store._validate_candidate_state(candidate_snapshot)

            # P2 Step 5-6: Verify expected revision, durable atomic commit
            result = self._durable_store.commit(self._durable_revision, candidate_snapshot) if self._durable_store else {"outcome": "committed"}
            if result.get("outcome") != "committed":
                if self._durable_store:
                    self._poison_rrm(f"Durable commit failed for first-governance recovery: {result.get('reason')}")
                return FirstGovernanceResult(
                    outcome=O.INVALID_STATE,
                    resource_kind=request.resource_kind,
                    resource_id=request.resource_id,
                    reason=f"durable_commit_failed: {result.get('reason', 'unknown')}",
                )

            # P2 Step 7: Only after commit succeeds, publish matching in-memory change
            self._first_governances[key] = (
                request.proposal_id,
                request.decision_id,
                governed_registration_id,
                resulting_generation,
            )

            existing.governed_registration_id = governed_registration_id
            existing.generation = resulting_generation
            existing.updated_at = utc_iso()  # WRITE 2

            if self._durable_store:
                self._durable_revision += 1

            return FirstGovernanceResult(
                outcome=O.APPLIED,
                resource_kind=request.resource_kind,
                resource_id=request.resource_id,
                governed_registration_id=governed_registration_id,
                resulting_generation=resulting_generation,
                reason="",
            )

    def get_first_governance_restart_evidence(
        self,
        resource_kind: ResourceType,
        resource_id: str,
        observed_governed_registration_id: str,
        observed_generation: int,
        observed_status: Any,
    ) -> Optional["FirstGovernanceRestartEvidence"]:
        """M32B-1 — READ-ONLY restart-reconciliation evidence query.

        Returns a FirstGovernanceRestartEvidence ONLY when the observed live
        identity is fully explained by durable M32A authority:

          - a first-governance fact for (kind, id) was LOADED from the durable
            store at initialization (never minted in this process);
          - the durable active record and the fact agree on the observed grid
            and generation;
          - observed status equals the durable status and is non-terminal;
          - the lineage is neither tombstoned nor consumed as a predecessor.

        Returns None otherwise. Performs NO mint, NO mutation, NO commit, and
        NO authorization. A None result MUST be treated as fail-closed by the
        caller (existing already_governed behavior).
        """
        from intent_kernel.rrm.generation import is_valid_generation
        from intent_kernel.rrm.models import FirstGovernanceRestartEvidence

        with self._lock:
            self._check_poisoned()

            key = (resource_kind, resource_id)
            if key not in self._durable_loaded_fg_keys:
                return None
            fact = self._first_governances.get(key)
            active = self._durable_active.get(key)
            if fact is None or active is None:
                return None

            grid = observed_governed_registration_id or ""
            if not grid:
                return None
            if grid != active.get("governed_registration_id"):
                return None
            if grid != fact[2]:
                return None

            gen = observed_generation
            if not is_valid_generation(gen):
                return None
            if gen != active.get("generation"):
                return None
            if gen != fact[3]:
                return None

            status_str = getattr(observed_status, "value", observed_status)
            status_str = str(status_str or "")
            if status_str != str(active.get("status") or ""):
                return None
            if status_str in (
                ResourceStatus.ARCHIVED.value,
                ResourceStatus.UNINSTALLED.value,
            ):
                return None

            if (resource_kind, resource_id, grid) in self._tombstones:
                return None
            if (resource_kind, resource_id, grid) in self._consumptions:
                return None

            return FirstGovernanceRestartEvidence(
                resource_kind=resource_kind,
                resource_id=resource_id,
                governed_registration_id=grid,
                generation=gen,
                status=status_str,
                fact_proposal_id=fact[0],
                fact_decision_id=fact[1],
                durable_loaded=True,
            )

    def _get_provider_for_mutation(self, provider_id: str) -> Optional[ProviderResource]:
        """Internal method to get mutable provider for mutation operations.

        WARNING: This returns the canonical mutable resource. Should only be used
        by RRM internal mutation methods (register, update, etc.).
        """
        with self._lock:
            return self._providers.get(provider_id)

    def list_providers(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProviderSnapshot]:
        with self._lock:
            self._check_poisoned()
            providers = list(self._providers.values())
            if only_eligible:
                providers = [p for p in providers if p.is_eligible]
            if status is not None:
                providers = [p for p in providers if p.status == status]
            return [p.to_snapshot() for p in providers]

    def unregister_provider(self, provider_id: str) -> bool:
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(provider_id):
                return False
            if provider_id in self._providers:
                del self._providers[provider_id]
                return True
            return False

    # --- Account Operations ---

    def register_account(self, account: AccountResource) -> AccountResource:
        with self._lock:
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.ACCOUNT, account.account_id):
                return self._accounts.get(account.account_id)  # H1.3: reject retired identity
            existing = self._accounts.get(account.account_id)
            if existing is not None and self._is_governed_resource(account.account_id):
                return existing
            self._establish_generation_on_registration(account, existing)
            account.updated_at = utc_iso()
            self._accounts[account.account_id] = account
            return account

    def get_account(self, account_id: str) -> Optional[AccountSnapshot]:
        with self._lock:
            self._check_poisoned()
            account = self._accounts.get(account_id)
            if account is None:
                return None
            return account.to_snapshot()

    def _get_account_for_mutation(self, account_id: str) -> Optional[AccountResource]:
        """Internal method to get mutable account for mutation operations."""
        with self._lock:
            return self._accounts.get(account_id)

    def list_accounts(
        self,
        provider_id: Optional[str] = None,
        status: Optional[ResourceStatus] = None,
        only_eligible: bool = False,
    ) -> List[AccountSnapshot]:
        with self._lock:
            self._check_poisoned()
            accounts = list(self._accounts.values())
            if only_eligible:
                accounts = [a for a in accounts if a.is_eligible]
            if provider_id is not None:
                accounts = [a for a in accounts if a.provider_id == provider_id]
            if status is not None:
                accounts = [a for a in accounts if a.status == status]
            return [a.to_snapshot() for a in accounts]

    def unregister_account(self, account_id: str) -> bool:
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(account_id):
                return False
            if account_id in self._accounts:
                del self._accounts[account_id]
                return True
            return False

    # --- Execution Environment Operations ---

    def register_environment(self, environment: ExecutionEnvironmentResource) -> ExecutionEnvironmentResource:
        with self._lock:
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.EXECUTION_ENVIRONMENT, environment.environment_id):
                return self._environments.get(environment.environment_id)  # H1.3: reject retired identity
            existing = self._environments.get(environment.environment_id)
            if existing is not None and self._is_governed_resource(environment.environment_id):
                return existing
            self._establish_generation_on_registration(environment, existing)
            environment.updated_at = utc_iso()
            self._environments[environment.environment_id] = environment
            return environment

    def get_environment(self, environment_id: str) -> Optional[ExecutionEnvironmentSnapshot]:
        with self._lock:
            self._check_poisoned()
            env = self._environments.get(environment_id)
            if env is None:
                return None
            return env.to_snapshot()

    def _get_environment_for_mutation(self, environment_id: str) -> Optional[ExecutionEnvironmentResource]:
        """Internal method to get mutable environment for mutation operations."""
        with self._lock:
            return self._environments.get(environment_id)

    def list_environments(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ExecutionEnvironmentSnapshot]:
        with self._lock:
            self._check_poisoned()
            envs = list(self._environments.values())
            if only_eligible:
                envs = [e for e in envs if e.is_eligible]
            if status is not None:
                envs = [e for e in envs if e.status == status]
            return [e.to_snapshot() for e in envs]

    def unregister_environment(self, environment_id: str) -> bool:
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(environment_id):
                return False
            if environment_id in self._environments:
                del self._environments[environment_id]
                return True
            return False

    # --- Capability Operations ---

    def register_capability(self, capability: CapabilityResource) -> CapabilityResource:
        with self._lock:
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.CAPABILITY, capability.capability_id):
                return self._capabilities.get(capability.capability_id)  # H1.3: reject retired identity
            existing = self._capabilities.get(capability.capability_id)
            if existing is not None and self._is_governed_resource(capability.capability_id):
                return existing
            self._establish_generation_on_registration(capability, existing)
            capability.updated_at = utc_iso()
            self._capabilities[capability.capability_id] = capability
            if capability.name and capability.name != capability.capability_id:
                self._capabilities[capability.name] = capability
            return capability

    def get_capability(self, capability_name_or_id: str) -> Optional[CapabilitySnapshot]:
        with self._lock:
            self._check_poisoned()
            cap = self._capabilities.get(capability_name_or_id)
            if cap is None:
                return None
            return cap.to_snapshot()

    def _get_capability_for_mutation(self, capability_id: str) -> Optional[CapabilityResource]:
        """Internal method to get mutable capability for mutation operations."""
        with self._lock:
            return self._capabilities.get(capability_id)

    def list_capabilities(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[CapabilitySnapshot]:
        with self._lock:
            self._check_poisoned()
            unique = {id(c): c for c in self._capabilities.values()}
            caps = list(unique.values())
            if only_eligible:
                caps = [c for c in caps if c.is_eligible]
            if status is not None:
                caps = [c for c in caps if c.status == status]
            return [c.to_snapshot() for c in caps]

    def unregister_capability(self, capability_id: str) -> bool:
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(capability_id):
                return False
            cap = self._capabilities.get(capability_id)
            if cap:
                keys_to_del = [k for k, v in self._capabilities.items() if v is cap]
                for k in keys_to_del:
                    del self._capabilities[k]
                return True
            return False

    # --- Agent Operations ---

    def register_agent(self, agent: AgentResource) -> AgentResource:
        with self._lock:
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.AGENT, agent.agent_id):
                return self._agents.get(agent.agent_id)  # H1.3: reject retired identity
            existing = self._agents.get(agent.agent_id)
            if existing is not None and self._is_governed_resource(agent.agent_id):
                return existing
            self._establish_generation_on_registration(agent, existing)
            agent.updated_at = utc_iso()
            self._agents[agent.agent_id] = agent
            return agent

    def get_agent(self, agent_id: str) -> Optional[AgentSnapshot]:
        with self._lock:
            self._check_poisoned()
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            return agent.to_snapshot()

    def _get_agent_for_mutation(self, agent_id: str) -> Optional[AgentResource]:
        """Internal method to get mutable agent for mutation operations."""
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[AgentSnapshot]:
        with self._lock:
            self._check_poisoned()
            agents = list(self._agents.values())
            if only_eligible:
                agents = [a for a in agents if a.is_eligible]
            if status is not None:
                agents = [a for a in agents if a.status == status]
            return [a.to_snapshot() for a in agents]

    def unregister_agent(self, agent_id: str) -> bool:
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(agent_id):
                return False
            if agent_id in self._agents:
                del self._agents[agent_id]
                return True
            return False

    def find_agents_for_capabilities(self, capabilities: List[str], only_eligible: bool = True) -> List[AgentResource]:
        with self._lock:
            self._check_poisoned()
            matching = []
            for agent in self._agents.values():
                if only_eligible and not agent.is_eligible:
                    continue
                if any(cap in agent.capabilities for cap in capabilities):
                    matching.append(agent)
            return matching

    # --- Project Operations ---

    def register_project(self, project: ProjectResource) -> ProjectResource:
        with self._lock:
            # M31.2B-2B: kind-aware tombstone guard — parity with other five families
            self._check_poisoned()
            if self._is_tombstoned(ResourceType.PROJECT, project.project_id):
                return self._projects.get(project.project_id)  # H1.3: reject retired identity
            existing = self._projects.get(project.project_id)
            # M31.2B-2B: governed overwrite guard — parity with other five families
            if existing is not None and self._is_governed_resource(project.project_id):
                return existing
            self._establish_generation_on_registration(project, existing)
            project.updated_at = utc_iso()
            self._projects[project.project_id] = project
            return project

    def get_project(self, project_id: str) -> Optional[ProjectSnapshot]:
        with self._lock:
            self._check_poisoned()
            project = self._projects.get(project_id)
            if project is None:
                return None
            return project.to_snapshot()

    def _get_project_for_mutation(self, project_id: str) -> Optional[ProjectResource]:
        """Internal method to get mutable project for mutation operations."""
        with self._lock:
            return self._projects.get(project_id)

    def list_projects(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProjectSnapshot]:
        with self._lock:
            self._check_poisoned()
            projects = list(self._projects.values())
            if only_eligible:
                projects = [p for p in projects if p.is_eligible]
            if status is not None:
                projects = [p for p in projects if p.status == status]
            return [p.to_snapshot() for p in projects]

    def unregister_project(self, project_id: str) -> bool:
        with self._lock:
            # M31.2B-2B: governed resource guard — parity with other five families.
            # Governed Project retirement must flow through retirement authority.
            self._check_poisoned()
            if self._is_governed_resource(project_id):
                return False
            if project_id in self._projects:
                del self._projects[project_id]
                return True
            return False

    # --- Governed Resource Provenance ---

    def _establish_generation_on_registration(self, incoming: Any, existing: Any) -> None:
        """Single canonical generation authority on registration.

        M30.2 — registration NEVER trusts caller-provided generation for a
        newly-introduced canonical resource:
          - new to RRM (existing is None): generation = GENERATION_INITIAL (1).
          - re-registration / repeated projection of an existing incarnation:
            preserve the stored generation so legitimate updates and repeated
            projections never reset or decrease lineage.
        """
        from intent_kernel.rrm.generation import (
            GENERATION_INITIAL,
            is_valid_generation,
        )

        if existing is None:
            families = (
                (ProviderResource, ResourceType.PROVIDER, "provider_id"),
                (AccountResource, ResourceType.ACCOUNT, "account_id"),
                (ExecutionEnvironmentResource, ResourceType.EXECUTION_ENVIRONMENT, "environment_id"),
                (CapabilityResource, ResourceType.CAPABILITY, "capability_id"),
                (AgentResource, ResourceType.AGENT, "agent_id"),
                (ProjectResource, ResourceType.PROJECT, "project_id"),
            )
            for resource_class, kind, id_field in families:
                if isinstance(incoming, resource_class):
                    record = self._durable_active.get((kind, getattr(incoming, id_field)))
                    if record is not None:
                        incoming.governed_registration_id = record["governed_registration_id"]
                        incoming.generation = record["generation"]
                        incoming.status = ResourceStatus(record["status"])
                        return
            incoming.generation = GENERATION_INITIAL
        elif is_valid_generation(getattr(existing, "generation", 0)):
            incoming.generation = existing.generation
        else:
            incoming.generation = GENERATION_INITIAL

    def _advance_generation(self, resource: Any) -> None:
        """Single canonical mutation authority: advance generation by exactly one.

        M30.2 — material mutation advances generation exactly once. A legacy
        resource's first material mutation establishes canonical generation 1.
        Called ONLY by RegistryResourceManager mutation methods, under the RRM
        lock, atomically with the state mutation it accompanies.
        """
        from intent_kernel.rrm.generation import (
            GENERATION_INITIAL,
            is_valid_generation,
        )

        gen = getattr(resource, "generation", 0)
        resource.generation = (
            (gen + 1) if is_valid_generation(gen) else GENERATION_INITIAL
        )

    # --- M31.2B-1: Typed Conditional Update/Create Operations ---

    def conditional_update_status(
        self,
        request: ConditionalResourceStatusRequest,
    ) -> ConditionalUpdateResult:
        """Conditionally update resource status with generation and lineage checks.

        M32A P2: Durable-before-memory protocol.
        Atomically compares expected governed_registration_id and generation
        against canonical RRM state. If all match, applies the status change
        and advances generation exactly once. Durable commit precedes memory mutation.

        Returns a typed result with outcome and observed state.
        """
        from intent_kernel.rrm.models import (
            ConditionalResourceStatusRequest,
            ConditionalUpdateResult,
            ConditionalUpdateOutcome,
        )

        with self._lock:
            self._check_poisoned()

            # P2 Step 1-2: Acquire lock, validate current canonical state
            # Locate resource by type and ID
            resource = self._get_resource_for_mutation(request.resource_type, request.resource_id)
            if resource is None:
                return ConditionalUpdateResult(
                    outcome=ConditionalUpdateOutcome.NOT_FOUND,
                    resource_type=request.resource_type,
                    resource_id=request.resource_id,
                    observed_generation=0,
                    observed_governed_registration_id="",
                    previous_status=None,
                    new_status=None,
                    reason="resource_not_found",
                )

            # Verify registration lineage
            if request.expected_governed_registration_id:
                actual_grid = getattr(resource, "governed_registration_id", "") or ""
                if request.expected_governed_registration_id != actual_grid:
                    return ConditionalUpdateResult(
                        outcome=ConditionalUpdateOutcome.REGISTRATION_LINEAGE_MISMATCH,
                        resource_type=request.resource_type,
                        resource_id=request.resource_id,
                        observed_generation=getattr(resource, "generation", 0),
                        observed_governed_registration_id=actual_grid,
                        previous_status=None,
                        new_status=None,
                        reason="registration_lineage_mismatch",
                    )

            # Verify generation
            expected_gen = request.expected_generation
            if expected_gen > 0:
                actual_gen = getattr(resource, "generation", 0)
                if expected_gen != actual_gen:
                    return ConditionalUpdateResult(
                        outcome=ConditionalUpdateOutcome.GENERATION_MISMATCH,
                        resource_type=request.resource_type,
                        resource_id=request.resource_id,
                        observed_generation=actual_gen,
                        observed_governed_registration_id=getattr(resource, "governed_registration_id", "") or "",
                        previous_status=None,
                        new_status=None,
                        reason="generation_mismatch",
                    )

            # Validate transition (basic lifecycle validation)
            if not self._is_valid_status_transition(request.resource_type, resource, request.desired_status):
                return ConditionalUpdateResult(
                    outcome=ConditionalUpdateOutcome.INVALID_TRANSITION,
                    resource_type=request.resource_type,
                    resource_id=request.resource_id,
                    observed_generation=getattr(resource, "generation", 0),
                    observed_governed_registration_id=getattr(resource, "governed_registration_id", "") or "",
                    previous_status=resource.status,
                    new_status=None,
                    reason="invalid_transition",
                )

            # Check for no-op
            if resource.status == request.desired_status:
                return ConditionalUpdateResult(
                    outcome=ConditionalUpdateOutcome.NO_OP,
                    resource_type=request.resource_type,
                    resource_id=request.resource_id,
                    observed_generation=getattr(resource, "generation", 0),
                    observed_governed_registration_id=getattr(resource, "governed_registration_id", "") or "",
                    previous_status=resource.status,
                    new_status=resource.status,
                    reason="",
                )

            # P2 Step 3: Derive candidate post-state WITHOUT mutating canonical memory
            new_generation = getattr(resource, "generation", 0)
            from intent_kernel.rrm.generation import GENERATION_INITIAL, is_valid_generation
            gen = getattr(resource, "generation", 0)
            candidate_generation = (
                (gen + 1) if is_valid_generation(gen) else GENERATION_INITIAL
            )
            candidate_status = request.desired_status

            # Build candidate durable state snapshot (simulating mutation)
            candidate_snapshot = self._build_durable_state_snapshot()
            # Update the candidate snapshot with the simulated mutation
            for ag in candidate_snapshot.get("active_governed", []):
                if ag["resource_kind"] == request.resource_type.value and ag["resource_id"] == request.resource_id:
                    ag["generation"] = candidate_generation
                    ag["status"] = candidate_status.value
                    break

# P2 Step 4: Validate candidate
            if self._durable_store:
                self._durable_store._validate_candidate_state(candidate_snapshot)

            # P2 Step 5-6: Verify expected revision, durable atomic commit
            result = self._durable_store.commit(self._durable_revision, candidate_snapshot) if self._durable_store else {"outcome": "committed"}
            if result.get("outcome") != "committed":
                if self._durable_store:
                    self._poison_rrm(f"Durable commit failed for status update: {result.get('reason')}")
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.INVALID_TRANSITION,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    observed_governed_registration_id=actual_grid,
                    observed_generation=actual_gen,
                    reason=f"durable_commit_failed: {result.get('reason', 'unknown')}",
                )

            # P2 Step 7: Only after commit succeeds, publish matching in-memory change
            previous_status = resource.status
            resource.status = request.desired_status
            self._advance_generation(resource)
            resource.updated_at = utc_iso()

            # Update durable revision tracking
            if self._durable_store:
                self._durable_revision += 1

            return ConditionalUpdateResult(
                outcome=ConditionalUpdateOutcome.APPLIED,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                observed_generation=getattr(resource, "generation", 0),
                observed_governed_registration_id=getattr(resource, "governed_registration_id", "") or "",
                previous_status=previous_status,
                new_status=resource.status,
                reason="",
            )

    def conditional_create_resource(
        self,
        request: ConditionalRegistrationRequest,
    ) -> ConditionalCreateResult:
        """Conditionally create a genuinely never-registered resource.

        M31.2B-1 supports ONLY fresh creates of never-registered identities.
        RRM does NOT authorize re-registration: an existing active identity
        collides (CONFLICT_ACTIVE) and a tombstoned / previously-governed
        identity fails closed (REJECTED_TOMBSTONED). No authorization is ever
        inferred from an expected old registration id, an expected old
        generation, logical-id equality, or tombstone presence.

        Under the SINGLE self._lock: absence check, tombstone inspection, new
        canonical resource construction, generation=1 assignment, and
        installation all occur atomically.

        Returns a detached immutable CREATED result. The caller's resource_data
        is never mutated, aliased, or installed as the canonical object.
        """
        from intent_kernel.rrm.models import (
            ConditionalRegistrationRequest,
            ConditionalCreateResult,
            ConditionalCreateOutcome,
        )

        with self._lock:
            self._check_poisoned()
            resource_type = request.resource_type
            resource_data = request.resource_data

            store, id_field = self._get_store_for_type(resource_type)
            if store is None:
                return ConditionalCreateResult(
                    outcome=ConditionalCreateOutcome.CONFLICT_ACTIVE,
                    resource_type=resource_type,
                    resource_id="",
                    observed_governed_registration_id="",
                    observed_generation=0,
                    reason="unsupported_resource_type",
                )

            resource_id = getattr(resource_data, id_field, None)
            if not resource_id:
                return ConditionalCreateResult(
                    outcome=ConditionalCreateOutcome.CONFLICT_ACTIVE,
                    resource_type=resource_type,
                    resource_id="",
                    observed_governed_registration_id="",
                    observed_generation=0,
                    reason="missing_resource_id",
                )

            # Defensive: M31.2B-1 does not authorize re-registration. The
            # request contract rejects expected_absence=False at construction,
            # but remain fail-closed here regardless.
            if not request.expected_absence:
                return ConditionalCreateResult(
                    outcome=ConditionalCreateOutcome.CONFLICT_ACTIVE,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    observed_governed_registration_id="",
                    observed_generation=0,
                    reason="re_registration_not_authorized",
                )

            # Tombstoned / retired governed identity: fail closed. A tombstone
            # NEVER implies re-registration authorization.
            # M31.2B-2B: kind-aware tombstone query
            if self._is_tombstoned(resource_type, resource_id):
                return ConditionalCreateResult(
                    outcome=ConditionalCreateOutcome.REJECTED_TOMBSTONED,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    observed_governed_registration_id="",
                    observed_generation=0,
                    reason="resource_tombstoned",
                )

            # Existing active resource collides with expected absence.
            existing = store.get(resource_id)
            if existing is not None:
                return ConditionalCreateResult(
                    outcome=ConditionalCreateOutcome.CONFLICT_ACTIVE,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    observed_governed_registration_id="",
                    observed_generation=getattr(existing, "generation", 0),
                    reason="resource_already_exists",
                )

            # Genuinely never-registered: construct a NEW canonical internal
            # resource from the validated caller data. Never mutate, alias, or
            # install the caller-owned resource_data.
            canonical = self._build_canonical_copy(resource_type, resource_data)
            # Governed lineage is RRM/promotion-boundary authority, never caller
            # input. Assign a clean (empty) governed identity and generation=1.
            canonical.governed_registration_id = ""
            self._establish_generation_on_registration(canonical, None)
            canonical.updated_at = utc_iso()
            store[resource_id] = canonical

            return ConditionalCreateResult(
                outcome=ConditionalCreateOutcome.CREATED,
                resource_type=resource_type,
                resource_id=resource_id,
                observed_governed_registration_id="",
                observed_generation=getattr(canonical, "generation", 0),
                reason="",
            )

    def conditional_retire_resource(
        self,
        request: ConditionalRetirementRequest,
    ) -> ConditionalRetirementResult:
        """M31.2B-2B — Conditionally retire a governed resource under a single lock.

        M32A P2: Durable-before-memory protocol.
        Single-lock critical section: locate → validate → tombstone → remove → result.
        All validation occurs before productive resource removal.
        Durable commit precedes memory mutation.
        """
        with self._lock:
            self._check_poisoned()

            resource_kind = request.resource_kind
            resource_id = request.resource_id
            expected_grid = request.governed_registration_id
            expected_gen = request.expected_generation

            store, id_field = self._get_store_for_type(resource_kind)
            if store is None:
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.NOT_FOUND,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    reason="unsupported_resource_kind",
                )

            resource = store.get(resource_id)

            if resource is None:
                lineage_key = (resource_kind, resource_id, expected_grid)
                existing_tombstone = self._tombstones.get(lineage_key)
                if existing_tombstone is not None:
                    if existing_tombstone.observed_generation == expected_gen:
                        return ConditionalRetirementResult(
                            outcome=ConditionalRetirementOutcome.ALREADY_RETIRED,
                            resource_kind=resource_kind,
                            resource_id=resource_id,
                            observed_governed_registration_id=expected_grid,
                            observed_generation=expected_gen,
                            reason="exact_retry_matches_tombstone",
                        )
                    return ConditionalRetirementResult(
                        outcome=ConditionalRetirementOutcome.GENERATION_MISMATCH,
                        resource_kind=resource_kind,
                        resource_id=resource_id,
                        observed_governed_registration_id=None,
                        observed_generation=None,
                        reason="tombstone_generation_mismatch",
                    )
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.NOT_FOUND,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    observed_governed_registration_id=None,
                    observed_generation=None,
                    reason="resource_not_found",
                )

            actual_grid = getattr(resource, "governed_registration_id", "") or ""
            if actual_grid != expected_grid:
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.REGISTRATION_LINEAGE_MISMATCH,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    observed_governed_registration_id=actual_grid,
                    observed_generation=getattr(resource, "generation", 0),
                    reason="registration_lineage_mismatch",
                )

            actual_gen = getattr(resource, "generation", 0)
            if actual_gen != expected_gen:
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.GENERATION_MISMATCH,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    observed_governed_registration_id=actual_grid,
                    observed_generation=actual_gen,
                    reason="generation_mismatch",
                )

            # P2 Step 3: Derive candidate post-state WITHOUT mutating canonical memory
            candidate_snapshot = self._build_durable_state_snapshot()
            # Add tombstone to candidate
            candidate_snapshot["tombstones"].append({
                "resource_kind": resource_kind.value,
                "resource_id": resource_id,
                "governed_registration_id": actual_grid,
                "observed_generation": actual_gen,
            })
            # Remove from active governed
            candidate_snapshot["active_governed"] = [
                ag for ag in candidate_snapshot.get("active_governed", [])
                if not (ag["resource_kind"] == resource_kind.value and ag["resource_id"] == resource_id)
            ]

# P2 Step 4: Validate candidate
            if self._durable_store:
                self._durable_store._validate_candidate_state(candidate_snapshot)

            # P2 Step 5-6: Verify expected revision, durable atomic commit
            result = self._durable_store.commit(self._durable_revision, candidate_snapshot) if self._durable_store else {"outcome": "committed"}
            if result.get("outcome") != "committed":
                if self._durable_store:
                    self._poison_rrm(f"Durable commit failed for retirement: {result.get('reason')}")
                return ConditionalRetirementResult(
                    outcome=ConditionalRetirementOutcome.INVALID_TRANSITION,
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    observed_governed_registration_id=actual_grid,
                    observed_generation=actual_gen,
                    reason=f"durable_commit_failed: {result.get('reason', 'unknown')}",
                )

            # P2 Step 7: Only after commit succeeds, publish matching in-memory change
            result_obj = ConditionalRetirementResult(
                outcome=ConditionalRetirementOutcome.RETIRED,
                resource_kind=resource_kind,
                resource_id=resource_id,
                observed_governed_registration_id=actual_grid,
                observed_generation=actual_gen,
                reason="",
            )

            tombstone = ResourceTombstone(
                resource_kind=resource_kind,
                resource_id=resource_id,
                governed_registration_id=actual_grid,
                observed_generation=actual_gen,
            )

            del store[resource_id]
            self._tombstones[tombstone.lineage_identity] = tombstone

            if self._durable_store:
                self._durable_revision += 1

            return result_obj

    def _build_canonical_copy(self, resource_type: ResourceType, source: Any) -> Any:
        """Construct a fresh, structurally detached canonical resource.

        RA-31.2B1-03: builds the canonical object from caller data that has been
        recursively detached (shallow-read via dataclass fields, then
        `_detach_value` deep structural clone). The caller-owned `source` is
        never mutated, installed, or aliased at any nesting depth.
        """
        from intent_kernel.rrm.models import (
            ProviderResource,
            AccountResource,
            ExecutionEnvironmentResource,
            CapabilityResource,
            AgentResource,
            ProjectResource,
        )

        # Read the caller's fields WITHOUT deepcopy so arbitrary caller objects
        # never reach copy.deepcopy/asdict hooks; then detach structurally and
        # fail-closed on unsupported types before any canonical mutation.
        raw = {f.name: getattr(source, f.name) for f in dataclasses.fields(source)}
        detached = _detach_value(raw)

        if resource_type == ResourceType.PROVIDER:
            return ProviderResource.from_dict(detached)
        elif resource_type == ResourceType.ACCOUNT:
            return AccountResource.from_dict(detached)
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            return ExecutionEnvironmentResource.from_dict(detached)
        elif resource_type == ResourceType.CAPABILITY:
            return CapabilityResource.from_dict(detached)
        elif resource_type == ResourceType.AGENT:
            return AgentResource.from_dict(detached)
        elif resource_type == ResourceType.PROJECT:
            return ProjectResource.from_dict(detached)
        raise ValueError(f"unsupported resource_type: {resource_type}")

    def _get_resource_for_mutation(self, resource_type: ResourceType, resource_id: str) -> Optional[Any]:
        """Get mutable resource by type and ID for conditional operations."""
        if resource_type == ResourceType.PROVIDER:
            return self._get_provider_for_mutation(resource_id)
        elif resource_type == ResourceType.ACCOUNT:
            return self._get_account_for_mutation(resource_id)
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            return self._get_environment_for_mutation(resource_id)
        elif resource_type == ResourceType.CAPABILITY:
            return self._get_capability_for_mutation(resource_id)
        elif resource_type == ResourceType.AGENT:
            return self._get_agent_for_mutation(resource_id)
        elif resource_type == ResourceType.PROJECT:
            return self._get_project_for_mutation(resource_id)
        return None

    def _get_store_for_type(self, resource_type: ResourceType):
        """Get the storage dict and id attribute name for a resource type."""
        if resource_type == ResourceType.PROVIDER:
            return self._providers, "provider_id"
        elif resource_type == ResourceType.ACCOUNT:
            return self._accounts, "account_id"
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            return self._environments, "environment_id"
        elif resource_type == ResourceType.CAPABILITY:
            return self._capabilities, "capability_id"
        elif resource_type == ResourceType.AGENT:
            return self._agents, "agent_id"
        elif resource_type == ResourceType.PROJECT:
            return self._projects, "project_id"
        return None, None

    def _is_valid_status_transition(self, resource_type: ResourceType, resource: Any, desired_status: ResourceStatus) -> bool:
        """Validate status transition rules for the resource type."""
        # Basic validation: cannot transition from terminal states
        current = resource.status
        if current == ResourceStatus.ARCHIVED or current == ResourceStatus.UNINSTALLED:
            return False
        # Add more specific rules per resource type if needed
        return True

    def mark_governed(self, resource_id: str, registration_id: str = "") -> None:
        """Compatibility-only marker — does NOT create canonical governed identity.

        COMPATIBILITY_ONLY / TEST_ONLY — retained for backward compatibility
        and test infrastructure only.

        This method does NOT:
        - Populate the canonical governed identity store
        - Cause _is_governed_resource() to return True
        - Trigger protected overwrite guards
        - Influence activation trust, eligibility, binding, or execution

        Canonical governed identity is created exclusively by
        CanonicalPromotionRegistrationBoundary via governed_registration_id
        on the resource object.
        """
        with self._lock:
            self._check_poisoned()
            pass

    def is_governed(self, resource_id: str) -> bool:
        """Check if a resource ID is governed.

        COMPATIBILITY_ONLY — checks canonical governed_registration_id
        on the resource object. Does NOT consult _governed_ids set.
        """
        with self._lock:
            self._check_poisoned()
            existing = (
                self._providers.get(resource_id)
                or self._capabilities.get(resource_id)
                or self._agents.get(resource_id)
                or self._environments.get(resource_id)
                or self._accounts.get(resource_id)
                or self._projects.get(resource_id)
            )
            if existing is not None:
                return bool(getattr(existing, "governed_registration_id", ""))
            return False

    def _is_governed_resource(self, resource_id: str) -> bool:
        """Check if a resource has canonical governed provenance.

        A resource is considered governed ONLY if it has a non-empty
        governed_registration_id set by CanonicalPromotionRegistrationBoundary.

        NOT governed:
        - mark_governed() called (compatibility-only, no canonical identity)
        - resource_origin alone (caller-controlled)
        - caller-provided registration strings
        - _governed_ids set (compatibility-only, not consulted)

        Canonical governed identity is generated by M17 registration boundary
        and bound to resource_id + kind + proposal_id + decision_id.
        """
        existing = (
            self._providers.get(resource_id)
            or self._capabilities.get(resource_id)
            or self._agents.get(resource_id)
            or self._environments.get(resource_id)
            or self._accounts.get(resource_id)
            or self._projects.get(resource_id)
        )
        if existing is not None:
            return bool(getattr(existing, "governed_registration_id", ""))
        return False

    # --- H1.3 Retired Resource Tombstones ---

    def _record_tombstone(
        self,
        resource_kind: ResourceType,
        resource_id: str,
        governed_registration_id: str,
        observed_generation: int,
    ) -> None:
        """Record a retired resource identity to prevent re-registration.

        M31.2B-2B: constructs a canonical ResourceTombstone and stores it
        in the single authoritative tombstone dict keyed by
        (resource_kind, resource_id, governed_registration_id).
        """
        with self._lock:
            tombstone = ResourceTombstone(
                resource_kind=resource_kind,
                resource_id=resource_id,
                governed_registration_id=governed_registration_id,
                observed_generation=observed_generation,
            )
            self._tombstones[tombstone.lineage_identity] = tombstone

    def _is_tombstoned(self, resource_kind: ResourceType, resource_id: str) -> bool:
        """Check if a resource has been retired and tombstoned for that kind.

        M31.2B-2B: kind-aware query against the canonical tombstone store.
        Cross-family same-ID resources are NOT blocked by each other.
        """
        return any(
            tk == resource_kind and rid == resource_id
            for (tk, rid, _grid) in self._tombstones
        )

    def _is_compatibility_source(self, resource_origin: ResourceOrigin) -> bool:
        """Check if a resource origin represents a compatibility/bootstrap source."""
        return resource_origin in (
            ResourceOrigin.MIGRATION,
            ResourceOrigin.CONFIGURATION,
            ResourceOrigin.HOST_DISCOVERY,
        )

    # --- Generic Query & Status Operations ---

    def query_resources(self, filter_criteria: ResourceQueryFilter) -> List[Any]:
        with self._lock:
            self._check_poisoned()
            results: List[Any] = []

            # Providers
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.PROVIDER:
                for p in self._providers.values():
                    if filter_criteria.matches(ResourceType.PROVIDER, p):
                        results.append(p)

            # Accounts
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.ACCOUNT:
                for a in self._accounts.values():
                    if filter_criteria.matches(ResourceType.ACCOUNT, a):
                        results.append(a)

            # Execution Environments
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.EXECUTION_ENVIRONMENT:
                for e in self._environments.values():
                    if filter_criteria.matches(ResourceType.EXECUTION_ENVIRONMENT, e):
                        results.append(e)

            # Capabilities
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.CAPABILITY:
                unique_caps = {id(c): c for c in self._capabilities.values()}.values()
                for c in unique_caps:
                    if filter_criteria.matches(ResourceType.CAPABILITY, c):
                        results.append(c)

            # Agents
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.AGENT:
                for ag in self._agents.values():
                    if filter_criteria.matches(ResourceType.AGENT, ag):
                        results.append(ag)

            # Projects
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.PROJECT:
                for pr in self._projects.values():
                    if filter_criteria.matches(ResourceType.PROJECT, pr):
                        results.append(pr)

            return results

    def update_resource_status(
        self,
        resource_type: ResourceType,
        resource_id: str,
        status: ResourceStatus,
    ) -> bool:
        """Update status of a non-governed resource.

        Governed resources cannot have their lifecycle mutated by
        generic status updates. Use the activation application boundary
        for governed resource lifecycle transitions.
        """
        with self._lock:
            self._check_poisoned()
            if self._is_governed_resource(resource_id):
                return False

            now = utc_iso()
            if resource_type == ResourceType.PROVIDER:
                res = self._get_provider_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.ACCOUNT:
                res = self._get_account_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
                res = self._get_environment_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.CAPABILITY:
                res = self._get_capability_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.AGENT:
                res = self._get_agent_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.PROJECT:
                res = self._get_project_for_mutation(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            return False

    # --- Health & Metrics ---

    def check_health(self) -> ResourceHealthReport:
        with self._lock:
            self._check_poisoned()
            degraded: List[str] = []
            exhausted_accounts = 0

            active_providers = sum(1 for p in self._providers.values() if p.is_eligible)
            for p in self._providers.values():
                if not p.is_template and p.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"provider:{p.provider_id}")

            active_accounts = sum(1 for a in self._accounts.values() if a.is_eligible)
            for a in self._accounts.values():
                if not a.is_template and a.status in (ResourceStatus.EXHAUSTED, ResourceStatus.THROTTLED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"account:{a.account_id}")
                    if a.status == ResourceStatus.EXHAUSTED or a.quota_remaining <= 0:
                        exhausted_accounts += 1

            active_environments = sum(1 for e in self._environments.values() if e.is_eligible)
            for e in self._environments.values():
                if not e.is_template and e.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"environment:{e.environment_id}")

            unique_caps = list({id(c): c for c in self._capabilities.values()}.values())
            active_caps = sum(1 for c in unique_caps if c.is_eligible)

            active_agents = sum(1 for ag in self._agents.values() if ag.is_eligible)
            for ag in self._agents.values():
                if not ag.is_template and ag.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"agent:{ag.agent_id}")

            active_projects = sum(1 for pr in self._projects.values() if pr.is_eligible)

            total = (
                len(self._providers)
                + len(self._accounts)
                + len(self._environments)
                + len(unique_caps)
                + len(self._agents)
                + len(self._projects)
            )

            is_healthy = len(degraded) == 0 and active_providers > 0 and active_accounts > 0
            overall_status = "healthy" if is_healthy else "degraded" if active_providers > 0 else "unconfigured"

            return ResourceHealthReport(
                is_healthy=is_healthy,
                status=overall_status,
                total_resources=total,
                active_providers=active_providers,
                active_accounts=active_accounts,
                active_environments=active_environments,
                active_capabilities=active_caps,
                active_agents=active_agents,
                active_projects=active_projects,
                exhausted_accounts=exhausted_accounts,
                degraded_resources=degraded,
            )

    def get_metrics(self) -> RRMRegistryMetrics:
        with self._lock:
            self._check_poisoned()
            counts = {
                "providers": len(self._providers),
                "accounts": len(self._accounts),
                "environments": len(self._environments),
                "capabilities": len({id(c) for c in self._capabilities.values()}),
                "agents": len(self._agents),
                "projects": len(self._projects),
            }

            status_counts: Dict[str, int] = {}

            all_resources: List[Any] = (
                list(self._providers.values())
                + list(self._accounts.values())
                + list(self._environments.values())
                + list({id(c): c for c in self._capabilities.values()}.values())
                + list(self._agents.values())
                + list(self._projects.values())
            )

            for r in all_resources:
                st = getattr(r, "status", None)
                st_str = st.value if isinstance(st, Enum) else str(st)
                status_counts[st_str] = status_counts.get(st_str, 0) + 1

            return RRMRegistryMetrics(
                resource_counts=counts,
                status_counts=status_counts,
                providers_count=counts["providers"],
                accounts_count=counts["accounts"],
                environments_count=counts["environments"],
                capabilities_count=counts["capabilities"],
                agents_count=counts["agents"],
                projects_count=counts["projects"],
            )

    # --- Default Catalog Seeds ---

    def populate_default_catalog(self) -> None:
        """Seeds template entries for Intent OS runtime.
        
        CRITICAL ARCHITECTURAL RULE (Studio 8.1):
        Default catalog seeds are strictly TEMPLATES (is_template=True, status=UNCONFIGURED/DRAFT).
        TEMPLATE != AVAILABLE/ELIGIBLE.
        Default seeds do NOT automatically participate in execution selection until explicit
        configuration, discovery, or user registration occurs.
        """
        with self._lock:
            # 1. Default Capabilities (Templates)
            self._check_poisoned()
            default_caps = [
                ("cap_retrieval_financial", "retrieval.financial_context", "Resgate de histórico financeiro", ["finance", "retrieval"], ["finance"], "read"),
                ("cap_modeling_allocation", "modeling.allocation_scenarios", "Modelagem de cenários de alocação", ["finance", "modeling"], ["finance"], "compute"),
                ("cap_analysis_risk", "analysis.risk_evaluation", "Avaliação de riscos de mercado e liquidez", ["finance", "risk"], ["finance"], "compute"),
                ("cap_synthesis_recommendation", "synthesis.recommendation", "Sintetização de recomendações", ["synthesis", "advisory"], ["finance", "general"], "generate"),
                ("cap_validation_goal", "validation.goal_alignment", "Validação de conformidade de metas", ["validation", "goal"], ["general"], "compute"),
                ("cap_code_architecture", "code.architecture_design", "Design de arquitetura de software", ["coding", "architecture"], ["coding"], "generate"),
                ("cap_code_scaffold", "code.scaffold_generation", "Geração de código base e estrutura", ["coding", "generation"], ["coding"], "generate"),
                ("cap_code_ui", "code.ui_design", "Construção e layout de interfaces", ["coding", "ui"], ["coding"], "generate"),
                ("cap_code_backend", "code.backend_logic", "Implementação de lógica backend e APIs", ["coding", "backend"], ["coding"], "generate"),
                ("cap_code_testing", "code.testing", "Verificação e testes unitários", ["coding", "testing"], ["coding"], "compute"),
                ("cap_code_docs", "code.documentation", "Geração de documentação técnica", ["coding", "docs"], ["coding"], "generate"),
                ("cap_ext_communication", "external.communication", "Comunicação e envio de mensagens externas", ["communication", "external"], ["communication"], "external_change"),
                ("cap_research_gathering", "research.information_gathering", "Coleta e pesquisa de informações", ["research", "gathering"], ["research"], "read"),
                ("cap_research_comparative", "research.comparative_analysis", "Análise comparativa de dados", ["research", "comparison"], ["research"], "compute"),
            ]
            for cid, name, desc, tags, domains, effect in default_caps:
                self.register_capability(
                    CapabilityResource(
                        capability_id=cid,
                        name=name,
                        description=desc,
                        tags=tags,
                        domains=domains,
                        effect=effect,
                        status=ResourceStatus.DRAFT,
                        resource_origin=ResourceOrigin.TEMPLATE,
                        availability_source=AvailabilitySource.UNKNOWN,
                        is_template=True,
                        is_executable=False,
                    )
                )

            # 2. Default Providers (Templates)
            self.register_provider(
                ProviderResource(
                    provider_id="provider_gemini_ultra",
                    name="Gemini 1.5 Pro / Ultra Profile",
                    reasoning_score=0.95,
                    tool_use_support=True,
                    context_window=1000000,
                    cost_per_1k_tokens=0.002,
                    privacy_tier="high",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_anthropic_claude",
                    name="Claude 3.5 Sonnet Profile",
                    reasoning_score=0.96,
                    tool_use_support=True,
                    context_window=200000,
                    cost_per_1k_tokens=0.003,
                    privacy_tier="high",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_openai_gpt4",
                    name="GPT-4o Profile",
                    reasoning_score=0.94,
                    tool_use_support=True,
                    context_window=128000,
                    cost_per_1k_tokens=0.0025,
                    privacy_tier="standard",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_local_llama",
                    name="Local Llama 3 Edge Profile",
                    reasoning_score=0.75,
                    tool_use_support=True,
                    context_window=32000,
                    cost_per_1k_tokens=0.0001,
                    privacy_tier="high",
                    multimodal=False,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )

            # 3. Default Accounts (Templates)
            self.register_account(
                AccountResource(
                    account_id="acc_primary_gcp_01",
                    provider_id="provider_gemini_ultra",
                    name="Primary GCP Studio Enterprise Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=10,
                    cost_multiplier=1.0,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy", "enterprise"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_anthropic_prod_01",
                    provider_id="provider_anthropic_claude",
                    name="Production Anthropic Direct Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=9,
                    cost_multiplier=1.0,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_openai_backup_01",
                    provider_id="provider_openai_gpt4",
                    name="OpenAI Reserve Enterprise Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=7,
                    cost_multiplier=1.1,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_local_edge_01",
                    provider_id="provider_local_llama",
                    name="Local On-Prem Edge Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=5,
                    cost_multiplier=0.01,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy", "offline_only"],
                )
            )

            # 4. Default Execution Environments (Templates)
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_local_process",
                    type=ExecutionEnvironmentType.LOCAL_PROCESS,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["code_execution", "local_storage", "in_memory"],
                    available_tools=["python_interpreter", "file_system"],
                    network_access=True,
                    privacy_level="high",
                    latency_class="ultra_low",
                    cost_class="free",
                    resource_limits={"memory_mb": 4096, "cpu_cores": 4},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_desktop_host",
                    type=ExecutionEnvironmentType.DESKTOP,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["ui_rendering", "local_storage", "ipc_bridge"],
                    available_tools=["desktop_native", "file_system"],
                    network_access=True,
                    privacy_level="high",
                    latency_class="low",
                    cost_class="free",
                    resource_limits={"memory_mb": 8192, "cpu_cores": 8},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_cloud_server",
                    type=ExecutionEnvironmentType.CLOUD,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["scalable_compute", "cloud_storage", "remote_api"],
                    available_tools=["cloud_runner", "external_http"],
                    network_access=True,
                    privacy_level="standard",
                    latency_class="medium",
                    cost_class="medium",
                    resource_limits={"memory_mb": 16384, "cpu_cores": 16},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_remote_edge",
                    type=ExecutionEnvironmentType.EDGE,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["airgapped_compute", "edge_inference"],
                    available_tools=["edge_runner"],
                    network_access=False,
                    privacy_level="airgapped",
                    latency_class="low",
                    cost_class="low",
                    resource_limits={"memory_mb": 2048, "cpu_cores": 2},
                )
            )

            # 5. Default Agents (Templates)
            self.register_agent(
                AgentResource(
                    agent_id="agent_financial_atlas",
                    name="Atlas Financial Engine",
                    capabilities=[
                        "retrieval.financial_context",
                        "modeling.allocation_scenarios",
                        "analysis.risk_evaluation",
                        "synthesis.recommendation",
                    ],
                    specialization=["finance", "risk", "modeling"],
                    historical_confidence=0.96,
                    cost_tier=0.015,
                    latency_tier=0.25,
                    supported_domains=["finance"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_logos_synthesizer",
                    name="Logos Synthesis Agent",
                    capabilities=[
                        "synthesis.recommendation",
                        "validation.goal_alignment",
                        "external.communication",
                        "research.comparative_analysis",
                    ],
                    specialization=["synthesis", "validation", "communication"],
                    historical_confidence=0.92,
                    cost_tier=0.010,
                    latency_tier=0.15,
                    supported_domains=["finance", "communication", "general"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_code_architect",
                    name="Code Architect & Builder Agent",
                    capabilities=[
                        "code.architecture_design",
                        "code.scaffold_generation",
                        "code.ui_design",
                        "code.backend_logic",
                        "code.testing",
                        "code.documentation",
                    ],
                    specialization=["coding", "architecture", "scaffold"],
                    historical_confidence=0.94,
                    cost_tier=0.020,
                    latency_tier=0.30,
                    supported_domains=["coding"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_researcher_scout",
                    name="Deep Research Scout",
                    capabilities=[
                        "research.information_gathering",
                        "research.comparative_analysis",
                        "retrieval.financial_context",
                    ],
                    specialization=["research", "comparative"],
                    historical_confidence=0.91,
                    cost_tier=0.008,
                    latency_tier=0.20,
                    supported_domains=["research", "general"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_core_orchestrator",
                    name="Core General Agent",
                    capabilities=[
                        "retrieval.financial_context",
                        "synthesis.recommendation",
                        "validation.goal_alignment",
                        "research.information_gathering",
                        "external.communication",
                    ],
                    specialization=["general", "coordination"],
                    historical_confidence=0.88,
                    cost_tier=0.005,
                    latency_tier=0.10,
                    supported_domains=["general", "finance", "coding", "communication"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )

            # 6. Default Projects (Templates / Demo Fixtures)
            self.register_project(
                ProjectResource(
                    project_id="proj_system_core",
                    name="Intent OS Core System Workspace",
                    domain="system",
                    description="Template workspace definition for Intent OS kernel processes and system agents.",
                    owner_id="system_governor",
                    status=ResourceStatus.DRAFT,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_demo=True,
                    retention_class="permanent",
                    access_scope="organization",
                    assigned_agents=[
                        "agent_core_orchestrator",
                        "agent_code_architect",
                    ],
                    assigned_environments=[
                        "env_local_process",
                        "env_desktop_host",
                    ],
                )
            )
            self.register_project(
                ProjectResource(
                    project_id="proj_product_alpha",
                    name="Product Alpha Workspace",
                    domain="finance",
                    description="Demo fixture workspace for Atlas financial modeling and advisory missions.",
                    owner_id="user_primary",
                    status=ResourceStatus.DRAFT,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_demo=True,
                    retention_class="permanent",
                    access_scope="project",
                    assigned_agents=[
                        "agent_financial_atlas",
                        "agent_logos_synthesizer",
                        "agent_researcher_scout",
                    ],
                    assigned_environments=[
                        "env_local_process",
                        "env_cloud_server",
                    ],
                )
            )

