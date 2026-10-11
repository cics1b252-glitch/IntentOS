"""FRONT-TP-02B/C: controlled ProductBridge preview integration tests.

GATE B: the selector's refusals.
GATE C: one end-to-end governed dispatch with independent host observation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileDenied,
    CreateTestFileAuthority,
    LocalFilesystemObserver,
    sha256_bytes,
)
from intent_kernel.adapters.preview_selection import (   # noqa: F401
    build_native_executor as _build_native_executor,
    PreviewSelectionDenied,
    run_bound_dispatch as _run_bound_dispatch,
    validate_established,
)
from intent_kernel.mission.intent_authority import IntentAuthorityError
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    establish_intent_authority_from_grant,
    propose_intent_authority,
)
from intent_kernel.runtime.executor_port import InMemoryActionExecutor
from intent_kernel.runtime.models import ActionContract

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"tp02-governed-preview-payload\n"
CLOCK = lambda: NOW  # noqa: E731


def _iso(d: int = 0) -> str:
    return (NOW + timedelta(seconds=d)).isoformat()


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "preview-root"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _propose(root: Path, *, capabilities=(CAPABILITY,), operations=(OPERATION,),
             valid_until=None):
    return propose_intent_authority(
        allow_capabilities=capabilities,
        allowed_operations=operations,
        target_scope=(str(root),),
        max_risk_level="low",
        max_side_effect="LOCAL_REVERSIBLE",
        require_verification=True,
        valid_from=_iso(-60),
        valid_until=valid_until or _iso(3600),
    )


def _grant(proposal):
    return approve_intent_authority(
        proposal,
        authority_source_type="user_explicit",
        authority_source_identity="tp02",
        approved_at=_iso(-30),
    )


def _established(root: Path, **kw):
    """Authority through the EXISTING legitimate approval chain."""
    return establish_intent_authority_from_grant(
        _grant(_propose(root, **kw)), now_iso=NOW.isoformat()
    )


def _contract(op=OPERATION, content=CONTENT):
    contract = ActionContract(
        action_id="n1", capability=CAPABILITY, action_type=op,
        idempotency_key="tp02",
    )
    contract.inputs_reference = {"path": "effect.txt",
                                 "content": content.decode()}
    return contract


def _grant_for(root, authority):
    return CreateTestFileAuthority(
        authorized_root=root, authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority, now_provider=CLOCK,
    )


class _FakeRuntime:
    def __init__(self):
        self.executor = InMemoryActionExecutor()


# --- GATE B: refusals -------------------------------------------------------
def test_b01_default_executor_is_inmemory(tmp_path):
    """TP-02D-R1: the public unsynchronized binder is GONE from the API.

    The supported integration exposes only ``run_bound_dispatch``. Attempting
    to reach the old entry point must fail at attribute lookup, so an
    unsynchronized substitution path no longer exists to be called.
    """
    import intent_kernel.adapters.preview_selection as sel

    assert not hasattr(sel, "bind_executor_for_request")
    rt = _FakeRuntime()
    assert isinstance(rt.executor, InMemoryActionExecutor)


def test_b02_mutation_binder_is_retired_and_shared_runtime_untouched(tmp_path):
    """TP-02D-R4: the shared-runtime mutation binder is GONE.

    No API assigns ``mission_runtime.executor`` any more. The supported path
    constructs an unpublished dedicated runtime instead, so the shared
    runtime's executor identity is preserved across a whole real dispatch.
    """
    import intent_kernel.adapters.preview_selection as sel

    assert not hasattr(sel, "_bind_executor_held")
    assert not hasattr(sel, "bind_executor_for_request")

    root = _root(tmp_path)
    authority = _established(root)
    rt = _FakeRuntime()
    original = rt.executor

    async def run(runtime):
        # ``run`` receives the DEDICATED runtime, never the shared one.
        assert runtime is not rt
        assert runtime.executor is not original
        return await runtime.executor.execute(_contract())

    asyncio.run(_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="effect.txt", content=CONTENT, run=run, now_provider=CLOCK))
    assert rt.executor is original
    assert isinstance(rt.executor, InMemoryActionExecutor)


def test_b02b_shared_runtime_untouched_even_on_failure(tmp_path):
    rt = _FakeRuntime()
    original = rt.executor
    root = _root(tmp_path)
    authority = _established(root)

    async def boom(runtime):
        raise RuntimeError("dispatch exploded")

    with pytest.raises(RuntimeError):
        asyncio.run(_dispatch(
            mission_runtime=rt, authority=authority, authorized_root=root,
            target_name="boom.txt", content=CONTENT, run=boom, now_provider=CLOCK))
    assert rt.executor is original
    assert isinstance(rt.executor, InMemoryActionExecutor)


def test_b03_missing_authority_denied(tmp_path):
    root = _root(tmp_path)
    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=None, authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert exc.value.code == "authority-type-invalid"
    assert not (root / "effect.txt").exists()


def test_b04_forged_authority_object_denied(tmp_path):
    root = _root(tmp_path)

    class Forged:
        ceiling = IntentCeiling(allow_capabilities=(CAPABILITY,))
        authority_digest = "0" * 64

        def compute_authority_digest(self):
            return "1" * 64

    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=Forged(), authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert exc.value.code == "authority-type-invalid"
    assert not (root / "effect.txt").exists()


def test_b05_tampered_authority_digest_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    object.__setattr__(authority, "authority_digest", "f" * 64)
    with pytest.raises(PreviewSelectionDenied) as exc:
        validate_established(authority)
    assert exc.value.code == "authority-digest-invalid"
    assert not (root / "effect.txt").exists()


def test_b06_capability_not_in_ceiling_denied(tmp_path):
    root = _root(tmp_path)
    authority = establish_intent_authority_from_grant(
        _grant(_propose(root, capabilities=("some.other.capability",))),
        now_iso=NOW.isoformat())
    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=authority, authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert exc.value.code == "capability-escalation"
    assert not (root / "effect.txt").exists()


def test_b07_operation_not_in_ceiling_denied(tmp_path):
    root = _root(tmp_path)
    authority = establish_intent_authority_from_grant(
        _grant(_propose(root, operations=("READ",))), now_iso=NOW.isoformat())
    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=authority, authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert exc.value.code == "operation-escalation"
    assert not (root / "effect.txt").exists()


def test_b08_target_outside_approved_scope_denied(tmp_path):
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    authority = _established(root)
    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=authority, authorized_root=outside,
                              target_name="escape.txt", content=CONTENT)
    assert exc.value.code in ("target-escape", "target-not-in-approved-scope")
    assert not (outside / "escape.txt").exists()


def test_b09_ambiguous_target_name_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    for bad in ("../escape.txt", "sub/child.txt", "", "a\\b.txt"):
        with pytest.raises(PreviewSelectionDenied) as exc:
            _build(authority=authority, authorized_root=root,
                                  target_name=bad, content=CONTENT)
        assert exc.value.code == "target-name-invalid"
    assert list(root.iterdir()) == []


def test_b10_unsupported_platform_denied_no_fallback(tmp_path, monkeypatch):
    root = _root(tmp_path)
    authority = _established(root)
    import intent_kernel.adapters.preview_selection as sel
    monkeypatch.setattr(sel, "platform_capabilities",
                        lambda: {"platform": "fake", "preventive": False})
    with pytest.raises(PreviewSelectionDenied) as exc:
        _build(authority=authority, authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert exc.value.code == "native-containment-unsupported"
    assert not (root / "effect.txt").exists()


def test_b11_expired_authority_refused_at_establishment(tmp_path):
    """Expired authority is stronger than denied: it can never be established."""
    root = _root(tmp_path)
    with pytest.raises(IntentAuthorityError) as exc:
        _established(root, valid_until=_iso(-1))
    assert "expired" in str(exc.value).lower()
    assert not (root / "effect.txt").exists()


def test_b12_revoked_authority_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    ex = _build(authority=authority, authorized_root=root,
                               target_name="effect.txt", content=CONTENT)
    ex._native._grant.revoked = True
    # Revocation is re-proven at EFFECT time inside the authority chain. The
    # port reports a non-effect receipt; the filesystem proves the truth.
    receipt = asyncio.run(ex.execute(_contract()))
    assert receipt["effect_occurred"] is False
    assert ex.effect_calls == 0
    assert not (root / "effect.txt").exists()


# --- GATE C: end-to-end governed dispatch ----------------------------------
def test_c01_authorized_dispatch_performs_real_effect_and_is_observed(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _FakeRuntime()

    async def run(runtime):
        return await runtime.executor.execute(_contract())

    envelope = asyncio.run(_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="effect.txt", content=CONTENT, run=run,
        now_provider=CLOCK))

    assert envelope["effect_calls"] == 1
    assert (root / "effect.txt").read_bytes() == CONTENT
    # Independent observation - not the executor's own report.
    observation = LocalFilesystemObserver(_grant_for(root, authority)).observe()
    assert observation.exists is True
    assert observation.matches_authorized is True
    assert observation.observed_sha256 == sha256_bytes(CONTENT)
    assert isinstance(rt.executor, InMemoryActionExecutor)
    assert sorted(p.name for p in root.iterdir()) == ["effect.txt"]


def test_c02_duplicate_execution_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _FakeRuntime()

    async def run(runtime):
        first = await runtime.executor.execute(_contract())
        second = await runtime.executor.execute(_contract())
        return first, second

    envelope = asyncio.run(_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="effect.txt", content=CONTENT, run=run,
        now_provider=CLOCK))
    first, second = envelope["outcome"]
    assert first["effect_occurred"] is True
    assert second["effect_occurred"] is False
    assert envelope["effect_calls"] == 1
    assert (root / "effect.txt").read_bytes() == CONTENT


def test_c03_changed_content_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _FakeRuntime()

    async def run(runtime):
        return await runtime.executor.execute(_contract(content=b"tampered"))

    envelope = asyncio.run(_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="effect.txt", content=CONTENT, run=run,
        now_provider=CLOCK))
    assert envelope["outcome"]["effect_occurred"] is False
    assert envelope["effect_calls"] == 0
    assert not (root / "effect.txt").exists()


def test_c04_wrong_operation_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    rt = _FakeRuntime()

    async def run(runtime):
        return await runtime.executor.execute(_contract(op="DELETE_ALL"))

    with pytest.raises(CreateTestFileDenied):
        asyncio.run(_dispatch(
            mission_runtime=rt, authority=authority, authorized_root=root,
            target_name="effect.txt", content=CONTENT, run=run,
            now_provider=CLOCK))
    assert not (root / "effect.txt").exists()
    assert isinstance(rt.executor, InMemoryActionExecutor)



# --- TP-04F: real trusted-approval tokens (NO stubbing, NO bypass) ---------
# The previous autouse fixture stubbed require_trusted_approval outright. That
# is GONE. These wrappers do exactly what a LOCAL OPERATOR does: register a
# real, single-use approval for the authority digest in hand and hand the real
# token to the selector. Refusal semantics are exercised for real; the genuine
# fail-closed path is asserted in tests/test_tp04d_trust_boundary.py.

@pytest.fixture(autouse=True)
def _isolated_approval_registry():
    from intent_kernel.preview.trusted_approval import LOCAL_APPROVALS

    LOCAL_APPROVALS._tokens.clear()
    try:
        yield LOCAL_APPROVALS
    finally:
        LOCAL_APPROVALS._tokens.clear()


def _mint(authority):
    """Operator action: approve this EXACT authority digest, once."""
    from intent_kernel.preview.trusted_approval import register_local_approval

    return register_local_approval(
        authority.authority_digest, now=NOW,
    ).token


def _build(*args, **kwargs):
    """build_native_executor with a REAL operator-minted approval.

    Approval and authority MUST be judged by the same clock, so the frozen
    test clock is the default unless a test explicitly overrides it.
    """
    authority = kwargs.get("authority")
    if kwargs.get("approval_token") is None and authority is not None:
        kwargs["approval_token"] = _mint(authority)
    if kwargs.get("now_provider") is None:
        kwargs["now_provider"] = lambda: NOW
    return _build_native_executor(*args, **kwargs)


def _dispatch(**kwargs):
    """run_bound_dispatch with a REAL operator-minted approval."""
    authority = kwargs.get("authority")
    if kwargs.get("approval_token") is None and authority is not None:
        kwargs["approval_token"] = _mint(authority)
    if kwargs.get("now_provider") is None:
        kwargs["now_provider"] = lambda: NOW
    return _run_bound_dispatch(**kwargs)
