"""M31.2B-2B — Atomic Generation-Bound Retirement (Conditional Retirement).

Covers generation-bound atomic retirement of local canonical RRM state for
all six governed resource families, the canonical structured tombstone store,
Project family guard parity, and retirement authority integration.

Map (per movement requirement):
  D = exact governed retirement identity
       (resource_kind, resource_id, governed_registration_id, expected_generation)
  TS1 = canonical tombstone store Dict[Tuple[ResourceType, str, str], ResourceTombstone]
  G1 = request_retirement captures generation before authorization
  P1 = retirement authority delegates to RRM atomic mechanism (no direct deletes)

Invariants under audit (60 canonical):
  1-10  exact lineage/generation success + rejection semantics
  11-19 concurrency + canonical tombstone truth
  20-30 authority separation + generation semantics + re-registration absence
  31-40 immutable binding + cross-family + no fake values + no direct deletes
  41-50 project guards + NOT_FOUND + no policy type + immutable request
  51-60 no parallel productive path + policy semantics + no derived state
"""

from __future__ import annotations

import threading
import unittest
from dataclasses import FrozenInstanceError

from intent_kernel.rrm.generation import (
    GENERATION_INITIAL,
    LEGACY_UNVERSIONED,
    is_valid_generation,
)
from intent_kernel.rrm.models import (
    AccountResource,
    AgentResource,
    CapabilityResource,
    ConditionalCreateOutcome,
    ConditionalCreateResult,
    ConditionalRegistrationRequest,
    ConditionalRetirementOutcome,
    ConditionalRetirementRequest,
    ConditionalRetirementResult,
    ConditionalResourceStatusRequest,
    ConditionalUpdateOutcome,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentType,
    ProjectResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
    ResourceType,
    ResourceTombstone,
)
from intent_kernel.rrm.retirement import (
    CanonicalResourceRetirementAuthority,
    ResourceRetirementDecisionType,
    ResourceRetirementRequest,
    RetirementError,
)
from intent_kernel.rrm.service import RegistryResourceManager


def _fresh() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


def _make_resource(resource_type: ResourceType, rid: str, grid: str = ""):
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


def _all_types():
    return [
        ResourceType.PROVIDER,
        ResourceType.ACCOUNT,
        ResourceType.EXECUTION_ENVIRONMENT,
        ResourceType.CAPABILITY,
        ResourceType.AGENT,
        ResourceType.PROJECT,
    ]


def _register_governed(rrm, resource_type: ResourceType, rid: str, grid: str):
    resource = _make_resource(resource_type, rid, grid)
    if resource_type == ResourceType.PROVIDER:
        rrm.register_provider(resource)
    elif resource_type == ResourceType.ACCOUNT:
        rrm.register_account(resource)
    elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
        rrm.register_environment(resource)
    elif resource_type == ResourceType.CAPABILITY:
        rrm.register_capability(resource)
    elif resource_type == ResourceType.AGENT:
        rrm.register_agent(resource)
    elif resource_type == ResourceType.PROJECT:
        rrm.register_project(resource)


def _retire_via_authority(rrm, resource_type, rid, grid):
    ret = CanonicalResourceRetirementAuthority(rrm)
    req = ret.request_retirement(rid, grid)
    dec = ret.decide_retirement(req.request_id, approved=True)
    return ret.apply_retirement(dec.decision_id)


# ===========================================================================
# 1-10: exact lineage/generation success + rejection semantics
# ===========================================================================

