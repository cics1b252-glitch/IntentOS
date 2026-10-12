"""TP-09E: inert semantic success contract tests."""

from __future__ import annotations

import pytest

from intent_kernel.mission.success_contract import (
    CONTRACT_VERSION,
    CriterionProvenance,
    CriterionVerdict,
    SemanticCriterion,
    compute_contract_digest,
    evaluate_success_contract,
)


def _criterion(**kw):
    defaults = dict(
        criterion_id="c1",
        objective="write file",
        provenance=CriterionProvenance.AUTHORIZED_APPROVER.value,
        predicate="equals",
        json_path="result.path",
        expected="/tmp/out.txt",
        evidence_refs=("gate_proof",),
        approver_ref="operator-1",
        evaluation_version=CONTRACT_VERSION,
    )
    defaults.update(kw)
    return SemanticCriterion(**defaults)


# 1. Valid deterministic criterion -> SATISFIED
def test_e01_valid_criterion_satisfied():
    c = _criterion()
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {"status": "ok"}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value


# 2. Invalid predicate -> constructor rejects (fail closed)
def test_e02_invalid_predicate_rejected():
    with pytest.raises(ValueError):
        _criterion(predicate="delete_everything")


# 3. Unsupported operation -> UNKNOWN via evaluation
def test_e03_unknown_operation_fails_closed():
    # Bypass constructor to test evaluation-layer defense
    c = _criterion()
    object.__setattr__(c, "predicate", "unsupported_op")
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.UNKNOWN.value


# 4. Missing evidence -> UNKNOWN
def test_e04_missing_evidence_unknown():
    c = _criterion(evidence_refs=("gate_proof", "extra_proof"))
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.UNKNOWN.value
    assert "missing evidence" in result["criteria"][0]["reason"]


# 5. Contradictory criteria -> UNSATISFIED
def test_e05_contradictory_criteria_unsatisfied():
    c1 = _criterion(criterion_id="c1", expected="/tmp/a.txt")
    c2 = _criterion(criterion_id="c2", expected="/tmp/b.txt")
    evidence = {"__result__": {"result": {"path": "/tmp/a.txt"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c1, c2], evidence)
    assert result["overall"] == CriterionVerdict.UNSATISFIED.value


# 6. Planner-only provenance -> never SATISFIED
def test_e06_planner_provenance_advisory_only():
    c = _criterion(provenance=CriterionProvenance.PLANNER_GENERATED.value,
                   approver_ref="")
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.UNKNOWN.value
    assert "advisory" in result["criteria"][0]["reason"]


# 7. Authorized provenance + valid evidence -> SATISFIED
def test_e07_authorized_provenance_satisfied():
    c = _criterion(provenance=CriterionProvenance.AUTHORIZED_APPROVER.value,
                   approver_ref="trusted-operator-42")
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {"proof": "valid"}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value


# 8. UNKNOWN handling - no evidence at all
def test_e08_no_evidence_unknown():
    c = _criterion()
    result = evaluate_success_contract([c], {})
    assert result["overall"] == CriterionVerdict.UNKNOWN.value


# 9. Tamper detection
def test_e09_tamper_detection():
    c = _criterion()
    object.__setattr__(c, "expected", "/tampered.txt")
    evidence = {"__result__": {"result": {"path": "/tmp/out.txt"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.UNKNOWN.value
    assert "digest-mismatch" in result["criteria"][0]["reason"]


# 10. Legacy compatibility - plain strings still work
def test_e10_legacy_plain_strings():
    from intent_kernel.mission.mission_record import (
        MissionDefinition,
        MissionRecord,
    )
    d = MissionDefinition(objective="legacy",
                          success_criteria=("c1", "c2"))
    assert d.success_criteria == ("c1", "c2")
    # A MissionRecord built from this legacy definition still has a digest,
    # and the plain-string criteria do not alter definition-digest semantics.
    ident = {"installation_id": "i-1"}
    record = MissionRecord(
        mission_id="m-legacy", installation_id=ident["installation_id"],
        mission_definition=d)
    assert record.compute_definition_digest()


# 11. Unsupported evaluation version -> constructor rejects
def test_e11_unsupported_version_rejected():
    with pytest.raises(ValueError):
        _criterion(evaluation_version="99.0.0")


# 12. Empty criteria -> UNKNOWN (vacuous truth is never success)
def test_e12_empty_criteria_unknown():
    result = evaluate_success_contract([], {"__result__": {}})
    assert result["overall"] == CriterionVerdict.UNKNOWN.value


# Additional: digest is deterministic
def test_e13_digest_deterministic():
    c1 = _criterion()
    c2 = _criterion()
    assert c1.contract_digest == c2.contract_digest


# Additional: exists predicate
def test_e14_exists_predicate():
    c = _criterion(predicate="exists", expected=None)
    evidence = {"__result__": {"result": {"path": "/x"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value


# Additional: type predicate
def test_e15_type_predicate():
    c = _criterion(predicate="type", expected="string")
    evidence = {"__result__": {"result": {"path": "hello"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value


# Additional: contains predicate
def test_e16_contains_predicate():
    c = _criterion(predicate="contains", expected="succeeded")
    evidence = {"__result__": {"result": {"path": "operation succeeded"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value


# Additional: multiple authorized criteria, ALL satisfied -> SATISFIED
def test_e17_all_authorized_criteria_satisfied():
    c1 = _criterion(criterion_id="c1", predicate="exists", expected=None)
    c2 = _criterion(criterion_id="c2", predicate="type", expected="string")
    c3 = _criterion(criterion_id="c3", predicate="contains", expected="ok")
    evidence = {"__result__": {"result": {"path": "status ok"}},
                "gate_proof": {}}
    result = evaluate_success_contract([c1, c2, c3], evidence)
    assert result["overall"] == CriterionVerdict.SATISFIED.value
    assert all(c["verdict"] == CriterionVerdict.SATISFIED.value
               for c in result["criteria"])