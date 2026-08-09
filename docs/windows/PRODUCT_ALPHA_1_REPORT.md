# Product Alpha 1 Report

Version: `0.3.0-alpha`.

Implemented: Portuguese first run, honest Provider states, DPAPI-protected OpenAI key, private stdio
bridge, canonical `ApplicationFactory`, real conversation, local history, separate demo mode,
settings, diagnostics, responsive simplified Shell, and update-compatible installer.

Gemini, email, calendar, contacts, and cloud stores remain **Em preparação**. No OAuth simulation or
password collection exists. The bridge opens no port and the UI has no concrete Kernel dependency.

Automated and build results are appended during release generation. Manual validation remains governed
by `MANUAL_TEST_PRODUCT_ALPHA_1.md`; the installer is not executed by the build agent.

## Validation evidence

- Product Alpha and Windows packaging tests: **20 passed**.
- Full Python suite: **570 passed, 3 failed**. The three failures are pre-existing environment-dependent
  checks: CP1252 decoding during source inspection, an empty installed-programs inventory in the isolated
  environment, and denied access to the legacy user-home PKB path.
- IDS and Shell JavaScript suite: **38 passed, 0 failed**.
- Product JavaScript syntax check: passed.
- Packaged `IntentOS.Bridge.exe` smoke test: startup and canonical Kernel status passed without an
  external Python installation or a listening network port.
- Visual checks: onboarding steps, explicit demonstration state, 1366x768, 1920x1080, and a reduced
  683x384 viewport completed without horizontal overflow.

## Manual validation still required

- The generated installer was intentionally **not installed or executed** by the build agent.
- A real OpenAI connection was not exercised because no API key was supplied to the build environment.
- Upgrade, uninstall, shortcut, persistence-after-restart, and real-provider conversation scenarios must
  be completed locally using `MANUAL_TEST_PRODUCT_ALPHA_1.md`.
- Gemini, e-mail, calendar, contacts, and cloud storage connectors are explicitly marked **Em preparação**.

The release is therefore a build-validated Product Alpha, not a claim of completed end-user acceptance.
