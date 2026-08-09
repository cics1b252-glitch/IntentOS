# Sprint 6 — Canonical Agent Orchestration and Capabilities

## Executive summary

Sprint 6 establishes one official Agent Orchestrator, one official Capability
Registry and one governed capability execution service.

The new layer does not plan missions, change mission lifecycle, create agents
dynamically or access the host directly. It coordinates already-declared
capabilities under the authority of the Mission Engine, Constitution and PKB.

All historical agents and the historical orchestrator remain available.

## Official architecture

```text
MissionId
   |
   v
Mission Engine (loads Mission and owns lifecycle)
   |
   v
CanonicalCapabilityRegistry (discovery and executor ownership)
   |
   v
ConstitutionEngine (policy verdict + constitutional audit)
   |
   v
CapabilityExecutionService
   |
   +--> CapabilityRouter --> Core App
   |
   +--> AgentOrchestrator --> Agent
   |
   +--> ProviderManager --> Provider Port
   |
   v
CapabilityResult
   |
   +--> capability.audit
   |
   +--> Agent result candidate --> KnowledgePipeline
                                      |
                                      +--> Constitution
                                      +--> Curator
                                      +--> persistence/audit
   |
   v
Mission Engine caller
```

The execution service receives a `MissionId`, not an arbitrary mutable Mission.
It loads the Mission through `MissionEngine` and only executes while the
Mission is `RUNNING`. It never transitions, completes, pauses or resumes the
Mission.

## Canonical Agent contract

The Sprint 1 Port was consolidated with:

- `AgentId`: stable, non-empty logical identity;
- declared immutable `Capability` descriptors;
- `AgentLimits`: timeout, maximum output and attempt limit;
- `AgentRequest`: Mission, capability, task, bounded context and limits;
- canonical `CapabilityResult`;
- normalized `ErrorCode`;
- agent metadata added by the orchestrator.

An Agent:

- executes only a declared capability;
- receives bounded context;
- cannot mutate the Mission through the contract;
- receives no Store or KnowledgeManager;
- returns a result but cannot make it official knowledge;
- may use a Provider only through an injected Provider Port or the canonical
  ProviderManager boundary.

## Canonical Agent Orchestrator

`CanonicalAgentOrchestrator` is the single official orchestrator.

Responsibilities:

1. register canonical Agents;
2. discover Agents by declared capability;
3. select a compatible Agent deterministically;
4. apply the lower timeout/output limit from Agent and request;
5. normalize missing-agent and timeout errors;
6. return a canonical result.

It does not:

- own Mission state;
- perform policy decisions;
- persist knowledge;
- infer capabilities from arbitrary text;
- coordinate multi-agent deliberation.

## Canonical Capability Registry

`CanonicalCapabilityRegistry` associates capability descriptors with:

- Core Apps;
- Agents;
- Providers.

Each registration identifies:

- capability;
- executor kind;
- executor identity;
- requirements;
- network requirement;
- effect classification;
- confirmation requirement;
- availability through the executor health contract.

The historical `intent_kernel.capabilities.CapabilityRegistry` remains
unchanged for compatibility, but is not the official registry.

## Effects and safeguards

Official effect classifications:

| Effect | Meaning |
|---|---|
| `READ` | Read-only access |
| `COMPUTE` | Deterministic calculation/analysis |
| `GENERATE` | Generated output without direct persistence |
| `PERSIST` | Internal persisted state |
| `EXTERNAL_CHANGE` | Change outside Intent OS |
| `IRREVERSIBLE` | Material action without reliable rollback |

`PERSIST`, `EXTERNAL_CHANGE` and `IRREVERSIBLE` require an idempotency key.
Capabilities marked `requires_confirmation` also require explicit
confirmation.

Idempotency is scoped by:

```text
(mission_id, capability, idempotency_key)
```

Repeated execution returns the stored canonical outcome and does not call the
executor again.

No external integration was added in this Sprint.

## Official execution paths

### Core App

The service delegates the request to `CapabilityRouter.execute_mission`.
Atlas, Logos and OEM Studio behavior remains as characterized in Sprint 5.

### Agent

The service delegates a bounded `AgentRequest` to the official orchestrator.
Successful agent output is proposed as a canonical `KnowledgeEvent` with
`candidate=True`. Only `KnowledgePipeline`, Constitution and Curator decide
whether it is stored.

### Provider

The service obtains a Provider through `ProviderManager` and calls only the
canonical Provider Port using `ProviderRequest`. No agent or orchestrator
imports Mock, OpenAI or another concrete Provider.

## Audit and observability

