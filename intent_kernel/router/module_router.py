"""ModuleRouter — detects domain and loads the right module."""

from __future__ import annotations

from typing import Any

from intent_kernel.types import Domain, IntentInput


class ModuleRouter:
    """Routes intents to the appropriate module based on domain.

    Modules register themselves with triggers and domains.
    The Router matches intent text against triggers to find
    the best module.
    """

    def __init__(self, *, telemetry: Any = None):
        self._modules: dict[str, Any] = {}  # name → module
        self._domain_map: dict[Domain, str] = {}  # domain → module name
        self._trigger_map: dict[str, str] = {}  # trigger word → module name
        self._telemetry = telemetry

    def register(self, module: Any) -> None:
        """Register a module with the router."""
        self._modules[module.name] = module

        for domain in getattr(module, "domains", []):
            self._domain_map[domain] = module.name

        for trigger in getattr(module, "triggers", []):
            self._trigger_map[trigger.lower()] = module.name

    def route(self, intent: IntentInput) -> Any | None:
        """Find the best module for an intent.

        Priority:
        1. Domain match
        2. Trigger word match
        3. CORE module (fallback)
        """
        if self._telemetry is not None:
            self._telemetry.record_fallback(intent.domain.value)
            self._telemetry.record_legacy("ModuleRouter")

        # Try domain match first
        if intent.domain in self._domain_map:
            name = self._domain_map[intent.domain]
            return self._modules.get(name)

        # Try trigger match
        text_lower = intent.text.lower()
        for trigger, name in self._trigger_map.items():
            if trigger in text_lower:
                return self._modules.get(name)

        # Fallback to CORE
        return self._modules.get("core")

    def get_module(self, name: str) -> Any | None:
        """Get a module by name."""
        return self._modules.get(name)

    @property
    def registered_modules(self) -> list[str]:
        """List of registered module names."""
        return list(self._modules.keys())
