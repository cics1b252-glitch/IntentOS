"""RFC-0017.2 / STUDIO 10.4.3 Regression Test Suite.

Verifies:
1. Root Cause A — Null-safe context in FinModule with pending_dialogue=None
2. Root Cause B — Financial domain classification and monetary signal extraction
3. Repair C — Error classification (internal_kernel_error vs provider_error)
4. Live integration path through ProductBridge / Server simulation
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from intent_kernel.iue import IntentUnderstandingEngine, is_financial_text
from intent_kernel.engine.intent_engine import IntentEngine
from intent_kernel.modules.fin.module import FinanceModule, _extract_brl_amount
from intent_kernel.response import CanonicalResultKind
from intent_kernel.types import Domain, IntentInput
from product_bridge import ProductBridge


class TestRFC0017_2Repair(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        os.environ["INTENTOS_DATA_ROOT"] = self.tmp_dir
        self.bridge = ProductBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. ROOT CAUSE A REGRESSION TEST
    async def test_root_cause_a_null_safe_context(self):
        """FinModule must handle pending_dialogue=None without raising AttributeError."""
        fin = FinanceModule()
        intent = IntentInput(text="o que eu faço com 24 mil?")
        ctx_dict = {"pending_dialogue": None, "known_context": None}

        # Must NOT raise AttributeError
        res = await fin.execute(intent, ctx_dict)
        self.assertIsNotNone(res)
        self.assertIn("text", res)

    # 2. ROOT CAUSE B REGRESSION TESTS — DOMAIN DETECTION
    async def test_financial_domain_classification_positives(self):
        positives = [
            "quero investir",
            "quero investir 24 mil",
            "o que eu faço com 24 mil?",
            "o que fazer com R$ 24.000?",
            "tenho 24 mil para aplicar",
            "quanto rende 24 mil?",
            "quero fazer aportes mensais",
            "tenho R$ 3.500 por mês para investir",
        ]
        iue = IntentUnderstandingEngine()
        engine = IntentEngine()

        for text in positives:
            with self.subTest(text=text):
                s_intent = iue.analyze(text)
                self.assertEqual(s_intent.domain, "finance")
                p_intent = await engine.parse(text)
                self.assertEqual(p_intent.domain, Domain.FINANCE)

    async def test_financial_domain_classification_negatives(self):
        negatives = [
            "tenho 24 anos",
            "viajei 24 mil quilômetros",
            "meu arquivo tem 24 mil linhas",
            "preciso analisar 24 mil registros",
        ]
        iue = IntentUnderstandingEngine()
        engine = IntentEngine()

        for text in negatives:
            with self.subTest(text=text):
                s_intent = iue.analyze(text)
                self.assertNotEqual(s_intent.domain, "finance")
                p_intent = await engine.parse(text)
                self.assertNotEqual(p_intent.domain, Domain.FINANCE)

    def test_monetary_amount_extraction(self):
        self.assertEqual(_extract_brl_amount("24 mil"), 24000.0)
        self.assertEqual(_extract_brl_amount("24k"), 24000.0)
        self.assertEqual(_extract_brl_amount("R$ 24.000"), 24000.0)
        self.assertEqual(_extract_brl_amount("24.000 reais"), 24000.0)
        self.assertEqual(_extract_brl_amount("3.500"), 3500.0)

    # 3. REPAIR C REGRESSION TESTS — ERROR CLASSIFICATION
    def test_error_classification_internal_vs_provider(self):
        res_internal = self.bridge._provider_failure(
            AttributeError("'NoneType' object has no attribute 'get'"),
            "session_1",
            "msg",
            [],
            {"mission_id": "m1"},
            None
        )
        self.assertIs(res_internal.kind, CanonicalResultKind.FAILED)
        self.assertEqual(
            res_internal.metadata["error_code"], "internal_kernel_error"
        )
        self.assertIsNone(res_internal.provider_evidence)
        self.assertIn("erro interno", res_internal.text)

        res_provider = self.bridge._provider_failure(
            RuntimeError("Provider connection error"),
            "session_2",
            "msg",
            [],
            {"mission_id": "m2"},
            "gemini"
        )
        self.assertIs(res_provider.kind, CanonicalResultKind.FAILED)
        self.assertEqual(res_provider.metadata["error_code"], "provider_error")
        self.assertEqual(res_provider.provider_evidence.provider_id, "gemini")

    # 4. LIVE PRODUCT PATH TESTS
    async def test_live_path_test_a_quero_investir(self):
        res = await self.bridge.dispatch({
            "action": "chat",
            "message": "quero investir",
            "session_id": "live_a"
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["domain"], "finance")
        self.assertFalse(res["provider_called"])
        self.assertIn("text", res)

    async def test_live_path_test_b_o_que_eu_faco_com_24_mil(self):
        res = await self.bridge.dispatch({
            "action": "chat",
            "message": "o que eu faço com 24 mil?",
            "session_id": "live_b"
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["domain"], "finance")
        self.assertEqual(res["status"], "WAITING_CONTEXT")
        self.assertFalse(res["provider_called"])
        self.assertEqual(res["pending_dialogue"]["known_context"]["amount"], 24000.0)

    async def test_live_path_test_c_multi_turn(self):
        res1 = await self.bridge.dispatch({
            "action": "chat",
            "message": "quero investir 24 mil",
            "session_id": "live_c"
        })
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["domain"], "finance")
        self.assertEqual(res1["status"], "WAITING_CONTEXT")
        mission_id_1 = res1["mission_id"]

        res2 = await self.bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "live_c"
        })
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["domain"], "finance")
        self.assertEqual(res2["status"], "WAITING_CONTEXT")
        self.assertEqual(res2["mission_id"], mission_id_1)
        self.assertEqual(res2["target_field"], "goal")


if __name__ == "__main__":
    unittest.main()
