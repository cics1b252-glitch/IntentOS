# MOVEMENT 14 — Mission Confirmation/Resume Continuation Map

## Scope

Movement 14 ("Mission Confirmation/Resume convergence") extends the existing
`MissionEngine` / `ActionGate` / `MissionRuntime` / `CanonicalMissionService` /
`ProductBridge` architecture so that a Mission in `WAITING_CONFIRMATION` resumes
as the **same Mission** after a valid **typed** user confirmation, preserving the
exact authorized/revalidated binding context, then runs controlled execution →
VerificationGate → MissionCompletionGate → `COMPLETED`.

This document classifies every authority, model, gate, and helper involved in the
confirmation→resume lifecycle. It accompanies the machine-readable
`docs/movement_14_mission_continuation_map.json`.

## Classifications

- **CANONICAL_AUTHORITY** — the single authority for a lifecycle decision. Only one
  CANONICAL_AUTHORITY exists per decision.
- **DERIVED** — derived read/view over canonical state; no decision authority.
- **PERSISTENCE_ONLY** — storage/ownership only; no decision authority.
- **AUTHORIZATION_ONLY** — decides pre-execution authorization only; never confirms,
  never completes.
- **CONFIRMATION_ONLY** — decides whether a pending confirmation may proceed; never
  authorizes the underlying tool, never executes, never completes.
- **EXECUTION_BINDING** — binds the confirmed instance to its execution context.
- **VERIFICATION_ONLY** — decides verification of a completed action only.
- **COMPLETION_ONLY** — decides Mission completion only.
- **TRANSPORT_ONLY** — formats/propagates signals; no decision authority.
- **COMPATIBILITY_ONLY** — backwards-compatible surface that keeps older callers valid.
- **DUPLICATE_AUTHORITY** — overlapping authority that MUST NOT be used.
- **DEPRECATION_CANDIDATE** — superseded by Movement 14; removal is optional and
  must be evaluated against compatibility tests.

## Components

### 1. `intent_kernel/runtime/action_gate.py` — `ActionGate`

- **Classification:** CANONICAL_AUTHORITY (pre-execution gate decision for a node).
- **State owned:** idempotency key registry (`_executed_idempotency_keys`).
- **Inputs:** `RuntimeNode`, `ActionContract`, `mission_constraints`,
  `execution_policy`, `confirmation` (`ExecutionConfirmationRequest | None`).
- **Outputs:** `ActionGateDecision.{DENY, REQUIRE_CONFIRMATION, WAIT_RESOURCE, ALLOW}`.
- **Precedence (strict order):** 1) Constitution/Safety → 2) Explicit Deny Policy →
  3) Persistent Mission Constraints → **4) User Confirmation Requirement** →
  5) RRM Resource Eligibility Revalidation → 6) Idempotency → 7) ALLOW.
- **Mission ID handling:** none.
- **Confirmation mutation:** none (reads `confirmation.approved` only).
- **Auth recheck:** no; authorization is revalidated by `CanonicalConfirmationService`.
- **Binding revalidation:** no.
- **Execution:** no.
- **Completion:** no.
- **Compat role:** unchanged from prior movements; confirmation step was already present.

### 2. `intent_kernel/application/mission_engine.py` — `MissionEngine`

- **Classification:** CANONICAL_AUTHORITY (Mission lifecycle state machine).
- **State owned:** Mission collection (status, decisions).
- **Inputs:** `MissionId`, creation payload, `reject(mission_id)`.
- **Outputs:** Mission state transitions; `reject()` moves `WAITING_FOR_DECISION` →
  `CANCELLED` (new in M14 — the canonical representation of a rejected confirmation).
- **Mission ID handling:** creates/preserves the Mission identity; resume uses the SAME id.
- **Confirmation mutation:** no.
- **Auth recheck:** no.
- **Binding revalidation:** no.
- **Execution:** no.
- **Completion:** no (completion handled by `CanonicalMissionService` sync).
- **Compat role:** existing `approve()`/`complete()`/`cancel()` preserved.

### 3. `intent_kernel/runtime/mission_runtime.py` — `MissionRuntime`

- **Classification:** EXECUTION_BINDING (runtime instance state) + TRANSPORT_ONLY
  (returns run outcomes to the service layer).
- **State owned:** runtime instances, nodes, attempt counters, per-node confirmations.
- **Inputs:** instance creation, `run_mission(runtime_id)`, `submit_confirmation(...)`,
  `get_confirmation(confirmation_id)`, `get_pending_confirmation(instance_id)`,
  `cancel_instance(instance_id)`.
- **Outputs:** `MissionRuntimeState` + `MissionRunOutcome`; confirmed resume yields the
  **same instance**.