Every authorized execution attempt emits `capability.audit` with:

- Mission ID;
- capability;
- executor identity and kind;
- duration;
- success or canonical error;
- external-effect classification;
- constitutional decision;
- constitutional audit ID;
- presence of an idempotency key.

The audit deliberately excludes:

- task/input text;
- output content;
- provider messages;
- secrets;
- raw credentials;
- the idempotency key itself.

Constitutional decisions also retain their independent `constitution.audit`,
and accepted agent knowledge retains the PKB `knowledge.audit`.

## Integrated historical agents

Through `LegacyAgentAdapter`:

| Historical agent | Canonical ID | Capabilities |
|---|---|---|
| `FinanceAgent` | `finance` | investment analysis, portfolio, retirement |
| `KnowledgeAgent` | `knowledge` | project management, decision tracking, research |
| `EngineeringAgent` | `engineering` | CAD, technical documentation |

Adapters construct the agents without a Kernel, preventing the historical
direct-write path from being used by canonical orchestration.

## Historical components that cannot yet satisfy the contract directly

- historical `AgentOrchestrator` may write to `kernel.knowledge` when given a
  Kernel;
- historical Agents expose mutable capability lists;
- historical Agents do not declare limits or effect metadata;
- historical selection infers an agent from keywords rather than an explicit
  capability;
- historical `AgentResult.events_created` describes direct persistence;
- historical capability registry stores callable infrastructure interfaces.

These components remain accessible and tested, but only adapters participate
in the canonical flow.

## ApplicationFactory composition

`KernelBuilder` now composes:

- canonical Capability Router and Core Apps;
- canonical Capability Registry;
- canonical Agent Orchestrator;
- three legacy Agent adapters without Kernel access;
- registered canonical Providers;
- Capability Execution Service;
- historical Agent Orchestrator for compatibility.

This produces the complete canonical application layer from one composition
root.

## Test results

Environment:

- Windows 10;
- Python 3.13.14;
- pytest 9.1.1;
- pytest-cov 7.1.0.

Commands:

```powershell
.\.venv\Scripts\python.exe -m compileall -q intent_kernel
.\.venv\Scripts\python.exe -m pytest --cov=intent_kernel --cov-report=term -q
```

Results:

- collected: 508;
- passed: 505;
- failed: 3;
- skipped: 0;
- collection errors: 0;
- warnings: 3;
- global coverage: 79%.

Sprint 6 added 11 tests; all pass.

The three failures and three warnings are unchanged from the Sprint 0
baseline:

1. Windows locale decoding in `test_kernel_independence.py`;
2. installed-program discovery in the sandbox;
3. write permission for the real user PKB path in `test_symbiotic.py`;
4. three historical unawaited `KnowledgeManager.count` warnings.

No Sprint 6 regression was observed.

## ArchitectureTarget v2 adherence

Implemented:

- Agent Port and bounded canonical request;
- official Agent Orchestrator;
- official Capability Registry;
- Core App, Agent and Provider executor association;
- Mission Engine authority;
- Constitution pre-execution validation;
- Provider Port-only execution;
- PKB candidate flow for agent output;
- effect metadata, confirmation and scoped idempotency;
- audit without sensitive payloads;
- composition through ApplicationFactory;
- legacy compatibility without removal.

Estimated agent/capability-layer migration: **92%**.

Estimated total architectural migration: **94%**.

## Remaining concrete and legacy dependencies

- historical Agent Orchestrator and Agents;
- historical Capability Registry;
- FIN and ModuleRouter in the visible response pipeline;
- direct `Kernel()` bootstrap still uses legacy capability composition;
- ProviderManager selection remains the characterized first/default policy;
- in-memory MissionStore;
- in-memory audit/idempotency state;
- legacy Monitor does not yet present canonical orchestration health;
- Core App domain implementations still coexist with their historical APIs.

## Risks and Sprint 7 preparation

1. Idempotency storage is in-memory and must gain a Port before process-level
   restart guarantees can be claimed.
2. Provider routing is canonical at the contract boundary but still uses the
   characterized default-provider policy.
3. Capability audit persistence needs a dedicated audit sink before external
   effects are enabled.
4. Agent-result content is intentionally bounded, but a future redaction
   service is required before sensitive production workloads.
5. Migrating the visible pipeline must use parity tests and retain rollback to
   ModuleRouter.
6. Historical agents that require direct Kernel access must not be registered
   canonically until rewritten behind Ports.

Sprint 7 should focus on interface convergence, persistent execution records
and parity of the visible pipeline. It must not expand agent autonomy.
