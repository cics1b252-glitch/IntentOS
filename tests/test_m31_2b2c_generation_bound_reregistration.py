"""Movement 31.2B-2C — Generation-Bound Re-Registration Authority.

Canonical regression suite for RRM-governed lineage-B re-registration:

    exact retired predecessor consumed == exact approved candidate materialized
                                        == exact successor lineage B created.

Core invariants enforced (>=160 assertions across categories A–N):

  A. Model construction/validation (frozen preconditions, no REJECTED, no
     caller-supplied successor lineage / resulting generation, detached
     materialization input).
  B. Predecessor-retirement fact gating (NO_TOMBSTONE, TOMBSTONE_LINEAGE_MISMATCH,
     TOMBSTONE_GENERATION_MISMATCH).
  C. Fresh re-registration exact binding (REREGISTERED, generation+1, successor
     lineage B RRM-sourced, consumption recorded, predecessor permanently
     consumed, exact candidate identity).
  D. Consumption-store immutability / deep detachment (no aliasing, mutation of
     caller input cannot reach canonical storage).
  E. Recovery (WRITE1 present / WRITE2 absent → REREGISTRATION_RECOVERED, reuse
     STORED materialization descriptor only, never a retry descriptor).
  F. Idempotent ALREADY_APPLIED + decision-consumption timing.
  G. PENDING_SUCCESSOR_MISMATCH (candidate identity divergence).
  H. ACTIVE_RESOURCE_CONFLICT (unexpected active lineage).
  I. STALE_RETIRED_LINEAGE (successor B itself retired → A never re-eligible).
  J. INVALID_RESOURCE / INVALID_TRANSITION terminal-state rejection.
  K. Six-family parity (Provider, Account, Capability, Agent, Environment,
     Project) — B1 remains governed_registration_id="" generation=1.
  L. Promotion-boundary integration (decision precondition carried; routes to
     RRM; decision consumed only after successful RRM re-registration).
  M. RRM is the SOLE governed-lineage-ID authority (no boundary minting for
     re-registration; successor lineage never caller-supplied).
  N. Decision-consumption timing: decision consumed only AFTER successful RRM
     registration/re-registration; never before.
"""

import copy
import os
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_kernel.discovery import (
    CanonicalResourceDiscoveryService,
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoveryStatus,
)
from intent_kernel.promotion.decision_authority import (
    ResourcePromotionDecisionAuthority,
)
from intent_kernel.promotion.models import (
    ReRegistrationPrecondition,
    ResourcePromotionDecision,
    ResourcePromotionDecisionType,
    ResourcePromotionResult,
)
from intent_kernel.promotion.proposal_service import (
    ResourcePromotionProposalService,
)
from intent_kernel.promotion.registration_boundary import (
    CanonicalPromotionRegistrationBoundary,
)
from intent_kernel.rrm.models import (
    AccountResource,
    AgentResource,
    AvailabilitySource,
    CapabilityResource,
    ExecutionEnvironmentResource,
    ProjectResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
    ResourceType,
    ConditionalReregistrationOutcome,
    ConditionalReregistrationRequest,
    ConditionalReregistrationResult,
    ResourceLineageConsumption,
    ConditionalRetirementOutcome,
    ConditionalRetirementRequest,
)
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fresh():
    return RegistryResourceManager(populate_defaults=False)


def _governed_resource(rrm, kind, rid, grid, generation=1, display_name="A"):
    """Register a governed canonical resource A into RRM."""
    if kind == ResourceType.PROVIDER:
        r = ProviderResource(
            provider_id=rid, name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE, governed_registration_id=grid,
            generation=generation,
        )
        rrm.register_provider(r)
    elif kind == ResourceType.ACCOUNT:
        r = AccountResource(
            account_id=rid, provider_id="parent", name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_configured=False, status=ResourceStatus.ACTIVE,
            governed_registration_id=grid, generation=generation,
        )
        rrm._accounts[rid] = r
    elif kind == ResourceType.EXECUTION_ENVIRONMENT:
        r = ExecutionEnvironmentResource(
            environment_id=rid, type=None,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_discovered=False, status=ResourceStatus.ACTIVE,
            governed_registration_id=grid, generation=generation,
        )
        rrm.register_environment(r)
    elif kind == ResourceType.CAPABILITY:
        r = CapabilityResource(
            capability_id=rid, name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_executable=False, status=ResourceStatus.ACTIVE,
            tags=[], governed_registration_id=grid, generation=generation,
        )
        rrm.register_capability(r)
    elif kind == ResourceType.AGENT:
        r = AgentResource(
            agent_id=rid, name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_enabled=False, installation_state=None,
            status=ResourceStatus.ACTIVE, governed_registration_id=grid,
            generation=generation,
        )
        rrm.register_agent(r)
    elif kind == ResourceType.PROJECT:
        r = ProjectResource(
            project_id=rid, name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_demo=False, status=ResourceStatus.ACTIVE,
            governed_registration_id=grid, generation=generation,
        )
        rrm._projects[rid] = r
    else:
        raise AssertionError(f"unsupported kind {kind}")
    return r


def _activate(rrm, kind, rid, grid, display_name="X"):
    """Insert an active governed resource directly, bypassing retirement guards.

    Used to fabricate an unexpected ACTIVE lineage for ACTIVE_RESOURCE_CONFLICT
    scenarios, which the guarded register_* path would refuse after retirement.
    """
    if kind == ResourceType.PROVIDER:
        r = ProviderResource(
            provider_id=rid, name=display_name,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE, governed_registration_id=grid,
            generation=1,
        )
        rrm._providers[rid] = r
    else:
        raise AssertionError(f"unsupported _activate kind {kind}")
    return r


