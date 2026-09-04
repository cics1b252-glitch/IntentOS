"""M31.3B-1A — Canonical Freshness & Idempotency Ordering (RA-31.3B-02).

Eliminates stale idempotency-cache replay by validating the current canonical RRM
generation/lineage BEFORE any cache replay:

  resolve -> constitution -> confirmation/input -> revalidation
  -> structural _verify_precondition_identity (STEP_09)
  -> Hc: current RRM freshness (must precede EVERY cache replay)
  -> single idempotency lookup
  -> if cached: replay (only after Hc passed)
  -> Hd: current RRM freshness again on cache MISS only
  -> local dispatch -> cache save -> audit/return

Tests:
1. stale cached SUCCESS is NEVER replayed once generation advanced between
   selection (N) and Hc (N+1) -> CAPABILITY_UNAVAILABLE, get_count == 0.
2. cache-miss race: on MISS, generation advances between Hc (N) and Hd (N+1)
   -> CAPABILITY_UNAVAILABLE, dispatch_count == 0, get_count == 1, save_count == 0.
3. fresh replay still works: cache hit with unchanged RRM -> single replay, get_count == 1.
4. fresh dispatch still works: MISS with unchanged RRM -> dispatch, get_count == 1, save_count == 1.
5. structural ordering: mismatched revalidation FAILS BEFORE cache consult
   (no replay, no dispatch, get_count == 0) even with a stale SUCCESS cached.
6. single lookup: only one idempotency_store.get on the fresh-dispatch path.
7. missing resource -> fail closed, no dispatch.
8. lineage mismatch -> fail closed, no dispatch.
9. generation mismatch -> fail closed, no dispatch.
10. legacy/unversioned resource -> fail closed, no dispatch.
11. unsupported precondition kind (EXPECTED_ABSENCE) -> fail closed, no dispatch.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import MagicMock

from intent_kernel.contracts import Capability, CapabilityResult, EffectType, ErrorCode
from intent_kernel.orchestration.execution import (
    CapabilityExecutionOutcome,
    CapabilityExecutionService,
)
from intent_kernel.orchestration.registry import CapabilityRegistration, ExecutorKind
from intent_kernel.rrm.binding import (
    ExecutionPrecondition,
    PreconditionKind,
    ResourceBindingDecision,
    ResourceBindingRevalidation,
)
from intent_kernel.rrm.generation import GENERATION_INITIAL, LEGACY_UNVERSIONED


# ---------------------------------------------------------------------------
# Deterministic fakes
# ---------------------------------------------------------------------------

class FakeRRM:
    """Controllable read-only RRM observation surface used by Hc / Hd.

    Only Hc / Hd observation APIs are exposed; no mutation methods exist here.
    Tests advance the generation explicitly via advance().
    """

    def __init__(self, grid: str = "reg-1", generation: int = GENERATION_INITIAL):
        self._grid = grid
        self._generation = generation

    def advance(self) -> None:
        self._generation += 1

    def set_snapshot(self, *, grid: str | None = None, generation: int | None = None) -> None:
        if grid is not None:
            self._grid = grid
        if generation is not None:
            self._generation = generation

    def get_capability(self, name: str) -> Any:
        return _snapshot(self._grid, self._generation)

    def get_agent(self, agent_id: str) -> Any:
        return _snapshot(self._grid, self._generation)

    def get_provider(self, provider_id: str) -> Any:
        return _snapshot(self._grid, self._generation)


def _snapshot(grid: str, generation: int) -> Any:
    from types import SimpleNamespace
    return SimpleNamespace(
        governed_registration_id=grid,
        generation=generation,
    )


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self._cache: dict[Any, Any] = {}
        self.get_count = 0
        self.save_count = 0
        self.on_get_hook = None  # optional async callback(key) run during each get

    def seed(self, key: Any, outcome: CapabilityExecutionOutcome) -> None:
        self._cache[key] = outcome

    async def get(self, key: Any) -> Any:
        self.get_count += 1
        if self.on_get_hook is not None:
            await self.on_get_hook(key)
        return self._cache.get(key)

    async def save(self, key: Any, outcome: CapabilityExecutionOutcome) -> None:
        self.save_count += 1
        self._cache[key] = outcome


class FakeRouter:
    def __init__(self) -> None:
        self.dispatch_count = 0

    async def execute_exact(self, mission, registration, payload, context):
        self.dispatch_count += 1
        return CapabilityResult(
            capability=registration.capability.name,
            success=True,
            output="ok",
            confidence=1.0,
            error_code=None,
            metadata={},
        )


class StubAuthority:
    """Deterministic authority. resolve/revalidate return controlled objects.

    ``advance_in_revalidate`` advances FakeRRM generation during revalidate,
    modelling a resource advancing between selection (resolve, captures N) and
    the structural/Hc steps that follow.
    """

    def __init__(self, rrm: FakeRRM, decision: ResourceBindingDecision,
                 revalidation: ResourceBindingRevalidation | None = None,
                 advance_in_revalidate: bool = False) -> None:
        self.rrm = rrm
        self._decision = decision
        self._revalidation = revalidation
        self._advance_in_revalidate = advance_in_revalidate

    async def resolve(self, capability: str, *, preferred_kind=None):
        return self._decision

    async def revalidate(self, decision):
        if self._advance_in_revalidate:
            self.rrm.advance()
        if self._revalidation is not None:
            return self._revalidation
        return ResourceBindingRevalidation(
            capability=decision.capability,
            valid=True,
            binding_registered=True,
            rrm_eligible=True,
            binding_healthy=True,
            reason="dispatch_revalidated",
            binding_identity=decision.binding_identity,
            execution_preconditions=decision.execution_preconditions,
        )


class FakeConstitution:
    def __init__(self, allowed: bool = True) -> None:
        self._allowed = allowed

    async def evaluate(self, action, data=None, context=None):
        from types import SimpleNamespace
        return SimpleNamespace(
            allowed=self._allowed,
            decision=SimpleNamespace(value="allowed"),
            metadata={"audit_id": "audit-1"},
        )


class FakeMissionEngine:
    def __init__(self, mission) -> None:
        self.mission = mission

    async def get(self, mission_id):
        return self.mission


class FakeEventPublisher:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, topic, data, *, correlation_id=None):
        self.events.append((topic, data))


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _make_mission():
    from types import SimpleNamespace
    from intent_kernel.contracts import MissionId, MissionStatus
    return SimpleNamespace(
        id=MissionId("00000000-0000-0000-0000-000000000001"),
        status=MissionStatus.RUNNING,
        objective="test objective",
        context=SimpleNamespace(
            correlation_id="corr-1",
            domain="other",
            session_id="sess-1",
        ),
    )


def _make_capability(effect: EffectType = EffectType.PERSIST) -> Capability:
    return Capability(
        name="test.echo",
        description="Test capability",
        requires_network=False,
        effect=effect,
        requires_confirmation=False,
    )


def _make_registration(capability: Capability) -> CapabilityRegistration:
    return CapabilityRegistration(
        capability=capability,
        executor_kind=ExecutorKind.CORE_APP,
        executor_id="app-1",
        executor=MagicMock(health=None),
    )


def _make_precondition(
    resource_id: str = "test.echo",
    grid: str = "reg-1",
    gen: int = GENERATION_INITIAL,
    kind: PreconditionKind = PreconditionKind.EXISTING_RESOURCE,
) -> ExecutionPrecondition:
    return ExecutionPrecondition(
        kind=kind,
        resource_id=resource_id,
        governed_registration_id=grid if kind is PreconditionKind.EXISTING_RESOURCE else "",
        expected_generation=gen if kind is PreconditionKind.EXISTING_RESOURCE else LEGACY_UNVERSIONED,
    )


def _make_decision(
    capability: Capability,
    registration: CapabilityRegistration,
    precondition: ExecutionPrecondition,
) -> ResourceBindingDecision:
    return ResourceBindingDecision(
        capability=capability.name,
        registration=registration,
        available=True,
        reason="eligible",
        registered=True,
        rrm_eligible=True,
        binding_healthy=True,
        selected_binding="core_app:app-1",
        binding_identity=registration.binding_identity,
        execution_preconditions=(precondition,),
    )


def _make_service(
    *,
    rrm: FakeRRM,
    decision: ResourceBindingDecision,
    revalidation: ResourceBindingRevalidation | None = None,
    advance_in_revalidate: bool = False,
    idempotency_store: FakeIdempotencyStore | None = None,
    router: FakeRouter | None = None,
    constitution_allowed: bool = True,
):
    mission = _make_mission()
    registration = decision.registration
    authority = StubAuthority(
        rrm, decision, revalidation=revalidation,
        advance_in_revalidate=advance_in_revalidate,
    )
    service = CapabilityExecutionService(
        mission_engine=FakeMissionEngine(mission),
        constitution=FakeConstitution(allowed=constitution_allowed),
        capability_router=router or FakeRouter(),
        registry=MagicMock(),
        agent_orchestrator=MagicMock(),
        provider_manager=MagicMock(),
        knowledge_pipeline=MagicMock(),
        event_publisher=FakeEventPublisher(),
        idempotency_store=idempotency_store or FakeIdempotencyStore(),
        resource_authority=authority,
    )
    return service, mission, idempotency_store or service.idempotency_store


def _cache_key(mission, capability: str, idempotency_key: str):
    return (str(mission.id), capability, idempotency_key)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1: stale replay eliminated by Hc
# ---------------------------------------------------------------------------

class TestStaleReplayEliminated(unittest.TestCase):
    def _build(self, advance_in_revalidate=True):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = _make_precondition(gen=GENERATION_INITIAL)  # captures N=1
        decision = _make_decision(cap, reg, pc)
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)  # N=1
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm,
            decision=decision,
            advance_in_revalidate=advance_in_revalidate,
            idempotency_store=store,
            router=router,
        )
        # Seed a stale SUCCESS that must NOT be replayed once generation advances.
        stale = CapabilityExecutionOutcome(
            result=CapabilityResult(
                capability=cap.name, success=True, output="old",
                error_code=None, metadata={},
            )
        )
        store.seed(_cache_key(mission, cap.name, "idem-1"), stale)
        return service, mission, store, router, cap, pc, rrm

    def test_01_stale_replay_eliminated_hc(self):
        """Advance N->N+1 inside revalidate: cache is never consulted (get_count==0)."""
        service, mission, store, router, cap, pc, rrm = self._build(advance_in_revalidate=True)
        outcome = _run(service.execute(
            mission.id, cap.name, idempotency_key="idem-1",
        ))
        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(outcome.result.metadata.get("freshness_phase"), "hc")
        self.assertEqual(outcome.result.metadata.get("freshness"), "generation_mismatch")
        self.assertEqual(store.get_count, 0)
        self.assertEqual(router.dispatch_count, 0)
        self.assertEqual(store.save_count, 0)

    def test_02_rrm_not_mutated_by_hc(self):
        """Hc is read-only: FakeRRM generation is unchanged after execution."""
        service, mission, store, router, cap, pc, rrm = self._build(advance_in_revalidate=False)
        _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        # After a normal (non-advanced) execution the source generation is untouched.
        self.assertEqual(rrm._generation, GENERATION_INITIAL)


# ---------------------------------------------------------------------------
# 3: cache-miss race rejected by Hd
# ---------------------------------------------------------------------------

class TestCacheMissRaceHd(unittest.TestCase):
    def test_03_hd_rejects_race_after_miss(self):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = _make_precondition(gen=GENERATION_INITIAL)  # N=1
        decision = _make_decision(cap, reg, pc)
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)  # N=1
        store = FakeIdempotencyStore()
        router = FakeRouter()

        # Advance N->N+1 at the cache MISS (between Hc and Hd).
        async def hook(_key):
            rrm.advance()
        store.on_get_hook = hook

        service, mission, store = _make_service(
            rrm=rrm, decision=decision,
            idempotency_store=store, router=router,
        )
        outcome = _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(outcome.result.metadata.get("freshness_phase"), "hd")
        self.assertEqual(outcome.result.metadata.get("freshness"), "generation_mismatch")
        self.assertEqual(store.get_count, 1)       # single miss lookup happened
        self.assertEqual(router.dispatch_count, 0)  # NOT dispatched (Hd rejected)
        self.assertEqual(store.save_count, 0)


# ---------------------------------------------------------------------------
# 4: fresh replay still works
# ---------------------------------------------------------------------------

class TestFreshReplay(unittest.TestCase):
    def test_04_fresh_replay_single_lookup_no_dispatch(self):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = _make_precondition(gen=GENERATION_INITIAL)
        decision = _make_decision(cap, reg, pc)
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)  # unchanged
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm, decision=decision, idempotency_store=store, router=router,
        )
        # Cache a fresh outcome.
        fresh = CapabilityExecutionOutcome(
            result=CapabilityResult(
                capability=cap.name, success=True, output="new",
                error_code=None, metadata={},
            )
        )
        store.seed(_cache_key(mission, cap.name, "idem-1"), fresh)

        outcome = _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        self.assertTrue(outcome.result.success)
        self.assertEqual(outcome.result.output, "new")
        self.assertTrue(outcome.result.metadata.get("idempotent_replay"))
        self.assertEqual(store.get_count, 1)       # single lookup
        self.assertEqual(router.dispatch_count, 0)  # replay, not dispatch
        self.assertEqual(store.save_count, 0)


# ---------------------------------------------------------------------------
# 4b: fresh dispatch still works
# ---------------------------------------------------------------------------

class TestFreshDispatch(unittest.TestCase):
    def test_04b_fresh_dispatch_saves_and_returns(self):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = _make_precondition(gen=GENERATION_INITIAL)
        decision = _make_decision(cap, reg, pc)
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)  # unchanged
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm, decision=decision, idempotency_store=store, router=router,
        )

        outcome = _run(service.execute(mission.id, cap.name, idempotency_key="idem-1", payload={"text": "hi"}))
        self.assertTrue(outcome.result.success)
        self.assertEqual(outcome.result.output, "ok")
        self.assertEqual(store.get_count, 1)       # single miss lookup
        self.assertEqual(router.dispatch_count, 1)  # dispatched
        self.assertEqual(store.save_count, 1)      # cached after success


# ---------------------------------------------------------------------------
# 5: structural ordering may not be bypassed by cache
# ---------------------------------------------------------------------------

class TestStructuralOrdering(unittest.TestCase):
    def test_05_structural_ahead_of_cache(self):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc_dec = _make_precondition(gen=GENERATION_INITIAL)
        decision = _make_decision(cap, reg, pc_dec)
        # Revalidation structurally diverges (different generation) -> identity mismatch.
        pc_rev = _make_precondition(gen=GENERATION_INITIAL + 1)
        reval = ResourceBindingRevalidation(
            capability=cap.name, valid=True, binding_registered=True,
            rrm_eligible=True, binding_healthy=True, reason="dispatch_revalidated",
            binding_identity=reg.binding_identity,
            execution_preconditions=(pc_rev,),
        )
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm, decision=decision, revalidation=reval,
            idempotency_store=store, router=router,
        )
        # Even with a stale SUCCESS cached, structural mismatch must win.
        stale = CapabilityExecutionOutcome(
            result=CapabilityResult(capability=cap.name, success=True, output="old",
                                    error_code=None, metadata={}),
        )
        store.seed(_cache_key(mission, cap.name, "idem-1"), stale)

        outcome = _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertTrue(outcome.result.metadata.get("precondition_identity_mismatch"))
        self.assertEqual(store.get_count, 0)       # cache never consulted
        self.assertEqual(router.dispatch_count, 0)  # not dispatched


# ---------------------------------------------------------------------------
# 6: single lookup on fresh path
# ---------------------------------------------------------------------------

class TestSingleLookup(unittest.TestCase):
    def test_06_single_lookup(self):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = _make_precondition(gen=GENERATION_INITIAL)
        decision = _make_decision(cap, reg, pc)
        rrm = FakeRRM(grid="reg-1", generation=GENERATION_INITIAL)
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm, decision=decision, idempotency_store=store, router=router,
        )
        _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        self.assertEqual(store.get_count, 1)


# ---------------------------------------------------------------------------
# 7-11: fail-closed freshness cases
# ---------------------------------------------------------------------------

class TestFailClosed(unittest.TestCase):
    def _run_case(self, *, snapshot=None, precondition=None, expect_reason):
        cap = _make_capability()
        reg = _make_registration(cap)
        pc = precondition or _make_precondition(gen=GENERATION_INITIAL)
        decision = _make_decision(cap, reg, pc)
        snapshot = snapshot or {}
        rrm = FakeRRM(grid=snapshot.get("grid", "reg-1"),
                      generation=snapshot.get("generation", GENERATION_INITIAL))
        if snapshot.get("missing"):
            rrm.get_capability = lambda name: None
        store = FakeIdempotencyStore()
        router = FakeRouter()
        service, mission, store = _make_service(
            rrm=rrm, decision=decision, idempotency_store=store, router=router,
        )
        outcome = _run(service.execute(mission.id, cap.name, idempotency_key="idem-1"))
        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertIn(outcome.result.metadata.get("freshness"), expect_reason)
        self.assertEqual(router.dispatch_count, 0)

    def test_07_missing_resource(self):
        # precondition expects "test.echo" but RRM has none (get returns None)
        self._run_case(snapshot={"missing": True}, expect_reason={"resource_not_found"})

    def test_08_lineage_mismatch(self):
        self._run_case(snapshot={"grid": "other-lineage"},
                       expect_reason={"registration_lineage_mismatch"})

    def test_09_generation_mismatch(self):
        self._run_case(snapshot={"generation": GENERATION_INITIAL + 1},
                       expect_reason={"generation_mismatch"})

    def test_10_legacy_unversioned(self):
        self._run_case(snapshot={"generation": LEGACY_UNVERSIONED},
                       expect_reason={"legacy_unversioned"})

    def test_11_unsupported_precondition_kind(self):
        pc = _make_precondition(kind=PreconditionKind.EXPECTED_ABSENCE, gen=LEGACY_UNVERSIONED, grid="")
        self._run_case(precondition=pc, expect_reason={"unsupported_precondition"})


if __name__ == "__main__":
    unittest.main()
