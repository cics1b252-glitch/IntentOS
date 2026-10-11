"""FRONT-TP-02: controlled selection of the native governed filesystem executor.

    SELECTOR != APPROVER        SELECTOR != AUTHORITY
    PRODUCT_BRIDGE != AUTHORIZER

This module decides ONE thing: given an ALREADY-ESTABLISHED, digest-valid
``IntentAuthorityRecord``, may this specific request be executed by the native
``CREATE_TEST_FILE`` executor, and under what exact binding?

It cannot approve anything. It cannot enlarge a ceiling. It cannot fabricate an
authority record. It never receives a caller-asserted "this is authorized"
flag as evidence: the only accepted authority input is a real
``IntentAuthorityRecord``, whose own digest must still validate, and whose
ceiling must already contain the capability, the operation and the target.

Authority flow (unchanged, reused from J1):
    propose_intent_authority -> approve_intent_authority -> IntentAuthorityGrant
        -> establish_intent_authority_from_grant -> IntentAuthorityRecord

Everything below runs AFTER that chain. The selector is a narrowing filter,
not an approval step.

DEFAULT BEHAVIOUR
    ``InMemoryActionExecutor`` remains the ProductBridge default. This selector
    never mutates the shared application ``MissionRuntime``: it CONSTRUCTS a
    fresh, unpublished, dedicated ``MissionRuntime`` whose ``executor`` is
    bound at construction time, runs exactly one dispatch on it, and lets it be
    collected. There is NO silent fallback: if native containment is
    unavailable, the request is DENIED, not downgraded to a weaker filesystem
    executor.

TP-02D-R4 (this revision)
    The previous revision performed a shared-runtime executor SWAP: it
    temporarily assigned ``mission_runtime.executor`` for the duration of the
    dispatch and restored it in a ``finally``. Because ``MissionRuntime`` is a
    frozen Core class with a plain public ``executor`` attribute, in-process
    code holding a reference to the shared runtime could substitute the
    executor mid-dispatch (P10). The supported path no longer shares a mutable
    executor: the native executor is bound at CONSTRUCTION of a dedicated,
    unpublished runtime that no other holder can reach. The private mutation
    binder (``_bind_executor_held``) is RETIRED - there is no post-construction
    executor assignment anywhere in this module.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    sha256_bytes,
)
from intent_kernel.adapters.native_containment import (
    NativeContainment,
    NativeContainmentUnavailable,
    NativeCreateTestFileActionExecutor,
    platform_capabilities,
)
from intent_kernel.mission.intent_authority import IntentAuthorityRecord


#: Bounded wait so a pathological caller cannot hang the process forever.
_LOCK_TIMEOUT_SECONDS = 120.0


class PreviewSelectionDenied(RuntimeError):
    """Request refused before any executor was bound. Carries a stable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


#: Per-runtime, PER-EVENT-LOOP async locks.
#:
#: TP-02D-R1 F-2: a single module-global ``asyncio.Lock`` was bound to
#: whichever loop touched it first. A second loop either raised
#: ``RuntimeError: ... is bound to a different event loop`` or deadlocked
#: forever on a lock held by a loop that no longer exists. Keying by the
#: RUNNING LOOP removes the binding entirely - each loop gets its own lock and
#: none is shared across loops. Weak keys let a dead loop's lock be collected.
_LOOP_LOCKS: "weakref.WeakKeyDictionary[Any, Dict[str, Any]]" = weakref.WeakKeyDictionary()

#: Per-runtime thread lock serializing the dedicated-dispatch critical section.
#: Held across the whole dispatch so two THREADS (or two event loops) cannot
#: interleave construction + execution for the same shared runtime. An
#: ``asyncio.Lock`` would not do: it excludes neither other threads nor other
#: loops (TP-02D-R1 F-2c).
#:
#: TP-02D-R4: with construction-time binding the lock no longer guards an
#: executor MUTATION (there is none). It now guards PRODUCTIVE SERIALIZATION of
#: the critical section so concurrent preview dispatches over the same shared
#: runtime remain mutually exclusive, preserving the single-effect guarantee.
_RUNTIME_LOCKS: "weakref.WeakKeyDictionary[Any, threading.Lock]" = weakref.WeakKeyDictionary()
_REGISTRY_GUARD = threading.Lock()


def _runtime_lock(mission_runtime: Any) -> threading.Lock:
    """Per-runtime threading lock. Never global: global state is the bug."""
    with _REGISTRY_GUARD:
        lock = _RUNTIME_LOCKS.get(mission_runtime)
        if lock is None:
            lock = threading.Lock()
            _RUNTIME_LOCKS[mission_runtime] = lock
        return lock


