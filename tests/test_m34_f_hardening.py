"""FRONT-M34-F: adversarial validation for the hardened filesystem guards.

Covers the Phase C matrix plus negative-sensitivity tests proving each repaired
guard actually fires rather than passing vacuously.
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    CONTAINMENT_MODE,
    OPERATION,
    ContainmentBreach,
    CreateTestFileAuthority,
    LocalFileSystemExecutor,
    LocalFilesystemObserver,
    UnsupportedGuaranteeError,
    require_atomic_containment,
    sha256_bytes,
)
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.runtime.models import ActionContract

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"m34-f-hardened-payload\n"


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _grant(tmp_path: Path, **kw):
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
        source_identity="m34-f",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )
    options = {"authority": authority, "now_provider": lambda: NOW}
    options.update(kw)
    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        **options,
    )


def _contract(path="effect.txt", content=CONTENT, op=OPERATION):
    contract = ActionContract(
        action_id="m34f", capability=CAPABILITY, action_type=op,
        idempotency_key="m34f-idem",
    )
    contract.inputs_reference = {"path": path, "content": content.decode()}
    return contract


def _run(coro):
    return asyncio.run(coro)


def _symlinks_available(tmp_path: Path) -> bool:
    probe = tmp_path / "__probe__"
    probe.mkdir()
    try:
        (tmp_path / "__link__").symlink_to(probe, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


# --- C1: traversal ----------------------------------------------------------
def test_f_c01_traversal_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(path="../escape.txt")))
    assert receipt.effect_occurred is False
    assert executor.effect_calls == 0
    assert executor.denials == ["target-escape"]
    assert not (tmp_path / "escape.txt").exists()


# --- C2: symlink / junction escape -----------------------------------------
def test_f_c02_symlink_escape_denied(tmp_path):
    if not _symlinks_available(tmp_path):
        pytest.skip("symlink creation unavailable on this platform")
    outside = tmp_path / "real_outside"
    outside.mkdir()
    grant = _grant(tmp_path)
    (grant.authorized_root / "effect.txt").symlink_to(outside, target_is_directory=True)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert executor.effect_calls == 0
    assert list(outside.iterdir()) == []


def test_f_c02b_symlinked_parent_component_denied(tmp_path):
    """A symlink on an INTERMEDIATE component must not be traversed."""
    if not _symlinks_available(tmp_path):
        pytest.skip("symlink creation unavailable on this platform")
    outside = tmp_path / "real_outside"
    outside.mkdir()
    grant = _grant(tmp_path)
    nested = grant.authorized_root / "nested"
    nested.symlink_to(outside, target_is_directory=True)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(path="nested/effect.txt")))
    assert receipt.effect_occurred is False
    assert list(outside.iterdir()) == []


# --- C3: concurrent path replacement ---------------------------------------
def test_f_c03_concurrent_path_replacement_detected(tmp_path):
    """Hostile replacement racing the write must not yield silent success."""
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    outside = tmp_path / "swallowed"
    outside.mkdir()

    original = LocalFileSystemExecutor._assert_chain_contained

    def sabotage(self, target, stage="pre-write"):
        # Simulate the hostile win: swap the leaf for a symlink exactly in the
        # check->write window.
        if stage == "pre-write" and target.parent.exists():
            try:
                target.unlink()
            except OSError:
                pass
            try:
                target.symlink_to(outside / "redirected.txt")
            except OSError:
                pass
        return original(self, target, stage)

    LocalFileSystemExecutor._assert_chain_contained = sabotage
    try:
        with pytest.raises((ContainmentBreach, OSError)):
            _run(executor.execute(_contract()))
    finally:
        LocalFileSystemExecutor._assert_chain_contained = original

    # Nothing may exist at the redirected location.
    assert not (outside / "redirected.txt").exists()


def test_f_c03b_atomic_containment_requirement_fails_closed_honestly():
    """The unsupported guarantee is refused, never silently downgraded."""
    if CONTAINMENT_MODE == "POSIX_ATOMIC_NOFOLLOW":
        assert require_atomic_containment() == "POSIX_ATOMIC_NOFOLLOW"
    else:
        with pytest.raises(UnsupportedGuaranteeError):
            require_atomic_containment()
    assert isinstance(CONTAINMENT_MODE, str) and CONTAINMENT_MODE


# --- C4: unauthorized overwrite --------------------------------------------
def test_f_c04_unauthorized_overwrite_denied(tmp_path):
    grant = _grant(tmp_path)
    grant.authorized_target.write_bytes(b"pre-existing")
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert grant.authorized_target.read_bytes() == b"pre-existing"


# --- C5: partial write ------------------------------------------------------
def test_f_c05_partial_write_detected_by_observer(tmp_path):
    grant = _grant(tmp_path)
    _run(LocalFileSystemExecutor(grant).execute(_contract()))
    grant.authorized_target.write_bytes(CONTENT[:4])
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.exists is True
    assert observation.matches_authorized is False
    assert observation.reason == "digest-mismatch"


def test_f_c05b_truncated_content_never_authorized(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract(content=CONTENT[:4])))
    assert receipt.effect_occurred is False
    assert executor.denials == ["content-substitution"]


# --- C6: replay -------------------------------------------------------------
def test_f_c06_replay_denied(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    assert _run(executor.execute(_contract())).effect_occurred is True
    assert _run(executor.execute(_contract())).effect_occurred is False
    assert executor.effect_calls == 1
    assert executor.denials == ["overwrite-not-authorized"]


# --- C7: authority expiry / revocation -------------------------------------
def test_f_c07_expired_authority_denied(tmp_path):
    grant = _grant(tmp_path)
    object.__setattr__(grant.authority.ceiling, "valid_until", _iso(-1))
    executor = LocalFileSystemExecutor(grant)
    receipt = _run(executor.execute(_contract()))
    assert receipt.effect_occurred is False
    assert executor.denials == ["authority-expired"]


def test_f_c07b_revoked_authority_denied(tmp_path):
    grant = _grant(tmp_path, revoked=True)
    executor = LocalFileSystemExecutor(grant)
    assert _run(executor.execute(_contract())).effect_occurred is False
    assert executor.denials == ["authority-revoked"]


# --- C8: global registry isolation -----------------------------------------
def test_f_c08_global_registry_not_mutated_at_import():
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION), (
        "importing M34 tests must not mutate the process-global registry"
    )


def test_f_c08b_scoped_declaration_is_restored():
    from intent_kernel.mission.quantity import DEFAULT_QUANTITY_APPLICABILITY

    assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION)
    DEFAULT_QUANTITY_APPLICABILITY.declare(OPERATION, None)
    try:
        assert DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION)
    finally:
        DEFAULT_QUANTITY_APPLICABILITY._by_operation.pop(OPERATION, None)
    assert not DEFAULT_QUANTITY_APPLICABILITY.is_declared(OPERATION)


# --- C9: genuine observed effect -------------------------------------------
def test_f_c09_genuine_effect_observed(tmp_path):
    grant = _grant(tmp_path)
    receipt = _run(LocalFileSystemExecutor(grant).execute(_contract()))
    assert receipt.effect_occurred is True
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.exists is True
    assert observation.matches_authorized is True
    assert observation.observed_sha256 == sha256_bytes(CONTENT)
    assert grant.authorized_target.read_bytes() == CONTENT


# --- C10: forged executor success ------------------------------------------
def test_f_c10_forged_success_cannot_satisfy_observer(tmp_path):
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    forged = _run(executor.execute(_contract(path="elsewhere.txt")))
    forged.reported_success = True
    forged.reported_digest = "f" * 64
    observation = LocalFilesystemObserver(grant).observe()
    assert observation.matches_authorized is False
    assert observation.exists is False


# --- negative sensitivity: guards must actually fire ------------------------
def test_f_n01_guards_are_not_vacuous(tmp_path):
    """Each deny code requires its specific trigger; swapping the trigger
    must NOT produce that code. A guard that always fires proves nothing."""
    grant = _grant(tmp_path)
    executor = LocalFileSystemExecutor(grant)
    # Wrong trigger for content-substitution: correct content must NOT deny.
    good = _run(executor.execute(_contract()))
    assert good.effect_occurred is True
    assert executor.denials == []

    # Wrong trigger for target-escape: in-root path must NOT deny.
    grant2 = _grant(tmp_path / "b")
    ex2 = LocalFileSystemExecutor(grant2)
    assert _run(ex2.execute(_contract())).effect_occurred is True
    assert ex2.denials == []


def test_f_n02_overwrite_guard_is_the_only_barrier(tmp_path):
    """Removing the authorization flag is what permits overwrite; nothing else."""
    grant = _grant(tmp_path)
    grant.authorized_target.write_bytes(b"old")
    denied = _run(LocalFileSystemExecutor(grant).execute(_contract()))
    assert denied.effect_occurred is False
    assert grant.authorized_target.read_bytes() == b"old"

    grant.allow_overwrite = True
    allowed = _run(LocalFileSystemExecutor(grant).execute(_contract()))
    assert allowed.effect_occurred is True
    assert grant.authorized_target.read_bytes() == CONTENT


def test_f_n03_threaded_concurrent_creation_single_winner(tmp_path):
    """Concurrent duplicate effects must yield exactly one real file write."""
    grant = _grant(tmp_path)
    results: list = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        results.append(_run(LocalFileSystemExecutor(grant).execute(_contract())))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r.effect_occurred]
    assert len(winners) == 1, f"expected exactly one effect, got {len(winners)}"
    assert grant.authorized_target.read_bytes() == CONTENT
    assert LocalFilesystemObserver(grant).observe().matches_authorized is True