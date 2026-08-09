# Sprint 8 Progress — Domain Migration and Legacy Reduction

## Executive summary

Sprint 8 moved Finance, knowledge-oriented work and Engineering into the
canonical capability pipeline while preserving characterized external
behavior. No legacy file was deleted. Atlas, Logos and OEM Studio are now the
official owners of their domains in the Composition Root.

Migrated routes execute through Mission Engine, Constitution,
`CapabilityExecutionService`, `CapabilityRouter`, registry and Core App.
Canonical provider calls use the Provider Port. Candidate knowledge continues
through the canonical Knowledge Pipeline. Missing canonical dependencies fail
explicitly rather than silently falling back.

`ModuleRouter` remains a compatibility facade for unmigrated domains and direct
historical consumers. The Monitor exposes migration telemetry and direct
dependency counts.

## Implemented

- Atlas owns `finance.intent`.
- Logos owns `knowledge.intent` for Research, Writing, Planning and Education.
- OEM Studio owns `engineering.intent` for Engineering and Programming.
- Atlas retains FIN internally only to preserve exact historical output.
- Logos and OEM Studio preserve existing provider prompts and response shape.
- The factory-created `LegacyCapabilityExecutorAdapter` delegates migrated
  capabilities to the governed canonical execution service.
- `MigrationTelemetry` records canonical, fallback and legacy calls.
- Migrated-route tests prove that `ModuleRouter` is not invoked.
- Historical Capability Registry and Agent Orchestrator are absent from the
  official runtime graph and remain available only for compatibility.

## Test evidence

Environment:

- Windows 10 build 19045;
- Python 3.13;
- repository virtual environment;
- branch `feat/openai-integration`.

Commands:

```powershell
.\.venv\Scripts\python.exe -m compileall -q intent_kernel intent_os_desktop tests
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

- collected: 538;
- passed: 535;
- failed: 3;
- skipped: 0;
- collection errors: 0;
- warnings: 0.
- global statement/branch coverage: 80%.

All 16 Sprint 8 tests pass. The three full-suite failures are unchanged
environmental baseline blockers:

1. a test reads UTF-8 source with the Windows cp1252 default;
2. the sandbox reports no installed programs;
3. the sandbox denies writes to the real user PKB path.

Sprint 8 does not modify tests or production behavior to conceal these known
conditions.

## Parity and edge cases

Covered:

- visible-output parity for Finance, Research, Writing, Planning, Education and
  Engineering;
- canonical owner selection and no legacy router call for migrated domains;
- explicit fallback telemetry for an unmigrated domain;
- governed legacy capability delegation;
- empty knowledge query and candidate persistence through the canonical
  pipeline;
- explicit store failure;
- provider failure and unavailable engineering capability;
- production import boundaries;
- absence of historical authorities from the official graph;
- user entry points using the Composition Root.

Programming is canonically assigned to OEM Studio, but the existing classifier
can classify common programming terms as Education due to keyword precedence.
That imperfection is documented and intentionally unchanged.

## Architecture status

- estimated total v2 migration: 99%;
- declared domain routes with canonical owners: 50%;
- fully classifier-reachable canonical domain routes: 6 of 14;
- source legacy removed: none, by mission rule;
- active legacy use narrowed to documented compatibility and unmigrated domains.

## Remaining risks

1. Seven generic domains still use the `CoreModule` fallback.
2. Programming classification precedence prevents full runtime ownership.
3. Atlas still delegates finance logic to FIN for parity.
4. Direct `Kernel()` can still compose compatibility defaults.
5. Historical public APIs cannot be removed until external consumers are known.
6. Dependency counts are repository evidence, not proof about downstream users.

## Recommended next step

Sprint 9 should migrate one coherent set of remaining generic domains, starting
with classifier ownership and explicit capability contracts. Compatibility
code must remain until repository search, downstream review, parity, rollback
and deprecation criteria all pass.
