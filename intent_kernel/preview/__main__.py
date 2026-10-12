"""FRONT-TP-06A: local interactive Technical Preview CLI.

    python -m intent_kernel.preview

Design constraints (TP-06A):

* The ONLY way to approve is to TYPE ``APPROVE`` at the interactive prompt.
* There is deliberately NO ``--approve``, ``--yes``, ``--force``, environment
  bypass, or non-interactive auto-confirmation. Any such argument is REJECTED
  rather than ignored, so it can never silently become a bypass.
* No trusted approval is minted until the operator has actually confirmed.
  The proposal is displayed FIRST; the token does not exist before that.
* The approval token is never printed, logged or serialized.
* Only the existing CREATE_TEST_FILE preview capability is executed.
* Local-only: this module starts no server and adds no HTTP route.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence

from intent_kernel.preview.local_harness import (
    DEFAULT_CONTENT,
    PreviewDenied,
    prepare_disposable_root,
    propose_preview,
    run_preview,
    safe_dispose,
)

CONFIRM_WORD = "APPROVE"
BANNER = (
    "INTENT OS - GOVERNED LOCAL TECHNICAL PREVIEW\n"
    "This performs ONE real, authorized filesystem effect in an isolated\n"
    "disposable directory and verifies it independently.\n"
)

#: Arguments that would constitute an approval bypass. They are rejected.
FORBIDDEN_SWITCHES = (
    "--approve", "--yes", "-y", "--force", "--auto", "--auto-approve",
    "--no-confirm", "--assume-yes", "--allow",
)


SECURITY_NOTICE = """
LOCAL SECURITY NOTICE - GOVERNED TECHNICAL PREVIEW
---------------------------------------------------
* TRUSTED OPERATOR ONLY. This performs a REAL filesystem effect. Run it only
  on a machine and account you control, and only when you intend the effect.
* IN-PROCESS BEARER TOKEN. The trusted approval is a single-use token held in
  this process's memory. Code executing inside this process can read or mint
  one. This control raises the bar against remote/untrusted callers; it is not
  a defence against local code execution.
* RUNTIME MUTATION LIMITATION. The shared MissionRuntime.executor is a plain
  attribute. In-process code that assigns it directly can affect an in-flight
  dispatch. Use only the supported path (this CLI).
* WINDOWS ONLY. Effects use the undocumented ntdll NtCreateFile with a pinned
  directory handle. Unsupported platforms fail closed with no fallback.
* NO NETWORK OR MULTI-USER PRODUCTIVE USE. This entry point is local and
  single-operator. Do not expose it as a service, share a root between users,
  or point it at documents or paths you do not own.
* NO WILDcards, NO IMPLICIT AUTHORITY. The capability is exactly
  CREATE_TEST_FILE inside one disposable directory, bound to one content
  digest, and only for an interactive APPROVE.
"""


class NonInteractiveRefusal(RuntimeError):
    """Approval requires a real interactive TTY. Piped input is refused."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m intent_kernel.preview",
        description="Governed local Technical Preview (CREATE_TEST_FILE only).",
    )
    parser.add_argument("--file-name", default="governed-preview.txt",
                        help="exact target file name (single component only)")
    parser.add_argument("--message", default=None,
                        help="content to write (default: standard preview text)")
    parser.add_argument("--root", default=None,
                        help="parent directory for the disposable root")
    return parser


def read_confirmation(stream=None) -> Optional[bool]:
    """Read the operator's explicit decision from an interactive stream.

    Returns True only for the exact word ``APPROVE``. Empty input, EOF, or
    anything else is a DECLINE. Never raises past this function.
    """
    stream = stream or sys.stdin
    try:
        response = stream.readline()
    except Exception:
        return False
    if response == "":            # EOF: no decision was made
        return False
    return response.strip() == CONFIRM_WORD


def run_cli(argv: Optional[Sequence[str]] = None,
            stdin=None, stdout=None) -> int:
    """Run the interactive preview. Returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    out = stdout or sys.stdout

    # Reject any bypass switch outright rather than ignoring it.
    for arg in argv:
        if arg.split("=", 1)[0].lower() in FORBIDDEN_SWITCHES:
            out.write(
                f"REFUSED: '{arg}' is not supported. Approval requires typing "
                f"'{CONFIRM_WORD}' interactively.\n")
            return 2

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Fail closed when there is no interactive terminal: approval cannot be
    # given by a pipe, a heredoc, or CI.
    stream = stdin or sys.stdin
    is_tty = False
    try:
        is_tty = bool(stream.isatty())
    except Exception:
        is_tty = False
    if not is_tty:
        raise NonInteractiveRefusal(
            "interactive terminal required; approval cannot be non-interactive")

    out.write(BANNER)
    out.write(SECURITY_NOTICE)
    from pathlib import Path

    root = prepare_disposable_root(
        Path(args.root) if args.root else None)
    content = (
        args.message.encode("utf-8")
        if args.message is not None
        else DEFAULT_CONTENT
    )
    try:
        proposal = propose_preview(
            root=root, target_name=args.file_name,
            **({"content": content} if content is not None else {}),
        )
        # Bind the SAME bytes to execution. run_preview independently checks
        # the content digest against the proposal, so passing anything else
        # here would be refused as content-changed-after-proposal.
        execution_content = content
    except PreviewDenied as exc:
        out.write(f"PREVIEW UNAVAILABLE: {exc.code} ({exc.detail})\n")
        return 3

    out.write("\n" + proposal.render() + "\n\n")

    # No trusted approval exists at this point. It can only be created after
    # the operator confirms below.
    out.write(
        f"Type '{CONFIRM_WORD}' to authorize this exact effect.\n"
        "Anything else (including empty input or EOF) declines.\n> "
    )
    out.flush()

    approved = read_confirmation(stream)
    if approved is not True:
        out.write(
            "\nDECLINED - no authority was established, no effect run.\n")
        # TP-06C: the CLI OWNS its disposable root and cleans it on every
        # terminal outcome, including decline, empty input, EOF and invalid
        # confirmation. Nothing outside a disposable root is ever removed.
        disposed = safe_dispose(root)
        state = ("removed" if disposed["removed"]
                 else "RETAINED (" + disposed["reason"] + ")")
        out.write(f"Disposable root cleanup: {state}\n")
        return 1

    # Only NOW may an authority and a trusted approval be created.
    report = run_preview(proposal, content=execution_content,
                         operator_approved=True, cleanup=True)
    out.write("\n" + report.render() + "\n")
    if report.outcome == "VERIFIED":
        out.write(
            "\nIndependent verification confirmed the exact authorized bytes.\n")
        return 0
    out.write(f"\nDENIED: {report.reason}\n")
    return 1


def main() -> int:
    try:
        return run_cli()
    except NonInteractiveRefusal as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
