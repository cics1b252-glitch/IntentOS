import asyncio
import json
import unittest
from product_bridge import ProductBridge


class TestIntentGatewayPythonBridge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = ProductBridge()

    async def test_handshake_and_status(self):
        res = await self.bridge.dispatch({"action": "health"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("protocol_version"), "1.0")
        self.assertEqual(res.get("kernel_status"), "ready")

        status = await self.bridge.dispatch({"action": "status"})
        self.assertTrue(status.get("ok"))
        self.assertEqual(status.get("kernel"), "pronto")
        self.assertIn("providers", status)
        self.assertIn("modules", status)

    async def test_provider_discovery(self):
        res = await self.bridge.dispatch({"action": "providers"})
        self.assertTrue(res.get("ok"))
        self.assertIn("available", res)
        self.assertIsInstance(res["available"], list)
        self.assertIn("gemini", res["available"])

    async def test_core_app_discovery(self):
        res = await self.bridge.dispatch({"action": "core_apps"})
        self.assertTrue(res.get("ok"))
        self.assertIn("modules", res)
        self.assertIsInstance(res["modules"], list)

    async def test_constitution_discovery(self):
        res = await self.bridge.dispatch({"action": "constitution"})
        self.assertTrue(res.get("ok"))
        self.assertIn("version", res)
        self.assertIn("guardians", res)
        self.assertIsInstance(res["guardians"], list)

    async def test_diagnostics(self):
        res = await self.bridge.dispatch({"action": "diagnostics"})
        self.assertTrue(res.get("ok"))
        self.assertIn("trace", res)
        self.assertIn("data_migration_status", res)

    async def test_iue_analysis(self):
        res = await self.bridge.dispatch({"action": "iue", "text": "Quero investir 23.500"})
        self.assertTrue(res.get("ok"))
        self.assertIn("structured_intent", res)
        si = res["structured_intent"]
        self.assertEqual(si.get("domain"), "finance")
        self.assertIn("intent_quality_index", si)
        self.assertIsNotNone(si.get("clarifying_question"))

    async def test_utf8_preservation(self):
        res = await self.bridge.dispatch({"action": "intent", "message": "Olá! Testando acentuação em Português."})
        self.assertIn("ok", res)
        # Should complete without throwing encoding errors
        serialized = json.dumps(res, ensure_ascii=False)
        self.assertIn("ok", serialized)

    async def test_absence_of_fake_data(self):
        status = await self.bridge.dispatch({"action": "status"})
        # Should not contain hardcoded fake values
        self.assertNotEqual(status.get("providers"), ["fake_provider_01", "fake_provider_02"])


if __name__ == "__main__":
    unittest.main()
