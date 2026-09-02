"""M31.2B-1 — Typed Conditional Update / Create Operations (Atomic RRM).

Covers the typed conditional update and create operations on the RRM with
compare-and-mutate under a single lock.

Section mapping (per work-state):
  Update (ConditionalResourceStatusRequest) cases:
    1.  APPLIED (grid+gen match, material mutation, generation +1 exactly once)
    2.  NO_OP (already in desired status, no generation change)
    3.  NOT_FOUND (resource does not exist)
    4.  REGISTRATION_LINEAGE_MISMATCH (governed_registration_id mismatch)
    5.  GENERATION_MISMATCH (expected_generation mismatch)
    6.  INVALID_TRANSITION (terminal state refuses mutation)
    7.  All 6 resource families route through APPLIED
    8.  Absence precondition distinct from generation=0 (never conflated)
    9.  Result is detached/immutable (frozen dataclass)
    10. No-op never advances generation
    11. Exactly-one-material-mutation under concurrency

  Create (ConditionalRegistrationRequest) cases:
    1.  CREATED (fresh, generation=1, etiquette: RRM assigns generation)
    2.  CONFLICT_ACTIVE (expected absence but resource exists)
    3.  REJECTED_TOMBSTONED (tombstone refuses re-registration)
    4.  RE_REGISTRATION_AUTHORIZED (canonical prior grid+gen match)
    5.  Fresh create never trusts caller-supplied generation (RRM authority)
    6.  All 6 resource families route through CREATED
    7.  Create result is detached/immutable
    8.  Missing resource_id rejected
    9.  Concurrent creates yield exactly one CREATED
    10. TypeError data-only (no callbacks accepted by construction)

Invariant under audit:
  RRM is the single generation authority: caller supplies only
  expected_generation; RRM computes the resulting generation.
  RESOURCE STATE IDENTITY = (resource_id, governed_registration_id, generation).
"""

from __future__ import annotations

import threading
import unittest
from types import MappingProxyType

from intent_kernel.rrm.models import (
    AccountResource,
    AgentResource,
    AvailabilitySource,
    CapabilityResource,
    ConditionalCreateOutcome,
    ConditionalCreateResult,
    ConditionalRegistrationRequest,
    ConditionalResourceStatusRequest,
    ConditionalUpdateOutcome,
    ConditionalUpdateResult,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentType,
    ProjectResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
    ResourceType,
)
from intent_kernel.rrm.service import RegistryResourceManager


def _fresh() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


def _make_resource(resource_type: ResourceType, rid: str, grid: str = ""):
    """Minimal resource fixture for a given family."""
    if resource_type == ResourceType.PROVIDER:
        return ProviderResource(provider_id=rid, name=rid, governed_registration_id=grid)
    if resource_type == ResourceType.ACCOUNT:
        return AccountResource(account_id=rid, provider_id="prov", name=rid,
                               governed_registration_id=grid)
    if resource_type == ResourceType.EXECUTION_ENVIRONMENT:
        return ExecutionEnvironmentResource(environment_id=rid, type=ExecutionEnvironmentType.LOCAL_PROCESS,
                                            governed_registration_id=grid)
    if resource_type == ResourceType.CAPABILITY:
        return CapabilityResource(capability_id=rid, name=rid, governed_registration_id=grid)
    if resource_type == ResourceType.AGENT:
        return AgentResource(agent_id=rid, name=rid, governed_registration_id=grid)
    if resource_type == ResourceType.PROJECT:
        return ProjectResource(project_id=rid, name=rid, governed_registration_id=grid)
    raise ValueError(resource_type)


def _id_dim(resource_type: ResourceType):
    return {
        ResourceType.PROVIDER: "provider_id",
        ResourceType.ACCOUNT: "account_id",
        ResourceType.EXECUTION_ENVIRONMENT: "environment_id",
        ResourceType.CAPABILITY: "capability_id",
        ResourceType.AGENT: "agent_id",
        ResourceType.PROJECT: "project_id",
    }[resource_type]