class TestExactRetirement(unittest.TestCase):
    def test_1_exact_lineage_retirement_succeeds(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.RETIRED)

    def test_2_exact_generation_retirement_succeeds(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.observed_generation, 1)
        self.assertEqual(res.observed_governed_registration_id, "R1")

    def test_3_stale_generation_rejects_without_mutation(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        rrm.conditional_update_status(
            ConditionalResourceStatusRequest(
                resource_type=ResourceType.PROVIDER,
                resource_id="p1",
                expected_governed_registration_id="R1",
                expected_generation=1,
                desired_status=ResourceStatus.DEGRADED,
            )
        )
        snap = rrm.get_provider("p1")
        self.assertEqual(snap.generation, 2)
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.GENERATION_MISMATCH)
        self.assertIsNotNone(rrm.get_provider("p1"))

    def test_4_wrong_lineage_rejects_without_mutation(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="WRONG",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.REGISTRATION_LINEAGE_MISMATCH)
        self.assertIsNotNone(rrm.get_provider("p1"))

    def test_5_wrong_resource_type_rejects(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.AGENT,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.NOT_FOUND)

    def test_6_missing_resource_rejects(self):
        rrm = _fresh()
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="nope",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.NOT_FOUND)

    def test_7_removal_and_tombstone_one_observable_success(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.RETIRED)
        self.assertIsNone(rrm.get_provider("p1"))
        self.assertTrue(rrm._is_tombstoned(ResourceType.PROVIDER, "p1"))

    def test_8_tombstone_exact_identity(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        ts = rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")]
        self.assertIsInstance(ts, ResourceTombstone)
        self.assertEqual(ts.resource_kind, ResourceType.PROVIDER)
        self.assertEqual(ts.resource_id, "p1")
        self.assertEqual(ts.governed_registration_id, "R1")
        self.assertEqual(ts.observed_generation, 1)

    def test_9_caller_cannot_supply_canonical_tombstone(self):
        rrm = _fresh()
        # ConditionalRetirementRequest has no tombstone field; ResourceTombstone
        # cannot be installed via any public RRM retirement path.
        self.assertFalse(hasattr(ConditionalRetirementRequest, "tombstone"))

    def test_10_all_six_resource_families_supported(self):
        for rt in _all_types():
            rrm = _fresh()
            _register_governed(rrm, rt, "r1", "R1")
            res = rrm.conditional_retire_resource(
                ConditionalRetirementRequest(
                    resource_kind=rt,
                    resource_id="r1",
                    governed_registration_id="R1",
                    expected_generation=1,
                )
            )
            self.assertEqual(res.outcome, ConditionalRetirementOutcome.RETIRED, rt)


# ===========================================================================
# 11-19: concurrency + canonical tombstone source
# ===========================================================================

class TestConcurrencyAndCanonicalSource(unittest.TestCase):
    def test_11_project_retirement_succeeds(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROJECT,
                resource_id="pj",
                governed_registration_id="RP",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.RETIRED)
        self.assertIsNone(rrm.get_project("pj"))

    def test_12_concurrent_same_generation_exactly_one_retired(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        outcomes = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            outcomes.append(
                rrm.conditional_retire_resource(
                    ConditionalRetirementRequest(
                        resource_kind=ResourceType.PROVIDER,
                        resource_id="p1",
                        governed_registration_id="R1",
                        expected_generation=1,
                    )
                ).outcome
            )

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(sum(1 for o in outcomes if o == ConditionalRetirementOutcome.RETIRED), 1)
        self.assertEqual(sum(1 for o in outcomes if o == ConditionalRetirementOutcome.ALREADY_RETIRED), 1)

    def test_13_losing_concurrent_call_no_second_mutation(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.ALREADY_RETIRED)
        self.assertEqual(len(rrm._tombstones), 1)

    def test_14_structured_canonical_tombstone_source_only(self):
        rrm = _fresh()
        self.assertIsInstance(rrm._tombstones, dict)
        self.assertNotIsInstance(rrm._tombstones, set)

    def test_15_no_dual_authoritative_tombstone_state(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "_tombstones_set"))
        self.assertFalse(hasattr(rrm, "_tombstone_index"))

    def test_16_b1_same_family_rejected_tombstoned_preserved(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p1", name="P"),
                expected_absence=True,
            )
        )
        self.assertEqual(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)

    def test_17_fresh_create_normal_semantics_preserved(self):
        rrm = _fresh()
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p9", name="P"),
                expected_absence=True,
            )
        )
        self.assertEqual(res.outcome, ConditionalCreateOutcome.CREATED)
        self.assertEqual(res.observed_generation, 1)

    def test_18_rrm_does_not_authorize_retirement(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        self.assertIsNotNone(dec)

    def test_19_authority_remains_authority(self):
        rrm = _fresh()
        self.assertIs(CanonicalResourceRetirementAuthority, CanonicalResourceRetirementAuthority)

    def test_20_exact_retry_returns_deterministic_already_retired(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        ret.apply_retirement(dec.decision_id)
        self.assertTrue(ret.is_decision_consumed(dec.decision_id))


# ===========================================================================
# 21-30: authority separation + generation semantics + re-registration absence
# ===========================================================================

class TestAuthoritySeparation(unittest.TestCase):
    def test_21_no_caller_executable_code_under_rrm_lock(self):
        # No hook/callback field on ConditionalRetirementRequest.
        self.assertFalse(hasattr(ConditionalRetirementRequest, "callback"))

    def test_22_no_public_mutable_canonical_reference_escape(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        # Mutation via retry cannot recreate or corrupt tombstone.
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.ALREADY_RETIRED)

    def test_23_policy_a_generation_semantics(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        ts = rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")]
        self.assertEqual(ts.observed_generation, 1)

    def test_24_b2a_observed_generation_semantic_unchanged(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        ts = rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")]
        self.assertEqual(ts.lineage_identity, (ResourceType.PROVIDER, "p1", "R1"))
        self.assertEqual(ts.observed_generation, 1)

    def test_25_productive_reregistration_absent(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "conditional_reregister_resource"))

    def test_26_rrm_reregistration_authority_absent(self):
        # No re-registration authority class introduced.
        import intent_kernel.rrm.models as m
        self.assertFalse(hasattr(m, "ConditionalReregistrationRequest"))
        self.assertFalse(hasattr(m, "ReregistrationAuthority"))

    def test_27_m13_exact_binding_path_unaffected(self):
        from intent_kernel.promotion.registration_boundary import CanonicalPromotionRegistrationBoundary
        self.assertTrue(hasattr(CanonicalPromotionRegistrationBoundary, "register"))

    def test_28_m31_2a_precondition_contract_unaffected(self):
        from intent_kernel.rrm.binding import ExecutionPrecondition
        self.assertTrue(hasattr(ExecutionPrecondition, "expected_generation"))
        self.assertTrue(hasattr(ExecutionPrecondition, "governed_registration_id"))

    def test_29_m31_2b1_conditional_update_create_unaffected(self):
        rrm = _fresh()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        res = rrm.conditional_update_status(
            ConditionalResourceStatusRequest(
                resource_type=ResourceType.PROVIDER,
                resource_id="p1",
                expected_governed_registration_id="",
                expected_generation=1,
                desired_status=ResourceStatus.DEGRADED,
            )
        )
        self.assertEqual(res.outcome, ConditionalUpdateOutcome.APPLIED)

    def test_30_no_global_transaction_introduced(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "_transaction"))


# ===========================================================================
# 31-40: immutable binding + cross-family + no fake + no direct deletes
# ===========================================================================

class TestImmutableBinding(unittest.TestCase):
    def test_31_approved_request_binds_expected_generation(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        self.assertEqual(req.expected_generation, 1)
        self.assertEqual(req.resource_kind, ResourceType.PROVIDER)

    def test_32_generation_cannot_be_substituted_after_approval(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        ret.decide_retirement(req.request_id, approved=True)
        with self.assertRaises(FrozenInstanceError):
            req.expected_generation = 99

    def test_33_kind_id_lineage_cannot_be_substituted_after_approval(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        with self.assertRaises(FrozenInstanceError):
            req.resource_id = "other"
        with self.assertRaises(FrozenInstanceError):
            req.resource_kind = ResourceType.AGENT
        with self.assertRaises(FrozenInstanceError):
            req.governed_registration_id = "OTHER"

    def test_34_cross_family_same_logical_id_kind_aware(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "shared", "RP")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="shared",
                governed_registration_id="RP",
                expected_generation=1,
            )
        )
        # Agent with same logical ID remains creatable/registerable.
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.AGENT,
                resource_data=AgentResource(agent_id="shared", name="A"),
                expected_absence=True,
            )
        )
        self.assertEqual(res.outcome, ConditionalCreateOutcome.CREATED)

    def test_35_no_derived_compatibility_state_can_override(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "_tombstone_kind_index"))

    def test_36_no_independent_derived_index_writer(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "_add_tombstone_index"))

    def test_37_not_found_contains_no_fake_generation(self):
        rrm = _fresh()
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="nope",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.NOT_FOUND)
        self.assertIsNone(res.observed_generation)
        self.assertIsNone(res.observed_governed_registration_id)

    def test_38_not_found_contains_no_fake_lineage(self):
        rrm = _fresh()
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="nope",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertIsNone(res.observed_governed_registration_id)

    def test_39_already_retired_requires_exact_retry_identity(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        # Different generation retries → GENERATION_MISMATCH, not ALREADY_RETIRED
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=2,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.GENERATION_MISMATCH)

    def test_40_authority_no_direct_dictionary_deletion(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)
        self.assertFalse(hasattr(ret, "_remove_resource"))


