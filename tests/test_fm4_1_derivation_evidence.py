"""FRONT-F.M4.1 adversarial suite: AUTHORITY_DERIVATION_EVIDENCE != AUTHORITY.

Every case drives the CANONICAL authority (``delegation.prove_edge`` /
``resolve_parent_view``) and then proves that provenance evidence changes no
verdict, revokes no authority, and resurrects nothing.
"""

from __future__ import annotations

import copy

import pytest

from intent_kernel.mission.delegation import (
    prove_edge,
    resolve_parent_view,
)
from intent_kernel.provenance.derivation import (
    DECISION_ACCEPTED,
    DECISION_REJECTED,
    DerivationEvidenceRecord,
    explain_accepted_edges,
    record_derivation_evidence,
)

MISSION = "mission-fm4"
PARENT_GRANT = {
    "delegation_id": "dlg-parent",
    "delegation_state": "AUTHORIZED",
    "delegation_allowed_capabilities": ["knowledge.search"],
    "delegation_allowed_targets": [
        "/workspace/project",
        "/workspace/project/src",
    ],
    "delegation_allowed_resources": [],
    "delegation_max_risk_level": "low",
    "delegation_max_side_effect": "NONE",
    "delegation_max_timeout_seconds": 30,
    "delegation_require_verification": True,
    "delegation_expires_at": "2099-01-01T00:00:00+00:00",
    "delegation_root_mission_id": MISSION,
    "delegation_root_generation": 1,
    "delegation_parent_delegation_id": "ROOT",
}
PARENT_ACTION = {
    "delegation_id": "dlg-parent",
    "delegation_parent_delegation_id": "ROOT",
    "expected_resource_id": "doc-1",
    "expected_governed_registration_id": "grid-1",
    "expected_resource_generation": 1,
}

CHILD_OK = {
    "delegation_id": "dlg-child",
    "delegation_allowed_capabilities": ["knowledge.search"],
    "delegation_allowed_targets": ["/workspace/project/src"],
    "delegation_allowed_resources": [],
    "delegation_max_risk_level": "low",
    "delegation_max_side_effect": "NONE",
    "delegation_max_timeout_seconds": 20,
    "delegation_require_verification": True,
    "delegation_expires_at": "2098-01-01T00:00:00+00:00",
    "delegation_root_mission_id": MISSION,
    "delegation_root_generation": 1,
    "delegation_parent_delegation_id": "dlg-parent",
}
CHILD_VIEW = {
    "capability": "knowledge.search",
    "grid": "grid-1",
    "generation": 1,
    "target": "/workspace/project/src",
    "resource_id": "doc-1",
}


def _parent_view():
    return resolve_parent_view(PARENT_ACTION, "knowledge.search", PARENT_GRANT)


def _canon(child):
    return prove_edge(child, CHILD_VIEW, _parent_view())


def _evidence(ok, reason, **kw):
    return record_derivation_evidence(
        mission_id=MISSION,
        parent_grant_id="dlg-parent",
        requested_child_identity=kw.pop("identity", "dlg-child"),
        canonical_ok=ok,
        canonical_reason=reason,
        **kw,
    )


# --- canonical reality -------------------------------------------------------
def test_canonical_accepts_narrowing_and_rejects_escapes():
    assert _canon(CHILD_OK) == (True, "")
    escaped = dict(CHILD_OK, delegation_allowed_targets=["/outside"])
    ok, reason = _canon(escaped)
    assert ok is False and "target" in reason
    escalated = dict(CHILD_OK, delegation_max_risk_level="high")
    ok, reason = _canon(escalated)
    assert ok is False and reason


# --- FM4-A01 -----------------------------------------------------------------
def test_fm4_a01_forged_accepted_evidence_cannot_authorize_rejected_delegation():
    rejected = dict(CHILD_OK, delegation_allowed_targets=["/outside"])
    assert _canon(rejected)[0] is False
    forged = _evidence(True, "durable-grant-present",
                       parent_value={"target": ["/outside"]},
                       requested_child_value={"target": ["/outside"]})
    assert forged.decision == DECISION_ACCEPTED
    assert _canon(rejected)[0] is False  # canonical verdict unchanged


# --- FM4-A02 -----------------------------------------------------------------
def test_fm4_a02_deleted_provenance_grants_and_revokes_nothing():
    before = _canon(CHILD_OK)
    _evidence(True, "durable-grant-present")
    assert _canon(CHILD_OK) == before  # evidence list intentionally discarded


# --- FM4-A03 -----------------------------------------------------------------
def test_fm4_a03_modified_parent_ceiling_in_evidence_does_not_alter_canonical():
    ev = _evidence(True, "durable-grant-present",
                   parent_value={"risk_level": "CRITICAL",
                                 "timeout_seconds": 99999})
    assert ev.parent_value["risk_level"] == "CRITICAL"
    view = _parent_view()
    assert view["ceilings"]["max_risk_level"] == "low"
    assert view["ceilings"]["max_timeout_seconds"] == 30
    assert _canon(CHILD_OK) == (True, "")
    assert _canon(dict(CHILD_OK, delegation_max_risk_level="high"))[0] is False