def _all_types():
    return [
        ResourceType.PROVIDER,
        ResourceType.ACCOUNT,
        ResourceType.EXECUTION_ENVIRONMENT,
        ResourceType.CAPABILITY,
        ResourceType.AGENT,
        ResourceType.PROJECT,
    ]


# ===========================================================================
# Update: ConditionalResourceStatusRequest
# ===========================================================================

class TestConditionalUpdateOutcomes(unittest.TestCase):
    """16 update cases (representative set)."""

    def test_update_applied_advances_generation_exactly_once(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        snap = rrm.get_provider("p1")
        self.assertEqual(snap.generation, 1)

        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER,
            resource_id="p1",
            expected_governed_registration_id="",
            expected_generation=1,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.APPLIED)
        self.assertEqual(res.previous_status, ResourceStatus.ACTIVE)
        self.assertEqual(res.new_status, ResourceStatus.DEGRADED)
        # generation advanced exactly once: 1 -> 2
        self.assertEqual(res.observed_generation, 2)
        snap2 = rrm.get_provider("p1")
        self.assertEqual(snap2.generation, 2)
        self.assertEqual(snap2.status, ResourceStatus.DEGRADED.value)

    def test_update_noop_does_not_advance_generation(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", status=ResourceStatus.ACTIVE)
        rrm.register_provider(p)
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=1,
            desired_status=ResourceStatus.ACTIVE,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.NO_OP)
        self.assertEqual(res.observed_generation, 1)
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_update_not_found(self):
        rrm = _fresh()
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="ghost",
            expected_governed_registration_id="", expected_generation=0,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.NOT_FOUND)

    def test_update_registration_lineage_mismatch(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="WRONG", expected_generation=1,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.REGISTRATION_LINEAGE_MISMATCH)
        self.assertEqual(res.observed_governed_registration_id, "R1")
        # no mutation occurred
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_update_generation_mismatch(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="R1", expected_generation=99,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.GENERATION_MISMATCH)
        self.assertEqual(res.observed_generation, 1)
        self.assertEqual(rrm.get_provider("p1").status, ResourceStatus.ACTIVE)

    def test_update_invalid_transition_terminal(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", status=ResourceStatus.ARCHIVED)
        rrm.register_provider(p)
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=1,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        self.assertIs(res.outcome, ConditionalUpdateOutcome.INVALID_TRANSITION)
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_update_all_six_families(self):
        for rt in _all_types():
            rrm = _fresh()
            r = _make_resource(rt, "id1")
            getattr(rrm, "register_" + _api_name(rt))(_cast(r, rt))
            req = ConditionalResourceStatusRequest(
                resource_type=rt, resource_id="id1",
                expected_governed_registration_id="", expected_generation=1,
                desired_status=ResourceStatus.DEGRADED,
            )
            res = rrm.conditional_update_status(req)
            self.assertIs(res.outcome, ConditionalUpdateOutcome.APPLIED,
                          f"{rt} should APPLY")
            self.assertEqual(res.observed_generation, 2, f"{rt} gen +1 once")

    def test_update_expected_absence_is_not_generation_zero(self):
        # With expected_generation=0, RRM must NOT treat this as an absence
        # check; a present resource with gen 1 either matches (0 is "*" sentinel
        # meaning skip) or the family check governs. We assert a real resource
        # is found and that gen-0 is a skip-sentinel, never an "absent" signal.
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", status=ResourceStatus.ACTIVE)
        rrm.register_provider(p)
        req = ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=0,
            desired_status=ResourceStatus.DEGRADED,
        )
        res = rrm.conditional_update_status(req)
        # gen 0 is a skip (wildcard); since desired differs, APPLIED not NOT_FOUND
        self.assertIs(res.outcome, ConditionalUpdateOutcome.APPLIED)

    def test_update_result_is_frozen_dataclass(self):
        from dataclasses import FrozenInstanceError
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        res = rrm.conditional_update_status(ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=1,
            desired_status=ResourceStatus.DEGRADED))
        self.assertIsInstance(res, ConditionalUpdateResult)
        with self.assertRaises(FrozenInstanceError):
            res.outcome = ConditionalUpdateOutcome.NO_OP

    def test_update_observation_public_snapshot_immutable(self):
        # After a conditional update, the public get_* surface returns an
        # immutable snapshot, not a mutable canonical resource.
        from types import MappingProxyType
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        rrm.conditional_update_status(ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=1,
            desired_status=ResourceStatus.DEGRADED))
        snap = rrm.get_provider("p1")
        self.assertNotIsInstance(snap, ProviderResource)
        self.assertIsInstance(snap.metadata, MappingProxyType)

    def test_update_concurrent_exactly_one_material_mutation(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", status=ResourceStatus.ACTIVE)
        rrm.register_provider(p)
        n = 8
        outcomes = []
        lock = threading.Lock()

        def worker():
            res = rrm.conditional_update_status(ConditionalResourceStatusRequest(
                resource_type=ResourceType.PROVIDER, resource_id="p1",
                expected_governed_registration_id="", expected_generation=1,
                desired_status=ResourceStatus.DEGRADED))
            with lock:
                outcomes.append(res.outcome)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one worker wins the compare-and-mutate at gen=1.
        self.assertEqual(outcomes.count(ConditionalUpdateOutcome.APPLIED), 1)
        # Final generation = 1 (initial) + 1 (single material mutation).
        self.assertEqual(rrm.get_provider("p1").generation, 2)
        self.assertEqual(rrm.get_provider("p1").status, ResourceStatus.DEGRADED.value)


# ===========================================================================
# Create: ConditionalRegistrationRequest
# ===========================================================================

class TestConditionalCreateOutcomes(unittest.TestCase):
    """11+ create cases (representative set)."""

    def test_create_fresh_generation_one(self):
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=p,
            expected_absence=True)
        res = rrm.conditional_create_resource(req)
        self.assertIs(res.outcome, ConditionalCreateOutcome.CREATED)
        self.assertEqual(res.observed_generation, 1)
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_create_does_not_alias_or_mutate_caller_resource_data(self):
        # The caller-owned resource_data is NEVER installed as, aliased to, or
        # mutated to become the canonical resource. RRM constructs a fresh
        # canonical object from validated data.
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        p.name = "caller_name"
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=p,
            expected_absence=True)
        res = rrm.conditional_create_resource(req)
        self.assertIs(res.outcome, ConditionalCreateOutcome.CREATED)
        installed = rrm._providers["p1"]
        self.assertIsNot(installed, p, "caller object must not be installed")
        self.assertIsNot(installed, req.resource_data,
                         "request payload must not be aliased into canonical")
        # The canonical copy carries the validated data but is a distinct object.
        self.assertEqual(installed.name, "caller_name")
        self.assertEqual(installed.generation, 1)
        # The caller object was not mutated into a versioned canonical state.
        self.assertEqual(getattr(p, "generation", 0), 0)
        self.assertEqual(p.governed_registration_id, "")

    def test_create_fresh_rejects_caller_governed_lineage(self):
        # Governed lineage may NOT be supplied by the caller for a new
        # creation — REJECTED at request construction, before any productive
        # mutation. No resource installed, no generation allocated, no
        # governed_registration_id generated.
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1", grid="CALLER_GRID")
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=p,
                expected_absence=True)
        # nothing was created, no generation allocated, no lineage generated
        self.assertIsNone(rrm.get_provider("p1"))
        self.assertNotIn("p1", rrm._providers)

    def test_create_fresh_rejects_caller_generation(self):
        # Caller may NOT supply a resulting generation; RRM computes it.
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        with self.assertRaises((TypeError, ValueError)):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=p,
                expected_absence=True, expected_generation=5)
        # A resource carrying a pre-set generation is ALSO rejected at
        # construction (caller cannot smuggle a resulting generation).
        p2 = _make_resource(ResourceType.PROVIDER, "p2")
        p2.generation = 999
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=p2,
                expected_absence=True)
        self.assertIsNone(rrm.get_provider("p2"))

    def test_create_conflict_active_when_expected_absence(self):
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        rrm.register_provider(p)
        # Use a fresh request resource (registered `p` now carries generation 1).
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=_make_resource(ResourceType.PROVIDER, "p1"),
            expected_absence=True)
        res = rrm.conditional_create_resource(req)
        self.assertIs(res.outcome, ConditionalCreateOutcome.CONFLICT_ACTIVE)

    def test_create_rejected_tombstoned(self):
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        rrm.register_provider(p)
        rrm._record_tombstone(ResourceType.PROVIDER, "p1", "R1", 1)
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=_make_resource(ResourceType.PROVIDER, "p1"),
            expected_absence=True)
        res = rrm.conditional_create_resource(req)
        self.assertIs(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)

    def test_create_re_registration_not_authorized(self):
        # RRM does NOT authorize re-registration. A matching expected old
        # governed_registration_id + old generation proves identity/freshness
        # only — it does NOT confer authorization to re-create the identity.
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1", grid="R1")
        rrm.register_provider(p)
        try:
            # expected_absence=False (re-registration) is rejected at request
            # construction in M31.2B-1.
            new = _make_resource(ResourceType.PROVIDER, "p1")
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=new,
                expected_absence=False,
                expected_governed_registration_id="R1",
                expected_generation=1)
            self.fail("expected ValueError for re-registration request")
        except ValueError:
            pass
        # The active resource remains untouched; no new registration was made.
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_create_false_re_registration_authority_fails_closed(self):
        # A retired / tombstoned identity does NOT authorize re-creation even
        # if the prior governed registration lineage is known. Result is a
        # fail-closed outcome; no resource installed, no new lineage, no
        # generation assigned, tombstone intact.
        from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1", grid="R1")
        rrm.register_provider(p)
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        ret.apply_retirement(dec.decision_id)
        # Tombstoned identity now fails the create closed (caller supplies no
        # lineage; identity id alone is refused).
        res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER,
            resource_data=_make_resource(ResourceType.PROVIDER, "p1"),
            expected_absence=True))
        self.assertIs(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)
        # no new active registration installed
        self.assertIsNone(rrm.get_provider("p1"))
        # tombstone intact (canonical structured store)
        self.assertIn((ResourceType.PROVIDER, "p1", "R1"), rrm._tombstones)

    def test_create_identity_match_does_not_confer_authority(self):
        # Correct old lineage + correct old generation can prove WHICH prior
        # registration is referenced, but cannot produce re-registration
        # authorization. No M31.2B-1 path returns RE_REGISTRATION_AUTHORIZED.
        rrm = _fresh()
        # Pre-existing governed identity is present in the RRM.
        p = _make_resource(ResourceType.PROVIDER, "p1", grid="R1")
        rrm.register_provider(p)
        # A live active identity still collides — expected lineage/identity
        # alone does NOT authorize replacement. (Caller supplies no lineage;
        # the request boundary rejects authority-bearing lineage.)
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER,
            resource_data=_make_resource(ResourceType.PROVIDER, "p1"),
            expected_absence=True)
        res = rrm.conditional_create_resource(req)
        self.assertIs(res.outcome, ConditionalCreateOutcome.CONFLICT_ACTIVE)
        # No productive M31.2B-1 code path may emit RE_REGISTRATION_AUTHORIZED.
        self.assertNotIn(ConditionalCreateOutcome.RE_REGISTRATION_AUTHORIZED,
                         self._producible_outcomes())

    def _producible_outcomes(self):
        """Collect all ConditionalCreateOutcome values ever returned by the
        service for a matrix of create requests, to prove the reserved
        RE_REGISTRATION_AUTHORIZED outcome is never produced."""
        from intent_kernel.rrm.models import (
            ResourceType, ConditionalCreateOutcome,
        )
        produced = set()
        for rt in [ResourceType.PROVIDER, ResourceType.ACCOUNT,
                   ResourceType.EXECUTION_ENVIRONMENT, ResourceType.CAPABILITY,
                   ResourceType.AGENT, ResourceType.PROJECT]:
            rrm = _fresh()
            rid = "id_" + rt.value
            res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
                resource_type=rt, resource_data=_make_resource(rt, rid),
                expected_absence=True))
            produced.add(res.outcome)
            # tombstoned path
            rrm2 = _fresh()
            rrm2._record_tombstone(rt, rid, "R-tomb", 1)
            res2 = rrm2.conditional_create_resource(ConditionalRegistrationRequest(
                resource_type=rt, resource_data=_make_resource(rt, rid),
                expected_absence=True))
            produced.add(res2.outcome)
            # conflict path: register then attempt create on same fresh id
            rrm3 = _fresh()
            getattr(rrm3, "register_" + _api_name(rt))( _make_resource(rt, rid))
            res3 = rrm3.conditional_create_resource(ConditionalRegistrationRequest(
                resource_type=rt, resource_data=_make_resource(rt, rid),
                expected_absence=True))
            produced.add(res3.outcome)
        return produced

    def test_create_re_registration_requires_grid(self):
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1", grid="R1")
        rrm.register_provider(p)
        new = _make_resource(ResourceType.PROVIDER, "p1", grid="R1")
        # expected_absence=False is rejected at construction in M31.2B-1
        # (RRM does not authorize re-registration).
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=new,
                expected_absence=False, expected_governed_registration_id="",
                expected_generation=1)

    def test_create_all_six_families(self):
        for rt in _all_types():
            rrm = _fresh()
            r = _make_resource(rt, "id1")
            req = ConditionalRegistrationRequest(
                resource_type=rt, resource_data=_cast(r, rt),
                expected_absence=True)
            res = rrm.conditional_create_resource(req)
            self.assertIs(res.outcome, ConditionalCreateOutcome.CREATED, f"{rt}")
            self.assertEqual(res.observed_generation, 1, f"{rt} gen=1")

    def test_create_result_is_frozen_dataclass(self):
        from dataclasses import FrozenInstanceError
        rrm = _fresh()
        p = _make_resource(ResourceType.PROVIDER, "p1")
        res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=p,
            expected_absence=True))
        self.assertIsInstance(res, ConditionalCreateResult)
        with self.assertRaises(FrozenInstanceError):
            res.outcome = ConditionalCreateOutcome.CREATED

    def test_create_missing_id_rejected(self):
        rrm = _fresh()
        # resource without an id value for its family => not created
        p = _make_resource(ResourceType.PROVIDER, "id1")
        req = ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER, resource_data=p,
            expected_absence=True)
        # force the id to be empty on the data object
        p.provider_id = ""
        res = rrm.conditional_create_resource(req)
        self.assertIsNot(res.outcome, ConditionalCreateOutcome.CREATED)

    def test_create_concurrent_exactly_one_created(self):
        rrm = _fresh()
        results = []
        lock = threading.Lock()

        def worker():
            p = _make_resource(ResourceType.PROVIDER, "p1")
            res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=p,
                expected_absence=True))
            with lock:
                results.append(res.outcome)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results.count(ConditionalCreateOutcome.CREATED), 1)
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_expected_absence_requires_empty_grid_and_gen(self):
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER, resource_data=object(),
                expected_absence=True, expected_governed_registration_id="R1")


