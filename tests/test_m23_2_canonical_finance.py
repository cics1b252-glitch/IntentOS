"""Movement 23.2 — Canonical finance field-collection tests.

Validates that finance multi-turn field-filling authority has been migrated
from ProductBridge's inline logic to the canonical conversation layer
(CognitiveConversationService + FinanceConversationPolicy).

Acceptance criteria:
  A. Incomplete finance → WAITING_CONTEXT with next field + question
  B. Valid continuation → field collected, advances to next
  C. All fields collected → complete summary (no WAITING_CONTEXT)
  D. Irrelevant input during pending → NOT_A_CONTINUATION, state preserved
  E. Cross-session isolation
  F. Restart persistence
  G. Adversarial / ambiguous inputs fail closed
  H. H1 non-regression (no authorization gate changes)
"""

from __future__ import annotations

import asyncio
import json
import pytest
from product_bridge import ProductBridge
from intent_kernel.conversation.policy import (
    classify_finance_turn,
    detect_finance_domain,
    is_finance_complete,
    next_finance_field,
    FinanceFieldFillingResult,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return ProductBridge()


async def _advance_finance_to(bridge, session_id, target_field):
    response = await bridge.dispatch({
        "action": "chat", "message": "Quero investir 24 mil.",
        "session_id": session_id,
    })
    steps = {
        "recurrence": [],
        "goal": ["com aportes mensais"],
        "risk_profile": ["com aportes mensais", "para aposentadoria"],
        "time_horizon": [
            "com aportes mensais", "para aposentadoria", "sou moderado",
        ],
        "liquidity": [
            "com aportes mensais", "para aposentadoria", "sou moderado",
            "por cinco anos",
        ],
    }
    for answer in steps[target_field]:
        response = await bridge.dispatch({
            "action": "chat", "message": answer, "session_id": session_id,
        })
    assert response["target_field"] == target_field
    return response


# ═══════════════════════════════════════════════════════════════════════════════
#  A. Incomplete finance → WAITING_CONTEXT with next field + question
# ═══════════════════════════════════════════════════════════════════════════════

class TestIncompleteFinanceAsksNextField:
    """A. Canonical policy determines the next field to ask."""

    @pytest.mark.asyncio
    async def test_initial_finance_ask_recurrence(self, bridge):
        response = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "a-initial",
        })
        assert response["status"] == "WAITING_CONTEXT"
        assert response["target_field"] == "recurrence"
        assert response["mission_id"] is None
        assert response["domain"] == "finance"
        assert "investimento único ou para um aporte mensal" in response["text"]

    @pytest.mark.asyncio
    async def test_after_recurrence_asks_goal(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "a-rec-goal",
        })
        response = await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "a-rec-goal",
        })
        assert response["status"] == "WAITING_CONTEXT"
        assert response["target_field"] == "goal"

    @pytest.mark.asyncio
    async def test_after_goal_asks_risk_profile(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "a-goal-risk",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "a-goal-risk",
        })
        response = await bridge.dispatch({
            "action": "chat",
            "message": "para aposentadoria",
            "session_id": "a-goal-risk",
        })
        assert response["status"] == "WAITING_CONTEXT"
        assert response["target_field"] == "risk_profile"

    @pytest.mark.asyncio
    async def test_after_risk_asks_time_horizon(self, bridge):
        resp = await _advance_finance_to(bridge, "a-risk-time", "risk_profile")
        # Answer risk_profile to advance to time_horizon
        response = await bridge.dispatch({
            "action": "chat",
            "message": "sou moderado",
            "session_id": "a-risk-time",
        })
        assert response["status"] == "WAITING_CONTEXT"
        assert response["target_field"] == "time_horizon"

    @pytest.mark.asyncio
    async def test_after_time_asks_liquidity(self, bridge):
        resp = await _advance_finance_to(
            bridge, "a-time-liquidity", "time_horizon"
        )
        # Answer time_horizon to advance to liquidity
        response = await bridge.dispatch({
            "action": "chat",
            "message": "por cinco anos",
            "session_id": "a-time-liquidity",
        })
        assert response["status"] == "WAITING_CONTEXT"
        assert response["target_field"] == "liquidity"


