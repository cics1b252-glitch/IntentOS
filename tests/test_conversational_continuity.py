"""Test suite for RFC-0017.1 — Conversational Continuity & Mission Resume Fix."""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from product_bridge import ProductBridge


class TestConversationalContinuity(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        os.environ["INTENTOS_DATA_ROOT"] = self.tmp_dir
        self.bridge = ProductBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_two_turn_investment_continuity(self):
        """Test full 2-turn dialogue continuity for investment clarification."""
        session_id = "test-continuity-session-1"

        # Turn 1: "quero investir 24 mil"
        req1 = {
            "action": "chat",
            "message": "quero investir 24 mil",
            "session_id": session_id,
            "correlation_id": "corr-turn-1",
        }
        res1 = asyncio.run(self.bridge.dispatch(req1))

        self.assertTrue(res1.get("ok"))
        self.assertEqual(res1.get("status"), "waiting_context")
        self.assertEqual(res1.get("dialogue_state"), "WAITING_CONTEXT")
        mission_id = res1.get("mission_id")
        self.assertIsNotNone(mission_id)
        self.assertIn("investimento único ou para um aporte mensal", res1.get("text", ""))

        # Verify session file on disk
        saved_session = self.bridge._load_session(session_id)
        self.assertEqual(saved_session.get("mission_status"), "waiting_context")
        pending = saved_session.get("pending_dialogue")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.get("target_field"), "recurrence")
        self.assertEqual(pending.get("known_context", {}).get("amount"), 24000.0)

        # Turn 2: "com aportes mensais"
        req2 = {
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": session_id,
            "correlation_id": "corr-turn-2",
            "resume_mission_id": mission_id,
        }
        res2 = asyncio.run(self.bridge.dispatch(req2))

        self.assertTrue(res2.get("ok"))
        self.assertEqual(res2.get("status"), "concluído")
        self.assertEqual(res2.get("mission_id"), mission_id)  # Mission ID preserved!
        self.assertIn("Análise de Investimento", res2.get("text", ""))
        self.assertIn("24.000/mês", res2.get("text", ""))

        # Verify session file after turn 2 completion
        completed_session = self.bridge._load_session(session_id)
        self.assertEqual(completed_session.get("mission_status"), "completed")
        self.assertIsNone(completed_session.get("pending_dialogue"))

    def test_process_restart_continuity_resilience(self):
        """Test continuity resilience across bridge process restarts."""
        session_id = "test-restart-session"

        # Turn 1 on Bridge instance 1
        req1 = {
            "action": "chat",
            "message": "quero investir 24 mil",
            "session_id": session_id,
        }
        res1 = asyncio.run(self.bridge.dispatch(req1))
        mission_id = res1.get("mission_id")
        self.assertEqual(res1.get("status"), "waiting_context")

        # Simulate process restart by instantiating a brand new ProductBridge
        new_bridge = ProductBridge()

        # Turn 2 on new Bridge instance without explicit resume_mission_id parameter
        req2 = {
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": session_id,
        }
        res2 = asyncio.run(new_bridge.dispatch(req2))

        self.assertTrue(res2.get("ok"))
        self.assertEqual(res2.get("status"), "concluído")
        self.assertEqual(res2.get("mission_id"), mission_id)  # Auto-resumed from disk session!
        self.assertIn("24.000/mês", res2.get("text", ""))


if __name__ == "__main__":
    unittest.main()
