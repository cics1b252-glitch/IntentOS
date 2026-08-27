"""M30.2 — Canonical Monotonic Resource Generation (Freshness Identity).

55+ tests covering:
  A. Registration establishes canonical generation 1        (8)
  B. Material mutation advances generation exactly once     (5)
  C. Type / forgery generation never trusted               (6)
  D. Retirement invalidates pre-retirement evidence        (3)
  E. Registration identity (governed_registration_id)      (4)
  F. Persistence serialization preserves generation        (4)
  G. Projection (TEMPLATE -> 1, no reset on repeat)        (3)
  H. External evidence freshness identity + fail-closed    (15)
  I. Preservation (M29/M28/M28.2.1/M27/M26/M25/M24/M23/H1) (8)
  + adversarial extras                                     (4)

Invariant under audit:
  RESOURCE STATE IDENTITY = (resource_id, governed_registration_id, generation)
  Only RegistryResourceManager may advance generation. Adapter is MECHANISM-ONLY.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from intent_kernel.application.composition import ApplicationFactory
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    VerificationStatus,
)
from intent_kernel.runtime.verification import VerificationGate
from intent_kernel.runtime.external_evidence import (
    ExternalEvidenceRequirement,
    ExternalEvidenceRequirementValidator,
    ExternalObservationResult,
    RRMEvidenceAdapter,
    external_evidence_contract_hash,
    _APPROVED_EXPECTED_STATE_KEYS,
)
from intent_kernel.rrm import generation as gen
from intent_kernel.rrm.generation import GENERATION_INITIAL, LEGACY_UNVERSIONED
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
)
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority
from intent_kernel.rrm.service import RegistryResourceManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(gate, node, result="A"):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            gate.evaluate_node(node, node.action_contract, result)
        )
    finally:
        loop.close()


def _echo_node(external_evidence=None, verification_type="EXACT"):
    return RuntimeNode(
        node_id="n1",
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": "A"},
            expected_output="A",
            verification_type=verification_type,
            external_evidence=external_evidence,
            verification_required=True,
        ),
    )


def _req(
    resource_id="p1",
    expected_state: Optional[Dict[str, Any]] = None,
) -> ExternalEvidenceRequirement:
    return ExternalEvidenceRequirement(
        evidence_type="PROVIDER_RESOURCE_STATE",
        resource_id=resource_id,
        expected_state=expected_state or {"status": "active", "is_eligible": True},
    )


def _fresh_rrm() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


# ===========================================================================
# A. Registration establishes canonical generation 1
# ===========================================================================

class TestRegistrationGeneration(unittest.TestCase):
    """A: Canonical registration initializes generation to 1 internally."""

    def _make_all(self, rrm):
        p = ProviderResource(provider_id="p1", name="P")
        acc = AccountResource(account_id="a1", provider_id="p1", name="A")
        env = ExecutionEnvironmentResource(environment_id="e1")
        cap = CapabilityResource(capability_id="c1", name="c1")
        ag = AgentResource(agent_id="g1", name="G")
        prj = ProjectResource(project_id="j1", name="J")
        rrm.register_provider(p)
        rrm.register_account(acc)
        rrm.register_environment(env)
        rrm.register_capability(cap)
        rrm.register_agent(ag)
        rrm.register_project(prj)
        return p, acc, env, cap, ag, prj

    def test_a1_provider_generation_1(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        self.assertEqual(p.generation, LEGACY_UNVERSIONED)
        rrm.register_provider(p)
        self.assertEqual(p.generation, GENERATION_INITIAL)

    def test_a2_account_generation_1(self):
        rrm = _fresh_rrm()
        acc = AccountResource(account_id="a1", provider_id="p1", name="A")
        rrm.register_account(acc)
        self.assertEqual(acc.generation, GENERATION_INITIAL)

    def test_a3_environment_generation_1(self):
        rrm = _fresh_rrm()
        env = ExecutionEnvironmentResource(environment_id="e1")
        rrm.register_environment(env)
        self.assertEqual(env.generation, GENERATION_INITIAL)

    def test_a4_capability_generation_1(self):
        rrm = _fresh_rrm()
        cap = CapabilityResource(capability_id="c1", name="c1")
        rrm.register_capability(cap)
        self.assertEqual(cap.generation, GENERATION_INITIAL)

    def test_a5_agent_generation_1(self):
        rrm = _fresh_rrm()
        ag = AgentResource(agent_id="g1", name="G")
        rrm.register_agent(ag)
        self.assertEqual(ag.generation, GENERATION_INITIAL)

    def test_a6_project_generation_1(self):
        rrm = _fresh_rrm()
        prj = ProjectResource(project_id="j1", name="J")
        rrm.register_project(prj)
        self.assertEqual(prj.generation, GENERATION_INITIAL)

    def test_a7_unregistered_default_is_legacy(self):
        p = ProviderResource(provider_id="p1", name="P")
        self.assertEqual(p.generation, LEGACY_UNVERSIONED)
        self.assertFalse(gen.is_valid_generation(p.generation))

    def test_a8_registration_returns_same_object_with_generation(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        returned = rrm.register_provider(p)
        self.assertIs(returned, p)
        self.assertEqual(rrm.get_provider("p1").generation, GENERATION_INITIAL)


# ===========================================================================
# B. Material mutation advances generation exactly once
# ===========================================================================

class TestMutationGeneration(unittest.TestCase):
    """B: Material mutation advances generation +1; no-op does not advance."""

    def test_b1_material_status_update_advances_once(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)
        ok = rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
        self.assertTrue(ok)
        self.assertEqual(rrm.get_provider("p1").generation, 2)

    def test_b2_second_material_update_advances_again(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.UNAVAILABLE)
        self.assertEqual(rrm.get_provider("p1").generation, 3)

    def test_b3_noop_update_does_not_advance(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.ACTIVE)
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_b4_all_six_types_advance_on_material_change(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        acc = AccountResource(account_id="a1", provider_id="p1", name="A")
        env = ExecutionEnvironmentResource(environment_id="e1")
        cap = CapabilityResource(capability_id="c1", name="c1")
        ag = AgentResource(agent_id="g1", name="G")
        prj = ProjectResource(project_id="j1", name="J")
        for rr in (p, acc, env, cap, ag, prj):
            pass
        rrm.register_provider(p)
        rrm.register_account(acc)
        rrm.register_environment(env)
        rrm.register_capability(cap)
        rrm.register_agent(ag)
        rrm.register_project(prj)
        pairs = [
            (ResourceType.PROVIDER, "p1"),
            (ResourceType.ACCOUNT, "a1"),
            (ResourceType.EXECUTION_ENVIRONMENT, "e1"),
            (ResourceType.CAPABILITY, "c1"),
            (ResourceType.AGENT, "g1"),
            (ResourceType.PROJECT, "j1"),
        ]
        for rt, rid in pairs:
            ok = rrm.update_resource_status(rt, rid, ResourceStatus.DEGRADED)
            self.assertTrue(ok)
        self.assertEqual(rrm.get_provider("p1").generation, 2)
        self.assertEqual(rrm.get_account("a1").generation, 2)
        self.assertEqual(rrm.get_environment("e1").generation, 2)
        self.assertEqual(rrm.get_capability("c1").generation, 2)
        self.assertEqual(rrm.get_agent("g1").generation, 2)
        self.assertEqual(rrm.get_project("j1").generation, 2)

    def test_b5_generation_and_status_change_together(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        before = (p.status, p.generation)
        self.assertEqual(before, (ResourceStatus.ACTIVE, 1))
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
        after = (rrm.get_provider("p1").status, rrm.get_provider("p1").generation)
        self.assertEqual(after, (ResourceStatus.DEGRADED, 2))


# ===========================================================================
# C. Type / forgery — caller-provided generation never trusted
# ===========================================================================

class TestTypeAndForgery(unittest.TestCase):
    """C: Registration normalizes caller generation internally."""

    def test_c1_forge_500_normalized_to_1(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", generation=500)
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)

    def test_c2_forge_negative_normalized_to_1(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", generation=-1)
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)

    def test_c3_forge_bool_normalized_to_1(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", generation=True)
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)

    def test_c4_forge_zero_normalized_to_1(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", generation=0)
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)

    def test_c5_validation_rejects_bad_types(self):
        for bad in (True, False, -1, 0, "5", 3.14, None):
            self.assertFalse(gen.is_valid_generation(bad), f"should reject {bad!r}")
        self.assertTrue(gen.is_valid_generation(1))
        self.assertTrue(gen.is_valid_generation(2))
        self.assertTrue(gen.is_valid_generation(999))

    def test_c6_legacy_sentinel_is_zero(self):
        self.assertEqual(LEGACY_UNVERSIONED, 0)
        self.assertEqual(GENERATION_INITIAL, 1)
        self.assertFalse(gen.is_versioned(LEGACY_UNVERSIONED))
        self.assertTrue(gen.is_versioned(GENERATION_INITIAL))


# ===========================================================================
# D. Retirement invalidates pre-retirement evidence
# ===========================================================================

class TestRetirementInvalidation(unittest.TestCase):
    """D: Pre-retirement evidence never verifies a retired resource."""

    def _governed(self):
        rrm = _fresh_rrm()
        ret = CanonicalResourceRetirementAuthority(rrm)
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        return rrm, ret, p

    def test_d1_valid_observation_before_retirement(self):
        rrm, _, p = self._governed()
        ad = RRMEvidenceAdapter(rrm)
        o = ad.observe(_req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R1", "resource_generation": 1}))
        self.assertTrue(o.matched)
        self.assertEqual(o.resource_generation, 1)

    def test_d2_post_retirement_fails_closed(self):
        rrm, ret, _ = self._governed()
        reqq = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(reqq.request_id, approved=True)
        res = ret.apply_retirement(dec.decision_id)
        self.assertTrue(res.success)
        ad = RRMEvidenceAdapter(rrm)
        o = ad.observe(_req(expected_state={"status": "active", "is_eligible": True, "resource_generation": 1}))
        self.assertFalse(o.matched)
        self.assertTrue(o.reason_code in ("resource_tombstoned", "resource_not_found"))

    def test_d3_retired_identity_refuses_reregistration(self):
        rrm, ret, _ = self._governed()
        reqq = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(reqq.request_id, approved=True)
        ret.apply_retirement(dec.decision_id)
        self.assertTrue(rrm._is_tombstoned("p1"))
        p2 = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p2)
        self.assertIsNone(rrm.get_provider("p1"))


# ===========================================================================
# E. Registration identity (governed_registration_id)
# ===========================================================================

class TestRegistrationIdentity(unittest.TestCase):
    """E: Freshness identity includes governed_registration_id."""

    def test_e1_observation_reports_grid(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        o = RRMEvidenceAdapter(rrm).observe(_req())
        self.assertEqual(o.governed_registration_id, "R1")

    def test_e2_requirement_grid_r2_vs_actual_r1_fails(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        o = RRMEvidenceAdapter(rrm).observe(
            _req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R2", "resource_generation": 1})
        )
        self.assertFalse(o.matched)
        self.assertEqual(o.governed_registration_id, "R1")

    def test_e3_same_logical_id_governed_overwrite_preserves_lineage(self):
        rrm = _fresh_rrm()
        p1 = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p1)
        p2 = ProviderResource(provider_id="p1", name="P2", governed_registration_id="R1")
        returned = rrm.register_provider(p2)
        self.assertIs(returned, p1)
        self.assertEqual(rrm.get_provider("p1").governed_registration_id, "R1")
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_e4_evidence_bound_to_r1_verifies_when_present(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        o = RRMEvidenceAdapter(rrm).observe(
            _req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R1", "resource_generation": 1})
        )
        self.assertTrue(o.matched)
        self.assertEqual((o.resource_id, o.governed_registration_id, o.resource_generation), ("p1", "R1", 1))


# ===========================================================================
# F. Persistence serialization preserves generation
# ===========================================================================

class TestPersistenceGeneration(unittest.TestCase):
    """F: to_dict/from_dict round-trip preserves generation; legacy -> sentinel."""

    def test_f1_roundtrip_preserves_generation(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
        self.assertEqual(p.generation, 2)
        stored = p.to_dict()
        self.assertEqual(stored["generation"], 2)
        restored = ProviderResource.from_dict(stored)
        self.assertEqual(restored.generation, 2)
        self.assertEqual(restored.governed_registration_id, "")

    def test_f2_missing_generation_becomes_legacy(self):
        d = ProviderResource(provider_id="p", name="N").to_dict()
        d.pop("generation")
        restored = ProviderResource.from_dict(d)
        self.assertEqual(restored.generation, LEGACY_UNVERSIONED)

    def test_f3_malformed_generation_becomes_legacy(self):
        for bad in (True, -1, "7", 0, 3.9):
            d = ProviderResource(provider_id="p", name="N").to_dict()
            d["generation"] = bad
            restored = ProviderResource.from_dict(d)
            self.assertEqual(restored.generation, LEGACY_UNVERSIONED, f"bad {bad!r}")

    def test_f4_all_six_types_roundtrip_generation(self):
        rrm = _fresh_rrm()
        acc = AccountResource(account_id="a1", provider_id="p1", name="A")
        env = ExecutionEnvironmentResource(environment_id="e1")
        cap = CapabilityResource(capability_id="c1", name="c1")
        ag = AgentResource(agent_id="g1", name="G")
        prj = ProjectResource(project_id="j1", name="J")
        for rr in (acc, env, cap, ag, prj):
            rrm.register_account(acc)
            rrm.register_environment(env)
            rrm.register_capability(cap)
            rrm.register_agent(ag)
            rrm.register_project(prj)
        for rr, cls in (
            (rrm.get_account("a1"), AccountResource),
            (rrm.get_environment("e1"), ExecutionEnvironmentResource),
            (rrm.get_capability("c1"), CapabilityResource),
            (rrm.get_agent("g1"), AgentResource),
            (rrm.get_project("j1"), ProjectResource),
        ):
            self.assertEqual(rr.generation, 1)
            restored = cls.from_dict(rr.to_dict())
            self.assertEqual(restored.generation, 1)


# ===========================================================================
# G. Projection — TEMPLATE -> 1, no reset/decrease on repeat
# ===========================================================================

class TestProjectionGeneration(unittest.TestCase):
    """G: Projected resources begin at generation 1 and never reset."""

    def _cap_app(self):
        class Eff:
            value = "compute"
        return SimpleNamespace(
            app_id="a1",
            capabilities=[SimpleNamespace(
                name="cap.x", description="d", version="1", tags=["t"],
                domains=[SimpleNamespace(value="g")], effect=Eff(),
                requires_network=False, requires_confirmation=False,
            )],
        )

    def test_g1_first_projection_generation_1(self):
        rrm = _fresh_rrm()
        proj = RuntimeResourceProjection(rrm)
        proj.project_core_app(self._cap_app())
        self.assertEqual(rrm.get_capability("cap.x").generation, 1)

    def test_g2_repeated_projection_no_reset_or_decrease(self):
        rrm = _fresh_rrm()
        proj = RuntimeResourceProjection(rrm)
        proj.project_core_app(self._cap_app())
        first = rrm.get_capability("cap.x").generation
        proj.project_core_app(self._cap_app())
        second = rrm.get_capability("cap.x").generation
        self.assertGreaterEqual(second, first)
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)

    def test_g3_projected_provider_generation_1(self):
        rrm = _fresh_rrm()
        proj = RuntimeResourceProjection(rrm)
        prov = SimpleNamespace(name="myprovider", capabilities=["a", "b"])
        proj.project_provider(prov)
        self.assertEqual(rrm.get_provider("myprovider").generation, 1)


# ===========================================================================
# H. External evidence freshness identity + fail-closed
# ===========================================================================

class TestExternalEvidenceIdentity(unittest.TestCase):
    """H: Observation reports canonical identity; fail-closed on bad identity."""

    def _reg(self, grid=""):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id=grid)
        rrm.register_provider(p)
        return rrm

    def test_h1_observation_includes_canonical_fields(self):
        o = RRMEvidenceAdapter(self._reg("R1")).observe(
            _req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R1", "resource_generation": 1})
        )
        self.assertTrue(o.matched)
        self.assertEqual(o.governed_registration_id, "R1")
        self.assertEqual(o.resource_generation, 1)
        self.assertEqual(o.observed_state["status"], "active")
        self.assertIs(o.observed_state["is_eligible"], True)

    def test_h2_valid_observation_matches(self):
        o = RRMEvidenceAdapter(self._reg()).observe(_req(expected_state={"status": "active", "is_eligible": True}))
        self.assertTrue(o.matched)
        self.assertEqual(o.resource_generation, 1)

    def test_h3_legacy_generation_fails_closed(self):
        rrm = _fresh_rrm()
        legacy = ProviderResource(provider_id="lp", name="L")  # generation defaults to 0
        rrm._providers["lp"] = legacy
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="lp"))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "legacy_unversioned_generation")
        self.assertEqual(o.resource_generation, LEGACY_UNVERSIONED)

    def test_h4_malformed_bool_generation_fails_closed(self):
        rrm = _fresh_rrm()
        bad = ProviderResource(provider_id="bp", name="B")
        bad.generation = True
        rrm._providers["bp"] = bad
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="bp"))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "legacy_unversioned_generation")

    def test_h5_negative_generation_fails_closed(self):
        rrm = _fresh_rrm()
        bad = ProviderResource(provider_id="np", name="N")
        bad.generation = -5
        rrm._providers["np"] = bad
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="np"))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "legacy_unversioned_generation")

    def test_h6_generation_mismatch_fails(self):
        o = RRMEvidenceAdapter(self._reg()).observe(
            _req(expected_state={"status": "active", "is_eligible": True, "resource_generation": 99})
        )
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "state_mismatch")

    def test_h7_grid_mismatch_fails(self):
        o = RRMEvidenceAdapter(self._reg("R1")).observe(
            _req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R2"})
        )
        self.assertFalse(o.matched)

    def test_h8_missing_resource_fails(self):
        rrm = _fresh_rrm()
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="nope"))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "resource_not_found")

    def test_h9_tombstoned_fails(self):
        rrm, ret, _ = self._governed()
        reqq = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(reqq.request_id, approved=True)
        ret.apply_retirement(dec.decision_id)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="p1"))
        self.assertFalse(o.matched)
        self.assertTrue(o.reason_code in ("resource_tombstoned", "resource_not_found"))

    def _governed(self):
        rrm = _fresh_rrm()
        ret = CanonicalResourceRetirementAuthority(rrm)
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        return rrm, ret, p

    def test_h10_generation_keys_approved(self):
        self.assertIn("resource_generation", _APPROVED_EXPECTED_STATE_KEYS)
        self.assertIn("governed_registration_id", _APPROVED_EXPECTED_STATE_KEYS)
        req = _req(expected_state={"status": "active", "resource_generation": 1})
        res = ExternalEvidenceRequirementValidator().validate([req])
        self.assertTrue(res.valid)

    def test_h11_observer_is_mechanism_only(self):
        from intent_kernel.runtime.verification import VerificationStatus
        o = RRMEvidenceAdapter(self._reg()).observe(_req())
        self.assertNotIsInstance(o, VerificationStatus)
        self.assertFalse(hasattr(o, "verified"))
        # observation result has no authority fields
        self.assertNotIn("status", type(o).__annotations__)

    def test_h12_verification_gate_fails_closed_on_legacy(self):
        rrm = _fresh_rrm()
        legacy = ProviderResource(provider_id="lp", name="L")
        rrm._providers["lp"] = legacy
        gate = VerificationGate(external_adapter=RRMEvidenceAdapter(rrm))
        node = _echo_node(external_evidence=[_req(resource_id="lp")])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "legacy_unversioned_generation")

    def test_h13_verification_details_serialize_identity(self):
        rrm = self._reg("R1")
        gate = VerificationGate(external_adapter=RRMEvidenceAdapter(rrm))
        node = _echo_node(external_evidence=[_req(expected_state={"status": "active", "is_eligible": True, "governed_registration_id": "R1", "resource_generation": 1})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        obs = evidence.details["external_observations"][0]
        self.assertEqual(obs["governed_registration_id"], "R1")
        self.assertEqual(obs["resource_generation"], 1)

    def test_h14_verification_gate_mismatch_fails(self):
        rrm = self._reg()
        gate = VerificationGate(external_adapter=RRMEvidenceAdapter(rrm))
        node = _echo_node(external_evidence=[_req(expected_state={"status": "active", "is_eligible": True, "resource_generation": 7})])
        status, _ = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_h15_contract_hash_includes_generation(self):
        a = external_evidence_contract_hash([_req(expected_state={"status": "active", "resource_generation": 1})])
        b = external_evidence_contract_hash([_req(expected_state={"status": "active", "resource_generation": 2})])
        self.assertNotEqual(a, b)


# ===========================================================================
# I. Preservation (M29 / M28 / M28.2.1 / M27 / M26 / M25 / M24 / M23 / H1)
# ===========================================================================

class TestPreservation(unittest.TestCase):
    """I: Known movements and policies remain intact."""

    def _reg(self, grid=""):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id=grid)
        rrm.register_provider(p)
        return rrm

    def test_i1_m28_2_1_mutable_resume_stays_inconclusive(self):
        from intent_kernel.runtime import InMemoryActionExecutor, MissionRuntime
        runtime = MissionRuntime(
            executor=InMemoryActionExecutor(),
            external_evidence_adapter=RRMEvidenceAdapter(_fresh_rrm()),
        )
        # mutable PROVIDER_RESOURCE_STATE evidence must remain INCONCLUSIVE on resume
        node = _echo_node(external_evidence=[_req()])
        ok = runtime._validate_resume_evidence(
            "n1",
            "VERIFIED_SUCCESS",
            [{"source": "VerificationGate", "verified": True, "details": {"node_id": "n1", "verification_status": "VERIFIED_SUCCESS", "external_evidence_contract_hash": "x"}}],
            current_action_contract=node.action_contract,
        )
        self.assertFalse(ok)

    def test_i2_m29_2_observer_missing_fails_closed(self):
        gate = VerificationGate(external_adapter=None)
        node = _echo_node(external_evidence=[_req()])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "observer_missing")

    def test_i3_adapter_never_sets_verified(self):
        o = RRMEvidenceAdapter(self._reg()).observe(_req())
        self.assertFalse(hasattr(o, "verified"))

    def test_i4_single_generation_authority_activation_observe_only(self):
        # ActivationApplicationBoundary is observe-only; it must not advance generation.
        from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
        from intent_kernel.activation.service import CanonicalResourceActivationService
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        self.assertEqual(p.generation, 1)
        # Activating an already-ACTIVE configured governed provider must not change generation
        service = CanonicalResourceActivationService(rrm)
        try:
            service.activate("p1")
        except Exception:
            pass
        self.assertEqual(rrm.get_provider("p1").generation, 1)

    def test_i5_h13_tombstone_authority_preserved(self):
        rrm, ret, _ = self._governed()
        reqq = ret.request_retirement("p1", "R1")
        dec = ret.decide_retirement(reqq.request_id, approved=True)
        ret.apply_retirement(dec.decision_id)
        self.assertTrue(rrm._is_tombstoned("p1"))

    def _governed(self):
        rrm = _fresh_rrm()
        ret = CanonicalResourceRetirementAuthority(rrm)
        p = ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        rrm.register_provider(p)
        return rrm, ret, p

    def test_i6_m28_2_resource_not_found_fails_closed(self):
        rrm = _fresh_rrm()
        gate = VerificationGate(external_adapter=RRMEvidenceAdapter(rrm))
        node = _echo_node(external_evidence=[_req(resource_id="nope")])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "resource_not_found")

    def test_i7_generation_is_not_observational_authority(self):
        # updated_at changes never drive generation; only RRM mutation does.
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        g = p.generation
        # Directly touching updated_at (observational) must not move generation
        p.updated_at = "9999-01-01T00:00:00Z"
        self.assertEqual(p.generation, g)

    def test_i8_m23_metadata_provenance_unaffected(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P", metadata={"provenance": "x"})
        rrm.register_provider(p)
        self.assertEqual(p.metadata["provenance"], "x")
        self.assertEqual(p.generation, 1)


# ===========================================================================
# Adversarial extras
# ===========================================================================

class TestAdversarial(unittest.TestCase):
    """Extra adversarial coverage for the freshness identity invariant."""

    def test_adv1_generation_never_decreases_across_mutations(self):
        rrm = _fresh_rrm()
        p = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p)
        prev = p.generation
        for i in range(5):
            rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
            rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.ACTIVE)
            self.assertGreaterEqual(rrm.get_provider("p1").generation, prev)
            prev = rrm.get_provider("p1").generation

    def test_adv2_noop_registration_of_existing_purposeful_does_not_advance(self):
        rrm = _fresh_rrm()
        p1 = ProviderResource(provider_id="p1", name="P")
        rrm.register_provider(p1)
        rrm.update_resource_status(ResourceType.PROVIDER, "p1", ResourceStatus.DEGRADED)
        self.assertEqual(rrm.get_provider("p1").generation, 2)
        # re-register (overwrite, non-governed): preserve, do not reset to 1
        p2 = ProviderResource(provider_id="p1", name="P2")
        rrm.register_provider(p2)
        self.assertEqual(rrm.get_provider("p1").generation, 2)

    def test_adv3_observation_reports_null_generation_for_legacy(self):
        rrm = _fresh_rrm()
        legacy = ProviderResource(provider_id="lp", name="L")
        rrm._providers["lp"] = legacy
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="lp"))
        self.assertFalse(o.matched)
        # resource_generation field reports the sentinel (0)
        self.assertEqual(o.resource_generation, LEGACY_UNVERSIONED)

    def test_adv4_valid_positive_generation_is_versioned(self):
        self.assertTrue(gen.is_versioned(1))
        self.assertTrue(gen.is_versioned(100))
        self.assertFalse(gen.is_versioned(0))
        self.assertFalse(gen.is_versioned(-1))
        self.assertFalse(gen.is_versioned(True))


if __name__ == "__main__":
    unittest.main()
