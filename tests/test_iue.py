"""Unit tests for Intent Understanding Engine (IUE) — RFC-0007."""

import unittest
from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent, IntentQualityIndex


class TestIntentUnderstandingEngine(unittest.TestCase):

    def setUp(self):
        self.engine = IntentUnderstandingEngine()

    def test_empty_input(self):
        si = self.engine.analyze("")
        self.assertEqual(si.domain, "general")
        self.assertTrue(si.requires_confirmation)
        self.assertEqual(si.confidence, 0.0)
        self.assertIn("digite", si.clarifying_question.lower())

    def test_incomplete_financial_intent(self):
        """RFC-0007 Example: 'Quero investir 23.500'."""
        si = self.engine.analyze("Quero investir 23.500")
        
        self.assertEqual(si.domain, "finance")
        self.assertTrue(si.requires_confirmation)
        self.assertTrue(si.mission_candidate)
        
        # Check known vs missing context
        known_str = " ".join(si.known_context)
        missing_str = " ".join(si.missing_context)
        self.assertIn("23.500", known_str)
        self.assertIn("Objetivo principal", missing_str)
        self.assertIn("Perfil de risco", missing_str)
        self.assertIn("Prazo", missing_str)
        
        # Check IQI
        iqi = si.intent_quality_index
        self.assertLess(iqi["overall_score"], 0.75)
        self.assertGreater(iqi["clarity"], 0.5)
        self.assertLess(iqi["completeness"], 0.5)
        
        # Check surgical clarifying question
        self.assertIsNotNone(si.clarifying_question)
        self.assertIn("23.500", si.clarifying_question)
        self.assertIn("objetivo", si.clarifying_question.lower())

    def test_complete_financial_intent(self):
        text = (
            "Quero investir R$ 23.500 em CDB de liquidez diária "
            "para minha reserva de emergência com perfil conservador"
        )
        si = self.engine.analyze(text)
        
        self.assertEqual(si.domain, "finance")
        self.assertEqual(len(si.missing_context), 0)
        self.assertFalse(si.requires_confirmation)
        
        iqi = si.intent_quality_index
        self.assertGreaterEqual(iqi["overall_score"], 0.75)

    def test_context_reuse_from_user_profile(self):
        """RFC-0007 Item 3 Test: Reuse prior context from user profile/session context."""
        session_context = {
            "user_profile": {
                "financial_goal": "Reserva de emergência",
                "risk_tolerance": "Conservador",
                "liquidity_preference": "Alta / Liquidez diária",
                "strategy": "CDB Pós-Fixado 100% CDI"
            }
        }
        si = self.engine.analyze("Quero investir 23.500", session_context=session_context)
        
        self.assertEqual(si.domain, "finance")
        self.assertEqual(len(si.missing_context), 0)
        self.assertFalse(si.requires_confirmation)
        self.assertIsNone(si.clarifying_question)
        self.assertGreater(len(si.known_context_provenance), 3)
        self.assertEqual(si.known_context_provenance[1]["origin"], "user_profile")


    def test_system_domain_intent(self):
        si = self.engine.analyze("Verificar status e guardians da constituição do kernel")
        self.assertEqual(si.domain, "system")
        self.assertIn("core.system_diagnostics", si.recommended_capabilities)

    def test_coding_domain_intent(self):
        si = self.engine.analyze("Escrever um script python para refatorar o parser de arquivos")
        self.assertEqual(si.domain, "coding")
        self.assertIn("core.code_generation", si.recommended_capabilities)


if __name__ == "__main__":
    unittest.main()
