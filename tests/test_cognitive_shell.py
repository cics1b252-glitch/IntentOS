from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
SHELL = ROOT / "ui" / "shell"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shell_host_and_modules_exist():
    assert (SHELL / "index.html").is_file()
    assert (SHELL / "bootstrap.js").is_file()
    assert (SHELL / "state.js").is_file()
    assert (SHELL / "router.js").is_file()
    for module in (
        "layout", "navigation", "mission-rail", "workspace", "context-panel",
        "activity-layer", "system-status", "fixtures",
    ):
        assert (SHELL / module).is_dir()


def test_shell_is_architecturally_isolated():
    source = "\n".join(text(path) for path in SHELL.rglob("*.js"))
    for forbidden in (
        "intent_kernel", "mission_engine", "provider_manager", "knowledge_manager",
        "constitution_engine", "core_apps",
    ):
        assert forbidden not in source.lower()
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_shell_css_uses_tokens_and_accessibility_media():
    css = text(SHELL / "layout" / "shell.css")
    assert "var(--ids-" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\brgba?\s*\(", css)
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (forced-colors: active)" in css
    assert "@media (max-width: 48rem)" in css


def test_host_has_skip_target_and_separate_showcase():
    host = text(SHELL / "index.html")
    assert 'id="intent-shell"' in host
    assert "../ids/styles/base.css" in host
    assert "./bootstrap.js" in host
    assert (ROOT / "ui" / "ids" / "showcase" / "index.html").is_file()


def test_shell_documentation_and_demo_labels_exist():
    assert (ROOT / "docs" / "design" / "IDS-008_COGNITIVE_SHELL.md").is_file()
    fixtures = text(SHELL / "fixtures" / "index.js")
    assert "demonstration" in fixtures.lower()
    assert "provideravailability" in fixtures.lower()
