"""C2/C3/G1.3 GAP 2 — final pre-handoff live contract revalidation (FH1–FH7).

Every test runs the REAL productive runtime:

    MissionRuntime.run_mission -> acquire -> FINAL GATE -> executor

The mutation is injected exactly in the TOCTOU window: after a SUCCESSFUL
acquire, before the final gate re-derives the live handoff identity. A real
``ProductiveDispatchGuard`` wrapper performs the mutation in that window, so
the test observes the true production gate, not a simulated one.

Required invariant immediately before executor handoff:

    ACQUIRED_CAPABILITY == LIVE_HANDOFF_CAPABILITY
    ACQUIRED_OPERATION == LIVE_HANDOFF_OPERATION
    ACQUIRED_REQUEST_DIGEST == LIVE_HANDOFF_REQUEST_DIGEST
    ACQUIRED_QUANTITY == LIVE_HANDOFF_QUANTITY

Any mutation of capability, operation, payload, idempotency key, quantity
dimension, quantity amount or quantity unit must produce
DENY / REFUSE HANDOFF with ZERO executor calls.
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

# Reuse the canonical lifecycle harness (real runtime wiring, real store,
# real ProductiveDispatchGuard, counting executor).
from tests.test_m32c_r2_lifecycle_proof import (  # noqa: F401
    CountingApp,
    _AllowConstitution,
    _components,
    _CountingExecutor,
    _govern,
    _guard_for,
    _mission_store,
    _started_mission,
)
from intent_kernel.mission import (
    ActionState,
    DurableActionState,
    MissionActionAuthority,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
    ProductiveDispatchGuard,
    spec_for_runtime_node,
)
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import ActionContract, RuntimeNode

NOW = "2026-10-05T00:00:00+00:00"
MONEY = QuantityDimension.MONETARY_AMOUNT
UNIT = "BRL_CENT"

#: A quantity-bearing operation registered with an exact supported dimension.
TRANSFER_OPERATION = "TRANSFER_FUNDS"
DEFAULT_QUANTITY_APPLICABILITY.declare(TRANSFER_OPERATION, MONEY)


def _qty(amount: int, unit: str = UNIT, dimension: str = MONEY.value) -> dict:
    return {"dimension": dimension, "amount": amount, "unit": unit}


def _qty_authority(amount: int = 10):
    return establish_quantity_authority(
        ceilings=(QuantityCeiling(Quantity(MONEY, amount, UNIT)),),
        source_type="user_explicit",
        source_identity="c2c3g13_fh",
        established_at=NOW,
    )


class _MutatingGuard(ProductiveDispatchGuard):
    """Real guard that mutates the LIVE node contract after acquire wins.

    This models the exact TOCTOU window: acquire succeeds against durable
    authority, then the in-memory handoff contract changes before the gate.
    No authority is added or removed — only the live request is mutated.
    """

    def __init__(self, authority, store, node, mutate):
        super().__init__(authority, store)
        self._node = node
        self._mutate = mutate
        self.acquired = False

    def acquire(self, spec, **kwargs):
        ownership = super().acquire(spec, **kwargs)
        self.acquired = True
        # The window opens here: ownership is won, effect has NOT occurred.
        self._mutate(self._node)
        return ownership


def _runtime_with(store, components, guard):
    return MissionRuntime(
        executor=_CountingExecutor(),
        constitution=_AllowConstitution(),
        dispatch_guard=guard,
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )


def _quantity_node(quantity: dict):
    """A runtime node whose contract carries a C1-bound quantity."""
    contract = ActionContract(
        action_id="n1",
        capability="c.rt",
        action_type=TRANSFER_OPERATION,
        idempotency_key="rk1",
    )
    contract.inputs_reference = {"text": "transfer", "quantity": dict(quantity)}
    # spec_for_runtime_node reads contract.quantity (canonical live field).
    contract.quantity = dict(quantity)
    return RuntimeNode(
        node_id="n1",
        capability="c.rt",
        agent_id="ex-rt",
        action_contract=contract,
    )


def _bind(store, mid, node, quantity: dict):
    """Bind the node's real identity (digest + operation + quantity) durably."""
    spec = spec_for_runtime_node(mid, node)
    ident = store.get_continuity_identity()
    definition = MissionDefinition(
        objective="productive",
        context={"k": "v"},
        quantity_authority=_qty_authority(10),
    )
    probe = MissionRecord(
        mission_id="probe",
        installation_id=ident,
        mission_definition=definition,
    )
    record = MissionRecord(
        mission_id=mid,
        installation_id=ident,
        revision=1,
        runtime_id="rt-1",
        mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=({
            "action_id": spec.action_id,
            "capability": node.capability,
            "node_id": node.node_id,
            "dependencies": [],
            "request_semantics_digest": spec.request_semantics_digest,
            "operation": spec.operation,
            "quantity": dict(quantity),
        },),
        action_states={spec.action_id: DurableActionState(
            action_id=spec.action_id,
            node_id=node.node_id,
            state=ActionState.PENDING,
            expected_resource_id="r",
            expected_governed_registration_id="",
            expected_resource_generation=0,
            expected_executor_kind="core_app",
            expected_executor_logical_id=spec.executor_logical_id,
        )},
    )
    assert store.create(record).outcome == "committed"
    return spec


