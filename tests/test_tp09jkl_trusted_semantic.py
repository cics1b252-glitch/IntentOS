"""TP-09J-R1 / TP-09K / TP-09L: trusted semantic approval + evaluation.

Adversarial regression suite. Every test asserts a FAIL-CLOSED boundary:
caller assertions, forged provenance, and possession-without-approval must
never yield a trusted SATISFIED, and never widen execution authority.
"""

from __future__ import annotations

import datetime as _dt
import inspect
import threading

import pytest

from intent_kernel.mission.success_contract import (
    CONTRACT_VERSION,
    CriterionProvenance,
    CriterionVerdict,
    SemanticCriterion,
    compute_contract_digest,
)
from intent_kernel.mission.trusted_semantic_eval import (
    TrustedEvaluationError,
    TrustedSemanticEvaluator,
    TrustedSemanticResult,
    compute_mission_contract_digest,
)
from intent_kernel.preview import trusted_approval as ta

MISSION = "mission-alpha"


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


def _evidence(**extra):
    base = {"__result__": {"result": {"path": "/tmp/out.txt"}},
            "gate_proof": {"status": "ok"}}
    base.update(extra)
    return base


def _approve(criteria, mission_id=MISSION, version=CONTRACT_VERSION, **kw):
    digest = compute_mission_contract_digest(criteria, mission_id)
    return ta.register_semantic_approval(digest, mission_id, version, **kw)


# =========================================================================
# TP-09J-R1 : approval regate
# =========================================================================

def test_j01_valid_approval_consumes_once():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    consumed = ta.require_semantic_approval(
        a.token, "d" * 64, MISSION, CONTRACT_VERSION)
    assert consumed.contract_digest == "d" * 64
    assert consumed.mission_id == MISSION


def test_j02_missing_token_rejected():
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval("", "d" * 64, MISSION, CONTRACT_VERSION)
    assert e.value.code == "approval-token-missing"


def test_j03_forged_token_rejected():
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(
            "forged", "d" * 64, MISSION, CONTRACT_VERSION)
    assert e.value.code == "approval-token-unknown"


def test_j04_wrong_digest_rejected():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(a.token, "e" * 64, MISSION, CONTRACT_VERSION)
    assert e.value.code == "approval-contract-mismatch"


def test_j05_wrong_mission_rejected():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(a.token, "d" * 64, "other", CONTRACT_VERSION)
    assert e.value.code == "approval-mission-mismatch"


def test_j06_wrong_version_rejected():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(a.token, "d" * 64, MISSION, "9.9.9")
    assert e.value.code == "approval-version-mismatch"


def test_j07_expired_token_rejected():
    past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=400)
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION,
                                      ttl_seconds=300.0, now=past)
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(a.token, "d" * 64, MISSION, CONTRACT_VERSION)
    assert e.value.code == "approval-expired"


def test_j08_replayed_token_rejected():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    ta.require_semantic_approval(a.token, "d" * 64, MISSION, CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError) as e:
        ta.require_semantic_approval(a.token, "d" * 64, MISSION, CONTRACT_VERSION)
    assert e.value.code == "approval-token-unknown"


def test_j09_concurrent_consumption_single_winner():
    a = ta.register_semantic_approval("d" * 64, MISSION, CONTRACT_VERSION)
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        try:
            ta.require_semantic_approval(
                a.token, "d" * 64, MISSION, CONTRACT_VERSION)
            results.append("ok")
        except ta.TrustedApprovalError:
            results.append("denied")

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert sorted(results) == ["denied", "ok"]


def test_j10_no_auto_minting_requires_all_bindings():
    with pytest.raises(ta.TrustedApprovalError):
        ta.register_semantic_approval("", MISSION, CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError):
        ta.register_semantic_approval("d" * 64, "", CONTRACT_VERSION)
    with pytest.raises(ta.TrustedApprovalError):
        ta.register_semantic_approval("d" * 64, MISSION, "")


# =========================================================================
# TP-09K : trusted evaluator
# =========================================================================

def test_k01_valid_approval_satisfied():
    c = _criterion()
    a = _approve([c])
    res = TrustedSemanticEvaluator().evaluate(
        [c], _evidence(), a.token, MISSION)
    assert isinstance(res, TrustedSemanticResult)
    assert res.trusted is True
    assert res.overall == CriterionVerdict.SATISFIED.value