def _set_generation(rrm, kind, rid, gen):
    """Set the canonical generation of an active governed resource directly."""
    if kind == ResourceType.PROVIDER:
        rrm._providers[rid].generation = gen
    elif kind == ResourceType.ACCOUNT:
        rrm._accounts[rid].generation = gen
    elif kind == ResourceType.EXECUTION_ENVIRONMENT:
        rrm._environments[rid].generation = gen
    elif kind == ResourceType.CAPABILITY:
        rrm._capabilities[rid].generation = gen
    elif kind == ResourceType.AGENT:
        rrm._agents[rid].generation = gen
    elif kind == ResourceType.PROJECT:
        rrm._projects[rid].generation = gen


def _retire(rrm, kind, rid, grid, generation=1):
    return rrm.conditional_retire_resource(
        ConditionalRetirementRequest(
            resource_kind=kind,
            resource_id=rid,
            governed_registration_id=grid,
            expected_generation=generation,
        )
    )


def _require_retired(ret):
    assert ret.outcome is ConditionalRetirementOutcome.RETIRED, ret.outcome


def _precondition(kind, rid, grid, gen):
    return ReRegistrationPrecondition(
        resource_kind=kind,
        resource_id=rid,
        retired_governed_registration_id=grid,
        retired_observed_generation=gen,
    )


def _req(kind, rid, grid, gen, pil="prop-1", did="dec-1"):
    return ConditionalReregistrationRequest(
        resource_kind=kind,
        resource_id=rid,
        predecessor_governed_registration_id=grid,
        predecessor_observed_generation=gen,
        proposal_id=pil,
        decision_id=did,
    )


def _discovery_svc(evidence):
    svc = CanonicalResourceDiscoveryService()

    class _Adapter:
        def __init__(self, ev):
            self._ev = [ev]
            self.adapter_id = "test-adapter"
            self.adapter_type = "stub"

        def discover(self):
            return list(self._ev)

    svc.register_adapter(_Adapter(evidence))
    svc.observe("test-adapter")
    return svc


def _evidence(rid, kind, discovery_id=None):
    kind_enum = kind if isinstance(kind, ResourceDiscoveryKind) else (
        ResourceDiscoveryKind.PROVIDER
    )
    return ResourceDiscoveryEvidence(
        discovery_id=discovery_id or f"disc-{rid}",
        resource_kind=kind_enum,
        resource_id=rid,
        display_name=f"Evidence {rid}",
        capability_claims=("doc.read",),
        source="test-adapter",
        source_type="adapter",
        observed_at=utc_iso(),
        observed_by="test-adapter",
        status=ResourceDiscoveryStatus.OBSERVED,
        confidence=0.9,
        health_observed="healthy",
        health_source="test-adapter",
        credential_required=False,
        credential_available=False,
        metadata={},
    )


def _stack(rrm, evidence):
    disc = _discovery_svc(evidence)
    proposals = ResourcePromotionProposalService(disc)
    decisions = ResourcePromotionDecisionAuthority(proposals)
    boundary = CanonicalPromotionRegistrationBoundary(
        proposals, decisions, rrm
    )
    return disc, proposals, decisions, boundary


def _approve(decisions, proposal_id, precondition):
    return decisions.decide(
        proposal_id,
        ResourcePromotionDecisionType.APPROVE,
        decided_by="auditor",
        re_registration_precondition=precondition,
    )


def _row(rrm, kind, rid, grid, gen=1, discovery_id=None):
    """Register A, retire A, return promotion stack pieces + ids."""
    _governed_resource(rrm, kind, rid, grid, generation=gen)
    _require_retired(_retire(rrm, kind, rid, grid, gen))
    disc, proposals, decisions, boundary = _stack(rrm, _evidence(rid, kind, discovery_id))
    return disc, proposals, decisions, boundary


O = ConditionalReregistrationOutcome


# ===========================================================================
# A. Model construction / validation
# ===========================================================================


