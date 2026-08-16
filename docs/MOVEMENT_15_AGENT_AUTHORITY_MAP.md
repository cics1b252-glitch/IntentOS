# MOVEMENT 15 — GOVERNED AGENT INSTANTIATION / AGENT FACTORY CONVERGENCE

Status: IN PROGRESS
Base commit: `2d123900906c88a8d18c4f48fe4af3006a54dfbd`
Authorized: MOVEMENT 15 AUTHORIZED TO BEGIN
Preceding movements: M11 (VERIFIED+CLOSED), M12 (VERIFIED+CLOSED), M13 (VERIFIED+CLOSED), M14 (VERIFIED+CLOSED)

## 1. Core principle

> **AGENT IS A GOVERNED EXECUTION PARTICIPANT. AGENT IS NOT SYSTEM AUTHORITY.**

An Agent in Intent OS v2.0 is a governed identity record with a bounded lifecycle that
participates in execution through the existing governed paths. It never holds system
authority over intent, Mission lifecycle, resources, resource binding, authorization,
confirmation, verification, completion, or the product response.

## 2. Discovery (Phase 15.2)

No governed Agent Factory exists in the codebase today.

| Artifact | Location | Nature |
|---|---|---|
| `AgentId` | `intent_kernel/contracts/models.py` | Identity contract (non-empty value) |
| `AgentLimits` / `AgentRequest` | `intent_kernel/contracts/models.py` | Contracts |
| `Agent` protocol | `intent_kernel/contracts/ports.py:126` | Capability execution protocol |
| `BaseAgent`, `FinanceAgent`, `KnowledgeAgent`, `EngineeringAgent` | `intent_kernel/agents/__init__.py` | Legacy domain agents (not governed) |
| `AgentOrchestrator` (legacy) | `intent_kernel/agents/__init__.py` | Legacy routing/messaging |
| `CanonicalAgentOrchestrator` | `intent_kernel/orchestration/agents.py` | Selection + bounded invocation; never Mission lifecycle |
| `AgentResource` | `intent_kernel/rrm/models.py` | RRM-bound agent descriptor (eligibility rules) |
| `AgentBlueprint` / `AgentLifecycle` / `AgentBlueprintResolver` | `intent_kernel/cognition/runtime.py` | Proposal-only, NOT wired, test-only |
| `MissionRuntime.create_instance` | `intent_kernel/runtime/mission_runtime.py` | Governed execution path |
| `KernelBuilder.build()` | `intent_kernel/application/composition.py` | Wires 3 legacy agents (Finance/Knowledge/Engineering) |
| `RuntimeNode.agent_id` | `intent_kernel/runtime/models.py` | Node attribution (`agent_default`) |

Result: **No governed instantiation, no governed identity registry, no governed lifecycle
state machine for agents.** M15 introduces the smallest canonical extension for these, and
only for these.

## 3. Mandated authority separation

### 3.1 Classifications

| Classification | Meaning |
|---|---|
| `CANONICAL_AUTHORITY` | Holds system authority for its concern |
| `IDENTITY_AUTHORITY` | Authoritative identity values |
| `FACTORY_ONLY` | Instantiation only; zero default agents |
| `REGISTRY_ONLY` | Registry; presence is NOT authorization |
| `DERIVED` | Derived/descriptive; grants no authority |
| `EXECUTION_PARTICIPANT` | Governed participant; output is evidence/input only |
| `EXECUTION_BINDING` | Binds execution to resources; governed |
| `AUTHORIZATION_ONLY` | Authorization decisions only |
| `TRANSPORT_ONLY` | Transport/idempotency; grants no authority |
| `COMPATIBILITY_ONLY` | Legacy compatibility; not extended by M15 |
| `DEPRECATION_CANDIDATE` | Superseded; not touched by M15 |
| `DUPLICATE_AUTHORITY` | Prohibited pattern in M15 |

### 3.2 What an Agent is NOT (M15 non-negotiables)

- `AGENT != INTENT AUTHORITY` — intent understanding stays with IntentUnderstandingEngine.
- `AGENT != MISSION AUTHORITY` — Mission lifecycle stays with MissionEngine; completion stays
  with MissionCompletionGate; confirmation stays with CanonicalConfirmationService.
- `AGENT != RRM AUTHORITY` — resource/agent availability stays with RegistryResourceManager.
- `AGENT != RESOURCE-BINDING AUTHORITY` — binding stays with CanonicalResourceBindingAuthority / MissionRuntime.
- `AGENT != AUTHORIZATION AUTHORITY` — authorization stays with ToolAuthorizationGate/ConstitutionEngine.
- `AGENT != CONFIRMATION AUTHORITY` — `CONFIRMATION != AUTHORIZATION` (M14).
- `AGENT != VERIFICATION AUTHORITY` — `VERIFICATION != COMPLETION` (M14).
- `AGENT != COMPLETION AUTHORITY` — completion is evidence-based and gate-authorized.
- `AGENT != PRODUCT-RESPONSE AUTHORITY` — the product response is never fabricated by an agent.

### 3.3 New M15 components and their exact scope

