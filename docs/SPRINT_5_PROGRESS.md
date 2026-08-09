# Sprint 5 — Canonical Core Apps and Capability Router

## Executive summary

Sprint 5 establishes the official Core App boundary and the canonical
`CapabilityRouter`. Atlas, Logos and OEM Studio now implement one
infrastructure-independent contract and are composed once by `KernelBuilder`.

The user-facing pipeline continues to use the historical `ModuleRouter`, so
the characterized responses remain unchanged. The old router, FIN and all
historical bootstraps remain available.

## Canonical architecture

```text
Mission
  |
  v
CapabilityRouter (official CapabilityExecutor)
  |
  +-- finance.intent ------------> AtlasCoreApp
  |
  +-- knowledge.* ---------------> LogosCoreApp ----> KnowledgeStore Port
  |
  +-- engineering.* -------------> OEMStudioCoreApp
  |
  v
CapabilityResult
```

The composition root owns registration:

```text
ApplicationFactory
  -> KernelBuilder
     -> CapabilityRouter
        -> AtlasCoreApp
        -> LogosCoreApp
        -> OEMStudioCoreApp
```

Core Apps do not create a Kernel, Constitution, ProviderManager, PKB or
infrastructure adapter.

## Canonical contracts

### `CapabilityRequest`

Carries:

- the canonical `Mission`;
- requested capability;
- payload;
- execution context.

### `CoreApp`

Every current or future Core App must expose only:

- `app_id`;
- immutable capability descriptors;
- `execute(CapabilityRequest) -> CapabilityResult`;
- `health()`.

The contract is runtime-checkable and independent from infrastructure.

### `CapabilityRouter`

Responsibilities implemented:

1. receive a Mission;
2. identify the default capability from the Mission domain when one is not
   explicit;
3. select the unique Core App that owns the capability;
4. forward a canonical request;
5. return a canonical result;
6. reject ambiguous capability ownership;
7. return `CAPABILITY_UNAVAILABLE` when no app can execute the request.

It also implements the existing `CapabilityExecutor` Port, allowing callers
that do not yet create Missions directly to use the canonical route.

## Official Core Apps

### Atlas

`AtlasCoreApp` is the official financial boundary.

- capability: `finance.intent`;
- domain: Finance;
- delegates to the characterized FIN implementation;
- returns exactly the existing FIN text, confidence and metadata;
- owns no provider, PKB or Kernel.

FIN remains a legacy implementation behind the official Atlas boundary until
its behavior can be migrated without changing responses.

### Logos

`LogosCoreApp` is the official knowledge-domain boundary.

- capabilities:
  - `knowledge.project.create`;
  - `knowledge.project.list`;
  - `knowledge.search`;
- project behavior delegates to the existing Logos domain;
- PKB queries use only the canonical `KnowledgeStore` Port;
- Logos remains semantically distinct from the PKB.

### OEM Studio

`OEMStudioCoreApp` is the official engineering boundary.

- capabilities:
  - `engineering.project.create`;
  - `engineering.project.list`;
- delegates to the existing OEM Studio domain;
- holds no infrastructure or host dependency.

## Compatibility

The following remain operational:

- `ModuleRouter`;
- `LegacyCapabilityExecutorAdapter`;
- `CoreModule`;
- `FinanceModule` (`FIN`);
- the historical pipeline route in `engine/nodes.py`;
- direct construction of `Kernel`;
- CLI, FastAPI and Desktop bootstraps.

`ApplicationComponents` now exposes both:

- `capability_router` / `capability_executor`: official route;
- `module_router` / `legacy_capability_executor`: compatibility route.

No legacy code was removed or renamed.

## Adherence to ArchitectureTarget v2

Completed:

- one `CoreApp` contract;
- one canonical capability request and result;
- one official Capability Router;
- Atlas, Logos and OEM Studio registered through the composition root;
- Logos connected to PKB through a Port;
- OEM Studio separated from infrastructure;
- FIN behavior preserved behind Atlas;
- ModuleRouter explicitly retained as compatibility infrastructure.

Estimated Core Apps and routing migration: **85%**.

Estimated total architectural migration: **88%**.

## Tests

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

- collected: 497;
- passed: 494;
- failed: 3;
- skipped: 0;
- collection errors: 0;
- warnings: 3;
- global coverage: 78%.

Sprint 5 added 10 tests; all pass.

The three failures and three warnings are unchanged from the Sprint 0
baseline:

1. locale decoding in `test_kernel_independence.py`;
2. installed-program discovery in the sandbox;
3. write permission for the real user PKB path in `test_symbiotic.py`;
4. three historical unawaited `KnowledgeManager.count` warnings.

No new regression was observed.

## Remaining legacy components

- FIN remains the characterized implementation behind Atlas;
- `ModuleRouter` remains active inside the historical response pipeline;
- `CoreModule` remains the old fallback;
- `LegacyCapabilityExecutorAdapter` remains available;
- Monitor and server diagnostics still display legacy module names;
- direct `Kernel()` construction still composes the legacy capability adapter;
- old module trigger/domain maps remain the active user-response route.

## Preparation for Sprint 6

Sprint 6 should migrate the execution pipeline to request capabilities through
the canonical router while running parity tests against `ModuleRouter`.
Migration should proceed one domain at a time:

1. Finance through Atlas with exact response parity;
2. engineering through OEM Studio only where an existing route exists;
3. knowledge through Logos only where behavior is already characterized;
4. fallback behavior last.

The legacy route should not be removed until CLI, FastAPI and Desktop parity
has been demonstrated and rollback remains available.

## Risks

1. Switching `engine/nodes.py` prematurely would change user-visible fallback
   behavior.
2. Treating Logos as the PKB would merge domain semantics with infrastructure.
3. Moving FIN calculations directly into Atlas without parity tests could
   change financial responses.
4. Allowing duplicate capability ownership would make routing nondeterministic.
5. Giving Core Apps direct provider or host access would violate the canonical
   architecture.

## Intent Design System Foundation

This complementary mission establishes the normative Intent Design System
foundation without modifying code, behavior, canonical contracts, or the
Sprint 5 composition.

Official documents:

- `docs/design/README.md`;
- `docs/design/IDS-001_LIVING_INTERFACE.md`;
- `docs/design/IDS-002_COLOR_SYSTEM.md`;
- `docs/design/IDS-003_COGNITIVE_SPACES.md`;
- `docs/design/IDS-004_COMPONENT_FOUNDATION.md`.

Decisions:

- IDS belongs exclusively to the presentation layer;
- Kernel, PKB, Constitution, Providers, Core Apps, and the canonical
  architecture do not depend on visual components;
- initial tokens are conceptual contracts, with no executable token file yet;
- `intent_kernel/ids` remains preserved as a historical implementation;
- no UI library was selected;
- no incomplete visible feature was introduced.

The foundation formalizes Living Interface, Cognitive Spaces, Silent UI,
Attention Principle, Visual Continuity, accessibility by default, and
Cognitive Pulse as an observable process state rather than emotion or
consciousness.
