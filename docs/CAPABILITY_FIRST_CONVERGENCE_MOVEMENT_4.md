# Intent OS — Capability-First Convergence, Movement 4

## Scope and evidence

This document records the executable architecture at starting SHA
`57553d8e07c6462d47251c1dbc26e50e30f9ac03`. Conclusions come from tracing
the Python entry points and the authoritative suite, not from RFC claims.
The machine-readable companion is `docs/runtime_map_capability_first.json`.

## Canonical source verification

- Repository: `cics1b252-glitch/IntentOS`
- Base: `recovery/canonical-product`
- Working branch: `architecture/capability-first-convergence`
- Starting SHA: `57553d8e07c6462d47251c1dbc26e50e30f9ac03`
- Baseline: 902 collected, 900 passed, 2 environment-restricted failures,
  12 subtests passed.

## Real runtime map

### Product conversation path today

`Gateway → ProductBridge._chat → IUE → ProductBridge heuristics → BCC/local
responses OR Kernel.process → Constitution → IntentEngine → domain-to-capability
map → CapabilityExecutionService/CoreApp → PipelineDAG → ModuleRouter/provider →
KnowledgePipeline → ProductBridge response/session persistence`

The path is hybrid. ProductBridge directly owns dialogue branches, finance and
application summaries, local responses, provider error translation and session
persistence. Kernel then runs both a canonical Core App route and the legacy
PipelineDAG for the same request.

### Deep cognitive controller path today

`ProductBridge diagnostic action → ECC → IUE → CDM → CPE → COR → execution graph`

This is reachable through explicit bridge actions, but it is not the default
chat path. MissionRuntime and Tool Access are implemented and unit tested but
are not the authority used by the default ProductBridge chat path.

### Interface composition

CLI and FastAPI obtain Kernel through `ApplicationFactory`. ProductBridge also
uses the factory but constructs IUE/CDM/CPE/COR/ECC and AME separately around
it. Therefore composition is canonical for Kernel dependencies but partial for
the product runtime.

## Fixed-domain dependency audit

| Dependency | Class | Current effect | Transition |
|---|---|---|---|
| `IntentEngine` domain keywords | A | Classification hint | Retain as non-authoritative signal |
| `Domain` in Mission/Knowledge schemas | A | Metadata and policy context | Retain |
| `CapabilityRouter._DOMAIN_DEFAULTS` | C | Domain selects execution destination | Require explicit capability |
| `Kernel._execute_canonical_route` mapping | D | Every domain maps to three fixed Core Apps | Replace with requirement resolution |
| `ApplicationFactory` unconditional Core Apps | C | Atlas/Logos/OEM become mandatory graph | Project them as optional capability providers |
| `ModuleRouter` | D | Domain loads FIN/Core modules | Keep only behind compatibility adapter |
| CPE domain/keyword plan branches | C | Planner shape determined by fixed task families | Feed abstract requirements into CPE |
| COR default catalog/agents | B/C | Useful capabilities but duplicated registry and named agents | Project into RRM |
| ProductBridge finance/app branches | D | Product response bypasses generic capability resolution | Migrate after parity tests |
| UI references to Core Apps | B | Presentation assumes modules | Deprecate after product route converges |

Domains remain useful as taxonomy, memory metadata, policy inputs and ranking
signals. They must not name an executor.

## Capability-first gap analysis

1. **CPE without a fixed module:** partially. Its plan is capability-shaped, but
   branch selection is still domain/keyword based and default catalogs are static.
2. **COR abstract requests:** yes. Plan steps contain `required_capabilities`,
   but COR uses a parallel RegistryCatalog.
3. **RRM dynamic discovery:** yes for registered providers, environments,
   capabilities and agents. Host discovery is catalog-level, not invasive.
4. **CapabilityRouter dynamic tools:** Tool Router can map abstract capability to
   tools; Core App Router cannot because it falls back to domain defaults.
5. **MissionRuntime dynamic graph:** structurally yes; it executes checkpointed
   nodes with gates and verification. It is not wired to default chat.
6. **BCC missing capability:** yes, truthfully, but RRM is optional in product
   composition and status vocabulary differs from the canonical contract.
7. **AME reusable compositions:** it can persist project-scoped memory, but no
   approved composition schema/lifecycle exists yet.
8. **Dynamic agent composition:** no. Existing orchestrators register/select
   static agents. No governed Agent Factory exists.
9. **System/app discovery:** partial contracts and Symbiotic discovery exist;
   no single authorized SystemCapabilityDiscoveryPort feeds RRM.
10. **Explicit availability states:** now represented by the minimal
    `CapabilityResolutionStatus` contract; execution integration remains future work.

## Minimal contracts introduced

`intent_kernel.cognition` introduces:

- `CapabilityRequirement`;
- `CapabilityCandidate`;
- `CapabilityResolution` and explicit truthful statuses;
- `CapabilityComposition` and ordered declarative steps;
- `CapabilityRequirementDiscovery`, a conservative capability-level bootstrap;
- `CapabilityFirstResolver`, which queries RRM and Tool Registry, ranks agents,
  applies Constitution before discovery, exposes permission gaps and never executes.

No existing contract was replaced. The service is intentionally not wired into
the default runtime until Movement 5 defines the canonical resolution engine.

## Dynamic agent composition readiness

**READY_WITH_PREREQUISITES.** Existing Agent contracts, RRM AgentResource,
CanonicalAgentOrchestrator, MissionRuntime, Tool Access and verification can be
reused. Missing prerequisites:

- a single RRM-backed agent catalog;
- an AgentBlueprint/AgentFactory contract;
- explicit instruction and memory scopes;
- Constitution gate for composition and registration;
- lifecycle decision: retain, improve or discard only after verified execution.

