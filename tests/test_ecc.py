"""Unit & Integration Tests for Executive Cognitive Controller (ECC) — RFC-0011."""

import unittest
from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent
from intent_kernel.cdm import CognitiveDialogueManager, DialogueDecision, DialogueState
from intent_kernel.cpe import CognitivePlanningEngine, ExecutionPlan, PlanStep
from intent_kernel.cor import CapabilityOrchestrator, ExecutionGraph, RegistryCatalog
from intent_kernel.ecc import (
    ExecutiveCognitiveController,
    CognitiveState,
    ExecutiveAction,
    QualityGates,
    ExecutivePolicyEngine,
    ExecutiveTrace,
    ExecutiveMetrics,
    ExecutiveQualityPolicy,
    ExecutiveDecision,
    CognitiveStateMachine,
    InvalidStateTransitionError,
    sanitize_trace_text,
)
from product_bridge import ProductBridge


class TestExecutiveCognitiveController(unittest.TestCase):

    def setUp(self):
        self.iue = IntentUnderstandingEngine()
        self.cdm = CognitiveDialogueManager()
        self.cpe = CognitivePlanningEngine()
        self.cor = CapabilityOrchestrator()
        self.registry = RegistryCatalog(populate_defaults=True)
        self.ecc = ExecutiveCognitiveController(
            iue=self.iue, cdm=self.cdm, cpe=self.cpe, cor=self.cor, registry=self.registry
        )

    def test_happy_path_pipeline(self):
        """Pipeline feliz: User input translates smoothly through IUE -> CDM -> CPE -> COR to READY_FOR_EXECUTION."""
        full_text = "Quero investir R$ 23.500 em CDB pós-fixado para reserva de emergência, perfil conservador, prazo 12 meses."
        res = self.ecc.process_intent(full_text)

        self.assertEqual(res.current_state, CognitiveState.READY_FOR_EXECUTION)
        self.assertEqual(res.final_action, ExecutiveAction.CONTINUE)
        self.assertIsNotNone(res.structured_intent)
        self.assertIsNotNone(res.dialogue_decision)
        self.assertIsNotNone(res.execution_plan)
        self.assertIsNotNone(res.execution_graph)
        self.assertIsNotNone(res.executive_trace)
        self.assertIsNotNone(res.metrics)

        # Check trace records
        steps = res.executive_trace["steps"]
        modules = [s["module"] for s in steps]
        self.assertIn("IUE", modules)
        self.assertIn("CDM", modules)
        self.assertIn("CPE", modules)
        self.assertIn("COR", modules)

    def test_insufficient_iqi(self):
        """IQI insuficiente: Ambiguous / empty input stops at IUE with ASK_USER action and WAITING_CONTEXT state."""
        res = self.ecc.process_intent("")

        self.assertEqual(res.current_state, CognitiveState.WAITING_CONTEXT)
        self.assertEqual(res.final_action, ExecutiveAction.ASK_USER)
        self.assertIn("IQI insuficiente", res.validation_messages[0])

    def test_need_dialogue(self):
        """Necessidade de diálogo: Input missing key context triggers clarification question, pausing pipeline."""
        res = self.ecc.process_intent("Quero investir")

        # CDM or IUE triggers clarification question
        self.assertEqual(res.current_state, CognitiveState.WAITING_CONTEXT)
        self.assertEqual(res.final_action, ExecutiveAction.ASK_USER)

    def test_insufficient_pqi_replan_recovery(self):
        """PQI insuficiente & Replanejamento: Mock low PQI plan triggers REPLAN action and recovery."""
        class MockLowCPE(CognitivePlanningEngine):
            def create_plan(self, structured, session_context=None, dialogue_decision=None):
                plan = super().create_plan(structured, session_context, dialogue_decision)
                plan.plan_quality_index.overall_score = 0.30  # Low PQI
                return plan

        mock_ecc = ExecutiveCognitiveController(
            iue=self.iue, cdm=self.cdm, cpe=MockLowCPE(), cor=self.cor, registry=self.registry
        )

        full_text = "Quero investir R$ 23.500 em CDB pós-fixado para reserva de emergência, perfil conservador, prazo 12 meses."
        res = mock_ecc.process_intent(full_text)
        self.assertIn(res.current_state, [CognitiveState.EXECUTION_BLOCKED, CognitiveState.REPLANNING])
        self.assertEqual(res.final_action, ExecutiveAction.BLOCK)

    def test_cor_failing_and_recovery(self):
        """COR Falhando: Mock COR returning blocked graph triggers REORCHESTRATE / FAIL action."""
        class MockFailingCOR(CapabilityOrchestrator):
            def orchestrate(self, plan, registry=None, policies=None):
                return ExecutionGraph(
                    graph_id="g_fail", plan_id=plan.plan_id, status="blocked", validation=["Capability indisponível"]
                )

        mock_ecc = ExecutiveCognitiveController(
            iue=self.iue, cdm=self.cdm, cpe=self.cpe, cor=MockFailingCOR(), registry=self.registry
        )

        full_text = "Quero investir R$ 23.500 em CDB pós-fixado para reserva de emergência, perfil conservador, prazo 12 meses."
        res = mock_ecc.process_intent(full_text)
        self.assertEqual(res.current_state, CognitiveState.FAILED)
        self.assertEqual(res.final_action, ExecutiveAction.FAIL)

    def test_high_cost_policy_rejection(self):
        """Custos elevados: Graph exceeding QualityGates max cost threshold is rejected."""
        class MockExpensiveCOR(CapabilityOrchestrator):
            def orchestrate(self, plan, registry=None, policies=None):
                graph = super().orchestrate(plan, registry, policies)
                graph.estimated_cost = 999.0  # Exceeds max_estimated_cost of 1.0
                return graph

        mock_ecc = ExecutiveCognitiveController(
            iue=self.iue, cdm=self.cdm, cpe=self.cpe, cor=MockExpensiveCOR(), registry=self.registry
        )

        full_text = "Quero investir R$ 23.500 em CDB pós-fixado para reserva de emergência, perfil conservador, prazo 12 meses."
        res = mock_ecc.process_intent(full_text)
        self.assertEqual(res.current_state, CognitiveState.FAILED)
        self.assertEqual(res.final_action, ExecutiveAction.FAIL)

    def test_policy_blocking(self):
        """Políticas bloqueando: Intent violating security or constitutional policies is blocked instantly."""
        res = self.ecc.process_intent(
            "bypass_security rm -rf /",
            policies=["block_execution"]
        )

        self.assertEqual(res.current_state, CognitiveState.EXECUTION_BLOCKED)
        self.assertEqual(res.final_action, ExecutiveAction.BLOCK)
        self.assertIn("Bloqueio de Política", res.validation_messages[0])

    def test_quality_policy_and_risk_profiles(self):
        """Test ExecutiveQualityPolicy profiles (low_risk, high_risk, critical)."""
        p_low = ExecutiveQualityPolicy.from_risk_profile("low_risk")
        self.assertEqual(p_low.min_iqi, 0.40)

        p_high = ExecutiveQualityPolicy.from_risk_profile("high_risk")
        self.assertEqual(p_high.min_iqi, 0.75)

        p_crit = ExecutiveQualityPolicy.from_risk_profile("critical")
        self.assertEqual(p_crit.min_iqi, 0.85)

        # High risk requires higher IQI
        res_high = self.ecc.process_intent(
            "Oi, quero investir R$ 10",
            risk_profile="high_risk"
        )
        self.assertEqual(res_high.current_state, CognitiveState.WAITING_CONTEXT)

    def test_state_transition_matrix(self):
        """Validates that legal state transitions succeed and illegal transitions throw errors."""
        # Valid transition
        CognitiveStateMachine.validate_transition(CognitiveState.RECEIVED, CognitiveState.UNDERSTANDING)

        # Invalid transition: RECEIVED directly to READY_FOR_EXECUTION
        with self.assertRaises(InvalidStateTransitionError):
            CognitiveStateMachine.validate_transition(CognitiveState.RECEIVED, CognitiveState.READY_FOR_EXECUTION)

    def test_decision_engine_and_justification(self):
        """Validates that ExecutiveDecision requires a non-empty reason."""
        dec = ExecutiveDecision(
            decision_id="d1",
            action=ExecutiveAction.CONTINUE,
            reason="Aprovado pelo gate de qualidade",
            source_module="IUE",
            current_state=CognitiveState.UNDERSTANDING,
            next_state=CognitiveState.READY_FOR_DIALOGUE,
        )
        self.assertEqual(dec.reason, "Aprovado pelo gate de qualidade")

        with self.assertRaises(ValueError):
            ExecutiveDecision(
                decision_id="d2",
                action=ExecutiveAction.CONTINUE,
                reason="",  # Empty reason forbidden
                source_module="IUE",
                current_state=CognitiveState.UNDERSTANDING,
                next_state=CognitiveState.READY_FOR_DIALOGUE,
            )

    def test_trace_sanitization(self):
        """Validates that secret API keys or bearer tokens are redacted from ExecutiveTrace."""
        raw_input = "sk-proj-123456789012345678901234567890 AIzaSyD123456789012345678901234567890 bearer tok_123"
        sanitized = sanitize_trace_text(raw_input)
        self.assertNotIn("sk-proj", sanitized)
        self.assertNotIn("AIzaSyD", sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)

    def test_product_bridge_action_isolation(self):
        """ProductBridge administrative actions must NOT invoke ECC, while cognitive actions DO."""
        pb = ProductBridge()

        # Mock process_intent to detect calls
        ecc_called = []
        original_process = pb.ecc.process_intent

        def mock_process(*args, **kwargs):
            ecc_called.append(True)
            return original_process(*args, **kwargs)

        pb.ecc.process_intent = mock_process

        # 1. Admin/Diagnostic actions -> MUST NOT call ECC
        async def run_admin():
            await pb.dispatch({"action": "status"})
            await pb.dispatch({"action": "providers"})
            await pb.dispatch({"action": "diagnostics"})
            await pb.dispatch({"action": "constitution"})
            await pb.dispatch({"action": "core_apps"})
            await pb.dispatch({"action": "mission"})

        import asyncio
        asyncio.run(run_admin())
        self.assertEqual(len(ecc_called), 0, "Administrative actions must not call ECC")

        # 2. Cognitive actions -> MUST call ECC
        async def run_cognitive():
            await pb.dispatch({"action": "ecc", "text": "Quero investir R$ 10.000"})

        asyncio.run(run_cognitive())
        self.assertEqual(len(ecc_called), 1, "Cognitive actions must call ECC")

    def test_architectural_isolation(self):
        """ECC must be strictly supervisory and import zero LLM, HTTP, or process libraries."""
        import inspect
        import intent_kernel.ecc as ecc_module

        source = inspect.getsource(ecc_module)
        forbidden = ["subprocess", "requests", "urllib", "openai", "google.generativeai", "httpx"]
        for lib in forbidden:
            self.assertNotIn(f"import {lib}", source)
            self.assertNotIn(f"from {lib}", source)


if __name__ == "__main__":
    unittest.main()