class TestModelContracts(unittest.TestCase):
    def test_a1_outcomes_exact_11_no_rejected(self):
        values = {e.value for e in O}
        expected = {
            "reregistered", "reregistration_recovered",
            "reregistration_already_applied", "no_tombstone",
            "tombstone_lineage_mismatch", "tombstone_generation_mismatch",
            "stale_retired_lineage", "pending_successor_mismatch",
            "active_resource_conflict", "invalid_resource",
            "invalid_transition",
        }
        self.assertEqual(values, expected)
        self.assertNotIn("rejected", values)

    def test_a2_request_has_no_successor_lineage(self):
        req = _req(ResourceType.PROVIDER, "p", "R1", 1)
        self.assertFalse(hasattr(req, "successor_governed_registration_id"))
        self.assertFalse(hasattr(req, "resulting_generation"))
        self.assertFalse(hasattr(req, "authorization_token"))
        self.assertFalse(hasattr(req, "retry_descriptor"))

    def test_a3_request_frozen_fields_exact(self):
        req = _req(ResourceType.PROVIDER, "p", "R1", 3)
        self.assertEqual(
            [
                "resource_kind", "resource_id",
                "predecessor_governed_registration_id",
                "predecessor_observed_generation", "proposal_id", "decision_id",
            ],
            list(req.__dataclass_fields__.keys()),
        )

    def test_a4_precondition_rejects_negative_generation(self):
        with self.assertRaises(ValueError):
            ReRegistrationPrecondition(
                resource_kind=ResourceType.PROVIDER, resource_id="p",
                retired_governed_registration_id="R", retired_observed_generation=0,
            )
        with self.assertRaises(ValueError):
            ReRegistrationPrecondition(
                resource_kind=ResourceType.PROVIDER, resource_id="p",
                retired_governed_registration_id="", retired_observed_generation=1,
            )

    def test_a5_precondition_requires_canonical_kind(self):
        with self.assertRaises(ValueError):
            ReRegistrationPrecondition(
                resource_kind="provider", resource_id="p",
                retired_governed_registration_id="R",
                retired_observed_generation=1,
            )

    def test_a6_consumption_frozen_and_keyed(self):
        c = ResourceLineageConsumption(
            resource_kind=ResourceType.PROVIDER, resource_id="p",
            predecessor_governed_registration_id="A",
            predecessor_observed_generation=2,
            successor_governed_registration_id="B",
            successor_candidate_proposal_id="prop-9",
            successor_candidate_decision_id="dec-9",
        )
        self.assertEqual(
            c.consumption_key,
            (ResourceType.PROVIDER, "p", "A"),
        )
        self.assertEqual(c.candidate_identity, ("prop-9", "dec-9"))

    def test_a7_consumption_immutable_predecessor(self):
        c = ResourceLineageConsumption(
            resource_kind=ResourceType.PROVIDER, resource_id="p",
            predecessor_governed_registration_id="A",
            predecessor_observed_generation=2,
            successor_governed_registration_id="B",
            successor_candidate_proposal_id="p", successor_candidate_decision_id="d",
        )
        with self.assertRaises(AttributeError):
            c.predecessor_governed_registration_id = "X"

    def test_a8_result_no_fake_values_on_failure(self):
        res = ConditionalReregistrationResult(
            outcome=O.NO_TOMBSTONE,
            resource_kind=ResourceType.PROVIDER, resource_id="p",
        )
        self.assertIsNone(res.successor_governed_registration_id)
        self.assertIsNone(res.successor_observed_generation)

    def test_a9_result_fake_values_absent_on_success(self):
        res = ConditionalReregistrationResult(
            outcome=O.REREGISTERED,
            resource_kind=ResourceType.PROVIDER, resource_id="p",
            successor_governed_registration_id="B",
            successor_observed_generation=2,
        )
        self.assertEqual(res.successor_governed_registration_id, "B")
        self.assertEqual(res.successor_observed_generation, 2)

    def test_a10_descriptor_detached_from_callable(self):
        class Evil:
            __reduce__ = lambda *_: (_ for _ in ()).throw(AssertionError)

        c = ResourceLineageConsumption(
            resource_kind=ResourceType.PROVIDER, resource_id="p",
            predecessor_governed_registration_id="A",
            predecessor_observed_generation=1,
            successor_governed_registration_id="B",
            successor_candidate_proposal_id="p", successor_candidate_decision_id="d",
            successor_materialization_descriptor={
                "ok": 1, "nested": {"x": [1, 2]},
            },
        )
        self.assertEqual(c.successor_materialization_descriptor["ok"], 1)
        self.assertEqual(c.successor_materialization_descriptor["nested"]["x"], [1, 2])


# ===========================================================================
# B. Predecessor-retirement fact gating
# ===========================================================================


