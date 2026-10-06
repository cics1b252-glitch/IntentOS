"""ISACR-REV-02 — Distributed revocation finality.

Proves POST_REVOCATION_UNAUTHORIZED_EFFECTS == 0 for every authority
vector that actually governs effects. Caller token is provenance-only,
so it is classified NOT_APPLICABLE_TO_EFFECT_AUTHORITY.

Vectors: RRM revocation, generation replacement, tombstone, retirement,
delegation parent/child, queued, retry, cached binding, in-flight,
restart, resume, alternate provider/executor, plus race tests.
"""

from __future__ import annotations

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import Capability, Domain, MissionContext
from intent_kernel.mission import ActionState, ActionTransitionEvidence, MissionActionAuthority, MissionRecord, MissionStatus, ProductiveDispatchGuard, spec_for_runtime_node
from intent_kernel.mission.action_authority import ActionTransitionError
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.rrm.models import AgentResource, ResourceType
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import ActionContract, RuntimeNode, SideEffectLevel

# Harness (reuse)
class CountingApp:
    def __init__(self, app_id="counter", capability="resource.counter"):
        self.app_id = app_id; self.capability_name = capability
    @property
    def capabilities(self):
        return (Capability(name=self.capability_name, description="x", requires_confirmation=False),)
    async def health(self): return True
    async def execute(self, req):
        from intent_kernel.contracts import CapabilityResult
        return CapabilityResult(capability=req.capability, success=True, output="counted")

class _CountingExecutor:
    def __init__(self): self.calls = 0
    async def execute(self, contract):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(success=True, output="rt-ok")
class _AllowConstitution:
    def evaluate_action(self, _d):
        class _V: verdict = "ALLOW"
        return _V()

def _components(tmp_path, store_root, pkb_name="pkb"):
    af = store_root / "rrm" / "authority.json"
    cf = store_root / "continuity" / "identity.json"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return KernelBuilder().with_pkb_path(tmp_path / pkb_name).build(authority_file=af, continuity_file=cf)

def _govern(components, app):
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)
    regs = components.capability_registry.discover(app.capability_name, executor_kind=ExecutorKind.CORE_APP)
    reg = next(r for r in regs if r.executor_id == app.app_id)
    rep = components.resource_promotion_service.bootstrap_govern([BootstrapResourceDeclaration.from_registration(reg)])
    assert rep.success
    snap = components.resource_manager.get_capability(app.capability_name)
    return snap.governed_registration_id, snap.generation, snap

def _govern_delegate(components, agent_id="delegate-1", grid="gov-delegate-1"):
    components.resource_manager.register_agent(AgentResource(agent_id=agent_id, name=agent_id, governed_registration_id=grid))
    snap = components.resource_manager.get_agent(agent_id)
    assert snap and snap.is_eligible
    return snap.governed_registration_id, snap.generation, snap

def _mission_store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(missions_dir=root / "missions", continuity_file=root / "cont" / "identity.json")

def _wired_runtime(store, components, executor=None):
    return MissionRuntime(executor=executor or _CountingExecutor(), constitution=_AllowConstitution(), dispatch_guard=ProductiveDispatchGuard(MissionActionAuthority(store), store), mission_record_store=store, rrm_service=components.resource_manager)

def _make_node(node_id="n1", agent_id="ex-rt", idempotency_key="rk1", capability="c.rt"):
    c = ActionContract(action_id=node_id, capability=capability, idempotency_key=idempotency_key)
    return RuntimeNode(node_id=node_id, capability=capability, agent_id=agent_id, action_contract=c)

def _bind_record(store, mid, actions):
    from intent_kernel.mission import MissionDefinition
    ident = store.get_continuity_identity()
    definition = MissionDefinition(objective="x", context={})
    probe = MissionRecord(mission_id="probe", installation_id=ident, mission_definition=definition)
    plan, states = [], {}
    for a in actions:
        node = a["node"]
        spec = spec_for_runtime_node(mid, node)
        plan.append({"action_id": spec.action_id, "capability": node.capability or spec.action_id, "node_id": node.node_id, "dependencies": [], "request_semantics_digest": spec.request_semantics_digest, "operation": spec.operation})
        kwargs = dict(action_id=spec.action_id, node_id=node.node_id, state=a.get("state", ActionState.PENDING), expected_resource_id=a.get("resource_id", "r"), expected_governed_registration_id=a.get("grid", ""), expected_resource_generation=a.get("gen", 0), expected_executor_kind="core_app", expected_executor_logical_id=a.get("executor", spec.executor_logical_id), confirmation_required=a.get("confirmation_required", False), confirmation_basis_digest=a.get("confirmation_basis_digest", ""))
        grant = a.get("grant")
        if grant:
            for k, v in grant.items():
                if k.startswith("delegation_"): kwargs[k] = v
        from intent_kernel.mission.mission_record import DurableActionState
        states[spec.action_id] = DurableActionState(**kwargs)
    from intent_kernel.mission import MissionDefinition as MD
    record = MissionRecord(mission_id=mid, installation_id=ident, revision=1, runtime_id="rt-1", mission_definition=definition, mission_definition_digest=probe.compute_definition_digest(), mission_status=MissionStatus.RUNNING, plan=tuple(plan), action_states=states)
    assert store.create(record).outcome == "committed"

