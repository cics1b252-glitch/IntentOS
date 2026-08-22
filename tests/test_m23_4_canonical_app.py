"""Movement 23.4 — Canonical application field-collection tests.

Validates ApplicationConversationPolicy, CognitiveConversationService delegates,
and ProductBridge integration for application (coding) field-filling.
"""

from __future__ import annotations

import pytest

from intent_kernel.conversation.policy import (
    ApplicationFieldFillingResult,
    classify_application_turn,
    detect_application_domain,
    is_application_complete,
    is_spreadsheet_domain,
    next_application_field,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  FIELD SCHEMA — 6 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldSchema:
    def test_first_field_is_platform(self):
        field, question = next_application_field({})
        assert field == "platform"
        assert "plataforma" in question.lower()

    def test_after_platform_next_is_purpose(self):
        field, _ = next_application_field({"platform": "Android"})
        assert field == "purpose"

    def test_after_purpose_next_is_connectivity(self):
        field, _ = next_application_field({"platform": "iOS", "purpose": "vendas"})
        assert field == "connectivity"

    def test_after_connectivity_next_is_pricing(self):
        field, _ = next_application_field({
            "platform": "Web", "purpose": "estoque", "connectivity": "online",
        })
        assert field == "pricing"

    def test_all_fields_complete_returns_none(self):
        result = next_application_field({
            "platform": "Android", "purpose": "estoque",
            "connectivity": "offline", "pricing": "gratuita",
        })
        assert result is None

    def test_is_application_complete_true(self):
        assert is_application_complete({
            "platform": "Android", "purpose": "estoque",
            "connectivity": "offline", "pricing": "gratuita",
        })

    def test_is_application_complete_false_when_missing(self):
        assert not is_application_complete({"platform": "Android"})


# ═══════════════════════════════════════════════════════════════════════════════
#  DOMAIN DETECTION — 5 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDomainDetection:
    def test_detects_app_keyword(self):
        assert detect_application_domain(message_lower="quero criar um app")

    def test_detects_aplicativo_keyword(self):
        assert detect_application_domain(message_lower="quero um aplicativo")

    def test_detects_app_type_in_known_context(self):
        assert detect_application_domain(
            message_lower="continuar",
            known_context={"app_type": "aplicativo"},
        )

    def test_detects_platform_in_known_context(self):
        assert detect_application_domain(
            message_lower="sim",
            known_context={"platform": "Android"},
        )

    def test_spreadsheet_excluded(self):
        assert not detect_application_domain(
            message_lower="criar uma planilha",
        )

    def test_is_spreadsheet_domain_true(self):
        assert is_spreadsheet_domain("criar planilha de vendas")

    def test_is_spreadsheet_domain_excel(self):
        assert is_spreadsheet_domain("exportar para excel")

    def test_detects_pending_dialogue_target(self):
        assert detect_application_domain(
            message_lower="android",
            pending_dialogue={"target_field": "platform"},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  CLASSIFY TURN — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyTurn:
    def test_empty_context_asks_platform(self):
        result = classify_application_turn({})
        assert result.next_field == "platform"
        assert result.is_waiting is True
        assert result.is_complete is False

    def test_all_fields_complete(self):
        result = classify_application_turn({
            "platform": "Android", "purpose": "estoque",
            "connectivity": "offline", "pricing": "gratuita",
        })
        assert result.is_complete is True
        assert result.is_waiting is False
        assert result.next_field is None

    def test_partial_fields_correct_next(self):
        result = classify_application_turn({
            "platform": "Web", "purpose": "vendas",
        })
        assert result.next_field == "connectivity"
        assert result.is_waiting is True

    def test_to_dict_roundtrip(self):
        result = classify_application_turn({})
        d = result.to_dict()
        assert d["next_field"] == "platform"
        assert d["is_waiting"] is True


# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION ISOLATION — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionIsolation:
    def test_separate_sessions_independent(self):
        ctx_a = {"platform": "Android", "purpose": "estoque"}
        ctx_b = {"platform": "iOS", "purpose": "vendas"}
        r_a = classify_application_turn(ctx_a)
        r_b = classify_application_turn(ctx_b)
        assert r_a.next_field == "connectivity"
        assert r_b.next_field == "connectivity"
        assert r_a.known_context != r_b.known_context

    def test_completing_one_does_not_affect_other(self):
        ctx_full = {
            "platform": "Android", "purpose": "estoque",
            "connectivity": "offline", "pricing": "gratuita",
        }
        ctx_partial = {"platform": "iOS"}
        r_full = classify_application_turn(ctx_full)
        r_partial = classify_application_turn(ctx_partial)
        assert r_full.is_complete is True
        assert r_partial.is_complete is False


# ═══════════════════════════════════════════════════════════════════════════════
#  CROSS-DOMAIN PROTECTION — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossDomainProtection:
    def test_finance_pending_does_not_trigger_app(self):
        assert not detect_application_domain(
            message_lower="investir",
            pending_dialogue={"target_field": "amount"},
        )

    def test_app_pending_does_not_trigger_finance(self):
        from intent_kernel.conversation.policy import detect_finance_domain
        assert not detect_finance_domain(
            message_lower="criar app",
            pending_dialogue={"target_field": "platform"},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  RESTART CONTINUITY — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRestartContinuity:
    def test_restart_resumes_from_correct_field(self):
        ctx = {"platform": "Android", "purpose": "estoque"}
        result = classify_application_turn(ctx)
        assert result.next_field == "connectivity"

    def test_pending_dialogue_target_matches_next_field(self):
        ctx = {"platform": "Android"}
        pending = {"target_field": "purpose", "dialogue_state": "WAITING_CONTEXT"}
        detected = detect_application_domain(
            message_lower="continuar",
            known_context=ctx,
            pending_dialogue=pending,
        )
        assert detected is True


# ═══════════════════════════════════════════════════════════════════════════════
#  THIN DELEGATES (CognitiveConversationService) — 3 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestThinDelegates:
    def test_resolve_application_pending(self):
        from intent_kernel.conversation.runtime import CognitiveConversationService
        result = CognitiveConversationService.resolve_application_pending({})
        assert isinstance(result, ApplicationFieldFillingResult)
        assert result.next_field == "platform"

    def test_application_domain_detected(self):
        from intent_kernel.conversation.runtime import CognitiveConversationService
        assert CognitiveConversationService.application_domain_detected(
            message_lower="criar um app",
        ) is True
        assert CognitiveConversationService.application_domain_detected(
            message_lower="investir",
        ) is False

    def test_application_is_complete(self):
        from intent_kernel.conversation.runtime import CognitiveConversationService
        assert CognitiveConversationService.application_is_complete({
            "platform": "Android", "purpose": "estoque",
            "connectivity": "offline", "pricing": "gratuita",
        }) is True
        assert CognitiveConversationService.application_is_complete({}) is False

    def test_is_spreadsheet_delegate(self):
        from intent_kernel.conversation.runtime import CognitiveConversationService
        assert CognitiveConversationService.is_spreadsheet("criar planilha") is True
        assert CognitiveConversationService.is_spreadsheet("criar app") is False
