"""Constitution models — Pillars, Constraints, and the Constitution itself."""

from __future__ import annotations

from dataclasses import dataclass, field

from intent_kernel.types import Severity


@dataclass
class Constraint:
    """A single enforceable rule."""
    id: str
    rule: str
    enforced_by: str
    severity: Severity = Severity.BLOCK

    def applies_to(self, action: object) -> bool:
        """Check if this constraint applies to the given action.
        Default: applies to everything. Override for specific filtering."""
        return True


@dataclass
class Pillar:
    """A foundational pillar of the Constitution."""
    id: str
    name: str
    description: str
    constraints: list[Constraint] = field(default_factory=list)


@dataclass
class Constitution:
    """The Living Constitution — first entity loaded by the Kernel.

    Validates all system decisions against immutable principles.
    """
    version: str = "1.0.0"
    supreme_principle: str = (
        "O Intent OS existe para ampliar a capacidade cognitiva "
        "do usuário, nunca para substituí-la."
    )
    pillars: list[Pillar] = field(default_factory=list)

    @property
    def all_constraints(self) -> list[Constraint]:
        """Flatten all constraints from all pillars."""
        result = []
        for pillar in self.pillars:
            result.extend(pillar.constraints)
        return result

    def validate(self, action: object) -> _ConstitutionVerdict:
        """Validate an action against all constraints.

        Returns a verdict: allowed or blocked with reason.
        """
        from intent_kernel.types import Action, ConstitutionVerdict

        for constraint in self.all_constraints:
            if not constraint.applies_to(action):
                continue
            # In Sprint 0, constraints are validated by the components
            # that enforce them. The Constitution just checks they exist
            # and are well-formed.
            if not constraint.id or not constraint.rule:
                return ConstitutionVerdict(
                    allowed=False,
                    violated_constraint=constraint.id or "malformed",
                    reason=f"Constraint '{constraint.id}' is malformed",
                )

        return ConstitutionVerdict(allowed=True)

    def add_constraint(self, pillar_id: str, constraint: Constraint) -> bool:
        """Add a constraint to a pillar. Returns True if found."""
        for pillar in self.pillars:
            if pillar.id == pillar_id:
                pillar.constraints.append(constraint)
                return True
        return False

    def add_pillar(self, pillar: Pillar) -> None:
        """Add a new pillar (Evolution — append-only)."""
        self.pillars.append(pillar)

    def export(self) -> dict:
        """Export Constitution as a dictionary."""
        return {
            "version": self.version,
            "supreme_principle": self.supreme_principle,
            "pillars": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "constraints": [
                        {
                            "id": c.id,
                            "rule": c.rule,
                            "enforced_by": c.enforced_by,
                            "severity": c.severity.value,
                        }
                        for c in p.constraints
                    ],
                }
                for p in self.pillars
            ],
        }