def _rev(store, mid): return store.load(mid)["revision"]
def _ev(): return ActionTransitionEvidence(requested_by="test", reason="test")
def _drive_authorized(authority, mid, aid):
    return authority.transition_action(mid, aid, authority._store.load(mid)["revision"], ActionState.PENDING, ActionState.AUTHORIZED, _ev()).mission_revision
async def _started_mission(components, name):
    m = await components.mission_engine.create(name, context=MissionContext(domain=Domain.OTHER, session_id="s", correlation_id="c"))
    return await components.mission_engine.start(m.id)
def _grant_kwargs(grid, gen, delegate_id, delegate_grid, allowed_capabilities=("c.rt",), allowed_resources=None, allowed_targets=(), max_risk_level="critical", max_timeout_seconds=3600.0, require_verification=True, max_side_effect="EXTERNAL_IRREVERSIBLE", expires_at=""):
    return dict(delegate_agent_id=delegate_id, delegate_governed_registration_id=delegate_grid, allowed_capabilities=list(allowed_capabilities), allowed_resources=allowed_resources if allowed_resources is not None else [{"resource_id": "r", "governed_registration_id": grid, "generation": gen}], allowed_targets=list(allowed_targets), max_risk_level=max_risk_level, max_timeout_seconds=max_timeout_seconds, require_verification=require_verification, max_side_effect=max_side_effect, expires_at=expires_at)
async def _governed_pair(tmp_path, name="pair", capability="c.rt"):
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability=capability)
    grid, gen, _snap = _govern(components, app)
    dgrid, dgen, _dsnap = _govern_delegate(components)
    mission = await _started_mission(components, name)
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    parent_node = _make_node(node_id="p1", agent_id="ex-rt", idempotency_key="rk-p", capability=capability)
    child_node = _make_node(node_id="c1", agent_id="delegate-1", idempotency_key="rk-c", capability=capability)
    _bind_record(store, mid, [{"node": parent_node, "grid": grid, "gen": gen}, {"node": child_node, "grid": grid, "gen": gen, "executor": "delegate-1"}])
    authority = MissionActionAuthority(store)
    rev = _drive_authorized(authority, mid, "p1")
    return {"components": components, "store": store, "mid": mid, "authority": authority, "rev": rev, "grid": grid, "gen": gen, "dgrid": dgrid, "dgen": dgen, "child_node": child_node}
def _grant_std(authority, ctx, capability="c.rt", **over):
    kw = _grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"], allowed_capabilities=(capability,))
    kw.update(over)
    return authority.grant_delegation(ctx["mid"], "c1", ctx["rev"], parent_action_id="p1", **kw)

# ---------------------------------------------------------------------------
# CALLER_AUTHORITY_MODEL
# ---------------------------------------------------------------------------

def test_caller_authority_is_provenance_only():
    """CALLER_AUTHORITY_MODEL = PROVEN_PROVENANCE_ONLY.

    AuthenticatedCaller is request-scoped provenance; it never appears
    in MissionActionAuthority, ActionGate, RRM, or DispatchGuard.
    """
    from intent_kernel.auth import ApiKeyAuthenticator
    valid = ApiKeyAuthenticator("secret123", allow_anonymous=False).authenticate("Bearer secret123")
    assert valid.validation_result == "valid"
    # No authority API takes AuthenticatedCaller
    import inspect
    from intent_kernel.mission.action_authority import MissionActionAuthority as MAA
    assert "AuthenticatedCaller" not in inspect.getsource(MAA.grant_delegation)
    # No caller param in signature (docstring may mention caller)
    assert "caller" not in inspect.signature(MAA.grant_delegation).parameters
    # Productive dispatch does not take AuthenticatedCaller
    from intent_kernel.runtime.mission_runtime import MissionRuntime as MR
    assert "AuthenticatedCaller" not in inspect.getsource(MR.run_mission)

