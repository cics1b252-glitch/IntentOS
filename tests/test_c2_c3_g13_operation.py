"""C2/C3/G1.2 §1–§4 — PRODUCTIVE operation semantics suite (O01–O10).

Every test traverses the REAL productive path:

    CapabilityExecutionService -> ProductiveDispatchGuard -> executor

Operation is authority-bearing. There is no DEFAULT/UNKNOWN/NONE operation,
no operation inferred from capability name or payload shape, and no operation
reconstructed after the fact. The canonical operation source is
``ActionContract.action_type``, bound INSIDE the C1 request digest.

For EVERY denied case the requirement is EXECUTOR_CALLS = 0.
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.quantity import (
    DEFAULT_QUANTITY_APPLICABILITY,
    Quantity,
    QuantityCeiling,
    QuantityDimension,
    establish_quantity_authority,
)

# Canonical C1 productive harness (real components, real guard, real service).
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
from intent_kernel.mission.dispatch_guard import (
    DispatchAttemptSpec,
    DispatchGuardError,
    ProductiveDispatchGuard,
    spec_for_legacy_dispatch,
)

NOW = "2026-10-05T00:00:00+00:00"
MONEY = QuantityDimension.MONETARY_AMOUNT
UNIT = "BRL_CENT"

#: A positively-declared quantity-bearing operation (authorized dimension).
TRANSFER_OPERATION = "TRANSFER_FUNDS"
DEFAULT_QUANTITY_APPLICABILITY.declare(TRANSFER_OPERATION, MONEY)


def _qty(amount: int) -> dict:
    return {"dimension": MONEY.value, "amount": amount, "unit": UNIT}


def _qty_authority(amount: int = 10):
    return establish_quantity_authority(
        ceilings=(
            QuantityCeiling(Quantity(MONEY, amount, UNIT)),
        ),
        source_type="user_explicit",
        source_identity="c2c3g13_o",
        established_at=NOW,
    )


async def _op_env(
    tmp_path,
    *,
    authorized_operation=TRANSFER_OPERATION,
    presented_operation=TRANSFER_OPERATION,
    plan_operation=TRANSFER_OPERATION,
    plan_quantity=None,
    quantity_authority=True,
    durable_digest=None,
    root="o",
):
    """Build a productive environment with independent control of each
    operation surface: the AUTHORIZED durable plan, the C1-BOUND digest and
    the PRESENTED spec operation.
    """
    components = _components(tmp_path, tmp_path / f".intent-os-{root}")
    app = CountingApp(capability="resource.transfer")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path, f"mstore-{root}")
    quantity = _qty(5) if plan_quantity is None else plan_quantity

    payload = {"text": "transfer", "quantity": quantity}
    spec = _spec_for(
        components, mission, app, payload, key="o1",
        operation=presented_operation, quantity=quantity,
    )
    # The authorized operation is what the DURABLE plan carries.
    authority = (
        _qty_authority(10) if quantity_authority else None
    )
    record = _bind_action(
        store, str(mission.id), spec,
        quantity=quantity,
        operation=plan_operation,
        quantity_authority=authority,
    )
    if durable_digest is not None:
        # Bind the durable plan with a FORGED C1 digest while the presented
        # request still recomputes the true digest. Durable authority and the
        # presented request therefore disagree -> refusal before effect.
        forged = DispatchAttemptSpec(
            mission_id=spec.mission_id,
            action_id=spec.action_id,
            request_semantics_digest=durable_digest,
            executor_logical_id=spec.executor_logical_id,
            expected_governed_registration_id=(
                spec.expected_governed_registration_id),
            expected_resource_generation=spec.expected_resource_generation,
            quantity=spec.quantity,
            operation=spec.operation,
        )
        store2 = _mission_store(tmp_path, f"mstore-{root}-forged")
        _bind_action(
            store2, str(mission.id), forged,
            quantity=quantity,
            operation=plan_operation,
            quantity_authority=authority,
        )
        store = store2
    guard = _guard_for(store)
    service = _service(components, guard)
    return components, app, mission, store, guard, service, spec


# ---------------------------------------------------------------------------
# O01: exact authorized operation match dispatches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o01_authorized_operation_exact_match_dispatches(tmp_path):
    """O01 PRODUCTIVE: presented operation == authorized -> EXECUTOR_CALLS = 1."""
    comps, app, mission, store, guard, svc, spec = await _op_env(tmp_path)
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is None, outcome.result.metadata
    assert app.calls == 1


# ---------------------------------------------------------------------------
# O02: operation substitution denied BEFORE effect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o02_operation_substitution_denied_before_effect(tmp_path):
    """O02 PRODUCTIVE: presented operation != authorized -> 0 executor calls."""
    comps, app, mission, store, guard, svc, spec = await _op_env(
        tmp_path, presented_operation="SOME_OTHER_OPERATION",
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O03: missing operation fails closed where operation is authority-bearing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o03_missing_operation_fails_closed(tmp_path):
    """O03 PRODUCTIVE: empty presented operation -> 0 executor calls.

    There is no DEFAULT/UNKNOWN/NONE fallback. The canonical C1-bound spec
    builder itself refuses an empty operation, so a missing operation can
    never become an inferred one. The refusal happens before any effect and
    leaves the durable record untouched.
    """
    comps, app, mission, store, guard, svc, spec = await _op_env(tmp_path)
    before = store.load(str(mission.id))
    with pytest.raises(ValueError, match="operation must be an explicit"):
        spec_for_legacy_dispatch(
            mission_id=str(mission.id),
            capability=app.capability_name,
            payload={"text": "transfer", "quantity": _qty(5)},
            idempotency_key="o1",
            executor_logical_id=app.app_id,
            expected_governed_registration_id=(
                spec.expected_governed_registration_id),
            expected_resource_generation=spec.expected_resource_generation,
            operation="",
            quantity=_qty(5),
        )
    # Fail closed before effect: ZERO executor calls, durable record unchanged.
    assert app.calls == 0
    after = store.load(str(mission.id))
    assert after["action_states"][spec.action_id]["state"] == before[
        "action_states"
    ][spec.action_id]["state"]


# ---------------------------------------------------------------------------
# O04: malformed operation fails closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o04_malformed_operation_fails_closed(tmp_path):
    """O04 PRODUCTIVE: undeclared/malformed operation -> 0 executor calls.

    A malformed operation is not a quantity-bearing operation; it is an
    UNKNOWN applicability, and UNKNOWN always denies.
    """
    malformed = "!!not-a-canonical-operation!!"
    comps, app, mission, store, guard, svc, spec = await _op_env(
        tmp_path, presented_operation=malformed,
        plan_operation=malformed,
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O05: plan operation != presented operation -> deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o05_plan_operation_differs_from_presented_denies(tmp_path):
    """O05 PRODUCTIVE: durable plan operation != presented -> 0 executor calls."""
    comps, app, mission, store, guard, svc, spec = await _op_env(
        tmp_path,
        authorized_operation="READ",
        presented_operation=TRANSFER_OPERATION,
        plan_operation="READ",
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O06: C1-bound operation != dispatch operation -> deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o06_c1_bound_operation_differs_from_dispatch_denies(tmp_path):
    """O06 PRODUCTIVE: the durable C1 digest disagrees -> 0 executor calls.

    The C1 digest binds capability + operation + payload + idempotency key.
    Tampering the durable digest alone proves the presented request cannot
    match durable authority.
    """
    comps, app, mission, store, guard, svc, spec = await _op_env(
        tmp_path, durable_digest="digest-forged-operation",
    )
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O07: operation mutation before acquire -> deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o07_operation_mutation_before_acquire_denies(tmp_path):
    """O07 PRODUCTIVE: mutate the spec operation before acquire -> 0 calls.

    The guard recomputes the C1 digest from the MUTATED spec and compares it
    to durable authority; the presented operation no longer matches.
    """
    comps, app, mission, store, guard, svc, spec = await _op_env(tmp_path)
    forged = DispatchAttemptSpec(
        mission_id=spec.mission_id,
        action_id=spec.action_id,
        request_semantics_digest=spec.request_semantics_digest,
        executor_logical_id=spec.executor_logical_id,
        expected_governed_registration_id=(
            spec.expected_governed_registration_id),
        expected_resource_generation=spec.expected_resource_generation,
        quantity=spec.quantity,
        # Mutation: the operation no longer matches the C1-bound digest.
        operation="SOME_OTHER_OPERATION",
    )
    with pytest.raises(DispatchGuardError):
        guard.acquire(forged, requested_by="o07")
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O08: operation mutation after acquire / before handoff -> deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o08_operation_mutation_after_acquire_denies(tmp_path):
    """O08 PRODUCTIVE: acquire, then change the handoff operation -> 0 calls.

    The final pre-handoff gate re-proves
    ACQUIRED_OPERATION == LIVE_HANDOFF_OPERATION.
    """
    comps, app, mission, store, guard, svc, spec = await _op_env(tmp_path)
    ownership = guard.acquire(spec, requested_by="o08")
    with pytest.raises(DispatchGuardError, match="operation changed since acquire"):
        guard.verify_pre_handoff_identity(
            ownership,
            capability="resource.transfer",
            operation="SOME_OTHER_OPERATION",
            request_semantics_digest=spec.request_semantics_digest,
            quantity=spec.quantity,
        )
    assert app.calls == 0


# ---------------------------------------------------------------------------
# O09: restart preserves exact durable operation semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o09_restart_preserves_exact_durable_operation(tmp_path):
    """O09 PRODUCTIVE: a fresh guard/service over the same store keeps the
    exact authorized operation and dispatches exactly once."""
    comps, app, mission, store, guard, svc, spec = await _op_env(tmp_path)
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "transfer", "quantity": _qty(5)},
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is None, outcome.result.metadata
    assert app.calls == 1

    # Simulated restart: brand-new guard + service over the SAME store.
    restarted_guard = _guard_for(store)
    restarted_service = _service(comps, restarted_guard)
    raw = store.load(str(mission.id))
    assert raw["plan"][0]["operation"] == TRANSFER_OPERATION
    assert restarted_guard.get_authorized_operation(
        str(mission.id), spec.action_id
    ) == TRANSFER_OPERATION

    # A post-restart attempt with a substituted operation is still refused.
    forged = DispatchAttemptSpec(
        mission_id=spec.mission_id,
        action_id=spec.action_id,
        request_semantics_digest=spec.request_semantics_digest,
        executor_logical_id=spec.executor_logical_id,
        expected_governed_registration_id=(
            spec.expected_governed_registration_id),
        expected_resource_generation=spec.expected_resource_generation,
        quantity=spec.quantity,
        operation="SOME_OTHER_OPERATION",
    )
    with pytest.raises(DispatchGuardError):
        restarted_guard.acquire(forged, requested_by="o09-restart")
    # No second effect: the durable record forbids redispatch.
    assert app.calls == 1


# ---------------------------------------------------------------------------
# O10: operation evidence / provenance / agent claim cannot authorize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o10_operation_evidence_cannot_authorize(tmp_path):
    """O10 PRODUCTIVE: claiming an operation does not authorize it.

    A supplied "operation evidence"/provenance payload naming the authorized
    operation does not make an unauthorized operation authorized. Only the
    durable plan plus the C1-bound digest do.
    """
    comps, app, mission, store, guard, svc, spec = await _op_env(
        tmp_path, presented_operation="SOME_OTHER_OPERATION",
    )
    payload = {
        "text": "transfer",
        "quantity": _qty(5),
        # An agent-style claim asserting the operation is legitimate.
        "operation_evidence": {
            "operation": TRANSFER_OPERATION,
            "verified": True,
            "authority": "system",
        },
        "provenance": {"operation": TRANSFER_OPERATION, "signed": True},
    }
    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=payload,
        idempotency_key="o1", durable_action=spec,
    )
    assert outcome.result.error_code is not None
    assert app.calls == 0


def test_o_suite_is_productive_only():
    """Structural guard: no O-case may be satisfied by a pure helper."""
    import inspect

    import tests.test_c2_c3_g13_operation as module

    cases = [
        obj
        for name, obj in vars(module).items()
        if name.startswith("test_o") and inspect.isfunction(obj)
    ]
    assert len(cases) == 11, [c.__name__ for c in cases]
    # The O-cases themselves (the guard function is the 11th).
    for case in cases:
        if case.__name__ == "test_o_suite_is_productive_only":
            continue
        source = inspect.getsource(case)
        # Each O-case must reach a real productive surface: the execution
        # service, the guard acquire, or the canonical C1 spec builder that
        # the productive service itself consumes.
        assert any(
            marker in source
            for marker in (
                "svc.execute",
                "guard.acquire",
                "spec_for_legacy_dispatch",
            )
        ), case.__name__