"""FRONT-M35-C: adversarial prototype for native preventive containment.

The decisive test is ``test_c04_concurrent_parent_replacement_is_prevented``:
a REAL competing OS process renames the authorized root and plants a symlink
in its place while the effect is in flight. M34 could only detect that after
the write; M35 must prevent the write from ever being redirected.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    LocalFilesystemObserver,
    sha256_bytes,
)
from intent_kernel.adapters.native_containment import (
    PREVENTIVE_CONTAINMENT,
    ContainmentViolation,
    NativeContainment,
    NativeContainmentUnavailable,
    NativeCreateTestFileExecutor,
    NativeEffectDenied,
    platform_capabilities,
)
from intent_kernel.mission.intent_authority import establish_intent_authority
from intent_kernel.mission.intent_ceiling import IntentCeiling

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
CONTENT = b"m35-native-contained-payload\n"


def _iso(delta: int = 0) -> str:
    return (NOW + timedelta(seconds=delta)).isoformat()


def _grant(tmp_path: Path, **kw):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    authority = establish_intent_authority(
        ceiling=IntentCeiling(
            allow_capabilities=(CAPABILITY,),
            allowed_operations=("CREATE_TEST_FILE",),
            target_scope=(str(root),),
            max_risk_level="low",
            max_side_effect="LOCAL_REVERSIBLE",
            require_verification=True,
            valid_from=_iso(-60),
            valid_until=_iso(3600),
        ),
        source_type="user_explicit",
        source_identity="m35",
        established_at=_iso(-60),
        now_iso=NOW.isoformat(),
    )
    options = {"authority": authority, "now_provider": lambda: NOW}
    options.update(kw)
    from intent_kernel.adapters.local_filesystem import CreateTestFileAuthority

    return CreateTestFileAuthority(
        authorized_root=root,
        authorized_target=root / "effect.txt",
        expected_content_sha256=sha256_bytes(CONTENT),
        **options,
    )


def _symlinks_available(tmp_path: Path) -> bool:
    probe = tmp_path / "__probe__"
    probe.mkdir()
    try:
        (tmp_path / "__link__").symlink_to(probe, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


# --- capability matrix ------------------------------------------------------
def test_c01_platform_capability_matrix_is_probed_not_assumed():
    caps = platform_capabilities()
    assert caps["platform"] == sys.platform
    assert "mechanism" in caps and caps["mechanism"]
    assert isinstance(PREVENTIVE_CONTAINMENT, bool)
    assert caps["preventive"] == PREVENTIVE_CONTAINMENT


def test_c02_fail_closed_when_primitives_absent(tmp_path, monkeypatch):
    """If the platform loses its primitives we must refuse, not degrade."""
    import intent_kernel.adapters.native_containment as mod

    monkeypatch.setattr(
        mod, "platform_capabilities",
        lambda: {"platform": sys.platform, "preventive": False,
                 "mechanism": "none"},
    )
    monkeypatch.setattr(mod, "PREVENTIVE_CONTAINMENT", False)
    with pytest.raises(NativeContainmentUnavailable):
        mod.NativeContainment(tmp_path)


# --- prevention of traversal ------------------------------------------------
def test_c03_traversal_forms_refused_and_nothing_escapes(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    with NativeContainment(root) as nc:
        for bad in ("../escape.txt", "..\\escape.txt", "sub/child.txt",
                    "a/b/c.txt", "", ".", "..", "C:evil", "\\\\?\\C:\\x"):
            with pytest.raises(ContainmentViolation):
                nc.create_exclusive(bad, b"x")
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "escape.txt").exists()


# --- THE decisive test: concurrent parent replacement ----------------------
_HOSTILE_SCRIPT = r"""
import os, sys, time, pathlib
root, outside, delay = sys.argv[1], sys.argv[2], float(sys.argv[3])
time.sleep(delay)
try:
    os.rename(root, root + "__moved")
    os.symlink(outside, root, target_is_directory=True)
    print("HOSTILE_WON")
except Exception as exc:
    print("HOSTILE_FAILED", exc)