def test_k02_no_approval_refused():
    c = _criterion()
    with pytest.raises(TrustedEvaluationError):
        TrustedSemanticEvaluator().evaluate([c], _evidence(), "", MISSION)


def test_k03_planner_only_stays_unknown_with_approval():
    c = _criterion(provenance=CriterionProvenance.PLANNER_GENERATED.value,
                   approver_ref="")
    a = _approve([c])
    res = TrustedSemanticEvaluator().evaluate([c], _evidence(), a.token, MISSION)
    assert res.overall == CriterionVerdict.UNKNOWN.value


def test_k04_caller_supplied_verdict_ignored():
    c = _criterion(predicate="equals", expected="/tmp/out.txt")
    a = _approve([c])
    # Caller tries to inject a SATISFIED verdict into evidence.
    forged = _evidence(verdict="SATISFIED", overall="SATISFIED",
                       __result__={"result": {"path": "/elsewhere"}})
    res = TrustedSemanticEvaluator().evaluate([c], forged, a.token, MISSION)
    assert res.overall == CriterionVerdict.UNSATISFIED.value


def test_k05_changed_contract_digest_refused():
    c = _criterion()
    a = _approve([c])
    mutated = _criterion(expected="/tmp/CHANGED.txt")
    with pytest.raises(TrustedEvaluationError) as e:
        TrustedSemanticEvaluator().evaluate([mutated], _evidence(), a.token, MISSION)
    assert "approval" in e.value.code


def test_k06_wrong_mission_binding_refused():
    c = _criterion()
    a = _approve([c], mission_id=MISSION)
    with pytest.raises(TrustedEvaluationError):
        TrustedSemanticEvaluator().evaluate([c], _evidence(), a.token, "mission-beta")


def test_k07_missing_evidence_unknown():
    c = _criterion(evidence_refs=("gate_proof",))
    a = _approve([c])
    res = TrustedSemanticEvaluator().evaluate(
        [c], {"__result__": {"result": {"path": "/tmp/out.txt"}}}, a.token, MISSION)
    assert res.overall == CriterionVerdict.UNKNOWN.value


def test_k08_stale_evidence_unknown():
    c = _criterion()
    a = _approve([c])
    res = TrustedSemanticEvaluator().evaluate(
        [c], _evidence(__stale__=True), a.token, MISSION)
    assert res.overall == CriterionVerdict.UNKNOWN.value
    assert res.reason == "stale-evidence"


def test_k09_conflicting_evidence_unknown():
    c = _criterion()
    a = _approve([c])
    res = TrustedSemanticEvaluator().evaluate(
        [c], _evidence(__conflict__=True), a.token, MISSION)
    assert res.overall == CriterionVerdict.UNKNOWN.value
    assert res.reason == "conflicting-evidence"


def test_k10_empty_criteria_refused():
    with pytest.raises(TrustedEvaluationError):
        TrustedSemanticEvaluator().evaluate([], _evidence(), "x", MISSION)


# =========================================================================
# TP-09L : boundary + integrity
# =========================================================================

def test_l01_no_completion_gate_wiring():
    source = inspect.getsource(
        __import__("intent_kernel.runtime.mission_runtime", fromlist=["x"]))
    for token in ("success_contract", "trusted_semantic_eval",
                  "TrustedSemanticEvaluator"):
        assert token not in source


def test_l02_frozen_core_untouched_by_evaluator():
    import intent_kernel.mission.delegation as d
    import intent_kernel.mission.dispatch_guard as g
    import intent_kernel.orchestration.execution as x
    for mod in (d, g, x):
        assert "trusted_semantic_eval" not in inspect.getsource(mod)
        assert "success_contract" not in inspect.getsource(mod)


def test_l03_evaluator_cannot_dispatch_or_grant():
    ev = TrustedSemanticEvaluator()
    public = [n for n in dir(ev) if not n.startswith("_")]
    for forbidden in ("dispatch", "execute", "grant", "authorize", "approve",
                      "register"):
        assert all(forbidden not in n for n in public)
