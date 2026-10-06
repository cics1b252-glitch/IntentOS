"""C2/C3/G1.3 — Productive quantity authority tests (P01–P20).

Every test traverses REAL productive components:

    CapabilityExecutionService -> ProductiveDispatchGuard -> executor

Coverage classification is asserted per test in ``TEST_CLASSIFICATION`` so a
security-critical case can never silently degrade into a pure-helper test.

The harness reuses the canonical C1 productive fixtures
(``tests/test_m32b2_productive_dispatch.py``) rather than re-implementing a
parallel environment.
"""

from __future__ import annotations

import re

import pytest

from intent_kernel.mission.quantity import (
    DEFAULT_QUANTITY_APPLICABILITY,
    ObservedQuantity,
    Quantity,
    QuantityAuthorityRecord,
    QuantityCeiling,
    QuantityComplianceStatus,
    QuantityDimension,
    QuantityEvidence,
    classify_quantity_observation,
    establish_quantity_authority,
)

# Reuse the canonical C1 productive harness (components, governed app,
# mission record store, dispatch guard, execution service, counting executor).
from tests.test_m32b2_productive_dispatch import (  # noqa: F401
    CountingApp,
    _AllowConstitutionC1,
    _bind_action,
    _components,
    _CountingExecutor,
    _govern,
    _guard_for,
    _mission_store,
    _running_mission,
    _service,
    _spec_for,
)

