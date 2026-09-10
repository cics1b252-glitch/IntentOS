"""Pytest configuration for Intent OS tests.

Provides fixtures for test isolation using temporary directories.
M32A tests MUST use isolated temporary directories via tmp_path fixture.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import os
import sys
import tempfile


def _make_isolated_store_root(tmp_path: Path) -> Path:
    """Create isolated authority store root under tmp_path."""
    return tmp_path / ".intent-os"


@pytest.fixture
def m32a_isolated_store_root(tmp_path: Path) -> Path:
    """Provide an isolated store root for M32A tests.

    Usage:
        def test_something(m32a_isolated_store_root):
            store = create_json_file_rrm_state_store(
                authority_file=m32a_isolated_store_root / "rrm" / "authority.json",
                continuity_file=m32a_isolated_store_root / "continuity" / "identity.json",
            )
    """
    root = _make_isolated_store_root(tmp_path)
    (root / "rrm").mkdir(parents=True, exist_ok=True)
    (root / "continuity").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def fresh_authority_state(m32a_isolated_store_root: Path):
    """Provide a clean authority state for tests that need it.

    Usage:
        def test_something(fresh_authority_state):
            # authority_state_path is fresh_authority_state
            ...
    """
    yield m32a_isolated_store_root

# This configuration owns test isolation only; production never detects pytest.
_REAL_INTENT_OS = os.path.normcase(os.path.abspath(os.environ.get("INTENTOS_TEST_PROTECTED_ROOT", Path.home() / ".intent-os")))
_GUARD_ENABLED = False
_SESSION_HOME_PATCH = None


def _guard_user_state(event, args):
    if not _GUARD_ENABLED:
        return
    if event not in {
        "open", "os.listdir", "os.scandir", "os.mkdir", "os.remove",
        "os.rmdir", "os.rename", "os.chmod", "os.utime", "os.truncate",
        "os.link", "os.symlink",
    }:
        return
    for value in args[:2]:
        if isinstance(value, (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(value)))
            if path == _REAL_INTENT_OS or path.startswith(_REAL_INTENT_OS + os.sep):
                raise RuntimeError("Tests must not access real user .intent-os state")


sys.addaudithook(_guard_user_state)


def pytest_configure(config):
    """Isolate even collection-time default home paths before test imports."""
    global _GUARD_ENABLED, _SESSION_HOME_PATCH
    _GUARD_ENABLED = True
    home = Path(tempfile.mkdtemp(prefix="intentos-pytest-home-"))
    _SESSION_HOME_PATCH = pytest.MonkeyPatch()
    _SESSION_HOME_PATCH.setenv("HOME", str(home))
    _SESSION_HOME_PATCH.setenv("USERPROFILE", str(home))


def pytest_unconfigure(config):
    global _GUARD_ENABLED
    if _SESSION_HOME_PATCH is not None:
        _SESSION_HOME_PATCH.undo()
    _GUARD_ENABLED = False


@pytest.fixture(autouse=True)
def isolated_intent_os_home(tmp_path, monkeypatch):
    """Redirect all default persistence to a fresh per-test fake home.

    Explicit authority/continuity paths remain explicit, so restart tests can
    intentionally reuse their own temporary store. No real path is cleaned.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home / ".intent-os"
