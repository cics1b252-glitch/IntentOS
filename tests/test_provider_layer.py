"""Test: Provider Layer + Capability Registry."""

import pytest
from intent_kernel.providers.layer import (
    ProviderRegistry,
    ProviderInfo,
)
from intent_kernel.capabilities import (
    CapabilityRegistry,
    Capability,
    register_default_capabilities,
)


# ---------------------------------------------------------------------------
# Mock providers for testing
# ---------------------------------------------------------------------------

class MockLLMProvider:
    def __init__(self, name: str = "mock"):
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def models(self):
        return ["mock-v1"]

    async def complete(self, messages, model=None, temperature=0.7, max_tokens=2048):
        return {"text": "mock response", "model": "mock-v1", "usage": {}}

    async def health_check(self):
        return True


class MockStorageProvider:
    def __init__(self):
        self._data = {}

    @property
    def name(self):
        return "mock-storage"

    async def store(self, key, data):
        self._data[key] = data
        return True

    async def retrieve(self, key):
        return self._data.get(key)

    async def delete(self, key):
        return self._data.pop(key, None) is not None

    async def list_keys(self, prefix=""):
        return [k for k in self._data if k.startswith(prefix)]

    async def health_check(self):
        return True


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    def test_register_and_get(self):
        r = ProviderRegistry()
        p = MockLLMProvider("openai")
        r.register("openai", "llm", p)
        assert r.get("openai") is p

    def test_get_active(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider("openai"), priority=1)
        r.register("claude", "llm", MockLLMProvider("claude"), priority=0)
        active = r.get_active("llm")
        assert active.name == "claude"  # lower priority = higher precedence

    def test_get_active_none_healthy(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider("openai"))
        r.deactivate("openai")
        assert r.get_active("llm") is None

    def test_list_providers(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider())
        r.register("s3", "storage", MockStorageProvider())
        assert len(r.list_providers()) == 2
        assert len(r.list_providers("llm")) == 1

    def test_deactivate_activate(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider())
        r.deactivate("openai")
        info = r.list_providers("llm")[0]
        assert info["active"] is False
        r.activate("openai")
        info = r.list_providers("llm")[0]
        assert info["active"] is True

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider())
        results = await r.health_check_all()
        assert results["openai"] is True

    def test_status(self):
        r = ProviderRegistry()
        r.register("openai", "llm", MockLLMProvider())
        s = r.status()
        assert s["total"] == 1
        assert "llm" in s["by_type"]


# ---------------------------------------------------------------------------
# Capability Registry
# ---------------------------------------------------------------------------

class TestCapabilityRegistry:
    def test_register_and_get(self):
        r = CapabilityRegistry()
        r.register("memory", "User memory", "intent_kernel.pkb")
        cap = r.get("memory")
        assert cap is not None
        assert cap.name == "memory"

    def test_has(self):
        r = CapabilityRegistry()
        r.register("knowledge", "Knowledge Core", "intent_kernel.pkb")
        assert r.has("knowledge") is True
        assert r.has("nonexistent") is False

    def test_query_by_tags(self):
        r = CapabilityRegistry()
        r.register("memory", "Memory", "kb", tags=["memory", "user"])
        r.register("knowledge", "Knowledge", "kb", tags=["knowledge", "persistence"])
        results = r.query(tags="memory")
        assert len(results) == 1

    def test_record_usage(self):
        r = CapabilityRegistry()
        r.register("memory", "Memory", "kb")
        r.record_usage("memory", "atlas")
        r.record_usage("memory", "logos")
        cap = r.get("memory")
        assert "atlas" in cap.used_by
        assert "logos" in cap.used_by

    def test_list_all(self):
        r = CapabilityRegistry()
        r.register("memory", "Memory", "kb")
        r.register("knowledge", "Knowledge", "kb")
        all_caps = r.list_all()
        assert len(all_caps) == 2

    def test_status(self):
        r = CapabilityRegistry()
        r.register("memory", "Memory", "kb")
        s = r.status()
        assert s["total"] == 1

    def test_register_default_capabilities(self):
        r = CapabilityRegistry()
        register_default_capabilities(r)
        assert r.has("memory")
        assert r.has("knowledge")
        assert r.has("decision")
        assert r.has("planning")
        assert r.has("simulation")
        assert r.has("research")
        assert r.has("versioning")
        assert r.has("search")
        assert r.has("guardians")
        assert r.has("event_bus")
        assert r.status()["total"] == 10


# ---------------------------------------------------------------------------
# Integration: Provider Registry + Capability Registry
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_providers_and_capabilities_together(self):
        pr = ProviderRegistry()
        cr = CapabilityRegistry()

        pr.register("openai", "llm", MockLLMProvider())
        register_default_capabilities(cr)

        # Core App can query both
        provider = pr.get_active("llm")
        assert provider is not None

        cap = cr.get("knowledge")
        assert cap is not None

        # Status for Monitor
        provider_status = pr.status()
        capability_status = cr.status()
        assert provider_status["total"] == 1
        assert capability_status["total"] == 10
