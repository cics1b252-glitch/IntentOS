"""TP-02D-R4/R5: independent isolation + security regate.

Proves the SUPPORTED preview path binds the native executor at CONSTRUCTION of
an UNPUBLISHED dedicated ``MissionRuntime`` and NEVER writes the shared
runtime's executor. Independent of the ordering of the other TP-02 suites.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

import intent_kernel.adapters.preview_selection as sel
from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    LocalFilesystemObserver,
    sha256_bytes,
)
from intent_kernel.adapters.native_containment import (
    NativeCreateTestFileActionExecutor,
)
from intent_kernel.adapters.preview_selection import (
    PreviewSelectionDenied,
    build_dedicated_runtime,
    build_native_executor,
    run_bound_dispatch,
    validate_established,
)
from intent_kernel.runtime.checkpoints import InMemoryCheckpointRepository
from intent_kernel.runtime.executor_port import InMemoryActionExecutor
from intent_kernel.runtime.models import ActionContract, MissionCheckpoint

from tests.test_tp02_preview_integration import (
    CONTENT,
    NOW,
    _contract,
    _established,
    _root,
)

CLOCK = lambda: NOW  # noqa: E731


class _SharedRuntime:
    """Stand-in for the shared application MissionRuntime exposing the exact
    surface the preview reads: executor + durable lifecycle services."""

    def __init__(self) -> None:
        self.executor = InMemoryActionExecutor()
        self.checkpoint_repo = InMemoryCheckpointRepository()
        self.resource_manager = object()
        self.dispatch_guard = object()
        self.mission_engine = object()
        self._mission_record_store = object()
        self.action_gate = types.SimpleNamespace(
            _constitution=object(), _replay_policy=object()
        )
        self.verification_gate = types.SimpleNamespace(_external_adapter=object())


def _contract_named(name: str, content: bytes = CONTENT, op: str = OPERATION) -> ActionContract:
    c = ActionContract(action_id="n1", capability=CAPABILITY, action_type=op,
                       idempotency_key="r5")
    c.inputs_reference = {"path": name, "content": content.decode()}
    return c


def _grant_named(root: Path, authority, name: str) -> CreateTestFileAuthority:
    return CreateTestFileAuthority(
        authorized_root=root, authorized_target=root / name,
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority, now_provider=CLOCK)


# ---------------------------------------------------------------------------
# R4: construction-time binding + shared durable services
# ---------------------------------------------------------------------------
def test_r4_module_has_no_shared_runtime_executor_assignment():
    """Static proof: the module contains no attribute assignment to executor."""
    src = Path(sel.__file__).read_text(encoding="utf-8")
    assert re.search(r"\.\s*executor\s*=\s*[^=]", src) is None, (
        "no `*.executor = ...` assignment may exist in the preview module"
    )
    assert "def _bind_executor_held" not in src  # the binder is not defined
    assert not hasattr(sel, "_bind_executor_held")  # nor reachable


def test_r4_dedicated_runtime_binds_executor_and_shares_durable_services(tmp_path):
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)
    ex = build_native_executor(authority=authority, authorized_root=root,
                               target_name="a.txt", content=CONTENT)
    try:
        dedicated = build_dedicated_runtime(shared, ex)
        assert dedicated is not shared
        assert dedicated.executor is ex  # bound AT CONSTRUCTION
        # SAME durable lifecycle service objects (continuity), never copies.
        assert dedicated.checkpoint_repo is shared.checkpoint_repo
        assert dedicated.dispatch_guard is shared.dispatch_guard
        assert dedicated._mission_record_store is shared._mission_record_store
        assert dedicated.resource_manager is shared.resource_manager
        assert dedicated.mission_engine is shared.mission_engine
        assert dedicated.action_gate._constitution is shared.action_gate._constitution
        assert dedicated.action_gate._replay_policy is shared.action_gate._replay_policy
        assert dedicated.verification_gate._external_adapter is (
            shared.verification_gate._external_adapter)
        # The shared runtime was not mutated by construction.
        assert shared.executor is original
        assert not any(v is dedicated for v in vars(shared).values())
    finally:
        ex.close()


def test_r4_zero_post_construction_executor_writes(tmp_path):
    """Behavioural proof: shared executor identity is stable across a dispatch
    and the dedicated executor never changes after construction."""
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)
    captured: dict = {}

    async def run(runtime):
        captured["d"] = runtime
        captured["at_entry"] = runtime.executor
        result = await runtime.executor.execute(_contract_named("z.txt"))
        captured["after"] = runtime.executor
        return result

    res = asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="z.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert res["effect_calls"] == 1
    assert isinstance(captured["at_entry"], NativeCreateTestFileActionExecutor)
    assert captured["after"] is captured["at_entry"]  # never reassigned
    assert shared.executor is original                # shared untouched


# ---------------------------------------------------------------------------
# R5-#2: the dedicated runtime is UNPUBLISHED
# ---------------------------------------------------------------------------
def test_r5_dedicated_runtime_is_unpublished(tmp_path):
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)
    captured: dict = {}

    async def run(runtime):
        captured["d"] = runtime
        return await runtime.executor.execute(_contract_named("u.txt"))

    asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="u.txt", content=CONTENT, run=run, now_provider=CLOCK))

    dedicated = captured["d"]
    assert dedicated is not shared
    # No reference from the shared runtime...
    assert not any(v is dedicated for v in vars(shared).values())
    # ...nor from any module global of the preview module.
    assert all(v is not dedicated for v in vars(sel).values())
    # No registry attribute was introduced to retain dedicated runtimes.
    assert not hasattr(sel, "_DEDICATED_RUNTIMES")
    assert shared.executor is original


# ---------------------------------------------------------------------------
# R5-#4: real effect + independent observation of the EXACT authorized target
# ---------------------------------------------------------------------------
def test_r5_real_effect_observed_exact_target(tmp_path):
    shared = _SharedRuntime()
    root = _root(tmp_path)
    authority = _established(root)
    captured: dict = {}

    async def run(runtime):
        captured["d"] = runtime
        return await runtime.executor.execute(_contract_named("exact.txt"))

    res = asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="exact.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert res["effect_calls"] == 1
    assert res["denials"] == []
    assert (root / "exact.txt").read_bytes() == CONTENT
    assert sorted(p.name for p in root.iterdir()) == ["exact.txt"]
    obs = LocalFilesystemObserver(_grant_named(root, authority, "exact.txt")).observe()
    assert obs.exists is True
    assert obs.matches_authorized is True
    assert obs.observed_sha256 == sha256_bytes(CONTENT)
    assert captured["d"] is not shared


# ---------------------------------------------------------------------------
# R5-#5: durable checkpoint continuity across dedicated instances
# ---------------------------------------------------------------------------
def test_r5_checkpoint_continuity_across_dedicated_instances(tmp_path):
    shared = _SharedRuntime()
    root = _root(tmp_path)
    authority = _established(root)
    captured: list = []

    async def run(runtime):
        captured.append(runtime)
        return await runtime.executor.execute(_contract_named(f"c{len(captured)}.txt"))

    for _ in range(2):
        asyncio.run(run_bound_dispatch(
            mission_runtime=shared, authority=authority, authorized_root=root,
            target_name=f"c{len(captured) + 1}.txt", content=CONTENT,
            run=run, now_provider=CLOCK))

    d1, d2 = captured[0], captured[1]
    assert d1 is not d2
    assert d1.checkpoint_repo is shared.checkpoint_repo
    assert d2.checkpoint_repo is shared.checkpoint_repo

    # Concrete continuity: state written through one dedicated runtime is
    # visible through the other (same durable repository object).
    chk = MissionCheckpoint(runtime_id="rt-cont", mission_id="m-cont")
    assert asyncio.run(d1.checkpoint_repo.save_checkpoint(chk)) is True
    got = asyncio.run(d2.checkpoint_repo.get_latest_checkpoint("rt-cont"))
    assert got is not None and got.checkpoint_id == chk.checkpoint_id


# ---------------------------------------------------------------------------
# R5-#6: authority identity is preserved
# ---------------------------------------------------------------------------
def test_r5_authority_identity_preserved(tmp_path):
    shared = _SharedRuntime()
    root = _root(tmp_path)
    authority = _established(root)
    digest_before = authority.authority_digest

    captured: dict = {}

    async def run(runtime):
        captured["d"] = runtime
        return await runtime.executor.execute(_contract_named("id.txt"))

    asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="id.txt", content=CONTENT, run=run, now_provider=CLOCK))

    dedicated = captured["d"]
    # Constitution identity is the same live object (no shadow authority).
    assert dedicated.action_gate._constitution is shared.action_gate._constitution
    assert dedicated.resource_manager is shared.resource_manager
    # The authority record still validates and its identity is unchanged.
    assert validate_established(authority) is authority
    assert authority.authority_digest == digest_before


# ---------------------------------------------------------------------------
# R5-#7: revocation / target / content / duplicate denial
# ---------------------------------------------------------------------------
def test_r5_denials_revocation_target_content_duplicate(tmp_path):
    shared = _SharedRuntime()
    root = _root(tmp_path)
    authority = _established(root)

    # duplicate
    async def dup(runtime):
        a = await runtime.executor.execute(_contract_named("dup.txt"))
        b = await runtime.executor.execute(_contract_named("dup.txt"))
        return a, b

    res = asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="dup.txt", content=CONTENT, run=dup, now_provider=CLOCK))
    first, second = res["outcome"]
    assert first["effect_occurred"] is True
    assert second["effect_occurred"] is False
    assert res["effect_calls"] == 1

    # content substitution
    async def bad_content(runtime):
        return await runtime.executor.execute(
            _contract_named("cs.txt", content=b"tampered"))

    res = asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="cs.txt", content=CONTENT, run=bad_content, now_provider=CLOCK))
    assert res["outcome"]["effect_occurred"] is False
    assert res["effect_calls"] == 0
    assert not (root / "cs.txt").exists()

    # target substitution
    async def bad_target(runtime):
        return await runtime.executor.execute(_contract_named("other.txt"))

    res = asyncio.run(run_bound_dispatch(
        mission_runtime=shared, authority=authority, authorized_root=root,
        target_name="ts.txt", content=CONTENT, run=bad_target, now_provider=CLOCK))
    assert res["effect_calls"] == 0
    assert not (root / "other.txt").exists()
    assert not (root / "ts.txt").exists()

    # revocation (re-proven at effect time)
    ex = build_native_executor(authority=authority, authorized_root=root,
                               target_name="rev.txt", content=CONTENT)
    ex._native._grant.revoked = True
    receipt = asyncio.run(ex.execute(_contract_named("rev.txt")))
    ex.close()
    assert receipt["effect_occurred"] is False
    assert not (root / "rev.txt").exists()


# ---------------------------------------------------------------------------
# R5-#8: unsupported containment fails closed (no fallback)
# ---------------------------------------------------------------------------
def test_r5_unsupported_containment_fails_closed(tmp_path, monkeypatch):
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)
    monkeypatch.setattr(sel, "platform_capabilities",
                        lambda: {"platform": "fake", "preventive": False})

    async def run(runtime):
        return await runtime.executor.execute(_contract_named("u.txt"))

    with pytest.raises(PreviewSelectionDenied) as exc:
        asyncio.run(run_bound_dispatch(
            mission_runtime=shared, authority=authority, authorized_root=root,
            target_name="u.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert exc.value.code == "native-containment-unsupported"
    assert not (root / "u.txt").exists()
    assert shared.executor is original


# ---------------------------------------------------------------------------
# R5-#9: concurrency, cancellation, exception
# ---------------------------------------------------------------------------
def test_r5_concurrent_threads_single_effect(tmp_path):
    shared = _SharedRuntime()
    root = _root(tmp_path)
    authority = _established(root)
    outcomes: list = []

    async def run(runtime):
        await asyncio.sleep(0.02)
        return await runtime.executor.execute(_contract_named("thr.txt"))

    def worker():
        try:
            outcomes.append(asyncio.run(run_bound_dispatch(
                mission_runtime=shared, authority=authority, authorized_root=root,
                target_name="thr.txt", content=CONTENT, run=run, now_provider=CLOCK)))
        except Exception as exc:  # pragma: no cover
            outcomes.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert len(outcomes) == 3
    assert not any(isinstance(o, Exception) for o in outcomes), outcomes
    assert sum(o["effect_calls"] for o in outcomes) == 1
    assert (root / "thr.txt").read_bytes() == CONTENT


def test_r5_cancellation_leaves_shared_runtime_untouched(tmp_path):
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)

    async def run(runtime):
        await asyncio.sleep(5)
        return "never"

    async def main():
        task = asyncio.ensure_future(run_bound_dispatch(
            mission_runtime=shared, authority=authority, authorized_root=root,
            target_name="cancel.txt", content=CONTENT, run=run, now_provider=CLOCK))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert shared.executor is original
    assert not (root / "cancel.txt").exists()


def test_r5_exception_leaves_shared_runtime_untouched(tmp_path):
    shared = _SharedRuntime()
    original = shared.executor
    root = _root(tmp_path)
    authority = _established(root)

    async def boom(runtime):
        raise RuntimeError("dispatch exploded")

    with pytest.raises(RuntimeError):
        asyncio.run(run_bound_dispatch(
            mission_runtime=shared, authority=authority, authorized_root=root,
            target_name="boom.txt", content=CONTENT, run=boom, now_provider=CLOCK))
    assert shared.executor is original
    assert not (root / "boom.txt").exists()


# ---------------------------------------------------------------------------
# R5-#12: independent audit of the R1 lock implementation
# ---------------------------------------------------------------------------
def test_r5_r1_runtime_lock_is_per_runtime_not_global():
    a = _SharedRuntime()
    b = _SharedRuntime()
    la1 = sel._runtime_lock(a)
    la2 = sel._runtime_lock(a)
    lb = sel._runtime_lock(b)
    assert la1 is la2            # stable per runtime
    assert la1 is not lb         # NOT a single global lock


def test_r5_r1_loop_lock_never_crosses_event_loops():
    rt = _SharedRuntime()

    async def capture(runtime):
        return sel._loop_lock(runtime)

    first = asyncio.run(capture(rt))
    second = asyncio.run(capture(rt))
    assert first is not second, "a lock must not be reused across event loops"
    # Outside a running loop the null lock is returned (no binding, no error).
    assert isinstance(sel._loop_lock(rt), sel._NullAsyncLock)


def test_r5_r1_runtime_lock_excludes_threads():
    rt = _SharedRuntime()
    lock = sel._runtime_lock(rt)
    active = [0]
    max_active = [0]
    guard = threading.Lock()

    def worker():
        with lock:
            with guard:
                active[0] += 1
                max_active[0] = max(max_active[0], active[0])
            time.sleep(0.02)
            with guard:
                active[0] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert max_active[0] == 1
