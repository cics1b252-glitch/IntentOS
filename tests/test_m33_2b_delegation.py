"""M33.2B — Governed non-escalating delegation: executable proof suite.

Core invariant: AUTHORITY(CHILD) ⊆ AUTHORITY(PARENT). Delegation narrows;
it never manufactures or expands authority.

V1 scope freeze (see intent_kernel/mission/delegation.py):

- delegates are governed AGENTS only (tool delegation deferred:
  ToolResource lacks governed registration identity);
- targets are exact typed ID allowlists (no wildcards, no hierarchy);
- constraints are mechanically comparable typed fields only;
- delegation is mission-scoped (cross-mission deferred).

D-number mapping:

D01 durable grant model + states (pure unit)
D02 parent live-authorized at creation
D03 creation only through typed authority transition
D04 capability narrowing
D05 resource narrowing, exact triple
D06 target narrowing, exact IDs
D07 lifetime narrowing
D08 typed constraint monotonicity
D09 guard enforcement at handoff
D10 replay posture for revoked/expired
D11 RRM rebind remains mandatory
D12 ActionGate remains mandatory
D13 durable revocation transition
D14 descendant invalidation (computed, no fan-out)
D15 resource-death invalidation via existing RRM
D16 nested ceiling
D17 governed delegator/delegate identities
D18 representation reuse + only justified target type
D19 restart from durable authority + live RRM
D20 planner/capability/memory/agent-state/token != authority
D21 adversarial matrix (see ADVERSARIAL_* tests)
D22 durable delegation/revocation evidence
D23 expiry enforced at productive handoff
D24 composition without cycle or parallel authority system

Adversarial proofs (zero productive handoffs each): capability /
resource / target escalation, constraint weakening, lifetime
extension, unknown parent, revoked parent, revoked ancestor, expired
grant, cross-agent laundering, sibling grant reuse, delegation-ID-only
presentation, target substitution, resource generation change,
revocation between planning and handoff, corrupt durable delegation,
nesting-depth overflow.

All stores isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    Domain,
    MissionContext,
)
from intent_kernel.mission import (
    ActionState,
    ActionTransitionEvidence,
    DurableActionState,
    MissionActionAuthority,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
    ProductiveDispatchGuard,
    ReplayDecision,
    spec_for_runtime_node,
)
from intent_kernel.mission.action_authority import ActionTransitionError
from intent_kernel.mission.delegation import (
    MAX_DELEGATION_DEPTH,
    DelegatedResource,
    DelegationError,
    DelegationGrant,
    DelegationState,
    capability_subset,
    confirmation_basis_for_grant,
    is_expired,
    lifetime_subset,
    mint_delegation_id,
    prove_edge,
    resource_subset,
    target_subset,
    verify_grant_dispatch,
    walk_chain,
)
from intent_kernel.mission.store import MissionRecordValidationError
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.rrm.models import AgentResource, ConditionalRetirementRequest, ResourceType
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    SideEffectLevel,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class CountingApp:
    def __init__(self, app_id="counter", capability="resource.counter"):
        self.app_id = app_id
        self.capability_name = capability
        self.calls = 0

    @property
    def capabilities(self):
        return (Capability(
            name=self.capability_name,
            description="counter",
            requires_confirmation=False,
        ),)

    async def health(self) -> bool:
        return True

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="counted",
        )


class _CountingExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, contract):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(success=True, output="rt-ok")


class _AllowConstitution:
    def evaluate_action(self, _data):
        class _V:
            verdict = "ALLOW"
        return _V()


def _components(tmp_path, store_root, pkb_name="pkb"):
    authority_file = store_root / "rrm" / "authority.json"
    continuity_file = store_root / "continuity" / "identity.json"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return KernelBuilder().with_pkb_path(tmp_path / pkb_name).build(
        authority_file=authority_file, continuity_file=continuity_file)


def _govern(components, app):
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)
    registrations = components.capability_registry.discover(
        app.capability_name, executor_kind=ExecutorKind.CORE_APP)
    registration = next(r for r in registrations if r.executor_id == app.app_id)
    report = components.resource_promotion_service.bootstrap_govern(
        [BootstrapResourceDeclaration.from_registration(registration)])
    assert report.success, [(e.resource_id, e.reason) for e in report.entries]
    snap = components.resource_manager.get_capability(app.capability_name)
    return snap.governed_registration_id, snap.generation, snap


def _govern_delegate(components, agent_id="delegate-1", grid="gov-delegate-1"):
    """Register a governed delegate agent; return live (grid, generation)."""
    components.resource_manager.register_agent(
        AgentResource(agent_id=agent_id, name=agent_id,
                      governed_registration_id=grid)
    )
    snap = components.resource_manager.get_agent(agent_id)
    assert snap is not None
    assert snap.is_eligible
    return snap.governed_registration_id, snap.generation, snap


def _mission_store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _definition(objective="productive"):
    return MissionDefinition(objective=objective, context={"k": "v"})


def _guard_for(store):
    return ProductiveDispatchGuard(MissionActionAuthority(store), store)


def _authority(store):
    return MissionActionAuthority(store)


def _wired_runtime(store, components, executor=None):
    return MissionRuntime(
        executor=executor or _CountingExecutor(),
        constitution=_AllowConstitution(),
        dispatch_guard=_guard_for(store),
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )


def _make_node(node_id="n1", agent_id="ex-rt", idempotency_key="rk1",
               capability="c.rt", risk="low", timeout=30.0,
               verification=True, side_effect=SideEffectLevel.NONE):
    contract = ActionContract(
        action_id=node_id, capability=capability,
        idempotency_key=idempotency_key, risk_level=risk, timeout=timeout,
        verification_required=verification, side_effect_level=side_effect,
    )
    return RuntimeNode(
        node_id=node_id, capability=capability, agent_id=agent_id,
        action_contract=contract)


def _bind_record(store, mid, actions):
    """Bind a fresh durable record.

    actions: list of dicts with keys: node (required), state=PENDING,
    grid="", gen=0, executor=None (= node agent), resource_id="r",
    confirmation_required=False, confirmation_basis_digest="",
    grant=None (durable delegation_* mapping merged verbatim).
    """
    ident = store.get_continuity_identity()
    definition = _definition("runtime")
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition)
    plan, states = [], {}
    for a in actions:
        node = a["node"]
        spec = spec_for_runtime_node(mid, node)
        plan.append({
            "action_id": spec.action_id,
            "capability": node.capability or spec.action_id,
            "node_id": node.node_id,
            "dependencies": [],
            "request_semantics_digest": spec.request_semantics_digest,
        })
        kwargs = dict(
            action_id=spec.action_id, node_id=node.node_id,
            state=a.get("state", ActionState.PENDING),
            expected_resource_id=a.get("resource_id", "r"),
            expected_governed_registration_id=a.get("grid", ""),
            expected_resource_generation=a.get("gen", 0),
            expected_executor_kind="core_app",
            expected_executor_logical_id=a.get("executor", spec.executor_logical_id),
            confirmation_required=a.get("confirmation_required", False),
            confirmation_basis_digest=a.get("confirmation_basis_digest", ""),
        )
        grant = a.get("grant")
        if grant:
            for key, value in grant.items():
                if key.startswith("delegation_"):
                    kwargs[key] = value
        states[spec.action_id] = DurableActionState(**kwargs)
    record = MissionRecord(
        mission_id=mid, installation_id=ident, revision=1,
        runtime_id="rt-1", mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=tuple(plan),
        action_states=states,
    )
    assert store.create(record).outcome == "committed"


def _rev(store, mid):
    return store.load(mid)["revision"]


def _ev():
    return ActionTransitionEvidence(requested_by="test", reason="test")


def _drive_authorized(authority, mid, aid):
    """PENDING -> AUTHORIZED; returns new revision."""
    result = authority.transition_action(
        mid, aid, _rev_for(authority, mid),
        ActionState.PENDING, ActionState.AUTHORIZED, _ev())
    return result.mission_revision


def _rev_for(authority, mid):
    return authority._store.load(mid)["revision"]


async def _started_mission(components, name):
    m = await components.mission_engine.create(
        name, context=MissionContext(
            domain=Domain.OTHER, session_id="s", correlation_id="c"))
    return await components.mission_engine.start(m.id)


def _grant_kwargs(grid, gen, delegate_id, delegate_grid,
                  allowed_capabilities=("c.rt",), allowed_resources=None,
                  allowed_targets=(), max_risk_level="critical",
                  max_timeout_seconds=3600.0, require_verification=True,
                  max_side_effect="EXTERNAL_IRREVERSIBLE", expires_at=""):
    return dict(
        delegate_agent_id=delegate_id,
        delegate_governed_registration_id=delegate_grid,
        allowed_capabilities=list(allowed_capabilities),
        allowed_resources=(
            allowed_resources if allowed_resources is not None
            else [{"resource_id": "r", "governed_registration_id": grid,
                   "generation": gen}]
        ),
        allowed_targets=list(allowed_targets),
        max_risk_level=max_risk_level,
        max_timeout_seconds=max_timeout_seconds,
        require_verification=require_verification,
        max_side_effect=max_side_effect,
        expires_at=expires_at,
    )


_SHORT_TO_FULL = {
    "caps": "allowed_capabilities",
    "resources": "allowed_resources",
    "targets": "allowed_targets",
    "risk": "max_risk_level",
    "timeout": "max_timeout_seconds",
    "verification": "require_verification",
    "side_effect": "max_side_effect",
    "expires": "expires_at",
}


async def _governed_pair(tmp_path, name="pair", capability="c.rt"):
    """Parent (AUTHORIZED) + child (PENDING) bound to a live governed
    resource, plus a live governed delegate. Returns a context dict."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability=capability)
    grid, gen, _snap = _govern(components, app)
    dgrid, dgen, _dsnap = _govern_delegate(components)
    mission = await _started_mission(components, name)
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    parent_node = _make_node(node_id="p1", agent_id="ex-rt",
                             idempotency_key="rk-p", capability=capability)
    child_node = _make_node(node_id="c1", agent_id="delegate-1",
                            idempotency_key="rk-c", capability=capability)
    _bind_record(store, mid, [
        {"node": parent_node, "grid": grid, "gen": gen},
        {"node": child_node, "grid": grid, "gen": gen,
         "executor": "delegate-1"},
    ])
    authority = _authority(store)
    rev = _drive_authorized(authority, mid, "p1")
    return {
        "components": components, "store": store, "mid": mid,
        "authority": authority, "rev": rev,
        "grid": grid, "gen": gen,
        "dgrid": dgrid, "dgen": dgen,
        "child_node": child_node,
    }


