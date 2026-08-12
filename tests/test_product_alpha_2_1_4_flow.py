"""Product Alpha 2.1.4 first-intent, timestamps, migration and telemetry."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from intent_kernel.contracts import ProviderResponse
from intent_kernel.time_utils import utc_iso
from intent_kernel.types import Domain, EpistemicStatus, IntentOutput, Mode
from product_bridge import ProductBridge


@pytest.mark.parametrize("value", [
    "2024-01-01T00:00:00Z",
    "2023-12-31T21:00:00-03:00",
    1704067200,
    1704067200000,
    datetime(2024, 1, 1, tzinfo=timezone.utc),
])
def test_timestamp_normalizer_accepts_canonical_inputs(value):
    assert utc_iso(value) == "2024-01-01T00:00:00Z"


def test_timestamp_normalizer_handles_missing_and_invalid():
    assert utc_iso(None, fallback_now=False) is None
    assert utc_iso("invalid", fallback_now=False) is None
    assert utc_iso("invalid").endswith("Z")


def test_legacy_session_is_backed_up_and_migrated(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    missions = tmp_path / "missions"
    missions.mkdir()
    source = missions / "legacy.json"
    source.write_text(json.dumps({"history": [
        {"role": "user", "content": "olá", "timestamp": 1704067200},
        {"role": "assistant", "content": "oi"},
    ]}), encoding="utf-8")
    bridge = ProductBridge()
    migrated = json.loads(source.read_text(encoding="utf-8"))
    assert migrated["history"][0]["timestamp"] == "2024-01-01T00:00:00Z"
    assert migrated["history"][1]["timestamp"].endswith("Z")
    assert list((tmp_path / "backups").rglob("legacy.json"))
    assert "migrated=1" in bridge.data_migration_status


@pytest.mark.parametrize("message", [
    "Quero investir 23500",
    "Quero investir 23.500",
    "Quero investir R$ 23.500",
    "Quero uma sugestão para investir vinte e três mil e quinhentos reais",
])
def test_ambiguous_first_financial_intent_creates_mission_and_asks_frequency(monkeypatch, tmp_path, message):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = asyncio.run(ProductBridge().dispatch({"action": "chat", "message": message,
                                                       "session_id": "first"}))
    assert response["ok"] and response["mission_id"]
    assert response["domain"] == "finance"
    assert "único ou para um aporte mensal" in response["text"]
    assert response["provider_called"] is False
    assert "Gemini não foi necessário" in response["provider_explanation"]
    saved = json.loads((tmp_path / "missions" / "first.json").read_text(encoding="utf-8"))
    assert saved["mission_status"] == "completed" and len(saved["history"]) == 2


def test_one_time_financial_intent_never_becomes_monthly_from_old_history(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    bridge.components.provider_manager._last_used = "gemini"
    response = asyncio.run(bridge.dispatch({"action": "chat",
        "message": "Tenho 23500 para investir", "session_id": "one-time",
        "history": [{"role": "assistant", "content": "1. objetivo 2. prazo"}]}))
    assert response["ok"] and "R$ 23.500 em investimento único" in response["text"]
    assert "R$ 1/mês" not in response["text"]
    assert response["provider"] == "local" and response["provider_called"] is False


def test_flow_telemetry_identifies_last_stage_without_sensitive_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    response = asyncio.run(bridge.dispatch({"action": "chat", "message": "Quero investir 23500",
        "session_id": "trace", "correlation_id": "corr-123"}))
    trace = response["trace"]
    assert trace["requestCorrelationId"] == "corr-123"
    assert trace["intentId"] and trace["missionId"]
    assert trace["lastCompletedStage"] == "response_persisted"
    assert trace["persistenceStatus"] == "completed"
    log = (tmp_path / "logs" / "intent-flow.jsonl").read_text(encoding="utf-8")
    for event in ("bridge_request_received", "intent_created", "intent_validated",
                  "mission_compiled", "mission_persisted", "response_persisted"):
        assert event in log
    assert "Quero investir" not in log


def test_failure_updates_trace_and_preserves_created_mission(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def fail(_text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        context["intent_model"] = {"domain": "finance"}
        context["flow_event"]("mission_persisted", mission_id=context["mission_id"])
        raise RuntimeError("secret prompt contents")

    bridge.kernel.process = fail
    response = asyncio.run(bridge.dispatch({"action": "chat", "message": "investir",
                                             "session_id": "failure"}))
    assert not response["ok"]
    assert response["mission_id"] == "11111111-1111-4111-8111-111111111111"
    assert response["trace"]["lastFailedStage"] == "mission_persisted"
    assert "secret" not in json.dumps(response)


def test_retry_forwards_same_mission_to_canonical_kernel(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    mission_id = "22222222-2222-4222-8222-222222222222"
    seen: list[str | None] = []

    async def characterized_process(_text, context):
        seen.append(context.get("resume_mission_id"))
        context["mission_id"] = mission_id
        context["intent_model"] = {"domain": "other"}
        if len(seen) == 1:
            raise RuntimeError("temporary")
        return IntentOutput(text="retomada", mode=Mode.BASIC, domain=Domain.OTHER,
                            confidence=1.0, epistemic_status=EpistemicStatus.FACT)

    bridge.kernel.process = characterized_process
    first = asyncio.run(bridge.dispatch({"action": "chat", "message": "teste",
                                         "session_id": "retry",
                                         "allow_compatibility_fallback": True}))
    second = asyncio.run(bridge.dispatch({"action": "chat", "message": "teste",
        "session_id": "retry", "resume_mission_id": first["mission_id"],
        "allow_compatibility_fallback": True}))
    assert not first["ok"] and second["ok"]
    assert first["mission_id"] == second["mission_id"] == mission_id
    assert seen == [None, mission_id]


def test_ui_contract_reports_render_and_recovers_loading():
    ui = (pytest.importorskip("pathlib").Path(__file__).parents[1] /
          "ui/shell/product/product.js").read_text(encoding="utf-8")
    assert "ui_response_rendered" in ui
    assert "onFinally: () => { busy=false; render(); }" in ui
    assert "lastMissionId" in ui and "resumeMissionId" in ui
    assert "Invalid Date" not in ui
