"""Module base — interface for plugins."""

from __future__ import annotations

from typing import Any

from intent_kernel.types import Domain, IntentInput


class Module:
    """Base class for Intent OS modules.

    Subclass this and implement execute() for domain-specific modules.
    """

    name: str = "base"
    version: str = "0.1.0"
    triggers: list[str] = []
    domains: list[Domain] = []
    required_providers: list[str] = []

    async def execute(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Execute the module's logic. Override in subclasses."""
        return {
            "text": f"[{self.name}] Module executed but no logic implemented.",
            "confidence": 0.3,
        }

    def validate_config(self, config: dict) -> bool:
        """Validate that config doesn't violate the Constitution."""
        return True
