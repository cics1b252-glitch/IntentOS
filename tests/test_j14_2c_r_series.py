"""J1.4.2C — R1-R7 + A-P gap coverage through REAL productive paths.

Every test below traverses the actual plan-acceptance authority
(MissionRuntime.create_instance -> _anchor_mission_record ->
prove_plan_actions_against_authority -> store.create), the REAL
ProductBridge controlled-mission path, or the REAL grant
proposal/approval/establishment chain.

Nothing here invokes the pure proof helper in isolation as authority
evidence, and nothing reuses a C1 identity test or a B4R2 RRM rebinding
test as a substitute for a J1 authority-derivation condition:

- C1 proves PRESENTED REQUEST == AUTHORIZED REQUEST (identity/binding).
- B4R2 proves RRM binding liveness (registration/generation/eligibility).
- THESE tests prove PLAN ACTION <= EXPLICITLY GRANTED INTENT AUTHORITY
  (derivation from an explicit grant through the productive anchor).

Conventions (matching production semantics in
intent_kernel/runtime/mission_runtime.py::_anchor_mission_record):
- plan "target" is the capability-id identity space (production maps
  target := contract.capability); target_scope therefore holds
  capability ids. Capability IDs share one canonical identity space.
- Denial raises IntentAuthorityError BEFORE store.create: a denied plan
  leaves zero durable mutation (store.load(mid) is None).
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.intent_authority import (
    IntentAuthorityError,
    establish_intent_authority,
    prove_plan_actions_against_authority,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    establish_intent_authority_from_grant,
    propose_intent_authority,
)
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    SideEffectLevel,
)
from intent_kernel.time_utils import utc_iso


NOW = "2026-10-03T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers (no shadow anchor: the REAL create_instance path is always used)
# ---------------------------------------------------------------------------

def _store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _runtime(store):
    return MissionRuntime(mission_record_store=store)


def _grant_chain(capabilities, operations=("READ",), targets=None,
                 risk="low", side_effect="NONE", verification=True,
                 source="user_explicit", identity="j14-2c"):
    """Full PROPOSED -> APPROVED -> ESTABLISHED chain for an exact scope."""
    targets = targets if targets is not None else tuple(capabilities)
    proposal = propose_intent_authority(
        allow_capabilities=tuple(capabilities),
        allowed_operations=tuple(operations),
        target_scope=tuple(targets),
        max_risk_level=risk,
        max_side_effect=side_effect,
        require_verification=verification,
        rationale="j14-2c r-series",
    )
    grant = approve_intent_authority(
        proposal,
        authority_source_type=source,
        authority_source_identity=identity,
        approved_at=NOW,
    )
    return establish_intent_authority_from_grant(grant, now_iso=NOW)


def _node(node_id="n1", capability="c.rt", operation="READ",
           risk="low", side_effect=SideEffectLevel.NONE, verification=True):
    contract = ActionContract(
        action_id=node_id, capability=capability,
        idempotency_key=f"rk-{node_id}",
        action_type=operation,
        risk_level=risk, side_effect_level=side_effect,
        verification_required=verification,
    )
    node = RuntimeNode(
        node_id=node_id, capability=capability,
        agent_id="agent_default", action_contract=contract,
    )
    contract.action_id = node.node_id
    return node


def _anchor(runtime, mid, nodes, authority):
    return runtime.create_instance(mid, "g1", nodes, intent_authority=authority)


# ---------------------------------------------------------------------------
# R1: approved A -> resolved A -> PASS (real anchor + persisted record)
# ---------------------------------------------------------------------------

def test_r1_approved_a_resolved_a_passes(tmp_path):
    """R1 PROVEN INVARIANT: an explicitly granted capability resolved by the
    planner is accepted into canonical durable authority."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    authority = _grant_chain(("c.rt",))
    inst = _anchor(runtime, "m-r1", [_node(capability="c.rt")], authority)
    data = store.load("m-r1")
    assert data is not None
    assert len(data["plan"]) == 1
    assert data["plan"][0]["capability"] == "c.rt"
    assert inst.status is not None


# ---------------------------------------------------------------------------
# R2: approved A -> resolved B outside scope -> DENY (real anchor)
# ---------------------------------------------------------------------------

