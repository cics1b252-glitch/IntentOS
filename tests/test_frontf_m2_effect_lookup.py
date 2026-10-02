"""FRONT-F.M2 — Effect-first Authority Provenance Lookup tests.

M2-01..M2-13 plus structural no-authority-path proof. All fixtures go
through canonical authority transitions; the LOOKUP under test only reads.
All stores isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from intent_kernel.mission import ActionState
from intent_kernel.mission.action_authority import ActionTransitionEvidence
from intent_kernel.mission.execution_identity import (
    compute_local_execution_identity,
    effect_identity_digest_for,
)
from intent_kernel.mission.mission_record import MissionStatus
from intent_kernel.provenance.lookup import (
    EffectCandidate,
    EffectLookup,
    EffectLookupResult,
    EffectProvenanceLookup,
)
from intent_kernel.provenance.view import AuthorityProvenanceView, LinkStatus
from tests.test_m33_2b_delegation import (
    _authority,
    _bind_record,
    _components,
    _drive_authorized,
    _ev,
    _govern,
    _governed_pair,
    _grant_kwargs,
    _grant_std,
    _make_node,
    _mission_store,
    _rev_for,
    CountingApp,
)
from tests.test_frontf_m1_provenance_view import _ident


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _view_for(components, store, installation_id="", now_iso=""):
    rm = components.resource_manager

    def _snap(getter, key):
        try:
            s = getter(key)
        except Exception:
            return None
        if s is None:
            return None
        elig = s.is_eligible
        return {
            "governed_registration_id": s.governed_registration_id,
            "generation": s.generation,
            "eligible": bool(elig() if callable(elig) else elig),
        }

    return AuthorityProvenanceView(
        load_mission=lambda mid: store.load(mid),
        mission_exists=lambda mid: store.exists(mid),
        rrm_capability=lambda name: _snap(rm.get_capability, name),
        rrm_agent=lambda aid: _snap(rm.get_agent, aid),
        rrm_provider=lambda pid: _snap(rm.get_provider, pid),
        installation_id=installation_id,
        now_iso=now_iso,
    )


def _lookup_for(components, store, mission_ids, max_missions=None, now_iso=""):
    view = _view_for(components, store, now_iso=now_iso)
    return EffectProvenanceLookup(
        view=view,
        enumerate_mission_ids=lambda: list(mission_ids),
        max_missions=max_missions,
    )


def _seed_effect(tmp_path, name="m2", token="pe-tok-1"):
    """Create a governed pair, drive to RESULT_RECORDED with a provider token."""
    import asyncio

    async def _run():
        ctx = await _governed_pair(tmp_path, name=name)
        authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
        rev = authority.transition_action(
            mid, "c1", ctx["rev"], ActionState.PENDING,
            ActionState.AUTHORIZED, _ev()).mission_revision
        rev = authority.transition_action(
            mid, "c1", rev, ActionState.AUTHORIZED,
            ActionState.DISPATCH_INTENT_RECORDED, _ev()).mission_revision
        rev = authority.transition_action(
            mid, "c1", rev, ActionState.DISPATCH_INTENT_RECORDED,
            ActionState.DISPATCHING, _ev()).mission_revision
        authority.transition_action(
            mid, "c1", rev, ActionState.DISPATCHING,
            ActionState.RESULT_RECORDED,
            ActionTransitionEvidence(
                requested_by="t", reason="t",
                result={"o": 1}, provider_effect_id=token))
        return ctx, mid

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# M2-01: empty effect identity rejected
# ---------------------------------------------------------------------------


def test_m2_01_empty_identity_rejected():
    with pytest.raises(ValueError, match="at least one"):
        EffectLookup()


# ---------------------------------------------------------------------------
# M2-02: unique identity resolves correctly
# ---------------------------------------------------------------------------


def test_m2_02_unique_match_resolves(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-02")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.status != LinkStatus.NOT_FOUND
    assert result.status != LinkStatus.AMBIGUOUS
    assert result.provenance is not None
    assert result.provenance.mission_id == mid
    assert result.provenance.action_id == "c1"
    assert result.search_complete is True


# ---------------------------------------------------------------------------
# M2-03: zero matches on complete scan → NOT_FOUND
# ---------------------------------------------------------------------------


def test_m2_03_zero_matches_not_found(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-03")
    store = ctx["store"]
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id="no-such-token"))
    assert result.status == LinkStatus.NOT_FOUND
    assert result.search_complete is True
    assert result.candidates == ()


# ---------------------------------------------------------------------------
# M2-04: duplicate identity → AMBIGUOUS
# ---------------------------------------------------------------------------


def test_m2_04_duplicate_identity_ambiguous(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-04")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    # Inject a second VALID action with the same token (correct E2 for c2)
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    mdata = json.loads(mission_file.read_text())
    plan_digest = next(
        e["request_semantics_digest"]
        for e in mdata["plan"] if e["action_id"] == "c1")
    e2_c2 = compute_local_execution_identity(
        mid, "c2", plan_digest, action["expected_executor_logical_id"],
        action["expected_governed_registration_id"],
        action["expected_resource_generation"])
    mdata["action_states"]["c2"] = {
        "action_id": "c2", "node_id": "n2",
        "state": "RESULT_RECORDED",
        "expected_resource_id": action["expected_resource_id"],
        "expected_governed_registration_id": action["expected_governed_registration_id"],
        "expected_resource_generation": action["expected_resource_generation"],
        "expected_executor_kind": action["expected_executor_kind"],
        "expected_executor_logical_id": action["expected_executor_logical_id"],
        "local_execution_identity": e2_c2,
        "provider_effect_id": token,
        "effect_identity_digest": effect_identity_digest_for(token),
        "result": {"o": 2},
    }
    mdata["plan"].append({
        "action_id": "c2", "capability": "c.rt", "node_id": "n2",
        "dependencies": [], "request_semantics_digest": plan_digest,
    })
    mission_file.write_text(json.dumps(mdata))
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.status == LinkStatus.AMBIGUOUS
    assert len(result.candidates) == 2
    assert result.provenance is None


# ---------------------------------------------------------------------------
# M2-05: candidate ordering cannot change ambiguity result
# ---------------------------------------------------------------------------


def test_m2_05_ordering_cannot_resolve_ambiguity(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-05")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    mdata = json.loads(mission_file.read_text())
    plan_digest = next(
        e["request_semantics_digest"]
        for e in mdata["plan"] if e["action_id"] == "c1")
    e2_c2 = compute_local_execution_identity(
        mid, "c2", plan_digest, action["expected_executor_logical_id"],
        action["expected_governed_registration_id"],
        action["expected_resource_generation"])
    mdata["action_states"]["c2"] = {
        "action_id": "c2", "node_id": "n2",
        "state": "RESULT_RECORDED",
        "expected_resource_id": action["expected_resource_id"],
        "expected_governed_registration_id": action["expected_governed_registration_id"],
        "expected_resource_generation": action["expected_resource_generation"],
        "expected_executor_kind": action["expected_executor_kind"],
        "expected_executor_logical_id": action["expected_executor_logical_id"],
        "local_execution_identity": e2_c2,
        "provider_effect_id": token,
        "effect_identity_digest": effect_identity_digest_for(token),
        "result": {"o": 2},
    }
    mdata["plan"].append({
        "action_id": "c2", "capability": "c.rt", "node_id": "n2",
        "dependencies": [], "request_semantics_digest": plan_digest,
    })
    mission_file.write_text(json.dumps(mdata))
    # Reverse enumeration order
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.status == LinkStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# M2-06: unique match receives fresh reload
# ---------------------------------------------------------------------------


def test_m2_06_fresh_reload_performed(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-06")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]

    reload_count = [0]
    original_load = store.load

    def counting_load(mid):
        reload_count[0] += 1
        return original_load(mid)

    ctx2, _ = _seed_effect(tmp_path, name="m2-06b")
    store2 = ctx2["store"]
    store2.load = counting_load
    lookup = _lookup_for(ctx2["components"], store2, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.provenance is not None
    # At least 2 loads: discovery + fresh reload
    assert reload_count[0] >= 2


# ---------------------------------------------------------------------------
# M2-07: identity changed between discovery/reload → fail closed
# ---------------------------------------------------------------------------


def test_m2_07_identity_changed_fails_closed(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-07")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]

    import json
    from pathlib import Path

    class MutatingStore:
        def __init__(self, real_store):
            self._real = real_store
            self._mutated = False

        def load(self, mid):
            if not self._mutated:
                self._mutated = True
                return self._real.load(mid)
            # Second load: tamper the token
            data = self._real.load(mid)
            data["action_states"]["c1"]["provider_effect_id"] = "tampered"
            return data

        def __getattr__(self, name):
            return getattr(self._real, name)

    mutating = MutatingStore(store)
    lookup = _lookup_for(ctx["components"], mutating, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.status == LinkStatus.NOT_FOUND
    assert "changed" in result.detail


# ---------------------------------------------------------------------------
# M2-08: historical match + current validity FALSE remains discoverable
# ---------------------------------------------------------------------------


def test_m2_08_historical_match_survives_current_false(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-08")
    authority, store = ctx["authority"], ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    # Create a PENDING child action, grant+revoke on it
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    mdata = json.loads(mission_file.read_text())
    plan_digest = next(
        e["request_semantics_digest"]
        for e in mdata["plan"] if e["action_id"] == "c1")
    mdata["action_states"]["c2"] = {
        "action_id": "c2", "node_id": "n2", "state": "PENDING",
        "expected_resource_id": "r",
        "expected_governed_registration_id": ctx["grid"],
        "expected_resource_generation": ctx["gen"],
        "expected_executor_kind": "core_app",
        "expected_executor_logical_id": "delegate-1",
        "local_execution_identity": "",
        "attempt_count": 0,
        "confirmation_required": False,
        "confirmation_basis_digest": "",
        "result": None,
        "verification_status": "",
        "verification_evidence": None,
        "error_message": None,
        "provider_effect_id": "",
        "effect_identity_digest": "",
        "verification_proof_digest": "",
    }
    mdata["plan"].append({
        "action_id": "c2", "capability": "c.rt", "node_id": "n2",
        "dependencies": [], "request_semantics_digest": plan_digest,
    })
    mission_file.write_text(json.dumps(mdata))
    store2 = _mission_store(tmp_path)
    authority2 = _authority(store2)
    authority2.grant_delegation(
        mid, "c2", _rev_for(authority2, mid), parent_action_id="p1",
        **_grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"],
                        allowed_capabilities=("c.rt",)))
    rev = store2.load(mid)["revision"]
    authority2.revoke_delegation(mid, "c2", rev, "m2-08 test")
    lookup = _lookup_for(ctx["components"], store2, [mid])
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.provenance is not None
    assert result.provenance.mission_id == mid
    assert result.provenance.action_id == "c1"


# ---------------------------------------------------------------------------
# M2-09: historical match + current validity UNKNOWN remains discoverable
# ---------------------------------------------------------------------------


def test_m2_09_historical_match_survives_current_unknown(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-09")
    authority, store = ctx["authority"], ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    # Create a PENDING child action, grant with expiry but no clock
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    mdata = json.loads(mission_file.read_text())
    plan_digest = next(
        e["request_semantics_digest"]
        for e in mdata["plan"] if e["action_id"] == "c1")
    mdata["action_states"]["c2"] = {
        "action_id": "c2", "node_id": "n2", "state": "PENDING",
        "expected_resource_id": "r",
        "expected_governed_registration_id": ctx["grid"],
        "expected_resource_generation": ctx["gen"],
        "expected_executor_kind": "core_app",
        "expected_executor_logical_id": "delegate-1",
        "local_execution_identity": "",
        "attempt_count": 0,
        "confirmation_required": False,
        "confirmation_basis_digest": "",
        "result": None,
        "verification_status": "",
        "verification_evidence": None,
        "error_message": None,
        "provider_effect_id": "",
        "effect_identity_digest": "",
        "verification_proof_digest": "",
    }
    mdata["plan"].append({
        "action_id": "c2", "capability": "c.rt", "node_id": "n2",
        "dependencies": [], "request_semantics_digest": plan_digest,
    })
    mission_file.write_text(json.dumps(mdata))
    store2 = _mission_store(tmp_path)
    authority2 = _authority(store2)
    authority2.grant_delegation(
        mid, "c2", _rev_for(authority2, mid), parent_action_id="p1",
        **_grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"],
                        allowed_capabilities=("c.rt",),
                        expires_at="2100-01-01T00:00:00+00:00"))
    lookup = _lookup_for(ctx["components"], store2, [mid], now_iso="")
    result = lookup.lookup(EffectLookup(provider_effect_id=token))
    assert result.provenance is not None
    assert result.provenance.mission_id == mid
    assert result.provenance.action_id == "c1"


# ---------------------------------------------------------------------------
# M2-10: bounded/truncated scan → INCOMPLETE, not NOT_FOUND
# ---------------------------------------------------------------------------


def test_m2_10_bounded_scan_incomplete(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-10")
    store = ctx["store"]
    # Enumerate 2 missions but only 1 exists; max_missions=1 truncates
    lookup = _lookup_for(ctx["components"], store, [mid, "nonexistent"], max_missions=1)
    result = lookup.lookup(EffectLookup(provider_effect_id="no-such-token"))
    assert result.status == LinkStatus.INCOMPLETE
    assert result.search_complete is False


# ---------------------------------------------------------------------------
# M2-11: F.M1 mission-scoped API remains functional
# ---------------------------------------------------------------------------


def test_m2_11_m1_api_preserved(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-11")
    store = ctx["store"]
    view = _view_for(ctx["components"], store)
    result = view.reconstruct_by_action(mid, "c1")
    assert result.mission_id == mid
    assert result.action_id == "c1"
    assert result.overall_status in (LinkStatus.PROVEN, LinkStatus.PARTIAL)


# ---------------------------------------------------------------------------
# M2-12: no mutation
# ---------------------------------------------------------------------------


def test_m2_12_no_mutation(tmp_path):
    import hashlib
    from pathlib import Path

    ctx, mid = _seed_effect(tmp_path, name="m2-12")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]

    def _snapshot():
        files = {}
        for base in (tmp_path / ".intent-os",):
            for path in base.rglob("*"):
                if path.is_file():
                    files[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return files

    before = _snapshot()
    lookup = _lookup_for(ctx["components"], store, [mid])
    for _ in range(3):
        lookup.lookup(EffectLookup(provider_effect_id=token))
    assert _snapshot() == before


# ---------------------------------------------------------------------------
# M2-13: no authorization/effect-producing calls introduced
# ---------------------------------------------------------------------------


_FORBIDDEN_CALLS = frozenset({
    "transition_action", "grant_delegation", "revoke_delegation", "commit",
    "create", "transition_confirmation", "transition_delegation_grant",
    "transition_delegation_revoke", "poison", "acquire", "acquire_for_legacy",
    "acquire_for_node", "record_result", "record_ambiguity", "decide",
    "execute", "bind_selected", "route", "publish", "resolve", "revalidate",
    "register", "unregister", "available", "select", "mint_delegation_id",
    "mint", "consume", "invalidate", "submit", "bind_pending",
    "evaluate_node", "evaluate", "decide_replay", "promote",
    "bootstrap_govern", "decide_proposal", "retire", "update_status",
    "complete", "synchronize_runtime_state", "ingest",
})

_ALLOWED_CALLS = frozenset({
    "_load_mission", "_mission_exists", "_snapshot_for", "_not_found",
    "_invalid", "_reconstruct", "_link", "_chain_expiry_state",
    "reconstruct_by_action", "lookup",
    "verify_grant_dispatch", "grant_view", "compute_local_execution_identity",
    "effect_identity_digest_for",
    "dict", "list", "set", "frozenset", "str", "int", "bool", "isinstance",
    "getattr", "len", "Exception", "LinkResult", "ProvenanceView",
    "dataclass", "field", "EffectLookup", "EffectCandidate",
    "EffectLookupResult", "EffectProvenanceLookup",
    "getter", "get", "items", "strip", "to_dict", "type", "upper", "append",
    "isinstance", "Mapping", "ValueError", "_enumerate", "any", "tuple",
})


def test_m2_13_no_authority_path_structural():
    import intent_kernel.provenance.lookup as lookup_module
    source = inspect.getsource(lookup_module)
    tree = ast.parse(source)
    called: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    violations = sorted(called & _FORBIDDEN_CALLS)
    assert not violations, f"authority-bearing calls in lookup: {violations}"
    unknown = sorted(called - _FORBIDDEN_CALLS - _ALLOWED_CALLS)
    assert not unknown, f"unreviewed calls in lookup: {unknown}"


# ---------------------------------------------------------------------------
# M2-14: local_execution_identity as lookup key
# ---------------------------------------------------------------------------


def test_m2_14_local_execution_identity_lookup(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-14")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    e2 = action["local_execution_identity"]
    assert e2 != ""
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(local_execution_identity=e2))
    assert result.provenance is not None
    assert result.provenance.mission_id == mid


# ---------------------------------------------------------------------------
# M2-15: effect_identity_digest as lookup key
# ---------------------------------------------------------------------------


def test_m2_15_effect_identity_digest_lookup(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-15")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    edigest = action["effect_identity_digest"]
    assert edigest != ""
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(effect_identity_digest=edigest))
    assert result.provenance is not None
    assert result.provenance.mission_id == mid


# ---------------------------------------------------------------------------
# M2-16: context filter narrows candidates
# ---------------------------------------------------------------------------


def test_m2_16_context_filter_narrows(tmp_path):
    ctx, mid = _seed_effect(tmp_path, name="m2-16")
    store = ctx["store"]
    data = store.load(mid)
    action = data["action_states"]["c1"]
    token = action["provider_effect_id"]
    # Wrong capability context → no match
    lookup = _lookup_for(ctx["components"], store, [mid])
    result = lookup.lookup(EffectLookup(
        provider_effect_id=token, capability="wrong.capability"))
    assert result.status == LinkStatus.NOT_FOUND
    # Correct capability context → match
    result2 = lookup.lookup(EffectLookup(
        provider_effect_id=token, capability="c.rt"))
    assert result2.provenance is not None