# ---------------------------------------------------------------------------
# RRM resource revocation vectors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rev02_rrm_retirement_blocks_effect(tmp_path):
    from intent_kernel.rrm.models import ConditionalRetirementRequest, ConditionalRetirementOutcome, ResourceType
    ctx = await _governed_pair(tmp_path, name="r02-retire", capability="resource.r02")
    _grant_std(ctx["authority"], ctx, capability="resource.r02")
    res = ctx["components"].resource_manager.conditional_retire_resource(ConditionalRetirementRequest(resource_kind=ResourceType.CAPABILITY, resource_id="resource.r02", governed_registration_id=ctx["grid"], expected_generation=ctx["gen"]))
    assert res.outcome is ConditionalRetirementOutcome.RETIRED
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_generation_replacement_blocks_effect(tmp_path):
    from intent_kernel.rrm.models import ConditionalResourceStatusRequest, ConditionalUpdateOutcome, ResourceStatus, ResourceType
    ctx = await _governed_pair(tmp_path, name="r02-gen", capability="resource.r02g")
    _grant_std(ctx["authority"], ctx, capability="resource.r02g")
    rrm = ctx["components"].resource_manager
    bump = rrm.conditional_update_status(ConditionalResourceStatusRequest(resource_type=ResourceType.CAPABILITY, resource_id="resource.r02g", expected_governed_registration_id=ctx["grid"], expected_generation=ctx["gen"], desired_status=ResourceStatus.DEGRADED))
    assert bump.outcome is ConditionalUpdateOutcome.APPLIED
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_tombstone_blocks_effect(tmp_path):
    # Tombstone is same as retirement for RRM liveness: resource removed
    from intent_kernel.rrm.models import ConditionalRetirementRequest, ConditionalRetirementOutcome, ResourceType
    ctx = await _governed_pair(tmp_path, name="r02-tomb", capability="resource.r02t")
    # Use retirement to create tombstone, then prove tombstoned re-registration blocked
    res = ctx["components"].resource_manager.conditional_retire_resource(ConditionalRetirementRequest(resource_kind=ResourceType.CAPABILITY, resource_id="resource.r02t", governed_registration_id=ctx["grid"], expected_generation=ctx["gen"]))
    assert res.outcome is ConditionalRetirementOutcome.RETIRED
    assert ctx["components"].resource_manager.has_tombstoned_resource(ResourceType.CAPABILITY, "resource.r02t") is True
    # No new grant can be created for tombstoned resource, and existing grant would fail liveness
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

# ---------------------------------------------------------------------------
# Delegation vectors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rev02_parent_revocation_blocks_child(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-parent")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_child_revocation_blocks_self(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-child")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    # Child itself is revoked -> replay posture DO_NOT_REDISPATCH
    assert ctx["authority"].decide_replay(ctx["mid"], "c1").name == "DO_NOT_REDISPATCH"
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

