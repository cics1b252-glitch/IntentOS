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

        self.assertFalse(res1.get("ok"))
        self.assertEqual(res1.get("status"), "WAITING_CONTEXT")
        self.assertEqual(res1.get("dialogue_state"), "WAITING_CONTEXT")
        self.assertIsNone(res1.get("mission_id"))
        dialogue_id = res1.get("compatibility_dialogue_id")
        self.assertIsNotNone(dialogue_id)
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
            "resume_mission_id": dialogue_id,
        }
        res2 = asyncio.run(self.bridge.dispatch(req2))

        self.assertFalse(res2.get("ok"))
        self.assertEqual(res2.get("status"), "WAITING_CONTEXT")
        self.assertIsNone(res2.get("mission_id"))
        self.assertEqual(res2.get("compatibility_dialogue_id"), dialogue_id)
        self.assertEqual(res2.get("target_field"), "goal")
        self.assertIn("objetivo principal", res2.get("text", ""))

        # Verify session remains pending for the next required field.
        continued_session = self.bridge._load_session(session_id)
        self.assertEqual(continued_session.get("mission_status"), "waiting_context")
        self.assertEqual(
            continued_session.get("pending_dialogue", {}).get("target_field"),
            "goal",
        )

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
        dialogue_id = res1.get("compatibility_dialogue_id")
        self.assertEqual(res1.get("status"), "WAITING_CONTEXT")

        # Simulate process restart by instantiating a brand new ProductBridge
        new_bridge = ProductBridge()

        # Turn 2 on new Bridge instance without explicit resume_mission_id parameter
        req2 = {
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": session_id,
        }
        res2 = asyncio.run(new_bridge.dispatch(req2))

        self.assertFalse(res2.get("ok"))
        self.assertEqual(res2.get("status"), "WAITING_CONTEXT")
        self.assertIsNone(res2.get("mission_id"))
        self.assertEqual(res2.get("compatibility_dialogue_id"), dialogue_id)
        self.assertEqual(res2.get("target_field"), "goal")


if __name__ == "__main__":
    unittest.main()