def test_r2_approved_a_resolved_b_denies(tmp_path):
    """R2 PROVEN INVARIANT: resolution outside the granted scope cannot
    become canonical plan, even though the grant itself is valid."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    authority = _grant_chain(("c.rt",))
    with pytest.raises(IntentAuthorityError, match="outside established intent authority"):
        _anchor(runtime, "m-r2", [_node(capability="c.OTHER")], authority)
    assert store.load("m-r2") is None


# ---------------------------------------------------------------------------
# R3: proposed A -> resolved B never approved -> DENY (real anchor)
# ---------------------------------------------------------------------------

def test_r3_never_approved_b_denies(tmp_path):
    """R3 PROVEN INVARIANT: only the EXACT approved scope authorizes. B was
    in no proposal and no approval, so B is denied although A is granted."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    # Proposal+approval covered only c.rt; nothing ever approved c.B.
    authority = _grant_chain(("c.rt",))
    with pytest.raises(IntentAuthorityError, match="capability-escalation"):
        _anchor(runtime, "m-r3", [_node(capability="c.B")], authority)
    assert store.load("m-r3") is None


# ---------------------------------------------------------------------------
# R4: resolved capability changes after approval -> DENY (real anchor)
# ---------------------------------------------------------------------------

def test_r4_capability_changed_after_approval_denies(tmp_path):
    """R4 PROVEN INVARIANT: post-approval substitution of the resolved
    capability is denied; approval is bound to the exact approved scope."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    authority = _grant_chain(("c.rt",))
    # What was approved (c.rt) is not what got resolved (c.swapped).
    with pytest.raises(IntentAuthorityError, match="outside established intent authority"):
        _anchor(runtime, "m-r4", [_node(capability="c.swapped")], authority)
    assert store.load("m-r4") is None


# ---------------------------------------------------------------------------
# R5: framework permission allows B but grant excludes B -> DENY
# ---------------------------------------------------------------------------

def test_r5_framework_allows_but_grant_excludes_denies(tmp_path):
    """R5 PROVEN INVARIANT: framework-level permission is not intent
    authority. The node carries a framework-allowed marker, yet the
    explicit grant excludes its capability, so the anchor denies.

    REAL PRODUCTBRIDGE PATH = NO (runtime anchor path); framework
    permission != grant is additionally proven end-to-end by R5-bridge.
    EXPLICIT GRANT INVOLVED = YES (grant for c.rt only)."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    authority = _grant_chain(("c.rt",))
    node = _node(capability="c.framework_allowed")
    node.action_contract.required_permissions = ["c.framework_allowed"]
    with pytest.raises(IntentAuthorityError, match="capability-escalation"):
        _anchor(runtime, "m-r5", [node], authority)
    assert store.load("m-r5") is None


# ---------------------------------------------------------------------------
# R6: synthetic GRANTED + grant excludes capability -> DENY (real anchor)
# ---------------------------------------------------------------------------

def test_r6_synthetic_granted_excluded_capability_denies(tmp_path):
    """R6 PROVEN INVARIANT: PermissionDecisionState.GRANTED != Intent
    Authority. A synthetic GRANTED marker in contract provenance cannot
    admit a capability the explicit grant excludes.

    EXPLICIT GRANT INVOLVED = YES (grant for c.rt; node needs c.evil)."""
    store = _store(tmp_path)
    runtime = _runtime(store)
    authority = _grant_chain(("c.rt",))
    contract = ActionContract(
        capability="c.evil", action_type="SIMULATED",
        inputs_reference={"message": "t"},
        side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
        provenance={"synthetic": True, "authorization_status": "GRANTED"},
    )
    node = RuntimeNode(capability="c.evil", action_contract=contract)
    contract.action_id = node.node_id
    with pytest.raises(IntentAuthorityError, match="capability-escalation"):
        _anchor(runtime, "m-r6", [node], authority)
    assert store.load("m-r6") is None


# ---------------------------------------------------------------------------
# R7: explicit grant covers exact resolved capability -> PASS (real bridge)
# ---------------------------------------------------------------------------

def _bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from product_bridge import ProductBridge
    return ProductBridge()