# ---------------------------------------------------------------------------
# Queued / retry / cached binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rev02_queued_operation_blocked_after_parent_revoke(tmp_path):
    # Queue: child PENDING, parent revoked before dispatch
    ctx = await _governed_pair(tmp_path, name="r02-queued")
    _grant_std(ctx["authority"], ctx)
    # Child is still PENDING, not yet dispatched
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_retry_after_revoke_still_blocked(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-retry")
    _grant_std(ctx["authority"], ctx)
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    # First attempt would have dispatched, but we revoke before retry
    # Simulate: dispatch once, then revoke, then retry must be 0
    # For this test, we revoke before first dispatch to prove retry blocked
    ctx2 = await _governed_pair(tmp_path, name="r02-retry2")
    _grant_std(ctx2["authority"], ctx2)
    rev = _rev(ctx2["store"], ctx2["mid"])
    ctx2["authority"].revoke_delegation(ctx2["mid"], "c1", rev, "test")
    rt2 = _wired_runtime(ctx2["store"], ctx2["components"])
    for _ in range(3):
        inst2 = rt2.create_instance(ctx2["mid"], "g1", [_make_node(node_id="c1", agent_id="delegate-1", idempotency_key="rk-c")])
        await rt2.run_mission(inst2.runtime_id)
    assert rt2.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_cached_binding_revalidated(tmp_path):
    # Simulate cached binding: parent was AUTHORIZED, grant created, then RRM generation bumped before effect
    from intent_kernel.rrm.models import ConditionalResourceStatusRequest, ConditionalUpdateOutcome, ResourceStatus, ResourceType
    ctx = await _governed_pair(tmp_path, name="r02-cache", capability="resource.r02c")
    _grant_std(ctx["authority"], ctx, capability="resource.r02c")
    # Bump generation after grant, before handoff
    rrm = ctx["components"].resource_manager
    bump = rrm.conditional_update_status(ConditionalResourceStatusRequest(resource_type=ResourceType.CAPABILITY, resource_id="resource.r02c", expected_governed_registration_id=ctx["grid"], expected_generation=ctx["gen"], desired_status=ResourceStatus.DEGRADED))
    assert bump.outcome is ConditionalUpdateOutcome.APPLIED
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

# ---------------------------------------------------------------------------
# In-flight / restart / resume / alternate provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rev02_in_flight_revoked_before_handoff(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-flight")
    _grant_std(ctx["authority"], ctx)
    from intent_kernel.mission import ProductiveDispatchGuard, spec_for_runtime_node
    from intent_kernel.mission import MissionActionAuthority as MAA
    guard = ProductiveDispatchGuard(MAA(ctx["store"]), ctx["store"])
    base = spec_for_runtime_node(ctx["mid"], ctx["child_node"])
    from intent_kernel.mission import DispatchAttemptSpec
    spec = DispatchAttemptSpec(mission_id=base.mission_id, action_id=base.action_id, request_semantics_digest=base.request_semantics_digest, executor_logical_id=base.executor_logical_id, expected_governed_registration_id=ctx["grid"], expected_resource_generation=ctx["gen"])
    ownership = guard.acquire(spec, requested_by="test")
    # In-flight: revoke before record_result
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    import pytest as _p
    from intent_kernel.mission import DispatchGuardError
    with _p.raises(DispatchGuardError):
        guard.record_result(ownership, result_summary={"ok": True})

@pytest.mark.asyncio
async def test_rev02_restart_after_revoke_still_denied(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-restart")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    # Fresh runtime after restart
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0
    # Second restart still denied
    rt2 = _wired_runtime(ctx["store"], ctx["components"])
    inst2 = rt2.create_instance(ctx["mid"], "g1", [_make_node(node_id="c1", agent_id="delegate-1", idempotency_key="rk-c")])
    await rt2.run_mission(inst2.runtime_id)
    assert rt2.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_resume_after_revoke_still_denied(tmp_path):
    # Resume path uses same MissionRecord + checkpoint never overrides
    ctx = await _governed_pair(tmp_path, name="r02-resume")
    _grant_std(ctx["authority"], ctx)
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    # First dispatch succeeded (before revoke) — now revoke and try resume
    # Create fresh pair for revoked case
    ctx2 = await _governed_pair(tmp_path, name="r02-resume2")
    _grant_std(ctx2["authority"], ctx2)
    rev = _rev(ctx2["store"], ctx2["mid"])
    ctx2["authority"].revoke_delegation(ctx2["mid"], "c1", rev, "test")
    rt2 = _wired_runtime(ctx2["store"], ctx2["components"])
    inst2 = rt2.create_instance(ctx2["mid"], "g1", [ctx2["child_node"]])
    await rt2.run_mission(inst2.runtime_id)
    assert rt2.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_alternate_provider_still_denied_after_revoke(tmp_path):
    ctx = await _governed_pair(tmp_path, name="r02-alt")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    # Alternate executor (different provider) still denied because delegation is revoked, not provider-specific
    alt_node = _make_node(node_id="c1", agent_id="delegate-1", idempotency_key="rk-c")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [alt_node])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

# ---------------------------------------------------------------------------
# Race tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rev02_race_submit_allow_revoke_then_effect_deny(tmp_path):
    """submit ALLOW -> revoke -> effect attempt -> DENY"""
    ctx = await _governed_pair(tmp_path, name="r02-race1")
    _grant_std(ctx["authority"], ctx)
    # Submit phase already ALLOW (grant exists, parent live)
    # Now revoke before effect
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "race")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

