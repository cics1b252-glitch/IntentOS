# MOVEMENT 15 — FORMAL CLOSURE

> Governed Agent Instantiation / Agent Factory Convergence

## MOVEMENT

**15** — Governed Agent Instantiation / Agent Factory Convergence

## STATUS

**MOVEMENT_15_VERIFIED**

## VERIFIED HEAD

`03803f3a63cb03371e2956b5e850056e74b3d590`

## MOVEMENT 14 CLOSURE BASE

`2d123900906c88a8d18c4f48fe4af3006a54dfbd`

## COMMIT

```
03803f3a63cb03371e2956b5e850056e74b3d590
feat: add governed agent factory
```

---

## CORE PRINCIPLE

```
AGENT IS A GOVERNED EXECUTION PARTICIPANT.
AGENT IS NOT SYSTEM AUTHORITY.
```

---

## FINAL AGENT AUTHORITY MODEL

| Component | Classification | Responsibility |
|---|---|---|
| `CanonicalAgentFactory` | **FACTORY_ONLY** | Instantiates governed agents; creates zero default agents. No provider invocation, no Mission invention, no authorization, no execution, no verification, no completion. |
| `CanonicalAgentRegistry` | **REGISTRY_ONLY** | Duplicate-identity rejection, fail-closed revocation, lookup. Presence in the registry is NOT authorization. |
| `GovernedAgent` | **EXECUTION_PARTICIPANT** | Passive identity + lifecycle record bound to an explicit Mission. No execute, verify, complete, confirm, authorize, spawn API. Output is evidence/input only. |
| `AgentSpec` | **DERIVED** | Typed declaration; rejects unknown fields. Declared capabilities are claims, never RRM availability or authorization. |
| `AgentLifecycleState` | **DERIVED** | Guarded lifecycle state machine: CREATED → READY → BOUND → RUNNING ↔ WAITING → COMPLETED / FAILED. Revoked is terminal. |
| `MissionEngine` | **CANONICAL_AUTHORITY** | Sole Mission identity and lifecycle authority. |
| `MissionCompletionGate` | **CANONICAL_AUTHORITY** | Sole canonical Mission completion authority. |
| `CanonicalConfirmationService` | **CANONICAL_AUTHORITY** | Typed human/owner confirmation. `CONFIRMATION != AUTHORIZATION`. |
| `ToolAuthorizationGate` | **AUTHORIZATION_ONLY** | Tool authorization decisions. |
| `CanonicalResourceBindingAuthority` | **EXECUTION_BINDING** | Exact binding selection/revalidation. |
| `MissionRuntime` | **EXECUTION_BINDING** | Governed execution graph; agents execute only through this path. |
| `CanonicalProviderAuthority` | **CANONICAL_AUTHORITY** | Provider selection and invocation. |
| `CanonicalMemoryService` | **CANONICAL_AUTHORITY** | Memory scoping. |
| `VerificationGate` | **EXECUTION_BINDING** | Post-execution verification. |
| `ProductBridge` | **PRODUCT_CONTRACT_LAYER** | Transport and presentation. |
| `ProductResponse` | **DERIVED** | Product output; never fabricated by an agent. |
| `CanonicalAgentOrchestrator` | **EXECUTION_BINDING** | Selection and bounded invocation of legacy agents; unchanged by M15. |
| `BaseAgent` / `FinanceAgent` / `KnowledgeAgent` / `EngineeringAgent` | **COMPATIBILITY_ONLY** | Legacy domain agents; unchanged by M15. |
| `AgentOrchestrator` (legacy) | **COMPATIBILITY_ONLY** | Legacy routing/messaging; unchanged by M15. |
| `AgentResource` (RRM) | **REGISTRY_ONLY** | RRM-bound agent descriptor; eligibility rules unchanged. |
| `AgentBlueprint` / `AgentBlueprintResolver` | **DERIVED** | Proposal-only; NOT wired; unchanged. |
| `KnowledgeStore` / `KnowledgePipeline` | **DERIVED** | Knowledge persistence. Agent output may be ingested as evidence/input. |
| `EventBus` / `IdempotencyStore` | **TRANSPORT_ONLY** | Transport and idempotency. |

No component other than `MissionEngine` creates or replaces Mission identity.
No component other than `MissionCompletionGate` independently turns execution into
the canonical `COMPLETED` truth.
`CanonicalAgentFactory` instantiates governed agents; it never binds resources,
invokes providers, executes productively, completes Missions, fabricates
verification, or mutates a product response.

