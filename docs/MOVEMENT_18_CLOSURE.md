# Movement 18 Closure

## STATUS

**MOVEMENT_18_VERIFIED**

## MOVEMENT

Governed Resource Activation Convergence

## IMPLEMENTATION/REPAIR CHAIN

```
3faeab3  (M17 closure)
→ ea44412  (M18 initial impl)
→ 0a72b2d  (RA-18-02 repair)
→ 21e0232  (canonical evidence/provenance)
→ 849e7c0  (canonical trust root)
→ 458ae1b  (governed identity isolation)
```

## FINAL VERIFIED HEAD

`458ae1b5335c3c57ed0dce11b330286e8ebe5740`

## CORE INVARIANT

```
DISCOVERY
!= PROMOTION
!= REGISTRATION
!= ACTIVATION EVIDENCE
!= ACTIVATION APPROVAL
!= ELIGIBILITY
!= BINDING
!= AUTHORIZATION
!= EXECUTION
!= VERIFICATION
!= COMPLETION
```

```
CALLER ASSERTION != TRUSTED EVIDENCE
RESOURCE ORIGIN != GOVERNED IDENTITY
SAME RESOURCE ID != REPLACEMENT AUTHORITY
```

## BLOCKERS AND RESOLUTION

### RA-18-01

**FIXED** — Governed resources cannot be silently overwritten/activated by generic or compatibility register paths.

### RA-18-02

**FIXED** — Activation does not fabricate prerequisite fields.

### RA-18-03

**FIXED** — Only canonical evidence collection creates trusted evidence.

### RA-18-04

**FIXED** — `mark_governed()` is compatibility-only/no-op. Canonical governed identity originates exclusively from M17 registration.

## FINAL AUTHORITY MODEL

| Authority | Role |
|---|---|
| `CanonicalPromotionRegistrationBoundary` | Canonical governed registration identity source |
| `CanonicalActivationEvidenceAuthority` | Canonical trusted evidence authority |
| `CanonicalResourceActivationAuthority` | ACTIVATION_ONLY |
| `ActivationApplicationBoundary` | Activation application / TOCTOU boundary |
| `RRM` | Canonical runtime eligibility/availability truth |
| `CanonicalResourceBindingAuthority` | Binding identity authority |
| `ToolAuthorizationGate` | Authorization authority |
| `VerificationGate` | Verification authority |
| `MissionCompletionGate` | Completion authority |

## SECURITY PROPERTIES

Verified protections:

- Caller evidence cannot become trusted;
- Forged governed identity cannot be created via `mark_governed()`;
- Same-ID overwrite blocked;
- Different-origin overwrite blocked;
- Activation approval does not fabricate prerequisites;
- TOCTOU fails closed;
- Provider/tool/agent cannot self-activate;
- RA-13-01 remains preserved.

## VALIDATION

| Metric | Result |
|---|---|
| M18 tests | 118/118 PASS |
| M17 tests | 62/62 PASS |
| Full suite | 1167 passed, 2 failed (pre-existing), 292 errors (environmental) |
| compileall | PASS |
| git diff --check | PASS |
| JSON | VALID |

## KNOWN LIMITATIONS

- `unregister_*` governed-resource hardening: future hardening opportunity, not M18 blocker.
- `register_project` overwrite guard: outside current governed project activation scope.
- 292 PermissionErrors across full suite: environmental (Windows), not code failures.

## MOVEMENT 19 READINESS

| Movement | Status |
|---|---|
| MOVEMENT 18 | **VERIFIED / CLOSED** |
| MOVEMENT 19 | **READY — NOT STARTED** |

Requires separate explicit authorization.