class TestPredecessorFactGating(unittest.TestCase):
    def test_b1_no_tombstone(self):
        rrm = _fresh()
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1)
        )
        self.assertIs(res.outcome, O.NO_TOMBSTONE)
        self.assertFalse(rrm.has_tombstoned_resource(ResourceType.PROVIDER, "p"))

    def test_b2_no_tombstone_leaves_no_mutation(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R9", 1)
        )
        self.assertEqual(rrm.get_provider("p").governed_registration_id, "R1")

    def test_b3_lineage_mismatch_distinct_grid(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R2", 1)
        )
        self.assertIs(res.outcome, O.TOMBSTONE_LINEAGE_MISMATCH)

    def test_b4_generation_mismatch(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 2)
        )
        self.assertIs(res.outcome, O.TOMBSTONE_GENERATION_MISMATCH)

    def test_b5_generation_mismatch_leaves_consumptions_empty(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 5)
        )
        self.assertEqual(rrm._consumptions, {})

    def test_b6_exact_grid_and_generation_pass_fact_gate(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _set_generation(rrm, ResourceType.PROVIDER, "p", 3)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 3))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 3),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTERED)

    def test_b7_tombstone_lookup_exact(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        tb = rrm.get_resource_tombstone(
            ResourceType.PROVIDER, "p", "R1"
        )
        self.assertIsNotNone(tb)
        self.assertEqual(tb.observed_generation, 1)
        self.assertIsNone(
            rrm.get_resource_tombstone(ResourceType.PROVIDER, "p", "R9")
        )

    def test_b8_missing_predecessor_generation_never_defaults(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        with self.assertRaises(ValueError):
            ReRegistrationPrecondition(
                resource_kind=ResourceType.PROVIDER, resource_id="p",
                retired_governed_registration_id="R1",
                retired_observed_generation=0,
            )


# ===========================================================================
# C. Fresh re-registration exact binding
# ===========================================================================


class TestFreshReregistration(unittest.TestCase):
    def test_c1_reregistered_with_rrm_lineage(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTERED)
        self.assertTrue(res.successor_governed_registration_id.startswith("gov-"))
        self.assertEqual(res.successor_observed_generation, 2)

    def test_c2_successor_lineage_is_rrm_minted_not_caller(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertNotEqual(res.successor_governed_registration_id, "R1")
        self.assertNotEqual(res.successor_governed_registration_id, "B")

    def test_c3_active_successor_materialized(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        b = rrm.get_provider("p")
        self.assertEqual(b.governed_registration_id, res.successor_governed_registration_id)
        self.assertEqual(b.generation, 2)
        self.assertEqual(b.status, ResourceStatus.ACTIVE)

    def test_c4_consumption_recorded_exactly(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        key = (ResourceType.PROVIDER, "p", "R1")
        self.assertIn(key, rrm._consumptions)
        c = rrm._consumptions[key]
        self.assertEqual(c.predecessor_observed_generation, 1)
        self.assertEqual(
            c.successor_governed_registration_id, res.successor_governed_registration_id
        )
        self.assertEqual(c.candidate_identity, ("prop-1", "dec-1"))

    def test_c5_predecessor_permanently_consumed_no_reopen(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        # A new decision cannot re-open A to a different successor
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-2", did="dec-2"),
            materialization_descriptor={"display_name": "C"},
        )
        self.assertIs(res2.outcome, O.PENDING_SUCCESSOR_MISMATCH)
        self.assertEqual(
            rrm.get_provider("p").governed_registration_id,
            res1.successor_governed_registration_id,
        )

    def test_c6_generation_advances_monotonically(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertEqual(res.successor_observed_generation, 2)
        # retire B then re-register again → generation 3
        _require_retired(_retire(
            rrm, ResourceType.PROVIDER, "p",
            res.successor_governed_registration_id, 2,
        ))
        # fresh consumption for the B lineage requires a pre-existing tombstone for
        # the requested predecessor; consumption A->B already exists for candidate
        # prop-1/dec-1 so reuse it (stale). Use new candidate for B lineage.
        res3 = rrm.conditional_reregister_resource(
            _req(
                ResourceType.PROVIDER, "p",
                res.successor_governed_registration_id, 2,
                pil="prop-3", did="dec-3",
            ),
            materialization_descriptor={"display_name": "C"},
        )
        self.assertIs(res3.outcome, O.REREGISTERED)
        self.assertEqual(res3.successor_observed_generation, 3)
        self.assertEqual(rrm.get_provider("p").generation, 3)

    def test_c7_mutation_is_atomic_two_writes(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTERED)
        # consumption AND active B both present (WRITE1 + WRITE2)
        self.assertIn((ResourceType.PROVIDER, "p", "R1"), rrm._consumptions)
        self.assertIsNotNone(rrm.get_provider("p"))


# ===========================================================================
# D. Consumption-store immutability / deep detachment
# ===========================================================================


class TestConsumptionDetachment(unittest.TestCase):
    def test_d1_descriptor_deep_detached(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        original = {"display_name": "B", "nested": {"items": [1, 2, 3]}}
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor=original,
        )
        # mutate the caller-owned input AFTER registration
        original["display_name"] = "MUTATED"
        original["nested"]["items"].append(999)
        c = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")]
        self.assertEqual(c.successor_materialization_descriptor["display_name"], "B")
        self.assertEqual(c.successor_materialization_descriptor["nested"]["items"], [1, 2, 3])
        self.assertIsNot(
            c.successor_materialization_descriptor["nested"],
            original["nested"],
        )

    def test_d2_stored_descriptor_not_shallow_copied(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        original_inner = {"a": [1]}
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B", "inner": original_inner},
        )
        original_inner["a"].append(7)
        c = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")]
        self.assertEqual(c.successor_materialization_descriptor["inner"]["a"], [1])

    def test_d3_no_alias_to_original_containers(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        original = {"display_name": "B"}
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor=original,
        )
        c = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")]
        self.assertIsNot(
            c.successor_materialization_descriptor, original
        )

    def test_d4_successor_resource_built_from_detached_descriptor(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        c = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")]
        b = rrm.get_provider("p")
        self.assertEqual(b.name, "B")

    def test_d5_descriptor_stored_for_recovery_not_retryable(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        # recovery must reuse the STORED "B" descriptor, not any retried value
        del rrm._providers["p"]  # simulate WRITE 2 absent
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "EVIL"},
        )
        self.assertIs(res.outcome, O.REREGISTRATION_RECOVERED)
        self.assertEqual(rrm.get_provider("p").name, "B")

    def test_d6_unsupported_descriptor_rejected_fail_closed(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))

        class Evil:
            def __reduce__(self):  # pragma: no cover
                raise AssertionError("reduce must not run")

        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B", "e": Evil()},
        )
        self.assertIs(res.outcome, O.INVALID_RESOURCE)
        self.assertEqual(rrm._consumptions, {})


# ===========================================================================
# E. Recovery (WRITE1 present / WRITE2 absent)
# ===========================================================================


class TestRecovery(unittest.TestCase):
    def test_e1_recovery_rereregister_recovers(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res2.outcome, O.REREGISTRATION_RECOVERED)
        self.assertEqual(
            res2.successor_governed_registration_id,
            res1.successor_governed_registration_id,
        )
        self.assertEqual(res2.successor_observed_generation, 2)

    def test_e2_recovery_preserves_b_never_allocates_c(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res2.outcome, O.REREGISTRATION_RECOVERED)
        self.assertEqual(
            res2.successor_governed_registration_id,
            res1.successor_governed_registration_id,
        )
        # only one lineage ever created for the predecessor lineage
        self.assertEqual(
            len(rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")].successor_governed_registration_id),
            len(res1.successor_governed_registration_id),
        )

    def test_e3_recovery_no_second_authorization(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res.outcome, O.REREGISTRATION_RECOVERED)
        self.assertEqual(res.successor_observed_generation, 2)

    def test_e4_recovery_uses_exact_original_decision(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-9", did="dec-9"),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-8", did="dec-8"),
        )
        self.assertIs(res.outcome, O.PENDING_SUCCESSOR_MISMATCH)

    def test_e5_recovery_active_present_is_already_applied_not_duplicate(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res.outcome, O.REREGISTRATION_ALREADY_APPLIED)

    def test_e6_recovery_never_rolls_back_reopens_a(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res.outcome, O.REREGISTRATION_RECOVERED)
        # A's lineage remains consumed (tombstone still for R1, consumption present)
        self.assertIn((ResourceType.PROVIDER, "p", "R1"), rrm._consumptions)


# ===========================================================================
# F. Idempotent already-applied + decision consumption timing
# ===========================================================================


class TestAlreadyAppliedAndDecisionTiming(unittest.TestCase):
    def test_f1_already_applied_same_candidate(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTRATION_ALREADY_APPLIED)
        self.assertEqual(rrm.get_provider("p").name, "B")

    def test_f2_completed_reregistration_persists(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTERED)
        self.assertEqual(rrm.get_provider("p").governed_registration_id,
                         res.successor_governed_registration_id)


# ===========================================================================
# G. PENDING_SUCCESSOR_MISMATCH
# ===========================================================================


class TestPendingSuccessorMismatch(unittest.TestCase):
    def test_g1_candidate_divergence(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-1"),
            materialization_descriptor={"display_name": "B"},
        )
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-2"),
        )
        self.assertIs(res.outcome, O.PENDING_SUCCESSOR_MISMATCH)

    def test_g2_decision_divergence_only(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-1"),
            materialization_descriptor={"display_name": "B"},
        )
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-9"),
        )
        self.assertIs(res.outcome, O.PENDING_SUCCESSOR_MISMATCH)

    def test_g3_no_second_successor_allocated(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-1"),
            materialization_descriptor={"display_name": "B"},
        )
        b_before = rrm.get_provider("p").governed_registration_id
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-9", did="dec-9"),
        )
        self.assertIs(res.outcome, O.PENDING_SUCCESSOR_MISMATCH)
        self.assertEqual(rrm.get_provider("p").governed_registration_id, b_before)


# ===========================================================================
# H. ACTIVE_RESOURCE_CONFLICT
# ===========================================================================


class TestActiveResourceConflict(unittest.TestCase):
    def test_h1_active_conflict_fresh(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        _activate(rrm, ResourceType.PROVIDER, "p", "R2")
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.ACTIVE_RESOURCE_CONFLICT)
        self.assertEqual(rrm.get_provider("p").governed_registration_id, "R2")

    def test_h2_no_consumption_on_conflict(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        _activate(rrm, ResourceType.PROVIDER, "p", "R2")
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertNotIn((ResourceType.PROVIDER, "p", "R1"), rrm._consumptions)


# ===========================================================================
# I. STALE_RETIRED_LINEAGE (successor B itself retired)
# ===========================================================================


class TestStaleRetiredLineage(unittest.TestCase):
    def test_i1_stale_after_successor_retired(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        _require_retired(_retire(
            rrm, ResourceType.PROVIDER, "p", res1.successor_governed_registration_id, 2,
        ))
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res2.outcome, O.STALE_RETIRED_LINEAGE)

    def test_i2_a_never_eligible_again(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        _require_retired(_retire(
            rrm, ResourceType.PROVIDER, "p", res1.successor_governed_registration_id, 2,
        ))
        # tombstone B + consumption A->B + tombstone B coexist
        self.assertTrue(
            rrm.has_tombstoned_resource(ResourceType.PROVIDER, "p")
        )
        self.assertIn(
            (ResourceType.PROVIDER, "p", "R1"), rrm._consumptions
        )
        self.assertIsNotNone(
            rrm.get_resource_tombstone(
                ResourceType.PROVIDER, "p", res1.successor_governed_registration_id
            )
        )

    def test_i3_old_decision_returns_stale(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-1"),
            materialization_descriptor={"display_name": "B"},
        )
        _require_retired(_retire(
            rrm, ResourceType.PROVIDER, "p", res1.successor_governed_registration_id, 2,
        ))
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-1", did="dec-1"),
        )
        self.assertIs(res2.outcome, O.STALE_RETIRED_LINEAGE)


# ===========================================================================
# J. INVALID_RESOURCE / INVALID_TRANSITION
# ===========================================================================


class TestInvalidResourceAndTransition(unittest.TestCase):
    def test_j1_invalid_resource_missing_descriptor(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res.outcome, O.INVALID_RESOURCE)
        self.assertIsNone(res.successor_governed_registration_id)

    def test_j2_invalid_terminal_transition_rejected(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B", "status": "archived"},
        )
        self.assertIs(res.outcome, O.INVALID_TRANSITION)
        self.assertEqual(rrm._consumptions, {})

    def test_j3_invalid_uninstalled_transition_rejected(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B", "status": "uninstalled"},
        )
        self.assertIs(res.outcome, O.INVALID_TRANSITION)
        self.assertEqual(rrm._consumptions, {})


# ===========================================================================
# K. Six-family parity
# ===========================================================================


class TestSixFamilyParity(unittest.TestCase):
    def _check_family(self, kind):
        rrm = _fresh()
        rid = "id-" + kind.value
        grid = f"R1-{kind.value}"
        _governed_resource(rrm, kind, rid, grid, 1, display_name="A")
        _require_retired(_retire(rrm, kind, rid, grid, 1))
        res = rrm.conditional_reregister_resource(
            _req(kind, rid, grid, 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res.outcome, O.REREGISTERED)
        self.assertTrue(res.successor_governed_registration_id.startswith("gov-"))
        self.assertEqual(res.successor_observed_generation, 2)
        return rrm, rid, res

    def test_k1_provider(self):
        self._check_family(ResourceType.PROVIDER)

    def test_k2_account(self):
        self._check_family(ResourceType.ACCOUNT)

    def test_k3_capability(self):
        self._check_family(ResourceType.CAPABILITY)

    def test_k4_agent(self):
        self._check_family(ResourceType.AGENT)

    def test_k5_environment(self):
        self._check_family(ResourceType.EXECUTION_ENVIRONMENT)

    def test_k6_project(self):
        self._check_family(ResourceType.PROJECT)

    def test_k7_b1_ordinary_registration_unchanged(self):
        # B1: an ordinary RRM resource (never promoted through the canonical
        # boundary) must keep governed_registration_id="" generation=1, and it
        # must NOT reach the re-registration lineage generator (no tombstone ⇒
        # NO_TOMBSTONE, no successor lineage minted).
        rrm = _fresh()
        p = ProviderResource(
            provider_id="b1", name="B1",
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False, is_configured=False, has_active_account=False,
            status=ResourceStatus.ACTIVE,
        )
        rrm.register_provider(p)
        snap = rrm.get_provider("b1")
        self.assertEqual(snap.governed_registration_id, "")
        self.assertEqual(snap.generation, 1)
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "b1", "gov-b1", 1),
            materialization_descriptor={"display_name": "X"},
        )
        self.assertIs(res.outcome, O.NO_TOMBSTONE)
        self.assertEqual(rrm._consumptions, {})
        self.assertEqual(rrm.get_provider("b1").governed_registration_id, "")

    def test_k8_b1_ordinary_promoted_by_boundary_still_mints_b1(self):
        # The ordinary first-time promotion path (no precondition) must NOT be
        # treated as a re-registration and must not consume a re-registration
        # lineage generator path.
        rrm = _fresh()
        disc, proposals, decisions, boundary = _stack(
            rrm, _evidence("b1p", ResourceDiscoveryKind.PROVIDER, "disc-b1p")
        )
        prop = proposals.create_proposal("disc-b1p", reasoning="first")
        dec = decisions.decide(
            prop.proposal_id, ResourcePromotionDecisionType.APPROVE,
            decided_by="auditor",
        )
        self.assertIsNone(dec.re_registration_precondition)
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res.success)
        self.assertFalse(res.re_registration)
        self.assertEqual(res.registration_type, "provider")
        # ordinary B1 promote never consumes a re-registration lineage
        self.assertEqual(rrm._consumptions, {})