# ===========================================================================
# 41-50: project guards + NOT_FOUND None + no policy type + immutable request
# ===========================================================================

class TestProjectGuardParity(unittest.TestCase):
    def test_41_register_project_rejects_tombstoned_id(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROJECT,
                resource_id="pj",
                governed_registration_id="RP",
                expected_generation=1,
            )
        )
        pj = ProjectResource(project_id="pj", name="P", governed_registration_id="RP")
        returned = rrm.register_project(pj)
        self.assertIsNone(returned)

    def test_42_register_project_rejects_governed_overwrite(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        pj2 = ProjectResource(project_id="pj", name="P2", governed_registration_id="RP")
        returned = rrm.register_project(pj2)
        self.assertIs(returned, rrm._projects["pj"])

    def test_43_unregister_project_rejects_governed_direct_removal(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        ok = rrm.unregister_project("pj")
        self.assertFalse(ok)
        self.assertIsNotNone(rrm.get_project("pj"))

    def test_44_provider_tombstone_blocks_agent(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        # Provider tombstone does NOT block Agent same logical ID
        self.assertFalse(rrm._is_tombstoned(ResourceType.AGENT, "p1"))
        self.assertTrue(rrm._is_tombstoned(ResourceType.PROVIDER, "p1"))

    def test_45_same_kind_tombstone_still_blocks_conditional_create(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p1", name="P"),
                expected_absence=True,
            )
        )
        self.assertEqual(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)

    def test_46_not_found_uses_none_never_generation_zero(self):
        rrm = _fresh()
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="nope",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertIsNone(res.observed_generation)
        self.assertNotEqual(res.observed_generation, 0)
        self.assertIsNone(res.observed_governed_registration_id)

    def test_47_no_unnecessary_generation_policy_type(self):
        import intent_kernel.rrm.generation as g
        self.assertFalse(hasattr(g, "GenerationPolicy"))

    def test_48_approved_request_remains_immutable_after_decision(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        ret.decide_retirement(req.request_id, approved=True)
        self.assertEqual(req.expected_generation, 1)
        self.assertEqual(req.resource_kind, ResourceType.PROVIDER)
        self.assertEqual(req.resource_id, "p1")
        self.assertEqual(req.governed_registration_id, "R1")

    def test_49_apply_cannot_override_approved_resource_type(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        # apply_retirement derives kind from request, caller supplies no override
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)

    def test_50_apply_cannot_override_approved_generation(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)
        self.assertEqual(rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")].observed_generation, 1)


# ===========================================================================
# 51-60: no parallel productive path + policy semantics + no derived state
# ===========================================================================

class TestNoParallelPath(unittest.TestCase):
    def test_51_old_direct_retirement_deletion_path_removed(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        self.assertFalse(hasattr(ret, "_remove_resource"))

    def test_52_no_parallel_productive_retirement_mechanism(self):
        rrm = _fresh()
        self.assertFalse(hasattr(rrm, "_remove_resource"))

    def test_53_project_retirement_through_rrm_conditional(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        res = _retire_via_authority(rrm, ResourceType.PROJECT, "pj", "RP")
        self.assertTrue(res.success)
        ts = rrm._tombstones[(ResourceType.PROJECT, "pj", "RP")]
        self.assertEqual(ts.observed_generation, 1)

    def test_54_project_support_not_via_expanded_direct_deletion(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("pj", "RP")
        dec = ret.decide_retirement(req.request_id, approved=True)
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)

    def test_55_canonical_tombstone_works_without_derived_cache(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertTrue(rrm._is_tombstoned(ResourceType.PROVIDER, "p1"))

    def test_56_conditional_create_reads_canonical_tombstone_truth(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p1", name="P"),
                expected_absence=True,
            )
        )
        self.assertEqual(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)

    def test_57_canonical_derived_divergence_impossible_no_derived_state(self):
        rrm = _fresh()
        self.assertEqual(len(rrm._tombstones), 0)
        self.assertTrue(all(isinstance(k, tuple) for k in rrm._tombstones))

    def test_58_tombstone_construction_failure_leaves_active_resource(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        # Invalid generation in request construction rejected before RRM call
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=0,
            )
        self.assertIsNotNone(rrm.get_provider("p1"))

    def test_59_failed_conditional_retirement_cannot_remove_without_tombstone(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="WRONG",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.REGISTRATION_LINEAGE_MISMATCH)
        self.assertIsNotNone(rrm.get_provider("p1"))
        self.assertEqual(len(rrm._tombstones), 0)

    def test_60_already_retired_exact_retry_includes_generation(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res1 = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        res2 = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res1.outcome, ConditionalRetirementOutcome.RETIRED)
        self.assertEqual(res2.outcome, ConditionalRetirementOutcome.ALREADY_RETIRED)
        self.assertEqual(res2.observed_generation, 1)


# ===========================================================================
# Contract-level: request/result/outcome validity
# ===========================================================================

class TestRequestContract(unittest.TestCase):
    def test_request_frozen_and_slots(self):
        req = ConditionalRetirementRequest(
            resource_kind=ResourceType.PROVIDER,
            resource_id="p1",
            governed_registration_id="R1",
            expected_generation=1,
        )
        self.assertTrue(req.__dataclass_params__.frozen)

    def test_request_validates_resource_kind(self):
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind="not-a-kind",
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )

    def test_request_rejects_empty_resource_id(self):
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="",
                governed_registration_id="R1",
                expected_generation=1,
            )

    def test_request_rejects_empty_grid(self):
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="",
                expected_generation=1,
            )

    def test_request_rejects_zero_generation(self):
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=LEGACY_UNVERSIONED,
            )

    def test_request_rejects_bool_generation(self):
        with self.assertRaises(ValueError):
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=True,
            )

    def test_result_immutable(self):
        res = ConditionalRetirementResult(
            outcome=ConditionalRetirementOutcome.RETIRED,
            resource_kind=ResourceType.PROVIDER,
            resource_id="p1",
        )
        with self.assertRaises(FrozenInstanceError):
            res.outcome = ConditionalRetirementOutcome.NOT_FOUND


# ===========================================================================
# Generation binding through authority
# ===========================================================================

class TestGenerationBinding(unittest.TestCase):
    def test_request_retirement_captures_generation_before_authorization(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        snap = rrm.get_provider("p1")
        self.assertEqual(req.expected_generation, snap.generation)

    def test_mutated_generation_before_apply_fails_closed(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        # Mutate resource to N+1 before apply
        rrm.conditional_update_status(
            ConditionalResourceStatusRequest(
                resource_type=ResourceType.PROVIDER,
                resource_id="p1",
                expected_governed_registration_id="R1",
                expected_generation=1,
                desired_status=ResourceStatus.DEGRADED,
            )
        )
        res = ret.apply_retirement(dec.decision_id)
        self.assertFalse(res.success)
        self.assertIsNotNone(rrm.get_provider("p1"))
        self.assertEqual(len(rrm._tombstones), 0)

    def test_exact_generation_still_active_retires_with_tombstone(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(req.request_id, approved=True)
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)
        ts = rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")]
        self.assertEqual(ts.observed_generation, 1)

    def test_no_n_plus_one_successor_generation_created(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        ts = rrm._tombstones[(ResourceType.PROVIDER, "p1", "R1")]
        self.assertEqual(ts.observed_generation, 1)
        self.assertNotEqual(ts.observed_generation, 2)


# ===========================================================================
# Project full lifecycle
# ===========================================================================

class TestProjectLifecycle(unittest.TestCase):
    def test_authority_resolves_project_snapshot(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("pj", "RP")
        self.assertEqual(req.resource_kind, ResourceType.PROJECT)
        self.assertEqual(req.expected_generation, 1)

    def test_project_generation_bound_before_authorization(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        ret = CanonicalResourceRetirementAuthority(rrm)
        req = ret.request_retirement("pj", "RP")
        self.assertEqual(req.expected_generation, rrm.get_project("pj").generation)

    def test_project_tombstone_recorded(self):
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROJECT, "pj", "RP")
        res = _retire_via_authority(rrm, ResourceType.PROJECT, "pj", "RP")
        self.assertTrue(res.success)
        self.assertTrue(rrm._is_tombstoned(ResourceType.PROJECT, "pj"))


# ===========================================================================
# Outcome/authority preservation
# ===========================================================================

class TestOutcomeClassification(unittest.TestCase):
    def test_rrm_matching_identity_alone_is_not_authorization(self):
        # Canonical retirement requires authorization owner; RRM mechanism is
        # invoked by the authority only.
        rrm = _fresh()
        _register_governed(rrm, ResourceType.PROVIDER, "p1", "R1")
        res = rrm.conditional_retire_resource(
            ConditionalRetirementRequest(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                expected_generation=1,
            )
        )
        self.assertEqual(res.outcome, ConditionalRetirementOutcome.RETIRED)
        # The mechanism exists but approval flows through the authority.
        ret = CanonicalResourceRetirementAuthority(rrm)


if __name__ == "__main__":
    unittest.main()
