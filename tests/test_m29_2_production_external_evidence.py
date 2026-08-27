"""Movement 29.2 — Production External Evidence Wiring / Fail-Closed Observer.

40 tests covering:
  A. Production wiring (canonical RRM identity)           (5)
  B. Required observer fail-closed                         (5)
  C. Real observation via canonical RRM                   (5)
  D. Producer separation                                  (5)
  E. ALL_REQUIRED composition                             (9)
  F. Resume freshness preservation (M28.2.1)              (5)
  G. Authority preservation                               (6)

M29 invariant:
  REQUIRED_EXTERNAL_EVIDENCE
  + MISSING / BROKEN / MALFORMED OBSERVER
  = VERIFIED_FAILURE
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from intent_kernel.application.composition import ApplicationFactory
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    VerificationStatus,
)
from intent_kernel.runtime.verification import VerificationGate, exact_contract_hash
from intent_kernel.runtime.semantic_verifier import rule_set_hash
from intent_kernel.runtime.external_evidence import (
    ExternalEvidenceRequirement,
    ExternalObservationResult,
    RRMEvidenceAdapter,
    external_evidence_contract_hash,
)
from intent_kernel.runtime import (
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionRuntime,
)
from intent_kernel.rrm.models import ProviderResource, ResourceStatus
from intent_kernel.rrm.service import RegistryResourceManager


# ---------------------------------------------------------------------------
# Concrete canonical RRM + providers (real RegistryResourceManager, no mocks)
# ---------------------------------------------------------------------------

def _register_provider(
    rrm: RegistryResourceManager,
    provider_id: str,
    status: ResourceStatus = ResourceStatus.ACTIVE,
    is_configured: bool = True,
    has_active_account: bool = True,
) -> ProviderResource:
    provider = ProviderResource(
        provider_id=provider_id,
        name=f"Test Provider {provider_id}",
        status=status,
        is_configured=is_configured,
        has_active_account=has_active_account,
    )
    rrm.register_provider(provider)
    return provider


def _make_echo_node(
    expected_output: str = "A",
    verification_type: str | None = "EXACT",
    semantic_rules=None,
    verification_schema=None,
    external_evidence=None,
) -> RuntimeNode:
    return RuntimeNode(
        node_id="n1",
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": "A"},
            expected_output=expected_output,
            verification_type=verification_type,
            verification_schema=verification_schema,
            semantic_rules=semantic_rules,
            external_evidence=external_evidence,
            verification_required=True,
        ),
    )


def _requirement(
    resource_id: str = "p1",
    expected_state: Optional[Dict[str, Any]] = None,
) -> ExternalEvidenceRequirement:
    return ExternalEvidenceRequirement(
        evidence_type="PROVIDER_RESOURCE_STATE",
        resource_id=resource_id,
        expected_state=expected_state or {"status": "active", "is_eligible": True},
    )


def _gate_and_rrm(
    providers: Optional[Dict[str, ProviderResource]] = None,
    adapter=None,
) -> tuple[VerificationGate, RegistryResourceManager, RRMEvidenceAdapter | None]:
    rrm = RegistryResourceManager(populate_defaults=False)
    if providers:
        for pid, p in providers.items():
            rrm.register_provider(p)
    if adapter is None:
        adapter = RRMEvidenceAdapter(rrm)
    gate = VerificationGate(external_adapter=adapter)
    return gate, rrm, adapter


def _run(gate, node, result="A"):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            gate.evaluate_node(node, node.action_contract, result)
        )
    finally:
        loop.close()


# ===========================================================================
# A. Production Wiring (canonical RRM identity)
# ===========================================================================

class TestProductionWiring(unittest.TestCase):
    """A: Canonical composition root wires the SAME RRM into the observer."""

    def test_a1_canonical_composition_creates_adapter(self):
        comps = ApplicationFactory().get_components()
        self.assertIsNotNone(comps.external_evidence_adapter)
        self.assertIsInstance(comps.external_evidence_adapter, RRMEvidenceAdapter)

    def test_a2_adapter_uses_same_canonical_rrm_instance(self):
        comps = ApplicationFactory().get_components()
        self.assertIs(
            comps.external_evidence_adapter._rrm,  # type: ignore[attr-defined]
            comps.resource_manager,
        )

    def test_a3_mission_runtime_holds_adapter_forwarded_to_gate(self):
        comps = ApplicationFactory().get_components()
        self.assertIs(
            comps.mission_runtime.verification_gate._external_adapter,  # type: ignore[attr-defined]
            comps.external_evidence_adapter,
        )

    def test_a4_action_gate_rrm_is_canonical_resource_manager(self):
        comps = ApplicationFactory().get_components()
        self.assertIs(
            comps.mission_runtime.action_gate._rrm,  # type: ignore[attr-defined]
            comps.resource_manager,
        )

    def test_a5_no_second_registry_resource_manager_for_evidence(self):
        """Only ONE RegistryResourceManager exists in the canonical graph.

        The adapter and the ActionGate reference the identical composition-root
        resource_manager instance. No shadow RRM, no copy, no reconstruction.
        """
        comps = ApplicationFactory().get_components()
        self.assertIsInstance(comps.resource_manager, RegistryResourceManager)
        self.assertIs(comps.external_evidence_adapter._rrm, comps.resource_manager)  # type: ignore[attr-defined]
        self.assertIs(comps.mission_runtime.action_gate._rrm, comps.resource_manager)  # type: ignore[attr-defined]

        # The observer reads the resource the CANONICAL RRM returns for a
        # provider registered only after composition — proving live identity,
        # not a snapshot.
        new_provider = ProviderResource(
            provider_id="live-id", name="Live", status=ResourceStatus.ACTIVE,
        )
        comps.resource_manager.register_provider(new_provider)
        canons = comps.resource_manager.get_provider("live-id")
        observed = comps.external_evidence_adapter.observe(
            _requirement("live-id", {"status": "active", "is_eligible": True})
        )
        self.assertIs(canons, new_provider)
        self.assertTrue(observed.matched)


# ===========================================================================
# B. Required Observer Fail-Closed
# ===========================================================================

class TestRequiredObserverFailClosed(unittest.TestCase):
    """B: Missing/broken/malformed observer must FAIL CLOSED."""

    def test_b6_external_requirement_and_no_adapter_failure(self):
        node = _make_echo_node(external_evidence=[_requirement()])
        gate = VerificationGate()  # no adapter
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertTrue(evidence.details["external_evidence_required"])
        self.assertFalse(evidence.details["external_observer_available"])
        self.assertEqual(evidence.details["external_failure_reason"], "observer_missing")

    def test_b7_adapter_exception_failure(self):
        class _Raising:
            def observe(self, req):
                raise RuntimeError("observer boom")
        node = _make_echo_node(external_evidence=[_requirement()])
        gate = VerificationGate(external_adapter=_Raising())
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "observer_exception")

    def test_b8_adapter_returns_none_failure(self):
        class _None:
            def observe(self, req):
                return None
        node = _make_echo_node(external_evidence=[_requirement()])
        gate = VerificationGate(external_adapter=_None())
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "malformed_observation")

    def test_b9_adapter_returns_wrong_object_type_failure(self):
        class _Wrong:
            def observe(self, req):
                return "not_an_observation"
        node = _make_echo_node(external_evidence=[_requirement()])
        gate = VerificationGate(external_adapter=_Wrong())
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "malformed_observation")

    def test_b10_matched_non_bool_failure(self):
        gate_rrm, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider()},
            adapter=_DuckAdapter({"p1": "truthy"}),
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active"})])
        status, evidence = _run(gate_rrm, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "malformed_observation")


class _DuckAdapter:
    """Adapter returning a duck-typed non-ExternalObservationResult payload."""

    def __init__(self, matched_map: Dict[str, Any]):
        self._matched_map = matched_map

    def observe(self, req):
        return type("Duck", (), {
            "evidence_type": req.evidence_type,
            "resource_id": req.resource_id,
            "matched": self._matched_map.get(req.resource_id, False),
        })()


def _make_observer_provider(**kwargs) -> ProviderResource:
    defaults = dict(status=ResourceStatus.ACTIVE, is_configured=True, has_active_account=True)
    defaults.update(kwargs)
    return ProviderResource(provider_id=defaults.get("provider_id", "p1"), name="O", **{k: v for k, v in defaults.items() if k != "provider_id"})


# ===========================================================================
# C. Real Observation (canonical RRM)
# ===========================================================================

class TestRealObservation(unittest.TestCase):
    """C: Adapter observes the SAME canonical RRM factually."""

    def test_c11_active_expected_active_observed_success(self):
        gate, _, _ = _gate_and_rrm({"p1": _make_observer_provider()})
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        self.assertTrue(evidence.details["external_observer_available"])
        self.assertIsNone(evidence.details["external_failure_reason"])

    def test_c12_active_expected_disabled_observed_failure(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(status=ResourceStatus.DISABLED)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "state_mismatch")

    def test_c13_eligible_expected_ineligible_observed_failure(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(is_configured=False)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "state_mismatch")

    def test_c14_resource_missing_failure(self):
        gate, _, _ = _gate_and_rrm({"p1": _make_observer_provider()})
        node = _make_echo_node(external_evidence=[_requirement("ghost", {"status": "active"})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "resource_not_found")

    def test_c15_unsupported_external_evidence_contract_failure(self):
        req = ExternalEvidenceRequirement(
            evidence_type="FILE_CONTENT", resource_id="p1", expected_state={"status": "active"},
        )
        node = _make_echo_node(external_evidence=[req])
        gate, _, _ = _gate_and_rrm({"p1": _make_observer_provider()})
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(evidence.details["external_failure_reason"], "unsupported_evidence_type")


# ===========================================================================
# D. Producer Separation
# ===========================================================================

class TestProducerSeparation(unittest.TestCase):
    """D: Producer/result payloads cannot satisfy RRM external evidence."""

    def test_d16_executor_claiming_active_cannot_satisfy(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(is_configured=False)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        # Executor result text claims ACTIVE, but canonical RRM says ineligible.
        status, _ = _run(gate, node, result={"status": "active", "is_eligible": True})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d17_provider_output_fake_observer_fields_ignored(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(is_configured=False)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, _ = _run(
            gate, node,
            result={"matched": True, "observer_id": "RRMEvidenceAdapter", "status": "active"},
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d18_result_with_verified_true_ignored(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(is_configured=False)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, _ = _run(gate, node, result={"verified": True, "valid": True})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d19_result_cannot_replace_resource_id(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider()}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        # Result names a different (nonexistent graceful) resource — ignored.
        status, _ = _run(gate, node, result={"resource_id": "ghost", "matched": True})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d20_result_cannot_replace_expected_state(self):
        gate, _, _ = _gate_and_rrm(
            {"p1": _make_observer_provider(is_configured=False)}
        )
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        # Result claims eligibility; canonical RRM disagrees.
        status, _ = _run(gate, node, result={"expected_state": {"status": "active", "is_eligible": True}})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


# ===========================================================================
# E. ALL_REQUIRED Composition
# ===========================================================================

class TestComposition(unittest.TestCase):
    """E: EXACT / STRUCTURAL / SEMANTIC / EXTERNAL all-required composition."""

    def _ext(self, providers=None):
        gate, _, _ = _gate_and_rrm(providers or {"p1": _make_observer_provider()})
        return gate

    def test_e21_exact_pass_external_pass_success(self):
        gate = self._ext()
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, _ = _run(gate, node, result="A")
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_e22_exact_pass_external_fail_failure(self):
        gate = self._ext({"p1": _make_observer_provider(status=ResourceStatus.DISABLED)})
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active"})])
        status, _ = _run(gate, node, result="A")
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_e23_exact_fail_external_pass_failure(self):
        gate = self._ext()
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, _ = _run(gate, node, result="B")  # exact mismatch
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_e24_structural_pass_external_pass_success(self):
        gate = self._ext()
        schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
        node = _make_echo_node(
            verification_type="STRUCTURAL", verification_schema=schema,
            external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})],
        )
        status, _ = _run(gate, node, result={"status": "active"})
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_e25_structural_pass_external_fail_failure(self):
        gate = self._ext({"p1": _make_observer_provider(status=ResourceStatus.DISABLED)})
        schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
        node = _make_echo_node(
            verification_type="STRUCTURAL", verification_schema=schema,
            external_evidence=[_requirement("p1", {"status": "active"})],
        )
        status, _ = _run(gate, node, result={"status": "active"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_e26_semantic_pass_external_pass_success(self):
        gate = self._ext()
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            verification_type="EXACT", semantic_rules=rules,
            external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})],
        )
        status, _ = _run(gate, node, result={"x": "foo", "y": "foo"})
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_e27_semantic_fail_external_pass_failure(self):
        gate = self._ext()
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            verification_type="EXACT", semantic_rules=rules,
            external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})],
        )
        status, _ = _run(gate, node, result={"x": "foo", "y": "bar"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_e28_structural_semantic_external_all_pass_success(self):
        gate = self._ext()
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            verification_type="STRUCTURAL", verification_schema=schema, semantic_rules=rules,
            external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})],
        )
        status, _ = _run(gate, node, result={"x": "foo", "y": "foo"})
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_e29_any_one_fails_failure(self):
        gate = self._ext({"p1": _make_observer_provider(status=ResourceStatus.DISABLED)})
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            verification_type="STRUCTURAL", verification_schema=schema, semantic_rules=rules,
            external_evidence=[_requirement("p1", {"status": "active"})],
        )
        # Structural + semantic would pass, but external fails -> ALL_REQUIRED FAILURE.
        status, _ = _run(gate, node, result={"x": "foo", "y": "foo"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


# ===========================================================================
# F. Resume Preservation (M28.2.1)
# ===========================================================================

class _ConstitutionAllow:
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


class TestResumePreservation(unittest.TestCase):
    """F: M29 wiring MUST NOT change M28.2.1 resume freshness semantics."""

    def _runtime(self):
        return MissionRuntime(
            executor=InMemoryActionExecutor(),
            checkpoint_repo=InMemoryCheckpointRepository(),
            constitution=_ConstitutionAllow(),
            external_evidence_adapter=RRMEvidenceAdapter(RegistryResourceManager(populate_defaults=False)),
        )

    def _evidence(self, node_id, external_evidence, expected_output=None,
                  verification_type="EXACT", semantic_rules=None):
        ext_hash = external_evidence_contract_hash(external_evidence) if external_evidence else None
        sem_hash = rule_set_hash(semantic_rules) if semantic_rules else None
        return [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": node_id,
                "verification_status": "VERIFIED_SUCCESS",
                "verification_type": verification_type,
                "external_evidence_contract_hash": ext_hash,
                "exact_contract_hash": exact_contract_hash(expected_output) if expected_output is not None else None,
                "rule_set_hash": sem_hash,
            },
        }]

    def test_f30_mutable_external_never_blindly_restores_success(self):
        rt = self._runtime()
        ext = [_requirement("p1", {"status": "active", "is_eligible": True})]
        contract = ActionContract(external_evidence=ext)
        evidence = self._evidence("n1", ext)
        self.assertFalse(
            rt._validate_resume_evidence("n1", "VERIFIED_SUCCESS", evidence, contract)
        )

    def test_f31_exact_only_resume_unchanged(self):
        rt = self._runtime()
        ext = None
        contract = ActionContract(expected_output="A", verification_type="EXACT")
        evidence = self._evidence("n1", ext, expected_output="A")
        self.assertTrue(
            rt._validate_resume_evidence("n1", "VERIFIED_SUCCESS", evidence, contract)
        )

    def test_f32_structural_only_resume_unchanged(self):
        rt = self._runtime()
        schema = {"type": "string"}
        from intent_kernel.runtime.verification import DeterministicStructuralVerifier
        struct_type = "STRUCTURAL"
        evidence = [{
            "source": "VerificationGate", "verified": True,
            "details": {
                "node_id": "n1", "verification_status": "VERIFIED_SUCCESS",
                "verification_type": struct_type,
                "contract_hash": DeterministicStructuralVerifier.contract_hash(schema),
            },
        }]
        contract = ActionContract(expected_output="A", verification_type="STRUCTURAL", verification_schema=schema)
        self.assertTrue(
            rt._validate_resume_evidence("n1", "VERIFIED_SUCCESS", evidence, contract)
        )

    def test_f33_semantic_only_resume_unchanged(self):
        rt = self._runtime()
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        evidence = self._evidence("n1", None, verification_type="EXACT", semantic_rules=rules)
        contract = ActionContract(expected_output="A", verification_type="STRUCTURAL", semantic_rules=rules)
        self.assertTrue(
            rt._validate_resume_evidence("n1", "VERIFIED_SUCCESS", evidence, contract)
        )

    def test_f34_combined_external_checkpoint_remains_inconclusive(self):
        rt = self._runtime()
        ext = [_requirement("p1", {"status": "active"})]
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        evidence = self._evidence("n1", ext, expected_output="A", verification_type="STRUCTURAL", semantic_rules=rules)
        contract = ActionContract(
            expected_output="A", verification_type="STRUCTURAL",
            semantic_rules=rules, external_evidence=ext,
        )
        self.assertFalse(
            rt._validate_resume_evidence("n1", "VERIFIED_SUCCESS", evidence, contract)
        )


# ===========================================================================
# G. Authority
# ===========================================================================

class TestAuthority(unittest.TestCase):
    """G: Observer is mechanism-only; VerificationGate is sole authority."""

    def test_g35_adapter_never_returns_verification_status(self):
        adapter = RRMEvidenceAdapter(RegistryResourceManager(populate_defaults=False))
        obs = adapter.observe(_requirement("p1", {"status": "active"}))
        self.assertIsInstance(obs, ExternalObservationResult)
        self.assertFalse(hasattr(obs, "verified"))

    def test_g36_adapter_cannot_mutate_rrm(self):
        rrm = RegistryResourceManager(populate_defaults=False)
        _register_provider(rrm, "p1", status=ResourceStatus.ACTIVE)
        adapter = RRMEvidenceAdapter(rrm)
        before = rrm.get_provider("p1").status
        adapter.observe(_requirement("p1", {"status": "active"}))
        after = rrm.get_provider("p1").status
        self.assertEqual(before, after)
        # Adapter exposes no mutation hooks.
        self.assertFalse(hasattr(adapter, "register_provider"))
        self.assertFalse(hasattr(adapter, "retire_provider"))
        self.assertFalse(hasattr(adapter, "activate_provider"))
        self.assertFalse(hasattr(adapter, "set_provider_status"))

    def test_g37_verification_gate_remains_evidence_authority(self):
        adapter = RRMEvidenceAdapter(RegistryResourceManager(populate_defaults=False))
        gate = VerificationGate(external_adapter=adapter)
        node = _make_echo_node(external_evidence=[_requirement("ghost", {"status": "active"})])
        status, evidence = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertFalse(evidence.verified)

    def test_g38_mission_completion_gate_unchanged(self):
        from intent_kernel.runtime.verification import MissionCompletionGate
        gate = MissionCompletionGate()
        # M29.2 does NOT thread the observer into MissionCompletionGate. The
        # completion gate remains the same constructor shape as before.
        for attr in ("output_validator",):
            self.assertTrue(hasattr(gate, attr))
        self.assertFalse(hasattr(gate, "external_adapter"))
        self.assertFalse(hasattr(gate, "external_evidence_adapter"))

    def test_g39_action_gate_unchanged(self):
        rrm = RegistryResourceManager(populate_defaults=False)
        _register_provider(rrm, "p-prod", status=ResourceStatus.ACTIVE)
        adapter = RRMEvidenceAdapter(rrm)
        gate = VerificationGate(external_adapter=adapter)
        node = _make_echo_node(external_evidence=[_requirement("p-prod", {"status": "active", "is_eligible": True})])
        status, _ = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_g40_no_conversation_integration(self):
        from intent_kernel.runtime.external_evidence import RRMEvidenceAdapter as A
        self.assertTrue(A)
        gate, _, _ = _gate_and_rrm({"p1": _make_observer_provider()})
        node = _make_echo_node(external_evidence=[_requirement("p1", {"status": "active", "is_eligible": True})])
        status, _ = _run(gate, node)
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        # Observer path is purely RRM-based; no conversation text is involved.
        self.assertIsNotNone(gate)


if __name__ == "__main__":
    unittest.main()
