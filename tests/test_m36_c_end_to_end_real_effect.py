"""FRONT-M36-C: END-TO-END REAL EFFECT PROOF through the canonical path.

    MissionRuntime.run_mission
        -> ProductiveDispatchGuard.acquire   (durable attempt authority)
        -> NativeCreateTestFileActionExecutor.execute  (frozen ActionExecutorPort)
        -> NativeCreateTestFileExecutor        (effect-time authority re-proof)
        -> NativeContainment.create_exclusive  (PREVENTIVE handle-relative create)
        -> VerificationGate.evaluate_node      (durable gate proof)
        -> NativeFilesystemObserver            (independent host observation)

Demonstrates, in ONE governed execution, real native containment AND governed
dispatch: a real file is created under a disposable isolated workspace, a REAL
competing OS process tries to redirect it, and no effect escapes the authorized
directory object.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    CreateTestFileDenied,
    sha256_bytes,
)
from intent_kernel.adapters.native_containment import (
    NativeCreateTestFileActionExecutor,
    NativeFilesystemObserver,
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
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    RuntimeNodeState,
    VerificationStatus,
)

# Reuse the canonical lifecycle harness (real wiring, real store, real guard).
from tests.test_m32c_r2_lifecycle_proof import (  # noqa: F401
    _AllowConstitution,
    _components,
    _govern,
    _mission_store,
    _started_mission,
    CountingApp,
)

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"m36-real-native-governed-effect\n"

VERIFICATION_SCHEMA = {
    "type": "object",
    "required": ["effect_occurred", "digest", "path", "root_identity"],
    "properties": {
        "effect_occurred": {"type": "boolean", "const": True},
        "digest": {"type": "string"},
        "path": {"type": "string"},
        "root_identity": {"type": "string"},
    },
}


@pytest.fixture(autouse=True)
def _declare_create_test_file_applicability():
    """Positive NOT_APPLICABLE proof for CREATE_TEST_FILE, scoped + restored."""
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION)
    DEFAULT_QUANTITY_APPLICABILITY.declare(OPERATION, None)
    try:
        yield
    finally:
        DEFAULT_QUANTITY_APPLICABILITY._by_operation.pop(OPERATION, None)


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _authority(root: Path):
    return establish_intent_authority(
        ceiling=IntentCeiling(
            allow_capabilities=(CAPABILITY,),
            allowed_operations=(OPERATION,),
            target_scope=(str(root),),
            max_risk_level="low",
            max_side_effect="LOCAL_REVERSIBLE",
            require_verification=True,
            valid_from=_iso(-60),
            valid_until=_iso(3600),
        ),
        source_type="user_explicit",
        source_identity="m36-c",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )


def _grant(root: Path, authority):
    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )


def _node(path: str, content: str) -> RuntimeNode:
    contract = ActionContract(
        action_id="n1",
        capability=CAPABILITY,
        action_type=OPERATION,
        idempotency_key="m36-c-idem",
        verification_required=True,
        verification_type="STRUCTURAL",
        verification_schema=VERIFICATION_SCHEMA,
    )
    contract.inputs_reference = {"path": path, "content": content}
    return RuntimeNode(
        node_id="n1",
        capability=CAPABILITY,
        agent_id="ex-m36",
        action_contract=contract,
    )


def _bind(store, mid: str, node: RuntimeNode, authority) -> None:
    spec = spec_for_runtime_node(mid, node)
    ident = store.get_continuity_identity()
    definition = MissionDefinition(
        objective="m36 native governed effect",
        context={"k": "v"},
        intent_authority=authority,
    )
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition,
    )
    record = MissionRecord(
        mission_id=mid,
        installation_id=ident,
        revision=1,
        runtime_id="rt-m36",
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


def _environment(tmp_path: Path, store_name: str = "mstore-m36c"):
    components = _components(tmp_path, tmp_path / ".intent-os-m36c")
    app = CountingApp(capability=CAPABILITY)
    _govern(components, app)
    store = _mission_store(tmp_path, store_name)
    return components, store


async def _run_governed(
    components, store, mission_id, node, authority, executor, runtime_id="g-m36"
):
    guard = ProductiveDispatchGuard(MissionActionAuthority(store), store)
    runtime = MissionRuntime(
        executor=executor,
        constitution=_AllowConstitution(),
        dispatch_guard=guard,
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )
    instance = runtime.create_instance(
        str(mission_id), runtime_id, [node], intent_authority=authority,
    )
    await runtime.run_mission(instance.runtime_id)
    return runtime, instance


# ---------------------------------------------------------------------------
# E2E-1: real governed native effect + independent observation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_m36c_01_end_to_end_real_native_effect(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "m36root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = NativeCreateTestFileActionExecutor(grant)
    observer = NativeFilesystemObserver(grant)

    components, store = _environment(tmp_path)
    mission = await _started_mission(components, "m36c")
    node = _node("effect.txt", CONTENT.decode())
    _bind(store, str(mission.id), node, authority)

    runtime, instance = await _run_governed(
        components, store, mission.id, node, authority, executor
    )

    # --- governed runtime outcome ---
    assert node.state == RuntimeNodeState.SUCCEEDED
    assert node.verification_result == VerificationStatus.VERIFIED_SUCCESS
    assert executor.effect_calls == 1

    # --- durable dispatch + gate evidence ---
    data = store.load(str(mission.id))
    action = data["action_states"][spec_for_runtime_node(str(mission.id), node).action_id]
    assert action["state"] == ActionState.VERIFIED.value
    assert action.get("verification_proof_digest")
    assert executor.denials == []

    # --- real, independent observation of the host filesystem ---
    observation = observer.observe()
    assert observation["observed"] is True
    assert observation["exists"] is True
    assert observation["matches_authorized"] is True
    assert observation["identity_stable"] is True
    assert observation["observed_sha256"] == sha256_bytes(CONTENT)
    assert grant.authorized_target.read_bytes() == CONTENT

    # --- native root identity present in the result evidence ---
    result = node.result
    assert result["root_identity"]
    assert observation["root_identity"] == result["root_identity"]

    # --- no effect outside the authorized directory object ---
    assert sorted(p.name for p in root.iterdir()) == ["effect.txt"]
    executor.close()


# ---------------------------------------------------------------------------
# E2E-2: real competing OS process cannot redirect the governed effect
# ---------------------------------------------------------------------------
_HOSTILE_SCRIPT = r"""
import os, sys, time
root, outside, delay = sys.argv[1], sys.argv[2], float(sys.argv[3])
time.sleep(delay)
try:
    os.rename(root, root + "__moved")
    os.symlink(outside, root, target_is_directory=True)
    print("HOSTILE_WON")
