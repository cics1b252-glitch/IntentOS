"""Movement 11.6 response-envelope and provider-invocation authority invariants."""

from __future__ import annotations

import pytest

from intent_kernel.application import KernelBuilder
from intent_kernel.cognition.runtime import CognitiveExecutionDecision, CognitiveExecutionMode
from intent_kernel.contracts import ProviderResponse
from intent_kernel.response import CognitiveResponseAssembler, ResponseStatus
from product_bridge import ProductBridge


class StubProvider:
    capabilities = {"text_completion"}

    def __init__(self, name: str, *, healthy: bool = True, text: str = "grounded"):
        self.name = name
        self._healthy = healthy
        self._text = text
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        return ProviderResponse(text=self._text, provider=self.name, model="stub-v1")

    async def health(self):
        return self._healthy


def _force_conversation(bridge: ProductBridge) -> None:
    async def analyze(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.CONVERSATION,
            reason="test canonical conversation",
        )

    bridge.components.cognitive_capability_runtime.analyze = analyze


@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_status", [
    ("O que você consegue fazer?", "COMPLETED"),
    ("Qual a capital de um planeta fictício chamado XZ-91?", "UNKNOWN"),
    ("Explique juros compostos.", "EXTERNAL_RESOURCE_REQUIRED"),
    ("Crie e envie um e-mail.", "AUTHORIZATION_REQUIRED"),
])
async def test_major_non_provider_paths_share_response_authority(
    monkeypatch, tmp_path, message, expected_status
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({"action": "chat", "message": message})
    assert response["status"] == expected_status
    assert response["response_authority"] == "CognitiveResponseAssembler"


@pytest.mark.asyncio
async def test_response_assembler_owns_status_and_provider_provenance(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    assembler = CognitiveResponseAssembler(components.constitution_engine)

    unknown = assembler.from_result({"text": "unknown", "status": "UNKNOWN"})
    provider = assembler.from_result({
        "text": "answer", "status": "concluído",
        "provider": "external", "provider_called": True,
    })

    assert unknown.status is ResponseStatus.UNKNOWN
    assert unknown.epistemic_status == "unknown"
    assert unknown.confidence == 1.0
    assert provider.status is ResponseStatus.COMPLETED
    assert provider.resource_provenance == ["provider:external"]


@pytest.mark.asyncio
async def test_mock_binding_is_not_an_eligible_provider_resource(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    decision = await components.provider_authority.select()
    assert decision.available is False
    assert decision.reason == "no_eligible_provider"
    assert decision.authority == "RRM"


@pytest.mark.asyncio
async def test_one_healthy_rrm_provider_is_selected(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.provider_manager.register("external", StubProvider("external"))
    decision = await components.provider_authority.select()
    assert decision.provider_id == "external"
    assert decision.eligible_provider_ids == ("external",)


@pytest.mark.asyncio
async def test_configured_but_unhealthy_provider_is_not_selected(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.provider_manager.register("unhealthy", StubProvider("unhealthy", healthy=False))
    decision = await components.provider_authority.select()
    assert decision.available is False
    assert decision.eligible_provider_ids == ()


@pytest.mark.asyncio
async def test_two_providers_use_deterministic_preference_and_fallback(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.provider_manager.register("alpha", StubProvider("alpha"))
    components.provider_manager.register("beta", StubProvider("beta"))
    decision = await components.provider_authority.select(
        preferred_provider_id="beta", fallback_provider_id="alpha", allow_fallback=True,
    )
    assert decision.provider_id == "beta"
    assert decision.fallback_provider_id == "alpha"


@pytest.mark.asyncio
async def test_provider_disappearing_before_invocation_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.provider_manager.register("external", StubProvider("external"))
    decision = await components.provider_authority.select()
    components.resource_manager.unregister_provider("external")
    binding = await components.provider_manager.route(mode=None, selection=decision)
    assert binding is None


@pytest.mark.asyncio
async def test_product_path_invokes_only_rrm_selected_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    provider = StubProvider("external", text="Resposta externa")
    bridge.components.provider_manager.register("external", provider)
    bridge.components.provider_manager.set_default("external")
    _force_conversation(bridge)
    response = await bridge.dispatch({
        "action": "chat", "message": "Analise este cenário independente.",
        "session_id": "provider-selected",
    })
    assert provider.calls == 1
    assert response["provider"] == "external"
    assert response["provider_called"] is True
    assert response["fallback_used"] is False
    assert response["provider_selection"]["authority"] == "RRM"
    assert response["resource_provenance"] == ["provider:external"]
    assert response["response_authority"] == "CognitiveResponseAssembler"


@pytest.mark.asyncio
async def test_zero_provider_product_path_is_truthful_and_never_invokes_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    mock = bridge.components.provider_manager.get("mock")
    mock_calls = 0
    original = mock.execute

    async def counted(request):
        nonlocal mock_calls
        mock_calls += 1
        return await original(request)

    mock.execute = counted
    _force_conversation(bridge)
    response = await bridge.dispatch({
        "action": "chat", "message": "Analise este cenário independente.",
        "session_id": "zero-provider-selection",
    })
    assert mock_calls == 0
    assert response["provider_called"] is False
    assert response["provider"] is None
    assert response["resource_provenance"] == []
    assert response["provider_selection"]["reason"] == "no_eligible_provider"


@pytest.mark.asyncio
async def test_waiting_confirmation_has_distinct_canonical_status(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    assembler = CognitiveResponseAssembler(components.constitution_engine)
    response = assembler.from_result({
        "text": "confirm", "status": "WAITING_USER_CONFIRMATION",
        "execution_mode": "MISSION",
    })
    assert response.status is ResponseStatus.WAITING_CONFIRMATION
    assert response.execution_mode == "MISSION"


@pytest.mark.asyncio
async def test_authorized_product_mission_reports_waiting_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
    })
    assert response["status"] == "WAITING_CONFIRMATION"
    assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    assert response["response_authority"] == "CognitiveResponseAssembler"
