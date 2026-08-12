"""Recovery-cycle characterization for the canonical product bridge."""

from __future__ import annotations

import asyncio

import pytest

from product_bridge import ProductBridge, _financial_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("quero investir 23500", 23_500.0),
        ("quero investir 23.500", 23_500.0),
        ("quero investir R$ 23.500", 23_500.0),
        ("quero investir 23.500,00", 23_500.0),
        ("quero investir R$ 23.500,00", 23_500.0),
        ("quero investir 24 mil", 24_000.0),
        ("quero investir 24k", 24_000.0),
        ("quero investir vinte e três mil e quinhentos reais", 23_500.0),
    ],
)
def test_financial_amount_supported_forms(text, expected):
    assert _financial_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    ["tenho 24 anos", "24 mil linhas", "percorri 24 mil quilômetros"],
)
def test_unrelated_numbers_are_not_financial_amounts(text):
    assert _financial_amount(text) is None


def test_multi_turn_finance_advances_and_preserves_mission(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    first = asyncio.run(bridge.dispatch({
        "action": "chat", "message": "quero investir 23500",
        "session_id": "finance",
    }))
    second = asyncio.run(bridge.dispatch({
        "action": "chat", "message": "com aportes mensais",
        "session_id": "finance",
    }))

    assert first["target_field"] == "recurrence"
    assert second["status"] == "COMPLETED"
    assert second["mission_id"] == first["mission_id"]
    restored = bridge._load_session("finance")
    assert restored["pending_dialogue"] is None
    assert restored["conversation_state"]["known_context"]["recurrence"] == "mensal"


def test_zero_provider_is_local_for_capability_and_unknown_for_knowledge(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    capability = asyncio.run(bridge.dispatch({
        "action": "chat", "message": "O que você consegue fazer?",
        "session_id": "capability",
    }))
    unknown = asyncio.run(bridge.dispatch({
        "action": "chat", "message": "Explique um fato externo inexistente xyz-987.",
        "session_id": "unknown",
    }))

    assert capability["provider"] == "local"
    assert unknown["provider"] is None
    assert unknown["status"] == "EXTERNAL_RESOURCE_REQUIRED"
    assert "quota" not in unknown["text"].lower()


def test_memory_survives_restart_and_is_project_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    asyncio.run(bridge.dispatch({
        "action": "chat", "message": "Prefiro respostas curtas.",
        "session_id": "memory-a", "project_id": "PROJECT_A",
    }))

    restarted = ProductBridge()
    same_project = asyncio.run(restarted.dispatch({
        "action": "chat", "message": "Como prefiro minhas respostas?",
        "session_id": "memory-a-2", "project_id": "PROJECT_A",
    }))
    other_project = asyncio.run(restarted.dispatch({
        "action": "chat", "message": "Como prefiro minhas respostas?",
        "session_id": "memory-b", "project_id": "PROJECT_B",
    }))

    assert "Prefiro respostas curtas" in same_project["text"]
    assert "UNKNOWN" in other_project["text"]


def test_spreadsheet_request_is_not_misclassified_as_an_app(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = asyncio.run(ProductBridge().dispatch({
        "action": "chat",
        "message": "quero criar uma planilha para controlar horas extras",
        "session_id": "spreadsheet",
    }))

    assert response["ok"]
    assert response["domain"] == "productivity"
    assert "planilha" in response["text"].lower()
    assert all(term not in response["text"] for term in ("Android", "iOS", "Web"))