def _grant_std(authority, ctx, capability="c.rt", **over):
    short = {k: v for k, v in over.items() if k in _SHORT_TO_FULL}
    for k in short:
        over[_SHORT_TO_FULL[k]] = over.pop(k)
    kw = _grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"],
                       allowed_capabilities=(capability,))
    kw.update(over)
    return authority.grant_delegation(
        ctx["mid"], "c1", ctx["rev"], parent_action_id="p1", **kw)


# ---------------------------------------------------------------------------
# D01: durable grant model + states (pure unit)
# ---------------------------------------------------------------------------

def test_d01_grant_shape_validation():
    good = dict(
        delegation_id="dlg_abc", delegation_parent_mission_id="m",
        delegation_parent_action_id="p", delegation_root_mission_id="m",
        delegation_root_action_id="p",
        delegation_delegator_grid="g", delegation_delegate_agent_id="a",
        delegation_allowed_capabilities=["c"],
        delegation_allowed_resources=[{"resource_id": "r",
                                       "governed_registration_id": "g",
                                       "generation": 2}],
    )
    g = DelegationGrant.from_dict(good)
    assert g.delegation_state is DelegationState.ACTIVE
    assert g.to_dict()["delegation_allowed_capabilities"] == ["c"]
    # Malformed proposals fail closed.
    import pytest as _p
    for bad in ({"delegation_id": ""}, {"delegation_allowed_capabilities": []},
                {"delegation_allowed_resources": []},
                {"delegation_max_risk_level": "bogus"},
                {"delegation_max_timeout_seconds": True},
                {"delegation_require_verification": "yes"},
                {"delegation_max_side_effect": "bogus"},
                {"delegation_state": "BOGUS"}):
        candidate = dict(good)
        candidate.update(bad)
        with _p.raises(DelegationError):
            DelegationGrant.from_dict(candidate)


def test_d01_state_lifecycle_values():
    assert {s.value for s in DelegationState} == {"NONE", "ACTIVE", "REVOKED"}
    assert MAX_DELEGATION_DEPTH == 4


def test_d01_mint_format():
    first, second = mint_delegation_id(), mint_delegation_id()
    assert first.startswith("dlg_") and second.startswith("dlg_")
    assert first != second


def test_d01_expiry_is_derived_not_stored():
    assert is_expired("2000-01-01T00:00:00Z", "2026-01-01T00:00:00Z") is True
    assert is_expired("2100-01-01T00:00:00Z", "2026-01-01T00:00:00Z") is False
    assert is_expired("", "2026-01-01T00:00:00Z") is False
    assert is_expired("2000-01-01T00:00:00Z", "") is False


