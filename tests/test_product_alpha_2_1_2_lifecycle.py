"""Product Alpha 2.1.2 bridge lifecycle and recovery contracts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from product_bridge import APP_VERSION, BRIDGE_VERSION, PROTOCOL_VERSION, ProductBridge, _health_payload

ROOT = Path(__file__).parents[1]
HOST = (ROOT / "windows" / "host" / "ProductController.cs").read_text(encoding="utf-8")
PROGRAM = (ROOT / "windows" / "host" / "Program.cs").read_text(encoding="utf-8")
INSTALLER = (ROOT / "windows" / "installer" / "Program.cs").read_text(encoding="utf-8")
UI = (ROOT / "ui" / "shell" / "product" / "product.js").read_text(encoding="utf-8")
BUILD = (ROOT / "windows" / "build.ps1").read_text(encoding="utf-8")


def test_ready_handshake_is_structured_and_versioned():
    ready = _health_payload(event="READY")
    assert ready == {
        "event": "READY", "protocol_version": "1.0", "app_version": "0.4.4-alpha",
        "bridge_version": "0.4.4-alpha", "kernel_status": "ready",
        "provider_manager_status": "ready", "timestamp": ready["timestamp"], "ready": True,
    }
    json.loads(json.dumps(ready))


def test_health_check_contains_only_safe_operational_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    result = asyncio.run(ProductBridge().dispatch({"action": "health"}))
    assert set(result) == {"ok", "protocol_version", "app_version", "bridge_version",
                           "kernel_status", "provider_manager_status", "timestamp", "ready"}
    assert result["ok"] and result["ready"]
    assert not ({"key", "prompt", "history", "response", "user"} & set(result))


def test_host_validates_ready_health_timeout_exit_and_invalid_json():
    for required in ("eventValue.GetString() != \"READY\"", "ValidateHealth", "ValidateVersions",
                     "TimeoutException", "EndOfStreamException", "InvalidDataException",
                     "_process.HasExited", "ReadDocumentAsync"):
        assert required in HOST
    assert 'Contains("\\\"ok\\\": true")' not in HOST


def test_all_canonical_lifecycle_states_and_single_restart_are_present():
    for state in ("not_started", "starting", "ready", "busy", "degraded", "restarting",
                  "unavailable", "stopped", "failed"):
        assert f'"{state}"' in HOST
    assert "RequestBridgeAsync" in HOST and "BridgeRecoveredException" in HOST
    assert "if (!replayAfterRestart)" in HOST
    assert "while" not in HOST[HOST.index("private async Task<JsonDocument> RequestBridgeAsync"):
                               HOST.index("private async Task<object> RestartBridgeForUser")]


def test_paths_working_directory_and_missing_executable_are_validated():
    for required in ("File.Exists(executable)", "FileNotFoundException", "WorkingDirectory = workingDirectory",
                     "Directory.Exists(workingDirectory)", "Directory.CreateDirectory(paths.DataRoot)"):
        assert required in HOST
    assert "Intent OS Unicode" in (ROOT / "tests" / "smoke_packaged_bridge.py").read_text(encoding="utf-8")


def test_ui_blocks_send_until_ready_and_offers_complete_recovery():
    assert "busy || !bridgeReady ? 'disabled'" in UI
    for label in ("Tentar novamente", "Reiniciar núcleo", "Copiar diagnóstico", "Abrir diagnóstico"):
        assert label in UI
    assert "Não foi possível iniciar o núcleo do Intent OS." in UI
    assert "onFinally: () => { busy=false; render(); }" in UI


def test_logs_are_separated_and_bridge_diagnostics_are_sanitized():
    assert '"host.log"' in PROGRAM and '"bridge.log"' in PROGRAM
    assert "WriteBridge" in PROGRAM and "WriteBridge" in HOST
    assert "apiKey" not in "\n".join(line for line in HOST.splitlines() if "AppLog." in line)
    assert "prompt" not in "\n".join(line.lower() for line in HOST.splitlines() if "AppLog." in line)


def test_update_replaces_old_binaries_and_preserves_user_data():
    assert "Directory.Delete(InstallRoot, true)" in INSTALLER
    assert "Directory.Move(staging, InstallRoot)" in INSTALLER
    assert '"IntentOS", "Data"' in INSTALLER
    assert "payloadVersion != Version" in INSTALLER
    assert "0.4.4-alpha" in INSTALLER


def test_build_executes_packaged_handshake_and_health_smoke():
    smoke = (ROOT / "tests" / "smoke_packaged_bridge.py").read_text(encoding="utf-8")
    assert "health-smoke" in smoke and 'startup["event"] == "READY"' in smoke
    assert "smoke_packaged_bridge.py" in BUILD
    assert APP_VERSION == BRIDGE_VERSION == "0.4.4-alpha" and PROTOCOL_VERSION == "1.0"
