"""Test: Constitution 4 Pillar Checks — RFC-0001.

Tests for checkSoberania, checkVerdade, checkContinuidade, checkEvolucao.
Based on TS canonical: src/constitution/index.ts
"""

import pytest
from intent_kernel.constitution.checker import ConstitutionChecker


@pytest.fixture
def checker():
    return ConstitutionChecker()


# ---------------------------------------------------------------------------
# Helper — build event dicts
# ---------------------------------------------------------------------------

def _make_event(
    event_type: str = "FACT",
    raw: str = "test content",
    source: str = "conversation",
    confidence: float = 1.0,
    level: str = "TRANSIENT",
    score_value: float = 0.0,
    event_id: str = "ke-test-001",
) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "content": {"raw": raw, "normalized": raw.lower().strip(), "source": source},
        "metadata": {"confidence": confidence, "sessionId": "sess-001", "detectedAt": "2026-01-01T00:00:00Z"},
        "level": level,
        "score": {"value": score_value, "breakdown": {}, "calculatedAt": "2026-01-01T00:00:00Z"},
    }


# ---------------------------------------------------------------------------
# Pillar I: Soberania
# ---------------------------------------------------------------------------

class TestCheckSoberania:
    """Privacy/sensitive data detection."""

    def test_clean_content_allowed(self, checker):
        """Normal content passes."""
        r = checker.check_soberania(_make_event(raw="Quero investir em ETFs"))
        assert r.decision == "allowed"

    def test_password_declaration_flagged(self, checker):
        """'minha senha é X' → flagged."""
        r = checker.check_soberania(_make_event(raw="minha senha é 123456"))
        assert r.decision == "flagged"
        assert "senha" in r.reason.lower()

    def test_cpf_declaration_flagged(self, checker):
        """CPF in assignment → flagged."""
        r = checker.check_soberania(_make_event(raw="meu cpf é 123.456.789-00"))
        assert r.decision == "flagged"

    def test_cpf_mention_allowed(self, checker):
        """CPF mentioned in question → allowed."""
        r = checker.check_soberania(_make_event(raw="preciso cadastrar meu cpf"))
        assert r.decision == "allowed"

    def test_api_key_assignment_flagged(self, checker):
        """API key with assignment → flagged."""
        r = checker.check_soberania(_make_event(raw="api_key: sk-abc123"))
        assert r.decision == "flagged"

    def test_senha_mention_allowed(self, checker):
        """'senha' without assignment → allowed."""
        r = checker.check_soberania(_make_event(raw="esqueci minha senha"))
        assert r.decision == "allowed"

    def test_cartao_declaration_flagged(self, checker):
        """Credit card declaration → flagged."""
        r = checker.check_soberania(_make_event(raw="cartão de crédito é 4111..."))
        assert r.decision == "flagged"

    def test_empty_content_allowed(self, checker):
        """Empty content → allowed (no sensitive data)."""
        r = checker.check_soberania(_make_event(raw=""))
        assert r.decision == "allowed"


# ---------------------------------------------------------------------------
# Pillar II: Verdade
# ---------------------------------------------------------------------------

class TestCheckVerdade:
    """Inference confidence validation."""

    def test_explicit_source_allowed(self, checker):
        """conversation source always passes."""
        r = checker.check_verdade(_make_event(source="conversation", confidence=0.1))
        assert r.decision == "allowed"

    def test_decision_inference_low_confidence_blocked(self, checker):
        """DECISION + inference + confidence < 0.7 → blocked."""
        r = checker.check_verdade(_make_event(
            event_type="DECISION", source="inference", confidence=0.5
        ))
        assert r.decision == "blocked"
        assert "confidence" in r.reason.lower()

    def test_decision_inference_high_confidence_allowed(self, checker):
        """DECISION + inference + confidence >= 0.7 → allowed."""
        r = checker.check_verdade(_make_event(
            event_type="DECISION", source="inference", confidence=0.8
        ))
        assert r.decision == "allowed"

    def test_fact_inference_low_confidence_flagged(self, checker):
        """FACT + inference + confidence < 0.5 → flagged."""
        r = checker.check_verdade(_make_event(
            event_type="FACT", source="inference", confidence=0.3
        ))
        assert r.decision == "flagged"
        assert "Estimativa" in r.reason

    def test_fact_inference_medium_confidence_allowed(self, checker):
        """FACT + inference + confidence 0.5-0.7 → allowed."""
        r = checker.check_verdade(_make_event(
            event_type="FACT", source="inference", confidence=0.6
        ))
        assert r.decision == "allowed"

    def test_correction_source_allowed(self, checker):
        """correction source → allowed (user corrected themselves)."""
        r = checker.check_verdade(_make_event(
            event_type="CORRECTION", source="correction", confidence=0.9
        ))
        assert r.decision == "allowed"


# ---------------------------------------------------------------------------
# Pillar III: Continuidade
# ---------------------------------------------------------------------------

class TestCheckContinuidade:
    """EPHEMERAL ≠ CONSTITUTIONAL."""

    def test_ephemeral_transient_allowed(self, checker):
        """EPHEMERAL + TRANSIENT → allowed."""
        r = checker.check_continuidade(_make_event(event_type="EPHEMERAL", level="TRANSIENT"))
        assert r.decision == "allowed"

    def test_ephemeral_constitutional_blocked(self, checker):
        """EPHEMERAL + CONSTITUTIONAL → blocked."""
        r = checker.check_continuidade(_make_event(event_type="EPHEMERAL", level="CONSTITUTIONAL"))
        assert r.decision == "blocked"
        assert "EPHEMERAL" in r.reason

    def test_decision_constitutional_allowed(self, checker):
        """DECISION + CONSTITUTIONAL → allowed."""
        r = checker.check_continuidade(_make_event(event_type="DECISION", level="CONSTITUTIONAL"))
        assert r.decision == "allowed"

    def test_fact_approved_allowed(self, checker):
        """FACT + APPROVED → allowed."""
        r = checker.check_continuidade(_make_event(event_type="FACT", level="APPROVED"))
        assert r.decision == "allowed"