| Component | Classification | Scope |
|---|---|---|
| `CanonicalAgentFactory` | `FACTORY_ONLY` | Instantiation of governed agents (identity + lifecycle). Creates **zero** default agents. |
| `CanonicalAgentRegistry` | `REGISTRY_ONLY` | Duplicate rejection, revocation (fail-closed), lookup. Presence ≠ authorization. |
| `GovernedAgent` | `EXECUTION_PARTICIPANT` | Passive identity + lifecycle record bound to an explicit Mission. No direct provider invocation, no self-verification, no self-completion. |
| `AgentSpec` | `DERIVED` | Typed declaration. Rejects unknown fields. Capabilities are claims, not availability. |
| `AgentLifecycleState` | `DERIVED` | `CREATED, READY, BOUND, RUNNING, WAITING, COMPLETED, FAILED, REVOKED`; guarded transitions. |

### 3.4 Factory obligations (FACTORY_ONLY)

The factory MUST generate identity via factory-assigned UUID (never user-supplied). It MUST
NOT:
- invent a Mission (every `GovernedAgent` requires an explicit Mission binding),
- authorize,
- select resources independently,
- invoke providers,
- execute productively during creation,
- complete a Mission,
- fabricate verification,
- mutate a product response.

### 3.5 Registry obligations (REGISTRY_ONLY)

The registry MUST reject duplicate identities without silent replacement, MUST fail closed on
revoked agents, and MUST expose an observable, secret-free snapshot. Registry presence is NOT
authorization.

### 3.6 Boundaries that M15 does NOT cross

- No agent marketplace, negotiation, voting, self-modification.
- No recursive delegation; **autonomous Agent-to-Agent delegation is OUT OF SCOPE**.
- No automatic spawning or unbounded autonomous loops.
- No privilege amplification (an agent may not create another agent with broader scope).
- No multi-provider orchestration beyond the current authority.
- No Constitution modification.

### 3.7 Additivity

M15 is additive. `CanonicalAgentOrchestrator` keeps its 3 legacy agents; RRM registrations are
untouched; `KernelBuilder.build()` still wires FinanceAgent/KnowledgeAgent/EngineeringAgent and
exposes the factory/registry as new components.

## 4. Authority map

Full per-component matrix: see `docs/movement_15_agent_authority_map.json`.

Summary:

| Component | Classification |
|---|---|
| AgentId | IDENTITY_AUTHORITY |
| CanonicalAgentFactory (NEW) | FACTORY_ONLY |
| CanonicalAgentRegistry (NEW) | REGISTRY_ONLY |
| GovernedAgent (NEW) | EXECUTION_PARTICIPANT |
| AgentSpec (NEW) | DERIVED |
| AgentLifecycleState (NEW) | DERIVED |
| MissionEngine | CANONICAL_AUTHORITY |
| MissionCompletionGate | CANONICAL_AUTHORITY |
| CanonicalConfirmationService | CANONICAL_AUTHORITY |
| CanonicalMissionService | CANONICAL_AUTHORITY |
| ConstitutionEngine | CANONICAL_AUTHORITY |
| RegistryResourceManager | CANONICAL_AUTHORITY |
| CanonicalProviderAuthority / ProviderManager | CANONICAL_AUTHORITY |
| AgentResource | REGISTRY_ONLY |
| CanonicalCapabilityRegistry | REGISTRY_ONLY |
| CanonicalAgentOrchestrator | EXECUTION_BINDING |
| MissionRuntime | EXECUTION_BINDING |
| CanonicalResourceBindingAuthority | EXECUTION_BINDING |
| CapabilityExecutionService | EXECUTION_BINDING |
| RuntimeNode.agent_id | DERIVED |
| AgentBlueprint / AgentBlueprintResolver | DERIVED |
| KnowledgeStore / KnowledgePipeline | DERIVED |
| ToolAuthorizationGate | AUTHORIZATION_ONLY |
| BaseAgent / Finance/Knowledge/EngineeringAgent | EXECUTION_PARTICIPANT (compat) |
| AgentOrchestrator (legacy) | COMPATIBILITY_ONLY |
| EventBus / IdempotencyStore | TRANSPORT_ONLY |

## 5. Verification plan

- **Test matrix A–X (24 tests)**: `tests/test_movement_15_governed_agent_factory.py`
- **Adversarial identity tests**: user-supplied identity, duplicate identity, silent
  replacement, revocation fail-closed, forged lifecycle transitions, role-name authority
  claims, capability-claim-vs-availability, no self-verification, no self-completion.
- **Novel domains**: legal document assistant, warehouse inventory assistant, language tutor
  agent, vehicle maintenance assistant.
- **Regressions**: M11, M12, M13, M14 preserved.
- **Phase 15.35**: full pytest + coverage, compileall, `git diff --check`, JSON validation,
  JS validation environment (expected `JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE`).
- **Phase 15.37**: single commit + bundle with required base `2d12390`. No push/merge; M16
  not started.

## 6. Stop conditions → MOVEMENT_15_BLOCKED

M15 is BLOCKED if implementation would require:
- Agent as Mission/resource authority,
- RRM/authorization/confirmation/binding bypass,
- self-verification or self-completion,
- direct Mission completion by an agent,
- weakening of M11–M14 guarantees,
- Constitution modification,
- unrestricted productive external execution,
- a broad autonomous-agent framework.
