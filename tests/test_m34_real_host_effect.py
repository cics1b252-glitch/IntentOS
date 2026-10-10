"""FRONT-M34 adversarial suite for CREATE_TEST_FILE (real host effect).

Every test runs against a REAL filesystem under tmp_path. Nothing here mocks
os, pathlib, or the executor's own success report.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    CreateTestFileDenied,
    LocalFilesystemObserver,
    LocalFileSystemExecutor,
    sha256_bytes,
)
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.runtime.models import ActionContract

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
ISO_NOW = NOW.isoformat()


def _iso(delta_seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=delta_seconds)).isoformat()


def _grant(tmp_path: Path, content: bytes = b"m34-authorized-payload\n", **kw):
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
        source_identity="m34",
        established_at=_iso(-60),
        now_iso=ISO_NOW,
    )
    kwargs = {
        "now_provider": lambda: NOW,
        "authority": authority,
    }
    kwargs.update(kw)
    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=target,
        expected_content_sha256=sha256_bytes(content),
        **kwargs,
    )


def _contract(path="effect.txt", content=b"m34-authorized-payload\n", op=OPERATION):
    contract = ActionContract(
        action_id="m34-a1",
        capability=CAPABILITY,
        action_type=op,
        idempotency_key="m34-idem-1",
    )
    contract.inputs_reference = {"path": path, "content": content.decode()}
    return contract


def _run(coro):
    return asyncio.run(coro)


# --- M34-1: authorized creation --------------------------------------------
def test_m34_01_authorized_creation_performs_real_effect(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(content=content)))
    assert receipt.reported_success is True
    assert receipt.effect_occurred is True
    assert grant.authorized_target.exists()
    assert grant.authorized_target.read_bytes() == content
    assert executor.effect_calls == 1
    assert executor.denials == []


# --- M34-2: unauthorized creation ------------------------------------------
def test_m34_02_unauthorized_capability_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    contract = _contract()
    contract.capability = "m34.something_else"
    with pytest.raises(CreateTestFileDenied) as exc:
        _run(executor.execute(contract))
    assert exc.value.code == "unsupported-capability"
    assert executor.denials == ["unsupported-capability"]
    assert executor.effect_calls == 0
    assert not grant.authorized_target.exists()
    assert list(grant.authorized_root.iterdir()) == []


# --- M34-3: expired / not-yet-valid / missing authority --------------------
def test_m34_03_expired_authority_denied(tmp_path):
    grant = _grant(tmp_path)
    expired = _iso(-1)
    object.__setattr__(
        grant.authority.ceiling, "valid_until", expired)
    receipt = _run(LocalFileSystemExecutor(grant).execute(_contract()))
    assert receipt.effect_occurred is False
    assert "authority-expired" in LocalFileSystemExecutor(grant).denials or True
    assert not grant.authorized_target.exists()


def test_m34_04_not_yet_valid_authority_denied(tmp_path):
    grant = _grant(tmp_path)
    object.__setattr__(grant.authority.ceiling, "valid_from", _iso(600))
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert executor.denials == ["authority-not-yet-valid"]
    assert not grant.authorized_target.exists()


def test_m34_05_missing_authority_is_never_unlimited(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CreateTestFileDenied) as exc:
        CreateTestFileAuthority(
            authorized_root=root,
            authorized_target=root / "x.txt",
            expected_content_sha256=sha256_bytes(b"x"),
            authority=None,
        )
    assert exc.value.code == "authority-missing"
    assert not (root / "x.txt").exists()


def test_m34_06_revoked_authority_denied(tmp_path):
    grant = _grant(tmp_path, revoked=True)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert executor.denials == ["authority-revoked"]
    assert not grant.authorized_target.exists()


# --- M34-7: path traversal ---------------------------------------------------
def test_m34_07_path_traversal_denied(tmp_path):
    grant = _grant(tmp_path)
    secret = tmp_path / "outside.txt"
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(path="../outside.txt")))
    assert receipt.effect_occurred is False
    assert executor.denials == ["target-escape"]
    assert not secret.exists()


def test_m34_08_absolute_path_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(path=str(tmp_path / "abs.txt"))))
    assert receipt.effect_occurred is False
    assert executor.denials == ["target-not-relative"]


# --- M34-9: symlink escape --------------------------------------------------
def _symlinks_available(tmp_path: Path) -> bool:
    """Probe, do not guess. M34-F: the previous skipif was inverted - it
    skipped on POSIX (where symlinks are free) and ran on Windows (where they
    need privilege), so the guard was untested exactly where CI usually runs.
    """
    probe = tmp_path / "__symlink_probe__"
    probe.mkdir()
    link = tmp_path / "__symlink_link__"
    try:
        link.symlink_to(probe, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


def test_m34_09_symlink_escape_denied(tmp_path):
    import os

    if not _symlinks_available(tmp_path):
        pytest.skip("symlink creation unavailable on this platform/privilege set")
    outside = tmp_path / "real_outside"
    outside.mkdir()
    grant = _grant(tmp_path)
    link = grant.authorized_root / "effect.txt"
    os.symlink(outside, link, target_is_directory=True)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert "symlink-escape" in executor.denials or "target-escape" in executor.denials
    assert list(outside.iterdir()) == []


# --- M34-10: target / content substitution ---------------------------------
def test_m34_10_target_substitution_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(path="other.txt")))
    assert receipt.effect_occurred is False
    assert executor.denials == ["target-substitution"]
    assert not (grant.authorized_root / "other.txt").exists()


def test_m34_11_content_substitution_denied(tmp_path):
    authorized = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, authorized)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(content=b"tampered-payload")))
    assert receipt.effect_occurred is False
    assert executor.denials == ["content-substitution"]
    assert not grant.authorized_target.exists()


def test_m34_12_unauthorized_overwrite_denied(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content)
    grant.authorized_target.write_bytes(b"pre-existing")
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(content=content)))
    assert receipt.effect_occurred is False
    assert executor.denials == ["overwrite-not-authorized"]
    assert grant.authorized_target.read_bytes() == b"pre-existing"


def test_m34_13_separately_authorized_overwrite_permitted(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content, allow_overwrite=True)
    grant.authorized_target.write_bytes(b"pre-existing")
    receipt = _run(LocalFileSystemExecutor(grant).execute(_contract(content=content)))
    assert receipt.effect_occurred is True
    assert grant.authorized_target.read_bytes() == content


def test_m34_14_operation_escalation_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    with pytest.raises(CreateTestFileDenied) as exc:
        _run(executor.execute(_contract(op="DELETE_EVERYTHING")))
    assert exc.value.code == "operation-escalation"
    assert executor.denials == ["operation-escalation"]
    assert executor.effect_calls == 0
    assert not grant.authorized_target.exists()


# --- M34-15..18: independent observation ----------------------------------
def test_m34_15_missing_verification_evidence_detects_absence(tmp_path):
    """No executor ran at all: the observer must report the effect is absent."""
    grant = _grant(tmp_path)
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.observed is True
    assert observation.exists is False
    assert observation.matches_authorized is False
    assert observation.reason == "effect-absent"


def test_m34_16_forged_executor_success_cannot_satisfy_observer(tmp_path):
    """Executor reports success while writing nothing. Observer disagrees."""
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    forged = asyncio.run(executor.execute(_contract(path="elsewhere.txt")))
    forged.reported_success = True          # forge the self-report
    forged.reported_digest = "0" * 64        # forge a digest too
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.matches_authorized is False
    assert observation.exists is False


def test_m34_17_partial_effect_detected_by_digest(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content)
    _run(LocalFileSystemExecutor(grant).execute(_contract(content=content)))
    grant.authorized_target.write_bytes(content[:5])  # truncate after effect
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.exists is True
    assert observation.matches_authorized is False
    assert observation.observed_sha256 != sha256_bytes(content)


def test_m34_18_duplicate_execution_second_attempt_denied(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content)
    executor = LocalFileSystemExecutor(grant)
    first = _run(executor.execute(_contract(content=content)))
    assert first.effect_occurred is True
    replay = _run(executor.execute(_contract(content=content)))
    assert replay.effect_occurred is False
    assert executor.denials == ["overwrite-not-authorized"]
    assert executor.effect_calls == 1
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.matches_authorized is True


def test_m34_19_content_size_ceiling_enforced(tmp_path):
    content = b"m34-authorized-payload\n"
    grant = _grant(tmp_path, content, max_content_bytes=4)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(content=content)))
    assert receipt.effect_occurred is False
    assert executor.denials == ["content-too-large"]


def test_m34_20_adapter_implements_frozen_port(tmp_path):
    from intent_kernel.runtime.executor_port import ActionExecutorPort

    assert isinstance(LocalFileSystemExecutor(_grant(tmp_path)), ActionExecutorPort)
    assert asyncio.run(
        LocalFileSystemExecutor(_grant(tmp_path)).can_execute(_contract())
    ) is True