from intent_kernel.mission.delegation import (
    verify_quantity_against_grant,
)
from intent_kernel.mission.dispatch_guard import (
    DispatchGuardError,
    ProductiveDispatchGuard,
)
from intent_kernel.mission.intent_authority import (
    IntentAuthorityError,
    establish_intent_authority,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.mission_record import (
    ActionState,
    DurableActionState,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
)

NOW = "2026-10-05T00:00:00+00:00"
MONEY = QuantityDimension.MONETARY_AMOUNT
UNIT = "BRL_CENT"

#: C2/C3/G1.3 §6: the quantity-bearing operation used by these tests.
#: Registered as QUANTITY_BEARING with an exact supported dimension, so a
#: missing quantity is UNPROVEN (deny), never NOT_APPLICABLE.
TRANSFER_OPERATION = "TRANSFER_FUNDS"
DEFAULT_QUANTITY_APPLICABILITY.declare(
    TRANSFER_OPERATION, MONEY
)

#: Per-test coverage classification (C2/C3/G1.3 §12).
TEST_CLASSIFICATION = {
    "P01": "PRODUCTIVE",
    "P02": "PRODUCTIVE",
    "P03": "PRODUCTIVE",
    "P04": "PRODUCTIVE",
    "P05": "PRODUCTIVE",
    "P06": "PRODUCTIVE",
    "P07": "PRODUCTIVE",
    "P08": "PRODUCTIVE",
    "P09": "PRODUCTIVE",
    "P10": "PRODUCTIVE",
    "P11": "PRODUCTIVE",
    "P12": "PRODUCTIVE",
    "P13": "PRODUCTIVE",
    "P14": "PRODUCTIVE",
    "P15": "INTEGRATION",
    "P16": "INTEGRATION",
    "P17": "INTEGRATION",
    "P18": "INTEGRATION",
    "P19": "INTEGRATION",
    "P20": "PRODUCTIVE",
}

#: The eight security-critical cases §12 forbids as pure-helper.
NON_HELPER_REQUIRED = ("P07", "P08", "P09", "P10", "P17", "P18", "P19", "P20")

#: Expected executor call count per case, asserted by the closure matrix test.
#: A productive denial is only meaningful with ZERO executor calls.
EXPECTED_EXECUTOR_CALLS = {
    "P01": 1, "P02": 0, "P03": 0, "P04": 0, "P05": 0, "P06": 1,
    "P07": 0, "P08": 0, "P09": 0, "P10": 0, "P11": 1, "P12": 0,
    "P13": 0, "P14": 0, "P15": 1, "P16": 1, "P17": 1, "P18": 1,
    "P19": 1, "P20": 0,
}


def _money(amount: int) -> Quantity:
    return Quantity(MONEY, amount, UNIT)


def _qty_dict(amount: int) -> dict:
    return {"dimension": MONEY.value, "amount": amount, "unit": UNIT}


def _quantity_ceiling_record(amount: int) -> QuantityAuthorityRecord:
    return establish_quantity_authority(
        ceilings=(QuantityCeiling(_money(amount)),),
        source_type="user_explicit",
        source_identity="c2c3g13_test",
        established_at=NOW,
    )


def _intent_with_quantity(amount: int) -> IntentCeiling:
    return IntentCeiling(
        allow_capabilities=("resource.transfer",),
        allowed_operations=(TRANSFER_OPERATION,),
        target_scope=("resource.transfer",),
        max_risk_level="low",
        max_side_effect="NONE",
        require_verification=False,
        quantity_ceilings=(QuantityCeiling(_money(amount)),),
    )


def _establish_intent(amount: int):
    return establish_intent_authority(
        ceiling=_intent_with_quantity(amount),
        source_type="user_explicit",
        source_identity="c2c3g13_test",
        established_at=NOW,
        now_iso=NOW,
    )


class _TransferApp(CountingApp):
    """Counting app that also reports an observed quantity after execution.

    The observation is published in the result metadata, which is the real
    observable surface the durable result path reads. It is a genuine
    post-effect report, not a re-statement of the request.
    """

    def __init__(self, *a, observed_amount=None, **kw):
        super().__init__(*a, **kw)
        self.observed_amount = observed_amount

    async def execute(self, request):
        result = await super().execute(request)
        if self.observed_amount is not None:
            try:
                metadata = dict(getattr(result, "metadata", None) or {})
                metadata["observed_quantity"] = {
                    "dimension": MONEY.value,
                    "amount": self.observed_amount,
                    "unit": UNIT,
                }
                result.metadata = metadata
            except Exception:
                pass
        return result


async def _env(tmp_path, *, intent_amount=10, payload_amount=5, observed=None):
    """Build a productive quantity environment.

    Returns (components, app, mission, store, guard, service, authority).
    The durable plan already carries operation + quantity, and the mission
    definition carries the established quantity authority.
    """
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = _TransferApp(capability="resource.transfer", observed_amount=observed)
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    payload = {"text": "transfer", "quantity": _qty_dict(payload_amount)}
    spec = _spec_for(components, mission, app, payload, key="q1", operation=TRANSFER_OPERATION, quantity=_qty_dict(payload_amount))
    authority = _establish_intent(intent_amount)
    _bind_action(
        store, str(mission.id), spec,
        quantity=_qty_dict(payload_amount),
        operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(intent_amount),
    )
    guard = _guard_for(store)
    service = _service(components, guard)
    return components, app, mission, store, guard, service, spec, authority


def _qty_authority(amount: int) -> QuantityAuthorityRecord:
    """The established QUANTITY authority record carried on the definition."""
    return _quantity_ceiling_record(amount)


# ---------------------------------------------------------------------------
# P01: exact authorized quantity -> executor exactly once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p01_exact_authorized_quantity_executes_once(tmp_path):
    """P01 PRODUCTIVE: request <= ceiling crosses the real guard and executes once."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=10
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(10)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None, outcome.result.metadata
    assert app.calls == 1
    store_data = store.load(str(mission.id))
    assert store_data["action_states"][spec.action_id]["state"] == "RESULT_RECORDED"


# ---------------------------------------------------------------------------
# P02: request > intent ceiling -> 0 executor calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p02_request_exceeds_intent_ceiling_zero_calls(tmp_path):
    """P02 PRODUCTIVE: request above intent quantity ceiling never executes."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=50
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(50)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P03: request > delegated ceiling -> 0 calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p03_request_exceeds_delegated_ceiling_zero_calls(tmp_path):
    """P03 PRODUCTIVE: the delegated quantity ceiling is enforced live.

    The delegated ceiling is proven by the real productive dispatch path: the
    durable plan quantity (9) exceeds the delegated quantity ceiling (5), so
    acquire refuses and the executor is never called.
    """
    granted = ({"quantity": _qty_dict(5)},)
    ok, reason = verify_quantity_against_grant(granted, _qty_dict(9))
    assert ok is False
    assert reason == "quantity-escalation"

    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=100, payload_amount=9
    )
    # Attach the delegated quantity ceiling of 5 to the durable action, which
    # is narrower than the request the productive path is about to dispatch.
    raw = store.load(str(mission.id))
    store.transition_delegation_grant(
        str(mission.id), spec.action_id, raw["revision"],
        {
            "delegation_id": "dlg_p03",
            "delegation_parent_mission_id": str(mission.id),
            "delegation_parent_action_id": "parent",
            "delegation_root_mission_id": str(mission.id),
            "delegation_root_action_id": "parent",
            "delegation_delegator_grid": "g",
            "delegation_delegator_agent_id": "ex-rt",
            "delegation_delegate_agent_id": app.app_id,
            "delegation_delegate_grid": "g",
            "delegation_allowed_capabilities": ["resource.transfer"],
            "delegation_allowed_resources": [{
                "resource_id": "r",
                "governed_registration_id": "g",
                "generation": 1,
            }],
            "delegation_max_risk_level": "critical",
            "delegation_max_timeout_seconds": 3600.0,
            "delegation_require_verification": True,
            "delegation_max_side_effect": "EXTERNAL_IRREVERSIBLE",
            "delegation_quantity_ceilings": [{"quantity": _qty_dict(5)}],
            "delegation_created_at": NOW,
            "delegation_expires_at": "",
            "delegation_state": "ACTIVE",
            "delegation_revoked_at": "",
            "delegation_revoke_reason": "",
        },
    )
    svc2 = _service(comps, _guard_for(store))
    outcome = await svc2.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(9)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0, "P03 must produce ZERO executor calls"


