"""Architecture guards for the executable Intent Design System."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
IDS = ROOT / "ui" / "ids"


def test_ids_has_required_presentation_structure():
    required = {
        "tokens", "theme", "styles", "motion", "typography", "icons",
        "layout", "components", "showcase", "accessibility", "tests",
    }
    assert required <= {path.name for path in IDS.iterdir() if path.is_dir()}


def test_ids_has_no_architecture_dependencies():
    forbidden = (
        "intent_kernel", "Kernel", "Constitution", "KnowledgeManager",
        "MissionEngine", "ProviderManager", "AtlasCoreApp", "LogosCoreApp",
        "OEMStudioCoreApp",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in IDS.rglob("*")
        if path.suffix in {".js", ".css", ".html"}
    )
    for symbol in forbidden:
        assert symbol not in source


def test_components_do_not_embed_literal_colors():
    css = (IDS / "components" / "components.css").read_text(encoding="utf-8")
    assert "#" not in css
    assert "rgb(" not in css
    assert "hsl(" not in css


def test_showcase_is_internal_and_not_product_ui():
    page = (IDS / "showcase" / "index.html").read_text(encoding="utf-8")
    assert "Ferramenta interna de validação" in page
    assert "Dashboard" not in page
    assert "Cognitive Shell" not in page
