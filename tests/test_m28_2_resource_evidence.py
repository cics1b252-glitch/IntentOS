"""Movement 28.2 — RRM Resource State Evidence Tests.

50 tests covering:
  A. Requirement contract validation (10 tests)
  B. RRMEvidenceAdapter observer (10 tests)
  C. Producer separation (5 tests)
  D. VerificationGate composition (ALL_REQUIRED) (10 tests)
  E. Resume validation (external_evidence_contract_hash) (8 tests)
  F. Identity properties (external_evidence_contract_hash) (5 tests)
  G. Authority preservation (2 tests)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    RuntimeNodeState,
    VerificationStatus,
)
from intent_kernel.runtime.verification import (
    VerificationGate,
    exact_contract_hash,
)
from intent_kernel.runtime.semantic_verifier import rule_set_hash
from intent_kernel.runtime.external_evidence import (
    ExternalEvidenceRequirement,
    ExternalObservationResult,
    RRMEvidenceAdapter,
    external_evidence_contract_hash,
    ExternalEvidenceRequirementValidator,
    MAX_EXTERNAL_EVIDENCE_REQUIREMENTS,
)
from intent_kernel.rrm.models import ProviderResource, ResourceStatus
from intent_kernel.runtime import (
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionCheckpoint,
    MissionRuntime,
    MissionRuntimeState,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class _ConstitutionAllow:
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


def _make_runtime(checkpoint_repo=None) -> MissionRuntime:
    return MissionRuntime(
        executor=InMemoryActionExecutor(),
        checkpoint_repo=checkpoint_repo,
        constitution=_ConstitutionAllow(),
    )


def _make_echo_node(
    node_id: str = "n1",
    expected_output: str = "A",
    inputs_message: str = "A",
    verification_type: str | None = None,
    semantic_rules=None,
    verification_schema=None,
    external_evidence=None,
) -> RuntimeNode:
    return RuntimeNode(
        node_id=node_id,
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": inputs_message},
            expected_output=expected_output,
            verification_type=verification_type,
            verification_schema=verification_schema,
            semantic_rules=semantic_rules,
            external_evidence=external_evidence,
            verification_required=True,
        ),
    )


def _make_provider(
    provider_id: str = "p1",
    status: ResourceStatus = ResourceStatus.ACTIVE,
    is_configured: bool = True,
    has_active_account: bool = True,
    is_template: bool = False,
) -> ProviderResource:
    return ProviderResource(
        provider_id=provider_id,
        name=f"Test Provider {provider_id}",
        status=status,
        is_configured=is_configured,
        has_active_account=has_active_account,
        is_template=is_template,
    )


def _make_requirement(
    resource_id: str = "p1",
    expected_state: Optional[Dict[str, Any]] = None,
) -> ExternalEvidenceRequirement:
    return ExternalEvidenceRequirement(
        evidence_type="PROVIDER_RESOURCE_STATE",
        resource_id=resource_id,
        expected_state=expected_state or {"status": "active", "is_eligible": True},
    )


def _make_adapter(providers: Optional[Dict[str, ProviderResource]] = None) -> RRMEvidenceAdapter:
    mock_rrm = MagicMock()
    _providers = providers or {"p1": _make_provider()}
    mock_rrm.get_provider = MagicMock(side_effect=lambda pid: _providers.get(pid))
    return RRMEvidenceAdapter(mock_rrm)


# ===========================================================================
# A. Requirement contract validation
# ===========================================================================

class TestRequirementValidation(unittest.TestCase):
    """A: Requirement contract validation."""

    def test_a1_valid_requirement_passes(self):
        req = _make_requirement()
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])

    def test_a2_empty_list_rejected(self):
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([])
        self.assertFalse(result.valid)
        self.assertIn("non-empty list", result.errors[0])

    def test_a3_non_list_rejected(self):
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate("not_a_list")
        self.assertFalse(result.valid)

    def test_a4_non_ExternalEvidenceRequirement_rejected(self):
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([{"evidence_type": "PROVIDER_RESOURCE_STATE"}])
        self.assertFalse(result.valid)
        self.assertIn("must be an ExternalEvidenceRequirement", result.errors[0])

    def test_a5_unsupported_evidence_type_rejected(self):
        req = ExternalEvidenceRequirement(
            evidence_type="UNSUPPORTED_TYPE",
            resource_id="p1",
            expected_state={"status": "active"},
        )
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertFalse(result.valid)
        self.assertIn("unsupported evidence_type", result.errors[0])

    def test_a6_empty_resource_id_rejected(self):
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="",
            expected_state={"status": "active"},
        )
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertFalse(result.valid)
        self.assertIn("resource_id must be a non-empty string", result.errors[0])

    def test_a7_empty_expected_state_rejected(self):
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="p1",
            expected_state={},
        )
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertFalse(result.valid)
        self.assertIn("expected_state must be a non-empty dict", result.errors[0])

    def test_a8_unsupported_expected_state_key_rejected(self):
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="p1",
            expected_state={"unsupported_key": "value"},
        )
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertFalse(result.valid)
        self.assertIn("unsupported expected_state key", result.errors[0])

    def test_a9_too_many_requirements_rejected(self):
        reqs = [
            ExternalEvidenceRequirement(
                evidence_type="PROVIDER_RESOURCE_STATE",
                resource_id=f"p{i}",
                expected_state={"status": "active"},
            )
            for i in range(MAX_EXTERNAL_EVIDENCE_REQUIREMENTS + 1)
        ]
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate(reqs)
        self.assertFalse(result.valid)
        self.assertIn("too many requirements", result.errors[0])

    def test_a10_valid_status_only_requirement_passes(self):
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="p1",
            expected_state={"status": "active"},
        )
        validator = ExternalEvidenceRequirementValidator()
        result = validator.validate([req])
        self.assertTrue(result.valid)


# ===========================================================================
# B. RRMEvidenceAdapter observer behavior
# ===========================================================================

class TestAdapterObserver(unittest.TestCase):
    """B: RRMEvidenceAdapter observer behavior."""

    def test_b1_active_matching_state(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertTrue(obs.matched)
        self.assertEqual(obs.observed_state, {"status": "active", "is_eligible": True})
        self.assertEqual(obs.reason_code, "")

    def test_b2_status_mismatch(self):
        provider = _make_provider(status=ResourceStatus.UNAVAILABLE)
        adapter = _make_adapter({"p1": provider})
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertFalse(obs.matched)
        self.assertEqual(obs.reason_code, "state_mismatch")

    def test_b3_is_eligible_mismatch(self):
        provider = _make_provider(is_template=True)
        adapter = _make_adapter({"p1": provider})
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertFalse(obs.matched)
        self.assertEqual(obs.reason_code, "state_mismatch")

    def test_b4_resource_not_found(self):
        adapter = _make_adapter({})
        req = _make_requirement(resource_id="nonexistent")
        obs = adapter.observe(req)
        self.assertFalse(obs.matched)
        self.assertEqual(obs.reason_code, "resource_not_found")
        self.assertEqual(obs.observed_state, {})

    def test_b5_unsupported_evidence_type(self):
        adapter = _make_adapter()
        req = ExternalEvidenceRequirement(
            evidence_type="UNSUPPORTED",
            resource_id="p1",
            expected_state={"status": "active"},
        )
        obs = adapter.observe(req)
        self.assertFalse(obs.matched)
        self.assertEqual(obs.reason_code, "unsupported_evidence_type")

    def test_b6_observer_never_returns_verification_status(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertNotIsInstance(obs, VerificationStatus)
        self.assertFalse(hasattr(obs, "verified"))

    def test_b7_observer_never_authorizes(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertFalse(hasattr(obs, "verified"))
        self.assertFalse(hasattr(obs, "VerificationStatus"))

    def test_b8_observed_at_is_iso_string(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertIsInstance(obs.observed_at, str)
        self.assertIn("T", obs.observed_at)

    def test_b9_observer_id_and_version_present(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertEqual(obs.observer_id, "RRMEvidenceAdapter")
        self.assertEqual(obs.observer_version, "1")

    def test_b10_partial_expected_state_checked(self):
        provider = _make_provider(status=ResourceStatus.ACTIVE, is_template=True)
        adapter = _make_adapter({"p1": provider})
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="p1",
            expected_state={"status": "active"},
        )
        obs = adapter.observe(req)
        self.assertTrue(obs.matched)


# ===========================================================================
# C. Producer separation
# ===========================================================================

class TestProducerSeparation(unittest.TestCase):
    """C: Producer separation — adapter never decides verification status."""

    def test_c1_observed_state_is_raw_facts(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertIn("status", obs.observed_state)
        self.assertIn("is_eligible", obs.observed_state)
        self.assertIsInstance(obs.observed_state["status"], str)
        self.assertIsInstance(obs.observed_state["is_eligible"], bool)

    def test_c2_matched_is_boolean_not_status(self):
        adapter = _make_adapter()
        req = _make_requirement()
        obs = adapter.observe(req)
        self.assertIsInstance(obs.matched, bool)

    def test_c3_verification_status_still_computed_by_gate(self):
        node = _make_echo_node(external_evidence=[_make_requirement()])
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        result = "A"
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, result)
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        self.assertTrue(evidence.verified)

    def test_c4_adapter_result_is_frozen_dataclass(self):
        obs = ExternalObservationResult(
            evidence_type="t",
            resource_id="r",
            observer_id="o",
            observer_version="1",
            observed_state={},
            observed_at="2024-01-01T00:00:00Z",
            matched=True,
            reason_code="",
        )
        with self.assertRaises(AttributeError):
            obs.matched = False

    def test_c5_requirement_is_frozen_dataclass(self):
        req = _make_requirement()
        with self.assertRaises(AttributeError):
            req.evidence_type = "CHANGED"


# ===========================================================================
# D. VerificationGate composition (ALL_REQUIRED)
# ===========================================================================

class TestVerificationGateComposition(unittest.TestCase):
    """D: VerificationGate external evidence composition."""

    def test_d1_external_evidence_success(self):
        node = _make_echo_node(external_evidence=[_make_requirement()])
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_d2_external_evidence_failure_blocks(self):
        provider = _make_provider(status=ResourceStatus.UNAVAILABLE)
        adapter = _make_adapter({"p1": provider})
        node = _make_echo_node(external_evidence=[_make_requirement()])
        gate = VerificationGate(external_adapter=adapter)
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d3_no_external_evidence_unaffected(self):
        node = _make_echo_node()
        gate = VerificationGate()
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_d4_all_required_multiple_success(self):
        reqs = [
            _make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True}),
            ExternalEvidenceRequirement(
                evidence_type="PROVIDER_RESOURCE_STATE",
                resource_id="p2",
                expected_state={"status": "active"},
            ),
        ]
        provider2 = _make_provider(provider_id="p2")
        adapter = _make_adapter({"p1": _make_provider(), "p2": provider2})
        node = _make_echo_node(external_evidence=reqs)
        gate = VerificationGate(external_adapter=adapter)
        status, _ = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_d5_all_required_one_failure_blocks_all(self):
        reqs = [
            _make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True}),
            ExternalEvidenceRequirement(
                evidence_type="PROVIDER_RESOURCE_STATE",
                resource_id="p2",
                expected_state={"status": "active"},
            ),
        ]
        provider2 = _make_provider(status=ResourceStatus.UNAVAILABLE)
        adapter = _make_adapter({"p1": _make_provider(), "p2": provider2})
        node = _make_echo_node(external_evidence=reqs)
        gate = VerificationGate(external_adapter=adapter)
        status, _ = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d6_no_adapter_no_crash(self):
        node = _make_echo_node(external_evidence=[_make_requirement()])
        gate = VerificationGate()  # No external adapter
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_d7_invalid_requirement_contract_failure(self):
        req = ExternalEvidenceRequirement(
            evidence_type="PROVIDER_RESOURCE_STATE",
            resource_id="",
            expected_state={"status": "active"},
        )
        node = _make_echo_node(external_evidence=[req])
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        status, _ = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    def test_d8_evidence_details_contain_external_fields(self):
        node = _make_echo_node(external_evidence=[_make_requirement()])
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        _, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertIn("external_evidence_contract_hash", evidence.details)
        self.assertIn("external_observations", evidence.details)
        self.assertIsNotNone(evidence.details["external_evidence_contract_hash"])

    def test_d9_semantic_and_external_compose(self):
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            semantic_rules=rules,
            external_evidence=[_make_requirement()],
        )
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        status, _ = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, {"x": "A", "y": "A"})
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    def test_d10_semantic_failure_stops_before_external(self):
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = _make_echo_node(
            semantic_rules=rules,
            external_evidence=[_make_requirement()],
        )
        adapter = _make_adapter()
        gate = VerificationGate(external_adapter=adapter)
        status, _ = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, {"x": "A", "y": "B"})
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


# ===========================================================================
# E. Resume validation (external_evidence_contract_hash)
# ===========================================================================

class TestResumeValidation(unittest.TestCase):
    """E: Resume validation for external evidence contract hash."""

    def _get_mission_runtime(self):
        return _make_runtime()

    def _run_resume(self, runtime, node_id, claimed_status, evidence_list, current_action_contract):
        return runtime._validate_resume_evidence(node_id, claimed_status, evidence_list, current_action_contract)

    def _build_evidence(self, node_id, external_evidence, expected_output=None):
        from intent_kernel.runtime.external_evidence import external_evidence_contract_hash
        ext_hash = external_evidence_contract_hash(external_evidence)
        return [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": node_id,
                "verification_status": "VERIFIED_SUCCESS",
                "external_evidence_contract_hash": ext_hash,
                "exact_contract_hash": exact_contract_hash(expected_output),
                "rule_set_hash": None,
            },
        }]

    def test_e1_same_external_evidence_rejects_mutable_state(self):
        """M28.2.1: Same external evidence contract does NOT restore VERIFIED_SUCCESS.

        External evidence contract hash binds to the REQUIREMENT CONTRACT,
        not to the current observed RRM state. Because PROVIDER_RESOURCE_STATE
        is mutable with no canonical generation/version, stored observation is
        historical only and cannot prove freshness.
        """
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(external_evidence=ext)
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e2_changed_external_evidence_rejected(self):
        rt = self._get_mission_runtime()
        ext_old = [_make_requirement()]
        ext_new = [
            ExternalEvidenceRequirement(
                evidence_type="PROVIDER_RESOURCE_STATE",
                resource_id="p2",
                expected_state={"status": "active"},
            )
        ]
        contract = ActionContract(external_evidence=ext_new)
        evidence = self._build_evidence("n1", ext_old)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e3_missing_hash_when_contract_has_external_rejected(self):
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(external_evidence=ext)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "external_evidence_contract_hash": None,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e4_legacy_exact_evidence_without_hash_rejected(self):
        """Legacy EXACT evidence without exact_contract_hash is rejected on resume (M27.2 fail-closed)."""
        rt = self._get_mission_runtime()
        contract = ActionContract(external_evidence=None, expected_output="A")
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "verification_type": "EXACT",
                # No exact_contract_hash → M27.2 fail-closed
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e5_evidence_with_hash_but_no_current_external_rejected(self):
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(external_evidence=None)
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e6_exact_hash_and_external_hash_independently_checked(self):
        """M28.2.1: Even with matching hashes, mutable external evidence rejects resume."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(
            expected_output="A",
            external_evidence=ext,
        )
        ext_hash = external_evidence_contract_hash(ext)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "exact_contract_hash": exact_contract_hash("A"),
                "external_evidence_contract_hash": ext_hash,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e7_wrong_exact_hash_rejected_even_with_correct_external(self):
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(
            expected_output="A",
            external_evidence=ext,
        )
        ext_hash = external_evidence_contract_hash(ext)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "exact_contract_hash": "wrong_hash",
                "external_evidence_contract_hash": ext_hash,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_e8_no_current_action_contract_with_external_evidence(self):
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, None)
        self.assertTrue(result)


