# Intent OS Recovery Cycle — Movements 1–3

## STATUS

Product P0 repairs complete on the canonical repository. The Python product
baseline is green after excluding two environment-only checks that the managed
workspace cannot satisfy.

## REPOSITORY

`cics1b252-glitch/IntentOS`

## BASE BRANCH

`main`

## WORKING BRANCH

`recovery/canonical-product`

## STARTING SHA

`76cdd5cb39b5e0f59d8144907b30373de4e95884`

## AUTHORITATIVE TEST COMMAND

Environment: Windows 10, Python 3.12.13, pytest 9.1.1,
pytest-asyncio 1.4.0 and pytest-cov 7.1.0. Dependencies were installed from
the declared `dev,server` extras into an isolated `.venv`.

```powershell
.\.venv\Scripts\pytest.exe -ra --tb=short
```

The executable entry point is intentional. Running `python -m pytest` from the
repository root imports the historical local `pytest.py` compatibility shim
instead of the real pytest package and is not authoritative.

## TEST COUNT BEFORE

- Collected: 887
- Passed in the managed workspace: 873
- Product failures: 12
- Environment-only failures: 2
- Historical independent result: 875 passed, 12 failed

The two additional failures are caused by the managed workspace: installed
program discovery is unavailable and writes to `%USERPROFILE%\.intent-os` are
denied. Test discovery matches the independent audit exactly.

## FAILURES BEFORE

- two conversational continuity/restart failures;
- seven Product Alpha 2.1.4 first-intent/telemetry failures;
- one RFC-0017.2 multi-turn failure;
- one canonical Mission completion failure;
- one Provider discovery contract that fabricated Gemini availability.

## STUDIO PATCH RECONSTRUCTION

Only the required behavior was reconstructed on top of the canonical
`product_bridge.py`. No historical bridge file was copied wholesale.

- zero external Provider now returns local BCC capability guidance or UNKNOWN;
- AME candidates retain the request `project_id`;
- question-shaped inputs are not ingested as facts/preferences;
- memory retrieval survives restart and remains project-isolated;
- financial and application continuity keep the same mission identifier.

## FINANCIAL PARSING

Contextual parsing supports `23500`, `23.500`, `R$ 23.500`, `23.500,00`,
`R$ 23.500,00`, `24 mil`, `24k` and the supported written-number form. Numbers
in age, source-line and distance statements are not interpreted as money.

## MULTI-TURN CONTINUITY

The follow-up `com aportes mensais` resolves the pending recurrence field,
clears the pending dialogue, advances the state and preserves the mission ID,
including after a ProductBridge restart.

Spreadsheet requests are handled as productivity requests and do not trigger
Android/iOS/Web questions.

## MISSION COMPLETION

The canonical route now completes the Mission after successful capability
execution. Completed Missions no longer appear in `MissionStore.list_active()`.

## PROVIDER DISCOVERY

Discovery reflects actual configuration. With no Gemini key/configuration,
Gemini is absent and the local mock remains an internal offline implementation;
it is never presented as an external Provider response.

## TEST COUNT AFTER

- Collected: 902 (887 existing + 15 recovery tests)
- Passed: 900
- Environment-only failures: 2
- Product failures: 0
- Subtests: 12 passed

Environment-neutral verification command:

```powershell
.\.venv\Scripts\pytest.exe -q `
  --deselect tests/test_symbiotic.py::test_programs_detected `
  --deselect tests/test_symbiotic.py::test_sync_with_kernel
```

Result: `900 passed, 2 deselected, 12 subtests passed`.

## RESULTS

All Movement 1–3 product contracts pass: finance, multi-turn continuity,
Mission completion, honest Provider discovery, zero-Provider behavior, memory
restart, project isolation and spreadsheet classification.

## COVERAGE

Global statement/branch coverage: 80% using:

```powershell
.\.venv\Scripts\pytest.exe --cov=intent_kernel --cov=product_bridge `
  --cov-report=term --cov-report=json:.artifacts\coverage.json
```

## FILES CHANGED

- `product_bridge.py`
- `intent_kernel/kernel.py`
- `tests/test_intent_gateway.py`
- `tests/test_recovery_canonical_product.py`
- `docs/RECOVERY_CYCLE_MOVEMENTS_1_3.md`

## COMMITS CREATED

Recorded after final commit.

## PUSH STATUS

Recorded after final push.

## REMOTE VERIFICATION

Recorded after remote SHA verification.

## ENDING SHA

Recorded after final commit.

## KNOWN ISSUES

- The managed workspace cannot enumerate installed programs or write outside
  its approved roots; these are environmental, not product regressions.
- The separate JavaScript Gateway suite has one pre-existing IUE contract
  mismatch: it expects an execution plan while the ECC is correctly waiting
  for missing financial context. Six of seven Gateway checks pass when a
  `python3` executable alias is available on Windows.
- `pytest.py` remains historical compatibility code and must not define the
  authoritative pytest invocation.

## BASE44 AUDIT HANDOFF

Audit only:

- repository: `cics1b252-glitch/IntentOS`
- branch: `recovery/canonical-product`
- verify the complete suite, coverage, regressions, architecture,
  canonical/legacy paths, RFC conformity and Constitution enforcement;
- do not implement fixes during the audit.

## NEXT MOVEMENTS

1. Independent Base44 audit of the remote branch.
2. Decide whether to align the JavaScript IUE test with WAITING_CONTEXT or
   change the Gateway response contract in a dedicated mission.
3. Run the two Symbiotic environment checks on an unrestricted Windows host.
4. Do not merge to `main` until the independent audit is accepted.
