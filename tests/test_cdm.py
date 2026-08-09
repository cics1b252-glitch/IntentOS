"""Unit tests for Cognitive Dialogue Manager (CDM) — RFC-0008."""

import unittest
from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent
from intent_kernel.cdm import (
    CognitiveDialogueManager,
    DialogueState,
    DialogueDecision,
    CandidateQuestion,
)


class TestCognitiveDialogueManager(unittest.TestCase):

    def setUp(self):
        self.iue = IntentUnderstandingEngine()
        self.cdm = CognitiveDialogueManager()

    def test_mandatory_case_1_finance_no_context(self):
        """Case 1: 'Quero investir 23.500.' with no prior context.
        Should choose the single question that yields the highest IQI Gain (Goal + Horizon).
        """
        intent = self.iue.analyze("Quero investir 23.500")
        decision = self.cdm.evaluate(intent)

        self.assertEqual(decision.state, DialogueState.NEEDS_CONTEXT)
        self.assertFalse(decision.can_proceed)
        self.assertTrue(decision.requires_question)
        self.assertIsNotNone(decision.selected_question)

        # Single question selected
        q = decision.selected_question
        self.assertEqual(q.target_field, "financial_goal")
        self.assertIn("23.500", q.question)
        self.assertGreaterEqual(q.expected_iqi_gain, 0.30)

        # Candidate ranking and internal justification check
        self.assertGreater(len(decision.candidate_questions), 1)
        self.assertEqual(decision.candidate_questions[0].question_id, q.question_id)
        self.assertIn("selection_reasoning", decision.justification)
        self.assertIn("discarded_candidates_reasons", decision.justification)

    def test_mandatory_case_2_finance_with_context(self):
        """Case 2: 'Quero investir 23.500.' with financial context already in profile.
        Question must disappear and state change to READY_TO_EXECUTE.
        """
        session_context = {
            "user_profile": {
                "financial_goal": "Reserva de emergência",
                "risk_tolerance": "Conservador",
                "liquidity_preference": "Diária / Imediata",
                "strategy": "CDB 100% CDI"
            }
        }
        intent = self.iue.analyze("Quero investir 23.500", session_context=session_context)
        decision = self.cdm.evaluate(intent, session_context=session_context)

        self.assertEqual(decision.state, DialogueState.READY_TO_EXECUTE)
        self.assertTrue(decision.can_proceed)
        self.assertFalse(decision.requires_question)
        self.assertIsNone(decision.selected_question)
        self.assertGreaterEqual(decision.initial_iqi, 0.85)

    def test_mandatory_case_3_high_uncertainty_app(self):
        """Case 3: 'Monte um aplicativo.' (extreme uncertainty).
        Must identify high ambiguity/multiple paths and select single question that reduces uncertainty most.
        """
        intent = self.iue.analyze("Monte um aplicativo.")
        decision = self.cdm.evaluate(intent)

        self.assertIn(decision.state, [DialogueState.INSUFFICIENT_INFORMATION, DialogueState.MULTIPLE_VALID_PATHS])
        self.assertFalse(decision.can_proceed)
        self.assertTrue(decision.requires_question)
        self.assertIsNotNone(decision.selected_question)

        q = decision.selected_question
        self.assertEqual(q.target_field, "app_architecture_and_purpose")
        self.assertGreaterEqual(q.expected_iqi_gain, 0.40)

    def test_high_iqi_complete_intent_no_question(self):
        """High IQI intent with complete facts should proceed immediately with no question."""
        intent = self.iue.analyze(
            "Quero investir 10.000 reais em CDB pós-fixado para minha reserva de emergência com liquidez diária e perfil conservador."
        )
        decision = self.cdm.evaluate(intent)

        self.assertEqual(decision.state, DialogueState.READY_TO_EXECUTE)
        self.assertTrue(decision.can_proceed)
        self.assertFalse(decision.requires_question)
        self.assertIsNone(decision.selected_question)

    def test_multiple_candidate_ranking(self):
        """CDM must evaluate multiple candidate questions and rank by net value."""
        intent = self.iue.analyze("Quero investir dinheiros")
        decision = self.cdm.evaluate(intent)

        self.assertGreater(len(decision.candidate_questions), 1)
        # Check descending order of net_value
        net_values = [q.calculate_net_value() for q in decision.candidate_questions]
        self.assertEqual(net_values, sorted(net_values, reverse=True))

    def test_learning_log_feedback_recording(self):
        """Record question feedback and verify CLE learning log entry."""
        record = self.cdm.record_feedback(
            question_id="q_fin_goal_123",
            question_text="Qual seu objetivo principal?",
            target_field="goal",
            user_response="Reserva de emergência",
            initial_iqi=0.60,
            actual_iqi_after=0.92,
            expected_iqi_gain=0.30,
        )

        self.assertEqual(record.actual_iqi_gain, 0.32)
        self.assertTrue(record.was_helpful)
        self.assertEqual(len(self.cdm.learning_log), 1)
        self.assertEqual(self.cdm.learning_log[0].question_id, "q_fin_goal_123")


    def test_single_variable_per_question_rule(self):
        """CDM questions must focus on a single variable per question (e.g. goal, horizon, risk, or liquidity)."""
        intent = self.iue.analyze("Quero investir 23.500")
        decision = self.cdm.evaluate(intent)

        q = decision.selected_question
        self.assertIsNotNone(q)
        # Ensure question targets single field, not compound fields
        self.assertIn(q.target_field, ["financial_goal", "horizon", "liquidity_preference", "risk_tolerance"])
        # Ensure question does not ask both goal AND horizon in the same string
        self.assertFalse("objetivo principal" in q.question and "em quanto tempo" in q.question)

    def test_no_rigid_tech_defaults_without_context(self):
        """CDM questions must not hardcode rigid framework names like 'React' unless present in context."""
        intent = self.iue.analyze("Monte um aplicativo para meu consultório.")
        decision = self.cdm.evaluate(intent)

        q = decision.selected_question
        self.assertIsNotNone(q)
        self.assertNotIn("React", q.question)
        self.assertNotIn("Tailwind", q.question)


if __name__ == "__main__":
    unittest.main()
