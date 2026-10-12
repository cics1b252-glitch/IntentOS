"""TP-08F-R1 — trusted operator-mediated ProductBridge native approval.

The native CREATE_TEST_FILE route of the REAL ProductBridge is reachable ONLY
through an explicit, trusted LOCAL OPERATOR act, and NEVER through any input an
untrusted caller can influence (HTTP body/context, planner, provider, agent or
environment).

Operator flow (in-process only; never reachable over HTTP):

    digest = bridge.propose_native_authority(request)      # read-only proposal
    token  = register_local_approval(digest).token         # operator act, once
    resp   = await bridge.dispatch_operator_approved(request, approval_token=token)

The token is passed directly to a local method. It is never placed in the
request or ``context``. The plain HTTP entry ``bridge.dispatch(request)`` never
supplies a token, so the native route fails closed there.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import intent_kernel.adapters.preview_selection as sel
from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    sha256_bytes,
)
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    propose_intent_authority,
)
from intent_kernel.preview.trusted_approval import (
    LOCAL_APPROVALS,
    register_local_approval,
)
from intent_kernel.runtime.executor_port import InMemoryActionExecutor

APPROVED_AT = "2026-10-03T00:00:00+00:00"
MESSAGE = "Crie um arquivo de teste governado."
CONTENT = "tp08f-r1-governed-content\n"


@pytest.fixture(autouse=True)
def _restore_native_quantity_applicability():
    """Restore the lazy CREATE_TEST_FILE quantity declaration after each test."""
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    registry = DEFAULT_QUANTITY_APPLICABILITY
    had = registry.is_declared(OPERATION)
    yield
    if not had:
        registry._by_operation.pop(OPERATION, None)


@pytest.fixture(autouse=True)
def _clear_approval_registry():
    """No operator approval may leak between tests."""
    LOCAL_APPROVALS._tokens.clear()
    yield
    LOCAL_APPROVALS._tokens.clear()


def _bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from product_bridge import ProductBridge

    return ProductBridge()


def _grant(root, *, approved_at=APPROVED_AT, capabilities=(CAPABILITY,),
           operations=(OPERATION,), targets=None, valid_until=None):
    scope = targets if targets is not None else (str(root), CAPABILITY)
    kwargs = {}
    if valid_until is not None:
        kwargs["valid_until"] = valid_until
    proposal = propose_intent_authority(
        allow_capabilities=tuple(capabilities),
        allowed_operations=tuple(operations),
        target_scope=tuple(scope),
        max_risk_level="low",
        max_side_effect="LOCAL_REVERSIBLE",
        require_verification=True,
        rationale="tp08f-r1",
        **kwargs,
    )
    return approve_intent_authority(
        proposal,
        authority_source_type="user_explicit",
        authority_source_identity="tp08f-r1",
        approved_at=approved_at,
    ).to_dict()


def _request(root, *, grant, target_name="tp08f_effect.txt", content=CONTENT,
             digest=None, extra=None):
    bounded = {
        "authorized_root": str(root),
        "target_name": target_name,
        "content": content,
        "content_digest": (
            digest if digest is not None
            else sha256_bytes(content.encode("utf-8"))
        ),
    }
    if extra:
        bounded.update(extra)
    request = {
        "action": "chat",
        "message": MESSAGE,
        "authorized_permissions": [],
        "create_test_file": bounded,
    }
    if grant is not None:
        request["intent_authority_grant"] = grant
    return request


async def _approved(bridge, request, *, token=None):
    """Drive the native route through the trusted OPERATOR entry."""
    if token is None:
        token = register_local_approval(
            bridge.propose_native_authority(request)
        ).token
    return await bridge.dispatch_operator_approved(request, approval_token=token)


def _assert_denied_zero_effect(response, root, *, code=None, files=()):
    assert response["execution_mode"] == "FAILED"
    assert response["ok"] is False
    assert response["native_denied"] is True
    if code is not None:
        assert response["reason_code"] == code
    assert response["executor_effect_calls"] == 0
    assert sorted(p.name for p in Path(root).iterdir()) == sorted(files)


# ---------------------------------------------------------------------------
# 1. Explicit local operator approval -> exactly one verified real effect.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e01_operator_approval_one_verified_effect(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    outside = workspace / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched")

    bridge = _bridge(tmp_path, monkeypatch)
    shared = bridge.components.mission_runtime
    original = shared.executor
    assert isinstance(original, InMemoryActionExecutor)

    response = await _approved(bridge, _request(root, grant=_grant(root)))

    assert response["execution_mode"] == "MISSION"
    assert response["status"] == "COMPLETED"
    assert response["verification_status"] == "VERIFIED_SUCCESS"
    assert response["executor_effect_calls"] == 1
    assert response["executor_denials"] == []

    target = root / "tp08f_effect.txt"
    assert target.read_bytes() == CONTENT.encode("utf-8")
    assert sorted(p.name for p in root.iterdir()) == ["tp08f_effect.txt"]
    assert sentinel.read_text() == "untouched"

    assert shared.executor is original
    assert shared._instances == {}


# ---------------------------------------------------------------------------
# 2. No approval -> zero productive effects (plain HTTP entry).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e02_no_operator_approval_zero_effect(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(_request(root, grant=_grant(root)))
    _assert_denied_zero_effect(response, root)
    assert response["reason_code"].startswith("trusted-approval-refused")


# ---------------------------------------------------------------------------
# 3. Forged approval token -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e03_forged_token_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    response = await _approved(bridge, request, token="forged-token")
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 4. HTTP-provided token -> denied (never read from request/context).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e04_http_provided_token_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    real = register_local_approval(
        bridge.propose_native_authority(request)).token
    request["approval_token"] = real
    request["intent_authority_approval_token"] = real
    request["context"] = {
        "intent_authority_approval_token": real, "token": real,
    }
    response = await bridge.dispatch(request)
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 5. Wrong authority digest -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e05_wrong_authority_digest_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    wrong = register_local_approval("some-other-authority-digest").token
    response = await _approved(bridge, request, token=wrong)
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 6. Expired token -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e06_expired_token_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    digest = bridge.propose_native_authority(request)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = register_local_approval(digest, ttl_seconds=60, now=past).token
    response = await _approved(bridge, request, token=token)
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 7. Replayed token -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e07_replayed_token_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    digest = bridge.propose_native_authority(request)
    token = register_local_approval(digest).token
    first = await _approved(bridge, request, token=token)
    assert first["executor_effect_calls"] == 1
    second = await _approved(bridge, request, token=token)
    _assert_denied_zero_effect(second, root, files=["tp08f_effect.txt"])


# ---------------------------------------------------------------------------
# 8. Concurrent consumption -> at most one authorization.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e08_concurrent_consumption_at_most_one(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    token = register_local_approval(
        bridge.propose_native_authority(request)).token

    results = await asyncio.gather(
        _approved(bridge, dict(request), token=token),
        _approved(bridge, dict(request), token=token),
    )
    approved = [r for r in results if r["executor_effect_calls"] == 1]
    denied = [r for r in results if r.get("native_denied") is True]
    assert len(approved) == 1
    assert len(denied) == 1
    assert (root / "tp08f_effect.txt").read_bytes() == CONTENT.encode("utf-8")


# ---------------------------------------------------------------------------
# 9. Planner-originated approval -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e09_planner_originated_approval_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    real = register_local_approval(
        bridge.propose_native_authority(request)).token
    request["structured_intent"] = {"approval_token": real}
    request["planner_output"] = {"intent_authority_approval_token": real}
    response = await bridge.dispatch(request)
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 10. Provider-originated approval -> denied.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e10_provider_originated_approval_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    request = _request(root, grant=_grant(root))
    real = register_local_approval(
        bridge.propose_native_authority(request)).token
    request["provider_output"] = {"token": real}
    request["context"] = {"provider_approval_token": real}
    response = await bridge.dispatch(request)
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 11. Wrong target or operation -> denied (a valid token cannot escape scope).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e11_wrong_target_or_operation_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)

    traversal = await _approved(
        bridge, _request(root, grant=_grant(root), target_name="sub/dir.txt"))
    _assert_denied_zero_effect(traversal, root, code="target-name-invalid")

    substitution = await _approved(
        bridge, _request(root, grant=_grant(root),
                         extra={"executor": {"module": "attacker"}}))
    _assert_denied_zero_effect(
        substitution, root, code="unknown-native-field")


# ---------------------------------------------------------------------------
# 12. Revoked authority -> denied (re-proven at effect time).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e12_revoked_authority_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)

    real_build = sel.build_native_executor

    def _revoking_build(*args, **kwargs):
        executor = real_build(*args, **kwargs)
        executor._native._grant.revoked = True
        return executor

    monkeypatch.setattr(sel, "build_native_executor", _revoking_build)
    response = await _approved(bridge, _request(root, grant=_grant(root)))
    _assert_denied_zero_effect(response, root)


# ---------------------------------------------------------------------------
# 13. Independent host observation verifies the real effect.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e13_independent_observer_verifies_effect(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _approved(bridge, _request(root, grant=_grant(root)))

    assert response["verification_status"] == "VERIFIED_SUCCESS"
    hvs = response["host_verified_state"]
    assert hvs["observed"] is True
    assert hvs["exists"] is True
    assert hvs["matches_authorized"] is True
    assert hvs["observed_sha256"] == sha256_bytes(CONTENT.encode("utf-8"))
    # An independent re-read outside the kernel confirms the exact bytes.
    assert (root / "tp08f_effect.txt").read_bytes() == CONTENT.encode("utf-8")
