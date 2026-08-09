# Sprint 7 — Canonical Composition Convergence

## Executive summary

Sprint 7 makes `ApplicationFactory` the official Composition Root for CLI,
FastAPI and Desktop. The canonical finance path now runs through Mission
Engine, Constitution, Capability Registry, Capability Router and Atlas before
returning through the characterized response pipeline.

No product feature or response redesign was introduced. FIN, ModuleRouter and
CoreModule remain compatibility implementations where equivalence has not yet
been demonstrated.

## Final Composition Root

`KernelBuilder.build()` composes:

- Kernel;
- Mission Engine and injected `MissionStore`;
- canonical Constitution and Guardians;
- Capability Router and Registry;
- canonical Agent Orchestrator;
- ProviderManager and configured Providers;
- Atlas, Logos and OEM Studio;
- KnowledgeStore, KnowledgeManager and KnowledgePipeline;
- EventBus through `EventPublisher` for audit;
- injected `IdempotencyStore`;
- legacy adapters still required by characterized behavior.

Audit uses the existing `EventPublisher` Port. Mission and idempotency stores
are in memory. Knowledge remains on the JSON adapter. Durable mission,
idempotency and audit persistence are explicitly outside this Sprint.

## Official initialization

```text
CLI / FastAPI / Desktop
  ↓
ApplicationFactory (singleton per interface host)
  ↓
KernelBuilder
  ↓
ApplicationComponents
  ↓
Kernel with injected canonical dependencies
```

The Desktop launcher now gives its factory to FastAPI, preventing a second
application graph in the same process. OpenAI environment configuration moved
from server mutation into `KernelBuilder.with_environment()`.

See `docs/BOOTSTRAPS.md` for the complete entry-point inventory.

## Visible finance flow

```text
input
  ↓
Kernel
  ↓
Mission Engine (create/start)
  ↓
Constitution
  ↓
Capability Registry
  ↓
Capability Router
  ↓
AtlasCoreApp
  ↓
FIN compatibility implementation
  ↓
Audit + characterized response pipeline + PKB
  ↓
Mission Engine (complete)
```

Atlas is the official owner of `finance.intent`. FIN remains its internal
compatibility implementation so exact text, confidence, missing-value handling
and fallback behavior remain unchanged.

## Components migrated

- CLI, FastAPI and Desktop bootstraps converge on `ApplicationFactory`;
- environment Provider registration belongs to `KernelBuilder`;
- finance execution uses canonical mission/capability governance;
- Monitor consumes public canonical composition metadata;
- idempotency state is injected through the new `IdempotencyStore` Port;
- Provider default selection uses a public `ProviderManager` method.

## Controlled removals

No legacy source file was deleted.

The first safe removal from the active graph consists of:

1. duplicate OpenAI registration and private `_default` mutation in FastAPI;
2. unused instantiation of the historical `AgentOrchestrator` inside the
   canonical composition.

Both had canonical replacements and no active consumer. Historical classes
remain importable for compatibility.

## Preserved adapters and legacy

- `LegacyKnowledgeStoreAdapter`;
- `LegacyProviderAdapter`;
- `LegacyEventPublisherAdapter`;
- `LegacyCapabilityExecutorAdapter`;
- `LegacyAgentAdapter`;
- `ModuleRouter`;
- `FinanceModule`;
- `CoreModule`;
- direct `Kernel()` compatibility composition;
- historical capability and agent registry APIs.

The reason, consumer, replacement and removal condition for each component are
recorded in `docs/DEPRECATION_POLICY.md`.

## Monitor and diagnostics

When constructed with `ApplicationComponents`, Monitor reports:

- bootstrap mode;
- Mission Engine;
- Constitution;
- Capability Router and Registry;
- Agent Orchestrator;
- ProviderManager;
- Core Apps;
- KnowledgePipeline;
- active store types;
- legacy adapters.

It exposes descriptions provided by the composition rather than inspecting
private registries. No prompts, API keys or payloads are included.

## Remaining concrete dependencies

- direct `Kernel()` still creates EventBus, JSON store, ProviderManager,
  MockProvider, ModuleRouter, CoreModule and FIN in compatibility mode;
- Atlas delegates to FIN for characterized response parity;
- ModuleRouter handles unmigrated fallback paths and legacy dashboards;
- Logos and OEM Studio retain their current domain implementations;
- JSON persistence still requires legacy/canonical event conversion;
- EventBus is the current audit implementation.

## Stores still in memory

- `InMemoryMissionStoreAdapter`;
- `InMemoryIdempotencyStoreAdapter`;
- capability execution replay data through the injected idempotency store;
- EventBus audit history.

Replacing them with durable adapters will not require domain changes because
composition depends on Ports.

## Test coverage added

Sprint 7 tests characterize:

- complete factory composition;
- canonical and compatibility bootstrap modes;
- Atlas/FIN output and confidence parity;
- Mission completion;
- shared CLI/Desktop/FastAPI factory;
- Provider environment composition;
- canonical Monitor diagnostics;
- public Provider default selection;
- absence of historical registries as canonical authorities;
- injected Kernel dependencies.

## Architecture conformance

The Sprint conforms to `ArchitectureTarget_v2.md`:

- dependencies are assembled at the outer composition boundary;
- Mission Engine owns lifecycle;
- Constitution runs before capability execution;
- CapabilityRouter owns Core App routing;
- canonical Agent Orchestrator is the only orchestrator in the official graph;
- agents do not persist directly;
- interfaces share one Kernel graph;
- compatibility remains explicit and documented.

## Risks

1. Direct `Kernel()` remains a substantial compatibility composition.
2. Finance parity currently relies on Atlas delegating to FIN.
3. Non-finance visible paths still use ModuleRouter/provider fallback.
4. Durable mission, audit and idempotency persistence is not implemented.
5. External consumers of historical registries cannot be proven absent from
   repository-only analysis.

## Preparation for Sprint 8

Sprint 8 should migrate one remaining visible domain at a time from
ModuleRouter, add parity tests for CoreModule/provider fallback, and introduce
explicit public health contracts if Monitor requirements expand. FIN should
not be deleted until Atlas owns its logic and all direct consumers disappear.

