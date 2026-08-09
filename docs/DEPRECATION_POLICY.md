# Intent OS Deprecation Policy

## Purpose

Legacy code is removed only after its canonical replacement has demonstrated
equivalent behavior. Deprecation is a migration state, not evidence that a
component is safe to delete.

Every retained legacy component must record:

1. why it remains;
2. known consumers;
3. canonical replacement;
4. compatibility adapter or facade;
5. removal condition;
6. target Sprint;
7. characterization or parity tests.

Runtime warnings are avoided while characterized consumers still depend on a
component. Deprecation is expressed in documentation and docstrings first.

## Current register

| Legacy component | Why it remains | Known consumers | Canonical replacement | Adapter/facade | Removal condition | Target |
|---|---|---|---|---|---|---|
| `FinanceModule` / FIN | exact historical finance behavior | Atlas internals and direct tests | `AtlasCoreApp` | Atlas delegates internally to FIN | no direct consumers and native Atlas parity for all scenarios | Sprint 9+ |
| `ModuleRouter` | unmigrated domain fallback and historical APIs | direct `Kernel()`, explicit compatibility calls and tests | `CapabilityRouter` | telemetry-enabled compatibility facade | every domain uses canonical capabilities and external consumers are migrated | Sprint 9+ |
| `CoreModule` | provider/fallback behavior for unmigrated domains | ModuleRouter compatibility | domain Core Apps or canonical unavailable result | ModuleRouter facade | every remaining domain has an owner and parity validation | Sprint 9+ |
| historical `CapabilityRegistry` | public historical API and tests | legacy consumers outside Composition Root possible | `CanonicalCapabilityRegistry` | none required in canonical graph | repository and release consumers migrated | Sprint 8+ |
| historical `AgentOrchestrator` | public historical API and agent tests | legacy imports | `CanonicalAgentOrchestrator` | `LegacyAgentAdapter` per agent | external consumers migrated | Sprint 8+ |
| direct `Kernel()` composition | broad baseline usage | tests and historical integrations | `ApplicationFactory` | constructor compatibility mode | entry points and external consumers migrate | Sprint 9+ |
| `LegacyKnowledgeStoreAdapter` | canonical Port over JSON legacy model | PKB and Kernel composition | native canonical store | adapter | durable canonical store and data migration | future persistence Sprint |
| `LegacyProviderAdapter` | provider protocol compatibility | component export and registry | native Provider contract | adapter | all providers implement canonical contract natively | Sprint 8+ |

Sprint 8 inventory and dependency evidence are maintained in
`LEGACY_FALLBACKS.md`. Migrated domain requests must never enter
`ModuleRouter`; this is enforced by tests and runtime migration telemetry.

## Evidence required for removal

- repository search finds no real consumer;
- public entry points delegate to the canonical composition;
- characterization and replacement tests pass;
- rollback or release migration is documented;
- baseline has no new regression;
- architecture and progress documentation are updated.