# ═══════════════════════════════════════════════════════════════════════════════
#  B. Valid continuation → field collected, advances to next
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidContinuationAdvances:
    """B. Typed answers advance the field-collection chain."""

    @pytest.mark.asyncio
    async def test_recurrence_answer_advances_to_goal(self, bridge):
        first = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "b-rec",
        })
        second = await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "b-rec",
        })
        assert first["compatibility_dialogue_id"] == second["compatibility_dialogue_id"]
        assert second["target_field"] == "goal"
        assert second["status"] == "WAITING_CONTEXT"

    @pytest.mark.asyncio
    async def test_goal_answer_advances_to_risk_profile(self, bridge):
        first = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "b-goal",
        })
        second = await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "b-goal",
        })
        third = await bridge.dispatch({
            "action": "chat",
            "message": "para aposentadoria",
            "session_id": "b-goal",
        })
        assert first["compatibility_dialogue_id"] == third["compatibility_dialogue_id"]
        assert third["target_field"] == "risk_profile"

    @pytest.mark.asyncio
    async def test_full_chain_recurrence_to_liquidity(self, bridge):
        first = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "b-full",
        })
        recurrence = await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "b-full",
        })
        goal = await bridge.dispatch({
            "action": "chat",
            "message": "para aposentadoria",
            "session_id": "b-full",
        })
        risk = await bridge.dispatch({
            "action": "chat",
            "message": "sou moderado",
            "session_id": "b-full",
        })
        time_h = await bridge.dispatch({
            "action": "chat",
            "message": "por cinco anos",
            "session_id": "b-full",
        })
        liq = await bridge.dispatch({
            "action": "chat",
            "message": "não preciso de liquidez",
            "session_id": "b-full",
        })
        # All share the same dialogue ID
        did = first["compatibility_dialogue_id"]
        for r in (recurrence, goal, risk, time_h, liq):
            assert r["compatibility_dialogue_id"] == did


# ═══════════════════════════════════════════════════════════════════════════════
#  C. Complete → summary (no WAITING_CONTEXT for last field)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinanceComplete:
    """C. All fields collected → complete summary."""

    @pytest.mark.asyncio
    async def test_one_time_investment_completes_immediately(self, bridge):
        response = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil como investimento único.",
            "session_id": "c-onetime",
        })
        # "único" in the same message as amount → complete on first turn
        assert response["status"] != "WAITING_CONTEXT"
        assert response["domain"] == "finance"

    @pytest.mark.asyncio
    async def test_full_recurring_investment_completes(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "c-full",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "c-full",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "para aposentadoria",
            "session_id": "c-full",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "sou moderado",
            "session_id": "c-full",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "por cinco anos",
            "session_id": "c-full",
        })
        final = await bridge.dispatch({
            "action": "chat",
            "message": "não preciso de liquidez",
            "session_id": "c-full",
        })
        assert final["status"] != "WAITING_CONTEXT"
        assert final["domain"] == "finance"
        assert "Análise de Investimento" in final["text"]


# ═══════════════════════════════════════════════════════════════════════════════
#  D. Irrelevant input → NOT_A_CONTINUATION, state preserved
# ═══════════════════════════════════════════════════════════════════════════════

