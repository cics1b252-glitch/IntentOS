# Movement 13 — Resource Authority Map

## Audited baseline

- Repository: `cics1b252-glitch/IntentOS`
- Source branch: `architecture/cognitive-response-product-convergence`
- Source HEAD: `9c0ab87e8dd5fada1aae861e3f196a9d547967e8`
- Movement 13 branch: `architecture/resource-binding-registry-convergence`
- Movement 11 runtime baseline: `31e44bd6c8c7dac38e813b952e478f2d66eef130`

## Governing invariant

`REGISTERED != AVAILABLE != ELIGIBLE != AUTHORIZED != INVOKED != SUCCESSFUL`

RRM owns runtime availability and eligibility truth. Registries retain known
invocation handles, binding authorities select only among RRM-eligible handles,
authorization gates decide whether a selected resource may be used, invocation
boundaries record attempts, and verification decides whether an observed result
satisfied its contract.

## Canonical pipeline

```text
CapabilityRequirementDiscovery
→ CapabilityFirstResolver
→ RRM
→ CanonicalResourceBindingAuthority
→ ToolAuthorizationGate / Constitution
→ MissionRuntime or controlled CapabilityExecutionService
→ observed invocation boundary
→ VerificationGate / MissionCompletionGate
```

Provider execution follows:

```text
CanonicalProviderAuthority
→ RRM eligibility and health
→ ProviderManager binding
→ ManagedProvider invocation boundary
→ attempted / used evidence
```

## Authority before Movement 13

RRM already rejected unavailable registered resources, but three residual gaps
remained:

1. dispatch-time binding revalidation repeated RRM status but did not repeat
   binding health or prove that the exact registry entry still existed;
2. canonical provider capability execution fetched the raw provider object,
   bypassing ProviderManager invocation evidence;
3. provider-backed Core Apps held a registered default provider and could invoke
   it without a fresh canonical provider selection.

ProductBridge also constructed ECC with the legacy COR default catalog. That
catalog was diagnostic, not executable, but could describe resources absent
from the canonical RRM.

## Final authority matrix

