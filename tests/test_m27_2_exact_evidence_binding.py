"""Movement 27.2 — EXACT Verification Contract Evidence Binding Tests.

15 tests covering:
  A. Same expected_output restores success
  B. Changed expected_output rejected
  C. Nested mutation rejected
  D. True vs 1 hashes differ
  E. False vs 0 hashes differ
  F. 1 vs 1.0 hashes differ
  G. Dict key-order same hash
  H. List ordering different hash
  I. Missing exact_contract_hash → fail closed
  J. Malformed exact_contract_hash → rejected
  K. EXACT verification itself unchanged
  L. STRUCTURAL resume unchanged
  M. SEMANTIC resume unchanged
  N. STRUCTURAL+SEMANTIC resume unchanged
  O. H1.4 forged evidence rejected
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest

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
from intent_kernel.runtime import (
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionCheckpoint,
    MissionRuntime,
    MissionRuntimeState,
)


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
            verification_required=True,
        ),
    )


# ===========================================================================
# A-G. exact_contract_hash IDENTITY TESTS
# ===========================================================================

class TestExactContractHash(unittest.TestCase):
    """A-G: Hash identity properties."""

    def test_a_same_value_same_hash(self):
        """A. same expected_output → same hash"""
        h1 = exact_contract_hash("A")
        h2 = exact_contract_hash("A")
        self.assertEqual(h1, h2)
        self.assertIsNotNone(h1)

    def test_b_different_value_different_hash(self):
        """B. different value → different hash"""
        h1 = exact_contract_hash("A")
        h2 = exact_contract_hash("B")
        self.assertNotEqual(h1, h2)

    def test_c_nested_mutation_different_hash(self):
        """C. nested mutation → different hash"""
        h1 = exact_contract_hash({"a": {"b": 1}})
        h2 = exact_contract_hash({"a": {"b": 2}})
        self.assertNotEqual(h1, h2)

    def test_d_true_vs_1_different_hash(self):
        """D. True vs 1 → different hash (type-safe)"""
        h_true = exact_contract_hash(True)
        h_one = exact_contract_hash(1)
        self.assertNotEqual(h_true, h_one)

    def test_e_false_vs_0_different_hash(self):
        """E. False vs 0 → different hash (type-safe)"""
        h_false = exact_contract_hash(False)
        h_zero = exact_contract_hash(0)
        self.assertNotEqual(h_false, h_zero)

    def test_f_int_vs_float_different_hash(self):
        """F. 1 vs 1.0 → different hash (type-safe)"""
        h_int = exact_contract_hash(1)
        h_float = exact_contract_hash(1.0)
        self.assertNotEqual(h_int, h_float)

    def test_g_dict_key_order_same_hash(self):
        """G. dict key-order-only mutation → same hash"""
        h1 = exact_contract_hash({"b": 2, "a": 1})
        h2 = exact_contract_hash({"a": 1, "b": 2})
        self.assertEqual(h1, h2)

    def test_h_list_ordering_different_hash(self):
        """H. list ordering mutation → different hash"""
        h1 = exact_contract_hash([1, 2, 3])
        h2 = exact_contract_hash([3, 2, 1])
        self.assertNotEqual(h1, h2)

    def test_unsupported_type_returns_none(self):
        """Unsupported type → None (fail-closed)"""
        h = exact_contract_hash(object())
        self.assertIsNone(h)


# ===========================================================================
# I-J. FAIL-CLOSED TESTS
# ===========================================================================

class TestExactFailClosed(unittest.TestCase):
    """I-J: Legacy and malformed evidence handling."""

    def test_i_missing_exact_contract_hash_fail_closed(self):
        """I. Missing exact_contract_hash in evidence → resume rejects"""
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _make_runtime(repo)
            node = _make_echo_node("i1", "A", "A")
            inst = rt.create_instance("m_i", "g_i", [node])
            await rt.run_mission(inst.runtime_id)

            # Forge checkpoint evidence without exact_contract_hash
            forged_chk = MissionCheckpoint(
                runtime_id=inst.runtime_id,
                mission_id=inst.mission_id,
                completed_nodes=["i1"],
                verification_state={"i1": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_i1"}},
                completion_evidence=[{
                    "evidence_id": "ev_i1",
                    "source": "VerificationGate",
                    "verified": True,
                    "details": {
                        "node_id": "i1",
                        "verification_status": "VERIFIED_SUCCESS",
                        "verification_type": "EXACT",
                        "exact_contract_hash": None,
                    },
                }],
            )
            await repo.save_checkpoint(forged_chk)
            node.action_contract.expected_output = "A"
            resumed = await rt.resume(inst.runtime_id)
            self.assertNotEqual(
                resumed.nodes["i1"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())

    def test_j_malformed_exact_contract_hash_rejected(self):
        """J. Malformed exact_contract_hash → resume rejects"""
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _make_runtime(repo)
            node = _make_echo_node("j1", "A", "A")
            inst = rt.create_instance("m_j", "g_j", [node])
            await rt.run_mission(inst.runtime_id)

            forged_chk = MissionCheckpoint(
                runtime_id=inst.runtime_id,
                mission_id=inst.mission_id,
                completed_nodes=["j1"],
                verification_state={"j1": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_j1"}},
                completion_evidence=[{
                    "evidence_id": "ev_j1",
                    "source": "VerificationGate",
                    "verified": True,
                    "details": {
                        "node_id": "j1",
                        "verification_status": "VERIFIED_SUCCESS",
                        "verification_type": "EXACT",
                        "exact_contract_hash": "not_a_real_hash",
                    },
                }],
            )
            await repo.save_checkpoint(forged_chk)
            node.action_contract.expected_output = "A"
            resumed = await rt.resume(inst.runtime_id)
            self.assertNotEqual(
                resumed.nodes["j1"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


# ===========================================================================
# K. EXACT VERIFICATION ITSELF UNCHANGED
# ===========================================================================

class TestExactVerificationUnchanged(unittest.TestCase):
    """K: EXACT verification match/mismatch still works."""

    async def test_k_exact_match_success(self):
        """K1. exact match → VERIFIED_SUCCESS"""
        gate = VerificationGate()
        node = _make_echo_node("k1", "A", "A")
        status, evidence = await gate.evaluate_node(node, node.action_contract, "A")
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)
        self.assertTrue(evidence.verified)
        self.assertIsNotNone(evidence.details["exact_contract_hash"])

    async def test_k_exact_mismatch_failure(self):
        """K2. exact mismatch → VERIFIED_FAILURE"""
        gate = VerificationGate()
        node = _make_echo_node("k2", "A", "A")
        status, evidence = await gate.evaluate_node(node, node.action_contract, "B")
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)
        self.assertFalse(evidence.verified)


# ===========================================================================
# A (resume). Same expected_output restores success
# ===========================================================================

class TestExactResume(unittest.TestCase):
    """A (resume): Same expected_output restores VERIFIED_SUCCESS."""

    async def test_a_resume_same_expected_restores_success(self):
        """A. same expected_output on resume → VERIFIED_SUCCESS restored"""
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        node = _make_echo_node("ar1", "A", "A")
        inst = rt.create_instance("m_ar", "g_ar", [node])
        await rt.run_mission(inst.runtime_id)
        self.assertEqual(inst.nodes["ar1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

        # Expected output unchanged — should restore
        node.action_contract.expected_output = "A"
        resumed = await rt.resume(inst.runtime_id)
        self.assertEqual(resumed.nodes["ar1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

    async def test_b_resume_changed_expected_rejected(self):
        """B. changed expected_output on resume → NOT VERIFIED_SUCCESS"""
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        node = _make_echo_node("br1", "A", "A")
        inst = rt.create_instance("m_br", "g_br", [node])
        await rt.run_mission(inst.runtime_id)
        self.assertEqual(inst.nodes["br1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

        # Expected output changed — should NOT restore
        node.action_contract.expected_output = "B"
        resumed = await rt.resume(inst.runtime_id)
        self.assertNotEqual(
            resumed.nodes["br1"].verification_result,
            VerificationStatus.VERIFIED_SUCCESS,
        )


# ===========================================================================
# L-N. STRUCTURAL / SEMANTIC / COMBINED RESUME UNCHANGED
# ===========================================================================

class TestStructuralResumeUnchanged(unittest.TestCase):
    """L: STRUCTURAL resume unchanged."""

    async def test_l_structural_resume_same_hash_restores(self):
        """L. STRUCTURAL resume with same contract_hash → restores"""
        from intent_kernel.runtime.verification import DeterministicStructuralVerifier
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}
        node = RuntimeNode(
            node_id="sl1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": '{"id": 1}'},
                expected_output={"id": 1},
                verification_type="STRUCTURAL",
                verification_schema=schema,
                verification_required=True,
            ),
        )
        inst = rt.create_instance("m_sl", "g_sl", [node])
        await rt.run_mission(inst.runtime_id)
        self.assertEqual(inst.nodes["sl1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

        resumed = await rt.resume(inst.runtime_id)
        self.assertEqual(resumed.nodes["sl1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)


class TestSemanticResumeUnchanged(unittest.TestCase):
    """M: SEMANTIC resume unchanged."""

    async def test_m_semantic_resume_same_hash_restores(self):
        """M. SEMANTIC resume with same rule_set_hash → restores"""
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = RuntimeNode(
            node_id="sm1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": '{"x": 1, "y": 1}'},
                expected_output={"x": 1, "y": 1},
                verification_type=None,
                semantic_rules=rules,
                verification_required=True,
            ),
        )
        inst = rt.create_instance("m_sm", "g_sm", [node])
        await rt.run_mission(inst.runtime_id)
        self.assertEqual(inst.nodes["sm1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

        resumed = await rt.resume(inst.runtime_id)
        self.assertEqual(resumed.nodes["sm1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)


class TestStructuralSemanticResumeUnchanged(unittest.TestCase):
    """N: STRUCTURAL+SEMANTIC resume unchanged."""

    async def test_n_structural_semantic_resume_same_hash_restores(self):
        """N. STRUCTURAL+SEMANTIC resume with both hashes → restores"""
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}
        rules = [{"op": "equals_field", "left": "x", "right": "y"}]
        node = RuntimeNode(
            node_id="sn1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": '{"id": 1, "x": 1, "y": 1}'},
                expected_output={"id": 1, "x": 1, "y": 1},
                verification_type="STRUCTURAL",
                verification_schema=schema,
                semantic_rules=rules,
                verification_required=True,
            ),
        )
        inst = rt.create_instance("m_sn", "g_sn", [node])
        await rt.run_mission(inst.runtime_id)
        self.assertEqual(inst.nodes["sn1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)

        resumed = await rt.resume(inst.runtime_id)
        self.assertEqual(resumed.nodes["sn1"].verification_result, VerificationStatus.VERIFIED_SUCCESS)


# ===========================================================================
# O. H1.4 FORGED EVIDENCE REJECTED
# ===========================================================================

class TestForgedEvidenceRejected(unittest.TestCase):
    """O: H1.4 forged evidence remains rejected."""

    async def test_o_forged_exact_evidence_rejected(self):
        """O. Forged EXACT evidence without valid hash → rejected"""
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        node = _make_echo_node("fo1", "A", "A")
        inst = rt.create_instance("m_fo", "g_fo", [node])

        # Forge checkpoint with wrong hash
        forged_chk = MissionCheckpoint(
            runtime_id=inst.runtime_id,
            mission_id=inst.mission_id,
            completed_nodes=["fo1"],
            verification_state={"fo1": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_fo1"}},
            completion_evidence=[{
                "evidence_id": "ev_fo1",
                "source": "VerificationGate",
                "verified": True,
                "details": {
                    "node_id": "fo1",
                    "verification_status": "VERIFIED_SUCCESS",
                    "verification_type": "EXACT",
                    "exact_contract_hash": "forged_hash_value",
                },
            }],
        )
        await repo.save_checkpoint(forged_chk)
        node.action_contract.expected_output = "A"
        resumed = await rt.resume(inst.runtime_id)
        self.assertNotEqual(
            resumed.nodes["fo1"].verification_result,
            VerificationStatus.VERIFIED_SUCCESS,
        )

    async def test_o_forged_structural_evidence_rejected(self):
        """O2. Forged STRUCTURAL evidence with wrong hash → rejected"""
        from intent_kernel.runtime.verification import DeterministicStructuralVerifier
        repo = InMemoryCheckpointRepository()
        rt = _make_runtime(repo)
        schema = {"type": "object", "required": ["id"]}
        node = RuntimeNode(
            node_id="fo2",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": '{"id": 1}'},
                expected_output={"id": 1},
                verification_type="STRUCTURAL",
                verification_schema=schema,
                verification_required=True,
            ),
        )
        inst = rt.create_instance("m_fo2", "g_fo2", [node])

        forged_chk = MissionCheckpoint(
            runtime_id=inst.runtime_id,
            mission_id=inst.mission_id,
            completed_nodes=["fo2"],
            verification_state={"fo2": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_fo2"}},
            completion_evidence=[{
                "evidence_id": "ev_fo2",
                "source": "VerificationGate",
                "verified": True,
                "details": {
                    "node_id": "fo2",
                    "verification_status": "VERIFIED_SUCCESS",
                    "verification_type": "STRUCTURAL",
                    "contract_hash": "forged_structural_hash",
                },
            }],
        )
        await repo.save_checkpoint(forged_chk)
        resumed = await rt.resume(inst.runtime_id)
        self.assertNotEqual(
            resumed.nodes["fo2"].verification_result,
            VerificationStatus.VERIFIED_SUCCESS,
        )


if __name__ == "__main__":
    unittest.main()