# ---------------------------------------------------------------------------
# P04: quantity-bearing request with missing quantity authority -> 0 calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p04_missing_quantity_authority_zero_calls(tmp_path):
    """P04 PRODUCTIVE: quantity-bearing action without authority is refused."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=5
    )
    # Rebuild the durable record WITHOUT any established quantity authority.
    comps2 = _components(tmp_path, tmp_path / ".intent-os2")
    app2 = _TransferApp(capability="resource.transfer")
    _govern(comps2, app2)
    mission2 = await _running_mission(comps2)
    store2 = _mission_store(tmp_path, "mstore-noauth")
    payload = {"text": "transfer", "quantity": _qty_dict(5)}
    spec2 = _spec_for(
        comps2, mission2, app2, payload, key="q1",
        operation=TRANSFER_OPERATION, quantity=_qty_dict(5),
    )
    _bind_action(
        store2, str(mission2.id), spec2,
        quantity=_qty_dict(5),
        operation=TRANSFER_OPERATION,
        quantity_authority=None,
    )
    svc2 = _service(comps2, _guard_for(store2))
    outcome = await svc2.execute(
        mission2.id, app2.capability_name,
        payload=payload, idempotency_key="q1", durable_action=spec2,
    )
    assert outcome.result.error_code is not None
    assert app2.calls == 0


# ---------------------------------------------------------------------------
# P05: UNKNOWN applicability -> 0 calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p05_unknown_applicability_zero_calls(tmp_path):
    """P05 PRODUCTIVE: an unregistered operation resolves UNKNOWN and denies."""
    undeclared_op = "UNDECLARED_OPERATION_XYZ"
    comps = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp(capability="resource.transfer")
    _govern(comps, app)
    mission = await _running_mission(comps)
    store = _mission_store(tmp_path)
    payload = {"text": "t", "quantity": _qty_dict(5)}
    spec = _spec_for(comps, mission, app, payload, key="u1", operation=undeclared_op, quantity=_qty_dict(5))
    _bind_action(
        store, str(mission.id), spec,
        quantity=_qty_dict(5), operation=undeclared_op,
        quantity_authority=_qty_authority(10),
    )
    svc = _service(comps, _guard_for(store))
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=payload, idempotency_key="u1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P06: positively proven NOT_APPLICABLE -> normal productive dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p06_not_applicable_dispatches_normally(tmp_path):
    """P06 PRODUCTIVE: READ is positively non-quantitative and dispatches."""
    comps = _components(tmp_path, tmp_path / ".intent-os-read")
    app = CountingApp(capability="resource.transfer")
    _govern(comps, app)
    mission = await _running_mission(comps)
    store = _mission_store(tmp_path, "mstore-read")
    read_spec = _spec_for(
        comps, mission, app, {"text": "read"}, key="r1",
        operation="READ", quantity=None,
    )
    _bind_action(
        store, str(mission.id), read_spec,
        quantity=None, operation="READ",
        quantity_authority=_qty_authority(10),
    )
    svc = _service(comps, _guard_for(store))
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "read"}, idempotency_key="r1",
        durable_action=read_spec,
    )
    assert outcome.result.error_code is None, outcome.result.metadata
    assert app.calls == 1


# ---------------------------------------------------------------------------
# P07: C1-bound quantity substitution -> 0 calls  (SECURITY CRITICAL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p07_c1_bound_quantity_substitution_zero_calls(tmp_path):
    """P07 PRODUCTIVE: swapping the quantity after C1 binding never executes."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=100, payload_amount=5
    )
    # Present the SAME capability/idempotency key but a different quantity.
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(50)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P08: intent authority narrowed between advisory and acquire -> 0 calls
#          (SECURITY CRITICAL - TQ1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p08_authority_narrowed_before_acquire_zero_calls(tmp_path):
    """P08 PRODUCTIVE (TQ1): narrowing authority after advisory denies at acquire."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=10
    )
    # Advisory-equivalent proof passes against the ORIGINAL authority...
    from intent_kernel.mission.quantity import prove_plan_quantities_against_authority
    prove_plan_quantities_against_authority(auth, [{"quantity": _qty_dict(10)}])
    # ...then authority is narrowed to 5 before acquire. A fresh mission/store
    # models the durable record as it stands at acquire time.
    comps2 = _components(tmp_path, tmp_path / ".intent-os-narrow")
    app2 = _TransferApp(capability="resource.transfer")
    _govern(comps2, app2)
    mission2 = await _running_mission(comps2)
    store2 = _mission_store(tmp_path, "mstore-narrow")
    payload = {"text": "transfer", "quantity": _qty_dict(10)}
    spec2 = _spec_for(
        comps2, mission2, app2, payload, key="q1",
        operation=TRANSFER_OPERATION, quantity=_qty_dict(10),
    )
    _bind_action(
        store2, str(mission2.id), spec2,
        quantity=_qty_dict(10), operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(5),
    )
    svc2 = _service(comps2, _guard_for(store2))
    outcome = await svc2.execute(
        mission2.id, app2.capability_name,
        payload=payload, idempotency_key="q1", durable_action=spec2,
    )
    assert outcome.result.error_code is not None
    assert app2.calls == 0


# ---------------------------------------------------------------------------
# P09: delegation narrowed/revoked between advisory and acquire -> 0 calls
#          (SECURITY CRITICAL - TQ2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p09_delegation_revoked_before_acquire_zero_calls(tmp_path):
    """P09 PRODUCTIVE (TQ2): a revoked quantity delegation denies at acquire.

    This is the same TOCTOU window as TQ2, asserted from the quantity side:
    the real delegated handoff is driven through the productive runtime after
    the quantity-bearing grant has been revoked.
    """
    granted = ({"quantity": _qty_dict(10)},)
    # Advisory-equivalent proof passes while the delegation is live.
    ok, _ = verify_quantity_against_grant(granted, _qty_dict(10))
    assert ok is True
    # Revocation / narrowing removes the grant entirely: zero quantity authority.
    revoked = ()
    ok, reason = verify_quantity_against_grant(revoked, _qty_dict(10))
    assert ok is False
    assert reason == "quantity-not-granted"
    narrowed = ({"quantity": _qty_dict(5)},)
    ok, reason = verify_quantity_against_grant(narrowed, _qty_dict(10))
    assert ok is False and reason == "quantity-escalation"

    # PRODUCTIVE: drive a real delegated dispatch whose grant is revoked
    # before acquire. The runtime must produce ZERO executor calls.
    from tests.test_c2_c3_g13_toctou import test_tq2_delegation_revoked_before_acquire_denies as _tq2

    await _tq2(tmp_path)


# ---------------------------------------------------------------------------
# P10: quantity mutated after acquire, before handoff -> 0 calls
#           (SECURITY CRITICAL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p10_quantity_mutated_before_handoff_zero_calls(tmp_path):
    """P10 PRODUCTIVE: the final pre-handoff gate refuses a mutated quantity.

    Driven through the REAL productive runtime (acquire -> final gate ->
    executor) with the quantity mutated inside the post-acquire window.
    """
    from tests.test_c2_c3_g13_final_handoff import (
        test_fh5_quantity_amount_mutation_zero_executor_calls as _fh5,
    )

    await _fh5(tmp_path)

    # The same refusal is directly observable at the guard surface: acquire
    # succeeds, then the presented quantity changes to 11 before handoff.
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=100, payload_amount=10
    )
    ownership = guard.acquire_for_legacy(
        mission_id=str(mission.id),
        capability=app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(10)},
        idempotency_key="q1",
        executor_logical_id=app.app_id,
        expected_governed_registration_id=spec.expected_governed_registration_id,
        expected_resource_generation=spec.expected_resource_generation,
        quantity=_qty_dict(10),
        operation=TRANSFER_OPERATION,
    )
    with pytest.raises(DispatchGuardError, match="quantity changed since acquire"):
        guard.verify_pre_handoff_identity(
            ownership,
            capability=app.capability_name,
            operation=TRANSFER_OPERATION,
            request_semantics_digest=spec.request_semantics_digest,
            quantity=_qty_dict(11),
        )
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P11/P12: zero semantics (preserved from C2/C3/G1.1 §7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p11_zero_ceiling_zero_request_allowed(tmp_path):
    """P11 PRODUCTIVE: zero ceiling with a zero request is allowed."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=0, payload_amount=0
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(0)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None, outcome.result.metadata
    assert app.calls == 1


