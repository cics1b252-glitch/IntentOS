"""TP-09V/W/X: productive grounded observation + adversarial gate.

Drives the REAL ProductBridge native governed effect and asserts the additive
grounded observation is correctly bound. All execution-authority denial paths
are asserted to perform ZERO host effect.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    sha256_bytes,
)
from intent_kernel.adapters.grounded_observation import (
    GroundedFilesystemObserver,
    GroundedObservation,
    GroundingError,
    is_fresh,
)
from intent_kernel.mission.grounded_semantic_evidence import ground_semantic_evidence
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    propose_intent_authority,
)
from intent_kernel.preview.trusted_approval import register_local_approval
from intent_kernel.runtime.executor_port import InMemoryActionExecutor

NOW = "2026-10-03T00:00:00+00:00"
MESSAGE = "Crie um arquivo de teste governado."
CONTENT = "tp09x-governed-native-content\n"


@pytest.fixture(autouse=True)
def _restore_native_quantity_applicability():
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY
    registry = DEFAULT_QUANTITY_APPLICABILITY
    had = registry.is_declared(OPERATION)
    yield
    if not had:
        registry._by_operation.pop(OPERATION, None)


def _bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from product_bridge import ProductBridge
    return ProductBridge()


def _proposal(root, *, capabilities=(CAPABILITY,), operations=(OPERATION,),
              targets=None, risk="low", side_effect="LOCAL_REVERSIBLE",
              verification=True, valid_from=None, valid_until=None):
    scope = targets if targets is not None else (str(root), CAPABILITY)
    now = datetime.now(timezone.utc)
    if valid_until is None:
        valid_until = (now + timedelta(hours=1)).isoformat()
    if valid_from is None:
        try:
            vu = datetime.fromisoformat(valid_until)
        except ValueError:
            vu = now + timedelta(hours=1)
        valid_from = (vu - timedelta(hours=1)).isoformat()
    return propose_intent_authority(
        allow_capabilities=tuple(capabilities),
        allowed_operations=tuple(operations),
        target_scope=tuple(scope),
        max_risk_level=risk,
        max_side_effect=side_effect,
        require_verification=verification,
        valid_from=valid_from,
        valid_until=valid_until,
        rationale="tp09x",
    )


def _grant(root, *, approved_at=NOW, **kw):
    return approve_intent_authority(
        _proposal(root, **kw),
        authority_source_type="user_explicit",
        authority_source_identity="tp09x",
        approved_at=approved_at,
    ).to_dict()


def _request(root, *, grant, target_name="tp09x_effect.txt", content=CONTENT,
             digest=None):
    bounded = {
        "authorized_root": str(root), "target_name": target_name,
        "content": content,
        "content_digest": digest if digest is not None
        else sha256_bytes(content.encode("utf-8")),
    }
    request = {"action": "chat", "message": MESSAGE,
               "authorized_permissions": [], "create_test_file": bounded}
    if grant is not None:
        request["intent_authority_grant"] = grant
    return request


async def _operator_dispatch(bridge, request, *, token=None):
    if token is None:
        token = register_local_approval(
            bridge.propose_native_authority(request)).token
    return await bridge.dispatch_operator_approved(request, approval_token=token)


def _workspace(tmp_path):
    root = tmp_path / "ws" / "root"
    root.mkdir(parents=True)
    return root


# ============================================================ productive path

@pytest.mark.asyncio
async def test_x01_real_host_effect_and_grounded_present(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert response["execution_mode"] == "MISSION"
    assert response["executor_effect_calls"] == 1
    assert (root / "tp09x_effect.txt").read_bytes() == CONTENT.encode("utf-8")
    g = response["grounded_observation"]
    assert g["available"] is True, g


@pytest.mark.asyncio
async def test_x02_independent_observation_observer_origin(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    g = response["grounded_observation"]
    assert g["observed_at"]  # stamped by the observer's own clock
    assert g["record_digest"]
    assert "observer-origin" in g["scope"]
    assert "NOT unique execution identity" in g["scope"]


@pytest.mark.asyncio
async def test_x03_correct_mission_binding(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert response["grounded_observation"]["mission_id"] == response["mission_id"]


@pytest.mark.asyncio
async def test_x04_correct_action_binding(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert response["grounded_observation"]["action_id"]


@pytest.mark.asyncio
async def test_x05_correct_authorized_target(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert response["grounded_observation"]["authorized_target"] == \
        str(root / "tp09x_effect.txt")


@pytest.mark.asyncio
async def test_x06_correct_expected_content_digest(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    g = response["grounded_observation"]
    assert g["observed_sha256"] == sha256_bytes(CONTENT.encode("utf-8"))
    assert g["content_matches"] is True


@pytest.mark.asyncio
async def test_x07_durable_gate_proof_binding(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    response = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    g = response["grounded_observation"]
    assert g["binding"] == "mission+action+authorized-target+durable-proof"
    assert g["record_digest"]


# ============================================================ adversarial

def _grant_obj(tmp_path, *, create=True):
    from intent_kernel.adapters.local_filesystem import CreateTestFileAuthority
    from intent_kernel.mission.intent_ceiling import IntentCeiling
    from intent_kernel.mission.intent_authority import establish_intent_authority
    root = tmp_path / "r"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "e.txt"
    content = b"x"
    if create:
        target.write_bytes(content)
    authority = establish_intent_authority(
        ceiling=IntentCeiling(
            allow_capabilities=(CAPABILITY,), allowed_operations=(OPERATION,),
            target_scope=(str(root),), max_risk_level="low",
            max_side_effect="LOCAL_REVERSIBLE", require_verification=True,
            valid_from=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            valid_until=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        ),
        source_type="user_explicit", source_identity="x",
        established_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        now_iso=datetime.now(timezone.utc).isoformat(),
    )
    return CreateTestFileAuthority(
        authorized_root=root, authorized_target=target,
        expected_content_sha256=sha256_bytes(content), authority=authority)


PROOF = "p" * 64
MISSION = "m1"
ACTION = "a1"


def test_x08_missing_gate_proof(tmp_path):
    with pytest.raises(GroundingError) as e:
        GroundedFilesystemObserver(_grant_obj(tmp_path), MISSION, ACTION, "")
    assert e.value.code == "missing-gate-proof"


def test_x09_wrong_mission(tmp_path):
    g = _grant_obj(tmp_path)
    obs = GroundedFilesystemObserver(g, MISSION, ACTION, PROOF).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id="other", action_id=ACTION,
            expected_target=obs.authorized_target,
            expected_content_sha256=obs.expected_content_sha256)
    assert e.value.code == "cross-mission"


def test_x10_wrong_action(tmp_path):
    g = _grant_obj(tmp_path)
    obs = GroundedFilesystemObserver(g, MISSION, ACTION, PROOF).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id="other",
            expected_target=obs.authorized_target,
            expected_content_sha256=obs.expected_content_sha256)
    assert e.value.code == "cross-action"


def test_x11_wrong_target(tmp_path):
    g = _grant_obj(tmp_path)
    obs = GroundedFilesystemObserver(g, MISSION, ACTION, PROOF).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id=ACTION,
            expected_target=str(tmp_path / "other.txt"),
            expected_content_sha256=obs.expected_content_sha256)
    assert e.value.code == "wrong-target"


def test_x12_changed_observed_content(tmp_path):
    g = _grant_obj(tmp_path)
    obs = GroundedFilesystemObserver(g, MISSION, ACTION, PROOF).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id=ACTION,
            expected_target=obs.authorized_target,
            expected_content_sha256="f" * 64)
    assert e.value.code == "wrong-content-spec"


def test_x13_forged_caller_evidence(tmp_path):
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            {"mission_id": MISSION, "observed_sha256": "0" * 64},
            mission_id=MISSION, action_id=ACTION, expected_target="t",
            expected_content_sha256="0" * 64)
    assert e.value.code == "caller-authored-record"


def test_x14_stale_observation(tmp_path):
    g = _grant_obj(tmp_path)
    frozen = datetime.now(timezone.utc) - timedelta(seconds=999)
    obs = GroundedFilesystemObserver(
        g, MISSION, ACTION, PROOF, now_provider=lambda: frozen).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id=ACTION,
            expected_target=obs.authorized_target,
            expected_content_sha256=obs.expected_content_sha256,
            now=datetime.now(timezone.utc))
    assert e.value.code == "stale-observation"


def test_x15_clock_rollback(tmp_path):
    g = _grant_obj(tmp_path)
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    obs = GroundedFilesystemObserver(
        g, MISSION, ACTION, PROOF, now_provider=lambda: future).observe()
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id=ACTION,
            expected_target=obs.authorized_target,
            expected_content_sha256=obs.expected_content_sha256,
            now=datetime.now(timezone.utc))
    assert e.value.code == "stale-observation"


def test_x16_observer_failure_not_fabricated(tmp_path):
    g = _grant_obj(tmp_path, create=False)  # file never created
    obs = GroundedFilesystemObserver(g, MISSION, ACTION, PROOF).observe()
    assert obs.exists is False
    with pytest.raises(GroundingError) as e:
        ground_semantic_evidence(
            obs, mission_id=MISSION, action_id=ACTION,
            expected_target=obs.authorized_target,
            expected_content_sha256=obs.expected_content_sha256)
    assert e.value.code == "effect-absent"


@pytest.mark.asyncio
async def test_x17_duplicate_dispatch_prevention(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    first = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert first["execution_mode"] == "MISSION"
    second = await _operator_dispatch(bridge, _request(root, grant=_grant(root)))
    assert second["ok"] is False
    assert (root / "tp09x_effect.txt").read_bytes() == CONTENT.encode("utf-8")


@pytest.mark.asyncio
async def test_x18_revoked_or_expired_authority_denied(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    bridge = _bridge(tmp_path, monkeypatch)
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    try:
        response = await _operator_dispatch(
            bridge, _request(root, grant=_grant(root, valid_until=past)))
    except Exception:
        response = None
    if response is not None:
        assert response["execution_mode"] == "FAILED"
        assert response["executor_effect_calls"] == 0
    # Fail-closed either way: no host effect whatsoever.
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_x19_legacy_native_effect_compatibility(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path, monkeypatch)
    shared = bridge.components.mission_runtime
    original = shared.executor
    assert isinstance(original, InMemoryActionExecutor)
    turn = await bridge.conversation_service.analyze_turn(
        "Crie e envie um e-mail.", project_id="GLOBAL")
    assert turn is not None
    assert shared.executor is original
    assert isinstance(shared.executor, InMemoryActionExecutor)


def test_x20_preview_harness_compatibility():
    import intent_kernel.preview.local_harness as lh
    assert "LocalFilesystemObserver" in inspect.getsource(lh)


def test_x21_no_semantic_completion_wiring():
    src = inspect.getsource(
        __import__("intent_kernel.runtime.mission_runtime", fromlist=["x"]))
    for token in ("grounded_observation", "grounded_semantic_evidence",
                  "ground_semantic_evidence", "TrustedSemanticEvaluator"):
        assert token not in src


def test_x22_frozen_core_integrity():
    import intent_kernel.mission.delegation as d
    import intent_kernel.mission.dispatch_guard as g
    import intent_kernel.orchestration.execution as x
    for mod in (d, g, x):
        src = inspect.getsource(mod)
        assert "grounded_observation" not in src
        assert "grounded_semantic_evidence" not in src
