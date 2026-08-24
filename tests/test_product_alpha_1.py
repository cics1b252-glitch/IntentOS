"""Product Alpha 1 integration and safety contracts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from product_bridge import ProductBridge

ROOT = Path(__file__).parents[1]
HOST = (ROOT / "windows" / "host" / "ProductController.cs").read_text(encoding="utf-8")
UI = (ROOT / "ui" / "shell" / "product" / "product.js").read_text(encoding="utf-8")


def test_first_run_defaults_to_incomplete_portuguese_real_mode():
    assert 'OnboardingComplete { get; set; }' in HOST
    assert 'Mode { get; set; } = "real"' in HOST
    assert 'Locale { get; set; } = "pt-BR"' in HOST
    assert "Bem-vindo ao Intent OS" in UI


def test_onboarding_only_completes_on_explicit_finish():
    assert '"complete_onboarding" => CompleteOnboarding(root)' in HOST
    assert "_state.OnboardingComplete = true" in HOST
    assert "data-action=\"finish\"" in UI


def test_demo_is_explicit_separate_and_can_exit():
    assert '"explore_demo" => EnterDemo()' in HOST
    assert '"exit_demo" => ExitDemo()' in HOST
    assert "Modo demonstração — nenhuma IA real está conectada" in UI
    assert "Sair da demonstração" in UI


def test_openai_and_gemini_are_real_and_future_connectors_are_honest():
    assert 'provider is not ("openai" or "gemini")' in HOST
    assert "Google Gemini" in UI and "Chave Gemini" in UI
    assert "OneDrive" in UI and "Google Drive" in UI
    assert "senha do seu e-mail" in UI


def test_provider_secret_is_dpapi_protected_and_never_logged():
    assert "ProtectedData.Protect" in HOST
    assert "DataProtectionScope.CurrentUser" in HOST
    assert "File.WriteAllBytes(SecretFile(provider), protectedBytes)" in HOST
    assert "apiKey" not in (ROOT / "windows" / "host" / "Program.cs").read_text(encoding="utf-8")
    assert "AppLog.Write" not in "\n".join(line for line in HOST.splitlines() if "apiKey" in line or "UnprotectKey" in line)


def test_conversation_requires_provider_in_real_mode_and_persists_history():
    assert "Conecte um Provider de IA" in HOST
    assert "_state.History.Add" in HOST
    assert "SaveState();" in HOST
    assert '"clear_history" => ClearHistory()' in HOST


def test_ui_uses_bridge_not_concrete_kernel_or_provider():
    assert "chrome.webview.postMessage" in UI
    assert "intent_kernel" not in UI
    assert "OpenAIProvider" not in UI
    assert "ApplicationFactory" not in UI


def test_bridge_uses_single_canonical_composition_and_no_network_listener():
    bridge = (ROOT / "product_bridge.py").read_text(encoding="utf-8")
    assert bridge.count("ApplicationFactory(") == 1
    assert "KernelBuilder()" in bridge
    assert "conversation_content_service.process" in bridge
    assert "listen(" not in bridge and "localhost" not in bridge and "FastAPI" not in bridge


def test_no_simulated_running_or_fixture_states_in_real_product_ui():
    for misleading in ("Queued", "Waiting", "Running", "fixtures"):
        assert misleading not in UI
    assert "Processando sua solicitação" in UI
    assert "busy" in UI


def test_diagnostics_exclude_secret_and_include_required_status():
    for term in ("version", "installPath", "dataPath", "kernel", "provider", "bridge", "mode"):
        assert term in HOST
    diagnostic_expression = HOST[HOST.index("private object Diagnostics"):HOST.index("private object PublicState")]
    assert "secret" not in diagnostic_expression.lower()
    assert "apiKey" not in diagnostic_expression


def test_product_version_is_incremented_consistently():
    version = json.loads((ROOT / "windows" / "version.json").read_text(encoding="utf-8"))["version"]
    assert version == "0.4.4-alpha"
    assert version in (ROOT / "windows" / "host" / "Program.cs").read_text(encoding="utf-8")
    assert version in (ROOT / "windows" / "installer" / "Program.cs").read_text(encoding="utf-8")


def test_canonical_bridge_can_start_offline(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    status = asyncio.run(bridge.dispatch({"action": "status"}))
    assert status["ok"] is True
    assert status["kernel"] == "pronto"
    assert status["providers"] == ["mock"]

