"""FRONT-F.M1 — Authority Provenance View tests.

M1-01..M1-10 plus a structural no-authority-path proof. All fixtures go
through canonical authority transitions; the VIEW under test only reads.
All stores isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import ast
import hashlib
import inspect

import pytest

from intent_kernel.mission import ActionState
from intent_kernel.mission.action_authority import ActionTransitionEvidence
from intent_kernel.provenance.view import (
    AuthorityProvenanceView,
    LinkStatus,
)
from tests.test_m33_2b_delegation import (
    _authority,
    _bind_record,  # noqa: F401 (re-exported for locality)
    _components,
    _drive_authorized,
    _ev,
    _govern,
    _govern_delegate,
    _governed_pair,
    _grant_std,
    _make_node,
    _mission_store,
    _started_mission,
    CountingApp,
)


def _view_for(components, store, installation_id="", now_iso="2026-06-01T00:00:00+00:00"):
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


def _ident(store):
    return store.get_continuity_identity()


# ---------------------------------------------------------------------------
# M1-01: valid mission/action reconstructs the canonical chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_01_granted_action_reconstructs_chain(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-01")
    authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
    _grant_std(authority, ctx)
    view = _view_for(ctx["components"], store, installation_id=_ident(store))
    out = view.reconstruct_by_action(mid, "c1")
    assert out.mission_id == mid
    assert out.action_id == "c1"
    assert out.query_identity == f"{mid}#c1"
    assert out.human_principal == "NOT_RECORDED"
    assert out.sovereign_origin["continuity_match"] is True
    assert out.delegation["link"].status == LinkStatus.PROVEN
    assert out.delegation["historical"]["present"] is True
    assert out.delegation["current"]["valid_now"] is True
    assert out.ceiling["components"]["quantity"] == "absent/deferred (no quantity authority in V1)"
    assert out.dispatch["action_state"] == "PENDING"
    # Never-dispatched action: identity/effect/verification/completion are
    # honestly absent — overall PARTIAL, never PROVEN-by-default.
    assert out.overall_status == LinkStatus.PARTIAL
    assert set(out.missing_links) == {
        "local_execution_identity", "provider_effect_id",
        "effect_attribution", "verification_proof", "completion",
    }
    assert out.ambiguous_links == []
    # Dict round-trip preserves the verdict.
    assert out.to_dict()["overall_status"] == LinkStatus.PARTIAL


@pytest.mark.asyncio
async def test_m1_01b_result_recorded_binds_identity_and_effect(tmp_path):
    """Dispatched-to-RESULT_RECORDED action: identity + effect PROVEN,
    verification/completion still honestly missing."""
    ctx = await _governed_pair(tmp_path, name="m1-01b")
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
        ActionTransitionEvidence(requested_by="t", reason="t",
                                 result={"o": 1},
                                 provider_effect_id="pe-1"))
    view = _view_for(ctx["components"], store, installation_id=_ident(store))
    out = view.reconstruct_by_action(mid, "c1")
    assert out.digests["link"].status == LinkStatus.PROVEN
    assert out.digests["local_execution_identity"] != ""
    assert out.effect["link"].status == LinkStatus.PROVEN
    assert out.effect["provider_effect_id"] == "pe-1"
    assert out.dispatch["action_state"] == "RESULT_RECORDED"
    assert out.overall_status == LinkStatus.PARTIAL
    assert set(out.missing_links) == {"verification_proof", "completion"}


@pytest.mark.asyncio
async def test_m1_01c_completed_verified_action_fully_proven(tmp_path):
    """Full canonical lifecycle to COMPLETED: every applicable link
    PROVEN, overall PROVEN."""
    from tests.test_m32b2_action_authority import _gate_proof
    ctx = await _governed_pair(tmp_path, name="m1-01c")
    authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
    rev = authority.transition_action(
        mid, "c1", ctx["rev"], ActionState.PENDING,
        ActionState.AUTHORIZED, _ev()).mission_revision
    for target in (ActionState.DISPATCH_INTENT_RECORDED,
                   ActionState.DISPATCHING):
        rev = authority.transition_action(
            mid, "c1", rev,
            ActionState.AUTHORIZED if target is ActionState.DISPATCH_INTENT_RECORDED else ActionState.DISPATCH_INTENT_RECORDED,
            target, _ev()).mission_revision
    rev = authority.transition_action(
        mid, "c1", rev, ActionState.DISPATCHING,
        ActionState.RESULT_RECORDED,
        ActionTransitionEvidence(requested_by="t", reason="t",
                                 result={"o": 1},
                                 provider_effect_id="pe-9")).mission_revision
    rev = authority.transition_action(
        mid, "c1", rev, ActionState.RESULT_RECORDED,
        ActionState.VERIFICATION_REQUIRED, _ev()).mission_revision
    plan_digest = next(
        e["request_semantics_digest"]
        for e in store.load(mid)["plan"] if e["action_id"] == "c1")
    # _gate_proof mints via its own event loop: run it off-thread since
    # this test already runs inside a loop.
    import asyncio as _asyncio
    proof = await _asyncio.to_thread(_gate_proof, mid, "c1", plan_digest)
    rev = authority.transition_action(
        mid, "c1", rev, ActionState.VERIFICATION_REQUIRED,
        ActionState.VERIFIED,
        ActionTransitionEvidence(requested_by="t", reason="t",
                                 verification_proof=proof)).mission_revision
    authority.transition_action(
        mid, "c1", rev, ActionState.VERIFIED, ActionState.COMPLETED,
        ActionTransitionEvidence(requested_by="t", reason="t",
                                 completion_basis=proof))
    view = _view_for(ctx["components"], store, installation_id=_ident(store))
    out = view.reconstruct_by_action(mid, "c1")
    assert out.verification["link"].status == LinkStatus.PROVEN
    assert out.verification["proof_digest"] != ""
    assert out.completion["link"].status == LinkStatus.PROVEN
    assert out.overall_status == LinkStatus.PROVEN
    assert out.missing_links == []


# ---------------------------------------------------------------------------
# M1-02 / M1-03: unknown mission / action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_02_unknown_mission_not_found(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-02")
    view = _view_for(ctx["components"], ctx["store"])
    out = view.reconstruct_by_action("no-such-mission", "c1")
    assert out.overall_status == LinkStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_m1_03_unknown_action_not_found(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-03")
    view = _view_for(ctx["components"], ctx["store"])
    out = view.reconstruct_by_action(ctx["mid"], "no-such-action")
    assert out.overall_status == LinkStatus.NOT_FOUND
    assert out.mission_id == ctx["mid"]


# ---------------------------------------------------------------------------
# M1-04: covered by M1-01 missing-link set (PARTIAL, never PROVEN)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_04_missing_optional_evidence_is_partial(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-04")
    view = _view_for(ctx["components"], ctx["store"])
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.overall_status == LinkStatus.PARTIAL
    assert "verification_proof" in out.missing_links
    assert out.verification["link"].status == LinkStatus.INCOMPLETE


# ---------------------------------------------------------------------------
# M1-05: revoked delegation — history preserved, current invalid
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_05_revoked_grant_history_preserved_current_invalid(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-05")
    authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
    _grant_std(authority, ctx)
    rev = store.load(mid)["revision"]
    authority.revoke_delegation(mid, "c1", rev, "m1-05 audit")
    view = _view_for(ctx["components"], store, installation_id=_ident(store))
    out = view.reconstruct_by_action(mid, "c1")
    assert out.delegation["historical"]["present"] is True
    assert out.delegation["historical"]["state"] == "REVOKED"
    assert out.delegation["historical"]["revoke_reason"] == "m1-05 audit"
    assert out.delegation["current"]["valid_now"] is False
    assert "ancestor-not-active" in out.delegation["current"]["detail"]
    # Historical attribution survives revocation (not INVALID, not wiped).
    assert out.overall_status != LinkStatus.INVALID
    assert out.delegation["link"].status == LinkStatus.PROVEN


# ---------------------------------------------------------------------------
# M1-06: generation advanced — history preserved, current false
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_06_generation_advanced_history_preserved_current_false(tmp_path):
    from intent_kernel.rrm.models import (
        ConditionalResourceStatusRequest,
        ConditionalUpdateOutcome,
        ResourceStatus,
        ResourceType,
    )
    ctx = await _governed_pair(tmp_path, name="m1-06")
    authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
    _grant_std(authority, ctx)
    cap = "c.rt"
    before = ctx["components"].resource_manager.get_capability(cap)
    result = ctx["components"].resource_manager.conditional_update_status(
        ConditionalResourceStatusRequest(
            resource_type=ResourceType.CAPABILITY,
            resource_id=cap,
            expected_governed_registration_id=before.governed_registration_id,
            expected_generation=before.generation,
            desired_status=(ResourceStatus.UNAVAILABLE
                            if before.status == ResourceStatus.ACTIVE
                            else ResourceStatus.ACTIVE),
        )
    )
    assert result.outcome is ConditionalUpdateOutcome.APPLIED
    view = _view_for(ctx["components"], store, installation_id=_ident(store))
    out = view.reconstruct_by_action(mid, "c1")
    # Durable expectation still names the old generation...
    assert out.historical["binding"]["generation"] == ctx["gen"]
    # ...while current observation differs → not executable now.
    assert out.current["binding"]["executable_now"] is False
    changed = (out.current["binding"]["observed_generation"] != ctx["gen"]
               or out.current["binding"]["observed_eligible"] is False)
    assert changed


# ---------------------------------------------------------------------------
# M1-07: tampered canonical data fails closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_07_tampered_identity_is_invalid(tmp_path):
    import json
    from pathlib import Path
    ctx = await _governed_pair(tmp_path, name="m1-07")
    authority, store, mid = ctx["authority"], ctx["store"], ctx["mid"]
    _drive_authorized(authority, mid, "c1")
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    data = json.loads(mission_file.read_text())
    data["action_states"]["c1"]["local_execution_identity"] = "forged"
    mission_file.write_text(json.dumps(data))
    view = _view_for(ctx["components"], store)
    out = view.reconstruct_by_action(mid, "c1")
    assert out.overall_status == LinkStatus.INVALID


# ---------------------------------------------------------------------------
# M1-08: telemetry absence leaves canonical reconstruction unaffected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_08_telemetry_absence_unaffected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-08")
    _grant_std(ctx["authority"], ctx)
    view = _view_for(ctx["components"], ctx["store"])
    first = view.reconstruct_by_action(ctx["mid"], "c1").to_dict()
    # Flood the (never-consulted) event bus with conflicting junk.
    bus = ctx["components"].event_publisher
    for i in range(5):
        try:
            res = bus.publish("capability.audit", {"mission_id": ctx["mid"],
                                                   "capability": "LIES",
                                                   "success": True})
            if hasattr(res, "__await__"):
                await res
        except Exception:
            pass
    second = view.reconstruct_by_action(ctx["mid"], "c1").to_dict()
    assert first == second
    # Structural: the view constructor accepts no telemetry/event parameter.
    import inspect as _inspect
    params = set(_inspect.signature(AuthorityProvenanceView).parameters)
    assert not (params & {"event_bus", "event_publisher", "telemetry",
                          "audit_log", "audit_writer"})


# ---------------------------------------------------------------------------
# M1-09: human principal never inferred
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_09_human_principal_not_recorded(tmp_path):
    ctx = await _governed_pair(tmp_path, name="m1-09")
    _grant_std(ctx["authority"], ctx)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]))
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.human_principal == "NOT_RECORDED"
    assert out.sovereign_origin["continuity_match"] is True


# ---------------------------------------------------------------------------
# M1-10: query performs zero persisted mutation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_10_query_performs_zero_persisted_mutation(tmp_path):
    from pathlib import Path
    ctx = await _governed_pair(tmp_path, name="m1-10")
    _grant_std(ctx["authority"], ctx)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]))

    def _snapshot():
        files = {}
        for base in (tmp_path / ".intent-os",):
            for path in base.rglob("*"):
                if path.is_file():
                    files[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return files

    before = _snapshot()
    for _ in range(3):
        out = view.reconstruct_by_action(ctx["mid"], "c1")
        assert out.overall_status in (LinkStatus.PROVEN, LinkStatus.PARTIAL)
    assert _snapshot() == before


# ---------------------------------------------------------------------------
# No-authority-path: structural proof (not mocks)
# ---------------------------------------------------------------------------

_FORBIDDEN_CALLS = frozenset({
    # mission authority + store mutation
    "transition_action", "grant_delegation", "revoke_delegation", "commit",
    "create", "transition_confirmation", "transition_delegation_grant",
    "transition_delegation_revoke", "poison",
    # dispatch guard authority
    "acquire", "acquire_for_legacy", "acquire_for_node", "record_result",
    "record_ambiguity", "decide",
    # execution / invocation
    "execute", "bind_selected", "route", "publish",
    # binding / registry authority
    "resolve", "revalidate", "register", "unregister", "available", "select",
    # minting / consumption
    "mint_delegation_id", "mint", "consume", "invalidate", "submit",
    "bind_pending",
    # gates / promotion / retirement / mutation
    "evaluate_node", "evaluate", "decide_replay", "promote",
    "bootstrap_govern", "decide_proposal", "retire", "update_status",
    "complete", "synchronize_runtime_state", "ingest",
})

_ALLOWED_CALLS = frozenset({
    # view's own private machinery + injected narrow ports
    "_not_found", "_invalid", "_reconstruct", "_snapshot_for",
    "_load_mission", "_mission_exists",
    "_link",
    # pure recompute collaborators (explicitly allowlisted by FRONT-F)
    "verify_grant_dispatch", "grant_view", "compute_local_execution_identity",
    "effect_identity_digest_for",
    # pure clock-evidence read (FRONT-F.M1.1/M1.2, no authority conferred)
    "_chain_expiry_state",
    # stdlib builtins / dataclass machinery / plain accessors used in view logic
    "dict", "list", "set", "frozenset", "str", "int", "bool", "isinstance",
    "getattr", "len", "Exception",
    # view's own value constructors (no authority conferred)
    "LinkResult", "ProvenanceView", "dataclass", "field",
    # read-port invocation + mapping accessors
    "getter", "get", "items", "strip", "to_dict", "type", "upper", "append",
})


def test_no_authority_path_structural():
    """AST proof: view.py invokes no authority-bearing operation.

    Structural, not mock-based: even a test double recording calls could
    not exist, because the view never names these operations as callees.
    """
    import intent_kernel.provenance.view as view_module
    source = inspect.getsource(view_module)
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
    assert not violations, f"authority-bearing calls in view: {violations}"
    unknown = sorted(called - _FORBIDDEN_CALLS - _ALLOWED_CALLS)
    assert not unknown, f"unreviewed calls in view: {unknown}"


def test_constructor_accepts_only_narrow_ports():
    params = set(inspect.signature(AuthorityProvenanceView).parameters)
    assert params == {"load_mission", "mission_exists", "rrm_capability",
                      "rrm_agent", "rrm_provider", "installation_id",
                      "now_iso"}, params


# ---------------------------------------------------------------------------
# CLOCK-01..05: explicit-clock validity hardening (FRONT-F.M1.1)
# ---------------------------------------------------------------------------

_FUTURE_EXPIRY = "2100-01-01T00:00:00+00:00"
_MID_EXPIRY = "2027-06-01T00:00:00+00:00"
_BEFORE_EXPIRY = "2026-06-01T00:00:00+00:00"
_AFTER_EXPIRY = "2028-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_clock_01_expiry_without_clock_is_unknown_never_true(tmp_path):
    """CLOCK-01: expiry-bearing grant + now_iso == '' -> historical
    preserved, current validity NOT True, clock evidence explicitly missing."""
    ctx = await _governed_pair(tmp_path, name="clock-01")
    _grant_std(ctx["authority"], ctx, expires_at=_FUTURE_EXPIRY)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["historical"]["present"] is True
    assert out.delegation["historical"]["state"] == "ACTIVE"
    assert out.delegation["current"]["valid_now"] is False
    assert out.delegation["current"]["valid_now"] is not True
    assert out.delegation["current"]["clock_evidence"] == "unavailable"
    assert out.delegation["link"].status == LinkStatus.INCOMPLETE
    assert "current_clock" in out.missing_links
    assert out.overall_status != LinkStatus.PROVEN


@pytest.mark.asyncio
async def test_clock_02_expiry_with_clock_before_expiry_proven(tmp_path):
    """CLOCK-02: same grant + explicit now before expiry -> canonical
    pure re-proof applies, current valid."""
    ctx = await _governed_pair(tmp_path, name="clock-02")
    _grant_std(ctx["authority"], ctx, expires_at=_FUTURE_EXPIRY)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]),
                     now_iso=_BEFORE_EXPIRY)
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["link"].status == LinkStatus.PROVEN
    assert out.delegation["current"]["valid_now"] is True
    assert "current_clock" not in out.missing_links


@pytest.mark.asyncio
async def test_clock_03_expiry_with_clock_after_expiry_invalid_current(tmp_path):
    """CLOCK-03: same grant shape + explicit now after expiry -> historical
    preserved, current false via ancestor-expired."""
    ctx = await _governed_pair(tmp_path, name="clock-03")
    _grant_std(ctx["authority"], ctx, expires_at=_MID_EXPIRY)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]),
                     now_iso=_AFTER_EXPIRY)
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["historical"]["present"] is True
    assert out.delegation["current"]["valid_now"] is False
    assert "ancestor-expired" in out.delegation["current"]["detail"]
    assert out.overall_status != LinkStatus.INVALID


@pytest.mark.asyncio
async def test_clock_04_no_expiry_without_clock_unchanged(tmp_path):
    """CLOCK-04: non-expiry-bearing grant + no clock -> existing semantics
    preserved (no unrelated regression)."""
    ctx = await _governed_pair(tmp_path, name="clock-04")
    _grant_std(ctx["authority"], ctx)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["link"].status == LinkStatus.PROVEN
    assert out.delegation["current"]["valid_now"] is True
    assert "current_clock" not in out.missing_links


@pytest.mark.asyncio
async def test_clock_05_missing_clock_query_zero_mutation(tmp_path):
    """CLOCK-05: clockless query performs zero persisted mutation."""
    ctx = await _governed_pair(tmp_path, name="clock-05")
    _grant_std(ctx["authority"], ctx, expires_at=_FUTURE_EXPIRY)
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")

    def _snapshot():
        files = {}
        for base in (tmp_path / ".intent-os",):
            for path in base.rglob("*"):
                if path.is_file():
                    files[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return files

    before = _snapshot()
    for _ in range(3):
        out = view.reconstruct_by_action(ctx["mid"], "c1")
        assert out.delegation["current"]["valid_now"] is False
    assert _snapshot() == before


# ---------------------------------------------------------------------------
# CLOCK-06..10: expiry-dependency fail-closed tri-state (FRONT-F.M1.2)
# ---------------------------------------------------------------------------

def test_clock_06_expiry_state_tristate_semantics():
    """CLOCK-06 unit: PRESENT / ABSENT / UNKNOWN are distinct; inspection
    uncertainty never reads as proven-absent."""
    from intent_kernel.provenance import view as _view
    assert _view._chain_expiry_state(None) == "ABSENT"
    assert _view._chain_expiry_state([]) == "ABSENT"
    assert _view._chain_expiry_state([("a", "b", {})]) == "ABSENT"
    assert _view._chain_expiry_state(
        [("a", "b", {"delegation_expires_at": _FUTURE_EXPIRY})]) == "PRESENT"
    # Malformed chains: uncertainty, never ABSENT.
    assert _view._chain_expiry_state([(1, 2)]) == "UNKNOWN"
    assert _view._chain_expiry_state(42) == "UNKNOWN"
    assert _view._chain_expiry_state("not-a-chain") == "UNKNOWN"


@pytest.mark.asyncio
async def test_clock_06b_forced_uncertainty_never_currently_true(tmp_path, monkeypatch):
    """CLOCK-06 end-to-end: even when chain inspection is forced
    uncertain, current validity is NOT True and no PROVEN current
    validity is reported."""
    from intent_kernel.provenance import view as _view
    ctx = await _governed_pair(tmp_path, name="clock-06b")
    _grant_std(ctx["authority"], ctx)
    monkeypatch.setattr(_view, "_chain_expiry_state",
                        lambda chain: "UNKNOWN")
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["current"]["valid_now"] is False
    assert out.delegation["current"]["valid_now"] is not True
    assert out.delegation["current"]["clock_evidence"] == "indeterminate"
    assert out.delegation["link"].status == LinkStatus.INCOMPLETE
    assert "current_clock" in out.missing_links
    assert out.overall_status != LinkStatus.PROVEN


@pytest.mark.asyncio
async def test_clock_07_sound_chain_absent_stays_proven_without_clock(tmp_path):
    """CLOCK-07: structurally valid non-expiring chain inspects ABSENT and
    keeps existing PROVEN/current-valid semantics without a clock."""
    from intent_kernel.mission import delegation as _dlg
    from intent_kernel.provenance import view as _view
    ctx = await _governed_pair(tmp_path, name="clock-07")
    _grant_std(ctx["authority"], ctx)
    data = ctx["store"].load(ctx["mid"])
    ok, why, chain = _dlg.verify_grant_dispatch(
        {"action_states": dict(data["action_states"]),
         "plan": list(data["plan"])},
        "c1", now_iso="")
    assert ok, why
    assert _view._chain_expiry_state(chain) == "ABSENT"
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")
    out = view.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["link"].status == LinkStatus.PROVEN
    assert out.delegation["current"]["valid_now"] is True
    assert "current_clock" not in out.missing_links


@pytest.mark.asyncio
async def test_clock_08_ancestor_expiry_without_clock_is_unknown(tmp_path):
    """CLOCK-08: multi-grant chain (nA -> nB -> nC) where the ancestor
    grant bears expiry: clockless query of the leaf reports INCOMPLETE
    current validity, never True, with history preserved."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.clock-08")
    grid, gen, _snap = _govern(components, app)
    _govern_delegate(components, agent_id="delegate-1",
                     grid="gov-delegate-1")
    mission = await _started_mission(components, "clock-08")
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    cap = "resource.clock-08"
    nodes = {
        nid: _make_node(node_id=nid, agent_id="delegate-1",
                        idempotency_key=f"rk-{nid}", capability=cap)
        for nid in ("nA", "nB", "nC")
    }
    _bind_record(store, mid, [
        {"node": nodes[nid], "grid": grid, "gen": gen,
         "executor": "delegate-1", "resource_id": "t1"}
        for nid in ("nA", "nB", "nC")
    ])
    authority = _authority(store)

    def _grant(child, parent, rev, targets, expires):
        return authority.grant_delegation(
            mid, child, rev, parent_action_id=parent,
            delegate_agent_id="delegate-1",
            delegate_governed_registration_id="gov-delegate-1",
            allowed_capabilities=[cap],
            allowed_resources=[{"resource_id": "t1",
                                "governed_registration_id": grid,
                                "generation": gen}],
            allowed_targets=list(targets),
            max_risk_level="critical", max_timeout_seconds=3600.0,
            require_verification=True,
            max_side_effect="EXTERNAL_IRREVERSIBLE",
            expires_at=expires).mission_revision

    rev = authority.transition_action(
        mid, "nA", 1, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision
    rev = _grant("nB", "nA", rev, ("t1",), _FUTURE_EXPIRY)
    rev = authority.transition_action(
        mid, "nB", rev, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision
    # Nested edge under a bounded parent must itself be bounded
    # (lifetime-subset); the ancestor expiry is what the view must detect.
    _grant("nC", "nB", rev, ("t1",), _FUTURE_EXPIRY)
    view = _view_for(components, store, installation_id=_ident(store),
                     now_iso="")
    out = view.reconstruct_by_action(mid, "nC")
    assert out.delegation["historical"]["present"] is True
    assert out.delegation["current"]["valid_now"] is False
    assert out.delegation["current"]["valid_now"] is not True
    assert out.delegation["current"]["clock_evidence"] == "unavailable"
    assert out.delegation["link"].status == LinkStatus.INCOMPLETE
    assert "current_clock" in out.missing_links
    assert out.overall_status != LinkStatus.PROVEN


@pytest.mark.asyncio
async def test_clock_09_inspection_failure_preserves_history(tmp_path, monkeypatch):
    """CLOCK-09: forced inspection uncertainty changes only the current
    section; the historical grant copy is byte-identical and overall
    never becomes INVALID."""
    from intent_kernel.provenance import view as _view
    ctx = await _governed_pair(tmp_path, name="clock-09")
    _grant_std(ctx["authority"], ctx)
    plain = _view_for(ctx["components"], ctx["store"],
                      installation_id=_ident(ctx["store"]), now_iso="")
    base = plain.reconstruct_by_action(ctx["mid"], "c1")
    assert base.delegation["link"].status == LinkStatus.PROVEN
    monkeypatch.setattr(_view, "_chain_expiry_state",
                        lambda chain: "UNKNOWN")
    forced = _view_for(ctx["components"], ctx["store"],
                       installation_id=_ident(ctx["store"]), now_iso="")
    out = forced.reconstruct_by_action(ctx["mid"], "c1")
    assert out.delegation["historical"] == base.delegation["historical"]
    assert out.delegation["link"].status == LinkStatus.INCOMPLETE
    assert out.overall_status != LinkStatus.INVALID
    assert out.overall_status == LinkStatus.PARTIAL


@pytest.mark.asyncio
async def test_clock_10_uncertain_inspection_zero_mutation(tmp_path, monkeypatch):
    """CLOCK-10: repeated reconstructions under forced inspection
    uncertainty persist zero durable mutation."""
    from intent_kernel.provenance import view as _view
    ctx = await _governed_pair(tmp_path, name="clock-10")
    _grant_std(ctx["authority"], ctx, expires_at=_FUTURE_EXPIRY)
    monkeypatch.setattr(_view, "_chain_expiry_state",
                        lambda chain: "UNKNOWN")
    view = _view_for(ctx["components"], ctx["store"],
                     installation_id=_ident(ctx["store"]), now_iso="")

    def _snapshot():
        files = {}
        for base in (tmp_path / ".intent-os",):
            for path in base.rglob("*"):
                if path.is_file():
                    files[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return files

    before = _snapshot()
    for _ in range(3):
        out = view.reconstruct_by_action(ctx["mid"], "c1")
        assert out.delegation["current"]["valid_now"] is False
    assert _snapshot() == before
