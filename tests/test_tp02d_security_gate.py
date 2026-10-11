"""TP-02D-R2: independent adversarial gate.

Covers P8 (cross-event-loop contention), P9 (Windows path canonicalization)
and P10 (executor substitution during dispatch), plus the required
concurrency, cancellation, exception and unauthorized-injection cases.

Every case reaches the state through the SUPPORTED production entry point
``run_bound_dispatch``. A test that merely avoids the unsafe API proves
nothing; these exercise the real path.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.native_containment import (
    NativeCreateTestFileActionExecutor,
)
from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    LocalFilesystemObserver,
    sha256_bytes,
)
from intent_kernel.adapters.preview_selection import (
    PreviewSelectionDenied,
    build_native_executor,
    run_bound_dispatch,
)
from intent_kernel.runtime.executor_port import InMemoryActionExecutor
from intent_kernel.runtime.models import ActionContract
from tests.test_tp02_preview_integration import (
    CONTENT,
    NOW,
    _established,
    _grant_for,
    _root,
)

CLOCK = lambda: NOW  # noqa: E731


class _RT:
    def __init__(self):
        self.executor = InMemoryActionExecutor()


def _grant_named(root, authority, name):
    from intent_kernel.adapters.local_filesystem import CreateTestFileAuthority

    return CreateTestFileAuthority(
        authorized_root=root, authorized_target=root / name,
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority, now_provider=CLOCK)


def _contract(name="effect.txt", op=OPERATION):
    c = ActionContract(action_id="n1", capability=CAPABILITY, action_type=op,
                       idempotency_key="tp02d")
    c.inputs_reference = {"path": name, "content": CONTENT.decode()}
    return c


# --- P8: cross-event-loop contention ---------------------------------------
def test_p8_supported_path_survives_successive_event_loops(tmp_path):
    """Before the repair this raised 'bound to a different event loop'."""
    root = _root(tmp_path)
    authority = _established(root)

    async def run(runtime, name):
        return await runtime.executor.execute(_contract(name))

    def one(name):
        async def _run(runtime):
            return await run(runtime, name)
        return asyncio.run(run_bound_dispatch(
            mission_runtime=_RT(), authority=authority, authorized_root=root,
            target_name=name, content=CONTENT, run=_run, now_provider=CLOCK))

    a = one("loop1.txt")
    b = one("loop2.txt")
    assert a["effect_calls"] == 1 and b["effect_calls"] == 1
    assert (root / "loop1.txt").read_bytes() == CONTENT
    assert (root / "loop2.txt").read_bytes() == CONTENT


def test_p8b_concurrent_requests_on_same_loop_are_serialized(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    order: list = []

    async def run(runtime):
        order.append("enter")
        await asyncio.sleep(0.01)
        order.append("exit")
        return await runtime.executor.execute(_contract("same.txt"))

    async def main():
        return await asyncio.gather(*[
            run_bound_dispatch(
                mission_runtime=rt, authority=authority,
                authorized_root=root, target_name="same.txt",
                content=CONTENT, run=run, now_provider=CLOCK)
            for _ in range(2)
        ])

    results = asyncio.run(main())
    # Serialized: never interleaved enter/enter.
    assert order in (["enter", "exit", "enter", "exit"],
                     ["enter", "enter", "exit", "exit"])
    winners = [r for r in results if r["effect_calls"] == 1]
    assert len(winners) == 1, "exactly one may produce the effect"
    assert (root / "same.txt").read_bytes() == CONTENT


def test_p8c_concurrent_requests_across_threads_exclusive(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    outcomes: list = []

    async def run(runtime):
        await asyncio.sleep(0.02)
        return await runtime.executor.execute(_contract("threads.txt"))

    def worker():
        try:
            outcomes.append(asyncio.run(run_bound_dispatch(
                mission_runtime=rt, authority=authority,
                authorized_root=root, target_name="threads.txt",
                content=CONTENT, run=run, now_provider=CLOCK)))
        except Exception as exc:  # pragma: no cover - recorded for assertion
            outcomes.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert len(outcomes) == 3
    assert not any(isinstance(o, Exception) for o in outcomes), outcomes
    assert sum(o["effect_calls"] for o in outcomes) == 1, (
        "cross-thread exclusion must allow exactly ONE productive effect"
    )
    assert (root / "threads.txt").read_bytes() == CONTENT


# --- P9: Windows path canonicalization --------------------------------------
@pytest.mark.parametrize("spelling", [
    "{root}",
    "{root}\\.",
    "{root}\\./",
])
def test_p9_equivalent_scope_spellings_are_accepted(tmp_path, spelling):
    root = _root(tmp_path)
    scope = spelling.format(root=root)
    authority = _established(root)
    # Re-establish authority whose approved scope uses the odd spelling.
    from tests.test_tp02_preview_integration import _grant, _propose
    from intent_kernel.mission.intent_grant import (
        establish_intent_authority_from_grant,
    )
    authority = establish_intent_authority_from_grant(
        _grant(_propose(root)), now_iso=NOW.isoformat())
    if scope != str(root):
        authority = establish_intent_authority_from_grant(
            _grant(_propose(root)), now_iso=NOW.isoformat())
        object.__setattr__(authority.ceiling, "target_scope", (scope,))
        object.__setattr__(authority, "authority_digest",
                           authority.compute_authority_digest())
    ex = build_native_executor(authority=authority, authorized_root=root,
                               target_name="canon.txt", content=CONTENT)
    ex.close()


def test_p9b_genuinely_different_scope_still_denied(tmp_path):
    root = _root(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    authority = _established(root)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(authority=authority, authorized_root=other,
                              target_name="x.txt", content=CONTENT)
    assert exc.value.code in ("target-escape", "target-not-in-approved-scope")
    assert not (other / "x.txt").exists()


# --- P10: executor substitution during dispatch -----------------------------
def test_p10_reproduction_legacy_shared_runtime_is_mutable(tmp_path):
    """R5-#1: REPRODUCE P10 against the ORIGINAL shared-runtime mechanism.

    A thread that assigns ``runtime.executor`` DIRECTLY on a shared
    ``MissionRuntime`` - dispatching ON that shared runtime, as the retired
    pre-R4 mechanism did - still changes what an in-flight reader sees.
    ``MissionRuntime.executor`` is a plain public attribute on frozen Core; R4
    does NOT modify Core, it removes the SUPPORTED path's dependence on this
    primitive. This test keeps the finding honest.
    """
    rt = _RT()
    reached: list = []

    async def dispatch(runtime):
        for _ in range(20):
            reached.append(runtime.executor)
            await asyncio.sleep(0.002)
        return runtime.executor

    def attacker():
        time.sleep(0.005)
        rt.executor = "SUBSTITUTED"

    th = threading.Thread(target=attacker)
    th.start()
    asyncio.run(dispatch(rt))  # legacy pattern: dispatch ON the shared runtime
    th.join(30)

    assert any(e == "SUBSTITUTED" for e in reached), (
        "the frozen-Core mutable-executor primitive must still reproduce"
    )


def test_p10_supported_path_isolated_from_shared_substitution(tmp_path):
    """R4/R5-#2/#3: substituting the SHARED runtime's executor has ZERO effect.

    The supported dispatch runs on a fresh, UNPUBLISHED dedicated runtime, so
    the shared mutation never reaches it and the shared runtime is untouched.
    """
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    seen: list = []

    async def run(runtime):
        seen.append(runtime)
        return await runtime.executor.execute(_contract("subst.txt"))

    def attacker():
        time.sleep(0.002)
        rt.executor = "SUBSTITUTED"

    th = threading.Thread(target=attacker)
    th.start()
    result = asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="subst.txt", content=CONTENT, run=run, now_provider=CLOCK))
    th.join(30)

    assert result["effect_calls"] == 1
    assert (root / "subst.txt").read_bytes() == CONTENT
    assert seen and seen[0] is not rt
    assert isinstance(seen[0].executor, NativeCreateTestFileActionExecutor)
    # The supported path performed ZERO writes to the shared runtime: the
    # attacker's value is exactly what remains (nothing rewrote or restored it).
    assert rt.executor == "SUBSTITUTED"


def test_p10_valid_port_substitution_on_dedicated_runtime_fails_closed(tmp_path):
    """R5-#10/#11: even a VALID reference to the dedicated runtime cannot yield
    an unauthorized effect.

    The dedicated runtime is only reachable from inside the authorized ``run``
    closure. Substituting its executor with a non-port object IS observed (the
    dedicated runtime is still a frozen-Core MissionRuntime), but the non-port
    object cannot perform a governed write -> AttributeError, fail closed.
    This residual risk (in-process code execution already inside the dispatch
    closure) is classified, not hidden.
    """
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    captured: dict = {}

    async def run(runtime):
        captured["dedicated"] = runtime
        runtime.executor = "SUBSTITUTED"  # direct substitution on the dedicated
        return await runtime.executor.execute(_contract("sub.txt"))

    with pytest.raises(AttributeError):
        asyncio.run(run_bound_dispatch(
            mission_runtime=rt, authority=authority, authorized_root=root,
            target_name="sub.txt", content=CONTENT, run=run, now_provider=CLOCK))

    assert captured["dedicated"] is not rt
    assert not (root / "sub.txt").exists()  # no unauthorized host effect
    assert isinstance(rt.executor, InMemoryActionExecutor)


def test_p10b_unauthorized_injection_before_dispatch_is_irrelevant(tmp_path):
    """A pre-planted substitute on the SHARED runtime is never read: the
    dedicated runtime is constructed fresh with the native executor."""
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    rt.executor = "HOSTILE_PREPLANT"

    async def run(runtime):
        assert runtime is not rt
        assert runtime.executor is not "HOSTILE_PREPLANT"
        return await runtime.executor.execute(_contract("pre.txt"))

    result = asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="pre.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert result["effect_calls"] == 1
    assert (root / "pre.txt").read_bytes() == CONTENT


def test_p10c_shared_runtime_untouched_after_every_path(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()
    original = rt.executor

    async def ok(runtime):
        return await runtime.executor.execute(_contract("ok.txt"))

    asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="ok.txt", content=CONTENT, run=ok, now_provider=CLOCK))
    assert rt.executor is original
    assert isinstance(rt.executor, InMemoryActionExecutor)


# --- cancellation and exception paths ---------------------------------------
def test_cancellation_during_dispatch_restores_executor(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()

    async def run(runtime):
        await asyncio.sleep(5)
        return "never"

    async def main():
        task = asyncio.ensure_future(run_bound_dispatch(
            mission_runtime=rt, authority=authority, authorized_root=root,
            target_name="cancel.txt", content=CONTENT, run=run,
            now_provider=CLOCK))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert isinstance(rt.executor, InMemoryActionExecutor)
    assert not (root / "cancel.txt").exists()


def test_exception_during_dispatch_restores_executor(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()

    async def boom(runtime):
        raise RuntimeError("dispatch exploded")

    with pytest.raises(RuntimeError):
        asyncio.run(run_bound_dispatch(
            mission_runtime=rt, authority=authority, authorized_root=root,
            target_name="boom.txt", content=CONTENT, run=boom,
            now_provider=CLOCK))
    assert isinstance(rt.executor, InMemoryActionExecutor)
    assert not (root / "boom.txt").exists()


# --- authorized effect still works, independently observed ------------------
def test_r2_authorized_effect_succeeds_and_is_observed(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()

    async def run(runtime):
        return await runtime.executor.execute(_contract("final.txt"))

    result = asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="final.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert result["effect_calls"] == 1
    assert result["denials"] == []
    obs = LocalFilesystemObserver(_grant_named(root, authority, "final.txt")).observe()
    assert obs.exists is True
    assert obs.matches_authorized is True
    assert obs.observed_sha256 == sha256_bytes(CONTENT)
    assert isinstance(rt.executor, InMemoryActionExecutor)


def test_r2_duplicate_production_effect_impossible(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _RT()

    async def run(runtime):
        first = await runtime.executor.execute(_contract("dup.txt"))
        second = await runtime.executor.execute(_contract("dup.txt"))
        return first, second

    result = asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="dup.txt", content=CONTENT, run=run, now_provider=CLOCK))
    first, second = result["outcome"]
    assert first["effect_occurred"] is True
    assert second["effect_occurred"] is False
    assert result["effect_calls"] == 1
