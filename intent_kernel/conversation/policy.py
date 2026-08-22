"""Canonical typed conversation policy for finance field-collection.

Movement 23.2 — migrates the authority for finance multi-turn field-filling
from ProductBridge's inline ad-hoc logic into the canonical conversation layer.

This module owns:
- The ordered field schema for finance conversations (amount → recurrence → goal → risk_profile → time_horizon → liquidity)
- Next-field selection given already-collected fields
- Domain detection for finance intents
- Completion detection (all required fields present)

It does NOT own:
- Field-value matching (CDM.match_pending_response already handles that)
- Session persistence (ProductBridge.persist_turn handles that)
- Response rendering or text authoring
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─── Finance field schema ────────────────────────────────────────────────────

_FINANCE_FIELD_QUESTIONS: dict[str, str] = {
    "amount": (
        "Para começarmos a análise de investimentos, "
        "qual é o valor total disponível?"
    ),
    "recurrence": (
        "Entendi que o valor é **{amount_str}**. "
        "Esse valor é para um investimento único ou para um aporte mensal?"
    ),
    "goal": (
        "Qual é o seu objetivo principal para este investimento de "
        "**{amount_str}** (ex: aposentadoria, reserva de emergência, "
        "compra de imóvel)?"
    ),
    "risk_profile": (
        "Qual é o seu perfil de risco para este investimento "
        "(conservador, moderado ou arrojado)?"
    ),
    "time_horizon": (
        "Por quanto tempo você pretende manter este investimento aplicado?"
    ),
    "liquidity": (
        "Você precisa de liquidez imediata para resgates "
        "ou pode manter aplicado pelo prazo?"
    ),
}

# Ordered fields. Amount is always first; recurrence second.
# If recurrence is "único", the conversation ends immediately after that answer.
# goal, risk_profile, time_horizon, liquidity are only required for recurring.
_RECURRING_FIELDS: tuple[str, ...] = (
    "recurrence",
    "goal",
    "risk_profile",
    "time_horizon",
    "liquidity",
)

_ONETIME_FIELDS: tuple[str, ...] = ()

# Fields that mark the finance conversation as complete (recurring path).
_ALL_FIELDS: tuple[str, ...] = ("amount",) + _RECURRING_FIELDS


# ─── Finance domain detection ────────────────────────────────────────────────

_FINANCE_CUES: tuple[str, ...] = (
    "invest", "aporte", "aplicar", "aplicação", "aplicacao",
    "carteira", "dinheiro", "capital", "renda", "reais",
    "poupança", "poupanca", "faço com", "faco com", "fazer com",
)

_FINANCE_FIELD_NAMES: frozenset[str] = frozenset({
    "amount", "recurrence", "investment_frequency", "goal",
    "risk_profile", "time_horizon", "liquidity",
})


def detect_finance_domain(
    *,
    message_lower: str,
    known_context: dict[str, Any] | None = None,
    pending_dialogue: dict[str, Any] | None = None,
) -> bool:
    """Return True if the current turn belongs to the finance domain.

    This replaces the inline ``is_fin`` check in ProductBridge.
    """
    kc = known_context or {}
    has_cue = any(cue in message_lower for cue in _FINANCE_CUES)
    has_field = "amount" in kc or "recurrence" in kc
    pending_target = ""
    if isinstance(pending_dialogue, dict):
        pending_target = str(pending_dialogue.get("target_field", ""))
    has_pending = pending_target in _FINANCE_FIELD_NAMES
    return has_cue or has_field or has_pending


# ─── Next-field selection ────────────────────────────────────────────────────

def _format_question(field_name: str, known_context: dict[str, Any]) -> str:
    """Format the canonical question for a field, interpolating known values."""
    template = _FINANCE_FIELD_QUESTIONS.get(field_name, "")
    amount_str = known_context.get("amount_str", "")
    return template.format(amount_str=amount_str)


def next_finance_field(
    known_context: dict[str, Any],
) -> tuple[str, str] | None:
    """Return ``(field_name, question_text)`` for the next missing field.

    Returns ``None`` when all required fields are present (conversation complete).
    """
    recurrence = known_context.get("recurrence")

    # After amount is answered, always ask recurrence next.
    if "amount" not in known_context:
        return ("amount", _format_question("amount", known_context))

    if recurrence is None:
        return ("recurrence", _format_question("recurrence", known_context))

    if recurrence == "único":
        return None

    # Recurring path — walk remaining fields.
    for fname in _RECURRING_FIELDS:
        if fname not in known_context:
            return (fname, _format_question(fname, known_context))

    return None


def is_finance_complete(known_context: dict[str, Any]) -> bool:
    """Return True when all required fields are collected."""
    return next_finance_field(known_context) is None


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class FinanceFieldFillingResult:
    """Canonical result of one finance field-collection turn.

    ProductBridge reads this and translates it into the legacy response shape.
    """

    next_field: str | None
    pending_question: str | None
    is_waiting: bool
    missing_fields: tuple[str, ...]
    known_context: dict[str, Any]
    is_complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_field": self.next_field,
            "pending_question": self.pending_question,
            "is_waiting": self.is_waiting,
            "missing_fields": list(self.missing_fields),
            "known_context": dict(self.known_context),
            "is_complete": self.is_complete,
        }


def classify_finance_turn(
    known_context: dict[str, Any],
) -> FinanceFieldFillingResult:
    """Classify the current finance field-collection state.

    This is the canonical decision point that replaces the inline
    ``if is_fin and lower != "investir"`` block in ProductBridge.
    """
    nf = next_finance_field(known_context)
    if nf is None:
        return FinanceFieldFillingResult(
            next_field=None,
            pending_question=None,
            is_waiting=False,
            missing_fields=(),
            known_context=dict(known_context),
            is_complete=True,
        )

    field_name, question = nf
    missing = [f for f in _ALL_FIELDS if f not in known_context]
    return FinanceFieldFillingResult(
        next_field=field_name,
        pending_question=question,
        is_waiting=True,
        missing_fields=tuple(missing),
        known_context=dict(known_context),
        is_complete=False,
    )