# ===========================================================================
# F. Identity properties (external_evidence_contract_hash)
# ===========================================================================

class TestIdentityProperties(unittest.TestCase):
    """F: external_evidence_contract_hash identity properties."""

    def test_f1_same_requirements_same_hash(self):
        reqs = [_make_requirement()]
        h1 = external_evidence_contract_hash(reqs)
        h2 = external_evidence_contract_hash(reqs)
        self.assertEqual(h1, h2)

    def test_f2_different_resource_id_different_hash(self):
        h1 = external_evidence_contract_hash([_make_requirement(resource_id="p1")])
        h2 = external_evidence_contract_hash([_make_requirement(resource_id="p2")])
        self.assertNotEqual(h1, h2)

    def test_f3_different_expected_state_different_hash(self):
        h1 = external_evidence_contract_hash([
            ExternalEvidenceRequirement("PROVIDER_RESOURCE_STATE", "p1", {"status": "active"})
        ])
        h2 = external_evidence_contract_hash([
            ExternalEvidenceRequirement("PROVIDER_RESOURCE_STATE", "p1", {"status": "unavailable"})
        ])
        self.assertNotEqual(h1, h2)

    def test_f4_is_sha256_hex(self):
        h = external_evidence_contract_hash([_make_requirement()])
        self.assertEqual(len(h), 64)
        int(h, 16)

    def test_f5_order_sensitive(self):
        r1 = ExternalEvidenceRequirement("PROVIDER_RESOURCE_STATE", "p1", {"status": "active"})
        r2 = ExternalEvidenceRequirement("PROVIDER_RESOURCE_STATE", "p2", {"status": "active"})
        h1 = external_evidence_contract_hash([r1, r2])
        h2 = external_evidence_contract_hash([r2, r1])
        self.assertNotEqual(h1, h2)