"""


def test_c04_concurrent_parent_replacement_is_prevented(tmp_path):
    """A real competing OS process swaps the root mid-flight.

    Prevention proof: the effect must land in the ORIGINAL directory object
    (now renamed), never in the attacker's symlink target.
    """
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "attacker"
    outside.mkdir()

    script = tmp_path / "hostile.py"
    script.write_text(_HOSTILE_SCRIPT)

    with NativeContainment(root) as nc:
        attacker = subprocess.Popen(
            [sys.executable, str(script), str(root), str(outside), "0.05"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            identity = nc.create_exclusive("effect.txt", CONTENT)
            # The pinned handle resolves the leaf INSIDE the authorized
            # directory object regardless of any path the attacker arranges.
            reopened = nc.open_existing_relative("effect.txt")
        finally:
            out, _ = attacker.communicate(timeout=30)

    assert identity is not None
    assert reopened == identity, "handle-relative reopen must be identity-stable"

    # PREVENTION PROOF: nothing exists in the attacker's directory.
    assert list(outside.iterdir()) == [], (
        f"ESCAPE: attacker directory contains {list(outside.iterdir())}"
    )
    assert not (outside / "effect.txt").exists()

    # The effect is retrievable from whichever directory object is now named
    # 'root' - proving the write followed the AUTHORIZED OBJECT, not the name.
    holder = root if (root / "effect.txt").exists() else tmp_path / "root__moved"
    assert (holder / "effect.txt").exists()
    assert (holder / "effect.txt").read_bytes() == CONTENT


def test_c05_competing_process_cannot_plant_a_symlink_at_the_leaf(tmp_path):
    """Attacker pre-plants a symlink at the exact leaf. Exclusive create and
    FILE_OPEN_REPARSE_POINT must both refuse to write through it."""
    if not _symlinks_available(tmp_path):
        pytest.skip("symlink creation unavailable on this platform")
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "attacker"
    outside.mkdir()
    (root / "effect.txt").symlink_to(outside / "victim.txt")

    with NativeContainment(root) as nc:
        with pytest.raises(ContainmentViolation):
            nc.create_exclusive("effect.txt", CONTENT)
        with pytest.raises(ContainmentViolation):
            nc.open_existing_relative("effect.txt")

    assert list(outside.iterdir()) == []


# --- exclusivity, replay, substitution -------------------------------------
def test_c06_replay_and_overwrite_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with NativeContainment(root) as nc:
        nc.create_exclusive("effect.txt", CONTENT)
        with pytest.raises(ContainmentViolation):
            nc.create_exclusive("effect.txt", CONTENT)
    assert (root / "effect.txt").read_bytes() == CONTENT


def test_c07_executor_binds_authority_and_digest(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileExecutor(grant) as ex:
        identity = ex.execute(CONTENT)
        assert identity is not None
        assert ex.effect_calls == 1
        assert grant.authorized_target.read_bytes() == CONTENT
        observation = LocalFilesystemObserver(grant).observe()
        assert observation.matches_authorized is True


def test_c08_executor_denies_content_substitution(tmp_path):
    grant = _grant(tmp_path)
    with NativeCreateTestFileExecutor(grant) as ex:
        with pytest.raises(NativeEffectDenied) as exc:
            ex.execute(b"tampered")
        assert exc.value.code == "content-substitution"
        assert not grant.authorized_target.exists()


def test_c09_executor_denies_revoked_and_expired_authority(tmp_path):
    grant = _grant(tmp_path, revoked=True)
    with NativeCreateTestFileExecutor(grant) as ex:
        with pytest.raises(NativeEffectDenied) as exc:
            ex.execute(CONTENT)
        assert exc.value.code == "authority-revoked"
        assert not grant.authorized_target.exists()

    grant2 = _grant(tmp_path / "b")
    object.__setattr__(grant2.authority.ceiling, "valid_until", _iso(-1))
    with NativeCreateTestFileExecutor(grant2) as ex:
        with pytest.raises(NativeEffectDenied) as exc:
            ex.execute(CONTENT)
        assert exc.value.code == "authority-expired"
        assert not grant2.authorized_target.exists()


def test_c10_partial_write_never_reported_as_success(tmp_path):
    """A zero-byte write is legal at the primitive layer; what must never
    happen is a SUCCESS reported for content the authority did not bind.

    The raw primitive permits an empty file. Authority is what forbids it:
    the digest binding in the executor rejects unbound content. This test
    pins both halves of that statement rather than asserting a false one.
    """
    root = tmp_path / "root"
    root.mkdir()
    with NativeContainment(root) as nc:
        # Primitive layer: empty write is a legitimate, atomic create.
        nc.create_exclusive("empty.txt", b"")
        assert (root / "empty.txt").exists()
        assert (root / "empty.txt").read_bytes() == b""

    # Authority layer: an empty payload that the digest does not bind is
    # refused BEFORE any effect.
    grant = _grant(tmp_path / "b")
    with NativeCreateTestFileExecutor(grant) as ex:
        with pytest.raises(NativeEffectDenied) as exc:
            ex.execute(b"")
        assert exc.value.code == "content-substitution"
        assert not grant.authorized_target.exists()


def test_c11_concurrent_threads_single_winner(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    results, errors = [], []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        try:
            with NativeContainment(root) as nc:
                results.append(nc.create_exclusive("effect.txt", CONTENT))
        except ContainmentViolation as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1, f"expected 1 winner, got {len(results)}"
    assert len(errors) == 3
    assert (root / "effect.txt").read_bytes() == CONTENT


def test_c12_root_handle_identity_is_stable(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with NativeContainment(root) as nc:
        first = nc.root_identity
        nc.assert_root_unchanged()
        assert nc.root_identity == first
        nc.assert_root_unchanged()


def test_c13_m34_adapter_still_intact_and_unmodified(tmp_path):
    """M35 must not have altered the M34 adapter's behaviour."""
    from intent_kernel.adapters.local_filesystem import (
        CreateTestFileAuthority,
        LocalFileSystemExecutor,
    )

    grant = _grant(tmp_path)
    assert isinstance(grant, CreateTestFileAuthority)
    import asyncio

    receipt = asyncio.run(
        LocalFileSystemExecutor(grant).execute(_m34_contract(CONTENT))
    )
    assert receipt.effect_occurred is True
    assert grant.authorized_target.read_bytes() == CONTENT


def _m34_contract(content: bytes):
    from intent_kernel.runtime.models import ActionContract

    contract = ActionContract(
        action_id="m35", capability=CAPABILITY, action_type="CREATE_TEST_FILE",
        idempotency_key="m35-m34",
    )
    contract.inputs_reference = {"path": "effect.txt", "content": content.decode()}
    return contract