# ---------------------------------------------------------------------------
# D02/D03: creation requires live-authorized parent, typed transition only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d02_unknown_parent_fails_closed(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d02")
    import pytest as _p
    with _p.raises(ActionTransitionError):
        ctx["authority"].grant_delegation(
            ctx["mid"], "c1", ctx["rev"], parent_action_id="nope",
            **_grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"]))
    # Failed creation leaves no grant and no revision bump.
    assert _rev(ctx["store"], ctx["mid"]) == ctx["rev"]
    assert ctx["store"].load(ctx["mid"])["action_states"]["c1"].get(
        "delegation_id", "") == ""


@pytest.mark.asyncio
async def test_d02_pending_parent_fails_closed(tmp_path):
    """A PENDING parent never authorized anything: no derivation."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "d02p")
    store = _mission_store(tmp_path)
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": _make_node(node_id="c1"), "grid": grid, "gen": gen},
    ])
    authority = _authority(store)
    import pytest as _p
    with _p.raises(ActionTransitionError):
        authority.grant_delegation(
            str(mission.id), "c1", 1, parent_action_id="p1",
            **_grant_kwargs(grid, gen, "delegate-1", "gov-delegate-1"))


@pytest.mark.asyncio
async def test_d02_terminal_parent_states_fail_closed(tmp_path):
    """FAILED / AMBIGUOUS_EFFECT / COMPLETED parents are closed history:
    nothing to derive."""
    import pytest as _p
    # FAILED: reachable directly from PENDING.
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.counter")
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "d02t-failed")
    store = _mission_store(tmp_path, "ms-failed")
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": _make_node(node_id="c1"), "grid": grid, "gen": gen},
    ])
    authority = _authority(store)
    authority.transition_action(
        str(mission.id), "p1", 1, ActionState.PENDING,
        ActionState.FAILED, _ev())
    with _p.raises(ActionTransitionError):
        authority.grant_delegation(
            str(mission.id), "c1", 2, parent_action_id="p1",
            **_grant_kwargs(grid, gen, "delegate-1", "gov-delegate-1"))
    # AMBIGUOUS_EFFECT: reachable via the dispatch chain, no proofs needed.
    mission2 = await _started_mission(components, "d02t-amb")
    store2 = _mission_store(tmp_path, "ms-amb")
    _bind_record(store2, str(mission2.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": _make_node(node_id="c1"), "grid": grid, "gen": gen},
    ])
    authority2 = _authority(store2)
    rev = 1
    for src, dst in ((ActionState.PENDING, ActionState.AUTHORIZED),
                     (ActionState.AUTHORIZED, ActionState.DISPATCH_INTENT_RECORDED),
                     (ActionState.DISPATCH_INTENT_RECORDED, ActionState.DISPATCHING),
                     (ActionState.DISPATCHING, ActionState.AMBIGUOUS_EFFECT)):
        rev = authority2.transition_action(
            str(mission2.id), "p1", rev, src, dst, _ev()).mission_revision
    with _p.raises(ActionTransitionError):
        authority2.grant_delegation(
            str(mission2.id), "c1", rev, parent_action_id="p1",
            **_grant_kwargs(grid, gen, "delegate-1", "gov-delegate-1"))
    # COMPLETED: bound directly (proof chain not needed for this refusal).
    mission3 = await _started_mission(components, "d02t-done")
    store3 = _mission_store(tmp_path, "ms-done")
    _bind_record(store3, str(mission3.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen,
         "state": ActionState.COMPLETED},
        {"node": _make_node(node_id="c1"), "grid": grid, "gen": gen},
    ])
    authority3 = _authority(store3)
    with _p.raises(ActionTransitionError):
        authority3.grant_delegation(
            str(mission3.id), "c1", 1, parent_action_id="p1",
            **_grant_kwargs(grid, gen, "delegate-1", "gov-delegate-1"))


@pytest.mark.asyncio
async def test_d03_grant_commits_durably_exactly_once(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d03")
    result = _grant_std(ctx["authority"], ctx)
    assert result.mission_revision == ctx["rev"] + 1
    data = ctx["store"].load(ctx["mid"])
    action = data["action_states"]["c1"]
    assert action["delegation_id"].startswith("dlg_")
    assert action["delegation_state"] == "ACTIVE"
    assert action["delegation_parent_action_id"] == "p1"
    assert action["delegation_root_action_id"] == "p1"
    assert action["delegation_root_governed_registration_id"] == ctx["grid"]
    assert action["delegation_root_generation"] == ctx["gen"]
    assert action["delegation_created_at"] != ""
    # Child action state untouched by the grant transition.
    assert action["state"] == ActionState.PENDING.value


@pytest.mark.asyncio
async def test_d03_duplicate_grant_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d03dup")
    _grant_std(ctx["authority"], ctx)
    rev_after_first = _rev(ctx["store"], ctx["mid"])
    import pytest as _p
    with _p.raises(ActionTransitionError):
        ctx["authority"].grant_delegation(
            ctx["mid"], "c1", rev_after_first, parent_action_id="p1",
            **_grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"]))
    assert _rev(ctx["store"], ctx["mid"]) == rev_after_first


@pytest.mark.asyncio
async def test_d03_direct_injection_fails_closed(tmp_path):
    """Ordinary commit() cannot smuggle grant fields — not even a complete,
    well-formed grant: the store rejects any delegation change outside the
    canonical transitions."""
    ctx = await _governed_pair(tmp_path, name="d03inj")
    _grant_std(ctx["authority"], ctx)
    import copy
    from intent_kernel.mission.mission_record import MissionRecord
    data = ctx["store"].load(ctx["mid"])
    # Copy c1's complete legitimate grant onto the un-delegated parent p1.
    src = data["action_states"]["c1"]
    forged = dict(data["action_states"]["p1"])
    for key, value in src.items():
        if key.startswith("delegation_"):
            forged[key] = copy.deepcopy(value)
    candidate_actions = dict(data["action_states"])
    candidate_actions["p1"] = forged
    candidate = dict(data)
    candidate["action_states"] = candidate_actions
    candidate["revision"] = data["revision"] + 1
    candidate_record = MissionRecord.from_dict(candidate)
    import pytest as _p
    with _p.raises(MissionRecordValidationError):
        ctx["store"].commit(data["revision"], candidate_record)
    # Nothing changed durably.
    assert ctx["store"].load(ctx["mid"])["action_states"]["p1"].get(
        "delegation_id", "") == ""

# ---------------------------------------------------------------------------
# D04-D08: narrowing proofs
# ---------------------------------------------------------------------------

def test_d04_capability_subset_pure():
    assert capability_subset(["c"], ["c"]) is True
    assert capability_subset(["c"], ["c", "d"]) is True
    assert capability_subset(["x"], ["c"]) is False
    assert capability_subset([], ["c"]) is False


@pytest.mark.asyncio
async def test_d04_capability_escalation_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d04")
    import pytest as _p
    with _p.raises(ActionTransitionError) as exc:
        _grant_std(ctx["authority"], ctx, caps=("other.capability",))
    assert "capability-escalation" in str(exc.value)


@pytest.mark.asyncio
async def test_d05_resource_escalation_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d05")
    import pytest as _p
    with _p.raises(ActionTransitionError) as exc:
        _grant_std(ctx["authority"], ctx, resources=[{
            "resource_id": "r", "governed_registration_id": "WRONG_REG",
            "generation": ctx["gen"]}])
    assert "resource-escalation" in str(exc.value)
    with _p.raises(ActionTransitionError) as exc:
        _grant_std(ctx["authority"], ctx, resources=[{
            "resource_id": "r", "governed_registration_id": ctx["grid"],
            "generation": 999}])
    assert "resource-escalation" in str(exc.value)


@pytest.mark.asyncio
async def test_d06_target_escalation_rejected(tmp_path):
    """Nested edge: a child proposing targets outside the parent grant's
    allowlist fails closed at creation."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.d06")
    grid, gen, _snap = _govern(components, app)
    _govern_delegate(components, agent_id="delegate-1",
                     grid="gov-delegate-1")
    mission = await _started_mission(components, "d06")
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    cap = "resource.d06"
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
    rev = authority.transition_action(
        mid, "nA", 1, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision

    def _g(child, parent, rev, targets):
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
            expires_at="").mission_revision
    # Parent grant allows target t1 only.
    rev = _g("nB", "nA", rev, ("t1",))
    assert store.load(mid)["action_states"]["nB"][
        "delegation_allowed_targets"] == ["t1"]
    # Derivation requires a live-authorized parent action: drive nB there.
    rev = authority.transition_action(
        mid, "nB", rev, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision
    # Child proposing t2 under it fails closed.
    import pytest as _p
    with _p.raises(ActionTransitionError) as exc:
        _g("nC", "nB", rev, ("t2",))
    assert "target-escalation" in str(exc.value)
    # Child proposing t1 succeeds.
    _g("nC", "nB", rev, ("t1",))


@pytest.mark.asyncio
async def test_d07_lifetime_extension_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d07")
    import pytest as _p
    # Root edge is unbounded: an explicit expiry is accepted...
    result = _grant_std(ctx["authority"], ctx, expires="2100-01-01T00:00:00Z")
    assert result is not None
    assert ctx["store"].load(ctx["mid"])["action_states"]["c1"][
        "delegation_expires_at"] == "2100-01-01T00:00:00Z"
    # ...but a stillborn (already-expired) grant is rejected at creation.
    with _p.raises(ActionTransitionError):
        ctx["authority"].grant_delegation(
            ctx["mid"], "c1", result.mission_revision,
            parent_action_id="p1",
            **_grant_kwargs(ctx["grid"], ctx["gen"], "delegate-1", ctx["dgrid"],
                            expires_at="2000-01-01T00:00:00Z"))


@pytest.mark.asyncio
async def test_d08_constraint_weakening_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d08")
    import pytest as _p
    # Root grants must be explicit: empty ceilings rejected.
    with _p.raises(ActionTransitionError):
        _grant_std(ctx["authority"], ctx, risk="", timeout=0.0,
                   verification=None, side_effect="")
    # Malformed ceiling values rejected.
    with _p.raises(ActionTransitionError):
        _grant_std(ctx["authority"], ctx, risk="bogus")
    with _p.raises(ActionTransitionError):
        _grant_std(ctx["authority"], ctx, side_effect="bogus")


def test_d08_monotonic_tables_pure():
    from intent_kernel.mission.delegation import (
        risk_allows, timeout_allows, verification_allows, side_effect_allows)
    assert risk_allows("low", "critical") is True
    assert risk_allows("critical", "low") is False
    assert risk_allows("bogus", "low") is False
    assert timeout_allows(30.0, 3600.0) is True
    assert timeout_allows(3600.0, 30.0) is False
    assert timeout_allows(30.0, 0) is True
    assert verification_allows(True, True) is True
    assert verification_allows(False, True) is False
    assert verification_allows(False, False) is True
    assert side_effect_allows("NONE", "EXTERNAL_IRREVERSIBLE") is True
    assert side_effect_allows("EXTERNAL_IRREVERSIBLE", "NONE") is False


# ---------------------------------------------------------------------------
# D09/D10: handoff enforcement + replay posture
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d09_delegated_handoff_exactly_once(tmp_path):
    """D09/D11/D12: a valid delegated action dispatches exactly once through
    the full mandatory stack (gate + rebind + guard)."""
    ctx = await _governed_pair(tmp_path, name="d09")
    _grant_std(ctx["authority"], ctx)
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 1
    # Restart: RESULT_RECORDED forbids redispatch.
    rt2 = _wired_runtime(ctx["store"], ctx["components"])
    inst2 = rt2.create_instance(ctx["mid"], "g1", [_make_node(
        node_id="c1", agent_id="delegate-1", idempotency_key="rk-c")])
    await rt2.run_mission(inst2.runtime_id)
    assert rt2.executor.calls == 0
    assert rt.executor.calls == 1


@pytest.mark.asyncio
async def test_d09_wrong_presenter_zero_handoffs(tmp_path):
    """Cross-agent laundering: a non-delegate presenter is refused."""
    ctx = await _governed_pair(tmp_path, name="d09p")
    _grant_std(ctx["authority"], ctx)
    stranger = _make_node(node_id="c1", agent_id="stranger",
                          idempotency_key="rk-c")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [stranger])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_d10_revoked_replay_posture(tmp_path):
    """D10/D13/D14: revoke -> replay forbids dispatch (direct authority read)."""
    ctx = await _governed_pair(tmp_path, name="d10")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    result = ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    assert result is not None
    assert ctx["store"].load(ctx["mid"])["action_states"]["c1"][
        "delegation_state"] == "REVOKED"
    assert ctx["authority"].decide_replay(
        ctx["mid"], "c1") is ReplayDecision.DO_NOT_REDISPATCH


