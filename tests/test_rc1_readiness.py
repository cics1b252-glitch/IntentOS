"""Test: RC1 Readiness — Audit, Explainability, Trust, Manifesto."""

import pytest
from intent_kernel.rc1 import (
    RC1Audit,
    ExplainabilityEngine,
    TrustIndex,
    RC1Manifesto,
    RealUserMode,
)
from intent_kernel.kernel import Kernel


# ---------------------------------------------------------------------------
# RC1 Audit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_with_kernel():
    kernel = Kernel()
    audit = RC1Audit(kernel)
    result = await audit.run_audit()
    assert result["total_score"] >= 80
    assert result["ready"] is True
    assert len(result["checks"]) >= 6


@pytest.mark.asyncio
async def test_audit_without_kernel():
    audit = RC1Audit()
    result = await audit.run_audit()
    assert result["total_score"] < 80
    assert result["ready"] is False


@pytest.mark.asyncio
async def test_audit_summary():
    kernel = Kernel()
    audit = RC1Audit(kernel)
    result = await audit.run_audit()
    assert "RC1 Readiness Audit" in result["summary"]
    assert "RC1 Score" in result["summary"]


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------

def test_explain():
    engine = ExplainabilityEngine()
    explanation = engine.explain(
        "Projeto relacionado encontrado",
        ["3 decisões similares", "Mesmo domínio"],
        0.85,
        "knowledge_core",
    )
    assert explanation.recommendation == "Projeto relacionado encontrado"
    assert explanation.confidence == 0.85
    assert len(explanation.evidence) == 2


def test_format_explanation():
    engine = ExplainabilityEngine()
    explanation = engine.explain("Test", ["Evidence 1"], 0.9, "test")
    formatted = engine.format_explanation(explanation)
    assert "💡" in formatted
    assert "Por que estou vendo isso" in formatted
    assert "90%" in formatted


# ---------------------------------------------------------------------------
# Trust Index
# ---------------------------------------------------------------------------

def test_trust_add_and_get():
    ti = TrustIndex()
    ti.add("item1", "Evidence A", 0.8, "knowledge_core")
    entry = ti.get("item1")
    assert entry is not None
    assert entry.confidence == 0.8


def test_trust_overall():
    ti = TrustIndex()
    ti.add("a", "Ev A", 0.9, "src")
    ti.add("b", "Ev B", 0.7, "src")
    assert abs(ti.overall_trust() - 0.8) < 0.01


def test_trust_get_all():
    ti = TrustIndex()
    ti.add("a", "Ev", 0.5, "src")
    all_entries = ti.get_all()
    assert len(all_entries) == 1


# ---------------------------------------------------------------------------
# RC1 Manifesto
# ---------------------------------------------------------------------------

def test_manifesto():
    manifesto = RC1Manifesto.get_manifesto()
    assert "Intent OS" in manifesto
    assert "Sistema Operacional Cognitivo" in manifesto
    assert "Constitution" in manifesto
    assert "Knowledge Core" in manifesto
    assert "Cognitive Continuity" in manifesto
    assert "7 Guardians" in manifesto


# ---------------------------------------------------------------------------
# Real User Mode
# ---------------------------------------------------------------------------

def test_real_user_tracking():
    rum = RealUserMode()
    rum.track("process", "chat", 2.5, "easy")
    rum.track("search", "search", 1.0, "easy")
    summary = rum.get_usage_summary()
    assert summary["total_actions"] == 2
    assert summary["most_used"] == "chat"


def test_real_user_empty():
    rum = RealUserMode()
    summary = rum.get_usage_summary()
    assert summary["total_actions"] == 0
