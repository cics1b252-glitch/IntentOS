"""TP-04D: adversarial validation of the trusted approval trust boundary.

Cases 1-8 exercise the ACTUAL HTTP ingress (``sanitize_context`` plus the
FastAPI request model), not just helper functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from intent_kernel.auth.api_key_auth import RESERVED_CONTEXT_KEYS, sanitize_context
from intent_kernel.preview.trusted_approval import (
    LOCAL_APPROVALS,
    TrustedApprovalError,
    register_local_approval,
    require_trusted_approval,
)

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"tp04d-governed-payload\n"
CLOCK = lambda: NOW  # noqa: E731


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "preview-root"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _established(root: Path):
    from tests.test_tp02_preview_integration import _established as _est
    return _est(root)


def _grant(root, authority, name="effect.txt"):
    from intent_kernel.adapters.local_filesystem import CreateTestFileAuthority
    return CreateTestFileAuthority(
        authorized_root=root, authorized_target=root / name,
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority, now_provider=CLOCK)


def _files(root: Path):
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


# --- 4/5/6: ingress must strip every caller-controlled approval field --------
@pytest.mark.parametrize("key", [
    "intent_authority_grant",
    "INTENT_AUTHORITY_GRANT",
    "intent_authority_approval",
    "intent_authority_approval_token",
    "_trusted_approval",
    "_preview_native_effect",
])
def test_d04_http_context_grant_fields_are_stripped(key):
    """Verified at the REAL ingress sanitizer."""
    assert key.lower() in {k.lower() for k in RESERVED_CONTEXT_KEYS}
    cleaned = sanitize_context({key: {"forged": True}, "harmless": 1})
    assert key not in cleaned
    assert cleaned == {"harmless": 1}


def test_d05_crafted_http_context_yields_no_authority(tmp_path):
    """A fully crafted request context cannot reach the grant transport."""
    forged = {
        "intent_authority_grant": {
            "ceiling": {"allow_capabilities": [CAPABILITY]},
            "approved_scope_digest": "0" * 64,
            "authority_source_type": "user_explicit",
            "authority_source_identity": "admin",
        },
        "_trusted_approval": True,
        "_preview_native_effect": True,
        "role": "admin",
    }
    cleaned = sanitize_context(dict(forged))
    assert "intent_authority_grant" not in cleaned
    assert "_trusted_approval" not in cleaned
    assert "_preview_native_effect" not in cleaned


def test_d06_desktop_context_forged_provenance_stripped():
    assert "intent_authority_grant" not in sanitize_context(
        {"intent_authority_grant": {"x": 1}})


# --- 1/2/3/8: grant alone, forged, replayed, cross-authority, no approval ---
def test_d01_forged_grant_with_matching_scope_digest_denied(tmp_path):
    """SCOPE_DIGEST != APPROVAL_AUTHENTICITY: a self-consistent grant is not
    approval. No trusted approval token -> refused before any effect."""
    root = _root(tmp_path)
    authority = _established(root)   # genuinely established, still unapproved
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(authority=authority, authorized_root=root,
                              target_name="effect.txt", content=CONTENT)
    assert "trusted-approval-refused:approval-token-missing" in exc.value.code
    assert _files(root) == []


def test_d02_replayed_approval_token_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    # First use succeeds.
    ex = build_native_executor(
        authority=authority, authorized_root=root, target_name="effect.txt",
        content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    ex.close()
    # Replay of the SAME token is refused.
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(
            authority=authority, authorized_root=root, target_name="effect.txt",
            content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    assert "trusted-approval-refused" in exc.value.code
    assert _files(root) == []


def test_d03_cross_identity_approval_denied(tmp_path):
    """An approval minted for authority A cannot authorise authority B."""
    root_a = _root(tmp_path / "a")
    root_b = _root(tmp_path / "b")
    auth_a = _established(root_a)
    auth_b = _established(root_b)
    approval_a = register_local_approval(auth_a.authority_digest, now=NOW)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(
            authority=auth_b, authorized_root=root_b, target_name="effect.txt",
            content=CONTENT, approval_token=approval_a.token)
    assert "trusted-approval-refused:approval-authority-mismatch" in exc.value.code
    assert _files(root_b) == []


def test_d08_unknown_forged_token_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(
            authority=authority, authorized_root=root, target_name="effect.txt",
            content=CONTENT, approval_token="not-a-real-token")
    assert "approval-token-unknown" in exc.value.code
    assert _files(root) == []


def test_d_expired_approval_token_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(
        authority.authority_digest, ttl_seconds=60,
        now=NOW - timedelta(hours=2))
    with pytest.raises(TrustedApprovalError) as exc:
        require_trusted_approval(approval.token, authority.authority_digest, now=NOW)
    assert exc.value.code == "approval-expired"
    assert _files(root) == []


# --- 9-13: authority constraints preserved WITH approval -------------------
def test_d09_expired_authority_denied(tmp_path):
    from tests.test_tp02_preview_integration import _grant, _propose
    from intent_kernel.mission.intent_grant import establish_intent_authority_from_grant
    root = _root(tmp_path)
    with pytest.raises(Exception):
        establish_intent_authority_from_grant(
            _grant(_propose(root, valid_until=_iso(-1))), now_iso=NOW.isoformat())
    assert _files(root) == []


def _iso(d):
    return (NOW + timedelta(seconds=d)).isoformat()


def test_d10_revoked_authority_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    ex = build_native_executor(
        authority=authority, authorized_root=root, target_name="effect.txt",
        content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    ex._native._grant.revoked = True

    import asyncio
    from intent_kernel.runtime.models import ActionContract
    c = ActionContract(action_id="n", capability=CAPABILITY, action_type=OPERATION,
                       idempotency_key="k")
    c.inputs_reference = {"path": "effect.txt", "content": CONTENT.decode()}
    receipt = asyncio.run(ex.execute(c))
    assert receipt["effect_occurred"] is False
    assert _files(root) == []


def test_d11_target_substitution_denied(tmp_path):
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(
            authority=authority, authorized_root=root,
            target_name="../escape.txt", content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    assert exc.value.code == "target-name-invalid"
    assert not (tmp_path / "escape.txt").exists()


def test_d12_content_substitution_denied(tmp_path):
    import asyncio
    from intent_kernel.runtime.models import ActionContract
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    ex = build_native_executor(
        authority=authority, authorized_root=root, target_name="effect.txt",
        content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    c = ActionContract(action_id="n", capability=CAPABILITY, action_type=OPERATION,
                       idempotency_key="k")
    c.inputs_reference = {"path": "effect.txt", "content": "tampered"}
    receipt = asyncio.run(ex.execute(c))
    assert receipt["effect_occurred"] is False
    assert _files(root) == []


def test_d13_operation_substitution_denied(tmp_path):
    import asyncio
    from intent_kernel.adapters.local_filesystem import CreateTestFileDenied
    from intent_kernel.runtime.models import ActionContract
    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    ex = build_native_executor(
        authority=authority, authorized_root=root, target_name="effect.txt",
        content=CONTENT, now_provider=CLOCK, approval_token=approval.token)
    c = ActionContract(action_id="n", capability=CAPABILITY,
                       action_type="DELETE_ALL", idempotency_key="k")
    c.inputs_reference = {"path": "effect.txt", "content": CONTENT.decode()}
    with pytest.raises(CreateTestFileDenied):
        asyncio.run(ex.execute(c))
    assert _files(root) == []


def test_d14_unsupported_capability_denied(tmp_path):
    """Even WITH a valid trusted approval, an authority whose ceiling does
    not contain the preview capability is refused. Approval cannot widen it."""
    from intent_kernel.mission.intent_grant import (
        establish_intent_authority_from_grant,
    )
    from tests.test_tp02_preview_integration import _grant, _propose

    root = _root(tmp_path)
    other = establish_intent_authority_from_grant(
        _grant(_propose(root, capabilities=("some.other.capability",))),
        now_iso=NOW.isoformat())
    # The operator may approve it; approval still cannot create capability.
    approval = register_local_approval(other.authority_digest, now=NOW)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(
            authority=other, authorized_root=root, target_name="effect.txt",
            content=CONTENT, now_provider=CLOCK,
            approval_token=approval.token)
    assert exc.value.code == "capability-escalation"
    assert _files(root) == []


# --- 15/16: trusted local harness positive effect + independent verification -
def test_d15_trusted_local_harness_executes(tmp_path):
    import asyncio
    from intent_kernel.runtime.executor_port import InMemoryActionExecutor
    from intent_kernel.runtime.models import ActionContract

    class RT:
        def __init__(self):
            self.executor = InMemoryActionExecutor()

    root = _root(tmp_path)
    authority = _established(root)
    approval = register_local_approval(authority.authority_digest, now=NOW)
    rt = RT()

    async def run(runtime):
        c = ActionContract(action_id="n", capability=CAPABILITY,
                           action_type=OPERATION, idempotency_key="k")
        c.inputs_reference = {"path": "effect.txt", "content": CONTENT.decode()}
        return await runtime.executor.execute(c)

    result = asyncio.run(run_bound_dispatch(
        mission_runtime=rt, authority=authority, authorized_root=root,
        target_name="effect.txt", content=CONTENT, run=run,
        now_provider=CLOCK, approval_token=approval.token))
    assert result["effect_calls"] == 1
    assert (root / "effect.txt").read_bytes() == CONTENT
    # 16. independent verification of the exact host effect
    obs = LocalFilesystemObserver(_grant(root, authority)).observe()
    assert obs.exists is True
    assert obs.matches_authorized is True
    assert obs.observed_sha256 == sha256_bytes(CONTENT)
    # default executor preserved, no simulation-to-production escalation
    assert isinstance(rt.executor, InMemoryActionExecutor)
    assert _files(root) == ["effect.txt"]


def test_registry_drains():
    before = LOCAL_APPROVALS.pending()
    approval = register_local_approval("digest-x", now=NOW)
    assert LOCAL_APPROVALS.pending() == before + 1
    require_trusted_approval(approval.token, "digest-x", now=NOW)
    assert LOCAL_APPROVALS.pending() == before


# --- TP-04F: approval semantics proved with REAL tokens, no stubs -----------
def test_f01_replay_of_real_token_denied(tmp_path):
    """Single-use is enforced on a genuinely issued token."""
    from intent_kernel.preview.trusted_approval import (
        TrustedApprovalError, require_trusted_approval,
    )

    root = _root(tmp_path)
    authority = _established(root)
    token = _mint(authority)
    # First consumption succeeds (real approval, real burn).
    require_trusted_approval(token, authority.authority_digest, now=NOW)
    # Replay is refused.
    with pytest.raises(TrustedApprovalError) as exc:
        require_trusted_approval(token, authority.authority_digest, now=NOW)
    assert exc.value.code == "approval-token-unknown"
    assert _files(root) == []


def test_f02_expiry_enforced_on_real_token(tmp_path):
    from datetime import timedelta
    from intent_kernel.preview.trusted_approval import (
        TrustedApprovalError, register_local_approval, require_trusted_approval,
    )

    root = _root(tmp_path)
    authority = _established(root)
    token = register_local_approval(
        authority.authority_digest, ttl_seconds=60,
        now=NOW - timedelta(hours=2)).token
    with pytest.raises(TrustedApprovalError) as exc:
        require_trusted_approval(token, authority.authority_digest, now=NOW)
    assert exc.value.code == "approval-expired"
    assert _files(root) == []


def test_f03_cross_authority_real_token_denied(tmp_path):
    from intent_kernel.preview.trusted_approval import (
        TrustedApprovalError, require_trusted_approval,
    )

    a = _root(tmp_path / "a")
    b = _root(tmp_path / "b")
    auth_a = _established(a)
    auth_b = _established(b)
    token = _mint(auth_a)
    with pytest.raises(TrustedApprovalError) as exc:
        require_trusted_approval(token, auth_b.authority_digest, now=NOW)
    assert exc.value.code == "approval-authority-mismatch"
    assert _files(b) == []


def test_f04_registry_is_isolated_between_tests(tmp_path):
    """The autouse fixture must leave no approvals behind."""
    from intent_kernel.preview.trusted_approval import LOCAL_APPROVALS

    root = _root(tmp_path)
    _mint(_established(root))
    assert LOCAL_APPROVALS.pending() >= 1


def test_f05_concurrent_consumption_authorizes_exactly_one(tmp_path):
    """Two threads race for ONE token: at most one may execute."""
    import threading as _t

    from intent_kernel.preview.trusted_approval import (
        TrustedApprovalError, require_trusted_approval,
    )

    root = _root(tmp_path)
    authority = _established(root)
    token = _mint(authority)
    granted: list = []

    def worker():
        try:
            require_trusted_approval(token, authority.authority_digest, now=NOW)
            granted.append(1)
        except TrustedApprovalError:
            granted.append(0)

    threads = [_t.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(granted) == 8
    assert sum(granted) == 1, "a single-use token must authorize ONE execution"
    assert _files(root) == []


def _mint(authority):
    """Operator action: approve this EXACT authority digest, once."""
    from intent_kernel.preview.trusted_approval import register_local_approval

    return register_local_approval(authority.authority_digest, now=NOW).token


@pytest.fixture(autouse=True)
def _isolated_approval_registry():
    from intent_kernel.preview.trusted_approval import LOCAL_APPROVALS

    LOCAL_APPROVALS._tokens.clear()
    try:
        yield LOCAL_APPROVALS
    finally:
        LOCAL_APPROVALS._tokens.clear()