# ===========================================================================
# RA-31.2B1-03: Canonical Deep-Detach (caller input graph != canonical graph)
# ===========================================================================

class TestCanonicalDeepDetach(unittest.TestCase):
    """Recursive detachment of caller-owned mutable data from canonical state."""

    def _fresh_metadata(self):
        # Build a NEW deep structure per call so tests never pollute one another.
        return {
            "level1": {
                "level2": {"value": "original"},
            },
            "items": [
                {"name": "A", "tags": ["a1", "a2"]},
                {"name": "B", "tags": ["b1"]},
            ],
            "mixed": {"a": [1, {"b": 2}], "tup": (["x"], {3: 4})},
            "setval": {5, 6},
        }

    def _create_with(self, rrm, rt, rid, grid=""):
        r = _make_resource(rt, rid, grid=grid)
        r.metadata = self._fresh_metadata()
        res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
            resource_type=rt, resource_data=r, expected_absence=True))
        assert res.outcome is ConditionalCreateOutcome.CREATED, res.outcome
        return r, res

    def _observable(self, rrm, rt, rid):
        return getattr(rrm, f"get_{_api_name(rt)}")(rid)

    def test_nested_dict_mutation_cannot_affect_canonical(self):
        rrm = _fresh()
        caller, _ = self._create_with(rrm, ResourceType.PROVIDER, "p1")
        caller.metadata["level1"]["level2"]["value"] = "attacker-change"
        # canonical + snapshot must be unaffected
        self.assertEqual(rrm._providers["p1"].metadata["level1"]["level2"]["value"],
                         "original")
        self.assertEqual(self._observable(rrm, ResourceType.PROVIDER, "p1")
                         .metadata["level1"]["level2"]["value"], "original")

    def test_nested_list_mutation_cannot_affect_canonical(self):
        rrm = _fresh()
        caller, _ = self._create_with(rrm, ResourceType.PROVIDER, "p1")
        caller.metadata["items"].append({"name": "C"})
        caller.metadata["items"][0]["name"] = "HACKED"
        caller.metadata["items"][0]["tags"].append("evil")
        canon = rrm._providers["p1"].metadata
        self.assertEqual([i["name"] for i in canon["items"]], ["A", "B"])
        self.assertNotIn("HACKED", [i["name"] for i in canon["items"]])
        self.assertNotIn("evil", canon["items"][0]["tags"])

    def test_mixed_nested_containers_cannot_affect_canonical(self):
        rrm = _fresh()
        caller, _ = self._create_with(rrm, ResourceType.ACCOUNT, "a1")
        m = caller.metadata
        m["mixed"]["a"].append(99)                      # list in dict
        m["mixed"]["a"][1]["b"] = 999                   # dict in list in dict
        m["mixed"]["tup"][0].append("evil")             # mutable element in tuple
        m["mixed"]["tup"][1][3] = 888                   # dict in tuple
        m["setval"].add(999)                            # set
        canon = rrm._accounts["a1"].metadata
        self.assertEqual(canon["mixed"]["a"], [1, {"b": 2}])
        self.assertEqual(canon["mixed"]["tup"], (["x"], {3: 4}))
        self.assertEqual(canon["setval"], {5, 6})

    def test_caller_not_aliased_to_canonical_any_depth(self):
        rrm = _fresh()
        caller, _ = self._create_with(rrm, ResourceType.PROVIDER, "p1")
        canon = rrm._providers["p1"]
        store = [rrm._providers["p1"].metadata]
        # walk both graphs to assert no shared mutable container
        self.assertIsNot(canon, caller)
        self.assertIsNot(canon.metadata, caller.metadata)
        self.assertIsNot(canon.metadata["items"], caller.metadata["items"])
        self.assertIsNot(canon.metadata["items"][0], caller.metadata["items"][0])
        self.assertIsNot(canon.metadata["mixed"], caller.metadata["mixed"])

    def test_canonical_mutation_does_not_alter_caller_input(self):
        # Mutate canonical through an authorized RRM mutation (status update)
        # and verify the caller's retained graph stays untouched.
        rrm = _fresh()
        caller, _ = self._create_with(rrm, ResourceType.PROVIDER, "p1")
        before = dict(caller.metadata)
        res = rrm.conditional_update_status(ConditionalResourceStatusRequest(
            resource_type=ResourceType.PROVIDER, resource_id="p1",
            expected_governed_registration_id="", expected_generation=1,
            desired_status=ResourceStatus.DEGRADED))
        self.assertIs(res.outcome, ConditionalUpdateOutcome.APPLIED)
        self.assertEqual(caller.metadata, before)
        self.assertEqual(caller.metadata["level1"]["level2"]["value"], "original")
        self.assertEqual(caller.generation, 0)  # caller never advanced by RRM

    def test_snapshot_nested_escape_blocked(self):
        # The public snapshot's metadata is deeply detached from canonical, so
        # mutating nested containers through the snapshot must NOT change
        # canonical state (PUBLIC_SNAPSHOT_NESTED_ALIAS_ESCAPE=NO).
        rrm = _fresh()
        self._create_with(rrm, ResourceType.PROVIDER, "p1")
        snap = rrm.get_provider("p1")
        self.assertIsInstance(snap.metadata, MappingProxyType)
        self.assertIsNot(snap.metadata["level1"],
                         rrm._providers["p1"].metadata["level1"])
        snap.metadata["level1"]["level2"]["value"] = "escaped"
        snap.metadata["items"][0]["name"] = "escaped-item"
        self.assertEqual(rrm._providers["p1"].metadata["level1"]["level2"]["value"],
                         "original")
        self.assertEqual(rrm._providers["p1"].metadata["items"][0]["name"], "A")

    def test_all_six_families_deep_detached(self):
        store_attr = {
            ResourceType.PROVIDER: "_providers",
            ResourceType.ACCOUNT: "_accounts",
            ResourceType.EXECUTION_ENVIRONMENT: "_environments",
            ResourceType.CAPABILITY: "_capabilities",
            ResourceType.AGENT: "_agents",
            ResourceType.PROJECT: "_projects",
        }
        for rt in _all_types():
            rrm = _fresh()
            caller, _ = self._create_with(rrm, rt, "id1")
            canon_id = getattr(rrm, store_attr[rt])["id1"]
            self.assertIsNot(canon_id, caller, rt)
            self.assertIsNot(canon_id.metadata, caller.metadata, rt)
            caller.metadata["level1"]["level2"]["value"] = "attacker-change"
            self.assertEqual(canon_id.metadata["level1"]["level2"]["value"],
                             "original", rt)

    def test_unsupported_arbitrary_object_fails_closed(self):
        # A caller-defined object is NOT deep-copied (no __deepcopy__/__reduce__
        # hook runs under the RRM lock) — it is refused fail-closed.
        from intent_kernel.rrm.service import _detach_value
        class Custom:
            def __deepcopy__(self, memo):
                raise AssertionError("deepcopy hook must NOT run under RRM lock")
            def __reduce__(self):
                raise AssertionError("reduce hook must NOT run")
        with self.assertRaises(ValueError):
            _detach_value(Custom())

    def test_caller_lineage_generation_tombstone_still_fail_closed(self):
        # RA-31.2B1-01 / 02 remain closed after deep-detach change.
        rrm = _fresh()
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=_make_resource(ResourceType.PROVIDER, "p1", grid="R1"),
                expected_absence=True)  # caller lineage rejected
        with self.assertRaises(ValueError):
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p2", name="p2",
                                               generation=7),
                expected_absence=True)  # caller generation rejected
        p = _make_resource(ResourceType.PROVIDER, "p1")
        rrm.register_provider(p)
        # M31.2B-2B: canonical structured tombstone store (kind-aware)
        rrm._record_tombstone(ResourceType.PROVIDER, "p1", "R1", 1)
        res = rrm.conditional_create_resource(ConditionalRegistrationRequest(
            resource_type=ResourceType.PROVIDER,
            resource_data=_make_resource(ResourceType.PROVIDER, "p1"),
            expected_absence=True))
        self.assertIs(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)


# ===========================================================================
# Helpers used by the classes above
# ===========================================================================

def _api_name(rt):
    return {
        ResourceType.PROVIDER: "provider",
        ResourceType.ACCOUNT: "account",
        ResourceType.EXECUTION_ENVIRONMENT: "environment",
        ResourceType.CAPABILITY: "capability",
        ResourceType.AGENT: "agent",
        ResourceType.PROJECT: "project",
    }[rt]


def _cast(r, rt):
    # Already an instance of the concrete family class; register_<family>
    # accepts the canonical resource objects directly.
    return r


if __name__ == "__main__":
    unittest.main()