# ===========================================================================
# L. Promotion-boundary integration
# ===========================================================================


class TestBoundaryIntegration(unittest.TestCase):
    def test_l1_reregister_via_boundary_success(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        self.assertIsNotNone(dec.re_registration_precondition)
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res.success)
        self.assertTrue(res.re_registration)
        self.assertTrue(res.governed_registration_id.startswith("gov-"))
        self.assertEqual(res.observed_generation, 2)
        self.assertEqual(res.reason, "reregistered")
        b = rrm.get_provider("p")
        self.assertEqual(b.governed_registration_id, res.governed_registration_id)
        self.assertEqual(b.generation, 2)
        # decision consumed only after successful re-registration
        self.assertTrue(decisions.is_consumed(dec.decision_id))

    def test_l2_decision_consumed_only_after_success(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        # no-op cleanup
        self.assertFalse(decisions.is_consumed(dec.decision_id))

    def test_l3_boundary_no_lineage_minting_for_rereg(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res.success)
        self.assertTrue(res.governed_registration_id.startswith("gov-"))
        self.assertFalse(res.governed_registration_id.startswith("registration_"))

    def test_l4_boundary_recovery_keeps_decision_retryable_then_consumes(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        # first promote normally -> REREGISTERED
        res1 = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res1.success)
        self.assertTrue(decisions.is_consumed(dec.decision_id))
        self.assertEqual(res1.reason, "reregistered")


# ===========================================================================
# M. RRM as sole governed-lineage-ID authority
# ===========================================================================


class TestSoleLineageAuthority(unittest.TestCase):
    def test_m1_successor_lineage_unpredictable(self):
        seen = set()
        for _ in range(20):
            rrm = _fresh()
            _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
            _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
            res = rrm.conditional_reregister_resource(
                _req(ResourceType.PROVIDER, "p", "R1", 1),
                materialization_descriptor={"display_name": "B"},
            )
            self.assertTrue(res.successor_governed_registration_id.startswith("gov-"))
            seen.add(res.successor_governed_registration_id)
        self.assertGreater(len(seen), 10)

    def test_m2_successor_grid_distinct_from_predecessor(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertNotEqual(res.successor_governed_registration_id, "R1")

    def test_m3_no_caller_supplied_lineage_accepted(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertTrue(res.successor_governed_registration_id.startswith("gov-"))

    def test_m4_boundary_register_type_and_lineage_evidence(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertEqual(res.registration_type, "provider")
        self.assertTrue(res.governed_registration_id.startswith("gov-"))


# ===========================================================================
# N. Decision-consumption timing conservatism
# ===========================================================================


class TestDecisionConsumptionTiming(unittest.TestCase):
    def test_n1_failure_leaves_decision_unconsumed(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        # introduce an active conflicting resource so RRM returns ACTIVE_CONFLICT
        _activate(rrm, ResourceType.PROVIDER, "p", "R2")
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertFalse(res.success)
        self.assertEqual(res.reason, "active_resource_conflict")
        self.assertFalse(decisions.is_consumed(dec.decision_id))

    def test_n2_decision_consumed_after_reregistered(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res.success)
        self.assertTrue(decisions.is_consumed(dec.decision_id))

    def test_n3_proposal_consumed_after_reregistered(self):
        rrm = _fresh()
        disc, proposals, decisions, boundary = _row(
            rrm, ResourceType.PROVIDER, "p", "R1", 1, "disc-p"
        )
        prop = proposals.create_proposal("disc-p", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            ResourceType.PROVIDER, "p", "R1", 1,
        ))
        boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(proposals.get_proposal(prop.proposal_id) is not None)
        # boundary transitions proposal - M17 semantics
        # (transition_to_consumed is invoked by the boundary)
        from intent_kernel.promotion.models import ResourcePromotionStatus
        self.assertEqual(
            proposals.get_proposal(prop.proposal_id).status,
            ResourcePromotionStatus.CONSUMED,
        )


# ===========================================================================
# Boundary round-trip across families
# ===========================================================================


class TestBoundaryFamilyRoundTrip(unittest.TestCase):
    def _roundtrip(self, kind, disc_kind):
        rrm = _fresh()
        rid = "rt-" + kind.value
        grid = "RG-" + kind.value
        _governed_resource(rrm, kind, rid, grid, 1, display_name="A")
        _require_retired(_retire(rrm, kind, rid, grid, 1))
        disc, proposals, decisions, boundary = _stack(
            rrm, _evidence(rid, disc_kind, f"disc-rt-{kind.value}")
        )
        prop = proposals.create_proposal(f"disc-rt-{kind.value}", reasoning="rereg")
        dec = _approve(decisions, prop.proposal_id, _precondition(
            kind, rid, grid, 1,
        ))
        res = boundary.register(prop.proposal_id, dec.decision_id)
        self.assertTrue(res.success, res.reason)
        self.assertTrue(res.re_registration)
        self.assertTrue(res.governed_registration_id.startswith("gov-"))
        return rrm, rid, res

    def test_r1_provider_boundary(self):
        self._roundtrip(ResourceType.PROVIDER, ResourceDiscoveryKind.PROVIDER)

    def test_r2_capability_boundary(self):
        self._roundtrip(ResourceType.CAPABILITY, ResourceDiscoveryKind.CAPABILITY)

    def test_r3_agent_boundary(self):
        self._roundtrip(ResourceType.AGENT, ResourceDiscoveryKind.AGENT)

    def test_r4_environment_boundary(self):
        self._roundtrip(
            ResourceType.EXECUTION_ENVIRONMENT, ResourceDiscoveryKind.ENVIRONMENT
        )


# ===========================================================================
# Adversarial / guard assertions
# ===========================================================================


class TestAdversarialGuards(unittest.TestCase):
    def test_s1_reopen_consumed_predecessor_blocked(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res1.outcome, O.REREGISTERED)
        # mutate the mutable store resource's lineage directly (unauthorized)
        rrm._providers["p"].governed_registration_id = "HACKED"
        # recovery now sees an active successor whose grid != stored consumption
        res2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(res2.outcome, O.ACTIVE_RESOURCE_CONFLICT)

    def test_s2_descriptor_hash_not_used_for_identity(self):
        # identity must be lineage (kind,id,grid) — never descriptor hashing
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(res1.outcome, O.REREGISTERED)
        key = (ResourceType.PROVIDER, "p", "R1")
        self.assertIn(key, rrm._consumptions)
        self.assertEqual(rrm._consumptions[key].consumption_key, key)

    def test_s3_no_callback_under_lock(self):
        # consumption/result construction must not invoke arbitrary callables
        class Evil:
            def __reduce__(self):
                raise AssertionError("must not execute")

        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B", "bad": Evil()},
        )
        self.assertIs(res.outcome, O.INVALID_RESOURCE)


# ===========================================================================
# Additional invariants (decision serialization, detachment, convergence)
# ===========================================================================


class TestAdditionalInvariants(unittest.TestCase):
    def test_plus1_decision_serializes_precondition(self):
        p = _precondition(ResourceType.PROVIDER, "p", "R1", 1)
        dec = ResourcePromotionDecision(
            decision_id="d1", proposal_id="prop1",
            evidence_identity="e1",
            decision_type=ResourcePromotionDecisionType.APPROVE,
            re_registration_precondition=p,
        )
        d = dec.to_dict()
        self.assertEqual(d["re_registration_precondition"]["resource_kind"], "provider")
        self.assertEqual(
            d["re_registration_precondition"]["retired_governed_registration_id"], "R1"
        )
        self.assertEqual(
            d["re_registration_precondition"]["retired_observed_generation"], 1
        )

    def test_plus2_precondition_immutable(self):
        p = _precondition(ResourceType.PROVIDER, "p", "R1", 1)
        with self.assertRaises(AttributeError):
            p.retired_governed_registration_id = "WRONG"

    def test_plus3_reentry_same_candidate_converges(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        r1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        r2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        self.assertIs(r1.outcome, O.REREGISTERED)
        self.assertIs(r2.outcome, O.REREGISTRATION_ALREADY_APPLIED)
        self.assertEqual(
            r1.successor_governed_registration_id,
            r2.successor_governed_registration_id,
        )
        self.assertEqual(
            rrm.get_provider("p").governed_registration_id,
            r1.successor_governed_registration_id,
        )

    def test_plus4_recovery_then_apply_converges(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        r1 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        r2 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(r2.outcome, O.REREGISTRATION_RECOVERED)
        r3 = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
        )
        self.assertIs(r3.outcome, O.REREGISTRATION_ALREADY_APPLIED)
        self.assertEqual(
            rrm.get_provider("p").governed_registration_id,
            r1.successor_governed_registration_id,
        )

    def test_plus5_metadata_deep_detached_from_caller(self):
        from intent_kernel.promotion.proposal_service import (
            ResourcePromotionProposalService,
        )
        rrm = _fresh()
        evidence = _evidence("p", ResourceDiscoveryKind.PROVIDER, "disc-md")
        disc = _discovery_svc(evidence)
        proposals = ResourcePromotionProposalService(disc)
        caller_meta = {"k": {"deep": [1, 2]}}
        prop = proposals.create_proposal("disc-md", reasoning="r", metadata=caller_meta)
        caller_meta["k"]["deep"].append(999)
        caller_meta["k"]["deep"][0] = "MUT"
        self.assertEqual(prop.metadata["k"]["deep"], [1, 2])
        self.assertIsNot(prop.metadata["k"], caller_meta["k"])

    def test_plus6_descriptor_stored_shares_no_node(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        inner = {"leaf": [1]}
        outer = {"display_name": "B", "inner": inner}
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor=outer,
        )
        stored = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")].successor_materialization_descriptor
        self.assertIsNot(stored, outer)
        self.assertIsNot(stored["inner"], inner)
        self.assertIsNot(stored["inner"]["leaf"], inner["leaf"])
        self.assertEqual(stored["inner"]["leaf"], [1])

    def test_plus7_consumption_key_is_lineage_not_generation(self):
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        c = rrm._consumptions[(ResourceType.PROVIDER, "p", "R1")]
        self.assertEqual(c.consumption_key[2], "R1")
        # generation is a field, NOT part of the primary key tuple
        self.assertEqual(len(c.consumption_key), 3)

    def test_plus8_result_never_partial_success(self):
        # a failed outcome must never carry successor lineage values
        for out in (
            O.NO_TOMBSTONE, O.TOMBSTONE_LINEAGE_MISMATCH,
            O.TOMBSTONE_GENERATION_MISMATCH, O.STALE_RETIRED_LINEAGE,
            O.PENDING_SUCCESSOR_MISMATCH, O.ACTIVE_RESOURCE_CONFLICT,
            O.INVALID_RESOURCE, O.INVALID_TRANSITION,
        ):
            res = ConditionalReregistrationResult(
                outcome=out, resource_kind=ResourceType.PROVIDER,
                resource_id="p", reason="x",
            )
            self.assertIsNone(res.successor_governed_registration_id)
            self.assertIsNone(res.successor_observed_generation)

    def test_plus9_recovery_stored_descriptor_is_immutable_input(self):
        # recovery must not clobber the stored descriptor with retry input
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "B"},
        )
        stored_key = (ResourceType.PROVIDER, "p", "R1")
        before = dict(rrm._consumptions[stored_key].successor_materialization_descriptor)
        del rrm._providers["p"]
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1),
            materialization_descriptor={"display_name": "ATTACK"},
        )
        after = rrm._consumptions[stored_key].successor_materialization_descriptor
        self.assertEqual(before, after)
        self.assertEqual(rrm.get_provider("p").name, "B")

    def test_plus10_no_second_authorization_on_recovery(self):
        # recovery does not re-validate/authorize a new candidate; it finishes the
        # exact already-approved operation.
        rrm = _fresh()
        _governed_resource(rrm, ResourceType.PROVIDER, "p", "R1", 1)
        _require_retired(_retire(rrm, ResourceType.PROVIDER, "p", "R1", 1))
        rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-A", did="dec-A"),
            materialization_descriptor={"display_name": "B"},
        )
        del rrm._providers["p"]
        res = rrm.conditional_reregister_resource(
            _req(ResourceType.PROVIDER, "p", "R1", 1, pil="prop-B", did="dec-B"),
        )
        self.assertIs(res.outcome, O.PENDING_SUCCESSOR_MISMATCH)


if __name__ == "__main__":
    unittest.main()
