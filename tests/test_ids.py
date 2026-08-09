"""Test: Intent Design System (IDS)."""

import pytest
from intent_kernel.ids import IntentDesignSystem, IDSToken


@pytest.fixture
def ids():
    return IntentDesignSystem()


def test_version(ids):
    assert ids.version == "1.0.0"


def test_tokens_exist(ids):
    tokens = ids.get_tokens()
    assert "color-primary" in tokens
    assert "font-heading" in tokens
    assert "space-md" in tokens
    assert "animation-normal" in tokens


def test_css_variables(ids):
    css = ids.get_css_variables()
    assert ":root {" in css
    assert "--ids-color-primary" in css
    assert "--ids-font-heading" in css
    assert css.endswith("}")


def test_components(ids):
    assert len(ids.components) >= 6
    names = [c["name"] for c in ids.components]
    assert "Card" in names
    assert "Button" in names


def test_get_component(ids):
    card = ids.get_component_spec("Card")
    assert card is not None
    assert card["token"] == "radius-md"


def test_get_component_not_found(ids):
    assert ids.get_component_spec("Nonexistent") is None


def test_token_dataclass():
    t = IDSToken("test", "#000", "color")
    assert t.name == "test"
    assert t.value == "#000"
    assert t.category == "color"
