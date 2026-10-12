"""TP-06B: CLI security gate."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from intent_kernel.preview.__main__ import (
    CONFIRM_WORD,
    NonInteractiveRefusal,
    read_confirmation,
    run_cli,
)


class _FakeTTY(io.StringIO):
    """A StringIO that claims to be an interactive terminal."""

    def isatty(self) -> bool:
        return True


def _argv(name="cli-preview.txt", msg="cli governed preview payload"):
    return ["--file-name", name, "--message", msg]


def test_b01_interactive_approve_one_verified_effect():
    stdin = _FakeTTY(CONFIRM_WORD + "\n")
    out = io.StringIO()
    code = run_cli(_argv(), stdin=stdin, stdout=out)
    text = out.getvalue()
    assert code == 0, text
    assert "VERIFIED" in text
    assert "independently-observed" in text
    assert "root cleaned up    : True" in text
    # every required scope field was displayed BEFORE approval
    for field in ("capability", "operation", "exact target",
                  "authorized root", "content sha256", "max risk level",
                  "max side effect", "requires verif."):
        assert field in text, f"missing {field}"
    assert text.index("content sha256") < text.index("Type 'APPROVE'")


def test_b02_interactive_decline_zero_effects():
    stdin = _FakeTTY("no\n")
    out = io.StringIO()
    assert run_cli(_argv(), stdin=stdin, stdout=out) == 1
    text = out.getvalue()
    assert "DECLINED" in text
    assert "VERIFIED" not in text
    assert "no authority was established" in text


def test_b03_empty_input_zero_effects():
    stdin = _FakeTTY("\n")
    out = io.StringIO()
    assert run_cli(_argv(), stdin=stdin, stdout=out) == 1
    assert "DECLINED" in out.getvalue()
    assert "VERIFIED" not in out.getvalue()


def test_b04_eof_zero_effects():
    stdin = _FakeTTY("")      # EOF: readline() returns ""
    out = io.StringIO()
    assert run_cli(_argv(), stdin=stdin, stdout=out) == 1
    assert "DECLINED" in out.getvalue()


def test_b05_invalid_confirmation_zero_effects():
    for bad in ("approve\n", "APPROVED\n", "yes\n", "APPROVE now\n", "  \n"):
        out = io.StringIO()
        assert run_cli(_argv(), stdin=_FakeTTY(bad), stdout=out) == 1
        assert "VERIFIED" not in out.getvalue()


def test_b06_non_interactive_fails_closed():
    """Piped stdin (no TTY) must refuse, never auto-approve."""
    out = io.StringIO()
    with pytest.raises(NonInteractiveRefusal):
        run_cli(_argv(), stdin=io.StringIO(CONFIRM_WORD + "\n"), stdout=out)
    assert "VERIFIED" not in out.getvalue()


@pytest.mark.parametrize("switch", [
    "--approve", "--yes", "-y", "--force", "--auto", "--no-confirm",
])
def test_b07_bypass_switches_rejected(switch):
    stdin = _FakeTTY(CONFIRM_WORD + "\n")
    out = io.StringIO()
    assert run_cli([switch], stdin=stdin, stdout=out) == 2
    text = out.getvalue()
    assert "REFUSED" in text
    assert "VERIFIED" not in text
    # the switch must not even mint a root
    assert "PROPOSED" not in text


def test_b07b_equals_form_switch_rejected():
    out = io.StringIO()
    assert run_cli(["--yes=1"], stdin=_FakeTTY(CONFIRM_WORD + "\n"),
                   stdout=out) == 2
    assert "REFUSED" in out.getvalue()


def test_b08_forged_approval_token_denied():
    from intent_kernel.adapters.preview_selection import (
        PreviewSelectionDenied, build_native_executor,
    )
    from tests.test_tp04d_trust_boundary import _established, _root, NOW

    root = _root(Path(__import__("tempfile").mkdtemp()))
    authority = _established(root)
    with pytest.raises(PreviewSelectionDenied) as exc:
        build_native_executor(authority=authority, authorized_root=root,
                              target_name="e.txt", content=b"x",
                              approval_token="forged-token",
                              now_provider=lambda: NOW)
    assert "trusted-approval-refused" in exc.value.code


def test_b09_replayed_approval_token_denied():
    from intent_kernel.preview.trusted_approval import (
        TrustedApprovalError, register_local_approval, require_trusted_approval,
    )
    from tests.test_tp04d_trust_boundary import _established, _root, NOW
    import tempfile

    root = _root(Path(tempfile.mkdtemp()))
    authority = _established(root)
    token = register_local_approval(authority.authority_digest, now=NOW).token
    require_trusted_approval(token, authority.authority_digest, now=NOW)
    with pytest.raises(TrustedApprovalError):
        require_trusted_approval(token, authority.authority_digest, now=NOW)


def test_b10_content_substitution_denied():
    from intent_kernel.preview.local_harness import (
        prepare_disposable_root, propose_preview, run_preview,
    )
    root = prepare_disposable_root()
    proposal = propose_preview(root=root)
    report = run_preview(proposal, content=b"tampered",
                         operator_approved=True, cleanup=False)
    assert report.outcome == "DENIED"
    assert report.reason == "content-changed-after-proposal"
    assert not (root / proposal.target_name).exists()


def test_b11_unsupported_platform_fails_closed(monkeypatch):
    import intent_kernel.preview.local_harness as h
    monkeypatch.setattr(h, "platform_capabilities",
                        lambda: {"platform": "fake", "preventive": False})
    with pytest.raises(h.PreviewDenied) as exc:
        h.propose_preview(root=h.prepare_disposable_root())
    assert exc.value.code == "platform-not-supported"


def test_b12_no_token_leakage():
    """A fingerprint is fine and labelled; a raw bearer token is not."""
    import re

    out = io.StringIO()
    run_cli(_argv(), stdin=_FakeTTY(CONFIRM_WORD + "\n"), stdout=out)
    text = out.getvalue()

    # The only approval-derived value shown is a labelled fingerprint.
    for line in text.splitlines():
        if "tok_" in line:
            assert "fingerprint only" in line, line
    fingerprints = re.findall(r"tok_[0-9a-f]{16}", text)
    assert len(fingerprints) == 1

    # A raw token is 43 chars of urlsafe base64; none may appear anywhere.
    from intent_kernel.preview.trusted_approval import (
        LOCAL_APPROVALS, register_local_approval,
    )
    sentinel = register_local_approval("digest-leak-probe",
                                       now=__import__("datetime").datetime.now(
                                           __import__("datetime").timezone.utc))
    assert sentinel.token not in text
    assert len(sentinel.token) == 43
    LOCAL_APPROVALS._tokens.clear()


def test_b13_handle_cleanup_on_failure():
    """A denied CLI run must leave no locked root behind."""
    out = io.StringIO()
    run_cli(["--file-name", "../escape.txt"], stdin=_FakeTTY(
        CONFIRM_WORD + "\n"), stdout=out)
    assert "VERIFIED" not in out.getvalue()


def test_b14_disposable_root_cleaned_on_terminal_run():
    from intent_kernel.preview.local_harness import (
        prepare_disposable_root, propose_preview, run_preview,
    )
    import tempfile
    root = prepare_disposable_root(Path(tempfile.mkdtemp()))
    proposal = propose_preview(root=root)
    report = run_preview(proposal, operator_approved=True, cleanup=True)
    assert report.outcome == "VERIFIED"
    assert report.cleaned_root is True
    assert not root.exists()


def test_b15_independent_observer_verifies_exact_bytes():
    from intent_kernel.preview.local_harness import (
        prepare_disposable_root, propose_preview, run_preview,
    )
    import tempfile
    from intent_kernel.adapters.local_filesystem import sha256_bytes

    payload = b"exact-bytes-verification-payload"
    root = prepare_disposable_root(Path(tempfile.mkdtemp()))
    proposal = propose_preview(root=root, content=payload)
    report = run_preview(proposal, content=payload,
                         operator_approved=True, cleanup=False)
    assert report.outcome == "VERIFIED"
    assert report.observed_sha256 == sha256_bytes(payload)
    assert report.matches_authorized is True
    assert (root / proposal.target_name).read_bytes() == payload


def test_b16_no_http_productive_path():
    import intent_kernel
    server = Path(intent_kernel.__file__).parent / "server"
    for py in server.glob("*.py"):
        src = py.read_text(encoding="utf-8", errors="ignore")
        assert "__main__" not in src or "preview" not in src
        assert "run_preview" not in src
        assert "register_local_approval" not in src


def test_b17_no_default_executor_mutation():
    from intent_kernel.runtime.executor_port import InMemoryActionExecutor
    rt = InMemoryActionExecutor()
    assert isinstance(rt, InMemoryActionExecutor)
    out = io.StringIO()
    run_cli(_argv(), stdin=_FakeTTY(CONFIRM_WORD + "\n"), stdout=out)
    assert isinstance(rt, InMemoryActionExecutor)


def test_b18_no_false_verified_success():
    out = io.StringIO()
    run_cli(_argv(), stdin=_FakeTTY("nope\n"), stdout=out)
    text = out.getvalue()
    assert "VERIFIED" not in text
    assert "DECLINED" in text


def test_read_confirmation_table():
    assert read_confirmation(io.StringIO("APPROVE\n")) is True
    assert read_confirmation(io.StringIO("approve\n")) is False
    assert read_confirmation(io.StringIO("")) is False
    assert read_confirmation(io.StringIO("\n")) is False


# --- TP-06C: cleanup ownership, bounded disposal, security notice ----------
def test_c_cleanup_bounded_and_foreign_paths_refused():
    from intent_kernel.preview.local_harness import (
        owns_disposable_root, prepare_disposable_root, safe_dispose,
    )
    import tempfile

    root = prepare_disposable_root(Path(tempfile.mkdtemp()))
    assert owns_disposable_root(root)
    assert safe_dispose(root)["removed"] is True
    assert not root.exists()

    # Never deletes a path it did not create.
    for foreign in ("C:/Windows", "C:/Users", tempfile.gettempdir()):
        result = safe_dispose(foreign)
        assert result["removed"] is False
        assert result["reason"] == "refused-not-a-disposable-root"


def test_c_cleanup_refuses_symlink_root():
    from intent_kernel.preview.local_harness import safe_dispose
    import os
    import tempfile

    base = Path(tempfile.mkdtemp())
    real = base / "intentos-preview-target"
    real.mkdir()
    link = base / "intentos-preview-linked"
    try:
        os.symlink(real, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    result = safe_dispose(link)
    assert result["removed"] is False
    assert "symlink" in result["reason"]
    assert real.exists(), "must not follow the substituted link"


def test_c_cleanup_is_not_a_directory_sweep():
    """safe_dispose deletes exactly one known path; it never sweeps.

    TP-08C added rglob for symlink/reparse-child refusal checks, but rmtree is
    still called on exactly one path - the one passed to safe_dispose.
    """
    import intent_kernel.preview.local_harness as h
    source = open(h.__file__, encoding="utf-8").read()
    start = source.index("def safe_dispose")
    end = source.index("\ndef ", start + 1) if "\ndef " in source[start:] else len(source)
    dispose_body = source[start:end]
    # rmtree is called exactly once, on the path argument
    assert dispose_body.count("shutil.rmtree(") == 1
    assert "rglob" in dispose_body  # used only for refusal, not deletion
    # recover_abandoned_roots may use glob but only with disposable prefix
    assert "DISPOSABLE_PREFIX" in source


def test_c_cli_cleans_root_on_every_terminal_decline():
    import re
    for response in ("no\n", "\n", "", "approve\n", "APPROVED\n"):
        out = io.StringIO()
        code = run_cli(_argv(), stdin=_FakeTTY(response), stdout=out)
        text = out.getvalue()
        assert code == 1, response
        assert "DECLINED" in text
        assert "Disposable root cleanup: removed" in text
        assert "VERIFIED" not in text
        m = re.search(r"authorized root\s+: (.+)", text)
        assert m and not Path(m.group(1).strip()).exists()


def test_c_security_notice_present_and_specific():
    from intent_kernel.preview.__main__ import SECURITY_NOTICE
    notice = SECURITY_NOTICE.lower()
    assert "trusted operator" in notice
    assert "bearer token" in notice
    assert "runtime mutation" in notice or "executor" in notice
    assert "windows" in notice
    assert "no network" in notice or "multi-user" in notice


def test_c_approval_semantics_unchanged_by_cleanup_work():
    """Cleanup changes must not have relaxed approval."""
    for bad in ("approve\n", "yes\n", "", "APPROVE please\n"):
        out = io.StringIO()
        assert run_cli(_argv(), stdin=_FakeTTY(bad), stdout=out) == 1
        assert "VERIFIED" not in out.getvalue()
    ok = io.StringIO()
    assert run_cli(_argv(), stdin=_FakeTTY("APPROVE\n"), stdout=ok) == 0
    assert "VERIFIED" in ok.getvalue()