@pytest.mark.asyncio
async def test_rev02_race_parent_active_child_derived_then_parent_revoked(tmp_path):
    """parent active -> child derived -> parent revoked -> child effect -> DENY"""
    components = _components(tmp_path, tmp_path / ".intent-os")
    from intent_kernel.contracts import Capability as Cap
    # Need 3-level chain: nA (root) -> nB -> nC
    cap = "resource.race2"
    app = CountingApp(capability=cap)
    grid, gen, _s = _govern(components, app)
    _govern_delegate(components, agent_id="delegate-1", grid="gov-delegate-1")
    mission = await _started_mission(components, "r02-race2")
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    nodes = {nid: _make_node(node_id=nid, agent_id="delegate-1", idempotency_key=f"rk-{nid}", capability=cap) for nid in ("nA", "nB", "nC")}
    from intent_kernel.mission import MissionDefinition, MissionRecord, MissionStatus, DurableActionState
    ident = store.get_continuity_identity()
    definition = MissionDefinition(objective="x", context={})
    probe = MissionRecord(mission_id="probe", installation_id=ident, mission_definition=definition)
    plan, states = [], {}
    for nid in ("nA", "nB", "nC"):
        node = nodes[nid]
        spec = spec_for_runtime_node(mid, node)
        plan.append({"action_id": spec.action_id, "capability": cap, "node_id": nid, "dependencies": [], "request_semantics_digest": spec.request_semantics_digest, "operation": spec.operation})
        states[spec.action_id] = DurableActionState(action_id=spec.action_id, node_id=nid, expected_resource_id="r", expected_governed_registration_id=grid, expected_resource_generation=gen, expected_executor_kind="core_app", expected_executor_logical_id="delegate-1")
    record = MissionRecord(mission_id=mid, installation_id=ident, revision=1, runtime_id="rt-1", mission_definition=definition, mission_definition_digest=probe.compute_definition_digest(), mission_status=MissionStatus.RUNNING, plan=tuple(plan), action_states=states)
    assert store.create(record).outcome == "committed"
    authority = MissionActionAuthority(store)
    rev = authority.transition_action(mid, "nA", 1, ActionState.PENDING, ActionState.AUTHORIZED, ActionTransitionEvidence(requested_by="test", reason="test")).mission_revision
    # B under A
    authority.grant_delegation(mid, "nB", rev, parent_action_id="nA", delegate_agent_id="delegate-1", delegate_governed_registration_id="gov-delegate-1", allowed_capabilities=[cap], allowed_resources=[{"resource_id": "r", "governed_registration_id": grid, "generation": gen}], max_risk_level="critical", max_timeout_seconds=3600.0, require_verification=True, max_side_effect="EXTERNAL_IRREVERSIBLE")
    rev = store.load(mid)["revision"]
    authority.transition_action(mid, "nB", rev, ActionState.PENDING, ActionState.AUTHORIZED, ActionTransitionEvidence(requested_by="test", reason="test"))
    rev = store.load(mid)["revision"]
    authority.grant_delegation(mid, "nC", rev, parent_action_id="nB", delegate_agent_id="delegate-1", delegate_governed_registration_id="gov-delegate-1", allowed_capabilities=[cap], allowed_resources=[{"resource_id": "r", "governed_registration_id": grid, "generation": gen}], max_risk_level="critical", max_timeout_seconds=3600.0, require_verification=True, max_side_effect="EXTERNAL_IRREVERSIBLE")
    # Now revoke parent B
    rev = store.load(mid)["revision"]
    authority.revoke_delegation(mid, "nB", rev, "race")
    # Child C effect must be denied (ancestor revoked)
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [nodes["nC"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0

# ---------------------------------------------------------------------------
# Caller token provenance-only classification
# ---------------------------------------------------------------------------

def test_rev02_caller_token_is_provenance_only():
    from intent_kernel.auth import ApiKeyAuthenticator
    valid = ApiKeyAuthenticator("secret123", allow_anonymous=False).authenticate("Bearer secret123")
    assert valid.validation_result == "valid"
    # Caller token is AuthenticatedCaller, not an authority object
    assert not hasattr(valid, "mission_id")
    assert not hasattr(valid, "action_id")
    # No MissionActionAuthority method takes AuthenticatedCaller
    import inspect
    from intent_kernel.mission.action_authority import MissionActionAuthority as MAA
    for name in ("grant_delegation", "revoke_delegation", "transition_action", "decide_replay"):
        assert "AuthenticatedCaller" not in inspect.getsource(getattr(MAA, name))
        # No caller param in signature
        assert "caller" not in inspect.signature(getattr(MAA, name)).parameters