| Component | Classification | Inputs and outputs | State owned / decisions | RRM enforcement and invocation | Compatibility / retirement |
| --- | --- | --- | --- | --- | --- |
| CapabilityRequirementDiscovery | `DISCOVERY_ONLY` | User intent → capability requirements | Owns no resource state; identifies demand only | Does not invoke | Retain |
| CapabilityFirstResolver | `CANONICAL_AUTHORITY` | Requirements + RRM query → declarative composition | Chooses capability strategy from RRM evidence; no execution | Consults RRM, never invokes | Retain |
| RegistryResourceManager (RRM) | `CANONICAL_AUTHORITY` | Projected/discovered resource evidence → resource records and eligibility queries | Sole runtime availability/eligibility truth | Canonical source for resolution and dispatch revalidation | Retain |
| RuntimeResourceProjection | `DERIVED` | Runtime binding registration → RRM evidence | Owns no availability truth; writes projection into RRM | Cannot invoke | Retain while registrations are projected |
| CanonicalCapabilityRegistry | `REGISTRY_ONLY` | Capability/executor handles → deterministic binding catalog | Knows exact callable bindings; cannot declare availability | RRM binding authority filters every canonical use | Retire `select()` after external callers migrate to binding authority |
| CanonicalResourceBindingAuthority | `CANONICAL_AUTHORITY` | Capability + registry catalog + RRM → typed binding decision | Sole capability-binding selection; records registered, eligible, healthy and selected stages | RRM checked at resolution; exact entry, RRM and health rechecked before dispatch | Retain |
| CapabilityExecutionService | `EXECUTION_BINDING` | Running Mission + validated binding → controlled result | Dispatch only; does not own resource or Mission truth | Requires resolution, Constitution, and dispatch-time revalidation | Retain |
| CanonicalProviderAuthority | `CANONICAL_AUTHORITY` | Provider requirement + RRM + binding health → immutable selection | Sole provider eligibility/selection for canonical paths | Revalidates RRM, binding presence and health | Retain |
| ProviderManager | `EXECUTION_BINDING` | Selected provider ID → ManagedProvider | Stores provider handles and observed `last_attempted`/`last_used`; does not select canonical resources | Canonical calls use typed selections or `bind_selected`; direct default is traced compatibility | Retire direct default after all callers supply selections |
| RRMProviderBinding | `EXECUTION_BINDING` | ProviderRequest → fresh RRM selection → ManagedProvider | No resource truth; provider-backed Core App port | Selects and revalidates through CanonicalProviderAuthority before every invocation | Retain until Core Apps express provider dependencies natively |
| ManagedProvider | `EXECUTION_BINDING` | Selected binding + request → ProviderResponse | Actual provider attempt/use evidence | Invokes only selected provider; canonical binding disables manager-global fallback | Retain |
| CanonicalAgentOrchestrator | `EXECUTION_BINDING` | Explicit agent ID + request → result | Stores agent handles; bounded invocation | Canonical service supplies RRM-selected explicit ID | Direct capability selection is a deprecation candidate |
| Core App CapabilityRouter | `EXECUTION_BINDING` | Explicit capability + Mission → Core App result | Capability-to-app handle mapping | Canonical service supplies RRM-selected explicit capability | Domain default remains traced compatibility; retire after parity |
| ModuleRouter | `COMPATIBILITY_ONLY` | Legacy domain/trigger → module | Legacy routing only | Cannot override terminal cognition or canonical RRM decisions | Deprecation candidate after unmigrated-domain parity |
| COR RegistryCatalog defaults | `COMPATIBILITY_ONLY` | Legacy COR registrations → diagnostic execution graph | Legacy planning catalog, not runtime availability | ProductBridge no longer uses defaults; receives RRMToCORAdapter | Retire defaults after all COR callers inject RRM projection |
| RRMToCORAdapter | `DERIVED` | RRM eligible resources → COR registrations | Projection only | Canonical ProductBridge ECC shares the application RRM | Retain while COR contract remains legacy-shaped |
| ToolRegistry / Tool CapabilityRouter | `DEPRECATION_CANDIDATE` | Tool descriptors/health/permissions → candidates | Separate historical tool catalog; not composed into ProductBridge runtime | Must be projected into RRM before future activation | Migrate before any runtime activation |
| ToolAuthorizationGate | `AUTHORIZATION_ONLY` | Selected tool + policy/project context → authorization decision | Owns authorization, not availability | Always downstream of canonical resolution | Retain |
| MissionRuntime | `EXECUTION_BINDING` | Authorized Mission action + RRM → controlled runtime | Runtime entry and action execution boundary | Revalidates resources; only ALLOW can enter | Retain |
| Legacy capability/provider/agent adapters | `COMPATIBILITY_ONLY` | Legacy contracts → canonical-shaped calls/results | No canonical availability or lifecycle truth | Canonical paths wrap them with RRM and gates; actual use emits trace | Retire individually after parity evidence |
| ProductBridge | `TRANSPORT_ONLY` | Request → canonical services → product response | Transport/session and explicit compatibility correlation | Provider/resource diagnostics come from RRM and observed execution | Retain; continue thinning compatibility |
| Gateway / FastAPI / Desktop / UI | `TRANSPORT_ONLY` | Product contract → client | No resource authority | Preserve canonical fields only | Retain |

## Dispatch-time revalidation

`CanonicalResourceBindingAuthority.revalidate()` now proves all of the following
immediately before dispatch:

- the original decision was executable;
- the exact binding is still registered;
- RRM still reports that binding eligible;
- the binding health check still passes.

Failure at any stage returns `CAPABILITY_UNAVAILABLE` without entering the
executor. Safe diagnostics expose only capability and binding identifiers plus
the booleans `registered`, `rrm_eligible`, `binding_healthy`, `selected`, and
revalidation reason.

## Compatibility containment

- `ModuleRouter`, Core App Domain defaults, direct ProviderManager defaults,
  direct Kernel/PipelineDAG, and legacy adapters remain explicit compatibility.
- A considered but rejected fallback emits no participation trace.
- Actual compatibility execution emits its trace at the execution boundary.
- ProductBridge ECC/COR now consumes the canonical RRM projection instead of a
  populated legacy default catalog.
- Standalone `RRMToCORAdapter` fails closed with an empty RRM when none is
  injected; it no longer manufactures default resource truth.

## Deprecation candidates and prerequisites

| Candidate | Retirement prerequisite |
| --- | --- |
| `CanonicalCapabilityRegistry.select()` | Every caller consumes `CanonicalResourceBindingAuthority.resolve()` |
| Core App Domain defaults | Every domain supplies explicit capability requirements with parity coverage |
| `ModuleRouter` and PipelineDAG fallback | Canonical content runtime covers all retained legacy responses |
| ProviderManager direct default | Every caller supplies canonical provider selection |
| COR `RegistryCatalog(populate_defaults=True)` | Every product/runtime composition injects RRM projection |
| ToolRegistry/Tool CapabilityRouter | Tool bindings and health are projected into RRM and authorization parity is proven |
| Legacy provider/capability/agent adapters | Native binding parity, rollback, and telemetry show no remaining callers |

No runtime-reachable `DUPLICATE_AUTHORITY` remains capable of overriding RRM
on the canonical product or Mission execution paths.