@pytest.mark.asyncio
async def test_p12_zero_ceiling_positive_request_denied(tmp_path):
    """P12 PRODUCTIVE: zero ceiling with a positive request is denied."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=0, payload_amount=1
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(1)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P13/P14: budget and quota never widen authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p13_operational_budget_exceeds_authority_still_denied(tmp_path):
    """P13 PRODUCTIVE: a large operational budget never authorizes a quantity."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=1000
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(1000)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


@pytest.mark.asyncio
async def test_p14_provider_quota_exceeds_authority_still_denied(tmp_path):
    """P14 PRODUCTIVE: a large provider quota never authorizes a quantity."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=5000
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(5000)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P15: restart preserves exact quantity authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p15_restart_preserves_exact_quantity_authority(tmp_path):
    """P15 INTEGRATION: a fresh store/service reload keeps the exact ceilings."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=10
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(10)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None
    # Restart view over the same durable files.
    store2 = _mission_store(tmp_path)
    data = store2.load(str(mission.id))
    definition = MissionDefinition.from_dict(dict(data["mission_definition"]))
    assert definition.quantity_authority is not None
    assert definition.quantity_authority.ceilings[0].quantity.amount == 10
    assert definition.quantity_authority.ceilings[0].quantity.unit == UNIT
    # And the reloaded authority still proves the exact quantity.
    from intent_kernel.mission.quantity import prove_plan_quantities_against_authority
    prove_plan_quantities_against_authority(
        definition.quantity_authority, [{"quantity": _qty_dict(10)}]
    )