async def _fh_env(tmp_path, mutate, *, root="fh", quantity=None):
    """Full productive runtime with a post-acquire mutation installed."""
    quantity = quantity or _qty(5)
    components = _components(tmp_path, tmp_path / f".intent-os-{root}")
    app = CountingApp(capability="c.rt")
    _govern(components, app)
    mission = await _started_mission(components, root)
    store = _mission_store(tmp_path, f"mstore-{root}")
    node = _quantity_node(quantity)
    _bind(store, str(mission.id), node, quantity)
    guard = _MutatingGuard(
        MissionActionAuthority(store), store, node, mutate
    )
    rt = _runtime_with(store, components, guard)
    # The instance shares the SAME live node object the guard mutates.
    inst = rt.create_instance(str(mission.id), "g1", [node])
    await rt.run_mission(inst.runtime_id)
    return rt, guard, store, node


# ---------------------------------------------------------------------------
# FH1: capability mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh1_capability_mutation_zero_executor_calls(tmp_path):
    """FH1: ACQUIRED_CAPABILITY != LIVE_HANDOFF_CAPABILITY -> 0 executor calls."""

    def mutate(node):
        node.capability = "c.attacker"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh1")
    assert guard.acquired is True, "mutation must land in the post-acquire window"
    assert rt.executor.calls == 0
    assert node.capability == "c.attacker"


# ---------------------------------------------------------------------------
# FH2: operation mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh2_operation_mutation_zero_executor_calls(tmp_path):
    """FH2: ACQUIRED_OPERATION != LIVE_HANDOFF_OPERATION -> 0 executor calls."""

    def mutate(node):
        node.action_contract.action_type = "SOME_OTHER_OPERATION"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh2")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.action_type == "SOME_OTHER_OPERATION"


# ---------------------------------------------------------------------------
# FH3: payload mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh3_payload_mutation_zero_executor_calls(tmp_path):
    """FH3: ACQUIRED_REQUEST_DIGEST != LIVE_HANDOFF_REQUEST_DIGEST -> 0 calls."""

    def mutate(node):
        node.action_contract.inputs_reference["text"] = "attacker-payload"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh3")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.inputs_reference["text"] == "attacker-payload"


# ---------------------------------------------------------------------------
# FH4: idempotency key mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh4_idempotency_mutation_zero_executor_calls(tmp_path):
    """FH4: a changed idempotency key changes the C1 digest -> 0 executor calls."""

    def mutate(node):
        node.action_contract.idempotency_key = "rk-attacker"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh4")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.idempotency_key == "rk-attacker"


# ---------------------------------------------------------------------------
# FH5: quantity AMOUNT mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh5_quantity_amount_mutation_zero_executor_calls(tmp_path):
    """FH5: ACQUIRED_QUANTITY != LIVE_HANDOFF_QUANTITY (amount) -> 0 calls."""

    def mutate(node):
        node.action_contract.quantity["amount"] = 9999

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh5")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.quantity["amount"] == 9999


# ---------------------------------------------------------------------------
# FH6: quantity UNIT mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh6_quantity_unit_mutation_zero_executor_calls(tmp_path):
    """FH6: quantity unit mutation -> 0 executor calls (no unit equivalence)."""

    def mutate(node):
        node.action_contract.quantity["unit"] = "USD_CENT"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh6")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.quantity["unit"] == "USD_CENT"


# ---------------------------------------------------------------------------
# FH7: quantity DIMENSION mutation after acquire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh7_quantity_dimension_mutation_zero_executor_calls(tmp_path):
    """FH7: quantity dimension mutation -> 0 executor calls."""

    def mutate(node):
        node.action_contract.quantity["dimension"] = "data_volume"

    rt, guard, store, node = await _fh_env(tmp_path, mutate, root="fh7")
    assert guard.acquired is True
    assert rt.executor.calls == 0
    assert node.action_contract.quantity["dimension"] == "data_volume"


# ---------------------------------------------------------------------------
# Control: with NO mutation the same harness dispatches exactly once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fh_control_no_mutation_dispatches_once(tmp_path):
    """Control: the FH harness really dispatches when nothing is mutated.

    Without this, a gate that refused EVERY handoff would also make FH1–FH7
    "pass". The control proves the gate distinguishes mutation from integrity.
    """

    def no_mutation(_node):
        return None

    rt, guard, store, node = await _fh_env(tmp_path, no_mutation, root="fhctl")
    assert guard.acquired is True
    assert rt.executor.calls == 1