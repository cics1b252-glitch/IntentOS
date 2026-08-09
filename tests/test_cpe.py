"""Unit and Integration tests for Cognitive Planning Engine (CPE) — RFC-0009."""

import ast
import os
import unittest
from intent_kernel.cdm import CognitiveDialogueManager, DialogueDecision, DialogueState, CandidateQuestion
from intent_kernel.cpe import CognitivePlanningEngine, ExecutionPlan, PlanStep, PlanQualityIndex
from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent


class TestCognitivePlanningEngine(unittest.TestCase):

    def setUp(self):
        self.iue = IntentUnderstandingEngine()
        self.cdm = CognitiveDialogueManager()
        self.cpe = CognitivePlanningEngine()

    def test_case_a_finance_investment_plan(self):
        """Case A: 'Quero investir R$ 23.500.' with sufficient context."""
        session_context = {
            "user_profile": {
                "financial_goal": "Reserva de emergência",
                "risk_tolerance": "Conservador",
                "liquidity_preference": "Diária",
            }
        }
        intent = self.iue.analyze("Quero investir R$ 23.500.", session_context=session_context)
        decision = self.cdm.evaluate(intent, session_context=session_context)

        self.assertTrue(decision.can_proceed)
        self.assertEqual(decision.state, DialogueState.READY_TO_EXECUTE)

        plan = self.cpe.create_plan(intent, session_context=session_context, dialogue_decision=decision)

        self.assertEqual(plan.status, "ready")
        self.assertGreater(len(plan.steps), 0)
        self.assertTrue(plan.mission_candidate_id)
        self.assertGreaterEqual(plan.confidence, 0.60)
        self.assertGreaterEqual(plan.plan_quality_index.overall_score, 0.70)

        # Ensure no real money movement or execution occurred
        for step in plan.steps:
            self.assertEqual(step.status, "pending")
            self.assertIn(step.action_type, ["retrieve", "analyze", "calculate", "synthesize", "validate"])

    def test_case_b_software_application_plan(self):
        """Case B: 'Monte um aplicativo para controlar manutenção do meu carro.'"""
        session_context = {
            "conversation_context": "Usuário quer controlar manutenção do veículo com web app React/TS."
        }
        intent = self.iue.analyze("Monte um aplicativo para controlar manutenção do meu carro.", session_context=session_context)
        decision = self.cdm.evaluate(intent, session_context=session_context)

        plan = self.cpe.create_plan(intent, session_context=session_context, dialogue_decision=decision)

        self.assertIn(plan.status, ["ready", "blocked"])
        self.assertGreater(len(plan.steps), 0)
        self.assertIn("code.architecture_design", plan.required_capabilities)

        # Verify step dependencies
        arch_step = next(s for s in plan.steps if s.step_id == "step_design_architecture")
        scaffold_step = next(s for s in plan.steps if s.step_id == "step_generate_scaffold")
        self.assertIn(arch_step.step_id, scaffold_step.dependencies)

    def test_case_c_communication_confirmation_gate(self):
        """Case C: 'Envie um e-mail para João informando que aceito a proposta.'
        Must identify external action, irreversible effect, and set confirmation gate.
        """
        intent = self.iue.analyze("Envie um e-mail para João informando que aceito a proposta.")
        decision = self.cdm.evaluate(intent)

        # Force decision ready for plan evaluation
        decision.can_proceed = True
        decision.state = DialogueState.READY_TO_EXECUTE

        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        self.assertEqual(plan.status, "ready")
        self.assertGreater(len(plan.confirmation_points), 0)

        confirm_gate = plan.confirmation_points[0]
        self.assertIn("irreversible", confirm_gate.get("type", "").lower())

        # Check irreversible step
        send_step = next(s for s in plan.steps if s.step_id == "step_send_communication")
        self.assertTrue(send_step.requires_confirmation)
        self.assertEqual(send_step.reversibility, "irreversible")
        self.assertIn(send_step.risk_level, ["high", "critical"])

    def test_case_d_parallel_steps(self):
        """Case D: 'Pesquise três alternativas e compare.'
        Demonstrates parallel research steps dependent on by comparison step.
        """
        intent = self.iue.analyze("Pesquise três alternativas e compare.")
        decision = self.cdm.evaluate(intent)
        decision.can_proceed = True

        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        s1 = next(s for s in plan.steps if s.step_id == "step_research_alt_1")
        s2 = next(s for s in plan.steps if s.step_id == "step_research_alt_2")
        s3 = next(s for s in plan.steps if s.step_id == "step_research_alt_3")
        compare = next(s for s in plan.steps if s.step_id == "step_compare_alternatives")

        # s1, s2, s3 have empty dependencies -> Parallel
        self.assertEqual(s1.dependencies, [])
        self.assertEqual(s2.dependencies, [])
        self.assertEqual(s3.dependencies, [])

        # compare depends on s1, s2, s3
        self.assertIn(s1.step_id, compare.dependencies)
        self.assertIn(s2.step_id, compare.dependencies)
        self.assertIn(s3.step_id, compare.dependencies)

    def test_blocked_plan_when_cdm_not_ready(self):
        """CPE must return a blocked draft plan if CDM decision is NOT READY_TO_EXECUTE."""
        intent = self.iue.analyze("Quero investir 23.500")
        decision = self.cdm.evaluate(intent)  # Needs context

        self.assertFalse(decision.can_proceed)

        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        self.assertEqual(plan.status, "blocked")
        self.assertEqual(len(plan.steps), 0)
        self.assertGreater(len(plan.confirmation_points), 0)

    def test_circular_dependency_detection(self):
        """CPE detect_cycles must identify invalid cycles in step graphs."""
        s1 = PlanStep(step_id="step_a", objective="A", action_type="test", dependencies=["step_b"])
        s2 = PlanStep(step_id="step_b", objective="B", action_type="test", dependencies=["step_a"])

        has_cycle = self.cpe.detect_cycles([s1, s2])
        self.assertTrue(has_cycle)

        # Acyclic test
        s3 = PlanStep(step_id="step_c", objective="C", action_type="test", dependencies=[])
        s4 = PlanStep(step_id="step_d", objective="D", action_type="test", dependencies=["step_c"])
        self.assertFalse(self.cpe.detect_cycles([s3, s4]))

    def _make_ready_decision(self, intent_id: str) -> DialogueDecision:
        return DialogueDecision(
            decision_id="d1",
            intent_id=intent_id,
            state=DialogueState.READY_TO_EXECUTE,
            can_proceed=True,
            requires_question=False,
            selected_question=None,
            candidate_questions=[],
            justification={},
            initial_iqi=0.9,
            projected_iqi_after_question=0.9,
            net_value=0.0,
        )

    def test_replanning_on_step_failure(self):
        """replan adaptively modifies an existing plan when a step fails."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        replanned = self.cpe.replan(
            existing_plan=plan,
            failed_step_id="step_calculate_allocation",
            failure_reason="Serviço de cotações em tempo real fora do ar",
        )

        self.assertEqual(replanned.status, "replanned")
        recovery_step = next((s for s in replanned.steps if "recovery" in s.step_id), None)
        self.assertIsNotNone(recovery_step)
        self.assertIn("step_calculate_allocation", recovery_step.dependencies)

    def test_pqi_calculation(self):
        """PQI (Plan Quality Index) must evaluate goal alignment, completeness, feasibility, risk, and validation."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        pqi = self.cpe.calculate_pqi(plan)
        self.assertIsInstance(pqi, PlanQualityIndex)
        self.assertGreaterEqual(pqi.overall_score, 0.0)
        self.assertLessEqual(pqi.overall_score, 1.0)
        self.assertEqual(pqi.dependency_integrity, 1.0)

    def test_provenance_and_assumptions(self):
        """Every significant decision must include provenance and explicit assumptions."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        self.assertGreater(len(plan.provenance), 0)
        for prov in plan.provenance:
            self.assertIn("fact", prov)
            self.assertIn("origin", prov)
            self.assertIn("type", prov)

    def test_no_hardcoded_providers_or_concrete_agents(self):
        """CPE must describe abstract provider requirements and capability-first steps, not concrete model names."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        plan_dict = plan.to_dict()
        reqs = plan_dict.get("provider_requirements", {})

        self.assertIn("reasoning", reqs)
        self.assertNotIn("gpt-4", reqs)
        self.assertNotIn("gemini-1.5-pro", reqs)
        self.assertNotIn("claude-3-5-sonnet", reqs)

    def test_architectural_isolation(self):
        """CPE must NOT import or invoke Providers, external APIs, subprocess, or concrete agents directly."""
        cpe_file_path = os.path.join(os.path.dirname(__file__), "..", "intent_kernel", "cpe.py")
        with open(cpe_file_path, "r", encoding="utf-8") as f:
            code_text = f.read()

        tree = ast.parse(code_text)

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

        forbidden = ["subprocess", "requests", "httpx", "urllib", "openai", "google.generativeai", "anthropic"]
        for mod in imported_modules:
            for f in forbidden:
                self.assertNotIn(f, mod, f"Forbidden architectural import detected in CPE: {mod}")


if __name__ == "__main__":
    unittest.main()
