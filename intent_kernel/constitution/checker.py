"""Constitution Checks — 4 pillar checks per RFC-0001.

These are the operational checks that the Constitution runs against
every Knowledge Event before it enters the scoring pipeline.

Based on TS canonical: src/constitution/index.ts
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Verdict types
# ---------------------------------------------------------------------------

@dataclass
class ConstitutionCheckResult:
    """Result of a single pillar check."""
    check_type: str           # 'privacy' | 'validity' | 'retention' | 'evolution'
    decision: str             # 'allowed' | 'blocked' | 'flagged'
    reason: str


@dataclass
class ConstitutionVerdict:
    """Final verdict after resolving all pillar checks."""
    decision: str             # 'allowed' | 'blocked' | 'flagged'
    reason: str
    applies_to: list[str]     # list of check_types that triggered


# ---------------------------------------------------------------------------
# Sensitive data patterns — Soberania pillar
# ---------------------------------------------------------------------------

DECLARATION_PATTERNS: dict[str, list[re.Pattern]] = {
    "senha": [
        re.compile(r"minha\s+senha\s+(é|e|eh|=|:)", re.IGNORECASE),
        re.compile(r"senha[:=]\s*", re.IGNORECASE),
        re.compile(r"password[:=]\s*", re.IGNORECASE),
    ],
    "cpf": [
        re.compile(r"meu\s+cpf\s+(é|e|eh|=|:)", re.IGNORECASE),
        re.compile(r"cpf[:=]\s*", re.IGNORECASE),
        re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}"),
    ],
    "cnpj": [
        re.compile(r"cnpj[:=]\s*", re.IGNORECASE),
        re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"),
    ],
    "credit_card": [
        re.compile(r"cart[aã]o\s+(de\s+crédito\s+)?(é|e|eh|=|:)", re.IGNORECASE),
    ],
}

DEFAULT_SENSITIVE_KEYWORDS = [
    "senha", "password", "token", "api_key", "secret",
    "cpf", "cnpj", "credit_card", "cartão",
]


# ---------------------------------------------------------------------------
# Constitution Checker
# ---------------------------------------------------------------------------

class ConstitutionChecker:
    """Runs 4 pillar checks against Knowledge Events.

    Checks run in order:
    1. checkSoberania — privacy/sensitive data
    2. checkVerdade — inference confidence validation
    3. checkContinuidade — EPHEMERAL ≠ CONSTITUTIONAL
    4. checkEvolucao — observe signals, never block

    Resolution: blocked > flagged > allowed
    """

    def __init__(
        self,
        sensitive_keywords: list[str] | None = None,
        score_protection_threshold: float = 70.0,
    ):
        self.sensitive_keywords = sensitive_keywords or DEFAULT_SENSITIVE_KEYWORDS
        self.score_protection_threshold = score_protection_threshold
        self.evolution_signals: list[dict] = []

    def evaluate(self, event: dict[str, Any]) -> ConstitutionVerdict:
        """Run all 4 pillar checks and resolve.

        Args:
            event: KnowledgeEvent as dict (with content, type, metadata, score, level fields)

        Returns:
            ConstitutionVerdict with decision and reason.
        """
        checks = [
            self.check_soberania(event),
            self.check_verdade(event),
            self.check_continuidade(event),
            self.check_evolucao(event),
        ]
        return self._resolve(checks)

    def get_evolution_signals(self) -> list[dict]:
        """Get accumulated evolution signals."""
        return list(self.evolution_signals)

    def clear_evolution_signals(self) -> None:
        """Clear evolution signals."""
        self.evolution_signals.clear()

    # -------------------------------------------------------------------
    # Pillar I: Soberania — declaration vs mention
    # -------------------------------------------------------------------

    def check_soberania(self, event: dict[str, Any]) -> ConstitutionCheckResult:
        """Detect sensitive data declarations.

        Distinguishes "minha senha é X" (flag) from "preciso mudar minha senha" (allow).
        """
        raw = self._get_raw(event)
        lower = raw.lower()

        for keyword in self.sensitive_keywords:
            if keyword.lower() not in lower:
                continue

            # Check if there's a specific declaration pattern
            patterns = DECLARATION_PATTERNS.get(keyword)
            if patterns:
                for pattern in patterns:
                    if pattern.search(raw):
                        return ConstitutionCheckResult(
                            check_type="privacy",
                            decision="flagged",
                            reason=f'Sensitive declaration detected (keyword: "{keyword}").',
                        )
                continue  # keyword found but no declaration pattern → allow

            # Generic assignment detection
            has_assignment = re.search(r"[:=]\s*\S", raw) or re.search(r"\bé\b\s+\S+", raw, re.IGNORECASE)
            if has_assignment:
                return ConstitutionCheckResult(
                    check_type="privacy",
                    decision="flagged",
                    reason=f'Content contains sensitive keyword "{keyword}" in assignment context.',
                )

        return ConstitutionCheckResult(check_type="privacy", decision="allowed", reason="OK")

    # -------------------------------------------------------------------
    # Pillar II: Verdade — DECISION block before general flagged
    # -------------------------------------------------------------------

    def check_verdade(self, event: dict[str, Any]) -> ConstitutionCheckResult:
        """Validate inference confidence.

        Rules (in order — RFC specifies this order):
        1. DECISION + source=inference + confidence < 0.7 → BLOCKED
        2. source=inference + confidence < 0.5 → FLAGGED
        3. Otherwise → ALLOWED
        """
        source = self._get_source(event)
        event_type = self._get_type(event)
        confidence = self._get_confidence(event)

        # Rule 1: DECISION with low confidence inference → blocked
        if source == "inference" and event_type == "DECISION" and confidence < 0.7:
            return ConstitutionCheckResult(
                check_type="validity",
                decision="blocked",
                reason="System conclusions must have high confidence (≥0.7).",
            )

        # Rule 2: Low confidence inference → flagged
        if source == "inference" and confidence < 0.5:
            return ConstitutionCheckResult(
                check_type="validity",
                decision="flagged",
                reason=f'Inference with low confidence ({confidence}). Mark as "Estimativa".',
            )

        return ConstitutionCheckResult(check_type="validity", decision="allowed", reason="OK")

    # -------------------------------------------------------------------
    # Pillar III: Continuidade — EPHEMERAL ≠ CONSTITUTIONAL
    # -------------------------------------------------------------------

    def check_continuidade(self, event: dict[str, Any]) -> ConstitutionCheckResult:
        """Prevent EPHEMERAL events from becoming CONSTITUTIONAL."""
        event_type = self._get_type(event)
        level = self._get_level(event)

        if event_type == "EPHEMERAL" and level == "CONSTITUTIONAL":
            return ConstitutionCheckResult(
                check_type="retention",
                decision="blocked",
                reason="EPHEMERAL events cannot be CONSTITUTIONAL.",
            )

        return ConstitutionCheckResult(check_type="retention", decision="allowed", reason="OK")

    # -------------------------------------------------------------------
    # Pillar IV: Evolução — observe, never block
    # -------------------------------------------------------------------

    def check_evolucao(self, event: dict[str, Any]) -> ConstitutionCheckResult:
        """Observe evolution signals. Never blocks — only observes."""
        event_type = self._get_type(event)
        event_id = self._get_id(event)
        confidence = self._get_confidence(event)
        score_value = self._get_score_value(event)

        now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

        if event_type == "CORRECTION":
            self.evolution_signals.append({
                "keId": event_id,
                "signal": "CORRECTION detected — consider updating related KC entries.",
                "timestamp": now_iso,
            })

        if event_type == "PATTERN" and confidence >= 0.7:
            self.evolution_signals.append({
                "keId": event_id,
                "signal": "High-confidence PATTERN — consider updating user profile.",
                "timestamp": now_iso,
            })

        if event_type == "DECISION" and score_value >= 80:
            self.evolution_signals.append({
                "keId": event_id,
                "signal": f"High-impact DECISION (score {score_value}).",
                "timestamp": now_iso,
            })

        # Evolution pillar NEVER blocks
        return ConstitutionCheckResult(check_type="evolution", decision="allowed", reason="OK")

    # -------------------------------------------------------------------
    # Helpers — extract fields from event dict
    # -------------------------------------------------------------------

    def _get_raw(self, event: dict[str, Any]) -> str:
        content = event.get("content", {})
        if isinstance(content, dict):
            return content.get("raw", content.get("text", str(content)))
        return str(content)

    def _get_source(self, event: dict[str, Any]) -> str:
        content = event.get("content", {})
        if isinstance(content, dict):
            return content.get("source", "conversation")
        return "conversation"

    def _get_type(self, event: dict[str, Any]) -> str:
        return event.get("type", "FACT")

    def _get_level(self, event: dict[str, Any]) -> str:
        # Check both 'level' and 'lifecycle.currentLevel' (TS format)
        level = event.get("level")
        if level:
            return level
        lifecycle = event.get("lifecycle", {})
        if isinstance(lifecycle, dict):
            return lifecycle.get("currentLevel", "TRANSIENT")
        return "TRANSIENT"

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

    def _get_id(self, event: dict[str, Any]) -> str:
        return event.get("id", "unknown")

    # -------------------------------------------------------------------
    # Resolution — blocked > flagged > allowed
    # -------------------------------------------------------------------

    def _resolve(self, checks: list[ConstitutionCheckResult]) -> ConstitutionVerdict:
        """Resolve multiple check results into a final verdict.

        Priority: blocked > flagged > allowed
        """
        blocked = [c for c in checks if c.decision == "blocked"]
        flagged = [c for c in checks if c.decision == "flagged"]

        if blocked:
            return ConstitutionVerdict(
                decision="blocked",
                reason=" | ".join(c.reason for c in blocked),
                applies_to=[c.check_type for c in blocked],
            )

        if flagged:
            return ConstitutionVerdict(
                decision="flagged",
                reason=" | ".join(c.reason for c in flagged),
                applies_to=[c.check_type for c in flagged],
            )

        return ConstitutionVerdict(
            decision="allowed",
            reason="All constitutional checks passed.",
            applies_to=[],
        )