@pytest.mark.asyncio
async def test_d10_expired_replay_posture(tmp_path):
    """An expired grant forbids dispatch even though the shape is valid.

    Creation rejects stillborn grants, so the exact post-expiry durable
    state is planted directly (the same technique as stale-generation
    tests): enforcement, not creation, is under proof here."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "d10e")
    store = _mission_store(tmp_path)
    expired_grant = {
        "delegation_id": "dlg_expired",
        "delegation_parent_mission_id": str(mission.id),
        "delegation_parent_action_id": "p1",
        "delegation_parent_delegation_id": "",
        "delegation_root_mission_id": str(mission.id),
        "delegation_root_action_id": "p1",
        "delegation_root_governed_registration_id": grid,
        "delegation_root_generation": gen,
        "delegation_delegator_grid": grid,
        "delegation_delegator_agent_id": "ex-rt",
        "delegation_delegate_agent_id": "delegate-1",
        "delegation_delegate_grid": "gov-delegate-1",
        "delegation_allowed_capabilities": ["c.rt"],
        "delegation_allowed_resources": [{"resource_id": "r",
                                          "governed_registration_id": grid,
                                          "generation": gen}],
        "delegation_allowed_targets": [],
        "delegation_max_risk_level": "critical",
        "delegation_max_timeout_seconds": 3600.0,
        "delegation_require_verification": True,
        "delegation_max_side_effect": "EXTERNAL_IRREVERSIBLE",
        "delegation_created_at": "2000-01-01T00:00:00Z",
        "delegation_expires_at": "2000-01-02T00:00:00Z",
        "delegation_state": "ACTIVE",
        "delegation_revoked_at": "",
        "delegation_revoke_reason": "",
    }
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": _make_node(node_id="c1", agent_id="delegate-1",
                            idempotency_key="rk-c"),
         "grid": grid, "gen": gen, "executor": "delegate-1",
         "grant": expired_grant},
    ])
    authority = _authority(store)
    assert authority.decide_replay(
        str(mission.id), "c1") is ReplayDecision.DO_NOT_REDISPATCH
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(str(mission.id), "g1", [_make_node(
        node_id="c1", agent_id="delegate-1", idempotency_key="rk-c")])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_d11_rebind_mandatory_for_delegated(tmp_path):
    """D11: a live generation bump after grant issuance refuses the handoff.
    The grant was valid when created; current-state revalidation (not the
    grant proof) fails it — the rebind remains mandatory."""
    from intent_kernel.rrm.models import (
        ConditionalResourceStatusRequest, ConditionalUpdateOutcome,
        ResourceStatus, ResourceType)
    ctx = await _governed_pair(tmp_path, name="d11", capability="resource.d11")
    _grant_std(ctx["authority"], ctx, capability="resource.d11")
    rrm = ctx["components"].resource_manager
    snap_before = rrm.get_capability("resource.d11")
    bump = rrm.conditional_update_status(ConditionalResourceStatusRequest(
        resource_type=ResourceType.CAPABILITY,
        resource_id="resource.d11",
        expected_governed_registration_id=ctx["grid"],
        expected_generation=ctx["gen"],
        desired_status=ResourceStatus.DEGRADED,
    ))
    assert bump.outcome is ConditionalUpdateOutcome.APPLIED
    snap_after = rrm.get_capability("resource.d11")
    assert snap_after.generation == ctx["gen"] + 1
    assert snap_before.generation == ctx["gen"]
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_d12_gate_mandatory_for_delegated(tmp_path):
    """D12: a DENY constitution blocks even a fully valid delegation."""
    ctx = await _governed_pair(tmp_path, name="d12")
    _grant_std(ctx["authority"], ctx)

    class _DenyConstitution:
        def evaluate_action(self, _data):
            class _V:
                verdict = "DENY"
            return _V()

    rt = MissionRuntime(
        executor=_CountingExecutor(), constitution=_DenyConstitution(),
        dispatch_guard=_guard_for(ctx["store"]),
        mission_record_store=ctx["store"],
        rrm_service=ctx["components"].resource_manager,
    )
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# D13/D14: revocation + descendant invalidation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d13_revocation_terminal_and_idempotent(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d13")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    first = ctx["authority"].revoke_delegation(
        ctx["mid"], "c1", rev, "operator revoke")
    assert first.mission_revision == rev + 1
    data = ctx["store"].load(ctx["mid"])
    action = data["action_states"]["c1"]
    assert action["delegation_state"] == "REVOKED"
    assert action["delegation_revoked_at"] != ""
    assert action["delegation_revoke_reason"] == "operator revoke"
    # Repeat revoke: idempotent, no revision bump, history preserved.
    second = ctx["authority"].revoke_delegation(
        ctx["mid"], "c1", rev + 1, "again")
    assert _rev(ctx["store"], ctx["mid"]) == rev + 1
    assert second.mission_revision == rev + 1
    data2 = ctx["store"].load(ctx["mid"])
    assert data2["action_states"]["c1"]["delegation_state"] == "REVOKED"


@pytest.mark.asyncio
async def test_d13_revoke_missing_grant_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d13m")
    import pytest as _p
    with _p.raises(ActionTransitionError):
        ctx["authority"].revoke_delegation(ctx["mid"], "c1", ctx["rev"], "x")
    with _p.raises(Exception):
        ctx["authority"].revoke_delegation(ctx["mid"], "nope", ctx["rev"], "x")


@pytest.mark.asyncio
async def test_d14_revoked_parent_blocks_child_handoff(tmp_path):
    """REVOKED(ANCESTOR) => INVALID(DESCENDANT), history preserved."""
    ctx = await _governed_pair(tmp_path, name="d14")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0
    # Evidence preserved, not deleted.
    data = ctx["store"].load(ctx["mid"])
    assert data["action_states"]["c1"]["delegation_id"].startswith("dlg_")
    assert data["action_states"]["c1"]["delegation_state"] == "REVOKED"


# ---------------------------------------------------------------------------
# D15: resource-death invalidation via existing RRM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d15_retired_parent_resource_blocks_child(tmp_path):
    """Retiring the governed parent resource removes it from the RRM, so
    the rebind root-liveness check fails: zero handoffs, no new code."""
    from intent_kernel.rrm.models import ConditionalRetirementOutcome
    ctx = await _governed_pair(tmp_path, name="d15", capability="resource.d15")
    _grant_std(ctx["authority"], ctx, capability="resource.d15")
    res = ctx["components"].resource_manager.conditional_retire_resource(
        ConditionalRetirementRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="resource.d15",
            governed_registration_id=ctx["grid"],
            expected_generation=ctx["gen"],
        )
    )
    assert res.outcome is ConditionalRetirementOutcome.RETIRED
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# D16: nested ceiling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d16_three_level_chain_dispatches_once(tmp_path):
    """Root A -> B -> C -> D: the deepest grant dispatches exactly once."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.n16")
    grid, gen, _snap = _govern(components, app)
    _govern_delegate(components, agent_id="delegate-1",
                     grid="gov-delegate-1")
    mission = await _started_mission(components, "d16")
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    cap = "resource.n16"
    nodes = {
        nid: _make_node(node_id=nid, agent_id="delegate-1",
                        idempotency_key=f"rk-{nid}", capability=cap)
        for nid in ("nA", "nB", "nC", "nD")
    }
    _bind_record(store, mid, [
        {"node": nodes[nid], "grid": grid, "gen": gen,
         "executor": "delegate-1", "resource_id": "r"}
        for nid in ("nA", "nB", "nC", "nD")
    ])
    authority = _authority(store)
    rev = authority.transition_action(
        mid, "nA", 1, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision

    def _g(child, parent, rev, inherit=False):
        kw = dict(
            delegate_agent_id="delegate-1",
            delegate_governed_registration_id="gov-delegate-1",
            allowed_capabilities=[cap],
            allowed_resources=[{"resource_id": "r",
                                "governed_registration_id": grid,
                                "generation": gen}],
            allowed_targets=[],
            max_risk_level="" if inherit else "critical",
            max_timeout_seconds=0.0 if inherit else 3600.0,
            require_verification=None if inherit else True,
            max_side_effect="" if inherit else "EXTERNAL_IRREVERSIBLE",
            expires_at="",
        )
        return authority.grant_delegation(
            mid, child, rev, parent_action_id=parent, **kw)

    # B under A (explicit), C under B (inherited ceilings resolve), D under C.
    # Each intermediate action is driven to AUTHORIZED first: derivation
    # requires a live-authorized parent action, not merely a valid grant.
    def _drive(nid, rev):
        return authority.transition_action(
            mid, nid, rev, ActionState.PENDING, ActionState.AUTHORIZED,
            _ev()).mission_revision
    r = _g("nB", "nA", 2).mission_revision
    r = _drive("nB", r)
    r = _g("nC", "nB", r, inherit=True).mission_revision
    r = _drive("nC", r)
    _g("nD", "nC", r, inherit=True)
    data = store.load(mid)
    assert data["action_states"]["nD"]["delegation_max_risk_level"] == "critical"
    assert data["action_states"]["nD"]["delegation_max_timeout_seconds"] == 3600.0
    assert data["action_states"]["nD"]["delegation_require_verification"] is True
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [nodes["nD"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 1


@pytest.mark.asyncio
async def test_d16_depth_overflow_rejected(tmp_path):
    """A fifth nested level fails closed at creation."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.d16b")
    grid, gen, _snap = _govern(components, app)
    _govern_delegate(components, agent_id="delegate-1",
                     grid="gov-delegate-1")
    mission = await _started_mission(components, "d16b")
    mid = str(mission.id)
    store = _mission_store(tmp_path)
    cap = "resource.d16b"
    ids = ["nA", "nB", "nC", "nD", "nE", "nF"]
    nodes = {
        nid: _make_node(node_id=nid, agent_id="delegate-1",
                        idempotency_key=f"rk-{nid}", capability=cap)
        for nid in ids
    }
    _bind_record(store, mid, [
        {"node": nodes[nid], "grid": grid, "gen": gen,
         "executor": "delegate-1", "resource_id": "r"}
        for nid in ids
    ])
    authority = _authority(store)
    rev = authority.transition_action(
        mid, "nA", 1, ActionState.PENDING, ActionState.AUTHORIZED,
        _ev()).mission_revision

    def _g(child, parent, rev):
        return authority.grant_delegation(
            mid, child, rev, parent_action_id=parent,
            delegate_agent_id="delegate-1",
            delegate_governed_registration_id="gov-delegate-1",
            allowed_capabilities=[cap],
            allowed_resources=[{"resource_id": "r",
                                "governed_registration_id": grid,
                                "generation": gen}],
            allowed_targets=[],
            max_risk_level="critical", max_timeout_seconds=3600.0,
            require_verification=True,
            max_side_effect="EXTERNAL_IRREVERSIBLE",
            expires_at="").mission_revision

    def _drive(nid, rev):
        return authority.transition_action(
            mid, nid, rev, ActionState.PENDING, ActionState.AUTHORIZED,
            _ev()).mission_revision
    rev = _g("nB", "nA", rev)  # depth 1
    rev = _drive("nB", rev)
    rev = _g("nC", "nB", rev)  # depth 2
    rev = _drive("nC", rev)
    rev = _g("nD", "nC", rev)  # depth 3
    rev = _drive("nD", rev)
    rev = _g("nE", "nD", rev)  # depth 4 (bound)
    rev = _drive("nE", rev)
    import pytest as _p
    with _p.raises(ActionTransitionError) as exc:
        _g("nF", "nE", rev)  # depth 5: overflow
    assert "depth" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# D17: governed identities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d17_malformed_delegate_identity_rejected(tmp_path):
    ctx = await _governed_pair(tmp_path, name="d17")
    import pytest as _p
    with _p.raises(ActionTransitionError):
        ctx["authority"].grant_delegation(
            ctx["mid"], "c1", ctx["rev"], parent_action_id="p1",
            delegate_agent_id="",
            delegate_governed_registration_id=ctx["dgrid"],
            allowed_capabilities=["c.rt"],
            allowed_resources=[{"resource_id": "r",
                                "governed_registration_id": ctx["grid"],
                                "generation": ctx["gen"]}],
            max_risk_level="critical", max_timeout_seconds=3600.0,
            require_verification=True,
            max_side_effect="EXTERNAL_IRREVERSIBLE")
    with _p.raises(ActionTransitionError):
        ctx["authority"].grant_delegation(
            ctx["mid"], "c1", ctx["rev"], parent_action_id="p1",
            delegate_agent_id="delegate-1",
            delegate_governed_registration_id="",
            allowed_capabilities=["c.rt"],
            allowed_resources=[{"resource_id": "r",
                                "governed_registration_id": ctx["grid"],
                                "generation": ctx["gen"]}],
            max_risk_level="critical", max_timeout_seconds=3600.0,
            require_verification=True,
            max_side_effect="EXTERNAL_IRREVERSIBLE")


@pytest.mark.asyncio
async def test_d17_unknown_delegate_agent_refused_at_handoff(tmp_path):
    """A pinned-but-unresolvable delegate fails the live standing check."""
    ctx = await _governed_pair(tmp_path, name="d17u")
    ctx["authority"].grant_delegation(
        ctx["mid"], "c1", ctx["rev"], parent_action_id="p1",
        delegate_agent_id="ghost-agent",
        delegate_governed_registration_id="gov-ghost",
        allowed_capabilities=["c.rt"],
        allowed_resources=[{"resource_id": "r",
                            "governed_registration_id": ctx["grid"],
                            "generation": ctx["gen"]}],
        max_risk_level="critical", max_timeout_seconds=3600.0,
        require_verification=True,
        max_side_effect="EXTERNAL_IRREVERSIBLE")
    ghost = _make_node(node_id="c1", agent_id="ghost-agent",
                       idempotency_key="rk-c")
    # Rebind the durable executor expectation to the ghost presenter.
    data = ctx["store"].load(ctx["mid"])
    assert data["action_states"]["c1"]["delegation_delegate_agent_id"] == "ghost-agent"
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ghost])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# D18: representation reuse
# ---------------------------------------------------------------------------

def test_d18_no_parallel_delegation_types():
    """Delegation introduces no store, no RRM import, no runtime import,
    and no credential/token identifiers. Single justified addition:
    exact-ID targets (no target representation exists anywhere else)."""
    import re
    import intent_kernel.mission.delegation as dg
    source = open(dg.__file__).read()
    assert "intent_kernel.rrm" not in source
    assert "intent_kernel.runtime" not in source
    assert "intent_kernel.mission.store" not in source
    forbidden = re.findall(
        r"[A-Za-z_]*(?:access_token|refresh_token|id_token|api_key|"
        r"client_secret|private_key|bearer|password|credential_reference)",
        source, re.IGNORECASE)
    assert forbidden == [], forbidden
    # The module's public surface is model + pure provers only
    # (imported helpers such as dataclass are excluded).
    import inspect
    fns = {n for n, m in inspect.getmembers(dg, predicate=inspect.isfunction)
           if not n.startswith("_")
           and getattr(m, "__module__", "") == dg.__name__}
    assert fns <= {
        "capability_subset", "confirmation_basis_for_grant",
        "contract_within_grant", "is_expired", "lifetime_subset",
        "mint_delegation_id", "prove_edge", "resource_subset",
        "resolve_effective_ceilings", "resolve_parent_view",
        "risk_allows", "side_effect_allows", "target_subset",
        "timeout_allows", "verification_allows", "verify_grant_dispatch",
        "walk_chain", "grant_view",
    }


# ---------------------------------------------------------------------------
# D19: restart from durable authority + live RRM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d19_restart_never_resurrects_revoked(tmp_path):
    """Grant -> revoke -> fresh runtime: zero handoffs, history intact."""
    ctx = await _governed_pair(tmp_path, name="d19")
    _grant_std(ctx["authority"], ctx)
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0
    data = ctx["store"].load(ctx["mid"])
    assert data["action_states"]["c1"]["delegation_state"] == "REVOKED"


@pytest.mark.asyncio
async def test_d19_checkpoint_claim_ignored_on_restart(tmp_path):
    """An agent/checkpoint claim of delegation authority is never trusted:
    only the durable record plus live RRM govern the fresh runtime."""
    ctx = await _governed_pair(tmp_path, name="d19c")
    _grant_std(ctx["authority"], ctx)
    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 1
    # A second, fabricated in-memory "grant" object changes nothing.
    phantom = DelegationGrant.from_dict({
        "delegation_id": "dlg_phantom",
        "delegation_parent_mission_id": ctx["mid"],
        "delegation_parent_action_id": "p1",
        "delegation_root_mission_id": ctx["mid"],
        "delegation_root_action_id": "p1",
        "delegation_delegator_grid": ctx["grid"],
        "delegation_delegate_agent_id": "delegate-1",
        "delegation_allowed_capabilities": ["c.rt"],
        "delegation_allowed_resources": [{"resource_id": "r",
                                          "governed_registration_id": ctx["grid"],
                                          "generation": ctx["gen"]}],
    })
    assert phantom.delegation_id == "dlg_phantom"
    assert rt.executor.calls == 1


# ---------------------------------------------------------------------------
# D20: planner/capability/memory/agent-state/token != authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d20_ordinary_path_inert_to_delegation(tmp_path):
    """Delegation machinery never interferes with non-delegated flows: a
    mission with no grants anywhere dispatches through the ordinary path
    exactly as before (capability possession still requires its own
    durable binding; nothing about delegation changes that)."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "d20")
    store = _mission_store(tmp_path)
    node = _make_node(node_id="n1")
    _bind_record(store, str(mission.id), [{"node": node}])
    assert store.load(str(mission.id))["action_states"]["n1"].get(
        "delegation_id", "") == ""
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(str(mission.id), "g1", [_make_node(
        node_id="n1")])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 1


def test_d20_grant_api_takes_no_credentials():
    """Structural: the grant/revoke API surface accepts no credential,
    token, secret, password, or session material whatsoever."""
    import inspect
    from intent_kernel.mission.action_authority import MissionActionAuthority
    for name in ("grant_delegation", "revoke_delegation"):
        text = inspect.getsource(getattr(MissionActionAuthority, name)).lower()
        for forbidden in ("token", "secret", "password", "credential",
                          "session", "bearer", "api_key", "apikey"):
            assert forbidden not in text, f"{name} mentions {forbidden}"


# ---------------------------------------------------------------------------
# D21: adversarial matrix (zero handoffs each)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adv_sibling_grant_reuse_refused(tmp_path):
    """A grant bound to action X cannot authorize sibling action Y.

    Y carries no grant of its own, so the guard treats it as an ordinary
    action — and copying X's grant fields onto Y via ordinary commit is
    rejected by the store's delegation hardening."""
    ctx = await _governed_pair(tmp_path, name="adv-sib")
    _grant_std(ctx["authority"], ctx)
    import copy
    from intent_kernel.mission.mission_record import MissionRecord
    data = ctx["store"].load(ctx["mid"])
    src = data["action_states"]["c1"]
    forged = dict(data["action_states"]["p1"])
    for key, value in src.items():
        if key.startswith("delegation_"):
            forged[key] = copy.deepcopy(value)
    candidate_actions = dict(data["action_states"])
    candidate_actions["p1"] = forged
    candidate = dict(data)
    candidate["action_states"] = candidate_actions
    candidate["revision"] = data["revision"] + 1
    import pytest as _p
    with _p.raises(MissionRecordValidationError):
        ctx["store"].commit(
            data["revision"], MissionRecord.from_dict(candidate))


@pytest.mark.asyncio
async def test_adv_delegation_id_only_presentation_refused(tmp_path):
    """A grant whose parent chain points nowhere fails the walk: an
    attacker presenting only a delegation ID cannot fabricate lineage."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "adv-id")
    store = _mission_store(tmp_path)
    node = _make_node(node_id="c1", agent_id="delegate-1",
                      idempotency_key="rk-c")
    grant = {
        "delegation_id": "dlg_orphan",
        "delegation_parent_mission_id": str(mission.id),
        "delegation_parent_action_id": "p1",
        "delegation_parent_delegation_id": "dlg_nonexistent",
        "delegation_root_mission_id": str(mission.id),
        "delegation_root_action_id": "p1",
        "delegation_root_governed_registration_id": grid,
        "delegation_root_generation": gen,
        "delegation_delegator_grid": grid,
        "delegation_delegator_agent_id": "ex-rt",
        "delegation_delegate_agent_id": "delegate-1",
        "delegation_delegate_grid": "gov-delegate-1",
        "delegation_allowed_capabilities": ["c.rt"],
        "delegation_allowed_resources": [{"resource_id": "r",
                                          "governed_registration_id": grid,
                                          "generation": gen}],
        "delegation_allowed_targets": [],
        "delegation_max_risk_level": "critical",
        "delegation_max_timeout_seconds": 3600.0,
        "delegation_require_verification": True,
        "delegation_max_side_effect": "EXTERNAL_IRREVERSIBLE",
        "delegation_created_at": "2026-01-01T00:00:00Z",
        "delegation_expires_at": "",
        "delegation_state": "ACTIVE",
        "delegation_revoked_at": "",
        "delegation_revoke_reason": "",
    }
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": node, "grid": grid, "gen": gen,
         "executor": "delegate-1", "grant": grant},
    ])
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(str(mission.id), "g1", [node])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_adv_target_substitution_refused(tmp_path):
    """An action retargeted after grant issuance fails the handoff check:
    the substituted target is outside the granted scope."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "adv-tgt")
    store = _mission_store(tmp_path)
    node = _make_node(node_id="c1", agent_id="delegate-1",
                      idempotency_key="rk-c")
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen,
         "resource_id": "t-original"},
        {"node": node, "grid": grid, "gen": gen,
         "executor": "delegate-1", "resource_id": "t-original"},
    ])
    authority = _authority(store)
    authority.transition_action(
        str(mission.id), "p1", 1, ActionState.PENDING,
        ActionState.AUTHORIZED, _ev())
    authority.grant_delegation(
        str(mission.id), "c1", 2, parent_action_id="p1",
        delegate_agent_id="delegate-1",
        delegate_governed_registration_id="gov-delegate-1",
        allowed_capabilities=["c.rt"],
        allowed_resources=[{"resource_id": "t-original",
                            "governed_registration_id": grid,
                            "generation": gen}],
        allowed_targets=["t-original"],
        max_risk_level="critical", max_timeout_seconds=3600.0,
        require_verification=True,
        max_side_effect="EXTERNAL_IRREVERSIBLE", expires_at="")
    # File-level retargeting (bypasses commit validation, as an attacker
    # with store write access could attempt): handoff still refuses.
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    data = json.loads(mission_file.read_text())
    data["action_states"]["c1"]["expected_resource_id"] = "t-substituted"
    mission_file.write_text(json.dumps(data))
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(str(mission.id), "g1", [node])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_adv_revocation_between_planning_and_handoff(tmp_path):
    """Ownership won, then revoked before result: the handoff cannot
    complete; stale ownership fails closed."""
    from intent_kernel.mission import DispatchAttemptSpec, spec_for_runtime_node
    ctx = await _governed_pair(tmp_path, name="adv-rev")
    _grant_std(ctx["authority"], ctx)
    guard = _guard_for(ctx["store"])
    # Acquire exactly as the runtime does for governed actions: the spec
    # carries the durable grid/generation (acquire_for_node builds an
    # empty-field spec, which cannot match a governed binding).
    base = spec_for_runtime_node(ctx["mid"], ctx["child_node"])
    ownership = guard.acquire(
        DispatchAttemptSpec(
            mission_id=base.mission_id,
            action_id=base.action_id,
            request_semantics_digest=base.request_semantics_digest,
            executor_logical_id=base.executor_logical_id,
            expected_governed_registration_id=ctx["grid"],
            expected_resource_generation=ctx["gen"],
        ),
        requested_by="test",
    )
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "test")
    import pytest as _p
    from intent_kernel.mission import DispatchGuardError
    with _p.raises(DispatchGuardError):
        guard.record_result(ownership, result_summary={"ok": True})


