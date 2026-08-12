"""Regression coverage for the Windows UTF-8 JSON-lines bridge."""
from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

from intent_kernel.cognition.runtime import (
    CognitiveExecutionDecision,
    CognitiveExecutionMode,
)
from intent_kernel.pkb.json_store import JsonFileStore
from intent_kernel.pkb.models import KnowledgeEvent
from product_bridge import ProductBridge, _protocol_write

ROOT = Path(__file__).parents[1]
HOST = (ROOT / "windows" / "host" / "ProductController.cs").read_text(encoding="utf-8")
PROGRAM = (ROOT / "windows" / "host" / "Program.cs").read_text(encoding="utf-8")
UI = (ROOT / "ui" / "shell" / "product" / "product.js").read_text(encoding="utf-8")
BUILD = (ROOT / "windows" / "build.ps1").read_text(encoding="utf-8")

UNICODE_SAMPLE = "📊 Português: ç, ã, é, ô | R$ 5.000, € 10, £ 8 | 日本語 | العربية"


def test_u1f4ca_protocol_survives_cp1252_stdout(monkeypatch):
    raw = io.BytesIO()
    cp1252 = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", cp1252)
    _protocol_write({"ok": True, "text": UNICODE_SAMPLE})
    cp1252.flush()
    payload = json.loads(raw.getvalue().decode("cp1252"))
    assert payload["text"] == UNICODE_SAMPLE


def test_bridge_and_session_round_trip_unicode(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path / "Dados com acentuação"))
    bridge = ProductBridge()

    async def nonterminal(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.CONVERSATION,
            reason="test nonterminal compatibility precondition",
        )

    bridge.components.cognitive_capability_runtime.analyze = nonterminal

    class Result:
        text = f"## Resposta Gemini\n\n{UNICODE_SAMPLE}"
        domain = type("Domain", (), {"value": "other"})()

    async def process(text, context):
        context["mission_id"] = "11111111-1111-4111-8111-111111111111"
        return Result()

    bridge.kernel.process = process
    response = asyncio.run(bridge.dispatch({"action": "chat", "message": UNICODE_SAMPLE,
                                            "session_id": "unicode",
                                            "allow_compatibility_fallback": True}))
    assert response["ok"] and response["text"].endswith(UNICODE_SAMPLE)
    restored = asyncio.run(bridge.dispatch({"action": "restore_session", "session_id": "unicode"}))
    assert restored["session"]["history"][-1]["content"].endswith(UNICODE_SAMPLE)


def test_pkb_files_are_utf8_with_unicode(tmp_path):
    store = JsonFileStore(str(tmp_path / "Conhecimento São Paulo"))
    event = KnowledgeEvent(title="📊 Balanço", summary=UNICODE_SAMPLE,
                           content={"markdown": f"**Análise** {UNICODE_SAMPLE}"})
    asyncio.run(store.append(event))
    raw = (store.events_path / f"{event.id}.json").read_bytes()
    assert "📊" in raw.decode("utf-8")
    assert asyncio.run(store.get(event.id)).summary == UNICODE_SAMPLE


def test_host_pipes_logs_and_state_are_explicit_utf8():
    for term in ("StandardInputEncoding", "StandardOutputEncoding", "StandardErrorEncoding"):
        assert term in HOST
    assert "PYTHONUTF8" in HOST and "PumpStandardErrorAsync" in HOST
    assert "new UTF8Encoding(false)" in HOST
    assert "new System.Text.UTF8Encoding(false)" in PROGRAM


def test_stdout_is_protocol_only_and_errors_are_redacted():
    bridge = (ROOT / "product_bridge.py").read_text(encoding="utf-8")
    assert "_protocol_write(response)" in bridge
    assert "print(" not in bridge
    assert "sys.stderr.write" in bridge
    assert "str(exc)" not in bridge[bridge.index("async def run"):]


def test_ui_recovers_from_bridge_exit_and_timeout():
    for required in ("runRecoverable", "onFinally: () => { busy=false; render(); }", "Tentar novamente", "Copiar diagnóstico",
                     "bridge_timeout", "lastFailedMessage"):
        assert required in UI
    assert "errorCode = \"bridge_unavailable\"" in HOST
    assert "_bridge = null" in HOST


def test_packaged_bridge_smoke_is_part_of_build():
    assert "smoke_packaged_bridge.py" in BUILD
    assert "0.4.4-alpha" in UI
