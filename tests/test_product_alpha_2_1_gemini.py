"""Product Alpha 2.1 Gemini provider and multi-provider contracts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from intent_kernel.application import KernelBuilder
from intent_kernel.providers import GeminiProvider, GeminiProviderError, ManagedProvider, ProviderManager
from intent_kernel.contracts import ProviderRequest, ProviderMessage, ProviderResponse
from intent_kernel.types import Message
from product_bridge import ProductBridge

ROOT = Path(__file__).parents[1]
HOST = (ROOT / "windows" / "host" / "ProductController.cs").read_text(encoding="utf-8")
UI = (ROOT / "ui" / "shell" / "product" / "product.js").read_text(encoding="utf-8")


def _success_transport(method, path, payload):
    assert method == "POST"
    assert path.endswith(":generateContent")
    return 200, {
        "candidates": [{"content": {"parts": [{"text": "Resposta Gemini"}]}, "finishReason": "STOP"}],
        "modelVersion": "gemini-2.5-flash-lite",
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5},
    }


def test_gemini_implements_canonical_provider_port():
    provider = GeminiProvider(api_key="test-key-with-safe-length", transport=_success_transport)
    assert provider.name == "gemini"
    assert provider.capabilities == {"text_completion"}
    assert callable(provider.execute) and callable(provider.health)


def test_gemini_generates_and_records_model_usage():
    provider = GeminiProvider(api_key="test-key-with-safe-length", transport=_success_transport)
    result = asyncio.run(provider.complete([Message(role="user", content="Olá")]))
    assert result.text == "Resposta Gemini"
    assert result.model == "gemini-2.5-flash-lite"
    assert result.usage["total_tokens"] == 5


@pytest.mark.parametrize("http_status,expected", [(403, "invalid_key"), (429, "quota_reached"), (503, "unavailable")])
def test_gemini_classifies_connection_failures(http_status, expected):
    def fail(method, path, payload):
        raise GeminiProviderError(expected, http_status)
    provider = GeminiProvider(api_key="test-key-with-safe-length", transport=fail)
    diagnosis = asyncio.run(provider.diagnose())
    assert diagnosis == {"ok": False, "status": expected, "error_code": expected}


def test_composition_registers_both_and_respects_default(tmp_path):
    components = (KernelBuilder().with_pkb_path(tmp_path / "pkb").with_environment({
        "OPENAI_API_KEY": "sk-test-only-not-real-value",
        "GEMINI_API_KEY": "gemini-test-only-not-real-value",
        "INTENTOS_DEFAULT_PROVIDER": "gemini",
    }).build())
    assert set(components.provider_manager.available) == {"openai", "gemini"}
    assert components.provider_manager.default == "gemini"


def test_managed_provider_switches_without_rebuilding_kernel():
    class Provider:
        capabilities = {"text_completion"}
        def __init__(self, name): self.name = name
        async def execute(self, request): return ProviderResponse(text=self.name, provider=self.name, model="test")
        async def health(self): return True
    manager = ProviderManager()
    manager.register("one", Provider("one"))
    manager.register("two", Provider("two"))
    managed = ManagedProvider(manager)
    request = ProviderRequest(messages=[ProviderMessage(role="user", content="test")])
    assert asyncio.run(managed.execute(request)).provider == "one"
    manager.set_default("two")
    assert asyncio.run(managed.execute(request)).provider == "two"


def test_managed_provider_fallback_is_opt_in_and_preserves_request():
    class Provider:
        capabilities = {"text_completion"}
        def __init__(self, name, fails=False): self.name, self.fails = name, fails
        async def execute(self, request):
            if self.fails: raise RuntimeError("failed")
            return ProviderResponse(text=request.messages[0].content, provider=self.name, model="test")
        async def health(self): return True
    manager = ProviderManager()
    manager.register("primary", Provider("primary", fails=True))
    manager.register("alternate", Provider("alternate"))
    managed = ManagedProvider(manager)
    request = ProviderRequest(messages=[ProviderMessage(role="user", content="same mission")])
    with pytest.raises(RuntimeError):
        asyncio.run(managed.execute(request))
    manager.configure_fallback(True, "alternate")
    response = asyncio.run(managed.execute(request))
    assert response.provider == "alternate" and response.text == "same mission"
    assert manager.last_used == "alternate"


def test_fallback_requires_explicit_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    class Provider:
        def __init__(self, name): self.name = name
        @property
        def capabilities(self): return {"text_completion"}
        async def execute(self, request): raise NotImplementedError
        async def health(self): return True

    bridge.components.provider_manager.register("primary", Provider("primary"))
    bridge.components.provider_manager.register("alternate", Provider("alternate"))
    bridge.components.provider_manager.set_default("primary")

    class Result:
        text = "fallback ok"
        domain = type("Domain", (), {"value": "other"})()

    async def process(text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        if not bridge.components.provider_manager.fallback:
            raise RuntimeError("primary failed")
        bridge.components.provider_manager._last_used = "alternate"
        return Result()
    bridge.kernel.process = process

    denied = asyncio.run(bridge.dispatch({"action": "chat", "message": "teste",
        "fallback_provider": "alternate", "allow_fallback": False, "session_id": "denied",
        "allow_compatibility_fallback": True}))
    allowed = asyncio.run(bridge.dispatch({"action": "chat", "message": "teste",
        "fallback_provider": "alternate", "allow_fallback": True, "session_id": "allowed",
        "allow_compatibility_fallback": True}))
    assert denied["ok"] is False
    assert allowed["ok"] is True and allowed["provider"] == "alternate"
    assert allowed["fallback_used"] is True


def test_windows_protects_each_key_and_never_collects_google_password():
    assert "ProtectedData.Protect" in HOST
    assert 'provider.{provider}.secret' in HOST
    assert 'start.Environment["GEMINI_API_KEY"]' in HOST
    assert "senha Google" not in UI
    assert "Google Gemini" in UI and "Chave Gemini" in UI


def test_default_provider_status_and_producer_are_persisted():
    for term in ("ProviderStates", "AllowFallback", "SetDefaultProvider", "usedProvider"):
        assert term in HOST
    assert "item.provider" in UI
    assert "Autorizar fallback" in UI


def test_free_tier_notice_is_explicit():
    assert "nível gratuito" in UI
    assert "usado pelo Google para melhorar produtos" in UI


def test_session_response_records_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    class Result:
        text = "persistida"
        domain = type("Domain", (), {"value": "other"})()
    async def process(text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        return Result()
    bridge.kernel.process = process
    response = asyncio.run(bridge.dispatch({"action": "chat", "message": "olá", "session_id": "provider-history",
                                            "allow_compatibility_fallback": True}))
    saved = json.loads((tmp_path / "missions" / "provider-history.json").read_text(encoding="utf-8"))
    assert saved["response"]["provider"] == response["provider"]
