# SUPPORT CONTRACT — Governed Local Technical Preview

## Supported environment (executable evidence)

| Item | Value | Evidence |
|------|-------|----------|
| Python | 3.13.14 (tested), 3.14 (available, untested) | `python --version` |
| Python 3.11 / 3.12 | **NOT TESTED** — interpreters unavailable | `py -0p` |
| Windows | 10 Home Single Language, build 19045 | `Get-CimInstance Win32_OperatingSystem` |
| POSIX (Linux/macOS) | **NOT TESTED** — containment path implemented but unexposed | `platform_capabilities()` |

`requires-python = ">=3.13"` is the narrowest declaration supported by
executable evidence. It is deliberately NOT `>=3.11`.

## Native containment dependency

The preview uses `NtCreateFile` (ntdll) with `OBJECT_ATTRIBUTES.RootDirectory`
to anchor filesystem operations to a pinned directory handle. This is an
**undocumented Windows API**. It is stable in practice on Windows 10 build
19045 but carries no Microsoft API-compatibility guarantee.

There is **no supported-API fallback**. On any platform where
`platform_capabilities()` reports `preventive: false`, the preview fails
closed with `platform-not-supported`. It never degrades to a weaker
filesystem executor.

## Installation

```bash
pip install intent-kernel
```

The package declares `pydantic>=2.0` as a dependency for the wider
application. The preview CLI itself imports **no** third-party package
(verified by import-graph audit), but the dependency is not removed because
the application needs it.

## Launch

```bash
intentos-preview
```

or equivalently:

```bash
python -m intent_kernel.preview
```

Both invoke the same governed CLI. The console script is declared in
`pyproject.toml` under `[project.scripts]`.

## Operator workflow

1. The CLI creates an isolated disposable directory under the system temp
   root, prefixed `intentos-preview-`.
2. It displays the exact proposed scope: capability, operation, authorized
   root, exact target, content SHA-256, risk level, side-effect
   classification, verification requirement, and validity window.
3. The operator must type `APPROVE` at the interactive prompt.
4. Any other input — including empty, EOF, `approve`, `yes`, `APPROVED` —
   declines.
5. Non-interactive stdin (piped, heredoc, CI) is refused outright.
6. No `--approve`, `--yes`, `--force` or similar flag is accepted; each is
   rejected with exit code 2.
7. On approval, one `CREATE_TEST_FILE` effect executes inside the
   disposable root, bound to the exact content digest.
8. The result is independently observed from the host filesystem and
   displayed with the observed SHA-256.
9. The disposable root is removed on terminal outcomes.

## Security notice

- **Trusted operator only.** This performs a real filesystem effect. Run it
  only on a machine and account you control.
- **In-process bearer token.** The trusted approval is a single-use token
  held in process memory. Code executing inside this process can read or
  mint one. This control raises the bar against remote/untrusted callers;
  it is not a defence against local code execution.
- **Runtime mutation limitation.** The shared `MissionRuntime.executor` is
  a plain attribute. In-process code that assigns it directly can affect an
  in-flight dispatch. Use only the supported CLI path.
- **Windows only.** Effects use undocumented `NtCreateFile`. Unsupported
  platforms fail closed with no fallback.
- **No network or multi-user productive use.** This entry point is local and
  single-operator. Do not expose it as a service or share a root between
  users.

## Cleanup

The CLI owns its disposable root and removes it on every terminal outcome
(approval, decline, empty input, EOF, invalid confirmation, non-interactive
refusal, execution exception). Cleanup is bounded: only paths carrying the
`intentos-preview-` prefix are deleted; symlinks and reparse points are
refused; no directory sweep is performed. If removal fails, the path is
retained and reported, never guessed at.

## Recovery of abandoned roots

If the CLI crashes or is terminated before cleanup, its disposable root remains on disk. A recovery function can find and remove such roots, but **only** with the following guarantees:

- The path must carry the `intentos-preview-` prefix (necessary, not sufficient).
- A lock file `intentos-preview.lock` must exist inside it.
- That lock must be **exclusively openable**, meaning no live process holds it.

A directory matching the prefix but lacking a lock is **reported, never deleted**. A locked root means a live process holds it: retained.

**TOCTOU limitation (explicit):** the exclusive-lock test proves a root is not actively held. It does **not** prove immunity to a same-user process replacing the directory with a symlink between the lock check and the delete. That window is not eliminated by this design. Destructive recovery is therefore exposed only to trusted local invocation and is **not** run automatically.

`recover_abandoned_roots()` defaults to report-only (`delete=False`). Destructive recovery requires an explicit trusted local call with `delete=True`.

## Trusted local operator approval boundary

Native preview effects require a **trusted local operator approval**. The approval:

- Is minted only by a direct in-process call to `register_local_approval(authority_digest)`.
- Is never read from HTTP request body, `context`, environment variables, CLI arguments, planner or agent output.
- Binds to the **exact** authority digest returned by `propose_native_authority(request)`.
- Is **single-use**: consumed once, then burned.
- Expires after a bounded TTL (default 300 seconds).
- Uses constant-time comparison (`hmac.compare_digest`).

The plain HTTP entry (`dispatch`) never supplies a token, so the native route fails closed there. The trusted local entry (`dispatch_operator_approved`) requires a pre-existing token minted by the operator.

**`CALLER_ASSERTED_GRANT != APPROVED_AUTHORITY`**: an `IntentAuthorityGrant` proves only self-consistency, not approval. `SCOPE_DIGEST != APPROVAL_AUTHENTICITY`: the scope digest is computable by any caller. `AUTHENTICATED_CALLER != AUTHORIZED_APPROVER`: a valid API key authenticates the caller but cannot approve authority.

## What this is NOT

- Not a network service.
- Not a multi-user tool.
- Not a general filesystem utility.
- Not a supported-API guarantee for `NtCreateFile`.
- Not a defence against in-process code execution.
- Not automatic destructive cleanup.