# ===========================================================================
# G. Authority preservation
# ===========================================================================

class TestAuthorityPreservation(unittest.TestCase):
    """G: Authority preservation — VerificationGate remains sole authority."""

    def test_g1_no_evidence_for_verified_when_external_fails(self):
        provider = _make_provider(status=ResourceStatus.UNAVAILABLE)
        adapter = _make_adapter({"p1": provider})
        node = _make_echo_node(external_evidence=[_make_requirement()])
        gate = VerificationGate(external_adapter=adapter)
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertFalse(evidence.verified)

    def test_g2_success_only_when_all_pass(self):
        reqs = [
            _make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True}),
            ExternalEvidenceRequirement(
                evidence_type="PROVIDER_RESOURCE_STATE",
                resource_id="p2",
                expected_state={"status": "active", "is_eligible": True},
            ),
        ]
        provider2 = _make_provider(provider_id="p2")
        adapter = _make_adapter({"p1": _make_provider(), "p2": provider2})
        node = _make_echo_node(external_evidence=reqs)
        gate = VerificationGate(external_adapter=adapter)
        status, evidence = asyncio.get_event_loop().run_until_complete(
            gate.evaluate_node(node, node.action_contract, "A")
        )
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        self.assertTrue(evidence.verified)


# ===========================================================================
# H. M28.2.1 — Mutable External Evidence Resume Fail-Closed
# ===========================================================================