- **Mission ID handling:** binds runtime instance to Mission id; preserves on resume.
- **Confirmation mutation:** `submit_confirmation` sets `approved=True`; only permitted
  while state == `WAITING_CONFIRMATION`.
- **Auth recheck:** no.
- **Binding revalidation:** no.
- **Execution:** run_mission drives node execution through the executor.
- **Completion:** completion decision delegated to `CanonicalMissionService`;
  runtime reports executed/completed nodes.
- **Compat role:** `get_pending_confirmation`/`cancel_instance` added without breaking
  prior callers.

### 4. `intent_kernel/application/confirmation_service.py` — `CanonicalConfirmationService`

- **Classification:** CANONICAL_AUTHORITY (confirmation lifecycle) — **CONFIRMATION_ONLY**.
- **State owned:** per-confirmation pending bindings (id, scope, token, expires_at,
  authorization snapshot, provenance).
- **Inputs:** `ConfirmationSubmission`, `bind_pending(...)`, `consume(id)`,
  `invalidate(id)`.
- **Outputs:** `ConfirmationOutcome` with `accepted`, `state` (CONFIRMED/REJECTED/
  EXPIRED/STALE/…), `reason`, `mission_id`, `runtime_id`.
- **Submit validation chain:** confirmation exists → mission_id matches → mission exists
  → mission status guards (completed/cancelled short-circuits) → state == WAITING →
  scope/session/project match → confirmation_token match → expiry not passed →
  binding identity valid → approve (submit_confirmation + runtime_id) or reject
  (engine.reject + cancel_instance).
- **Mission ID handling:** reuses the bound Mission id; never creates a new Mission.
- **Confirmation mutation:** the ONLY mutator of confirmation lifecycle state.
- **Auth recheck:** `recheck_authorization` → `ToolAuthorizationGate.evaluate_tool`
  on the SAME serialized candidate/tool on confirmed resume.
- **Binding revalidation:** `_binding_identity_valid` compares instance/node presence,
  node contract `action_id`, and contract.provenance `tool_id` vs bound snapshot.
- **Execution:** NEVER executes the tool. **Confirmed intentionally.**
- **Completion:** NEVER completes the Mission directly. **Confirmed intentionally.**
- **Compat role:** new service; isolated from prior callers.

### 5. `intent_kernel/application/composition.py` — Composition

- **Classification:** DERIVED (wiring only).
- **State owned:** component registry; adds `confirmation_service`
  (`CanonicalConfirmationService(mission_engine, mission_runtime,
  tool_authorization_gate=…, confirmation_ttl_seconds=300)`).
- **Metadata:** `"confirmation_authority": "CanonicalConfirmationService"`.
- **Mission ID handling:** none.
- **Confirmation mutation / auth / binding / execution / completion:** none.

### 6. `product_bridge.py` — `ProductBridge` (dispatch + `_confirm_mission` +
   `_resume_confirmed` + `_bind_pending_confirmation`)

- **Classification:** TRANSPORT_ONLY (bridge to product protocol) for the
  `confirm` action; delegates all decisions.
- **State owned:** none (stateless glue).
- **Inputs:** `{action: "confirm", params: {mission_id, confirmation_id, approved,
  session_id, project_id, confirmation_token}}`.
- **Outputs:** product response (WAITING_CONFIRMATION when pending, COMPLETED only on
  verified completion, local informational response on rejection/invalid/expired).
- **Approved parsing:** "true"/"1"/"yes"/"sim" → True; "false"/"0"/"no"/"não"/"nao" →
  False; any other string → None (invalid → `invalid_confirmation_request`).
- **Mission ID handling:** carries `mission_id` through metadata; rejection result is a
  local UNKNOWN (no `mission_id` on the response, since the presenter forbids
  `UNKNOWN` from exposing execution evidence); mission_id still present in
  `confirm.mission_id` metadata.
- **Confirmation mutation:** none (delegates to service).
- **Auth recheck / binding revalidation:** none (delegates to service).
- **Execution / completion:** none.
- **Compat role:** `dispatch` gains a new `confirm` branch; existing branches unchanged.

### 7. `intent_kernel/runtime/models.py` — `ConfirmationState` + extended
   `ExecutionConfirmationRequest`

- **Classification:** PERSISTENCE_ONLY (data model).
- **State owned:** `NO_CONFIRMATION_REQUIRED / WAITING_CONFIRMATION / CONFIRMED /
  REJECTED / EXPIRED / STALE / CONSUMED`; fields `runtime_id`, `confirmation_token`,
  `session_id`, `project_id` (defaults keep prior callers valid).
- **Compat role:** additive defaults only.

### 8. `intent_kernel/runtime/time_utils.py` — `utc_iso`/`utc_now`

