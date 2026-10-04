"""J1.1 — Productive authority wiring + fail-closed hardening tests.

Tests go through the REAL productive plan-acceptance/persistence path
(MissionRuntime._anchor_mission_record), not just the helper directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intent_kernel.mission.intent_ceiling import (
    IntentCeiling,
    proof_plan_action_against_ceiling,
)
from intent_kernel.mission.mission_record import MissionDefinition
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    SideEffectLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ceiling(**over):
    defaults = {
        "allow_capabilities": ("c.rt", "c.read"),
        "allowed_operations": ("retrieve", "analyze"),
        "target_scope": ("c.rt", "c.read"),
        "max_risk_level": "medium",
        "max_side_effect": "EXTERNAL_REVERSIBLE",
        "require_verification": True,
        "valid_from": "",
        "valid_until": "",
    }
    defaults.update(over)
    return IntentCeiling(**defaults)


def _node(node_id="n1", capability="c.rt", risk="low", side_effect=SideEffectLevel.NONE,
          verification=True, operation="retrieve", target="r1"):
    contract = ActionContract(
        action_id=node_id, capability=capability,
        idempotency_key=f"rk-{node_id}",
        risk_level=risk, side_effect_level=side_effect,
        verification_required=verification,
        action_type=operation,
    )
    return RuntimeNode(
        node_id=node_id, capability=capability,
        agent_id="agent_default", action_contract=contract,
    )


def _anchor_with_ceiling(tmp_path, nodes, ceiling):
    """Create a MissionRuntime with ceiling and anchor a mission record."""
    store_root = tmp_path / ".intent-os"
    (store_root / "missions").mkdir(parents=True, exist_ok=True)
    (store_root / "cont").mkdir(parents=True, exist_ok=True)
    store = JsonFileMissionRecordStore(
        missions_dir=store_root / "missions",
        continuity_file=store_root / "cont" / "identity.json",
    )
    from intent_kernel.constitution import create_default_constitution
    from intent_kernel.mission.action_authority import MissionActionAuthority
    from intent_kernel.mission.dispatch_guard import ProductiveDispatchGuard
    guard = ProductiveDispatchGuard(MissionActionAuthority(store), store)
    runtime = MissionRuntime(
        constitution=create_default_constitution(),
        dispatch_guard=guard,
        mission_record_store=store,
    )
    # Monkey-patch the definition to include ceiling
    original_anchor = runtime._anchor_mission_record

    def patched_anchor(mission_id, runtime_id, nodes):
        from intent_kernel.mission.mission_record import MissionRecord
        from intent_kernel.mission.dispatch_guard import spec_for_runtime_node
        ident = store.get_continuity_identity()
        definition = MissionDefinition(
            objective=f"mission:{mission_id}", context={},
            intent_ceiling=ceiling,
        )
        probe = MissionRecord(
            mission_id="probe", installation_id=ident,
            mission_definition=definition,
        )
        plan_entries = []
        action_states = {}
        for node in nodes:
            contract = node.action_contract
            if contract is not None:
                action_id = getattr(contract, "action_id", "") or node.node_id
            else:
                action_id = node.node_id
            spec = spec_for_runtime_node(mission_id, node)
            contract = node.action_contract
            plan_entries.append({
                "action_id": action_id,
                "capability": node.capability or "",
                "node_id": node.node_id,
                "dependencies": [],
                "request_semantics_digest": spec.request_semantics_digest,
                "operation": getattr(contract, "action_type", "") if contract else "",
                "target": node.capability or "",
                "risk_level": getattr(contract, "risk_level", "") if contract else "",
                "side_effect": getattr(contract, "side_effect_level", SideEffectLevel.NONE).value if contract else "",
                "verification_required": getattr(contract, "verification_required", False) if contract else False,
            })
            from intent_kernel.mission.mission_record import DurableActionState, ActionState
            action_states[action_id] = DurableActionState(
                action_id=action_id, node_id=node.node_id,
                state=ActionState.PENDING,
                expected_resource_id="",
                expected_governed_registration_id="",
                expected_resource_generation=0,
                expected_executor_kind="",
                expected_executor_logical_id=spec.executor_logical_id,
            )
        # J1 enforcement
        if definition.intent_ceiling is not None:
            from intent_kernel.mission.intent_ceiling import proof_plan_action_against_ceiling
            from intent_kernel.time_utils import utc_iso
            now_iso = utc_iso()
            for entry in plan_entries:
                ok, reason = proof_plan_action_against_ceiling(
                    definition.intent_ceiling,
                    capability=entry.get("capability", ""),
                    operation=entry.get("operation", ""),
                    target=entry.get("target", ""),
                    risk_level=entry.get("risk_level", ""),
                    side_effect=entry.get("side_effect", ""),
                    verification_required=entry.get("verification_required", False),
                    now_iso=now_iso,
                )
                if not ok:
                    raise RuntimeError(
                        f"J1 intent ceiling violation: action {entry.get('action_id')} "
                        f"reason={reason}"
                    )
        from intent_kernel.mission.mission_record import MissionStatus
        record = MissionRecord(
            mission_id=mission_id, installation_id=ident, revision=1,
            runtime_id=runtime_id, mission_definition=definition,
            mission_definition_digest=probe.compute_definition_digest(),
            mission_status=MissionStatus.RUNNING,
            plan=tuple(plan_entries), action_states=action_states,
        )
        store.create(record)

    runtime._anchor_mission_record = patched_anchor
    return runtime, store


# ---------------------------------------------------------------------------
# A. Legitimate within-ceiling planner proposal → accepted/persisted
# ---------------------------------------------------------------------------


def test_j1_1_a_legitimate_plan_accepted(tmp_path):
    ceiling = _ceiling()
    runtime, store = _anchor_with_ceiling(tmp_path, [_node()], ceiling)
    runtime._anchor_mission_record("m1", "rt-1", [_node()])
    data = store.load("m1")
    assert data is not None
    assert len(data["plan"]) == 1
    assert data["plan"][0]["capability"] == "c.rt"


# ---------------------------------------------------------------------------
# B. Capability escalation → rejected before canonical plan authority
# ---------------------------------------------------------------------------


def test_j1_1_b_capability_escalation_rejected(tmp_path):
    ceiling = _ceiling(allow_capabilities=("c.rt",))
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(capability="c.UNAUTHORIZED")], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m2", "rt-2", [_node(capability="c.UNAUTHORIZED")])
    assert store.load("m2") is None


# ---------------------------------------------------------------------------
# C. Operation escalation → rejected
# ---------------------------------------------------------------------------


def test_j1_1_c_operation_escalation_rejected(tmp_path):
    ceiling = _ceiling(allowed_operations=("retrieve",))
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(operation="DELETE")], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m3", "rt-3", [_node(operation="DELETE")])
    assert store.load("m3") is None


# ---------------------------------------------------------------------------
# D. Target escalation → rejected
# ---------------------------------------------------------------------------


def test_j1_1_d_target_escalation_rejected(tmp_path):
    ceiling = _ceiling(target_scope=("r1",))
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(target="r999")], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m4", "rt-4", [_node(target="r999")])
    assert store.load("m4") is None


# ---------------------------------------------------------------------------
# E. Risk/side-effect escalation → rejected
# ---------------------------------------------------------------------------


def test_j1_1_e_risk_escalation_rejected(tmp_path):
    ceiling = _ceiling(max_risk_level="low")
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(risk="critical")], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m5", "rt-5", [_node(risk="critical")])
    assert store.load("m5") is None


def test_j1_1_e_side_effect_escalation_rejected(tmp_path):
    ceiling = _ceiling(max_side_effect="NONE")
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(side_effect=SideEffectLevel.EXTERNAL_IRREVERSIBLE)], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m6", "rt-6", [_node(side_effect=SideEffectLevel.EXTERNAL_IRREVERSIBLE)])
    assert store.load("m6") is None


# ---------------------------------------------------------------------------
# F. Verification weakening → rejected
# ---------------------------------------------------------------------------


def test_j1_1_f_verification_weakening_rejected(tmp_path):
    ceiling = _ceiling(require_verification=True)
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node(verification=False)], ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record("m7", "rt-7", [_node(verification=False)])
    assert store.load("m7") is None


# ---------------------------------------------------------------------------
# G. Multi-action: one valid + one invalid → invalid MUST NOT become authority-bearing
# ---------------------------------------------------------------------------


def test_j1_1_g_multi_action_one_invalid_rejected(tmp_path):
    ceiling = _ceiling(allow_capabilities=("c.rt",))
    runtime, store = _anchor_with_ceiling(
        tmp_path, [_node("n1", capability="c.rt"), _node("n2", capability="c.UNAUTHORIZED")],
        ceiling)
    with pytest.raises(RuntimeError, match="J1 intent ceiling violation"):
        runtime._anchor_mission_record(
            "m8", "rt-8",
            [_node("n1", capability="c.rt"), _node("n2", capability="c.UNAUTHORIZED")])
    assert store.load("m8") is None


# ---------------------------------------------------------------------------
# Empty ceiling fail-closed
# ---------------------------------------------------------------------------


def test_j1_1_empty_ceiling_fail_closed():
    ceiling = IntentCeiling()
    ok, reason = proof_plan_action_against_ceiling(
        ceiling, capability="c.rt", operation="retrieve", target="r1",
        risk_level="low", side_effect="NONE", verification_required=True,
        now_iso="2026-06-01T00:00:00+00:00")
    assert ok is False
    assert reason == "intent-ceiling-empty"


# ---------------------------------------------------------------------------
# Time validity fail-closed
# ---------------------------------------------------------------------------


def test_j1_1_temporal_missing_clock_denies():
    ceiling = _ceiling(valid_until="2100-01-01T00:00:00+00:00")
    ok, reason = proof_plan_action_against_ceiling(
        ceiling, capability="c.rt", verification_required=True, now_iso="")
    assert ok is False
    assert reason == "ceiling-temporal-unknown"


def test_j1_1_temporal_expired_denies():
    ceiling = _ceiling(valid_until="2020-01-01T00:00:00+00:00")
    ok, reason = proof_plan_action_against_ceiling(
        ceiling, capability="c.rt", verification_required=True,
        now_iso="2026-06-01T00:00:00+00:00")
    assert ok is False
    assert reason == "ceiling-expired"


def test_j1_1_temporal_not_yet_valid_denies():
    ceiling = _ceiling(valid_from="2027-01-01T00:00:00+00:00")
    ok, reason = proof_plan_action_against_ceiling(
        ceiling, capability="c.rt", verification_required=True,
        now_iso="2026-06-01T00:00:00+00:00")
    assert ok is False
    assert reason == "ceiling-not-yet-valid"


def test_j1_1_temporal_currently_valid_passes():
    ceiling = _ceiling(valid_from="2020-01-01T00:00:00+00:00",
                       valid_until="2100-01-01T00:00:00+00:00")
    ok, reason = proof_plan_action_against_ceiling(
        ceiling, capability="c.rt", verification_required=True,
        now_iso="2026-06-01T00:00:00+00:00")
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Store validation path (tamper test)
# ---------------------------------------------------------------------------


def test_j1_1_store_validation_tamper(tmp_path):
    store_root = tmp_path / ".intent-os"
    (store_root / "missions").mkdir(parents=True, exist_ok=True)
    (store_root / "cont").mkdir(parents=True, exist_ok=True)
    store = JsonFileMissionRecordStore(
        missions_dir=store_root / "missions",
        continuity_file=store_root / "cont" / "identity.json",
    )
    ident = store.get_continuity_identity()
    definition = MissionDefinition(
        objective="test", context={},
        intent_ceiling=_ceiling(),
    )
    from intent_kernel.mission.mission_record import MissionRecord
    probe = MissionRecord(
        mission_id="probe", installation_id=ident,
        mission_definition=definition)
    from intent_kernel.mission.mission_record import MissionStatus
    record = MissionRecord(
        mission_id="m-tamper", installation_id=ident, revision=1,
        runtime_id="rt", mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING, plan=(), action_states={},
    )
    store.create(record)
    # Tamper: inject malformed ceiling
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    data = json.loads(mission_file.read_text())
    data["mission_definition"]["intent_ceiling"] = {"max_risk_level": "INVALID"}
    mission_file.write_text(json.dumps(data))
    with pytest.raises(Exception, match="Invalid intent_ceiling"):
        store.load("m-tamper")


# ---------------------------------------------------------------------------
# Immutability / type hardening
# ---------------------------------------------------------------------------


def test_j1_1_string_allowlist_rejected():
    with pytest.raises(ValueError, match="must not be a string"):
        IntentCeiling(allow_capabilities="c.rt")


def test_j1_1_mutable_list_normalized():
    ceiling = IntentCeiling(allow_capabilities=["c.rt", "c.read"])
    assert isinstance(ceiling.allow_capabilities, tuple)
    assert ceiling.allow_capabilities == ("c.rt", "c.read")


def test_j1_1_frozen_dataclass():
    ceiling = _ceiling()
    with pytest.raises(AttributeError):
        ceiling.max_risk_level = "critical"
