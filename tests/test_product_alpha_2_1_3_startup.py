"""Product Alpha 2.1.3 startup, recovery, and shutdown contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = (ROOT / "windows/host/Program.cs").read_text(encoding="utf-8")
CONTROLLER = (ROOT / "windows/host/ProductController.cs").read_text(encoding="utf-8")
UI = (ROOT / "ui/shell/product/product.js").read_text(encoding="utf-8")


def test_startup_has_explicit_states_and_native_surface():
    for state in (
        "Launching", "LoadingHost", "LoadingWebView", "LoadingShell",
        "StartingBridge", "Handshaking", "Ready", "Degraded", "Failed",
        "ShuttingDown",
    ):
        assert state in HOST
    for action in ("Tentar novamente", "Modo seguro", "Limpar cache", "Abrir diagnóstico", "Fechar"):
        assert action in HOST
    assert "BuildStartupSurface" in HOST


def test_ui_thread_has_no_synchronous_bridge_waits():
    forbidden = ("GetAwaiter().GetResult()", ".Result", ".Wait(")
    for value in forbidden:
        assert value not in HOST
        assert value not in CONTROLLER
    assert "KernelBridge.StartAsync" in CONTROLLER
    assert "await _product.InitializeAsync" in HOST


def test_startup_timeouts_and_watchdog_are_bounded():
    for timeout in (
        "WebViewEnvironmentTimeout", "WebViewInitializationTimeout",
        "ShellNavigationTimeout", "TotalStartupTimeout",
    ):
        assert timeout in HOST
    assert "WaitAsync" in HOST
    assert "CancelAfter(duration)" in CONTROLLER


def test_bridge_is_started_only_after_shell_navigation():
    shell = HOST.index('AppLog.Event("shell_loaded")')
    bridge = HOST.index("await _product.InitializeAsync")
    assert shell < bridge
    assert "TryStartBridge();" not in CONTROLLER


def test_shutdown_is_cancelable_and_force_stops_without_waiting():
    assert "FormClosing += OnFormClosing" in HOST
    assert "_startupCancellation.Cancel()" in HOST
    assert "_product.ForceStop()" in HOST
    assert "_process.Kill(true)" in CONTROLLER
    assert "_stderrPump.Wait" not in CONTROLLER
    assert 'AppLog.Event("shutdown_started")' in HOST
    assert 'AppLog.Event("shutdown_completed")' in HOST


def test_safe_mode_skips_restore_and_provider_startup():
    assert '_state = safeMode ? new ProductState { Mode = "demo" } : LoadState()' in CONTROLLER
    assert "if (_safeMode)" in CONTROLLER
    assert 'safeMode={_safeMode.ToString().ToLowerInvariant()}' in HOST
    assert "state.mode === 'demo'" in UI


def test_corrupt_state_is_isolated_and_defaults_are_used():
    assert "product.invalid-" in CONTROLLER
    assert "File.Move(_stateFile, backup, true)" in CONTROLLER
    assert "return new();" in CONTROLLER


def test_webview_failure_and_cache_recovery_are_exposed():
    assert "ProcessFailed" in HOST
    assert "ClearCacheAndRetryAsync" in HOST
    assert "webview_cache_cleared" in HOST
    assert "StartsWith(data, StringComparison.OrdinalIgnoreCase)" in HOST


def test_required_startup_events_are_logged():
    for event in (
        "host_started", "webview_environment_started", "webview_ready",
        "shell_navigation_started", "shell_loaded", "bridge_process_started",
        "bridge_ready", "kernel_ready", "session_restored", "app_ready",
        "shutdown_started", "shutdown_completed",
    ):
        assert event in HOST + CONTROLLER


def test_shell_recovers_from_async_startup_state_changes():
    assert "startup_state" in UI
    assert "busy = false" in UI
    assert "Tentar novamente" in UI
    assert "0.4.4-alpha" in UI