def _loop_lock(mission_runtime: Any) -> asyncio.Lock:
    """Async lock bound to the CURRENT event loop, stored per runtime.

    TP-02D-R1 F-2: a single module-global ``asyncio.Lock`` was bound to
    whichever loop touched it first, so a second loop raised
    ``RuntimeError: ... is bound to a different event loop`` or deadlocked on a
    lock held by a loop that no longer existed. The lock is now created for,
    and re-created whenever, the loop actually running. It never crosses a
    loop boundary: cross-loop and cross-thread exclusion is the job of
    ``_runtime_lock``, which is loop-agnostic by construction.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _NullAsyncLock()
    with _REGISTRY_GUARD:
        entry = _LOOP_LOCKS.get(mission_runtime)
        if entry is None or entry["loop"] is not loop:
            entry = {"loop": loop, "lock": asyncio.Lock()}
            _LOOP_LOCKS[mission_runtime] = entry
        return entry["lock"]


class _NullAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def validate_established(authority: Any) -> IntentAuthorityRecord:
    """Accept only a genuine, still-digest-valid authority record."""
    if not isinstance(authority, IntentAuthorityRecord):
        raise PreviewSelectionDenied("authority-type-invalid")
    # Re-verify the digest: a mutated/tampered record must not select.
    expected = authority.compute_authority_digest()
    if expected != authority.authority_digest:
        raise PreviewSelectionDenied("authority-digest-invalid")
    ceiling = authority.ceiling
    if not ceiling.is_constraining:
        raise PreviewSelectionDenied("authority-unbounded")
    if ceiling.allow_capabilities and CAPABILITY not in ceiling.allow_capabilities:
        raise PreviewSelectionDenied("capability-escalation")
    if ceiling.allowed_operations and OPERATION not in ceiling.allowed_operations:
        raise PreviewSelectionDenied("operation-escalation")
    return authority


def _authorize_target(ceiling_scope: Tuple[str, ...], authorized_root: Path,
                      target: Path) -> None:
    """Target must sit inside the AUTHORIZED ROOT and inside the ceiling.

    TP-02D-R1 F-3: BOTH sides are now canonicalized through ``Path.resolve()``
    before comparison. Previously the approved scope strings were compared
    verbatim against the resolved target, so a legitimate spelling of the same
    directory (``/root/.``, a trailing separator, a different case on Windows)
    produced a FALSE DENIAL. Target containment itself is unchanged: the
    resolved target must still be inside the resolved root.
    """
    try:
        resolved_root = authorized_root.resolve()
        resolved_target = target.resolve()
    except (OSError, RuntimeError) as exc:
        raise PreviewSelectionDenied("target-unresolvable", str(exc)) from exc
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise PreviewSelectionDenied("target-escape")
    if ceiling_scope:
        # Canonicalize every approved scope entry, then compare canonically.
        allowed_dirs = set()
        allowed_files = set()
        for entry in ceiling_scope:
            try:
                resolved_entry = Path(entry).resolve()
            except (OSError, RuntimeError):
                # An unresolvable approved entry simply authorizes nothing.
                continue
            allowed_dirs.add(str(resolved_entry))
            allowed_files.add(str(resolved_entry / target.name))
        if (str(resolved_target.parent) not in allowed_dirs
                and str(resolved_target) not in allowed_files):
            raise PreviewSelectionDenied("target-not-in-approved-scope")


def build_native_executor(
    *,
    authority: Any,
    authorized_root: Any,
    target_name: str,
    content: bytes,
    expected_root_identity: Optional[str] = None,
    now_provider: Any = None,
) -> NativeCreateTestFileActionExecutor:
    """Validate and construct the native executor for ONE authorized request.

    ``authorized_root``/``target_name``/``content`` describe WHAT is requested.
    They grant nothing: the ceiling decides whether that request is allowed.
    """
    established = validate_established(authority)
    root = Path(authorized_root)
    if not root.is_dir():
        raise PreviewSelectionDenied("authorized-root-missing")
    if not target_name or "/" in target_name or "\\" in target_name:
        raise PreviewSelectionDenied("target-name-invalid")
    target = root / target_name
    _authorize_target(established.ceiling.target_scope, root, target)

    caps = platform_capabilities()
    if not caps.get("preventive"):
        raise PreviewSelectionDenied(
            "native-containment-unsupported", str(caps.get("platform"))
        )
    try:
        containment = NativeContainment(root)
    except NativeContainmentUnavailable as exc:
        # Fail closed. NEVER fall back to the non-atomic M34 adapter.
        raise PreviewSelectionDenied(
            "native-containment-unavailable", str(exc)
        ) from exc

    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=target,
        expected_content_sha256=sha256_bytes(content),
        authority=established,
        allow_overwrite=False,
        **({"now_provider": now_provider} if now_provider is not None else {}),
    )
    try:
        return NativeCreateTestFileActionExecutor(
            grant, containment=containment,
            expected_root_identity=expected_root_identity,
        )
    except Exception as exc:
        containment.close()
        raise PreviewSelectionDenied("executor-construction-failed", str(exc)) from exc


#: Shared durable/lifecycle services that MUST be carried onto the dedicated
#: runtime. The SAME live objects are reused (never copied, never re-created),
#: so durable authority, dispatch idempotency, checkpoints and resource
#: governance remain continuous across dedicated runtime instances.
#:
#: Reads are defensive (``getattr`` with a ``None`` default): a caller may pass
#: a bare runtime for tests, in which case the dedicated runtime falls back to
#: the frozen defaults its constructor supplies.
def _shared_lifecycle_services(shared_runtime: Any) -> Dict[str, Any]:
    """Extract the shared services read-only from the application runtime."""
    action_gate = getattr(shared_runtime, "action_gate", None)
    verification_gate = getattr(shared_runtime, "verification_gate", None)
    return {
        "checkpoint_repo": getattr(shared_runtime, "checkpoint_repo", None),
        "rrm_service": getattr(shared_runtime, "resource_manager", None),
        "dispatch_guard": getattr(shared_runtime, "dispatch_guard", None),
        "mission_engine": getattr(shared_runtime, "mission_engine", None),
        "mission_record_store": getattr(
            shared_runtime, "_mission_record_store", None
        ),
        "constitution": getattr(action_gate, "_constitution", None),
        "replay_policy": getattr(action_gate, "_replay_policy", None),
        "external_evidence_adapter": getattr(
            verification_gate, "_external_adapter", None
        ),
    }


def build_dedicated_runtime(
    shared_runtime: Any, executor: NativeCreateTestFileActionExecutor
) -> Any:
    """Construct an UNPUBLISHED dedicated ``MissionRuntime`` with ``executor``
    bound AT CONSTRUCTION.

    Uses only the frozen ``MissionRuntime`` public constructor. The dedicated
    runtime shares the SAME durable lifecycle services as ``shared_runtime``
    (checkpoint_repo, dispatch_guard, mission_record_store, RRM service,
    mission engine, constitution, replay policy, external evidence adapter) but
    gets its own instance state and its OWN executor. It is returned to the
    caller only; it is never stored on the shared runtime, in a module global,
    or in any registry.
    """
    from intent_kernel.runtime.mission_runtime import MissionRuntime

    services = _shared_lifecycle_services(shared_runtime)
    return MissionRuntime(
        executor=executor,
        checkpoint_repo=services["checkpoint_repo"],
        rrm_service=services["rrm_service"],
        constitution=services["constitution"],
        mission_engine=services["mission_engine"],
        external_evidence_adapter=services["external_evidence_adapter"],
        dispatch_guard=services["dispatch_guard"],
        replay_policy=services["replay_policy"],
        mission_record_store=services["mission_record_store"],
    )


async def run_bound_dispatch(
    *,
    mission_runtime: Any,
    authority: Any,
    authorized_root: Any,
    target_name: str,
    content: bytes,
    run: Any,
    expected_root_identity: Optional[str] = None,
    now_provider: Any = None,
) -> Dict[str, Any]:
    """Serialize, construct a dedicated runtime, run one dispatch, discard it.

    ``run(mission_runtime)`` performs the governed dispatch. It receives the
    DEDICATED runtime (never the shared one), whose ``executor`` is the native
    executor bound at construction. The shared ``mission_runtime`` object is
    never read for its executor and is NEVER written.

    Exclusion is established on BOTH boundaries (TP-02D-R1, retained in R4):
      * a per-``(runtime, running-loop)`` async lock serializes tasks on one
        event loop without ever binding a lock across loops;
      * a per-runtime ``threading.Lock`` held across the dispatch excludes
        other threads and other event loops for the whole critical section.
    """
    runtime_lock = _runtime_lock(mission_runtime)
    async with _loop_lock(mission_runtime):
        executor = build_native_executor(
            authority=authority,
            authorized_root=authorized_root,
            target_name=target_name,
            content=content,
            expected_root_identity=expected_root_identity,
            now_provider=now_provider,
        )
        acquired = runtime_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS)
        if not acquired:
            executor.close()
            raise PreviewSelectionDenied("dispatch-lock-timeout")
        try:
            # Construction-time binding. The dedicated runtime is local to this
            # authorized dispatch and is not published anywhere.
            dedicated_runtime = build_dedicated_runtime(mission_runtime, executor)
            outcome = await run(dedicated_runtime)
        finally:
            runtime_lock.release()
            try:
                executor.close()
            except Exception:
                pass
        return {
            "outcome": outcome,
            "effect_calls": executor.effect_calls,
            "denials": list(executor.denials),
            "root_identity": _root_identity_of(executor),
        }


def _root_identity_of(executor: Any) -> Optional[str]:
    """Best-effort stable root identity for the evidence envelope."""
    getter = getattr(executor, "_root_identity_str", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return getattr(executor, "_root_identity", None)