async def _bridge_grant_for(bridge, message, permissions):
    from intent_kernel.mission.intent_grant import (
        approve_intent_authority as _approve,
        propose_intent_authority as _propose,
    )
    turn = await bridge.conversation_service.analyze_turn(
        message, project_id="GLOBAL", authorized_permissions=permissions,
    )
    resolved = tuple(
        r.capability_id for r in getattr(turn.capability_decision, "requirements", ())
        if r.capability_id
    )
    capabilities = resolved or ("knowledge.search",)
    proposal = _propose(
        allow_capabilities=capabilities,
        allowed_operations=("READ", "GENERATE", "SIMULATED"),
        target_scope=capabilities,
        max_risk_level="low",
        max_side_effect="EXTERNAL_REVERSIBLE",
        require_verification=True,
        rationale="r7 exact resolved scope",
    )
    return _approve(
        proposal,
        authority_source_type="user_explicit",
        authority_source_identity="j14-2c-r7",
        approved_at="2026-10-03T00:00:00+00:00",
    ).to_dict(), capabilities


@pytest.mark.asyncio
async def test_r7_exact_grant_resolved_capability_passes_bridge(tmp_path, monkeypatch):
    """R7 PROVEN INVARIANT: an explicit grant covering the EXACT resolved
    capability (remaining dimensions conforming) reaches governed runtime.

    REAL PRODUCTBRIDGE PATH = YES. EXPLICIT GRANT INVOLVED = YES."""
    bridge = _bridge(tmp_path, monkeypatch)
    grant, _caps = await _bridge_grant_for(bridge, "Crie e envie um e-mail.", ["email.send"])
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
        "intent_authority_grant": grant,
    })
    assert response["execution_mode"] == "MISSION"
    assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    assert response["mission_id"]


@pytest.mark.asyncio
async def test_r2_bridge_resolved_outside_grant_denies(tmp_path, monkeypatch):
    """R2 (bridge end): approved knowledge.search only, message resolves
    email.send -> the J1 anchor denies; nothing becomes canonical plan.

    REAL PRODUCTBRIDGE PATH = YES. EXPLICIT GRANT INVOLVED = YES."""
    from intent_kernel.mission.intent_authority import IntentAuthorityError
    bridge = _bridge(tmp_path, monkeypatch)
    turn = await bridge.conversation_service.analyze_turn(
        "Crie e envie um e-mail.", project_id="GLOBAL",
        authorized_permissions=["email.send"],
    )
    resolved = tuple(
        r.capability_id for r in getattr(turn.capability_decision, "requirements", ())
        if r.capability_id
    )
    assert resolved, "analyzer must resolve a capability for this message"
    # The framework permission (email.send) is NOT the resolved capability
    # id; the grant below excludes every resolved id by construction.
    grant_proposal = propose_intent_authority(
        allow_capabilities=("knowledge.search",),
        allowed_operations=("READ",),
        target_scope=("knowledge.search",),
        max_risk_level="low",
        max_side_effect="EXTERNAL_REVERSIBLE",
        require_verification=True,
        rationale="r2 disjoint grant",
    )
    assert not (set(resolved) & {"knowledge.search"})
    grant = approve_intent_authority(
        grant_proposal,
        authority_source_type="user_explicit",
        authority_source_identity="j14-2c-r2",
        approved_at="2026-10-03T00:00:00+00:00",
    ).to_dict()
    # Grant scope is unrelated to every resolved capability id.
    with pytest.raises(IntentAuthorityError, match="outside established intent authority"):
        await bridge.dispatch({
            "action": "chat",
            "message": "Crie e envie um e-mail.",
            "authorized_permissions": ["email.send"],
            "intent_authority_grant": grant,
        })