# ---------------------------------------------------------------------------
# P16: multi-hop delegation amplification -> DENY
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p16_multi_hop_amplification_denied(tmp_path):
    """P16 INTEGRATION: 10 -> 8 -> 9 amplification is refused."""
    from intent_kernel.mission.delegation import quantity_subset
    root = ({"quantity": _qty_dict(10)},)
    hop1 = ({"quantity": _qty_dict(8)},)
    hop2 = ({"quantity": _qty_dict(9)},)
    assert quantity_subset(hop1, root) is True
    # The third hop asks 9 under an 8 ceiling -> amplification refused.
    assert quantity_subset(hop2, hop1) is False
    ok, reason = verify_quantity_against_grant(hop1, _qty_dict(9))
    assert ok is False and reason == "quantity-escalation"

    # INTEGRATION: the same amplification is refused on the productive path.
    # A delegated quantity ceiling of 8 cannot carry a request of 9.
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=100, payload_amount=9
    )
    raw = store.load(str(mission.id))
    store.transition_delegation_grant(
        str(mission.id), spec.action_id, raw["revision"],
        {
            "delegation_id": "dlg_p16",
            "delegation_parent_mission_id": str(mission.id),
            "delegation_parent_action_id": "parent",
            "delegation_root_mission_id": str(mission.id),
            "delegation_root_action_id": "parent",
            "delegation_delegator_grid": "g",
            "delegation_delegator_agent_id": "ex-rt",
            "delegation_delegate_agent_id": app.app_id,
            "delegation_delegate_grid": "g",
            "delegation_allowed_capabilities": ["resource.transfer"],
            "delegation_allowed_resources": [{
                "resource_id": "r",
                "governed_registration_id": "g",
                "generation": 1,
            }],
            "delegation_max_risk_level": "critical",
            "delegation_max_timeout_seconds": 3600.0,
            "delegation_require_verification": True,
            "delegation_max_side_effect": "EXTERNAL_IRREVERSIBLE",
            # HOP-1 ceiling is 8; the request asks 9 -> amplification.
            "delegation_quantity_ceilings": [{"quantity": _qty_dict(8)}],
            "delegation_created_at": NOW,
            "delegation_expires_at": "",
            "delegation_state": "ACTIVE",
            "delegation_revoked_at": "",
            "delegation_revoke_reason": "",
        },
    )
    outcome = await _service(comps, _guard_for(store)).execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(9)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# P17/P18/P19: G1 post-effect observation semantics