except Exception as exc:
    print("HOSTILE_FAILED", exc)
"""


@pytest.mark.asyncio
async def test_m36c_02_competing_process_cannot_redirect_governed_effect(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "m36root"
    root.mkdir(parents=True)
    outside = workspace / "attacker"
    outside.mkdir()

    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    # Containment (and its pinned root handle) is established BEFORE the attack.
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c2")
    mission = await _started_mission(components, "m36c2")
    node = _node("effect.txt", CONTENT.decode())
    _bind(store, str(mission.id), node, authority)

    script = tmp_path / "hostile.py"
    script.write_text(_HOSTILE_SCRIPT)
    attacker = subprocess.Popen(
        [sys.executable, str(script), str(root), str(outside), "0.02"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        await _run_governed(components, store, mission.id, node, authority, executor)
    finally:
        attacker.communicate(timeout=30)

    # PREVENTION: the attacker's directory object received nothing.
    assert list(outside.iterdir()) == []
    assert not (outside / "effect.txt").exists()

    # The effect followed the AUTHORIZED directory object (wherever it is named).
    holder = root if (root / "effect.txt").exists() else workspace / "m36root__moved"
    assert (holder / "effect.txt").exists()
    assert (holder / "effect.txt").read_bytes() == CONTENT
    executor.close()


# ---------------------------------------------------------------------------
# E2E-3..: fail-closed matrix
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_m36c_03_missing_authority_is_never_unlimited(tmp_path):
    root = tmp_path / "ws" / "root"
    root.mkdir(parents=True)
    with pytest.raises(CreateTestFileDenied) as exc:
        CreateTestFileAuthority(
            authorized_root=root,
            authorized_target=root / "effect.txt",
            expected_content_sha256=sha256_bytes(CONTENT),
            authority=None,
        )
    assert exc.value.code == "authority-missing"
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_m36c_04_expired_authority_no_effect(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    # Well-formed, digest-valid authority; expiry is observed at EFFECT time via
    # the grant clock (past the ceiling window), never by mutating the record.
    expired_clock = NOW + timedelta(seconds=3600 + 10)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: expired_clock,
    )
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c4")
    mission = await _started_mission(components, "m36c4")
    node = _node("effect.txt", CONTENT.decode())
    _bind(store, str(mission.id), node, authority)
    await _run_governed(components, store, mission.id, node, authority, executor)

    assert node.state == RuntimeNodeState.FAILED
    assert executor.effect_calls == 0
    assert not grant.authorized_target.exists()
    executor.close()


@pytest.mark.asyncio
async def test_m36c_05_wrong_digest_no_effect(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c5")
    mission = await _started_mission(components, "m36c5")
    node = _node("effect.txt", "tampered-content")
    _bind(store, str(mission.id), node, authority)
    await _run_governed(components, store, mission.id, node, authority, executor)

    assert node.state == RuntimeNodeState.FAILED
    assert executor.effect_calls == 0
    assert "content-substitution" in executor.denials
    assert not grant.authorized_target.exists()
    executor.close()


@pytest.mark.asyncio
async def test_m36c_06_wrong_target_no_effect(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c6")
    mission = await _started_mission(components, "m36c6")
    node = _node("other.txt", CONTENT.decode())
    _bind(store, str(mission.id), node, authority)
    await _run_governed(components, store, mission.id, node, authority, executor)

    assert executor.effect_calls == 0
    assert not grant.authorized_target.exists()
    assert not (root / "other.txt").exists()
    executor.close()


@pytest.mark.asyncio
async def test_m36c_07_dispatch_binding_mismatch_zero_dispatch(tmp_path):
    """A durable action bound to a different digest refuses dispatch: ZERO calls."""
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c7")
    mission = await _started_mission(components, "m36c7")
    bound_node = _node("effect.txt", CONTENT.decode())
    _bind(store, str(mission.id), bound_node, authority)

    # Dispatch a DIFFERENT node (different idempotency key -> different digest).
    other = _node("effect.txt", CONTENT.decode())
    other.action_contract.idempotency_key = "other"
    await _run_governed(components, store, mission.id, other, authority, executor)

    assert executor.effect_calls == 0
    assert not grant.authorized_target.exists()
    executor.close()


@pytest.mark.asyncio
async def test_m36c_08_duplicate_execution_denied(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = NativeCreateTestFileActionExecutor(grant)

    components, store = _environment(tmp_path, "mstore-m36c8")
    mission = await _started_mission(components, "m36c8")
    node = _node("effect.txt", CONTENT.decode())
    _bind(store, str(mission.id), node, authority)

    await _run_governed(components, store, mission.id, node, authority, executor)
    assert executor.effect_calls == 1

    # A second full governed run over the SAME durable record must not re-dispatch.
    await _run_governed(
        components, store, mission.id, _node("effect.txt", CONTENT.decode()),
        authority, executor, runtime_id="g-m36b",
    )
    assert executor.effect_calls == 1
    assert grant.authorized_target.read_bytes() == CONTENT
    executor.close()


def test_m36c_09_forged_executor_receipt_cannot_satisfy_observer(tmp_path):
    workspace = tmp_path / "ws"
    root = workspace / "root"
    root.mkdir(parents=True)
    authority = _authority(root)
    grant = CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    # A forged "success" claim with no real effect.
    forged = {"success": True, "effect_occurred": True, "digest": sha256_bytes(CONTENT)}
    observation = NativeFilesystemObserver(grant).observe()
    assert forged["success"] is True
    assert observation["exists"] is False
    assert observation["matches_authorized"] is False


def test_m36c_10_verification_failure_on_denied_effect(tmp_path):
    """STRUCTURAL schema requires effect_occurred==true; a denied dict fails."""
    import asyncio

    from intent_kernel.runtime.verification import (
        DeterministicStructuralVerifier,
    )

    contract = _node("effect.txt", CONTENT.decode()).action_contract
    contract.verification_type = "STRUCTURAL"
    contract.verification_schema = VERIFICATION_SCHEMA
    denied = {
        "success": False, "effect_occurred": False, "path": "effect.txt",
        "digest": "", "reason": "authority-expired", "root_identity": "x:y:z",
    }
    status = asyncio.run(
        DeterministicStructuralVerifier().verify(contract, denied)
    )
    assert status == VerificationStatus.VERIFIED_FAILURE
