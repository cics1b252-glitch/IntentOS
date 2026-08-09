"""Continuidade Guardian — Pillar III.

Protects: Knowledge continuity.
Ensures: No important knowledge dies in a conversation.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


class ContinuidadeGuardian:
    """Protects Pillar III: Continuity.

    Prevents EPHEMERAL events from becoming CONSTITUTIONAL.
    Ensures knowledge survives between sessions.
    """

    def __init__(self):
        self._blocked_count = 0

    @property
    def name(self) -> str:
        return "continuidade"

    @property
    def description(self) -> str:
        return "Continuity — no important knowledge dies in a conversation."

    @property
    def principle(self) -> str:
        return "Nenhum conhecimento importante pode morrer em uma conversa."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        event_type = self._get_type(event)
        level = self._get_level(event)

        if event_type == "EPHEMERAL" and level == "CONSTITUTIONAL":
            self._blocked_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="blocked",
                reason="EPHEMERAL events cannot be CONSTITUTIONAL.",
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "blocked": self._blocked_count,
        }

    def _get_type(self, event: dict[str, Any]) -> str:
        return event.get("type", "FACT")

    def _get_level(self, event: dict[str, Any]) -> str:
        level = event.get("level")
        if level:
            return level
        lifecycle = event.get("lifecycle", {})
        if isinstance(lifecycle, dict):
            return lifecycle.get("currentLevel", "TRANSIENT")
        return "TRANSIENT"