No self-modifying or arbitrary-code agent was introduced.

## System resource discovery readiness

**READY_WITH_PREREQUISITES.** RRM already models providers, accounts,
environments, capabilities, agents and projects. ToolRegistry models tools.
Symbiotic code observes host facts but is not a canonical permissioned discovery
port. Movement 7 should introduce a discovery adapter that emits candidates into
RRM. Discovery must never imply authorization, and authorization must never imply
action approval.

## Response assembly status

**BLOCKED.** There is no canonical CognitiveResponseAssembler. Responses are
fragmented across ProductBridge local heuristics, BCC, Provider output,
PipelineDAG delivery nodes and legacy modules. Future boundary inputs:

- conversation or mission result;
- verification evidence;
- relevant AME context;
- uncertainty and limitations;
- next safe actions;
- provenance and provider identity.

Movement 8 must create this boundary without becoming a presentation framework.

## Constitution enforcement status

| Gate | Code exists | Tested | Connected | Authoritative |
|---|---:|---:|---:|---:|
| Kernel input/process | yes | yes | yes | yes |
| Knowledge ingest | yes | yes | yes | yes |
| Capability execution | yes | yes | yes | yes |
| Capability resolution | now | yes | not yet | no |
| CPE planning | partial | yes | ECC only | no for product chat |
| Tool authorization | yes | yes | MissionRuntime path | no for product chat |
| Response output | no single gate | partial | fragmented | no |

CanonicalConstitutionEngine and ConstitutionPipeline are the target. Legacy
checkers/Guardian representations remain compatibility debt. No constitutional
rule was changed.

## Knowledge pipeline truth

| Stage | Code exists | Unit tested | Connected | Authoritative in runtime |
|---|---:|---:|---:|---:|
| Constitution Gate | yes | yes | yes | yes |
| Knowledge Score | yes | yes | via CanonicalCurator | yes |
| Threshold decisions | yes | yes | yes | yes |
| Conflict handling | yes | yes | yes | yes |
| Curator action | yes | yes | yes | yes |
| Audit | yes | yes | yes | yes |
| AME/KOM persistence | yes | yes | ProductBridge path | memory authority separate from PKB |

Knowledge Score is not merely documented: `KnowledgePipeline.ingest` calls
`CanonicalKnowledgeCurator.curate`; that curator builds the score, applies
thresholds and conflict policy, and the pipeline persists and publishes audit.
PKB is the knowledge authority. AME/KOM remains the scoped conversational/project
memory authority; this movement does not create a second memory truth.

## Legacy convergence plan

| Current | Transition | Canonical target |
|---|---|---|
| Domain Router | Compatibility adapter | Capability requirement discovery |
| AtlasCoreApp | Capability provider adapter | RRM-resolved capabilities |
| LogosCoreApp | Capability provider adapter | RRM-resolved knowledge/reasoning resources |
| OEMStudioCoreApp | Capability provider adapter | Dynamic engineering composition |
| FinModule/CoreModule | Legacy executor | Reusable capability packages |
| CanonicalCapabilityRegistry | RRM projection adapter | RRM single resource authority |
| COR RegistryCatalog | Read-through RRM adapter | RRM single resource authority |
| ProductBridge heuristics | Characterized compatibility branches | Thin chat/mission interface |
| PipelineDAG | Legacy compatibility pipeline | Explicit Chat or Mission path |

Stages: stop new domain dependencies; expose useful behavior as capabilities;
route new intents capability-first; retain adapters; remove only after reachability
and regression proof.

## Explicit canonical path targets

### Cognitive conversation

`User → Constitution → IUE → AME Context → CDM → Capability Assessment →
BCC/Provider/local decision → Response Validation → User`

Conversation must not create an executable mission unless the capability
assessment identifies action, persistence beyond conversational memory, or an
external effect.

### Cognitive mission

`User → Constitution → IUE → AME Context → CDM → CapabilityRequirement → CPE →
RRM/COR → ECC/Mission Engine → MissionRuntime → Tool Access → Verification →
Response Validation → AME learning candidate`

All effects remain supervised, permissioned, idempotent and auditable.

## Movement readiness

- Movement 5, canonical requirement/resolution engine: **READY**. Contracts and
  safe resolution prototype now exist.
- Movement 6, dynamic Agent Factory: **READY_WITH_PREREQUISITES**. Requires
  Movement 5 authority and an approved AgentBlueprint lifecycle.
- Movement 7, system/application discovery: **READY_WITH_PREREQUISITES**.
  Requires permissioned discovery port and RRM ingestion policy.
- Movement 8, response assembly: **READY_WITH_PREREQUISITES**. Requires explicit
  Chat/Mission result contracts and output Constitution gate.
- Movement 9, learning from verified missions: **BLOCKED** until verification
  provenance and reusable-composition approval are canonical.
- Movement 10, legacy retirement: **BLOCKED** until reachability telemetry and
  parity tests show no product dependence.

## Known technical debt

Confirmed but deliberately not bundled into this architectural movement:

- repository `pytest.py` shadows real pytest under `python -m pytest`;
- JavaScript WAITING_CONTEXT/execution_plan mismatch;
- ProductBridge is an oversized parallel orchestrator;
- RRM, COR catalog and CanonicalCapabilityRegistry overlap;
- MissionRuntime/ToolAccess are not default product authorities;
- response assembly and output gate are fragmented;
- EventBus async isolation, permission revoke scope, CORS, timing-safe API auth,
  provider health/routing semantics and domain-filter behavior require separate
  reproduction before fixes.

