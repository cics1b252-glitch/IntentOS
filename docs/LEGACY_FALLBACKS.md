# Legacy Fallback Inventory

Sprint 8 makes every fallback explicit. Presence in this register is not
approval for new use; it is a compatibility obligation with a removal
condition.

| Fallback | Input | Output | Current consumer | Why it remains | Canonical substitute | Test/evidence | Risk | Removal condition |
|---|---|---|---|---|---|---|---|---|
| `ModuleRouter` | legacy intent/domain/context | legacy module result | direct compatibility Kernel, direct tests, unmigrated domains | preserves non-migrated domain behavior | `CapabilityRouter` | baseline plus Sprint 8 fallback telemetry test | parallel authority if called accidentally | every domain canonical and no external consumer |
| `CoreModule` | intent and context | provider/template response | `ModuleRouter` for unmigrated domains | preserves generic responses | domain Core App or explicit unavailable result | baseline and import-boundary test | generic behavior can mask missing ownership | each remaining domain has an owner and parity tests |
| FIN / `FinanceModule` | financial intent | historical finance response | Atlas internals, direct tests | exact finance output parity | native Atlas implementation | finance output-parity test | duplicate domain implementation | Atlas owns logic natively and direct consumers are migrated |
| direct `Kernel()` composition | constructor defaults | compatibility application graph | historical tests/integrations | public baseline contract | `ApplicationFactory` | bootstrap tests and dependency audit | new code may bypass canonical composition | repository and external consumers use factory |
| `LegacyCapabilityExecutorAdapter` direct mode | canonical capability | legacy module execution | standalone compatibility consumers | adapter historically worked without composition | governed `CapabilityExecutionService` | governed adapter delegation test | standalone mode bypasses full canonical governance | all consumers receive canonical services |
| `LegacyKnowledgeStoreAdapter` | canonical events | legacy JSON records | canonical PKB composition | persistent format compatibility | native canonical store | PKB baseline and Sprint 3 tests | conversion and format drift | data migration and rollback validated |
| `LegacyProviderAdapter` | canonical provider request | legacy provider request | provider compatibility exports | supports historical providers | native Provider Port implementations | provider tests | inconsistent metadata | all supported providers are native |
| historical `CapabilityRegistry` | historical registrations | historical lookup | direct legacy imports/tests only | public compatibility API | `CanonicalCapabilityRegistry` | official-graph and read-only tests | competing registration authority | no external consumers |
| historical `AgentOrchestrator` | historical agent task | historical result | direct legacy imports/tests only | public compatibility API | canonical Agent Orchestrator | official-graph import test | competing execution authority | no external consumers |
| legacy Constitution adapters | historical decisions | canonical verdict | compatibility composition | behavior parity | canonical Constitution Engine | Sprint 4 tests | dual models at boundary | all consumers speak canonical verdict |
| legacy agent adapters | legacy agent calls | canonical agent result | characterized historical agents | avoid rewriting agent logic | canonical Agent contract | Sprint 6 tests | incomplete metadata/capability declaration | each supported agent becomes native |

## Telemetry

`MigrationTelemetry` records canonical calls by domain, fallback calls by
domain, legacy component calls, direct production dependency counts, and
canonical/fallback percentages. The Monitor exposes this snapshot without
taking ownership of routing and without recording secrets or full user content.

## Known direct production dependencies

| Component | Direct imports | Allowed locations |
|---|---:|---|
| FIN | 5 | composition, Atlas implementation, Kernel compatibility and module exports |
| `ModuleRouter` | 3 | composition, Kernel compatibility and router export |
| `CoreModule` | 4 | composition, Kernel compatibility and module exports |
| historical Capability Registry | 0 in official graph | legacy package only |
| historical Agent Orchestrator | 0 in official graph | legacy package only |

Any increase fails the Sprint 8 architecture test.