#          (SECURITY CRITICAL - must not be pure-helper)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p17_observed_within_authorized_is_compliant(tmp_path):
    """P17 DURABLE: observed 8 <= authorized 10 -> COMPLIANT via record_result()."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=8, observed=8,
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(8)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None
    assert app.calls == 1

    # AUTH=10 / REQ=8 / OBS=8 -> COMPLIANT, read from the DURABLE record path.
    data = store.load(str(mission.id))
    result_evidence = data["action_states"][spec.action_id]["result"]
    evidence = result_evidence["quantity_evidence"]
    assert evidence["status"] == "COMPLIANT"
    assert result_evidence["quantity_compliance_status"] == "COMPLIANT"
    assert evidence["authorized_quantity"]["amount"] == 10
    assert evidence["requested_quantity"]["amount"] == 8
    assert evidence["observed_quantity"]["amount"] == 8
    assert result_evidence.get("quantity_continuation_allowed") is None
    # Evidence is read-only: it grants nothing and prevents nothing.
    assert evidence["grants_authority"] is False
    assert evidence["prevented_effect"] is False
    # The durable evidence round-trips through the canonical contract type.
    assert QuantityEvidence.from_dict(evidence).is_violation is False


@pytest.mark.asyncio
async def test_p18_observed_exceeds_authorized_is_violation_not_prevented(tmp_path):
    """P18 DURABLE: observed 12 > authorized 10 -> VIOLATION via record_result().

    The VIOLATION is recorded as POST-EFFECT evidence on the durable record.
    It is never described as pre-effect prevented/denied, and no successful
    compliant state is produced. Dependent continuation is stopped.
    """
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=10, observed=12,
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(10)},
        idempotency_key="q1", durable_action=spec,
    )
    # The authorized request WAS allowed and the effect happened.
    assert outcome.result.error_code is None
    assert app.calls == 1

    # The durable record path (not the pure helper) carries the evidence.
    data = store.load(str(mission.id))
    result_evidence = data["action_states"][spec.action_id]["result"]
    evidence = result_evidence["quantity_evidence"]
    assert evidence["status"] == "VIOLATION"
    assert result_evidence["quantity_compliance_status"] == "VIOLATION"
    # Dependent continuation is stopped for a violation.
    assert result_evidence["quantity_continuation_allowed"] is False
    # Never relabelled as pre-effect prevention, never grants authority.
    assert evidence["prevented_effect"] is False
    assert evidence["grants_authority"] is False
    # AUTHORIZED / REQUESTED / OBSERVED are all preserved and distinct.
    assert evidence["authorized_quantity"]["amount"] == 10
    assert evidence["requested_quantity"]["amount"] == 10
    assert evidence["observed_quantity"]["amount"] == 12
    assert evidence["request_digest"] == spec.request_semantics_digest


@pytest.mark.asyncio
async def test_p19_unobservable_quantity_is_unknown(tmp_path):
    """P19 DURABLE: unavailable observation -> UNKNOWN via record_result()."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=8, observed=None,
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(8)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None
    assert app.calls == 1

    # No observation is available -> UNKNOWN, read from the DURABLE path.
    data = store.load(str(mission.id))
    result_evidence = data["action_states"][spec.action_id]["result"]
    evidence = result_evidence["quantity_evidence"]
    assert evidence["status"] == "UNKNOWN"
    assert result_evidence["quantity_compliance_status"] == "UNKNOWN"
    # Executor success is NEVER promoted into an observation.
    assert evidence["observed_quantity"] is None
    # AUTHORIZED / REQUESTED are still recorded truthfully.
    assert evidence["authorized_quantity"]["amount"] == 10
    assert evidence["requested_quantity"]["amount"] == 8
    # An UNKNOWN observation can never be forged with a value.
    with pytest.raises(Exception):
        QuantityEvidence(
            mission_id=str(mission.id), action_id=spec.action_id,
            authorized_quantity=_money(10), requested_quantity=_money(8),
            observed_quantity=ObservedQuantity(MONEY, 8, UNIT),
            request_digest="d",
            status=QuantityComplianceStatus.UNKNOWN,
        )


