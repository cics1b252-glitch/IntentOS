"""Verdade Guardian — Pillar II.

Protects: Truth — system never invents.
Ensures: Confidence classification, epistemic honesty.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


class VerdadeGuardian:
    """Protects Pillar II: Truth.

    Blocks DECISION with low-confidence inference.
    Flags low-confidence inferences for review.
    """

    def __init__(self):
        self._blocked_count = 0
        self._flagged_count = 0

    @property
    def name(self) -> str:
        return "verdade"

    @property
    def description(self) -> str:
        return "Truth — system never invents. When it doesn't know: 'Não sei'."

    @property
    def principle(self) -> str:
        return "O sistema nunca inventa. Quando não sabe: 'Não sei'. Quando estima: 'Estimativa'."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate event against Verdade principle."""
        source = self._get_source(event)
        event_type = self._get_type(event)
        confidence = self._get_confidence(event)

        # DECISION + inference + confidence < 0.7 → blocked
        if source == "inference" and event_type == "DECISION" and confidence < 0.7:
            self._blocked_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="blocked",
                reason="System conclusions must have high confidence (≥0.7).",
            )

        # inference + confidence < 0.5 → flagged
        if source == "inference" and confidence < 0.5:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason=f'Inference with low confidence ({confidence}). Mark as "Estimativa".',
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "total_validated": self._blocked_count + self._flagged_count,
            "blocked": self._blocked_count,
            "flagged": self._flagged_count,
        }

    def _get_source(self, event: dict[str, Any]) -> str:
        content = event.get("content", {})
        if isinstance(content, dict):
            return content.get("source", "conversation")
        return "conversation"

    def _get_type(self, event: dict[str, Any]) -> str:
        return event.get("type", "FACT")

    def _get_confidence(self, event: dict[str, Any]) -> float:
        metadata = event.get("metadata", {})
        if isinstance(metadata, dict):
            return metadata.get("confidence", 1.0)
        return 1.0