class TestIrrelevantInputPreservesState:
    """D. Non-finance utterances during pending do not mutate dialogue state."""

    @pytest.mark.asyncio
    async def test_unknown_query_preserves_pending(self, bridge):
        first = await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "d-unknown",
        })
        saved_before = bridge._load_session("d-unknown")
        response = await bridge.dispatch({
            "action": "chat",
            "message": "Qual a capital de um planeta fictício chamado XZ-91?",
            "session_id": "d-unknown",
        })
        saved_after = bridge._load_session("d-unknown")
        assert response["status"] == "UNKNOWN"
        assert response["mission_id"] is None
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]

    @pytest.mark.asyncio
    async def test_explanation_request_preserves_pending(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "d-explain",
        })
        saved_before = bridge._load_session("d-explain")
        response = await bridge.dispatch({
            "action": "chat",
            "message": "Explique juros compostos.",
            "session_id": "d-explain",
        })
        saved_after = bridge._load_session("d-explain")
        assert response["status"] == "EXTERNAL_RESOURCE_REQUIRED"
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]

    @pytest.mark.asyncio
    async def test_question_mark_input_preserves_pending(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "d-question",
        })
        saved_before = bridge._load_session("d-question")
        response = await bridge.dispatch({
            "action": "chat",
            "message": "O que você consegue fazer?",
            "session_id": "d-question",
        })
        saved_after = bridge._load_session("d-question")
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]


# ═══════════════════════════════════════════════════════════════════════════════
#  E. Cross-session isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossSessionIsolation:
    """E. Finance pending in session A must not leak into session B."""

    @pytest.mark.asyncio
    async def test_session_b_does_not_inherit_session_a_pending(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "e-session-a",
        })
        response_b = await bridge.dispatch({
            "action": "chat",
            "message": "Qual a capital de um planeta fictício?",
            "session_id": "e-session-b",
        })
        assert response_b["status"] == "UNKNOWN"
        assert response_b["domain"] != "finance"
        assert response_b["mission_id"] is None

    @pytest.mark.asyncio
    async def test_session_a_pending_unaffected_by_session_b(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "e-protect-a",
        })
        await bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "e-other-b",
        })
        saved_a = bridge._load_session("e-protect-a")
        assert saved_a["pending_dialogue"] is not None
        assert saved_a["pending_dialogue"]["target_field"] == "recurrence"


# ═══════════════════════════════════════════════════════════════════════════════
#  F. Restart persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestRestartPersistence:
    """F. Finance pending survives bridge process restart."""

    @pytest.mark.asyncio
    async def test_restart_preserves_pending_and_advances(self, bridge, tmp_path, monkeypatch):
        first = await bridge.dispatch({
            "action": "chat",
            "message": "quero investir 24 mil",
            "session_id": "f-restart",
        })
        dialogue_id = first["compatibility_dialogue_id"]
        assert first["status"] == "WAITING_CONTEXT"

        # Simulate process restart
        monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
        new_bridge = ProductBridge()
        second = await new_bridge.dispatch({
            "action": "chat",
            "message": "com aportes mensais",
            "session_id": "f-restart",
        })
        assert second["status"] == "WAITING_CONTEXT"
        assert second["compatibility_dialogue_id"] == dialogue_id
        assert second["target_field"] == "goal"


