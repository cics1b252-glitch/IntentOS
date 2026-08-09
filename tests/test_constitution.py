"""Test: Constitution validation."""

import pytest
from intent_kernel.constitution import create_default_constitution
from intent_kernel.types import Action


def test_constitution_loads():
    """Default Constitution loads correctly."""
    c = create_default_constitution()
    assert c.version == "1.0.0"
    assert len(c.pillars) == 4
    assert c.supreme_principle.startswith("O Intent OS")


def test_constitution_has_four_pillars():
    """Constitution has exactly 4 pillars."""
    c = create_default_constitution()
    pillar_ids = [p.id for p in c.pillars]
    assert "soberania" in pillar_ids
    assert "verdade" in pillar_ids
    assert "continuidade" in pillar_ids
    assert "evolucao" in pillar_ids


def test_constitution_constraints_exist():
    """Each pillar has at least one constraint."""
    c = create_default_constitution()
    for pillar in c.pillars:
        assert len(pillar.constraints) > 0, f"Pillar '{pillar.id}' has no constraints"


def test_constitution_validate_allowed():
    """Normal action is allowed."""
    c = create_default_constitution()
    action = Action(type="process", data="test")
    verdict = c.validate(action)
    assert verdict.allowed is True


def test_constitution_validate_malformed_constraint():
    """Malformed constraint is blocked."""
    from intent_kernel.constitution.models import Constitution, Pillar, Constraint
    from intent_kernel.types import Severity

    c = Constitution(
        pillars=[
            Pillar(
                id="test",
                name="Test",
                description="Test pillar",
                constraints=[
                    Constraint(
                        id="",  # malformed: empty id
                        rule="test rule",
                        enforced_by="test",
                        severity=Severity.BLOCK,
                    )
                ],
            )
        ]
    )
    action = Action(type="test")
    verdict = c.validate(action)
    assert verdict.allowed is False


def test_constitution_export():
    """Constitution can be exported to dict."""
    c = create_default_constitution()
    data = c.export()
    assert data["version"] == "1.0.0"
    assert len(data["pillars"]) == 4
    assert "constraints" in data["pillars"][0]


def test_constitution_add_constraint():
    """Can add a constraint to an existing pillar."""
    c = create_default_constitution()
    from intent_kernel.constitution.models import Constraint
    from intent_kernel.types import Severity

    new = Constraint(
        id="test_constraint",
        rule="Test rule",
        enforced_by="test",
        severity=Severity.WARN,
    )
    result = c.add_constraint("soberania", new)
    assert result is True
    assert len(c.pillars[0].constraints) == 3  # was 2, now 3


def test_constitution_add_pillar():
    """Can add a new pillar."""
    c = create_default_constitution()
    from intent_kernel.constitution.models import Pillar

    new = Pillar(id="new", name="New", description="New pillar")
    c.add_pillar(new)
    assert len(c.pillars) == 5