# ---------------------------------------------------------------------------
# Pillar IV: Evolução
# ---------------------------------------------------------------------------

class TestCheckEvolucao:
    """Observe signals, never block."""

    def test_correction_emits_signal(self, checker):
        """CORRECTION → evolution signal, always allowed."""
        r = checker.check_evolucao(_make_event(event_type="CORRECTION"))
        assert r.decision == "allowed"
        signals = checker.get_evolution_signals()
        assert len(signals) == 1
        assert "CORRECTION" in signals[0]["signal"]

    def test_high_confidence_pattern_emits_signal(self, checker):
        """PATTERN + confidence ≥ 0.7 → evolution signal."""
        r = checker.check_evolucao(_make_event(event_type="PATTERN", confidence=0.8))
        assert r.decision == "allowed"
        signals = checker.get_evolution_signals()
        assert len(signals) == 1
        assert "PATTERN" in signals[0]["signal"]

    def test_low_confidence_pattern_no_signal(self, checker):
        """PATTERN + confidence < 0.7 → no signal."""
        r = checker.check_evolucao(_make_event(event_type="PATTERN", confidence=0.5))
        assert r.decision == "allowed"
        assert len(checker.get_evolution_signals()) == 0

    def test_high_score_decision_emits_signal(self, checker):
        """DECISION + score ≥ 80 → evolution signal."""
        r = checker.check_evolucao(_make_event(event_type="DECISION", score_value=85))
        assert r.decision == "allowed"
        signals = checker.get_evolution_signals()
        assert len(signals) == 1
        assert "DECISION" in signals[0]["signal"]

    def test_evolucao_never_blocks(self, checker):
        """Evolucao pillar NEVER blocks — even for unusual events."""
        # Even a weird combination should be allowed
        r = checker.check_evolucao(_make_event(
            event_type="FACT", confidence=0.0, score_value=0.0
        ))
        assert r.decision == "allowed"

    def test_clear_signals(self, checker):
        """clear_evolution_signals empties the list."""
        checker.check_evolucao(_make_event(event_type="CORRECTION"))
        assert len(checker.get_evolution_signals()) == 1
        checker.clear_evolution_signals()
        assert len(checker.get_evolution_signals()) == 0


# ---------------------------------------------------------------------------
# Full evaluate — 4 checks combined
# ---------------------------------------------------------------------------

class TestEvaluate:
    """Full Constitution evaluation with all 4 pillars."""

    def test_clean_event_allowed(self, checker):
        """Clean event passes all checks."""
        event = _make_event(raw="Quero investir 5000/mês", source="conversation")
        verdict = checker.evaluate(event)
        assert verdict.decision == "allowed"

    def test_sensitive_event_flagged(self, checker):
        """Sensitive content → flagged (not blocked)."""
        event = _make_event(raw="minha senha é abc123")
        verdict = checker.evaluate(event)
        assert verdict.decision == "flagged"
        assert "privacy" in verdict.applies_to

    def test_bad_inference_decision_blocked(self, checker):
        """Low-confidence inference DECISION → blocked."""
        event = _make_event(
            event_type="DECISION", source="inference",
            confidence=0.5, raw="decision content"
        )
        verdict = checker.evaluate(event)
        assert verdict.decision == "blocked"
        assert "validity" in verdict.applies_to

    def test_blocked_takes_priority_over_flagged(self, checker):
        """blocked > flagged in resolution."""
        # Create event that triggers both: sensitive + bad inference
        event = _make_event(
            event_type="DECISION", source="inference",
            confidence=0.4, raw="minha senha é 123"
        )
        verdict = checker.evaluate(event)
        assert verdict.decision == "blocked"  # not flagged

    def test_ephemeral_constitutional_blocked(self, checker):
        """EPHEMERAL + CONSTITUTIONAL → blocked via Continuidade."""
        event = _make_event(event_type="EPHEMERAL", level="CONSTITUTIONAL")
        verdict = checker.evaluate(event)
        assert verdict.decision == "blocked"
        assert "retention" in verdict.applies_to


# ---------------------------------------------------------------------------
# Resolution priority
# ---------------------------------------------------------------------------

class TestResolution:
    """Verify blocked > flagged > allowed priority."""

    def test_all_allowed(self, checker):
        checks = [
            {"check_type": "privacy", "decision": "allowed", "reason": "OK"},
            {"check_type": "validity", "decision": "allowed", "reason": "OK"},
        ]
        from intent_kernel.constitution.checker import ConstitutionCheckResult
        results = [ConstitutionCheckResult(**c) for c in checks]
        v = checker._resolve(results)
        assert v.decision == "allowed"

    def test_one_flagged(self, checker):
        from intent_kernel.constitution.checker import ConstitutionCheckResult
        results = [
            ConstitutionCheckResult("privacy", "allowed", "OK"),
            ConstitutionCheckResult("validity", "flagged", "Low confidence"),
        ]
        v = checker._resolve(results)
        assert v.decision == "flagged"

    def test_blocked_over_flagged(self, checker):
        from intent_kernel.constitution.checker import ConstitutionCheckResult
        results = [
            ConstitutionCheckResult("privacy", "flagged", "Sensitive"),
            ConstitutionCheckResult("validity", "blocked", "Bad inference"),
        ]
        v = checker._resolve(results)
        assert v.decision == "blocked"