---

## PRIMARY INVARIANT

```
AGENT IS NOT SYSTEM AUTHORITY.

AGENT != INTENT AUTHORITY
AGENT != MISSION AUTHORITY
AGENT != RRM AUTHORITY
AGENT != RESOURCE-BINDING AUTHORITY
AGENT != AUTHORIZATION AUTHORITY
AGENT != CONFIRMATION AUTHORITY
AGENT != VERIFICATION AUTHORITY
AGENT != COMPLETION AUTHORITY
AGENT != PRODUCT-RESPONSE AUTHORITY
```

And explicitly:

- `AGENT_IDENTITY` is factory-assigned (never user-supplied).
- `AGENT_CAPABILITIES` are claims only (never RRM availability).
- `AGENT_ROLE` is descriptive only (never authority-bearing).
- `REGISTRY_PRESENCE != AUTHORIZATION`.
- `AGENT_LIFECYCLE` is subordinate to `MissionEngine` lifecycle.
- `AGENT_MEMORY_SCOPE` is bounded metadata (never access).
- `AGENT_OUTPUT` is evidence/input only (never verification or completion).

---

## NON-PRODUCTIVE CREATION

Under full instrumentation (all productive subsystems patched to raise):

- `create()` made **zero** productive calls.
- `create()` left the agent in `CREATED` state.
- Factory module graph contains **no** provider, executor, MissionRuntime,
  ActionGate, VerificationGate, MissionCompletionGate, ConfirmationService,
  ToolAuthorizationGate, RRM, or memory symbols.
- Factory does **not** invent a Mission; `mission_id` defaults to `None`.
- No provider, executor, or runtime is invoked during creation.

---

## IDENTITY RESULTS

- Factory-assigned UUID identity (`agent_<hex>`); never user-supplied.
- Duplicate identity rejected by `CanonicalAgentRegistry.register()`.
- Public API cannot replace an existing registry entry.
- `get()` returns the exact original object (object identity, not reconstruction).
- Forged identity in snapshot does not alter the underlying object.
- GovernedAgent has no `execute`/`run`/`invoke`/`act`/`spawn`/`create` API.

### TOCTOU

Private-dict forced swap with Agent B (same `agent_id`, `role`, `declared_capabilities`):

- B is a **distinct** object.
- B does **not** inherit A's Mission binding (`None` vs `A`'s bound mission).
- B does **not** inherit A's lifecycle state.
- B has no execution surface to receive inherited context.
- **Fails closed.**

---

## ROLE / PRIVILEGE RESULTS

Tested: `admin`, `administrator`, `system`, `trusted`, `supervisor`, `manager`,
`expert`, `master`, `root`.

All: `authority == "NONE"`, lifecycle == `CREATED`.

No role name grants authorization or bypasses any gate.

---

## CAPABILITY CLAIM RESULTS

Agent declaring unsupported capabilities (`document.read`, `vehicle.diagnostics`,
`email.send`, `filesystem.write`):

- Claims stored only (no RRM interaction during creation).
- Claims do **not** create RRM agent resources.
- Claims do **not** create RRM capability resources.
- Claims do **not** grant authorization.
- Claims do **not** create binding or invocation paths.

---

## MISSION ASSOCIATION RESULTS

- A → MissionB without governed reassignment: **rejected** (`MissionBindingError`).
- Agent B cannot adopt A's Mission via context, role match, or string matching.
- B has no execution/context API to access A's Mission state.
- Binding requires an explicit `bind()` call — the only governed path.
- `AgentSpec.mission_id` with empty string rejected.

---

## REGISTRY RESULTS

- `registered != active != authorized != executing`
- Registry-only agent has zero execution API.
- Registry snapshot is observational only.
- Registry presence does **not** imply runtime eligibility or permission.

---

## REVOCATION RESULTS

- Revoked agent: `is_revoked() == True`, lifecycle `REVOKED`.
- Revoked agent cannot transition (e.g., to `RUNNING`): `AgentLifecycleError`.
- Revoked agent cannot be re-bound to the **same** Mission: `AgentLifecycleError`
  (terminal state cannot transition).
- Revoked agent cannot be re-bound to a **different** Mission: `MissionBindingError`
  (mismatch detected before lifecycle check).
