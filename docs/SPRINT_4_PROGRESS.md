# Sprint 4 — Canonical Constitution

## Executive summary

Sprint 4 establishes `CanonicalConstitutionEngine` as the official
governance authority for Intent OS v2. The Kernel, ApplicationFactory and
canonical PKB now share the same engine and the canonical
`ConstitutionVerdict` created in Sprint 1.

No legacy implementation was deleted. Existing checkers, models and seven
historical Guardians remain importable for compatibility and characterization.

## Final governance architecture

```text
Mission / Kernel / PKB
          |
          v
CanonicalConstitutionEngine
          |
          v
Six official Guardian contracts
          |
          v
Canonical ConstitutionVerdict
          |
          +--> constitution.audit --> EventPublisher / PKB audit trail
          |
          v
ConstitutionPipeline
          |
          v
Pipeline / Mission Engine
```

The `ConstitutionPipeline` provides an explicit authorization boundary. It
does not execute an operation when the canonical verdict denies it.

## Official Guardians

| Guardian | Responsibility |
|---|---|
| `SecurityGuardian` | Sensitive data and user sovereignty |
| `PolicyGuardian` | Constitutional policy and user authority |
| `ContinuityGuardian` | Mission and knowledge continuity |
| `MemoryGuardian` | Retention, deletion and knowledge heritage |
| `IntegrityGuardian` | Truth, confidence and structural integrity |
| `AuditGuardian` | Traceability of governance decisions |

Every Guardian implements the same `Guardian` protocol and returns a
`GuardianResult`. Resolution is centralized:

1. `DENY` has priority.
2. Advisory historical flags become `ALLOW_WITH_CONDITIONS`.
3. Otherwise the decision is `ALLOW`.

This preserves the previous non-blocking meaning of a flag.

## Canonical verdict and audit

Only `intent_kernel.contracts.ConstitutionVerdict` is emitted by the official
engine. It contains:

- decision;
- reason;
- violated rule;
- conditions;
- evidence;
- Constitution version;
- audit identifier;
- individual Guardian results.

Every evaluation creates a `ConstitutionAuditRecord` and publishes a
`constitution.audit` event. The canonical Knowledge Pipeline uses the same
engine and continues to publish its existing `knowledge.audit` event. This
keeps governance evidence and curation evidence separate but correlated.

## Compatibility

The following historical surfaces remain available:

- `Constitution.validate()` and the legacy synchronous verdict;
- `ConstitutionChecker` and its historical checker verdict;
- `LegacyConstitutionEngineAdapter`;
- the historical Guardian registry and seven Guardian classes;
- the old Curator adapters that still consume the historical checker.

They are compatibility boundaries, not additional official Constitutions.
No legacy file was removed or renamed.

## Integration points

- `Kernel` creates the canonical engine by default.
- `KernelBuilder` and `ApplicationFactory` expose the canonical engine.
- `ApplicationComponents` exposes the official `ConstitutionPipeline`.
- `KnowledgeManager` and `KnowledgePipeline` receive the same engine.
- CLI, FastAPI and Desktop continue to obtain the same Kernel through the
  existing composition root.

## Test results

Environment:

- Windows 10;
- Python 3.13.14;
- pytest 9.1.1;
- pytest-cov 7.1.0.

Commands:

```powershell
.\.venv\Scripts\python.exe -m compileall -q intent_kernel
.\.venv\Scripts\python.exe -m pytest --cov=intent_kernel --cov-report=term-missing -ra
```

Result:

- collected: 487;
- passed: 484;
- failed: 3;
- skipped: 0;
- collection errors: 0;
- warnings: 3;
- total coverage: 78%.

The three failures and three warnings are the same environment-dependent
baseline findings documented in `SPRINT_0_TEST_BASELINE.md`:

1. locale decoding in `test_kernel_independence.py`;
2. installed-program discovery in the sandbox;
3. write permission for the real user PKB path in `test_symbiotic.py`;
4. three pre-existing unawaited `KnowledgeManager.count` warnings.

Sprint 4 introduced 11 tests, all passing. There are no new regressions.

## Conformance with ArchitectureTarget v2

Completed in this Sprint:

- one official Constitution engine;
- one official Guardian contract;
- one canonical verdict;
- one governance pipeline;
- governance audit events;
- use of the composition root and Ports;
- PKB integration.

Estimated Constitution migration: **90%**.

Estimated total architecture migration: **82%**.

## Remaining legacy dependencies

- historical Guardian implementations and registry;
- `ConstitutionChecker` in the v2 legacy Curator adapter;
- synchronous `Constitution.validate()` facade;
- `intent_kernel.types.ConstitutionVerdict`;
- legacy checker verdict;
- display/monitor code that reports historical Guardians;
- direct legacy bootstraps preserved for compatibility.

These remain intentionally. Their removal requires usage evidence and a
separate deprecation/migration Sprint.

## Risks for Sprint 5

1. Removing old verdict types prematurely could break plugins or direct
   imports not represented by the current test suite.
2. Persisting Constitution audit records as ordinary knowledge would create
   recursive validation; audit events must remain a dedicated evidence stream.
3. Monitor migration must distinguish official governance status from legacy
   Guardian diagnostics.
4. Policy and Memory Guardians currently centralize ownership but intentionally
   preserve permissive historical behavior. New enforcement rules would be a
   product change and require separate approval.
5. Baseline environment failures should be corrected only in an explicit
   stabilization mission, not hidden by architectural refactoring.

## Recommended next step

Sprint 5 should migrate observability and remaining callers to the canonical
governance API, add deprecation telemetry for historical surfaces and define
the evidence required before legacy removal. It must keep enforcement policy
changes outside the migration scope.
