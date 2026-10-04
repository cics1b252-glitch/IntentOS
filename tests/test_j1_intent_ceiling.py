"""J1 — Intent Authority Ceiling adversarial tests.

J1-R01..R16 plus legitimate-plan control. All tests use pure proof function
(no production execution path). Fail-closed semantics verified.
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.intent_ceiling import (
    IntentCeiling,
    proof_plan_action_against_ceiling,
)


def _ceiling(**over):
    defaults = {
        "allow_capabilities": ("c.rt", "c.read"),
        "allowed_operations": ("retrieve", "analyze"),
        "target_scope": ("r1", "r2"),
        "max_risk_level": "medium",
        "max_side_effect": "EXTERNAL_REVERSIBLE",
        "require_verification": True,
        "valid_from": "",
        "valid_until": "",
    }
    defaults.update(over)
    return IntentCeiling(**defaults)


def _proof(ceiling, **over):
    defaults = {
        "capability": "c.rt",
        "operation": "retrieve",
        "target": "r1",
        "risk_level": "low",
        "side_effect": "NONE",
        "verification_required": True,
        "now_iso": "2026-06-01T00:00:00+00:00",
    }
    defaults.update(over)
    return proof_plan_action_against_ceiling(ceiling, **defaults)


# ---------------------------------------------------------------------------
# J1-R01: capability escalation
# ---------------------------------------------------------------------------


def test_j1_r01_capability_escalation():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, capability="c.UNAUTHORIZED")
    assert ok is False
    assert reason == "capability-escalation"


# ---------------------------------------------------------------------------
# J1-R02: operation escalation
# ---------------------------------------------------------------------------


def test_j1_r02_operation_escalation():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, operation="DELETE")
    assert ok is False
    assert reason == "operation-escalation"


# ---------------------------------------------------------------------------
# J1-R03: target escalation
# ---------------------------------------------------------------------------


def test_j1_r03_target_escalation():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, target="r999")
    assert ok is False
    assert reason == "target-escalation"


# ---------------------------------------------------------------------------
# J1-R04: risk escalation
# ---------------------------------------------------------------------------


def test_j1_r04_risk_escalation():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, risk_level="critical")
    assert ok is False
    assert reason == "risk-escalation"


# ---------------------------------------------------------------------------
# J1-R05: side-effect escalation
# ---------------------------------------------------------------------------


def test_j1_r05_side_effect_escalation():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, side_effect="EXTERNAL_IRREVERSIBLE")
    assert ok is False
    assert reason == "side-effect-escalation"


# ---------------------------------------------------------------------------
# J1-R06: verification weakening
# ---------------------------------------------------------------------------


def test_j1_r06_verification_weakened():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, verification_required=False)
    assert ok is False
    assert reason == "verification-weakened"


# ---------------------------------------------------------------------------
# J1-R07: expired ceiling
# ---------------------------------------------------------------------------


def test_j1_r07_expired_ceiling():
    ceiling = _ceiling(valid_until="2020-01-01T00:00:00+00:00")
    ok, reason = _proof(ceiling)
    assert ok is False
    assert reason == "ceiling-expired"


# ---------------------------------------------------------------------------
# J1-R08: not-yet-valid ceiling
# ---------------------------------------------------------------------------


def test_j1_r08_not_yet_valid_ceiling():
    ceiling = _ceiling(valid_from="2027-01-01T00:00:00+00:00")
    ok, reason = _proof(ceiling)
    assert ok is False
    assert reason == "ceiling-not-yet-valid"


# ---------------------------------------------------------------------------
# J1-R09: malformed ceiling
# ---------------------------------------------------------------------------


def test_j1_r09_malformed_ceiling():
    with pytest.raises(ValueError):
        IntentCeiling(max_risk_level="INVALID_LEVEL")


# ---------------------------------------------------------------------------
# J1-R10: absent ceiling
# ---------------------------------------------------------------------------


def test_j1_r10_absent_ceiling():
    ok, reason = _proof(None)
    assert ok is False
    assert reason == "intent-ceiling-absent"


# ---------------------------------------------------------------------------
# J1-R11: planner default capability escalation
# ---------------------------------------------------------------------------


def test_j1_r11_planner_default_capability_escalation():
    ceiling = _ceiling(allow_capabilities=("c.rt",))
    ok, reason = _proof(ceiling, capability="c.DEFAULT")
    assert ok is False
    assert reason == "capability-escalation"


# ---------------------------------------------------------------------------
# J1-R12: planner default agent/self-authorization attempt
# ---------------------------------------------------------------------------


def test_j1_r12_planner_self_authorization():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling, capability="c.rt", operation="self_authorize")
    assert ok is False
    assert reason == "operation-escalation"


# ---------------------------------------------------------------------------
# J1-R13: one valid + one invalid action in multi-action plan
# ---------------------------------------------------------------------------


def test_j1_r13_multi_action_one_invalid():
    ceiling = _ceiling()
    ok1, _ = _proof(ceiling, capability="c.rt", target="r1")
    ok2, reason2 = _proof(ceiling, capability="c.UNAUTHORIZED", target="r2")
    assert ok1 is True
    assert ok2 is False
    assert reason2 == "capability-escalation"


# ---------------------------------------------------------------------------
# J1-R14: restart preserves exact ceiling
# ---------------------------------------------------------------------------


def test_j1_r14_restart_preserves_ceiling():
    ceiling = _ceiling()
    d = ceiling.to_dict()
    ceiling2 = IntentCeiling.from_dict(d)
    ok, reason = _proof(ceiling2, capability="c.rt", target="r1")
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# J1-R15: mutation after anchoring rejected/not authoritative
# ---------------------------------------------------------------------------


def test_j1_r15_mutation_after_anchoring():
    ceiling = _ceiling()
    with pytest.raises(AttributeError):
        ceiling.max_risk_level = "critical"


# ---------------------------------------------------------------------------
# J1-R16: generic human confirmation cannot expand scope
# ---------------------------------------------------------------------------


def test_j1_r16_confirmation_cannot_expand_scope():
    ceiling = _ceiling(allow_capabilities=("c.rt",))
    ok, reason = _proof(ceiling, capability="c.EXPANDED")
    assert ok is False
    assert reason == "capability-escalation"


# ---------------------------------------------------------------------------
# Control: legitimate bounded plan passes
# ---------------------------------------------------------------------------


def test_j1_control_legitimate_plan_passes():
    ceiling = _ceiling()
    ok, reason = _proof(ceiling)
    assert ok is True
    assert reason == ""


def test_j1_control_exact_boundary_passes():
    ceiling = _ceiling()
    ok, reason = _proof(
        ceiling,
        capability="c.rt",
        operation="retrieve",
        target="r1",
        risk_level="medium",
        side_effect="EXTERNAL_REVERSIBLE",
        verification_required=True,
    )
    assert ok is True
    assert reason == ""