- Stale-reference post-revoke execution attempt: **blocked** (`AgentLifecycleError`).
- Revocation does **not** complete/cancel the Mission; does **not** spawn a
  replacement agent.

---

## AUTHORIZATION / CONFIRMATION RESULTS

- Agent has no `confirm`/`authorize` API.
- `CanonicalConfirmationService` (Movement 14 authoritative) still requires
  typed user confirmation.
- No confirmation field exists in agent/registry snapshots to forge.
- Agent presence in the registry cannot fabricate confirmation.

---

## RESOURCE / PROVIDER RESULTS

- Agent with declared capability + RRM unavailable: zero execution.
- Agent with no private resource authority created.
- Provider requirement in `AgentSpec` is a claim; does **not** invoke provider.
- `SELECTED != ATTEMPTED != USED` preserved (M11/M12 regressions pass).

---

## VERIFICATION / COMPLETION RESULTS

- Agent has no `verify`/`complete` API.
- Agent snapshot contains **no** injectable completion/verification fields
  (`mission_completed`, `completion_allowed`, `verification`, `ok`).
- Agent lifecycle `COMPLETED` does **not** mutate `MissionEngine` store.
  `MissionEngine.get(mission)` returns `None` for the agent's mission.
- `MissionEngine` remains the sole Mission authority (`create`/`complete`).
- `MissionCompletionGate` remains the sole completion authority (Movement 14).

---

## MEMORY SCOPE RESULTS

- `memory_scope` is metadata only (values: `mission`, `project`, `none`).
- GovernedAgent has no `read_memory`/`write_memory` API.
- Registry identity alone grants no memory access.
- No new memory bypass introduced.

---

## MULTI-AGENT ISOLATION RESULTS

- Agent A and Agent B: independent `agent_id`, Mission, scope, lifecycle.
- No cross-contamination between agents.

---

## DELEGATION / SPAWNING RESULTS

- GovernedAgent has no `spawn`/`delegate`/`factory`/`registry` reference.
- No autonomous Agent-to-Agent delegation path exists.
- No recursive spawning, automatic delegation, privilege amplification, or
  unbounded autonomous loops.

---

## LEGACY / COMPATIBILITY RESULTS

- Legacy agents (`FinanceAgent`/`KnowledgeAgent`/`EngineeringAgent`) remain
  `BaseAgent`-derived, `COMPATIBILITY_ONLY`, unchanged.
- `CanonicalAgentOrchestrator` remains selection-only (no Mission mutation API).
- Legacy Agent paths cannot bypass the new factory/governance.
- Legacy Agents remain `COMPATIBILITY_ONLY`; no parallel canonical authority.

---

## PRODUCT CONTRACT RESULTS

- `ProductBridge` unchanged; remains `PRODUCT_CONTRACT_LAYER`.
- Agent output does **not** control `status`, `execution_mode`, `ok`,
  `epistemic_status`, `confidence`, `provider_called`, or Mission completion.
- No metadata collision vectors introduced by M15.

---

## AUTHORITY RULES (from movement_15_agent_authority_map.json)

Movement 15 establishes 20 authority rules and 12 obligations:

| # | Rule |
|---|---|
| 1 | Agent is a governed execution participant, not system authority. |
| 2 | Agent != Intent authority. |
| 3 | Agent != Mission authority. |
| 4 | Agent != RRM authority. |
| 5 | Agent != Resource-binding authority. |
| 6 | Agent != Authorization authority. |
| 7 | Agent != Confirmation authority. |
| 8 | Agent != Verification authority. |
| 9 | Agent != Completion authority. |
| 10 | Agent != Product-response authority. |
| 11 | Factory creates zero default agents. |
| 12 | Registry rejects duplicates, revokes fail-closed; presence ≠ authorization. |
| 13 | Factory never invents a Mission; explicit binding required. |
| 14 | Factory never selects resources, invokes providers, executes, completes, verifies, or mutates response. |
| 15 | Capability declarations are claims, never RRM availability. |
| 16 | Role names grant no authority. |
| 17 | Autonomous Agent-to-Agent delegation is out of scope. |
| 18 | No privilege amplification. |
| 19 | Registry is not authorization. |
| 20 | M15 is additive: existing orchestrator + RRM registrations untouched. |

Full detail: `docs/MOVEMENT_15_AGENT_AUTHORITY_MAP.md` + `docs/movement_15_agent_authority_map.json`.

