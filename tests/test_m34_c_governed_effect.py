"""FRONT-M34-C: real governed host effect with independent verification.

Drives the CANONICAL productive path end to end:

    establish explicit bounded intent authority
    -> durable mission record + PENDING action (authority-bearing)
    -> MissionRuntime.create_instance
    -> run_mission
    -> ProductiveDispatchGuard.acquire   (durable attempt authority)
    -> LocalFileSystemExecutor.execute   (REAL host filesystem write)
    -> LocalFilesystemObserver.observe   (INDEPENDENT read-back)

Emits a durable evidence package under the isolated workspace.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    LocalFilesystemObserver,
    LocalFileSystemExecutor,
    sha256_bytes,
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
from intent_kernel.mission.intent_authority import (
    IntentAuthorityRecord,
    establish_intent_authority,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import ActionContract, RuntimeNode

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
CONTENT = b"m34-real-host-effect-payload\n"


@pytest.fixture(autouse=True)
def _declare_create_test_file_applicability():
    """Scoped, restored declaration - NEVER a module-import side effect.

    M34-F: the previous version called
    ``DEFAULT_QUANTITY_APPLICABILITY.declare(...)`` at import time, which
    permanently mutated process-global registry state for every other test
    collected in the same session. CREATE_TEST_FILE is a bounded single-target
    effect with no quantity dimension, so the declaration is a POSITIVE
    not-applicable proof - not an authority grant - and it is now installed
    only for the duration of these tests and removed afterwards.
    """
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION), (
        "global registry leaked state before this test ran"
    )
    DEFAULT_QUANTITY_APPLICABILITY.declare(OPERATION, None)
    try:
        yield
    finally:
        DEFAULT_QUANTITY_APPLICABILITY._by_operation.pop(OPERATION, None)
        assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION)


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _authority(root: Path) -> IntentAuthorityRecord:
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
        source_identity="m34-c",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )


def _node(path: str, content: str) -> RuntimeNode:
    contract = ActionContract(
        action_id="n1",
        capability=CAPABILITY,
        action_type=OPERATION,
        idempotency_key="m34-c-idem",
    )
    contract.inputs_reference = {"path": path, "content": content}
    return RuntimeNode(
        node_id="n1",
        capability=CAPABILITY,
        agent_id="ex-m34",
        action_contract=contract,
    )


def _bind(store, mid: str, node: RuntimeNode) -> None:
    spec = spec_for_runtime_node(mid, node)
    ident = store.get_continuity_identity()
    definition = MissionDefinition(
        objective="m34 real host effect",
        context={"k": "v"},
        intent_authority=_authority(Path(node.action_contract.inputs_reference["root"])),
    )
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition,
    )
    record = MissionRecord(
        mission_id=mid,
        installation_id=ident,
        revision=1,
        runtime_id="rt-m34",
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


@pytest.mark.asyncio
async def test_m34_c_real_governed_host_effect_with_independent_verification(tmp_path):
    """M34-C: one real, authorized, independently verified filesystem effect."""
    workspace = tmp_path / "workspace"
    effect_root = workspace / "root"
    effect_root.mkdir(parents=True)
    unauthorized_target = workspace / "unauthorized.txt"
    unauthorized_target.write_bytes(b"untouched")

    authority = _authority(effect_root)
    grant = CreateTestFileAuthority(
        authorized_root=effect_root,
        authorized_target=effect_root / "governed-effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )
    executor = LocalFileSystemExecutor(grant)
    observer = LocalFilesystemObserver(grant)

    components = _components(tmp_path, tmp_path / ".intent-os-m34c")
    app = CountingApp(capability=CAPABILITY)
    _govern(components, app)
    mission = await _started_mission(components, "m34c")
    store = _mission_store(tmp_path, "mstore-m34c")

    node = _node("governed-effect.txt", CONTENT.decode())
    node.action_contract.inputs_reference["root"] = str(effect_root)
    _bind(store, str(mission.id), node)

    guard = ProductiveDispatchGuard(MissionActionAuthority(store), store)
    runtime = MissionRuntime(
        executor=executor,
        constitution=_AllowConstitution(),
        dispatch_guard=guard,
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )
    instance = runtime.create_instance(
        str(mission.id), "g-m34", [node], intent_authority=authority,
    )
    await runtime.run_mission(instance.runtime_id)

    # --- authority decision + exact binding ---
    assert authority.ceiling.allow_capabilities == (CAPABILITY,)
    assert authority.authority_digest

    # --- real, independent observation of the host filesystem ---
    observation = observer.observe()
    assert observation.observed is True
    assert observation.exists is True
    assert observation.matches_authorized is True
    assert observation.observed_sha256 == sha256_bytes(CONTENT)
    assert grant.authorized_target.read_bytes() == CONTENT

    # --- no unauthorized side effects ---
    assert unauthorized_target.read_bytes() == b"untouched"
    assert sorted(p.name for p in effect_root.iterdir()) == ["governed-effect.txt"]

    # --- durable evidence package ---
    package = {
        "authority": {
            "source_type": authority.source_type,
            "authority_digest": authority.authority_digest,
            "ceiling": {
                "allow_capabilities": list(authority.ceiling.allow_capabilities),
                "allowed_operations": list(authority.ceiling.allowed_operations),
                "target_scope": list(authority.ceiling.target_scope),
            },
        },
        "binding": {
            "authorized_target": str(grant.authorized_target),
            "expected_content_sha256": grant.expected_content_sha256,
            "request_semantics_digest": spec_for_runtime_node(
                str(mission.id), node).request_semantics_digest,
        },
        "dispatch": {
            "executor_effect_calls": executor.effect_calls,
            "denials": list(executor.denials),
        },
        "observation": {
            "exists": observation.exists,
            "observed_sha256": observation.observed_sha256,
            "matches_authorized": observation.matches_authorized,
            "reason": observation.reason,
        },
        "negative_test": {
            "unauthorized_target_unchanged":
                unauthorized_target.read_bytes() == b"untouched",
        },
    }
    evidence_path = workspace / "M34_C_EVIDENCE.json"
    evidence_path.write_text(json.dumps(package, indent=2, sort_keys=True))
    assert evidence_path.exists()

    # Executor self-report is NOT the basis of any assertion above: the
    # observation component never receives the receipt.
    assert executor.effect_calls == 1
    assert observation.observed_sha256 == sha256_bytes(
        grant.authorized_target.read_bytes()
    )
    return package


@pytest.mark.asyncio
async def test_m34_c_negative_unauthorized_target_remains_unchanged(tmp_path):
    """M34-C negative: an unauthorized target must not be created at all."""
    workspace = tmp_path / "workspace"
    effect_root = workspace / "root"
    effect_root.mkdir(parents=True)
    outside = workspace / "escape.txt"

    grant = CreateTestFileAuthority(
        authorized_root=effect_root,
        authorized_target=effect_root / "governed-effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=_authority(effect_root),
        now_provider=lambda: NOW,
    )
    executor = LocalFileSystemExecutor(grant)

    node = _node("../escape.txt", CONTENT.decode())
    receipt = await executor.execute(node.action_contract)

    assert receipt.effect_occurred is False
    assert executor.effect_calls == 0
    assert executor.denials == ["target-escape"]
    assert not outside.exists()
    assert observer_denies(grant)


def observer_denies(grant: CreateTestFileAuthority) -> bool:
    return LocalFilesystemObserver(grant).observe().matches_authorized is False