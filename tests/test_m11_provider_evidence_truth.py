"""Movement 11.10 truthful provider invocation evidence invariants."""

from __future__ import annotations

import pytest

from intent_kernel.cognition.runtime import (
    CognitiveExecutionDecision,
    CognitiveExecutionMode,
)
from intent_kernel.contracts import ProviderMessage, ProviderRequest, ProviderResponse
from intent_kernel.providers.manager import ProviderManager
from intent_kernel.types import Mode
from product_bridge import ProductBridge


class RecordingProvider:
    capabilities = {"text_completion"}

    def __init__(self, name: str, *, error: Exception | None = None):
        self.name = name
        self.error = error
        self.calls = 0

    async def execute(self, _request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderResponse(text="grounded", provider=self.name, model="stub-v1")

    async def health(self):
        return True


def _force_conversation(bridge: ProductBridge) -> None:
    async def analyze(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.CONVERSATION,
            reason="provider evidence boundary test",
        )

    bridge.components.cognitive_capability_runtime.analyze = analyze


def _assert_no_invocation_evidence(response: dict) -> None:
    assert response["provider_called"] is False
    assert response["provider"] is None
    assert not any(
        item.startswith("provider:") for item in response["resource_provenance"]
    )


@pytest.mark.asyncio
async def test_ra01_selected_mock_is_not_invocation_evidence(monkeypatch, tmp_path):
    """A pre-invocation Kernel failure cannot promote the default mock to execution."""
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    mock = bridge.components.provider_manager.get("mock")
    calls = 0
    original = mock.execute

    async def counted(request):
        nonlocal calls
        calls += 1
        return await original(request)

    async def fail_before_provider(*_args, **_kwargs):
        raise RuntimeError("failure before provider invocation")

    mock.execute = counted
    bridge.kernel.process = fail_before_provider
    _force_conversation(bridge)

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Analise este cenário independente.",
        "session_id": "ra01-pre-invocation",
    })

    assert calls == 0
    assert bridge.components.provider_manager.last_attempted is None
    assert bridge.components.provider_manager.last_used is None
    _assert_no_invocation_evidence(response)
    assert response["provider_selection"]["provider_id"] is None
    assert response["provider_selection"]["reason"] == "no_eligible_provider"


@pytest.mark.asyncio
async def test_selected_external_provider_remains_diagnostics_before_invocation(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    external = RecordingProvider("external")
    bridge.components.provider_manager.register("external", external)
    bridge.components.provider_manager.set_default("external")

    async def fail_before_provider(*_args, **_kwargs):
        raise RuntimeError("pre-invocation failure")

    bridge.kernel.process = fail_before_provider
    _force_conversation(bridge)
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Analise este cenário independente.",
        "session_id": "selected-not-invoked",
    })

    assert external.calls == 0
    assert bridge.components.provider_manager.last_attempted is None
    _assert_no_invocation_evidence(response)
    assert response["provider_selection"]["provider_id"] == "external"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("provider failed"), TypeError("bad response")])
async def test_actual_provider_attempt_is_preserved_on_failure(
    monkeypatch, tmp_path, error
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    external = RecordingProvider("external", error=error)
    bridge.components.provider_manager.register("external", external)
    bridge.components.provider_manager.set_default("external")
    _force_conversation(bridge)

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Analise este cenário independente.",
        "session_id": f"attempt-{type(error).__name__}",
    })

    assert external.calls == 1
    assert bridge.components.provider_manager.last_attempted == "external"
    assert bridge.components.provider_manager.last_used is None
    assert response["provider_called"] is True
    assert response["provider"] == "external"
    assert response["resource_provenance"] == ["provider:external"]
    assert response["status"] == "FAILED"


@pytest.mark.asyncio
async def test_deterministic_selection_without_dispatch_is_not_execution(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    alpha = RecordingProvider("alpha")
    beta = RecordingProvider("beta")
    bridge.components.provider_manager.register("alpha", alpha)
    bridge.components.provider_manager.register("beta", beta)

    async def fail_before_provider(*_args, **_kwargs):
        raise RuntimeError("blocked after selection")

    bridge.kernel.process = fail_before_provider
    _force_conversation(bridge)
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Analise este cenário independente.",
        "provider": "beta",
        "fallback_provider": "alpha",
        "allow_fallback": True,
        "session_id": "multiple-selected-not-invoked",
    })

    assert alpha.calls == beta.calls == 0
    _assert_no_invocation_evidence(response)
    assert response["provider_selection"]["provider_id"] == "beta"
    assert response["provider_selection"]["fallback_provider_id"] == "alpha"


@pytest.mark.asyncio
async def test_direct_compatibility_invocation_crosses_observed_boundary():
    manager = ProviderManager()
    provider = RecordingProvider("compatibility")
    manager.register("compatibility", provider)

    binding = await manager.route(Mode.QUICK)
    assert manager.last_attempted is None
    assert manager.last_used is None

    response = await binding.execute(ProviderRequest(
        messages=[ProviderMessage(role="user", content="compatibility call")]
    ))

    assert response.provider == "compatibility"
    assert provider.calls == 1
    assert manager.last_attempted == "compatibility"
    assert manager.last_used == "compatibility"
