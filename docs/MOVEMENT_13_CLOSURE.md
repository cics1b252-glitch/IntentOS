# Movement 13 — Resource / Binding / Registry Convergence

## Closure status

- Status: `MOVEMENT_13_VERIFIED`
- Verified HEAD: `e6a23afab6393ac631ef619293fa490290d42146`
- Canonical branch: `architecture/resource-binding-registry-convergence`
- Movement 13 initial checkpoint: `255e7536c1c98adb05879e36f6dda68ed14a768b`
- Movement 12 closure base: `9c0ab87e8dd5fada1aae861e3f196a9d547967e8`

## Commit chain

1. `255e7536c1c98adb05879e36f6dda68ed14a768b` — `refactor: converge resource binding authority`
2. `e6a23afab6393ac631ef619293fa490290d42146` — `fix: preserve exact canonical binding identity`

## Final authority model

| Authority | Role | Owns |
| --- | --- | --- |
| RRM | `CANONICAL_AUTHORITY` | runtime availability and eligibility |
| CanonicalCapabilityRegistry | `REGISTRY_ONLY` | known executable binding objects |
| CanonicalResourceBindingAuthority | `CANONICAL_AUTHORITY` | deterministic exact binding selection and revalidation |
| CapabilityExecutionService | `EXECUTION_BINDING` | consumes and dispatches the selected canonical binding |
| CapabilityRouter | `COMPATIBILITY_ONLY` | legacy routing surface on the canonical architecture |
| CanonicalProviderAuthority | `CANONICAL_AUTHORITY` | provider selection constrained by RRM |
| ProviderManager / ManagedProvider | `EXECUTION_BINDING` | selected provider identity and actual invocation evidence |
| ToolAuthorizationGate | `AUTHORIZATION_ONLY` | authorization decisions |
| MissionRuntime | `EXECUTION_BINDING` | mission execution |
| Compatibility paths | `COMPATIBILITY_ONLY / subordinate` | legacy behavior contained from canonical authority |

Canonical Core App dispatch uses the exact selected registration and performs
no second binding lookup.

## Primary invariants

```text
REGISTERED != AVAILABLE != ELIGIBLE != SELECTED != AUTHORIZED != ATTEMPTED != USED != VERIFIED
```

And for successful canonical execution:

```text
SELECTED BINDING = REVALIDATED BINDING = AUTHORIZED BINDING = DISPATCHED BINDING
```

## Historical blocker — RA-13-01

Before repair:

Core App A could be selected, revalidated and authorized while CapabilityRouter
performed a second lookup and executed replacement Core App B with the same
logical ID.

Observed before:

```text
A calls = 0
B calls = 1
```

Root cause:

CapabilityExecutionService discarded the selected executable reference and
called CapabilityRouter by capability name.

Repair:

Canonical execution now preserves exact binding identity through dispatch.
`CapabilityRouter.execute_exact` consumes the selected registration and invokes
its exact executor.

Verified after repair:

```text
selected = A
revalidated = A
authorized = A
dispatched = A

A calls = 1
B calls = 0
```

Replacement B cannot inherit authorization merely by sharing `app_id` /
`capability`.

## TOCTOU / identity results

The final independent audit verified:

- router mapping replacement cannot substitute executor;
- registry removal fails closed;
- registry replacement fails closed;
- same logical ID with different object cannot inherit execution;
- health change before dispatch fails closed;
- RRM availability change before dispatch fails closed;
- authorization denial prevents execution;
- provider replacement after selection fails closed;
- provider invocation evidence remains truthful.

## Movement 11 / 12 regressions

- Movement 11 critical authority invariants: `PASS`
- Movement 12 product semantic authority: `PASS`
- RA-01 provider evidence: `PASS`
- XZ-91: `PASS`
- Memory isolation / current truth: `PASS`
- Mission completion authority: `PASS`
- Compatibility trace truth: `PASS`

## Validation baseline

- Python: `1117 passed`, `12 subtests passed`, `1 environmental failure on Windows`
- Environmental failure: `tests/test_symbiotic.py::test_programs_detected` —
  Unix-only `which`, pre-existing, not a Movement 13 defect
- Linux reference: `1118 total expected` after `+18` Movement 13.1 tests
- Coverage: `82%`
- `compileall`: `PASS`
- `git diff --check`: `PASS`
- Movement 13 authority map JSON: `PASS`
- JavaScript: `JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE`

Node/npm unavailable in the OpenCode audit environment. JavaScript PASS is not
claimed.

## Known limitations

- compatibility routes remain active but subordinate;
- registry / tool legacy retirement still requires migration parity evidence;
- provider invocation telemetry remains execution evidence, not a per-request
  historical ledger;
- productive external execution remains disabled;
- JavaScript validation unavailable in the final OpenCode audit environment;
- Windows symbiotic program-detection test retains a pre-existing Unix-only
  assumption.

None are Movement 13 blockers.

## Movement 14 readiness

- Movement 14: `READY`
- But: `NOT STARTED`.

Movement 14 requires separate explicit authorization after closure
publication.
