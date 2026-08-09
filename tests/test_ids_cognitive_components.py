from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
COGNITIVE = ROOT / "ui" / "ids" / "cognitive"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cognitive_catalog_structure_is_complete():
    expected = {
        "cognitive-pulse", "mission-card", "context-card", "capability-badge",
        "decision-timeline", "confidence-indicator", "execution-indicator",
        "provenance-card", "agent-status", "knowledge-relationship-card",
    }
    assert expected == {path.name for path in COGNITIVE.iterdir() if path.is_dir()}
    assert all((COGNITIVE / name / "index.js").is_file() for name in expected)


def test_cognitive_layer_has_no_architectural_dependency():
    source = "\n".join(_text(path) for path in COGNITIVE.rglob("*.js"))
    forbidden = (
        "intent_kernel", "mission_engine", "core_apps", "provider_manager",
        "knowledge_manager", "constitution_engine",
    )
    assert not any(term in source.lower() for term in forbidden)


def test_cognitive_css_uses_ids_tokens_without_literal_colors():
    css = _text(COGNITIVE / "cognitive.css")
    assert "var(--ids-" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\brgba?\s*\(", css)
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (forced-colors: active)" in css


def test_showcase_and_design_documents_cover_cognitive_components():
    showcase = _text(ROOT / "ui" / "ids" / "showcase" / "index.html")
    docs = [
        ROOT / "docs" / "design" / "IDS-006_COGNITIVE_INTERACTION.md",
        ROOT / "docs" / "design" / "IDS-007_COGNITIVE_COMPONENTS.md",
    ]
    assert all(path.is_file() for path in docs)
    assert "Cognitive Components" in showcase
    for tag in (
        "ids-cognitive-pulse", "ids-mission-card", "ids-context-card",
        "ids-capability-badge", "ids-decision-timeline",
        "ids-confidence-indicator", "ids-execution-indicator",
        "ids-provenance-card", "ids-agent-status",
        "ids-knowledge-relationship-card",
    ):
        assert tag in showcase


def test_public_state_contracts_include_required_states():
    contracts = _text(COGNITIVE / "contracts.js")
    for required in (
        "waiting-for-provider", "partially-completed", "user-supplied",
        "external-effect-requested", "superseded-by", "restricted",
    ):
        assert required in contracts


def test_listener_lifecycle_and_framework_independence_are_explicit():
    elements = _text(COGNITIVE / "elements.js")
    assert 'addEventListener("click", this.#onClick)' in elements
    assert 'removeEventListener("click", this.#onClick)' in elements
    assert 'addEventListener("keydown", this.#onKeydown)' in elements
    assert 'removeEventListener("keydown", this.#onKeydown)' in elements
    assert "React" not in elements
    assert "Vue" not in elements
