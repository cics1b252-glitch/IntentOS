"""Test: Constitution Guardians — 6 Guardians + Registry."""

import pytest
from intent_kernel.constitution.guardians import GuardianRegistry, GuardianVerdict
from intent_kernel.constitution.guardians.soberania import SoberaniaGuardian
from intent_kernel.constitution.guardians.verdade import VerdadeGuardian
from intent_kernel.constitution.guardians.continuidade import ContinuidadeGuardian
from intent_kernel.constitution.guardians.evolucao import EvolucaoGuardian
from intent_kernel.constitution.guardians.symbiosis import SymbiosisGuardian
from intent_kernel.constitution.guardians.knowledge_heritage import KnowledgeHeritageGuardian
from intent_kernel.constitution.guardians.continuity import ContinuityGuardian


def _make_event(**kwargs) -> dict:
    defaults = {
        "id": "ke-test-001",
        "type": "FACT",
        "content": {"raw": "test content", "normalized": "test content", "source": "conversation"},
        "metadata": {"confidence": 1.0, "sessionId": "sess-001"},
        "level": "TRANSIENT",
        "score": {"value": 50},
    }
    # Handle convenience kwargs
    if "raw" in kwargs:
        raw_val = kwargs.pop("raw")
        defaults["content"]["raw"] = raw_val
        defaults["content"]["normalized"] = raw_val.lower().strip()
    if "source" in kwargs:
        defaults["content"]["source"] = kwargs.pop("source")
    if "event_type" in kwargs:
        defaults["type"] = kwargs.pop("event_type")
    if "confidence" in kwargs:
        defaults["metadata"]["confidence"] = kwargs.pop("confidence")
    if "score_value" in kwargs:
        defaults["score"]["value"] = kwargs.pop("score_value")
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Soberania Guardian
# ---------------------------------------------------------------------------

class TestSoberaniaGuardian:
    def test_clean_content(self):
        g = SoberaniaGuardian()
        v = g.validate(_make_event(raw="Quero investir em ETFs"))
        assert v.decision == "allowed"

    def test_password_declaration(self):
        g = SoberaniaGuardian()
        v = g.validate(_make_event(raw="minha senha é 123456"))
        assert v.decision == "flagged"

    def test_cpf_declaration(self):
        g = SoberaniaGuardian()
        v = g.validate(_make_event(raw="meu cpf é 123.456.789-00"))
        assert v.decision == "flagged"

    def test_cpf_mention_allowed(self):
        g = SoberaniaGuardian()
        v = g.validate(_make_event(raw="preciso cadastrar meu cpf"))
        assert v.decision == "allowed"

    def test_api_key_assignment(self):
        g = SoberaniaGuardian()
        v = g.validate(_make_event(raw="api_key: sk-abc123"))
        assert v.decision == "flagged"

    def test_status(self):
        g = SoberaniaGuardian()
        g.validate(_make_event(raw="minha senha é x"))
        s = g.status()
        assert s["flagged"] == 1


# ---------------------------------------------------------------------------
# Verdade Guardian
# ---------------------------------------------------------------------------

class TestVerdadeGuardian:
    def test_conversation_source(self):
        g = VerdadeGuardian()
        v = g.validate(_make_event(source="conversation", confidence=0.1))
        assert v.decision == "allowed"

    def test_decision_inference_low_confidence(self):
        g = VerdadeGuardian()
        v = g.validate(_make_event(event_type="DECISION", source="inference", confidence=0.5))
        assert v.decision == "blocked"

    def test_decision_inference_high_confidence(self):
        g = VerdadeGuardian()
        v = g.validate(_make_event(event_type="DECISION", source="inference", confidence=0.8))
        assert v.decision == "allowed"

    def test_fact_inference_low_confidence(self):
        g = VerdadeGuardian()
        v = g.validate(_make_event(event_type="FACT", source="inference", confidence=0.3))
        assert v.decision == "flagged"


# ---------------------------------------------------------------------------
# Continuidade Guardian
# ---------------------------------------------------------------------------

class TestContinuidadeGuardian:
    def test_ephemeral_transient(self):
        g = ContinuidadeGuardian()
        v = g.validate(_make_event(event_type="EPHEMERAL", level="TRANSIENT"))
        assert v.decision == "allowed"

    def test_ephemeral_constitutional(self):
        g = ContinuidadeGuardian()
        v = g.validate(_make_event(event_type="EPHEMERAL", level="CONSTITUTIONAL"))
        assert v.decision == "blocked"

    def test_decision_constitutional(self):
        g = ContinuidadeGuardian()
        v = g.validate(_make_event(event_type="DECISION", level="CONSTITUTIONAL"))
        assert v.decision == "allowed"


# ---------------------------------------------------------------------------
# Evolução Guardian
# ---------------------------------------------------------------------------

class TestEvolucaoGuardian:
    def test_correction_emits_signal(self):
        g = EvolucaoGuardian()
        v = g.validate(_make_event(event_type="CORRECTION"))
        assert v.decision == "allowed"
        assert len(g.get_signals()) == 1

    def test_high_confidence_pattern(self):
        g = EvolucaoGuardian()
        v = g.validate(_make_event(event_type="PATTERN", confidence=0.8))
        assert v.decision == "allowed"
        assert len(g.get_signals()) == 1

    def test_never_blocks(self):
        g = EvolucaoGuardian()
        v = g.validate(_make_event(event_type="FACT", confidence=0.0, score_value=0))
        assert v.decision == "allowed"


