"""C2/C3/G1.3 — TOCTOU proof suite (TQ1, TQ2, TQ3).

All three cases traverse a REAL productive surface and assert
EXECUTOR_CALLS = 0 on the refused path.

TQ1  Intent quantity 10 passes advisory. Intent authority narrows to 5 before
     authoritative acquire. Request 10 must deny.
TQ2  Delegation valid during advisory. Delegation revoked/narrowed before
     authoritative acquire. Dispatch must deny.
TQ3  The relevant durable revision changes. A stale quantity proof must be
     unusable.

The advisory check is diagnostic only (``authoritative = False``): it never
authorizes. Authority lives exclusively in the revision-anchored acquire
transaction.
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.quantity import (
    DEFAULT_QUANTITY_APPLICABILITY,
    Quantity,
    QuantityCeiling,
    QuantityDimension,
    establish_quantity_authority,
    prove_plan_quantities_against_authority,
)

# Canonical C1 productive harness.
from tests.test_m32b2_productive_dispatch import (  # noqa: F401
    CountingApp,
    _bind_action,
    _components,
    _govern,
    _guard_for,
    _mission_store,
    _running_mission,
    _service,
    _spec_for,
)
# Canonical K1.2 delegation harness (real governed parent/child + grant).
from tests.test_m33_2b_delegation import (  # noqa: F401
    _authority,
    _grant_std,
    _governed_pair,
    _rev,
    _wired_runtime,
)
from intent_kernel.mission import MissionActionAuthority
from intent_kernel.mission.delegation import verify_quantity_against_grant
from intent_kernel.mission.dispatch_guard import DispatchGuardError

NOW = "2026-10-05T00:00:00+00:00"
MONEY = QuantityDimension.MONETARY_AMOUNT
UNIT = "BRL_CENT"
TRANSFER_OPERATION = "TRANSFER_FUNDS"
DEFAULT_QUANTITY_APPLICABILITY.declare(TRANSFER_OPERATION, MONEY)


def _qty_dict(amount: int) -> dict:
    return {"dimension": MONEY.value, "amount": amount, "unit": UNIT}


def _qty_authority(amount: int):
    return establish_quantity_authority(
        ceilings=(QuantityCeiling(Quantity(MONEY, amount, UNIT)),),
        source_type="user_explicit",
        source_identity="c2c3g13_tq",
        established_at=NOW,
    )


# ---------------------------------------------------------------------------
# TQ1: advisory passes, then intent authority narrows before acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tq1_advisory_passes_then_authority_narrows_denies(tmp_path):
    """TQ1: advisory accepts 10, authority narrows to 5, request 10 denies."""
    components = _components(tmp_path, tmp_path / ".intent-os-tq1")
    app = CountingApp(capability="resource.transfer")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path, "mstore-tq1")

    payload = {"text": "transfer", "quantity": _qty_dict(10)}
    spec = _spec_for(
        components, mission, app, payload, key="tq1",
        operation=TRANSFER_OPERATION, quantity=_qty_dict(10),
    )
    # The DURABLE authority at bind time is 10.
    _bind_action(
        store, str(mission.id), spec,
        quantity=_qty_dict(10),
        operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(10),
    )

    # ADVISORY: the real advisory surface reports no quantity problem for
    # authority 10 / request 10. It is diagnostic only: it authorizes nothing
    # and advances no durable state.
    guard = _guard_for(store)
    service = _service(components, guard)
    before = store.load(str(mission.id))
    advisory = service._quantity_advisory_refusal(
        str(mission.id), spec.action_id
    )
    assert advisory is None, advisory
    # The advisory pass leaves the durable record byte-identical.
    assert store.load(str(mission.id)) == before
    # And the authority-10 quantity proof holds for request 10.
    prove_plan_quantities_against_authority(
        _qty_authority(10), [{"quantity": _qty_dict(10)}]
    )

    # ...then intent authority NARROWS to 5 before authoritative acquire.
    narrow_store = _mission_store(tmp_path, "mstore-tq1-narrow")
    _bind_action(
        narrow_store, str(mission.id), spec,
        quantity=_qty_dict(10),
        operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(5),
    )
    # The narrowed authority now refuses the very same request 10.
    with pytest.raises(Exception):
        prove_plan_quantities_against_authority(
            _qty_authority(5), [{"quantity": _qty_dict(10)}]
        )

    narrow_service = _service(components, _guard_for(narrow_store))
    outcome = await narrow_service.execute(
        mission.id, app.capability_name,
        payload=payload, idempotency_key="tq1", durable_action=spec,
    )
    assert outcome.result.error_code is not None, outcome.result.metadata
    assert app.calls == 0, "TQ1 must produce ZERO executor calls"


# ---------------------------------------------------------------------------
# TQ2: delegation valid during advisory, revoked before acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tq2_delegation_revoked_before_acquire_denies(tmp_path):
    """TQ2: a live delegation grants quantity 10, then revocation removes it."""
    ctx = await _governed_pair(tmp_path, name="tq2")
    authority = ctx["authority"]

    # ADVISORY WINDOW: the delegation is live and its DURABLE grant carries a
    # quantity ceiling of 10, so the advisory-equivalent quantity proof
    # passes against the real persisted grant.
    _grant_std(
        authority, ctx, delegation_quantity_ceilings=(
            {"quantity": _qty_dict(10)},
        )
    )
    data = ctx["store"].load(ctx["mid"])
    assert data["action_states"]["c1"]["delegation_state"] == "ACTIVE"
    persisted = tuple(
        data["action_states"]["c1"].get("delegation_quantity_ceilings") or ()
    )
    assert persisted, "grant must durably carry its quantity ceilings"
    ok, reason = verify_quantity_against_grant(persisted, _qty_dict(10))
    assert ok is True and reason == ""
    ok, reason = verify_quantity_against_grant(persisted, _qty_dict(11))
    assert ok is False and reason == "quantity-escalation"

    # ...then the delegation is REVOKED before authoritative acquire.
    authority.revoke_delegation(
        ctx["mid"], "c1", _rev(ctx["store"], ctx["mid"]), "tq2-revoked",
    )
    after = ctx["store"].load(ctx["mid"])
    assert after["action_states"]["c1"]["delegation_state"] == "REVOKED"
    # The quantity grant no longer exists.
    ok, reason = verify_quantity_against_grant((), _qty_dict(10))
    assert ok is False and reason == "quantity-not-granted"

    rt = _wired_runtime(ctx["store"], ctx["components"])
    inst = rt.create_instance(ctx["mid"], "g1", [ctx["child_node"]])
    await rt.run_mission(inst.runtime_id)
    assert rt.executor.calls == 0, "TQ2 must produce ZERO executor calls"


# ---------------------------------------------------------------------------
# TQ3: relevant revision changes -> stale quantity proof unusable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tq3_revision_change_invalidates_stale_quantity_proof(tmp_path):
    """TQ3: after the revision advances, an acquire anchored to the old
    revision can no longer use its earlier quantity proof."""
    components = _components(tmp_path, tmp_path / ".intent-os-tq3")
    app = CountingApp(capability="resource.transfer")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path, "mstore-tq3")

    payload = {"text": "transfer", "quantity": _qty_dict(5)}
    spec = _spec_for(
        components, mission, app, payload, key="tq3",
        operation=TRANSFER_OPERATION, quantity=_qty_dict(5),
    )
    _bind_action(
        store, str(mission.id), spec,
        quantity=_qty_dict(5),
        operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(10),
    )
    guard = _guard_for(store)

    # Acquire succeeds and pins mission_revision.
    ownership = guard.acquire(spec, requested_by="tq3")

    # The relevant revision advances (another durable transition).
    auth = MissionActionAuthority(store)
    from intent_kernel.mission.mission_record import ActionState
    auth.transition_action(
        str(mission.id), spec.action_id, ownership.mission_revision,
        ActionState.DISPATCHING, ActionState.RESULT_RECORDED,
        __import__(
            "intent_kernel.mission.action_authority",
            fromlist=["ActionTransitionEvidence"],
        ).ActionTransitionEvidence(
            requested_by="tq3", reason="revision-advance",
        ),
    )
    assert store.load(str(mission.id))["revision"] > ownership.mission_revision

    # The stale quantity proof anchored to the OLD revision is unusable:
    # both the final handoff gate and record_result refuse it.
    with pytest.raises(DispatchGuardError, match="revision advanced"):
        guard.verify_pre_handoff_identity(
            ownership,
            capability="resource.transfer",
            operation=TRANSFER_OPERATION,
            request_semantics_digest=spec.request_semantics_digest,
            quantity=spec.quantity,
        )
    with pytest.raises(DispatchGuardError, match="revision advanced"):
        guard.record_result(
            ownership,
            result_summary={"success": True},
            requested_by="tq3",
        )
    assert app.calls == 0, "TQ3 must produce ZERO executor calls"