@pytest.mark.asyncio
async def test_r5_bridge_framework_allow_grant_excludes_denies(tmp_path, monkeypatch):
    """R5 (bridge end): framework authorization ALLOWs email.send, but the
    explicit grant excludes it -> J1 denies. Framework GRANTED != authority.

    REAL PRODUCTBRIDGE PATH = YES. EXPLICIT GRANT INVOLVED = YES."""
    from intent_kernel.mission.intent_authority import IntentAuthorityError
    bridge = _bridge(tmp_path, monkeypatch)
    proposal = propose_intent_authority(
        allow_capabilities=("knowledge.search",),
        allowed_operations=("READ",),
        target_scope=("knowledge.search",),
        max_risk_level="low",
        max_side_effect="EXTERNAL_REVERSIBLE",
        require_verification=True,
        rationale="r5 grant excludes email",
    )
    grant = approve_intent_authority(
        proposal,
        authority_source_type="user_explicit",
        authority_source_identity="j14-2c-r5",
        approved_at="2026-10-03T00:00:00+00:00",
    ).to_dict()
    with pytest.raises(IntentAuthorityError, match="outside established intent authority"):
        await bridge.dispatch({
            "action": "chat",
            "message": "Crie e envie um e-mail.",
            "authorized_permissions": ["email.send"],
            "intent_authority_grant": grant,
        })


# ---------------------------------------------------------------------------
# A-P gap coverage through the REAL anchor (C-H dimensions)
# ---------------------------------------------------------------------------

def test_j142_c_capability_escalation_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",))
    with pytest.raises(IntentAuthorityError, match="capability-escalation"):
        _anchor(_runtime(store), "m-c", [_node(capability="c.NOPE")], authority)
    assert store.load("m-c") is None


def test_j142_d_operation_escalation_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",), operations=("READ",))
    with pytest.raises(IntentAuthorityError, match="operation-escalation"):
        _anchor(_runtime(store), "m-d", [_node(operation="DELETE")], authority)
    assert store.load("m-d") is None


def test_j142_e_target_escalation_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",), targets=("c.rt",))
    node = _node(capability="c.rt")
    node.action_contract.capability = "c.elsewhere"
    node.capability = "c.elsewhere"
    with pytest.raises(IntentAuthorityError, match="capability-escalation|target-escalation"):
        _anchor(_runtime(store), "m-e", [node], authority)
    assert store.load("m-e") is None


def test_j142_f_risk_escalation_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",), risk="low")
    with pytest.raises(IntentAuthorityError, match="risk-escalation"):
        _anchor(_runtime(store), "m-f", [_node(risk="critical")], authority)
    assert store.load("m-f") is None


def test_j142_g_side_effect_escalation_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",), side_effect="NONE")
    with pytest.raises(IntentAuthorityError, match="side-effect-escalation"):
        _anchor(
            _runtime(store), "m-g",
            [_node(side_effect=SideEffectLevel.EXTERNAL_IRREVERSIBLE)], authority,
        )
    assert store.load("m-g") is None


