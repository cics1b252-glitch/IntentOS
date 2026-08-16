# MOVEMENT 14 — FORMAL CLOSURE

> Mission Confirmation / Resume / Verified Execution Convergence

## MOVEMENT

**14** — Mission Confirmation / Resume / Verified Execution Convergence

## STATUS

**MOVEMENT_14_VERIFIED**

## VERIFIED HEAD

`a3f31f764e676b9d7423a048e69f1352d461fcfd`

## MOVEMENT 13 CLOSURE BASE

`9d12768d65b4dbc431d2170a9f26644c72fef23e`

## COMMIT

```
a3f31f764e676b9d7423a048e69f1352d461fcfd
feat: add canonical mission confirmation resume
```

---

## FINAL MISSION AUTHORITY MODEL

| Authority | Classification | Responsibility |
|---|---|---|
| `MissionEngine` | **CANONICAL_AUTHORITY** | Owns canonical Mission identity and lifecycle. |
| `CanonicalConfirmationService` | **CONFIRMATION_ONLY** | Validates and consumes confirmation state. It cannot execute or complete a Mission. |
| `ToolAuthorizationGate` | **AUTHORIZATION_ONLY** | Authorization decision authority. |
| `ActionGate` | **CANONICAL_AUTHORITY** | Action safety and confirmation requirement. |
| `RRM` | **CANONICAL_AUTHORITY** | Resource availability/eligibility. |
| `CanonicalResourceBindingAuthority` | **CANONICAL_AUTHORITY** | Exact binding selection/revalidation. |
| `MissionRuntime` | **EXECUTION_BINDING** | Controlled execution, resume and run control. |
| `VerificationGate` | **VERIFICATION_ONLY** | Post-execution verification. |
| `MissionCompletionGate` | **COMPLETION_ONLY** | Sole authority for canonical Mission completion. |
| `ProductBridge` | **TRANSPORT_ONLY** | Transport and presentation; never a truth authority. |
| `Compatibility` | **COMPATIBILITY_ONLY** | Legacy compatibility containment. |

No component other than `MissionEngine` creates or replaces Mission identity, and no
component other than `MissionCompletionGate` independently turns execution into the
canonical `COMPLETED` truth.

---

## PRIMARY INVARIANT

```
WAITING_CONFIRMATION
  → VALID TYPED CONFIRMATION
  → SAME MISSION
  → AUTHORIZATION VALID
  → RESOURCE/BINDING REVALIDATED
  → EXACT EXECUTION
  → VERIFICATION
  → MISSION COMPLETION GATE
  → COMPLETED
```

And explicitly:

- `CONFIRMATION != AUTHORIZATION`
- `AUTHORIZATION != EXECUTION`
- `EXECUTION != VERIFICATION`
- `VERIFICATION != COMPLETION`
- `RESUME != NEW MISSION`

---

## CONFIRMATION RESULTS

Independent audit findings (adversarial probes + fresh official suite):

- same Mission identity preserved on resume;
- wrong-Mission confirmation rejected (`mission_mismatch`, no execution);
- no pending Mission → no execution;
- completed Mission cannot be replayed;
- rejected Mission cannot be replayed;
- ambiguous confirmation does not execute;
- rejection does not execute;
- replay does not double execute;
- typed approved parsing is fail-closed (true/1/yes/sim → execute; false/0/no/não/nao → reject; anything else → invalid);
- generic affirmative language cannot independently create execution authority.

---

## RA-13-01 ACROSS RESUME

Movement 13 exact-binding identity survives the confirmation delay.

Core App replacement while waiting: the replacement executable does not inherit the
selected/authorized binding.

Exact binding identity remains preserved or execution fails closed
(`binding_invalid` on tool_id/action_id mismatch or node removal; a replaced tool does
not change which action executes, since execution is capability-bound and never
re-resolves tools at execute time).

**RA-13-01 remains fixed.**

---

## RESOURCE / PROVIDER REVALIDATION

Verified resume-time behavior:

- RRM unavailable → no stale execution (`WAITING_RESOURCE`, zero attempts);
- binding removed → fail closed;
- binding replaced → no substitution;
- binding unhealthy → fail closed;
- authorization revoked → no execution (`AUTHORIZATION_REQUIRED`);
- provider removed/replaced/unavailable → no unauthorized invocation;
- provider selected != provider attempted != provider used.

---

## VERIFICATION / COMPLETION

- Executor success alone does NOT complete a Mission.
- Provider/executor output such as `done`, `completed`, `success=true`, HTTP-style
  success does NOT bypass `VerificationGate`.
- Valid verification still does NOT itself bypass `MissionCompletionGate`.
- Only valid execution + valid verification + valid `MissionCompletionGate` decision
  produces canonical `COMPLETED`.
- A forged `MissionCompletionDecision` (default authority, spoofed authority string,
  wrong Mission id, or missing decision) is rejected with
  `MissionCompletionEvidenceError`; the runtime assigns `COMPLETED` only under
  `completion_decision.allowed`.

---

## PRODUCT CONTRACT

- `WAITING_CONFIRMATION`:
  - `ok=false`
  - `requires_confirmation=true` (signalled by `status=WAITING_CONFIRMATION` plus
    the `confirmation` metadata bound to the Mission)
- Successful verified completion:
  - `COMPLETED`
  - `ok=true`
- Failures after confirmation remain truthful and cannot be upgraded by
  `ProductBridge` or downstream layers.
- `ProductBridge` remains **TRANSPORT_ONLY**.

---

## FINAL VALIDATION BASELINE

- Movement 14 targeted: **67 passed**
- Movement 11/12/13 regressions: **182 passed**
- Full Python: **1184 passed, 12 subtests passed, 1 environmental Windows failure**
- Environmental failure: `tests/test_symbiotic.py::test_programs_detected`
- Cause: pre-existing Unix `which` assumption on Windows
- Coverage: **82%**
- `compileall`: **PASS**
- `git diff --check`: **PASS**
- Movement 14 JSON map (`docs/movement_14_mission_continuation_map.json`): **PASS**
  (movement=14, components=14, authority_rules=9, test_count=67, regression_count=182)
- JavaScript: **JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE**
  - Node/npm unavailable in audit environment.
  - JS PASS is NOT claimed.

---

## SECURITY / ADVERSARIAL RESULTS

The independent audit challenged:

- replay;
- double execution;
- cross-Mission confirmation;
- cross-project/session confirmation where supported;
- stale authorization;
- stale binding;
- provider substitution;
- RA-13-01 during wait;
- forged Mission identity;
- forged verification;
- forged completion;
- compatibility bypass.

**No critical RA-14-XX blocker was found.**

---

## KNOWN LIMITATIONS

1. expired confirmation does not automatically generate a new confirmation;
2. `WAITING_RESOURCE` nodes do not automatically retry;
3. authorization recheck validates the bound snapshot rather than a live external
   permission registry;
4. some binding-identity checks rely on canonical product-path snapshot shape;
5. JavaScript validation unavailable in this audit environment;
6. productive external execution remains disabled.

These are **NOT** Movement 14 blockers.

---

## MOVEMENT 15 READINESS

Movement 15: **READY**

**BUT NOT STARTED.**

Separate explicit authorization is required after closure publication.
