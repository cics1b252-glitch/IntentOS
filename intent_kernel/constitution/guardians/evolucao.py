"""Evolução Guardian — Pillar IV.

Protects: System evolution.
Ensures: System learns, versions, refactors, improves. Never blocks — only observes.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


class EvolucaoGuardian:
    """Protects Pillar IV: Evolution.

    Observes CORRECTION, PATTERN, and DECISION signals.
    NEVER blocks — only generates evolution signals.
    """

    def __init__(self):
        self._signals: list[dict] = []

    @property
    def name(self) -> str:
        return "evolucao"

    @property
    def description(self) -> str:
        return "Evolution — system never stops improving."

    @property
    def principle(self) -> str:
        return "O Intent OS nunca está 'pronto'. Ele aprende, versiona, refatora e melhora."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        event_type = self._get_type(event)
        event_id = event.get("id", "unknown")
        confidence = self._get_confidence(event)
        score_value = self._get_score_value(event)

        now_iso = __import__("datetime").datetime.now(timezone.utc).isoformat()

        if event_type == "CORRECTION":
            self._signals.append({
                "keId": event_id,
                "signal": "CORRECTION detected — consider updating related KC entries.",
                "timestamp": now_iso,
            })

        if event_type == "PATTERN" and confidence >= 0.7:
            self._signals.append({
                "keId": event_id,
                "signal": "High-confidence PATTERN — consider updating user profile.",
                "timestamp": now_iso,
            })

        if event_type == "DECISION" and score_value >= 80:
            self._signals.append({
                "keId": event_id,
                "signal": f"High-impact DECISION (score {score_value}).",
                "timestamp": now_iso,
            })

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def get_signals(self) -> list[dict]:
        return list(self._signals)

    def clear_signals(self) -> None:
        self._signals.clear()

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "signals_observed": len(self._signals),
            "never_blocks": True,
        }

    def _get_type(self, event: dict[str, Any]) -> str:
        return event.get("type", "FACT")

    def _get_confidence(self, event: dict[str, Any]) -> float:
        metadata = event.get("metadata", {})
        if isinstance(metadata, dict):
            return metadata.get("confidence", 1.0)
        return 1.0

    def _get_score_value(self, event: dict[str, Any]) -> float:
        score = event.get("score", {})
        if isinstance(score, dict):
            return score.get("value", 0.0)
        return 0.0