@pytest.mark.asyncio
async def test_adv_corrupt_durable_delegation_fails_closed(tmp_path):
    """A malformed grant blob in the durable file fails load validation:
    no handoff, loud error, nothing dispatched."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    grid, gen, _snap = _govern(components, app)
    mission = await _started_mission(components, "adv-corrupt")
    store = _mission_store(tmp_path)
    node = _make_node(node_id="c1", agent_id="delegate-1",
                      idempotency_key="rk-c")
    _bind_record(store, str(mission.id), [
        {"node": _make_node(node_id="p1"), "grid": grid, "gen": gen},
        {"node": node, "grid": grid, "gen": gen,
         "executor": "delegate-1"},
    ])
    import json
    from pathlib import Path
    mission_file = next(Path(store._missions_dir).glob("*.json"))
    data = json.loads(mission_file.read_text())
    # Partial grant: id set but capability scope missing.
    data["action_states"]["c1"]["delegation_id"] = "dlg_corrupt"
    data["action_states"]["c1"]["delegation_state"] = "ACTIVE"
    mission_file.write_text(json.dumps(data))
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(str(mission.id), "g1", [node])
    import pytest as _p
    with _p.raises(Exception):
        await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# D22/D23/D24
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_d22_grant_revocation_evidence_durable(tmp_path):
    """Grant + revocation leave a complete, revision-anchored evidence
    trail: lineage, timestamps, reason, terminal state, intact history."""
    ctx = await _governed_pair(tmp_path, name="d22")
    result = _grant_std(ctx["authority"], ctx)
    assert result.mission_revision == ctx["rev"] + 1
    rev = _rev(ctx["store"], ctx["mid"])
    ctx["authority"].revoke_delegation(ctx["mid"], "c1", rev, "audit-test")
    data = ctx["store"].load(ctx["mid"])
    assert data["revision"] == rev + 1
    action = data["action_states"]["c1"]
    assert action["delegation_id"].startswith("dlg_")
    assert action["delegation_parent_action_id"] == "p1"
    assert action["delegation_root_action_id"] == "p1"
    assert action["delegation_state"] == "REVOKED"
    assert action["delegation_revoked_at"] != ""
    assert action["delegation_revoke_reason"] == "audit-test"
    assert action["delegation_created_at"] != ""
    assert action["state"] == ActionState.PENDING.value


@pytest.mark.asyncio
async def test_d24_composition_without_parallel_system(tmp_path):
    """D24: delegation rides the existing composed authority: no
    delegation store, no delegation RRM, no delegation service object
    exists anywhere in the composition; the authority exposes exactly
    the two reviewed methods."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    authority = components.mission_runtime.dispatch_guard._authority
    assert hasattr(authority, "grant_delegation")
    assert hasattr(authority, "revoke_delegation")
    assert not hasattr(components, "delegation_store")
    assert not hasattr(components, "delegation_service")
    assert not hasattr(components, "delegation_authority")
    assert components.mission_runtime.dispatch_guard is not None
    assert components.mission_runtime._mission_record_store is not None