- **Classification:** PERSISTENCE_ONLY (time source for expiry).
- **Mission ID handling / confirmation / auth / binding / execution / completion:** none.
- **Note:** expiry compares ISO strings from the same UTC formatter (lexicographic
  order is chronological).

### 9. `intent_kernel/application/mission_service.py` — `CanonicalMissionService`

- **Classification:** CANONICAL_AUTHORITY for Mission completion sync (existing
  authority); **never** mutates confirmations.
- **Mission ID handling:** syncs the same Mission id to COMPLETED/FAILED/…
- **Confirmation mutation:** none.
- **Auth / binding / execution:** none (execution delegated to runtime).

### 10. `intent_kernel/runtime/tools/authorization.py` — `ToolAuthorizationGate`

- **Classification:** AUTHORIZATION_ONLY.
- **Decision:** `evaluate_tool` (ALLOW/DENY/…). Re-invoked by
  `CanonicalConfirmationService.recheck_authorization` on confirmed resume.
- **Confirmation mutation / binding / execution / completion:** none.

### 11. `intent_kernel/runtime/verification.py` — VerificationGate

- **Classification:** VERIFICATION_ONLY.
- **Decision:** expected-output match decides VERIFIED_SUCCESS / VERIFIED_FAILURE.
- **Mission ID handling:** none; **never** marks a Mission COMPLETED by itself.

### 12. `intent_kernel/runtime/mission_completion_gate.py`

- **Classification:** COMPLETION_ONLY.
- **Decision:** only an executed + verified Mission may transition to COMPLETED.
- **Confirmation mutation / auth / binding:** none.

### 13. Legacy fast-path helpers (`_chat_flow`-adjacent local/intent helpers)

- **Classification:** DEPRECATION_CANDIDATE / COMPATIBILITY_ONLY.
- Legacy local-response helpers (`local(...)`, intent extraction) remain available for
  compatibility; they are NOT the confirmation authority and MUST NOT be used to
  complete a confirmed Mission.

### 14. UI button (Phase 14.18)

- **Classification:** TRANSPORT_ONLY / DEFERRED.
- **Status:** NOT implemented in Movement 14. The typed `confirm` product action
  carries `mission_id` + `confirmation_id` + `approved` (+ session/project/token).

## Authority Rules (no-conflict)

1. Confirmation is decided ONLY by `CanonicalConfirmationService`.
2. Confirmation is NEVER authorization and NEVER completion.
3. A confirmed resume revalidates authorization (`recheck_authorization`) and binding
   identity (`_binding_identity_valid`); failure → non-executing outcome, no execution.
4. Only VerificationGate + MissionCompletionGate can produce canonical COMPLETED.
5. Rejection → `MissionEngine.reject` → canonical `CANCELLED`; never executes.
6. Free-form text (e.g. "sim") never reaches the confirm handler → zero execution.
7. Typed `confirm` is the ONLY resume path.
8. Expired/consumed/replayed confirmations never execute.
9. `UNKNOWN` product responses never expose execution evidence (`mission_id`).

## Test Matrix

`tests/test_movement_14_confirmation_resume.py` — 67 tests:

- **Matrix A–T (bridge + service):** pending binding, valid confirm resume (same Mission,
  canonical COMPLETED), invalid approval, wrong Mission, ambiguous approval
  (invalid, NOT rejection), rejection (cancels, never executes), expired token/conf,
  consumed/replay, invalidated stale, replaced tool binding (fails closed), replaced
  contract action_id (fails closed), RRM-unavailable on resume (fails closed), missing
  session, wrong scope, forged completion evidence (rejected), failed verification
  (no completion), and confirmation/execution/verification/completion precedence.
- **Adversarial (5 scenarios × phrases):** free-form text ("sim", "confirmo", "pode",
  "continue", "ok") with no / one / wrong / completed / cancelled / expired Mission →
  zero executor calls.
- **Service-level invariants:** service never executes; engine/runtime/sync canonical
  states converge.

## Files

- `intent_kernel/runtime/models.py` — ConfirmationState enum + extended request.
- `intent_kernel/runtime/mission_runtime.py` — runtime_id + confirmation lifecycle API.
- `intent_kernel/runtime/action_gate.py` — confirmation step (existing, read-only).
- `intent_kernel/application/mission_engine.py` — `reject()`.
- `intent_kernel/application/confirmation_service.py` — NEW canonical authority.
- `intent_kernel/application/composition.py` — wiring + metadata.
- `product_bridge.py` — `confirm` branch + helpers.
- `tests/test_movement_14_confirmation_resume.py` — NEW suite.
- `docs/MOVEMENT_14_MISSION_CONTINUATION_MAP.md` + `.json` — this map.