---

## SECURITY / ADVERSARIAL RESULTS

The independent audit challenged:

- agent creation productivity (full subsystem instrumentation);
- agent identity spoofing / duplication / replacement;
- identity TOCTOU (private-dict forced swap);
- role-based privilege escalation;
- capability-claim-to-resource leakage;
- Mission association transfer / implicit adoption;
- Mission creation by agent;
- registry authority;
- revocation + stale reference;
- authorization transfer between agents;
- self-confirmation / self-verification / self-completion;
- resource authority bypass;
- provider invocation during creation;
- memory scope leakage;
- multi-agent cross-contamination;
- delegation / spawning;
- legacy agent bypass;
- ProductBridge metadata collision;
- unknown field injection;
- malformed specification handling;
- factory failure atomicity;
- observability truthfulness.

**118/118 independent adversarial probes PASSED.**
**No critical RA-15-XX blocker was found.**

---

## FINAL VALIDATION BASELINE

| Metric | Result |
|---|---|
| Movement 15 targeted tests | **38 passed** |
| Matrix A–X (24) | 24 passed |
| Adversarial identity (10) | 10 passed |
| Novel domains (4 official) | 4 passed |
| Independent adversarial probes (outside repo) | **118/118 passed** |
| Movement 11/12/13/14 regressions (12 files) | **249 passed** |
| Full Python suite | **1222 passed, 12 subtests, 1 env failure** |
| Environmental failure | `tests/test_symbiotic.py::test_programs_detected` |
| Cause | pre-existing Unix `which` assumption on Windows |
| Coverage | **82%** (`intent_kernel` + `product_bridge`; `factory.py` **97%**) |
| `compileall` | **PASS** |
| `git diff --check 2d12390..03803f3` | **PASS** |
| Movement 15 JSON map | **PASS** (movement=15, components=26, authority_rules=20, obligations=12) |
| JavaScript / TypeScript | **JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE** |

Count differences from M14 baseline (1184 → 1222): **+38** new M15 tests.
Regression counts (182 → 249): **+67** M14 tests added to the regression set
(previously part of the targeted suite; now included in the regression pass).

---

## NOVEL DOMAINS

Movement 15 tested (beyond the four official novel domains) two additional
independently-chosen domains: `clinical_trial_assistant` and
`supply_chain_risk_analyst`.

- Both created with full declared capabilities.
- Neither produced any RRM resource, provider invocation, or authority escalation.
- Role/capability declarations are descriptive claims only.
- No finance/default contamination.

---

## KNOWN LIMITATIONS

1. `AgentSpec` label fields (`mission_id`, `project_id`, `allowed_scope`) use
   untyped strings (coerced via `str()`); descriptive only, no authority granted.
2. Registry private dict `_agents` is technically mutable via direct access;
   this grants no authority and no execution path consumes it.
3. JavaScript validation unavailable in this environment.
4. Agent lifecycle transitions are guarded, but there is no persistence layer
   for `GovernedAgent` state across process restarts.
5. `AgentBlueprint` / `AgentBlueprintResolver` (M15 discovery) are proposal-only,
   not wired; they could be converged with `CanonicalAgentFactory` in a future
   movement.

These are **NOT** Movement 15 blockers.

---

## DELIVERY ARTIFACTS

- Commit: `03803f3` "feat: add governed agent factory" (5 files, +1570)
- Bundle: `intentos-m15-governed-agent-factory.bundle`
  - Size: 15682 bytes
  - SHA-256: `44E0FEE56BD9D3385263CFAF29129D67040356C1578EBDC95360E4B0C7EC8E7B`
  - Contains: HEAD `03803f3`; requires base `2d12390`
  - `git bundle verify`: OK
  - Base64 round-trip (20912 chars): rebuilt SHA-256 identical; verify OK

---

## MOVEMENT 16 READINESS

Movement 16: **NOT READY**

Movement 15 establishes the governed Agent identity/lifecycle factory. Movement 16
would require connecting the factory to the governed execution path through
`MissionRuntime` under existing authorities (`MissionEngine`, `RRM`,
`ToolAuthorizationGate`, `CanonicalConfirmationService`, `VerificationGate`,
`MissionCompletionGate`) — which must be a separate, explicitly authorized
movement.

**DO NOT BEGIN MOVEMENT 16 without separate authorization.**
