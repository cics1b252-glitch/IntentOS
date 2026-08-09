"""Soberania Guardian — Pillar I.

Protects: User data sovereignty.
Ensures: User owns their data, memory, KC, and projects. Never the system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


# Sensitive data declaration patterns
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


class SoberaniaGuardian:
    """Protects Pillar I: User data sovereignty.

    Detects sensitive data declarations and flags them for protection.
    Distinguishes "minha senha é X" (flag) from "preciso mudar minha senha" (allow).
    """

    def __init__(self, sensitive_keywords: list[str] | None = None):
        self.sensitive_keywords = sensitive_keywords or DEFAULT_SENSITIVE_KEYWORDS
        self._blocked_count = 0
        self._flagged_count = 0

    @property
    def name(self) -> str:
        return "soberania"

    @property
    def description(self) -> str:
        return "User data sovereignty — user owns their data, memory, KC, and projects."

    @property
    def principle(self) -> str:
        return "O usuário é dono dos dados, da memória, da KC e dos projetos. Nunca o sistema."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate event against Soberania principle."""
        raw = self._get_raw(event)
        lower = raw.lower()

        for keyword in self.sensitive_keywords:
            if keyword.lower() not in lower:
                continue

            patterns = DECLARATION_PATTERNS.get(keyword)
            if patterns:
                for pattern in patterns:
                    if pattern.search(raw):
                        self._flagged_count += 1
                        return GuardianVerdict(
                            guardian=self.name,
                            decision="flagged",
                            reason=f'Sensitive declaration detected (keyword: "{keyword}").',
                        )
                continue

            has_assignment = re.search(r"[:=]\s*\S", raw) or re.search(r"\bé\b\s+\S+", raw, re.IGNORECASE)
            if has_assignment:
                self._flagged_count += 1
                return GuardianVerdict(
                    guardian=self.name,
                    decision="flagged",
                    reason=f'Content contains sensitive keyword "{keyword}" in assignment context.',
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

    def _get_raw(self, event: dict[str, Any]) -> str:
        content = event.get("content", {})
        if isinstance(content, dict):
            return content.get("raw", content.get("text", str(content)))
        return str(content)
