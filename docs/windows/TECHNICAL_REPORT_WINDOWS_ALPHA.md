# Technical Report — Windows Host & Installer Alpha

## Implemented

- Self-contained .NET 8 WinForms host with embedded WebView2.
- Existing Cognitive Shell/IDS loaded locally through a virtual origin.
- Single-instance guard, resizable window, local preference and lifecycle logging.
- Per-user setup with staged/validated extraction, shortcuts, HKCU registration, and uninstall.
- Preserve/delete-data choice, portable ZIP, metadata, checksums, manifest, and documentation.

## Automated validation

Tests validate resource paths, version consistency, program/data separation, local-only hosting,
self-contained build policy, missing-resource handling, setup/uninstall contract, and Shell reuse.
The build runs the full Python suite unless explicitly skipped.

Validation on 2026-08-03 (Windows 10.0.19045, Python 3.13, .NET SDK 8.0.423):

- Windows/Shell focused Python tests: **13 passed, 0 failed**.
- IDS + Cognitive Shell JavaScript tests: **38 passed, 0 failed**.
- Full Python repository suite: **558 passed, 3 environment-dependent historical failures**.
  The failures are the existing default-encoding read in `test_kernel_no_external_imports`, sandboxed
  installed-program discovery, and a sandbox-denied write to the legacy `~/.intent-os` PKB path.
  No new Windows Alpha test fails.
- Host and setup: successful Release self-contained compilation. The WebView2 package emits an
  MSBuild `WindowsBase` version-resolution warning; compilation completes with zero errors.
- Portable archive: required `app/IntentOS.exe`, `ui/shell/index.html`, and `version.json` verified.
- Setup was not executed, so no installation was performed on the user's computer.

## Security

No port, required remote script, Kernel, provider, credential, or API key is packaged. Logs exclude
interaction content. Installation uses only the user profile and HKCU.

## Manual validation and limitations

Clean-machine installation, restart, SmartScreen, and Installed apps UI confirmation require local
human execution with the checklist and are not claimed yet. This is demonstration data only: there is
no Kernel integration, auto-update, signing, onboarding, provider, cloud, microphone, or real PKB.
The standard WebView2 Runtime is required. The application identity/icon remains provisional.
