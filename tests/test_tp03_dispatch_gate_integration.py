"""TP-03B/C — governed native real-effect route through the REAL ProductBridge.

The native CREATE_TEST_FILE effect is entered ONLY through an explicit bounded
``create_test_file`` request plus an explicit approved ``intent_authority_grant``
transported on a real ``bridge.dispatch`` chat call. The message text never
selects the effect, and no caller-supplied executor is ever accepted.

Chain exercised (all real, pre-existing mechanisms):

    ProductBridge.dispatch -> _chat (explicit bounded recognition)
        -> _run_native_governed_effect
            -> MissionService.create_started        (MissionEngine identity)
            -> Constitution.evaluate("mission.plan")
            -> establish_intent_authority_from_grant (J1.4)
            -> scope narrowing (selector never approves)
            -> preview_selection.run_bound_dispatch
                -> MissionRuntime.create_instance   (real J1 anchor proof)
                -> MissionRuntime.run_mission
                    -> ActionGate -> ProductiveDispatchGuard.acquire
                    -> NativeCreateTestFileActionExecutor.execute
                    -> VerificationGate.evaluate_node (STRUCTURAL)
            -> NativeFilesystemObserver.observe     (independent host read)

GATE B: the positive path reaches canonical VERIFIED_SUCCESS with exactly one
real host effect, and the shared application runtime is never mutated.
GATE C: the fail-closed denial matrix produces ZERO unauthorized host effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    sha256_bytes,
)
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    propose_intent_authority,
)
from intent_kernel.preview.trusted_approval import register_local_approval
from intent_kernel.runtime.executor_port import InMemoryActionExecutor

NOW = "2026-10-03T00:00:00+00:00"
MESSAGE = "Crie um arquivo de teste governado."
CONTENT = "tp03-governed-native-content\n"


@pytest.fixture(autouse=True)
def _restore_native_quantity_applicability():
    """The native route declares CREATE_TEST_FILE lazily; restore the global.

    Importing ``product_bridge`` has NO global side effect. Only an actual
    native dispatch declares the operation. This fixture guarantees the
    process-wide registry is restored to its pre-test state so that suites
    asserting the canonical "undeclared" invariant stay isolated.
    """
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    registry = DEFAULT_QUANTITY_APPLICABILITY
    had = registry.is_declared(OPERATION)
    yield
    if not had:
        registry._by_operation.pop(OPERATION, None)


# ---------------------------------------------------------------------------
# Builders (mirror the R7 live-bridge pattern: no standalone bootstrap)
# ---------------------------------------------------------------------------

def _bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from product_bridge import ProductBridge

    return ProductBridge()


def _proposal(root, *, capabilities=(CAPABILITY,), operations=(OPERATION,),
              targets=None, risk="low", side_effect="LOCAL_REVERSIBLE",
              verification=True, valid_until=None):
    scope = targets if targets is not None else (str(root), CAPABILITY)
    kwargs = {}
    if valid_until is not None:
        kwargs["valid_until"] = valid_until
    return propose_intent_authority(
        allow_capabilities=tuple(capabilities),
        allowed_operations=tuple(operations),
        target_scope=tuple(scope),
        max_risk_level=risk,
        max_side_effect=side_effect,
        require_verification=verification,
        rationale="tp03 native route",
        **kwargs,
    )


def _grant(root, *, approved_at=NOW, **proposal_kw):
    return approve_intent_authority(
        _proposal(root, **proposal_kw),
        authority_source_type="user_explicit",
        authority_source_identity="tp03",
        approved_at=approved_at,
    ).to_dict()


def _request(root, *, grant, target_name="tp03_effect.txt", content=CONTENT,
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


async def _operator_dispatch(bridge, request, *, token=None):
    """TP-08F-R1: drive the native route through the trusted OPERATOR entry.

    A trusted local operator approves the EXACT authority digest and passes the
    single-use token directly to ``dispatch_operator_approved``. The token is
    never placed in the request/context, so the plain HTTP ``dispatch`` path
    cannot reach the native executor.
    """
    if token is None:
        digest = bridge.propose_native_authority(request)
        token = register_local_approval(digest).token
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
# GATE B: positive real effect + isolation + default-path preservation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tp03_b_positive_native_governed_effect(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    outside = workspace / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched")

    bridge = _bridge(tmp_path, monkeypatch)
    shared = bridge.components.mission_runtime
    original_executor = shared.executor
    assert isinstance(original_executor, InMemoryActionExecutor)

    response = await _operator_dispatch(
        bridge, _request(root, grant=_grant(root)))

    # --- canonical product outcome ---
    assert response["execution_mode"] == "MISSION"
    assert response["status"] == "COMPLETED"
    assert response["runtime_status"] == "COMPLETED"
    assert response["verification_status"] == "VERIFIED_SUCCESS"
    assert response["executor_effect_calls"] == 1
    assert response["executor_denials"] == []
    assert response["mission_id"]

    # --- independent host observation (evidence, not trust) ---
    hvs = response["host_verified_state"]
    assert hvs["observed"] is True
    assert hvs["exists"] is True
    assert hvs["matches_authorized"] is True
    assert hvs["identity_stable"] is True
    assert hvs["observed_sha256"] == sha256_bytes(CONTENT.encode("utf-8"))

    target = root / "tp03_effect.txt"
    assert target.read_bytes() == CONTENT.encode("utf-8")
    assert sorted(p.name for p in root.iterdir()) == ["tp03_effect.txt"]

    # --- no unauthorized host effect outside the authorized root ---
    assert sentinel.read_text() == "untouched"

    # --- shared application runtime is NEVER mutated ---
    assert shared.executor is original_executor
    assert isinstance(shared.executor, InMemoryActionExecutor)
    assert shared._instances == {}


@pytest.mark.asyncio
async def test_tp03_b_default_simulation_path_preserved(tmp_path, monkeypatch):
    """A non-native turn keeps the frozen InMemoryActionExecutor simulation path."""
    bridge = _bridge(tmp_path, monkeypatch)
    shared = bridge.components.mission_runtime
    original_executor = shared.executor

    turn = await bridge.conversation_service.analyze_turn(
        "Crie e envie um e-mail.", project_id="GLOBAL",
        authorized_permissions=["email.send"],
    )
    resolved = tuple(
        r.capability_id for r in getattr(turn.capability_decision, "requirements", ())
        if r.capability_id
    )
    grant = approve_intent_authority(
        propose_intent_authority(
            allow_capabilities=resolved or ("knowledge.search",),
            allowed_operations=("READ", "GENERATE", "SIMULATED"),
            target_scope=resolved or ("knowledge.search",),
            max_risk_level="low",
            max_side_effect="EXTERNAL_REVERSIBLE",
            require_verification=True,
            rationale="tp03 sim preservation",
        ),
        authority_source_type="user_explicit",
        authority_source_identity="tp03-sim",
        approved_at=NOW,
    ).to_dict()

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
        "intent_authority_grant": grant,
    })

    assert response["execution_mode"] == "MISSION"
    assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    # The controlled simulation path legitimately runs on the shared runtime;
    # what must NEVER change is the executor identity (it must stay InMemory,
    # never the native CREATE_TEST_FILE executor).
    assert shared.executor is original_executor
    assert isinstance(shared.executor, InMemoryActionExecutor)


# ---------------------------------------------------------------------------
# GATE C: fail-closed denial matrix (every case: ZERO unauthorized effect)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tp03_c_missing_grant_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(_request(root, grant=None))
    _assert_denied_zero_effect(
        response, root, code="missing_explicit_intent_authority_grant")


@pytest.mark.asyncio
async def test_tp03_c_forged_grant_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root)
    grant["approved_scope_digest"] = "0" * 64
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(
        response, root, code="invalid_intent_authority_grant")


@pytest.mark.asyncio
async def test_tp03_c_expired_grant_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(
        root,
        approved_at="2020-01-01T00:00:00+00:00",
        valid_until="2020-01-01T00:00:00+00:00",
    )
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(
        response, root, code="invalid_intent_authority_grant")


@pytest.mark.asyncio
async def test_tp03_c_capability_escalation_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root, capabilities=("knowledge.search",),
                   targets=(str(root), CAPABILITY))
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(response, root, code="capability-escalation")


@pytest.mark.asyncio
async def test_tp03_c_operation_escalation_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root, operations=("SIMULATED",))
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(response, root, code="operation-escalation")


@pytest.mark.asyncio
async def test_tp03_c_side_effect_escalation_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root, side_effect="NONE")
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(response, root, code="side-effect-escalation")


@pytest.mark.asyncio
async def test_tp03_c_root_not_in_target_scope_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    other = tmp_path / "ws" / "other"
    other.mkdir()
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root, targets=(str(other), CAPABILITY))
    response = await bridge.dispatch(_request(root, grant=grant))
    _assert_denied_zero_effect(response, root, code="root-not-in-approved-scope")


@pytest.mark.asyncio
async def test_tp03_c_content_substitution_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(
        _request(root, grant=_grant(root), digest="f" * 64)
    )
    _assert_denied_zero_effect(response, root, code="content-substitution")


@pytest.mark.asyncio
async def test_tp03_c_target_traversal_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(
        _request(root, grant=_grant(root), target_name="sub/dir.txt")
    )
    _assert_denied_zero_effect(response, root, code="target-name-invalid")


@pytest.mark.asyncio
async def test_tp03_c_incomplete_bounded_request_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(
        _request(root, grant=_grant(root), digest="")
    )
    _assert_denied_zero_effect(
        response, root, code="bounded-request-incomplete")


@pytest.mark.asyncio
async def test_tp03_c_unknown_native_field_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await bridge.dispatch(
        _request(root, grant=_grant(root),
                 extra={"executor": {"module": "attacker"}})
    )
    _assert_denied_zero_effect(response, root, code="unknown-native-field")


@pytest.mark.asyncio
async def test_tp03_c_duplicate_execution_denied(tmp_path, monkeypatch):
    root = (tmp_path / "ws" / "root")
    root.mkdir(parents=True)
    bridge = _bridge(tmp_path, monkeypatch)
    grant = _grant(root)

    first = await _operator_dispatch(bridge, _request(root, grant=grant))
    assert first["execution_mode"] == "MISSION"
    assert first["executor_effect_calls"] == 1

    second = await _operator_dispatch(bridge, _request(root, grant=grant))
    assert second["native_denied"] is True
    assert second["reason_code"] == "effect-not-verified"
    # Exactly one file exists and its content is the original authorized one.
    assert sorted(p.name for p in root.iterdir()) == ["tp03_effect.txt"]
    assert (root / "tp03_effect.txt").read_bytes() == CONTENT.encode("utf-8")