def test_j142_h_verification_weakening_real_anchor(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",), verification=True)
    with pytest.raises(IntentAuthorityError, match="verification-weakened"):
        _anchor(_runtime(store), "m-h", [_node(verification=False)], authority)
    assert store.load("m-h") is None


# ---------------------------------------------------------------------------
# I: temporal invalid/unknown -> DENY (establishment + real anchor)
# ---------------------------------------------------------------------------

def test_j142_i_temporal_missing_clock_establishment_denies():
    """A temporal ceiling without an explicit current clock cannot be
    established: UNKNOWN validity is never valid authority."""
    ceiling = IntentCeiling(
        allow_capabilities=("c.rt",),
        valid_until="2100-01-01T00:00:00+00:00",
    )
    with pytest.raises(IntentAuthorityError, match="ceiling-temporal-unknown"):
        establish_intent_authority(
            ceiling=ceiling, source_type="user_explicit",
            source_identity="t", established_at=NOW, now_iso="",
        )


def test_j142_i_expired_grant_real_anchor_denies(tmp_path):
    """An expired temporal grant cannot be established: DENY AT ESTABLISHMENT
    with ceiling-expired. No IntentAuthorityRecord is created, so nothing
    reaches the productive anchor."""
    proposal = propose_intent_authority(
        allow_capabilities=("c.rt",),
        valid_until="2020-01-01T00:00:00+00:00",
        rationale="expired",
    )
    grant = approve_intent_authority(
        proposal, authority_source_type="user_explicit",
        authority_source_identity="t", approved_at="2020-01-01T00:00:00+00:00",
    )
    with pytest.raises(IntentAuthorityError, match="ceiling-expired"):
        establish_intent_authority_from_grant(grant, now_iso=utc_iso())
    # No authority established, so nothing to anchor
    store = _store(tmp_path)
    assert store.load("m-i") is None


# ---------------------------------------------------------------------------
# J: mixed valid/invalid multi-action -> DENY canonical authority
# ---------------------------------------------------------------------------

def test_j142_j_mixed_multi_action_real_anchor_denies(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",))
    nodes = [_node("n1", capability="c.rt"), _node("n2", capability="c.BAD")]
    with pytest.raises(IntentAuthorityError, match="outside established intent authority"):
        _anchor(_runtime(store), "m-j", nodes, authority)
    assert store.load("m-j") is None


# ---------------------------------------------------------------------------
# L: restart preserves exact authority (reload + re-proof)
# ---------------------------------------------------------------------------

def test_j142_l_restart_preserves_exact_authority(tmp_path):
    store = _store(tmp_path)
    authority = _grant_chain(("c.rt",))
    _anchor(_runtime(store), "m-l", [_node(capability="c.rt")], authority)
    # Fresh store object over the same durable files (restart view).
    store2 = JsonFileMissionRecordStore(
        missions_dir=tmp_path / "mstore" / "missions",
        continuity_file=tmp_path / "mstore" / "cont" / "identity.json",
    )
    data = store2.load("m-l")
    assert data is not None
    from intent_kernel.mission.mission_record import MissionDefinition, MissionRecord
    definition = MissionDefinition.from_dict(dict(data["mission_definition"]))
    assert definition.intent_ceiling is not None
    assert definition.intent_ceiling.to_dict() == authority.ceiling.to_dict()
    assert definition.intent_authority is not None
    assert definition.intent_authority.authority_digest == authority.authority_digest
    # Carried definition digest still matches recomputation over content.
    record = MissionRecord.from_dict(dict(data))
    assert record.mission_definition_digest == record.compute_definition_digest()
    # The persisted plan still proves against the reloaded authority.
    prove_plan_actions_against_authority(
        definition.intent_authority, list(data["plan"]), now_iso=utc_iso()
    )


# ---------------------------------------------------------------------------
# M: tampered record/digest fails at the commit boundary
# ---------------------------------------------------------------------------

def test_j142_m_tampered_digest_commit_boundary_denies(tmp_path):
    """A valid-shaped but altered ceiling with a stale digest cannot be
    committed: the store never carries an unchecked digest.

    NOTE (loading semantic, pre-existing, not J1-specific): file loads are
    shape-validated; the definition-digest recomputation is enforced at
    commit boundaries. Post-anchor file tamper has no productive consumer:
    the authority decision happens once, at anchor, from the authority
    object — never by re-reading file content as authority."""
    from intent_kernel.mission.mission_record import (
        MissionDefinition,
        MissionRecord,
        MissionStatus,
    )
    from intent_kernel.mission.store import MissionRecordValidationError
    store = _store(tmp_path)
    ident = store.get_continuity_identity()
    authority = _grant_chain(("c.rt",))
    definition = MissionDefinition(
        objective="m", context={},
        intent_ceiling=authority.ceiling, intent_authority=authority,
    )
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition)
    record = MissionRecord(
        mission_id="m-m", installation_id=ident, revision=1,
        runtime_id="rt", mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING, plan=(), action_states={},
    )
    assert store.create(record).outcome == "committed"
    # Tamper 1 (deserialization boundary): valid-shaped broader ceiling
    # against the attested authority -> from_dict denies (ceiling/authority
    # coherence is enforced before any object exists).
    raw = dict(store.load("m-m"))
    raw["mission_definition"]["intent_ceiling"]["allow_capabilities"] = ["c.rt", "c.BROAD"]
    with pytest.raises(ValueError, match="does not match attested"):
        MissionRecord.from_dict(raw)
    # Tamper 2 (commit boundary): stale carried digest with changed content
    # can never commit; the store never carries an unchecked digest.
    stale = MissionRecord(
        mission_id="m-m2", installation_id=ident, revision=1,
        runtime_id="rt", mission_definition=definition,
        mission_definition_digest="stale-digest",
        mission_status=MissionStatus.RUNNING, plan=(), action_states={},
    )
    assert stale.mission_definition_digest != stale.compute_definition_digest()
    with pytest.raises(MissionRecordValidationError, match="does not match"):
        store.create(stale)


# ---------------------------------------------------------------------------
# N: generic confirmation without structured approval -> no authority
# ---------------------------------------------------------------------------

def test_j142_n_generic_confirmation_is_not_a_grant():
    """Approval requires the explicit proposal object; a generic
    confirmation/yes string can never become an IntentAuthorityGrant, and a
    non-grant can never establish canonical authority."""
    proposal = propose_intent_authority(
        allow_capabilities=("c.rt",), rationale="n")
    with pytest.raises(IntentAuthorityError, match="explicit ProposedIntentAuthority"):
        approve_intent_authority(
            "yes",
            authority_source_type="user_explicit",
            authority_source_identity="n",
            approved_at=NOW,
        )
    assert proposal.scope_digest
    with pytest.raises(IntentAuthorityError, match="explicit IntentAuthorityGrant"):
        establish_intent_authority_from_grant({"not": "a grant"}, now_iso=NOW)


# ---------------------------------------------------------------------------
# O: proposal altered after approval -> DENY at establishment
# ---------------------------------------------------------------------------

def test_j142_o_altered_after_approval_denies():
    """The scope approved is not the scope presented at establishment:
    digest recheck fails closed."""
    proposal = propose_intent_authority(
        allow_capabilities=("c.rt",), rationale="o")
    grant = approve_intent_authority(
        proposal, authority_source_type="user_explicit",
        authority_source_identity="o", approved_at=NOW,
    )
    altered_ceiling = IntentCeiling(allow_capabilities=("c.rt", "c.SNEAKED"))
    # Post-approval alteration bypassing grant construction (the frozen
    # guard bypassed exactly as a memory-level tamper would): the approved
    # digest still attests the ORIGINAL scope.
    object.__setattr__(grant, "ceiling", altered_ceiling)
    from intent_kernel.mission.intent_grant import compute_scope_digest
    assert grant.approved_scope_digest != compute_scope_digest(altered_ceiling)
    with pytest.raises(IntentAuthorityError, match="does not match approved scope"):
        establish_intent_authority_from_grant(grant, now_iso=NOW)


# ---------------------------------------------------------------------------
# P: grant broader than approved proposal -> DENY at grant construction
# ---------------------------------------------------------------------------

def test_j142_p_broader_than_approved_denies():
    """A grant object whose ceiling exceeds its approved scope digest fails
    closed at construction: approved_scope_digest binds the exact scope."""
    proposal = propose_intent_authority(
        allow_capabilities=("c.rt",), rationale="p")
    broader = IntentCeiling(allow_capabilities=("c.rt", "c.BROAD"))
    from intent_kernel.mission.intent_grant import IntentAuthorityGrant
    with pytest.raises(IntentAuthorityError, match="does not match the granted scope"):
        IntentAuthorityGrant(
            ceiling=broader,
            approved_scope_digest=proposal.scope_digest,
            authority_source_type="user_explicit",
            authority_source_identity="p",
            approved_at=NOW,
        )


# ---------------------------------------------------------------------------
# Section 1: ACTION_CONTRACT == RESOLVED == J1-CHECKED (durable layer)
# ---------------------------------------------------------------------------

def test_j142_action_contract_capability_equals_j1_checked(tmp_path):
    """The J1-checked plan capability is the resolved capability carried by
    both node and contract: no substitution between contract, node, and the
    durable plan entry is possible without breaking the proof."""
    store = _store(tmp_path)
    authority = _grant_chain(("c.resolved",))
    node = _node(capability="c.resolved")
    assert node.action_contract.capability == "c.resolved"
    _anchor(_runtime(store), "m-eq", [node], authority)
    data = store.load("m-eq")
    assert data["plan"][0]["capability"] == "c.resolved"
    assert data["plan"][0]["capability"] == node.capability
    assert data["plan"][0]["capability"] == node.action_contract.capability
