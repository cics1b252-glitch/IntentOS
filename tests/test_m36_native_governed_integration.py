"""FRONT-M36-B: governed integration of native preventive containment.

Proves the additive adapter ``NativeCreateTestFileActionExecutor`` implements
the EXISTING frozen port and preserves every M34/M35 guarantee:

    intent-derived authority, exact binding identity, effect-time
    revalidation, revocation enforcement, single-target restriction,
    exclusive creation, native preventive containment, fail-closed posture,
    and independent observation.

Every test runs against a REAL filesystem under tmp_path. Nothing here mocks
the executor's own success report.
"""

from __future__ import annotations

import asyncio
import json
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
    NativeContainmentUnavailable,
    NativeCreateTestFileActionExecutor,
    NativeFilesystemObserver,
)
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"m36-exec-content\n"


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _grant(tmp_path: Path, content: bytes = CONTENT, **kw):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
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
        source_identity="m36-b",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )
    options = {"authority": authority, "now_provider": lambda: NOW}
    options.update(kw)
    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(content),
        **options,
    )


def _contract(path="effect.txt", content=CONTENT, op=OPERATION, cap=CAPABILITY):
    from intent_kernel.runtime.models import ActionContract

    contract = ActionContract(
        action_id="m36-a1", capability=cap, action_type=op, idempotency_key="m36-idem",
    )
    contract.inputs_reference = {
        "path": path, "content": content.decode("utf-8", "surrogateescape"),
    }
    return contract


def _run(coro):
    return asyncio.run(coro)


# --- frozen port -----------------------------------------------------------
def test_m36b_01_adapter_implements_frozen_port(tmp_path):
    from intent_kernel.runtime.executor_port import ActionExecutorPort

    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        assert isinstance(ex, ActionExecutorPort)
        assert _run(ex.can_execute(_contract())) is True
        assert _run(ex.can_execute(_contract(cap="other"))) is False


def test_m36b_02_authorized_effect_is_real_and_independently_observed(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract()))
        assert result["success"] is True
        assert result["effect_occurred"] is True
        assert result["digest"] == sha256_bytes(CONTENT)
        assert result["root_identity"]
        assert result["created_identity"]
        assert ex.effect_calls == 1
        assert ex.denials == []
        observer = NativeFilesystemObserver(
            grant, expected_root_identity=result["root_identity"]
        )
    observation = observer.observe()
    assert observation["observed"] is True
    assert observation["exists"] is True
    assert observation["matches_authorized"] is True
    assert observation["identity_stable"] is True
    assert observation["root_identity"] == result["root_identity"]
    assert observation["root_identity_matches"] is True
    assert grant.authorized_target.read_bytes() == CONTENT


def test_m36b_03_result_is_json_safe(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract()))
    assert json.loads(json.dumps(result)) == result


# --- exact binding / escalation --------------------------------------------
def test_m36b_04_wrong_target_is_denied(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract(path="elsewhere.txt")))
        assert result["effect_occurred"] is False
        assert result["reason"] == "target-substitution"
        assert ex.effect_calls == 0
        assert not (grant.authorized_root / "elsewhere.txt").exists()


def test_m36b_05_capability_escalation_refused_hard(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        with pytest.raises(CreateTestFileDenied) as exc:
            _run(ex.execute(_contract(cap="m34.other")))
        assert exc.value.code == "unsupported-capability"
        assert ex.effect_calls == 0


def test_m36b_06_operation_escalation_refused_hard(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        with pytest.raises(CreateTestFileDenied) as exc:
            _run(ex.execute(_contract(op="DELETE_EVERYTHING")))
        assert exc.value.code == "operation-escalation"
        assert ex.effect_calls == 0


# --- authority / containment fail-closed -----------------------------------
def test_m36b_07_content_substitution_denied(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract(content=b"tampered")))
        assert result["effect_occurred"] is False
        assert result["reason"] == "content-substitution"
        assert not grant.authorized_target.exists()


def test_m36b_08_revoked_authority_denied(tmp_path):
    grant = _grant(tmp_path, revoked=True)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract()))
        assert result["effect_occurred"] is False
        assert result["reason"] == "authority-revoked"
        assert not grant.authorized_target.exists()


def test_m36b_09_expired_authority_denied(tmp_path):
    grant = _grant(tmp_path)
    object.__setattr__(grant.authority.ceiling, "valid_until", _iso(-1))
    with NativeCreateTestFileActionExecutor(grant) as ex:
        result = _run(ex.execute(_contract()))
        assert result["effect_occurred"] is False
        assert result["reason"] == "authority-expired"
        assert not grant.authorized_target.exists()


def test_m36b_10_root_identity_precondition(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(
        grant, expected_root_identity="0:0:0"
    ) as ex:
        result = _run(ex.execute(_contract()))
        assert result["effect_occurred"] is False
        assert result["reason"] == "root-identity-mismatch"
        assert not grant.authorized_target.exists()

        # A matching identity executes normally and the observer agrees.
        real = ex._root_identity_str()
    with NativeCreateTestFileActionExecutor(
        grant, expected_root_identity=real
    ) as ex2:
        result = _run(ex2.execute(_contract()))
        assert result["effect_occurred"] is True
    obs = NativeFilesystemObserver(grant, expected_root_identity="deadbeef").observe()
    assert obs["root_identity"] == real
    assert obs["root_identity_matches"] is False


def test_m36b_11_exclusive_create_duplicate_denied(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileActionExecutor(grant) as ex:
        first = _run(ex.execute(_contract()))
        assert first["effect_occurred"] is True
        again = _run(ex.execute(_contract()))
        assert again["effect_occurred"] is False
        assert again["reason"] == "overwrite-not-authorized"
        assert ex.effect_calls == 1
    assert grant.authorized_target.read_bytes() == CONTENT


def test_m36b_12_fail_closed_when_native_containment_unavailable(tmp_path, monkeypatch):
    import intent_kernel.adapters.native_containment as mod

    monkeypatch.setattr(
        mod, "platform_capabilities",
        lambda: {"platform": "test", "preventive": False, "mechanism": "none"},
    )
    monkeypatch.setattr(mod, "PREVENTIVE_CONTAINMENT", False, raising=False)
    grant = _grant(tmp_path)
    with pytest.raises(NativeContainmentUnavailable):
        NativeCreateTestFileActionExecutor(grant)
    # NO fallback to the non-atomic M34 adapter: nothing was written.
    assert list(grant.authorized_root.iterdir()) == []
    assert not grant.authorized_target.exists()


def test_m36b_13_observer_reports_absence(tmp_path):
    grant = _grant(tmp_path)
    observation = NativeFilesystemObserver(grant).observe()
    assert observation["observed"] is True
    assert observation["exists"] is False
    assert observation["matches_authorized"] is False


def test_m36b_14_m34_adapter_unmodified(tmp_path):
    """M36 must not have altered the M34 adapter's behaviour."""
    from intent_kernel.adapters.local_filesystem import LocalFileSystemExecutor

    grant = _grant(tmp_path)
    receipt = _run(LocalFileSystemExecutor(grant).execute(_contract()))
    assert receipt.effect_occurred is True
    assert grant.authorized_target.read_bytes() == CONTENT