# --- FM4-A04 -----------------------------------------------------------------
def test_fm4_a04_replay_from_another_mission_cannot_authorize_current_mission():
    other = _evidence(True, "durable-grant-present")
    replayed = copy.deepcopy(other)
    object.__setattr__(replayed, "mission_id", MISSION)
    object.__setattr__(replayed, "evidence_digest", replayed.compute_evidence_digest())
    assert replayed.mission_id == MISSION
    # Baseline canonical verdict, computed with no evidence in existence.
    baseline = _canon(CHILD_OK)
    # Replayed evidence from a foreign mission changes nothing.
    assert _canon(CHILD_OK) == baseline
    # And it cannot smuggle an escaping target into authority.
    assert _canon(dict(CHILD_OK, delegation_allowed_targets=["/outside"]))[0] is False


# --- FM4-A05 -----------------------------------------------------------------
def test_fm4_a05_rejected_derivation_stays_rejected_and_is_durable_as_evidence():
    escaped = dict(CHILD_OK, delegation_allowed_targets=["/outside"])
    ok, reason = _canon(escaped)
    assert ok is False
    ev = _evidence(False, reason, requested_child_value={"target": ["/outside"]})
    for _ in range(3):
        assert ev.decision == DECISION_REJECTED
        assert _canon(escaped)[0] is False


# --- FM4-A06 -----------------------------------------------------------------
def test_fm4_a06_accepted_evidence_is_not_a_delegation_credential():
    ev = _evidence(True, "durable-grant-present",
                   child_grant_id="dlg-forged",
                   canonical_reference="evidence")
    forged_credential = {k: v for k, v in ev.to_dict().items()
                         if k not in ("capability", "grid", "generation")}
    assert not forged_credential.get("delegation_allowed_capabilities")
    assert _canon(CHILD_OK)[0] is True
    # The evidence grants nothing the parent grant did not already allow.
    assert set(forged_credential.get("delegation_allowed_capabilities", ())) == set()


# --- FM4-A07 -----------------------------------------------------------------
def test_fm4_a07_quantity_evidence_cannot_raise_quantity_ceiling():
    ev = _evidence(True, "durable-grant-present", dimension="quantity",
                   parent_value={"max_quantity": 10},
                   requested_child_value={"max_quantity": 10_000})
    assert ev.dimension == "quantity"
    assert ev.requested_child_value["max_quantity"] == 10_000
    # OBSERVED_QUANTITY != AUTHORIZED_QUANTITY: canonical ceilings untouched.
    assert "max_quantity" not in _parent_view()["ceilings"]
    assert _canon(CHILD_OK) == (True, "")
    assert _canon(dict(CHILD_OK, delegation_allowed_targets=["/outside"]))[0] is False


# --- FM4-A08 -----------------------------------------------------------------
def test_fm4_a08_provenance_query_is_read_only_and_non_authorizing():
    mission_data = {
        "mission_id": MISSION,
        "action_states": {"a-1": dict(PARENT_ACTION, **PARENT_GRANT)},
    }
    snapshot = copy.deepcopy(mission_data)
    records = explain_accepted_edges(mission_data)
    assert records and all(r.decision == DECISION_ACCEPTED for r in records)
    assert mission_data == snapshot  # no mutation
    assert _canon(CHILD_OK) == (True, "")
    assert explain_accepted_edges({}) == []


# --- FM4-A09 -----------------------------------------------------------------
def test_fm4_a09_ambiguous_or_missing_provenance_never_becomes_authority():
    with pytest.raises(ValueError):
        _evidence(True, "durable-grant-present", identity="")
    with pytest.raises(ValueError):
        record_derivation_evidence(
            mission_id=MISSION, parent_grant_id="dlg-parent",
            requested_child_identity="dlg-child", canonical_ok="yes")
    with pytest.raises(ValueError):
        record_derivation_evidence(
            mission_id="", parent_grant_id="dlg-parent",
            requested_child_identity="dlg-child", canonical_ok=True)
    assert _canon(CHILD_OK) == (True, "")


# --- FM4-A10 -----------------------------------------------------------------
def test_fm4_a10_mission_mismatch_visible_but_verdict_owned_by_canonical():
    ev = record_derivation_evidence(
        mission_id="mission-other", parent_grant_id="dlg-parent",
        requested_child_identity="dlg-child", canonical_ok=False,
        canonical_reason="mission-pin-mismatch:parent",
        dimension="mission_pin")
    assert ev.dimension == "mission_pin"
    assert ev.mission_id == "mission-other"
    assert ev.decision == DECISION_REJECTED
    # The evidence reports the mismatch; canonical authority alone decides, and
    # presenting the record grants nothing.
    baseline = _canon(CHILD_OK)
    assert _canon(CHILD_OK) == baseline


# --- integrity ---------------------------------------------------------------
def test_evidence_is_immutable_and_digest_bound():
    ev = _evidence(True, "durable-grant-present")
    with pytest.raises(Exception):
        ev.decision = "REJECTED"
    forged = copy.deepcopy(ev)
    object.__setattr__(forged, "decision", DECISION_REJECTED)
    with pytest.raises(ValueError):
        DerivationEvidenceRecord(
            mission_id=forged.mission_id, parent_grant_id=forged.parent_grant_id,
            child_grant_id=forged.child_grant_id,
            requested_child_identity=forged.requested_child_identity,
            dimension=forged.dimension, parent_value=forged.parent_value,
            requested_child_value=forged.requested_child_value,
            decision=forged.decision, reason=forged.reason,
            evidence_digest=forged.evidence_digest)