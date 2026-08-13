"""Movement 11.9 response semantics and compatibility provenance invariants."""

from __future__ import annotations

import inspect

import pytest

from intent_kernel.application import KernelBuilder
from intent_kernel.cognition.runtime import (
    CognitiveExecutionDecision,
    CognitiveExecutionMode,
)
from intent_kernel.response import (
    CanonicalResultKind,
    CanonicalTurnResult,
    CognitiveResponseAssembler,
)
from product_bridge import ProductBridge


@pytest.mark.asyncio
async def test_product_bridge_passes_typed_semantics_to_assembler(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    result = await bridge._chat({
        "action": "chat",
        "message": "Qual a capital de um planeta fictício chamado XZ-91?",
    })

    assert isinstance(result, CanonicalTurnResult)
    assert result.kind is CanonicalResultKind.UNKNOWN
    assert not hasattr(result, "status")
    assert not hasattr(result, "execution_mode")
    assert not hasattr(result, "epistemic_status")
    assert not hasattr(result, "confidence")


@pytest.mark.asyncio
async def test_typed_metadata_cannot_override_canonical_response_semantics(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    assembler = CognitiveResponseAssembler(components.constitution_engine)
    result = CanonicalTurnResult(
        text="truthful unknown",
        kind=CanonicalResultKind.UNKNOWN,
        metadata={
            "status": "COMPLETED",
            "execution_mode": "MISSION",
            "epistemic_status": "fact",
            "confidence": 0.01,
            "provider": "invented",
            "provider_called": True,
        },
    )
    response = assembler.from_result(result)

    assert response.status.value == "UNKNOWN"
    assert response.execution_mode == "UNKNOWN"
    assert response.epistemic_status == "unknown"
    assert response.confidence == 1.0
    assert response.provider is None
    assert response.provider_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,expected_status",
    [
        ("Qual a capital de um planeta fictício chamado XZ-91?", "UNKNOWN"),
        ("Qual a população da Islândia em 2025?", "UNKNOWN"),
        ("Crie e envie um e-mail.", "AUTHORIZATION_REQUIRED"),
        ("Explique juros compostos.", "EXTERNAL_RESOURCE_REQUIRED"),
    ],
)
async def test_terminal_paths_without_participation_have_no_compatibility_trace(
    monkeypatch, tmp_path, message, expected_status
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({
        "action": "chat",
        "message": message,
        "allow_compatibility_fallback": True,
    })

    assert response["status"] == expected_status
    assert response["compatibility_path_used"] is False
    assert "compatibility_trace" not in response
    assert response["compatibility_traces"] == []


@pytest.mark.asyncio
async def test_blocked_with_domain_hint_does_not_fabricate_compatibility(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def blocked(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.BLOCKED,
            reason="test",
            domain_hint="coding",
        )

    bridge.components.cognitive_capability_runtime.analyze = blocked
    response = await bridge.dispatch({"action": "chat", "message": "blocked"})

    assert response["status"] == "BLOCKED"
    assert response.get("compatibility_path_used", False) is False


@pytest.mark.asyncio
async def test_actual_field_filling_emits_boundary_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({
        "action": "chat", "message": "Quero investir 24 mil."
    })

    assert response["compatibility_path_used"] is True
    assert response["compatibility_trace"]["compatibility_component"] == (
        "ProductBridgeFieldFilling"
    )
    assert response["compatibility_trace"]["entry_point"] == (
        "ProductBridge.finance_field_filling"
    )


@pytest.mark.asyncio
async def test_considered_but_terminal_fallback_is_not_participation(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def unknown(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.UNKNOWN,
            reason="terminal",
            domain_hint="finance",
        )

    bridge.components.cognitive_capability_runtime.analyze = unknown
    response = await bridge.dispatch({
        "action": "chat",
        "message": "unrelated",
        "allow_compatibility_fallback": True,
    })
    assert response["status"] == "UNKNOWN"
    assert response.get("compatibility_path_used", False) is False


@pytest.mark.asyncio
async def test_multiple_actual_compatibility_events_are_aggregated(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    result = CanonicalTurnResult.local("compatibility")
    result = bridge._compatibility_response(
        result,
        component="FirstAdapter",
        reason="first_executed",
        entry_point="first.boundary",
        canonical_alternative_missing="first.canonical",
    )
    result = bridge._compatibility_response(
        result,
        component="SecondAdapter",
        reason="second_executed",
        entry_point="second.boundary",
        canonical_alternative_missing="second.canonical",
    )
    response = await bridge._govern_response(result, {})

    assert response["compatibility_path_used"] is True
    assert [
        event["compatibility_component"]
        for event in response["compatibility_traces"]
    ] == ["FirstAdapter", "SecondAdapter"]


def test_product_bridge_no_longer_authors_canonical_semantic_fields():
    governed_methods = (
        ProductBridge._terminal_cognitive_response,
        ProductBridge._run_controlled_mission,
        ProductBridge._complete_local_request,
        ProductBridge._provider_failure,
        ProductBridge._govern_response,
    )
    source = "\n".join(inspect.getsource(method) for method in governed_methods)

    for field in (
        '"status":',
        '"execution_mode":',
        '"epistemic_status":',
        '"confidence":',
        '"provider_called":',
        '"missing_capabilities":',
    ):
        assert field not in source
