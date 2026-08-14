"""Movement 11.7 invariants: compatibility is explicit and subordinate."""

from __future__ import annotations

import pytest

from intent_kernel.application import KernelBuilder
from intent_kernel.cognition.runtime import CognitiveExecutionDecision, CognitiveExecutionMode
from intent_kernel.contracts import Mission, MissionContext
from intent_kernel.core_apps.router import CapabilityRouter
from intent_kernel.providers.manager import ProviderManager
from intent_kernel.types import Domain, IntentInput, Mode
from product_bridge import ProductBridge


TRACE_KEYS = {
    "compatibility_path_used",
    "compatibility_component",
    "reason",
    "entry_point",
    "canonical_alternative_missing",
    "deprecation_candidate",
}


def _assert_trace(response, component):
    assert response["compatibility_path_used"] is True
    trace = response["compatibility_trace"]
    assert set(trace) == TRACE_KEYS
    assert trace["compatibility_component"] == component
    assert trace["deprecation_candidate"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,status", [
    (CognitiveExecutionMode.UNKNOWN, "UNKNOWN"),
    (CognitiveExecutionMode.BLOCKED, "BLOCKED"),
    (CognitiveExecutionMode.AUTHORIZATION_REQUIRED, "AUTHORIZATION_REQUIRED"),
    (CognitiveExecutionMode.EXTERNAL_REASONING_REQUIRED, "EXTERNAL_RESOURCE_REQUIRED"),
])
async def test_terminal_decisions_never_enter_or_report_compatibility(
    monkeypatch, tmp_path, mode, status
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def analyze(*_args, **_kwargs):
        return CognitiveExecutionDecision(mode=mode, reason="terminal invariant")

    bridge.components.cognitive_capability_runtime.analyze = analyze
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Qual a capital de XZ-91?",
        "allow_compatibility_fallback": True,
    })
    assert response["status"] == status
    assert response["mission_id"] is None
    assert response["compatibility_path_used"] is False
    assert response["compatibility_traces"] == []
    assert "compatibility_trace" not in response


@pytest.mark.asyncio
async def test_product_field_filling_is_explicit_compatibility(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({
        "action": "chat", "message": "Quero investir 24 mil.",
    })
    _assert_trace(response, "ProductBridgeFieldFilling")
    assert response["response_authority"] == "CognitiveResponseAssembler"


@pytest.mark.asyncio
async def test_kernel_conversation_fallback_is_explicit_and_governed(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def analyze(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.CONVERSATION,
            reason="nonterminal compatibility characterization",
        )

    bridge.components.cognitive_capability_runtime.analyze = analyze
    response = await bridge.dispatch({
        "action": "chat", "message": "Conte algo independente.",
    })
    _assert_trace(response, "Kernel/PipelineDAG")
    assert response["response_authority"] == "CognitiveResponseAssembler"


@pytest.mark.asyncio
async def test_module_router_emits_safe_standard_trace(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.module_router.route(IntentInput(text="investir", domain=Domain.FINANCE))
    trace = components.module_router.last_compatibility_trace
    assert set(trace) == TRACE_KEYS
    assert trace["compatibility_component"] == "ModuleRouter"
    assert components.migration_telemetry.snapshot()["compatibility_traces"][-1] == trace
    assert "investir" not in str(trace)


@pytest.mark.asyncio
async def test_provider_manager_direct_default_is_characterized_compatibility():
    manager = ProviderManager()

    class Provider:
        name = "stub"
        capabilities = {"text_completion"}

    provider = Provider()
    manager.register("stub", provider)
    assert (await manager.route(Mode.QUICK)).name == provider.name
    trace = manager.last_compatibility_trace
    assert set(trace) == TRACE_KEYS
    assert trace["compatibility_component"] == "ProviderManager"


def test_domain_default_is_explicit_compatibility_not_silent_authority():
    router = CapabilityRouter()
    mission = Mission(objective="legacy", context=MissionContext(domain=Domain.FINANCE))
    assert router.select(mission) is None
    trace = router.last_compatibility_trace
    assert set(trace) == TRACE_KEYS
    assert trace["compatibility_component"] == "CapabilityRouter"


@pytest.mark.asyncio
async def test_explicit_capability_selection_has_no_compatibility_trace(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = Mission(objective="canonical", context=MissionContext(domain=Domain.FINANCE))
    app = components.capability_router.select(mission, "finance.intent")
    assert app is not None
    assert components.capability_router.last_compatibility_trace is None
