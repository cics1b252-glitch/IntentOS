"""Product Alpha 2 durable first-intent contracts."""
from __future__ import annotations

import asyncio
import json
import inspect

from intent_kernel.kernel import Kernel
from product_bridge import ProductBridge


class _Result:
    text = "Resposta real"
    domain = type("DomainValue", (), {"value": "other"})()


def test_first_intent_uses_kernel_and_persists_session(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def process(text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        context["intent_model"] = {"text": text, "domain": "other", "mode": "quick",
                                   "entities": [], "ambiguities": []}
        return _Result()

    bridge.kernel.process = process
    response = asyncio.run(bridge.dispatch({"action": "chat",
        "message": "Explique qual é sua função.", "session_id": "product-alpha",
        "allow_compatibility_fallback": True}))
    assert response["ok"] and response["mission_id"]
    saved = json.loads((tmp_path / "missions" / "product-alpha.json").read_text(encoding="utf-8"))
    assert saved["intent"]["domain"] == "other"
    assert saved["mission_status"] == "completed"
    assert saved["response"]["text"] == "Resposta real"


def test_session_restores_after_bridge_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    missions = tmp_path / "missions"
    missions.mkdir()
    (missions / "product-alpha.json").write_text(
        json.dumps({"mission_id": "saved", "history": [{"role": "user", "content": "olá"}]}),
        encoding="utf-8")
    restored = asyncio.run(ProductBridge().dispatch(
        {"action": "restore_session", "session_id": "product-alpha"}))
    assert restored["session"]["mission_id"] == "saved"
    assert restored["session"]["history"][0]["content"] == "olá"


def test_provider_quota_error_is_clear_and_recoverable(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    class RateLimitError(Exception):
        pass

    async def fail(text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        raise RateLimitError("sensitive provider payload")

    bridge.kernel.process = fail
    response = asyncio.run(bridge.dispatch(
        {"action": "chat", "message": "resuma", "session_id": "quota",
         "allow_compatibility_fallback": True}))
    assert response["error_code"] == "provider_quota"
    assert "cota" in response["error"].lower()
    assert "sensitive" not in response["error"]
    saved = json.loads((tmp_path / "missions" / "quota.json").read_text(encoding="utf-8"))
    assert saved["mission_status"] == "failed_recoverable"


def test_domain_is_not_the_canonical_execution_destination():
    source = inspect.getsource(Kernel._execute_canonical_route)
    assert 'Domain.OTHER: "knowledge.intent"' not in source
    assert 'analysis.get("mode") != "MISSION"' in source
