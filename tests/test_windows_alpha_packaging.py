"""Contract tests for the Studio 2.5 Windows package."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
WINDOWS = ROOT / "windows"


def test_version_metadata_is_consistent():
    version = json.loads((WINDOWS / "version.json").read_text(encoding="utf-8"))
    assert version["version"] == "0.4.4-alpha"
    assert version["channel"] == "alpha"
    assert version["dataPolicy"] == "preserve-by-default"
    assert version["version"] in (WINDOWS / "host" / "Program.cs").read_text(encoding="utf-8")
    assert version["version"] in (WINDOWS / "installer" / "Program.cs").read_text(encoding="utf-8")


def test_host_uses_local_webview_without_server_or_browser():
    source = (WINDOWS / "host" / "Program.cs").read_text(encoding="utf-8")
    assert "WebView2" in source
    assert "SetVirtualHostNameToFolderMapping" in source
    assert "https://intent.local/shell/index.html" in source
    assert "HttpListener" not in source
    assert "localhost" not in source
    assert "webbrowser" not in source.lower()


def test_program_and_data_are_separated():
    host = (WINDOWS / "host" / "Program.cs").read_text(encoding="utf-8")
    installer = (WINDOWS / "installer" / "Program.cs").read_text(encoding="utf-8")
    assert '"Programs", "IntentOS"' in installer
    assert '"IntentOS", "Data"' in host
    assert '"IntentOS", "Data"' in installer
    for directory in ("preferences", "logs", "cache", "future-kc", "backups", "updates"):
        assert f'"{directory}"' in installer


def test_installer_contract_covers_shortcuts_registry_and_data_choice():
    source = (WINDOWS / "installer" / "Program.cs").read_text(encoding="utf-8")
    assert "CurrentVersion\\Uninstall\\IntentOS" in source
    assert "SpecialFolder.StartMenu" in source
    assert "SpecialFolder.DesktopDirectory" in source
    assert "preservá-los" in source
    assert "Registry.CurrentUser" in source
    assert "WindowsPrincipal" not in source


def test_host_handles_spaces_and_missing_resources_by_api_choice():
    source = (WINDOWS / "host" / "Program.cs").read_text(encoding="utf-8")
    assert "Path.Combine" in source
    assert "Path.GetFullPath" in source
    assert "FileNotFoundException" in source
    assert "ShellEntry" in source


def test_build_is_self_contained_and_does_not_bundle_python():
    build = (WINDOWS / "build.ps1").read_text(encoding="utf-8")
    assert "--self-contained true" in build
    assert "PublishSingleFile=true" in build
    assert "IntentOS.Bridge" in (ROOT / "product_bridge.spec").read_text(encoding="utf-8")
    assert "product_bridge.spec" in build


def test_shell_declares_local_demo_only_for_windows_host():
    shell = (ROOT / "ui" / "shell" / "index.html").read_text(encoding="utf-8")
    assert "Versão demonstrativa local" in shell
    host_script = (ROOT / "ui" / "shell" / "windows-host.js").read_text(encoding="utf-8")
    assert "host') === 'windows-alpha'" in host_script
    assert "Content-Security-Policy" in shell


def test_no_kernel_or_domain_is_packaged():
    build = (WINDOWS / "build.ps1").read_text(encoding="utf-8")
    copied = [line.strip() for line in build.splitlines() if line.strip().startswith("Copy-Item")]
    assert any("'ui'" in line for line in copied)
    assert not any("intent_kernel" in line or "tests" in line for line in copied)