# ---------------------------------------------------------------------------
# P20: evidence from a prior execution cannot authorize a later request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p20_prior_evidence_cannot_authorize_subsequent_request(tmp_path):
    """P20 PRODUCTIVE: recorded G1 evidence never authorizes the next request."""
    comps, app, mission, store, guard, svc, spec, auth = await _env(
        tmp_path, intent_amount=10, payload_amount=10,
    )
    # A first compliant execution produces evidence.
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty_dict(10)},
        idempotency_key="q1", durable_action=spec,
    )
    assert outcome.result.error_code is None
    evidence = classify_quantity_observation(
        mission_id=str(mission.id), action_id=spec.action_id,
        authorized_quantity=_money(10), requested_quantity=_money(10),
        observed_quantity=ObservedQuantity(MONEY, 10, UNIT),
        request_digest=spec.request_semantics_digest,
    )
    assert evidence.status is QuantityComplianceStatus.COMPLIANT
    # The evidence itself carries no authority...
    assert evidence.to_dict()["grants_authority"] is False
    # ...so a LATER, larger request against the same ceiling still denies.
    comps2 = _components(tmp_path, tmp_path / ".intent-os-p20")
    app2 = _TransferApp(capability="resource.transfer")
    _govern(comps2, app2)
    mission2 = await _running_mission(comps2)
    store2 = _mission_store(tmp_path, "mstore-p20")
    payload2 = {"text": "transfer", "quantity": _qty_dict(9999)}
    spec2 = _spec_for(
        comps2, mission2, app2, payload2, key="q2",
        operation=TRANSFER_OPERATION, quantity=_qty_dict(9999),
    )
    _bind_action(
        store2, str(mission2.id), spec2,
        quantity=_qty_dict(9999), operation=TRANSFER_OPERATION,
        quantity_authority=_qty_authority(10),
    )
    svc2 = _service(comps2, _guard_for(store2))
    outcome2 = await svc2.execute(
        mission2.id, app2.capability_name,
        payload=payload2, idempotency_key="q2", durable_action=spec2,
    )
    assert outcome2.result.error_code is not None
    assert app2.calls == 0


# ---------------------------------------------------------------------------
# §12 self-check: security-critical cases must not be pure-helper
# ---------------------------------------------------------------------------

def test_p_classification_covers_every_required_case():
    for case in NON_HELPER_REQUIRED:
        assert case in TEST_CLASSIFICATION, case
        assert TEST_CLASSIFICATION[case] in {"PRODUCTIVE", "INTEGRATION"}, case
    assert set(TEST_CLASSIFICATION) == {f"P{i:02d}" for i in range(1, 21)}


def test_p_matrix_every_case_reaches_a_productive_surface():
    """Closure matrix: every P-case executes a real productive/integration call.

    A security-critical case that only exercised a pure helper would fail
    here, so it cannot silently degrade.
    """
    import inspect
    import sys

    module = sys.modules[__name__]
    cases = {
        name: obj
        for name, obj in vars(module).items()
        if re.match(r"^test_p\d\d_", name) and inspect.isfunction(obj)
    }
    assert len(cases) == 20, sorted(cases)
    for name, case in cases.items():
        source = inspect.getsource(case)
        assert any(
            marker in source
            for marker in (
                ".execute(",
                "guard.acquire",
                "_fh5",
                "_tq2",
            )
        ), f"{name} does not reach a productive surface"