# ---------------------------------------------------------------------------
# Symbiosis Guardian
# ---------------------------------------------------------------------------

class TestSymbiosisGuardian:
    def test_clean_imports(self):
        g = SymbiosisGuardian()
        v = g.validate({}, context={"check_type": "imports", "imports": ["os.path", "json", "datetime"]})
        assert v.decision == "allowed"

    def test_os_specific_import(self):
        g = SymbiosisGuardian()
        v = g.validate({}, context={"check_type": "imports", "imports": ["winreg"]})
        assert v.decision == "blocked"

    def test_subprocess_import(self):
        g = SymbiosisGuardian()
        v = g.validate({}, context={"check_type": "imports", "imports": ["subprocess"]})
        assert v.decision == "blocked"

    def test_clean_system_access(self):
        g = SymbiosisGuardian()
        v = g.validate({}, context={"check_type": "system_access", "accesses": ["file.read()"]})
        assert v.decision == "allowed"


# ---------------------------------------------------------------------------
# Knowledge Heritage Guardian
# ---------------------------------------------------------------------------

class TestKnowledgeHeritageGuardian:
    def test_event_with_versioning(self):
        g = KnowledgeHeritageGuardian()
        event = _make_event()
        event["lifecycle"] = {"currentLevel": "TRANSIENT", "transitions": []}
        v = g.validate(event)
        assert v.decision == "allowed"

    def test_event_without_versioning(self):
        g = KnowledgeHeritageGuardian()
        v = g.validate({"id": "ke-001"})  # no lifecycle, no version
        assert v.decision == "flagged"

    def test_store_with_capabilities(self):
        g = KnowledgeHeritageGuardian()
        v = g.validate_store({
            "export": True, "versioning": True, "audit_trail": True,
            "recovery": True, "no_proprietary_format": True,
        })
        assert v.decision == "allowed"

    def test_store_missing_export(self):
        g = KnowledgeHeritageGuardian()
        v = g.validate_store({
            "export": False, "versioning": True, "audit_trail": True,
            "recovery": True, "no_proprietary_format": True,
        })
        assert v.decision == "flagged"
        assert "export" in v.reason


# ---------------------------------------------------------------------------
# Continuity Guardian
# ---------------------------------------------------------------------------

class TestContinuityGuardian:
    def test_provider_change_no_kc_effect(self):
        g = ContinuityGuardian()
        v = g.validate({}, context={"change_type": "provider_change", "kc_affected": False})
        assert v.decision == "allowed"

    def test_provider_change_kc_affected(self):
        g = ContinuityGuardian()
        v = g.validate({}, context={"change_type": "provider_change", "kc_affected": True})
        assert v.decision == "flagged"

    def test_infra_change_no_kernel_effect(self):
        g = ContinuityGuardian()
        v = g.validate({}, context={"change_type": "infra_change", "kernel_affected": False})
        assert v.decision == "allowed"

    def test_version_change_with_migration(self):
        g = ContinuityGuardian()
        v = g.validate({}, context={
            "change_type": "version_change",
            "from_version": "1.0", "to_version": "1.1",
            "has_migration_path": True,
        })
        assert v.decision == "allowed"

    def test_version_change_without_migration(self):
        g = ContinuityGuardian()
        v = g.validate({}, context={
            "change_type": "version_change",
            "from_version": "1.0", "to_version": "2.0",
            "has_migration_path": False,
        })
        assert v.decision == "flagged"

    def test_export_open_format(self):
        g = ContinuityGuardian()
        v = g.validate_export("json")
        assert v.decision == "allowed"

    def test_export_proprietary_format(self):
        g = ContinuityGuardian()
        v = g.validate_export("docx")
        assert v.decision == "flagged"


# ---------------------------------------------------------------------------
# Guardian Registry
# ---------------------------------------------------------------------------

class TestGuardianRegistry:
    def test_register_and_get(self):
        r = GuardianRegistry()
        g = SoberaniaGuardian()
        r.register(g)
        assert r.get("soberania") is g

    def test_validate_all(self):
        r = GuardianRegistry()
        r.register(SoberaniaGuardian())
        r.register(VerdadeGuardian())
        r.register(ContinuidadeGuardian())
        r.register(EvolucaoGuardian())

        verdicts = r.validate_all(_make_event(raw="test"))
        assert len(verdicts) == 4

    def test_resolve_all_allowed(self):
        r = GuardianRegistry()
        verdicts = [
            GuardianVerdict("a", "allowed", "OK"),
            GuardianVerdict("b", "allowed", "OK"),
        ]
        v = r.resolve(verdicts)
        assert v.decision == "allowed"

    def test_resolve_one_blocked(self):
        r = GuardianRegistry()
        verdicts = [
            GuardianVerdict("a", "allowed", "OK"),
            GuardianVerdict("b", "blocked", "Bad"),
        ]
        v = r.resolve(verdicts)
        assert v.decision == "blocked"

    def test_resolve_blocked_over_flagged(self):
        r = GuardianRegistry()
        verdicts = [
            GuardianVerdict("a", "flagged", "Sensitive"),
            GuardianVerdict("b", "blocked", "Bad"),
        ]
        v = r.resolve(verdicts)
        assert v.decision == "blocked"

    def test_status(self):
        r = GuardianRegistry()
        r.register(SoberaniaGuardian())
        s = r.status()
        assert s["count"] == 1
        assert "soberania" in s["guardians"]