# ═══════════════════════════════════════════════════════════════════════════════
#  G. Adversarial / ambiguous inputs fail closed
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdversarialInputsFailClosed:
    """G. Marker collisions and ambiguous inputs do not consume pending dialogue."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_field,message", [
        ("goal", "Minha casa é azul."),
        ("recurrence", "Minha reunião mensal terminou."),
        ("risk_profile", "O carro está seguro."),
        ("time_horizon", "O projeto dura cinco anos."),
    ])
    async def test_marker_collision_not_continuation(
        self, bridge, target_field, message
    ):
        session_id = f"g-false-pos-{target_field}"
        pending_response = await _advance_finance_to(
            bridge, session_id, target_field
        )
        saved_before = bridge._load_session(session_id)
        response = await bridge.dispatch({
            "action": "chat", "message": message, "session_id": session_id,
        })
        saved_after = bridge._load_session(session_id)
        assert response["pending_dialogue_match"]["match_status"] == "NOT_A_CONTINUATION"
        assert response["mission_id"] is None
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]

    @pytest.mark.asyncio
    async def test_ambiguous_answer_does_not_mutate(self, bridge):
        session_id = "g-ambiguous"
        await _advance_finance_to(bridge, session_id, "goal")
        saved_before = bridge._load_session(session_id)
        response = await bridge.dispatch({
            "action": "chat", "message": "talvez", "session_id": session_id,
        })
        saved_after = bridge._load_session(session_id)
        assert response["pending_dialogue_match"]["match_status"] == "AMBIGUOUS"
        assert response["mission_id"] is None
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]

    @pytest.mark.asyncio
    async def test_empty_input_preserves_pending(self, bridge):
        await bridge.dispatch({
            "action": "chat",
            "message": "Quero investir 24 mil.",
            "session_id": "g-empty",
        })
        saved_before = bridge._load_session("g-empty")
        response = await bridge.dispatch({
            "action": "chat",
            "message": "",
            "session_id": "g-empty",
        })
        saved_after = bridge._load_session("g-empty")
        assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]


# ═══════════════════════════════════════════════════════════════════════════════
#  H. Canonical policy unit tests (no ProductBridge)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCanonicalPolicyUnit:
    """H. Direct unit tests for the FinanceConversationPolicy."""

    def test_empty_context_asks_amount(self):
        result = classify_finance_turn({})
        assert result.next_field == "amount"
        assert result.is_waiting is True
        assert result.is_complete is False

    def test_amount_only_asks_recurrence(self):
        result = classify_finance_turn({"amount": 24000.0, "amount_str": "R$ 24.000"})
        assert result.next_field == "recurrence"
        assert result.is_waiting is True

    def test_amount_recurrence_unique_completes(self):
        result = classify_finance_turn({
            "amount": 24000.0, "amount_str": "R$ 24.000", "recurrence": "único"
        })
        assert result.is_complete is True
        assert result.next_field is None
        assert result.is_waiting is False

    def test_amount_recurrence_monthly_asks_goal(self):
        result = classify_finance_turn({
            "amount": 24000.0, "amount_str": "R$ 24.000", "recurrence": "mensal"
        })
        assert result.next_field == "goal"
        assert result.is_waiting is True

    def test_all_fields_complete(self):
        result = classify_finance_turn({
            "amount": 24000.0,
            "amount_str": "R$ 24.000",
            "recurrence": "mensal",
            "goal": "aposentadoria",
            "risk_profile": "moderado",
            "time_horizon": "5 anos",
            "liquidity": "sem necessidade de liquidez imediata",
        })
        assert result.is_complete is True
        assert result.next_field is None

    def test_detect_finance_cue_in_message(self):
        assert detect_finance_domain(message_lower="quero investir") is True
        assert detect_finance_domain(message_lower="bom dia") is False

    def test_detect_finance_from_known_context(self):
        assert detect_finance_domain(
            message_lower="qualquer coisa",
            known_context={"amount": 1000},
        ) is True

    def test_detect_finance_from_pending_dialogue(self):
        assert detect_finance_domain(
            message_lower="com aportes",
            pending_dialogue={"target_field": "recurrence"},
        ) is True

    def test_detect_finance_non_finance_pending(self):
        assert detect_finance_domain(
            message_lower="qual é a plataforma",
            pending_dialogue={"target_field": "platform"},
        ) is False

    def test_next_field_returns_none_when_complete(self):
        assert next_finance_field({
            "amount": 1000, "amount_str": "R$ 1.000",
            "recurrence": "único",
        }) is None

    def test_next_field_returns_tuple_when_incomplete(self):
        result = next_finance_field({"amount": 1000, "amount_str": "R$ 1.000"})
        assert result is not None
        field_name, question = result
        assert field_name == "recurrence"
        assert "investimento único" in question

    def test_is_finance_complete_true(self):
        assert is_finance_complete({
            "amount": 1000, "amount_str": "R$ 1.000", "recurrence": "único",
        }) is True

    def test_is_finance_complete_false(self):
        assert is_finance_complete({"amount": 1000}) is False

    def test_result_to_dict_shape(self):
        result = classify_finance_turn({})
        d = result.to_dict()
        assert "next_field" in d
        assert "pending_question" in d
        assert "is_waiting" in d
        assert "missing_fields" in d
        assert "known_context" in d
        assert "is_complete" in d
