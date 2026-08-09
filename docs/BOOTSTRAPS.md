# Intent OS Bootstrap Registry

`ApplicationFactory` is the official Composition Root. A valid user-facing
entry point receives or creates one factory and obtains the Kernel from it.

| Entry point | Classification | Status | Composition behavior |
|---|---|---|---|
| `intent_kernel.__main__:main` | official CLI | canonical | delegates through `create_cli_kernel()` to `ApplicationFactory` |
| `intent_kernel.server.app:get_kernel` | official server | canonical | creates an environment-configured `KernelBuilder` or uses an injected factory |
| `intent_os_desktop:create_app` | official Desktop | canonical | creates or receives one factory |
| `intent_os_desktop:main` | Desktop launcher | canonical | injects the Desktop factory into the local server before startup |
| direct `Kernel()` | compatibility | deprecated path | composes legacy defaults inside the constructor for characterized consumers |
| test builders/factories | test | canonical or explicit compatibility | tests choose the intended bootstrap mode |
| `IntentOSMonitor` | diagnostic | not a bootstrap | observes Kernel and optional public `ApplicationComponents` |
| `intent_os_desktop.spec` | packaging | canonical Desktop target | packages the Desktop launcher |

## Official flow

```text
Interface
  ↓
ApplicationFactory
  ↓
KernelBuilder
  ├─ Constitution + Guardians
  ├─ KnowledgeStore + KnowledgePipeline
  ├─ MissionStore + Mission Engine
  ├─ ProviderManager
  ├─ Core Apps + CapabilityRouter
  ├─ CapabilityRegistry
  ├─ AgentOrchestrator
  ├─ CapabilityExecutionService
  ├─ EventPublisher / Audit
  └─ IdempotencyStore
  ↓
Kernel (dependencies injected)
```

## Compatibility rule

Direct `Kernel()` remains available because the baseline and historical
consumers instantiate it. It reports `bootstrap_mode=compatibility`. New entry
points must not use it. It can be removed only after external-consumer
migration and parity validation.

## Domain routing rule

The official factory registers Atlas, Logos and OEM Studio as canonical domain
owners. Finance, knowledge-oriented and engineering routes execute through the
governed capability pipeline. `ModuleRouter` is injected only as a compatibility
facade for unmigrated domains and direct historical consumers; its use is
reported by `MigrationTelemetry`.
