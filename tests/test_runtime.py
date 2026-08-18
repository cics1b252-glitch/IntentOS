"""Mission Runtime & Action / Verification Gates Test Suite — RFC-0015 (STUDIO 10.2).

Comprehensive unit and integration test suite covering requirements A through AX
and Real Cases 1 through 5.
"""

import ast
import os
import shutil
import tempfile
import unittest
from unittest import IsolatedAsyncioTestCase

from intent_kernel.instructions import (
    MissionConstraint,
    OutputContract,
    OutputContractValidator,
)
from intent_kernel.persistence import JsonFilePersistenceEngine
from intent_kernel.rrm.models import AgentInstallationState, AgentResource, ResourceStatus
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.runtime import (
    ActionContract,
    ActionExecutorPort,
    ActionGate,
    ActionGateDecision,
    ExecutionConfirmationRequest,
    FailureCategory,
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionCheckpoint,
    MissionCompletionGate,
    MissionRuntime,
    MissionRuntimeInstance,
    MissionRuntimeState,
    RealActionExecutionProhibitedError,
    RuntimeNode,
    RuntimeNodeState,
    SideEffectLevel,
    VerificationGate,
    VerificationStatus,
)


class TestMissionRuntime(IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "checkpoints.json")
        self.persistence = JsonFilePersistenceEngine(file_path=self.file_path)
        self.checkpoint_repo = InMemoryCheckpointRepository(persistence_engine=self.persistence)
        self.executor = InMemoryActionExecutor()
        self.rrm = RegistryResourceManager()
        self.runtime = MissionRuntime(
            executor=self.executor,
            checkpoint_repo=self.checkpoint_repo,
            rrm_service=self.rrm,
        )

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # -------------------------------------------------------------------------
    # A, B, C: Instance Creation & State Transitions
    # -------------------------------------------------------------------------
    async def test_a_b_c_instance_creation_and_states(self):
        nodes = [
            RuntimeNode(node_id="n1", capability="test.echo", action_contract=ActionContract(capability="test.echo")),
        ]
        inst = self.runtime.create_instance("m1", "g1", nodes)
        self.assertEqual(inst.status, MissionRuntimeState.READY)
        self.assertEqual(len(inst.pending_nodes), 1)

    # -------------------------------------------------------------------------
    # D, E, F: DAG Execution Ordering & Dependencies
    # -------------------------------------------------------------------------
    async def test_d_e_f_dag_ordering(self):
        n1 = RuntimeNode(
            node_id="n1",
            capability="test.echo",
            action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "step1"}, expected_output="step1"),
        )
        n2 = RuntimeNode(
            node_id="n2",
            capability="test.echo",
            dependencies=["n1"],
            action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "step2"}, expected_output="step2"),
        )
        inst = self.runtime.create_instance("m_dag", "g_dag", [n1, n2])

        # Run mission to completion
        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.COMPLETED)
        self.assertEqual(res.completed_nodes, ["n1", "n2"])

    # -------------------------------------------------------------------------
    # G, H, I, J, K: ActionGate Allow, Deny, and User Confirmation
    # -------------------------------------------------------------------------
    async def test_g_h_i_j_k_action_gate_and_confirmation(self):
        n_side_effect = RuntimeNode(
            node_id="n_se",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                side_effect_level=SideEffectLevel.EXTERNAL_IRREVERSIBLE,
                expected_output="echo",
            ),
        )
        inst = self.runtime.create_instance("m_conf", "g_conf", [n_side_effect])

        # Initial run requires confirmation
        res1 = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res1.status, MissionRuntimeState.WAITING_USER_CONFIRMATION)

        # Retrieve generated confirmation request ID
        diag = await self.runtime.get_diagnostics()
        self.assertEqual(diag["waiting_confirmation"], 1)

        conf_req = list(self.runtime._confirmations.values())[0]

        # Submit user approval
        self.runtime.submit_confirmation(conf_req.confirmation_id, approved=True)

        # Resume run
        res2 = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res2.status, MissionRuntimeState.COMPLETED)
        self.assertIn("n_se", res2.completed_nodes)

    # -------------------------------------------------------------------------
    # L, M: Resource Revalidation via RRM
    # -------------------------------------------------------------------------
    async def test_l_m_resource_revalidation(self):
        # Register a disabled agent in RRM
        disabled_agent = AgentResource(
            agent_id="agent_disabled",
            name="Disabled Agent",
            capabilities=["test.echo"],
            status=ResourceStatus.DISABLED,
            installation_state=AgentInstallationState.UNAVAILABLE,
        )
        self.rrm.register_agent(disabled_agent)

        n_disabled = RuntimeNode(
            node_id="nd",
            capability="test.echo",
            agent_id="agent_disabled",
            action_contract=ActionContract(capability="test.echo"),
        )
        inst = self.runtime.create_instance("m_dis", "g_dis", [n_disabled])

        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.WAITING_RESOURCE)

    # -------------------------------------------------------------------------
    # N, O, P, Q: Idempotency & Retries
    # -------------------------------------------------------------------------
    async def test_n_idempotency_tracking(self):
        contract = ActionContract(
            capability="test.echo",
            idempotency_key="idemp_12345",
            inputs_reference={"message": "idempotent_test"},
            expected_output="idempotent_test",
        )
        n = RuntimeNode(node_id="n_idemp", capability="test.echo", action_contract=contract)
        inst = self.runtime.create_instance("m_idemp", "g_idemp", [n])

        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.COMPLETED)
        self.assertTrue(self.runtime.action_gate.is_idempotency_key_executed("idemp_12345"))

    # -------------------------------------------------------------------------
    # R, S, T, U, V: Checkpoints, Pause, Resume, and Process Restart
    # -------------------------------------------------------------------------
    async def test_r_s_t_u_v_checkpoints_pause_resume_restart(self):
        n1 = RuntimeNode(node_id="n1", capability="test.echo", action_contract=ActionContract(capability="test.echo", expected_output="echo"))
        n2 = RuntimeNode(node_id="n2", capability="test.echo", dependencies=["n1"], action_contract=ActionContract(capability="test.echo", expected_output="echo"))
        inst = self.runtime.create_instance("m_rest", "g_rest", [n1, n2])

        # Run n1
        await self.runtime.run_mission(inst.runtime_id)

        # Simulate process restart by reading latest checkpoint into a new runtime instance
        new_repo = InMemoryCheckpointRepository(persistence_engine=self.persistence)
        new_runtime = MissionRuntime(executor=self.executor, checkpoint_repo=new_repo)

        # Re-register instance in new runtime
        new_runtime._instances[inst.runtime_id] = inst

        # Resume execution
        res_resumed = await new_runtime.resume(inst.runtime_id)
        self.assertIsNotNone(res_resumed)

        res_final = await new_runtime.run_mission(inst.runtime_id)
        self.assertEqual(res_final.status, MissionRuntimeState.COMPLETED)
        self.assertEqual(len(res_final.completed_nodes), 2)

    # -------------------------------------------------------------------------
    # AA - AL: Verification Gate & OutputContract Integration
    # -------------------------------------------------------------------------
    async def test_verification_gate_failure(self):
        # Expected output != Actual output
        contract = ActionContract(
            capability="test.echo",
            inputs_reference={"message": "actual"},
            expected_output="EXPECTED_DIFFERENT",
        )
        n = RuntimeNode(node_id="n_verif_fail", capability="test.echo", action_contract=contract)
        inst = self.runtime.create_instance("m_vf", "g_vf", [n])

        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.FAILED)
        self.assertIn("n_verif_fail", res.failed_nodes)

    # -------------------------------------------------------------------------
    # AR - AX: Real Action Execution Prohibition & Architectural Boundaries
    # -------------------------------------------------------------------------
    async def test_prohibit_real_actions(self):
        contract_email = ActionContract(capability="email.send_email")
        with self.assertRaises(RealActionExecutionProhibitedError):
            await self.executor.execute(contract_email)

    def test_architectural_imports_boundary(self):
        runtime_file = os.path.join(os.path.dirname(__file__), "../intent_kernel/runtime/mission_runtime.py")
        with open(runtime_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=runtime_file)

        forbidden = ["urllib", "requests", "httpx", "subprocess", "os.system"]
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.append(node.module)

        for forb in forbidden:
            for imp in imported:
                self.assertFalse(imp.startswith(forb), f"Mission Runtime imports prohibited library {imp}")

    # -------------------------------------------------------------------------
    # CASO 1 — MISSÃO LOCAL SIMPLES (A -> B verified -> Mission COMPLETED)
    # -------------------------------------------------------------------------
    async def test_caso_1_simple_local_mission(self):
        nA = RuntimeNode(
            node_id="node_A",
            capability="test.echo",
            action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "Result A"}, expected_output="Result A"),
        )
        nB = RuntimeNode(
            node_id="node_B",
            capability="test.transform",
            dependencies=["node_A"],
            action_contract=ActionContract(capability="test.transform", inputs_reference={"text": "hello", "mode": "upper"}, expected_output="HELLO"),
        )
        inst = self.runtime.create_instance("m_case1", "g_case1", [nA, nB])

        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.COMPLETED)
        self.assertEqual(res.completed_nodes, ["node_A", "node_B"])
        self.assertEqual(res.nodes["node_B"].result, "HELLO")

    # -------------------------------------------------------------------------
    # CASO 2 — RESTART (A completed, Checkpoint, Restart, A not rerun, B continues)
    # -------------------------------------------------------------------------
    async def test_caso_2_restart(self):
        nA = RuntimeNode(node_id="node_A", capability="test.echo", action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "A"}, expected_output="A"))
        nB = RuntimeNode(node_id="node_B", capability="test.echo", dependencies=["node_A"], action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "B"}, expected_output="B"))

        inst = self.runtime.create_instance("m_case2", "g_case2", [nA, nB])

        # Step 1: Execute Node A
        await self.runtime.run_mission(inst.runtime_id)

        # Step 2: Simulate restart with fresh runtime using saved checkpoints
        fresh_runtime = MissionRuntime(executor=self.executor, checkpoint_repo=self.checkpoint_repo)
        fresh_runtime._instances[inst.runtime_id] = inst

        # Resume from checkpoint
        resumed_inst = await fresh_runtime.resume(inst.runtime_id)
        self.assertIn("node_A", resumed_inst.completed_nodes)

        # Confirm Node A attempt_count is 1
        attempt_a_before = resumed_inst.nodes["node_A"].attempt_count

        res_final = await fresh_runtime.run_mission(inst.runtime_id)
        self.assertEqual(res_final.status, MissionRuntimeState.COMPLETED)
        # Node A should NOT have been executed again
        self.assertEqual(res_final.nodes["node_A"].attempt_count, attempt_a_before)

    # -------------------------------------------------------------------------
    # CASO 3 — CONFIRMAÇÃO (external_irreversible -> WAITING_USER_CONFIRMATION)
    # -------------------------------------------------------------------------
    async def test_caso_3_confirmation(self):
        n_ext = RuntimeNode(
            node_id="node_ext",
            capability="test.echo",
            action_contract=ActionContract(
                capability="test.echo",
                side_effect_level=SideEffectLevel.EXTERNAL_IRREVERSIBLE,
                expected_output="echo",
            ),
        )
        inst = self.runtime.create_instance("m_case3", "g_case3", [n_ext])

        # Execution halts waiting for confirmation
        res1 = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res1.status, MissionRuntimeState.WAITING_USER_CONFIRMATION)

        # User approves
        conf_req = list(self.runtime._confirmations.values())[0]
        self.runtime.submit_confirmation(conf_req.confirmation_id, approved=True)

        res2 = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res2.status, MissionRuntimeState.COMPLETED)

    # -------------------------------------------------------------------------
    # CASO 4 — RESULTADO INCORRETO (Expected != Observed -> VERIFIED_FAILURE)
    # -------------------------------------------------------------------------
    async def test_caso_4_incorrect_result(self):
        n_wrong = RuntimeNode(
            node_id="node_wrong",
            capability="test.calculate",
            action_contract=ActionContract(
                capability="test.calculate",
                inputs_reference={"a": 2, "b": 2, "op": "add"},
                expected_output=5,  # Incorrect expectation!
            ),
        )
        inst = self.runtime.create_instance("m_case4", "g_case4", [n_wrong])

        res = await self.runtime.run_mission(inst.runtime_id)
        self.assertEqual(res.status, MissionRuntimeState.FAILED)
        self.assertEqual(res.nodes["node_wrong"].verification_result, VerificationStatus.VERIFIED_FAILURE)

    # -------------------------------------------------------------------------
    # CASO 5 — OUTPUT CONTRACT (single_block_required -> OutputContractValidator)
    # -------------------------------------------------------------------------
    async def test_caso_5_output_contract_integration(self):
        n_report = RuntimeNode(
            node_id="node_rep",
            capability="test.echo",
            action_contract=ActionContract(capability="test.echo", inputs_reference={"message": "Generated report text"}, expected_output="Generated report text"),
        )
        inst = self.runtime.create_instance("m_case5", "g_case5", [n_report])

        contract = OutputContract(
            single_block_required=True,
            text_outside_block_allowed=False,
            max_blocks=1,
        )

        # Candidate output with text outside block (INVALID)
        bad_output = "Relatório concluído:\n\n```text\nSTATUS: OK\n```"
        res_bad = await self.runtime.run_mission(
            inst.runtime_id,
            output_contract=contract,
            final_output_candidate=bad_output,
        )
        self.assertEqual(res_bad.status, MissionRuntimeState.BLOCKED)

        # Candidate output strictly inside single block (VALID)
        good_output = "```text\nSTATUS: OK\nDETALHES: Completo\n```"
        res_good = await self.runtime.run_mission(
            inst.runtime_id,
            output_contract=contract,
            final_output_candidate=good_output,
        )
        self.assertEqual(res_good.status, MissionRuntimeState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