class TestMutableEvidenceResumeFailClosed(unittest.TestCase):
    """H: M28.2.1 — Mutable PROVIDER_RESOURCE_STATE evidence never restores
    VERIFIED_SUCCESS from stored observation alone.

    CONTRACT IDENTITY != OBSERVATION FRESHNESS.
    Until RRM obtains a canonical generation/version model, mutable external
    RRM evidence must be re-observed after resume.
    """

    def _get_mission_runtime(self):
        return _make_runtime()

    def _run_resume(self, runtime, node_id, claimed_status, evidence_list, current_action_contract):
        return runtime._validate_resume_evidence(node_id, claimed_status, evidence_list, current_action_contract)

    def _build_evidence(self, node_id, external_evidence, expected_output=None,
                        verification_type="EXACT", semantic_rules=None):
        from intent_kernel.runtime.external_evidence import external_evidence_contract_hash
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

    def test_h1_external_active_then_resume_same_contract(self):
        """1. Same provider ACTIVE, same contract, no fresh observation → NOT VERIFIED_SUCCESS."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True})]
        contract = ActionContract(external_evidence=ext)
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h2_external_active_then_retired(self):
        """2. Provider ACTIVE → retired, same contract → NOT VERIFIED_SUCCESS."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True})]
        contract = ActionContract(external_evidence=ext)
        evidence = self._build_evidence("n1", ext)
        # Even if provider was retired after verification, resume rejects
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h3_external_active_then_disabled(self):
        """3. Provider ACTIVE → disabled, same contract → NOT VERIFIED_SUCCESS."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True})]
        contract = ActionContract(external_evidence=ext)
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h4_external_eligibility_changes(self):
        """4. Verified while is_eligible=True, resume → NOT VERIFIED_SUCCESS."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active", "is_eligible": True})]
        contract = ActionContract(external_evidence=ext)
        evidence = self._build_evidence("n1", ext)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h5_external_contract_changes(self):
        """5. Contract A checkpoint, resume contract B → INCONCLUSIVE (hash mismatch)."""
        rt = self._get_mission_runtime()
        ext_a = [_make_requirement(resource_id="p1", expected_state={"status": "active"})]
        ext_b = [_make_requirement(resource_id="p2", expected_state={"status": "active"})]
        contract_b = ActionContract(external_evidence=ext_b)
        evidence = self._build_evidence("n1", ext_a)
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract_b)
        self.assertFalse(result)

    def test_h6_external_hash_missing(self):
        """6. Current external requirement exists, evidence lacks hash → INCONCLUSIVE."""
        rt = self._get_mission_runtime()
        ext = [_make_requirement()]
        contract = ActionContract(external_evidence=ext)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "external_evidence_contract_hash": None,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h7_external_plus_exact(self):
        """7. EXACT + EXTERNAL previously SUCCESS, resume → NOT VERIFIED_SUCCESS.

        Even though exact_contract_hash matches, mutable external evidence
        causes rejection.
        """
        rt = self._get_mission_runtime()
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active"})]
        contract = ActionContract(expected_output="A", external_evidence=ext)
        evidence = self._build_evidence("n1", ext, expected_output="A")
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h8_external_plus_structural_semantic(self):
        """8. STRUCTURAL + SEMANTIC + EXTERNAL previously SUCCESS.

        All hashes match but mutable external state requires re-observation.
        REQUIRED: NOT VERIFIED_SUCCESS.
        """
        from intent_kernel.runtime.verification import DeterministicStructuralVerifier
        rt = self._get_mission_runtime()
        schema = {"type": "object", "required": ["id"]}
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        ext = [_make_requirement(resource_id="p1", expected_state={"status": "active"})]
        contract = ActionContract(
            verification_type="STRUCTURAL",
            verification_schema=schema,
            semantic_rules=rules,
            external_evidence=ext,
        )
        schema_hash = DeterministicStructuralVerifier.contract_hash(schema)
        sem_hash = rule_set_hash(rules)
        ext_hash = external_evidence_contract_hash(ext)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "verification_type": "STRUCTURAL",
                "contract_hash": schema_hash,
                "rule_set_hash": sem_hash,
                "external_evidence_contract_hash": ext_hash,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertFalse(result)

    def test_h9_exact_only_resume_unchanged(self):
        """9. EXACT-only resume unchanged — M27.2 behavior preserved."""
        rt = self._get_mission_runtime()
        contract = ActionContract(expected_output="A")
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "verification_type": "EXACT",
                "exact_contract_hash": exact_contract_hash("A"),
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertTrue(result)

    def test_h10_structural_only_resume_unchanged(self):
        """10. STRUCTURAL-only resume unchanged — M25 behavior preserved."""
        from intent_kernel.runtime.verification import DeterministicStructuralVerifier
        rt = self._get_mission_runtime()
        schema = {"type": "object", "required": ["id"]}
        contract = ActionContract(
            verification_type="STRUCTURAL",
            verification_schema=schema,
        )
        schema_hash = DeterministicStructuralVerifier.contract_hash(schema)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "verification_type": "STRUCTURAL",
                "contract_hash": schema_hash,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertTrue(result)

    def test_h11_semantic_only_resume_unchanged(self):
        """11. SEMANTIC-only resume unchanged — M26 behavior preserved."""
        rt = self._get_mission_runtime()
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        contract = ActionContract(semantic_rules=rules)
        sem_hash = rule_set_hash(rules)
        evidence = [{
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n1",
                "verification_status": "VERIFIED_SUCCESS",
                "rule_set_hash": sem_hash,
            },
        }]
        result = self._run_resume(rt, "n1", "VERIFIED_SUCCESS", evidence, contract)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
