"""TP-09P-R1 / TP-09Q-R1 / TP-09R-R1: grounded observation + semantic evidence.

Adversarial validation of the additive observation-grounding adapter. Every
test asserts fail-closed provenance: caller assertions, forged records, stale
timestamps, cross-mission/action reuse and missing proofs must NEVER ground to
SATISFIED. Frozen Core is untouched.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.grounded_observation import (
    GroundedFilesystemObserver,
    GroundedObservation,
    GroundingError,
    compute_grounded_digest,
    is_fresh,
)
from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    ExecutionReceipt,
    LocalFilesystemObserver,
    LocalFileSystemExecutor,
    sha256_bytes,
)
from intent_kernel.mission.grounded_semantic_evidence import ground_semantic_evidence
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.success_contract import (
    CONTRACT_VERSION,
    CriterionProvenance,
    CriterionVerdict,
    SemanticCriterion,
)
from intent_kernel.mission.trusted_semantic_eval import (
    TrustedSemanticEvaluator,
    compute_mission_contract_digest,
)
from intent_kernel.preview import trusted_approval as ta
from intent_kernel.runtime.models import ActionContract

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"tp09 grounded payload\n"
MISSION = "mission-alpha"
ACTION = "action-a1"
PROOF = "proof-" + "a" * 58


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _grant(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "effect.txt"
    authority = establish_intent_authority(
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
        source_identity="tp09",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )
    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=target,
        expected_content_sha256=sha256_bytes(CONTENT),
        authority=authority,
        now_provider=lambda: NOW,
    )


def _contract():
    return ActionContract(
        action_id=ACTION, capability=CAPABILITY, action_type=OPERATION,
        idempotency_key="tp09-idem", inputs_reference={
            "path": "effect.txt", "content": CONTENT.decode()},
    )


def _effect(tmp_path):
    grant = _grant(tmp_path)
    asyncio.run(LocalFileSystemExecutor(grant).execute(_contract()))
    return grant


def _observe(grant, now_provider=lambda: NOW, **kw):
    obs = GroundedFilesystemObserver(
        grant, MISSION, ACTION, kw.pop("proof", PROOF),
        now_provider=now_provider,
    ).observe()
    return obs


def _forge(obs, **changes):
    fields = {k: v for k, v in obs.__dict__.items() if k != "record_digest"}
    fields.update(changes)
    return GroundedObservation(**fields)


def _ground(obs, **kw):
    args = dict(mission_id=MISSION, action_id=ACTION,
                expected_target=obs.authorized_target,
                expected_content_sha256=obs.expected_content_sha256,
                now=NOW)
    args.update(kw)
    return ground_semantic_evidence(obs, **args)


# ---------------------------------------------------------------- 1
def test_r01_valid_fresh_observation(tmp_path):
    obs = _observe(_effect(tmp_path))
    evidence = _ground(obs)
    assert evidence["gate_proof"]["digest"] == PROOF
    assert evidence["__result__"]["result"]["path"] == obs.authorized_target


# ---------------------------------------------------------------- 2
def test_r02_forged_caller_timestamp(tmp_path):
    obs = _observe(_effect(tmp_path))
    forged = _forge(obs, observed_at=_iso(600))
    with pytest.raises(GroundingError) as e:
        _ground(forged)
    assert e.value.code == "stale-observation"


# ---------------------------------------------------------------- 3
def test_r03_forged_observation_record(tmp_path):
    obs = _observe(_effect(tmp_path))
    object.__setattr__(obs, "observed_sha256", "0" * 64)
    with pytest.raises(GroundingError) as e:
        _ground(obs)
    assert e.value.code == "forged-observation-record"


# ---------------------------------------------------------------- 4
def test_r04_missing_observation_timestamp(tmp_path):
    obs = _observe(_effect(tmp_path))
    forged = _forge(obs, observed_at="")
    assert is_fresh("", NOW) is False
    with pytest.raises(GroundingError) as e:
        _ground(forged)
    assert e.value.code == "stale-observation"


# ---------------------------------------------------------------- 5
def test_r05_expired_observation(tmp_path):
    old = lambda: NOW - timedelta(seconds=400)
    obs = _observe(_effect(tmp_path), now_provider=old)
    with pytest.raises(GroundingError) as e:
        _ground(obs)
    assert e.value.code == "stale-observation"


# ---------------------------------------------------------------- 6
def test_r06_clock_rollback(tmp_path):
    future = lambda: NOW + timedelta(seconds=100)
    obs = _observe(_effect(tmp_path), now_provider=future)
    with pytest.raises(GroundingError) as e:
        _ground(obs)
    assert e.value.code == "stale-observation"


# ---------------------------------------------------------------- 7
def test_r07_wrong_mission(tmp_path):
    obs = _observe(_effect(tmp_path))
    with pytest.raises(GroundingError) as e:
        _ground(obs, mission_id="mission-beta")
    assert e.value.code == "cross-mission"


# ---------------------------------------------------------------- 8
def test_r08_wrong_action(tmp_path):
    obs = _observe(_effect(tmp_path))
    with pytest.raises(GroundingError) as e:
        _ground(obs, action_id="action-zzz")
    assert e.value.code == "cross-action"


# ---------------------------------------------------------------- 9
def test_r09_wrong_authorized_target(tmp_path):
    obs = _observe(_effect(tmp_path))
    with pytest.raises(GroundingError) as e:
        _ground(obs, expected_target=str(tmp_path / "other.txt"))
    assert e.value.code == "wrong-target"


# ---------------------------------------------------------------- 10
def test_r10_wrong_content_digest(tmp_path):
    obs = _observe(_effect(tmp_path))
    with pytest.raises(GroundingError) as e:
        _ground(obs, expected_content_sha256="f" * 64)
    assert e.value.code == "wrong-content-spec"


# ---------------------------------------------------------------- 11
def test_r11_same_content_different_execution(tmp_path):
    grant = _effect(tmp_path)
    obs_a = GroundedFilesystemObserver(grant, MISSION, "action-a1", PROOF,
                                       now_provider=lambda: NOW).observe()
    obs_b = GroundedFilesystemObserver(grant, MISSION, "action-b2", PROOF,
                                       now_provider=lambda: NOW).observe()
    # Identical observed_sha256, yet they are different executions.
    assert obs_a.observed_sha256 == obs_b.observed_sha256
    with pytest.raises(GroundingError) as e:
        _ground(obs_a, action_id="action-b2")
    assert e.value.code == "cross-action"


# ---------------------------------------------------------------- 12
def test_r12_missing_gate_proof(tmp_path):
    grant = _effect(tmp_path)
    with pytest.raises(GroundingError) as e:
        GroundedFilesystemObserver(grant, MISSION, ACTION, "")
    assert e.value.code == "missing-gate-proof"


# ---------------------------------------------------------------- 13
def test_r13_tampered_gate_proof(tmp_path):
    obs = _observe(_effect(tmp_path))
    object.__setattr__(obs, "gate_proof_digest", "tampered")
    with pytest.raises(GroundingError) as e:
        _ground(obs)
    assert e.value.code == "forged-observation-record"


# ---------------------------------------------------------------- 14
def test_r14_conflicting_receipt(tmp_path):
    obs = _observe(_effect(tmp_path))
    lying = ExecutionReceipt(
        reported_path="x", reported_success=True,
        reported_digest="1" * 64, effect_occurred=True)
    with pytest.raises(GroundingError) as e:
        _ground(obs, receipt=lying)
    assert e.value.code == "conflicting-receipt"


# ---------------------------------------------------------------- 15
def test_r15_observation_effect_race_limitation(tmp_path):
    """Honest TOCTOU: grounding trusts a point-in-time observation."""
    grant = _effect(tmp_path)
    obs = _observe(grant)
    evidence = _ground(obs)  # valid at observation time
    Path(obs.authorized_target).unlink()  # effect removed afterwards
    # The recorded, already-grounded evidence is unaffected — documented limit.
    assert evidence["__result__"]["result"]["path"] == obs.authorized_target


# ---------------------------------------------------------------- 16
def test_r16_planner_authored_semantic_success(tmp_path):
    obs = _observe(_effect(tmp_path))
    evidence = _ground(obs)
    c = SemanticCriterion(
        criterion_id="p", objective="x",
        provenance=CriterionProvenance.PLANNER_GENERATED.value,
        predicate="equals", json_path="result.path",
        expected=obs.authorized_target, evidence_refs=("gate_proof",),
        evaluation_version=CONTRACT_VERSION)
    digest = compute_mission_contract_digest([c], MISSION)
    token = ta.register_semantic_approval(digest, MISSION, CONTRACT_VERSION).token
    res = TrustedSemanticEvaluator().evaluate([c], evidence, token, MISSION)
    assert res.overall == CriterionVerdict.UNKNOWN.value


# ---------------------------------------------------------------- 17
def test_r17_approval_replay(tmp_path):
    obs = _observe(_effect(tmp_path))
    evidence = _ground(obs)
    c = SemanticCriterion(
        criterion_id="c", objective="x",
        provenance=CriterionProvenance.AUTHORIZED_APPROVER.value,
        predicate="equals", json_path="result.path",
        expected=obs.authorized_target, evidence_refs=("gate_proof",),
        approver_ref="op-1", evaluation_version=CONTRACT_VERSION)
    digest = compute_mission_contract_digest([c], MISSION)
    token = ta.register_semantic_approval(digest, MISSION, CONTRACT_VERSION).token
    ev = TrustedSemanticEvaluator()
    assert ev.evaluate([c], evidence, token, MISSION).overall == \
        CriterionVerdict.SATISFIED.value
    with pytest.raises(Exception):
        ev.evaluate([c], evidence, token, MISSION)


# ---------------------------------------------------------------- 18
def test_r18_legacy_observation_compatibility(tmp_path):
    grant = _effect(tmp_path)
    legacy = LocalFilesystemObserver(grant).observe()
    assert legacy.observed is True
    assert legacy.matches_authorized is True
    assert not hasattr(legacy, "mission_id")


# ---------------------------------------------------------------- 19
def test_r19_frozen_core_integrity():
    import intent_kernel.mission.delegation as d
    import intent_kernel.mission.dispatch_guard as g
    import intent_kernel.orchestration.execution as x
    import intent_kernel.runtime.verification as v
    for mod in (d, g, x, v):
        src = inspect.getsource(mod)
        assert "grounded_observation" not in src
        assert "grounded_semantic_evidence" not in src


# ---------------------------------------------------------------- 20
def test_r20_no_completion_gate_wiring():
    src = inspect.getsource(
        __import__("intent_kernel.runtime.mission_runtime", fromlist=["x"]))
    for token in ("grounded_observation", "grounded_semantic_evidence",
                  "ground_semantic_evidence"):
        assert token not in src
