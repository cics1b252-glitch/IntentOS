"""Movement 21 — Phase 21.2: Verification Authority Repair Tests.

Tests 1–17: expected_output=None always returns VERIFIED_FAILURE
Tests 18–19: expected_output present preserves existing semantics
Test 20–21: Mission runtime integration
Test 22: verification_required=False preservation
Test 23: Cross-movement regression (M11–M20)
"""

import unittest
from unittest import IsolatedAsyncioTestCase

from intent_kernel.runtime.models import ActionContract, RuntimeNode
from intent_kernel.runtime.verification import (
    InMemoryActionVerificationAdapter,
    MissionCompletionGate,
    MissionCompletionDecision,
    VerificationGate,
    VerificationStatus,
)
from intent_kernel.runtime import (
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionRuntime,
    MissionRuntimeState,
    RuntimeNodeState,
)


# ---------------------------------------------------------------------------
# Tests 1–17: expected_output=None → VERIFIED_FAILURE for all result types
# ---------------------------------------------------------------------------
class _ConstitutionAllow:
    """Mock constitution that always allows — for testing non-constitution gate steps."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


class TestVerificationWithoutExpectedOutput(IsolatedAsyncioTestCase):
    """Without an explicit verification contract, all results must fail verification."""

    def setUp(self):
        self.adapter = InMemoryActionVerificationAdapter()
        self.action = ActionContract(capability="test.echo")

    async def test_01_none_result(self):
        """1. verification_required=True + expected_output=None + None → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, None)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_02_exception_result(self):
        """2. same + Exception → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, Exception("error"))
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_03_status_success_dict(self):
        """3. same + {"status": "SUCCESS"} → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"status": "SUCCESS"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_04_status_failed_dict(self):
        """4. same + {"status": "FAILED"} → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"status": "FAILED"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_05_status_error_dict(self):
        """5. same + {"status": "ERROR"} → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"status": "ERROR"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_06_status_denied_dict(self):
        """6. same + {"status": "DENIED"} → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"status": "DENIED"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_07_status_simulated_success_dict(self):
        """7. same + {"status": "SIMULATED_SUCCESS"} → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"status": "SIMULATED_SUCCESS"})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_08_arbitrary_dict(self):
        """8. same + arbitrary dict → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {"key": "value", "nested": {"a": 1}})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_09_empty_dict(self):
        """9. same + empty dict → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, {})
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_10_boolean_true(self):
        """10. same + True → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, True)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_11_boolean_false(self):
        """11. same + False → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, False)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_12_integer_one(self):
        """12. same + 1 → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, 1)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_13_integer_zero(self):
        """13. same + 0 → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, 0)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_14_non_empty_string(self):
        """14. same + non-empty string → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, "hello world")
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_15_empty_string(self):
        """15. same + empty string → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, "")
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_16_non_empty_list(self):
        """16. same + non-empty list → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, [1, 2, 3])
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)

    async def test_17_empty_list(self):
        """17. same + empty list → VERIFIED_FAILURE"""
        status = await self.adapter.verify(self.action, [])
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


# ---------------------------------------------------------------------------
# Tests 18–19: expected_output present preserves existing semantics
# ---------------------------------------------------------------------------
class TestVerificationWithExpectedOutput(IsolatedAsyncioTestCase):
    """With an explicit verification contract, exact equality is required."""

    async def test_18_matching_result(self):
        """18. expected_output present + matching result → VERIFIED_SUCCESS"""
        adapter = InMemoryActionVerificationAdapter()
        action = ActionContract(capability="test.echo", expected_output="hello")
        status = await adapter.verify(action, "hello")
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    async def test_19_non_matching_result(self):
        """19. expected_output present + non-matching result → VERIFIED_FAILURE"""
        adapter = InMemoryActionVerificationAdapter()
        action = ActionContract(capability="test.echo", expected_output="hello")
        status = await adapter.verify(action, "world")
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


# ---------------------------------------------------------------------------
# Tests 20–21: Mission runtime integration
# ---------------------------------------------------------------------------
class TestVerificationMissionIntegration(IsolatedAsyncioTestCase):
    """Verification repair must propagate through MissionRuntime and MissionCompletionGate."""

    def setUp(self):
        self.executor = InMemoryActionExecutor()
        self.runtime = MissionRuntime(executor=self.executor, constitution=_ConstitutionAllow())

    async def test_20_no_expected_output_cannot_become_verified_success(self):
        """20. A node requiring verification with expected_output=None cannot
        achieve VERIFIED_SUCCESS solely because execution returned a value."""
        node = RuntimeNode(
            node_id="n1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": "result"},
            ),
        )
        inst = self.runtime.create_instance("m_v21", "g_v21", [node])
        res = await self.runtime.run_mission(inst.runtime_id)

        # Node should have failed verification
        self.assertEqual(node.verification_result, VerificationStatus.VERIFIED_FAILURE)
        self.assertEqual(node.state, RuntimeNodeState.FAILED)
        self.assertEqual(res.status, MissionRuntimeState.FAILED)

    async def test_21_mission_completion_cannot_rely_on_false_positive(self):
        """21. MissionCompletionGate must not allow completion from false-positive verification.
        A mission with a verification-required node (no expected_output) must not complete."""
        n1 = RuntimeNode(
            node_id="n1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": "output"},
            ),
        )
        n2 = RuntimeNode(
            node_id="n2",
            capability="test.echo",
            dependencies=["n1"],
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": "output"},
            ),
        )
        inst = self.runtime.create_instance("m_v21_2", "g_v21_2", [n1, n2])
        res = await self.runtime.run_mission(inst.runtime_id)

        # Both nodes fail verification → mission fails
        self.assertEqual(n1.verification_result, VerificationStatus.VERIFIED_FAILURE)
        # n2 never executes because n1 fails first (blocked dependency)
        self.assertIsNone(n2.verification_result)
        self.assertEqual(res.status, MissionRuntimeState.FAILED)
        self.assertNotIn("n1", res.completed_nodes)
        self.assertNotIn("n2", res.completed_nodes)

    async def test_21b_mission_completes_with_explicit_expected_output(self):
        """21b. Mission COMPLETES when all nodes have explicit expected_output that matches."""
        n1 = RuntimeNode(
            node_id="n1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": "hello"},
                expected_output="hello",
            ),
        )
        inst = self.runtime.create_instance("m_v21_3", "g_v21_3", [n1])
        res = await self.runtime.run_mission(inst.runtime_id)

        self.assertEqual(n1.verification_result, VerificationStatus.VERIFIED_SUCCESS)
        self.assertEqual(res.status, MissionRuntimeState.COMPLETED)


# ---------------------------------------------------------------------------
# Test 22: verification_required=False preservation
# ---------------------------------------------------------------------------
class TestVerificationRequiredFalse(IsolatedAsyncioTestCase):
    """verification_required=False must continue to bypass verification."""

    def setUp(self):
        self.runtime = MissionRuntime(executor=InMemoryActionExecutor(), constitution=_ConstitutionAllow())

    async def test_22_verification_required_false_preserved(self):
        """22. verification_required=False behavior remains unchanged."""
        node = RuntimeNode(
            node_id="n1",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                inputs_reference={"message": "result"},
                verification_required=False,
            ),
        )
        inst = self.runtime.create_instance("m_v21_4", "g_v21_4", [node])
        res = await self.runtime.run_mission(inst.runtime_id)

        # Node should be verified (bypassed → auto VERIFIED_SUCCESS)
        self.assertEqual(node.verification_result, VerificationStatus.VERIFIED_SUCCESS)
        self.assertEqual(res.status, MissionRuntimeState.COMPLETED)


# ---------------------------------------------------------------------------
# Test 23: Cross-movement regression (M11–M20)
# ---------------------------------------------------------------------------
class TestMovement21Regression(unittest.IsolatedAsyncioTestCase):
    """Ensure Phase 21.2 repair does not break closed Movements."""

    async def test_23_expected_output_match_preserves_success(self):
        """23. M11/M12 contract path: expected_output matching still works."""
        adapter = InMemoryActionVerificationAdapter()
        action = ActionContract(
            capability="test.calculate",
            inputs_reference={"a": 2, "b": 3, "op": "add"},
            expected_output=5,
        )
        status = await adapter.verify(action, 5)
        self.assertEqual(status, VerificationStatus.VERIFIED_SUCCESS)

    async def test_23b_expected_output_mismatch_preserves_failure(self):
        """23b. M11/M12 contract path: expected_output mismatch still fails."""
        adapter = InMemoryActionVerificationAdapter()
        action = ActionContract(
            capability="test.calculate",
            inputs_reference={"a": 2, "b": 3, "op": "add"},
            expected_output=5,
        )
        status = await adapter.verify(action, 6)
        self.assertEqual(status, VerificationStatus.VERIFIED_FAILURE)


if __name__ == "__main__":
    unittest.main()
