# Intent OS — Cognitive Convergence Movements 5, 6A and 7A

## Source and boundary

- Repository: `cics1b252-glitch/IntentOS`
- Base branch: `architecture/capability-first-convergence`
- Starting SHA: `d12adb62b177761d92ddecf39d770222b156f1cc`
- Working branch: `architecture/capability-resolution-runtime`

This cycle connects capability analysis to the real ProductBridge and Kernel
input paths. It does not authorize or execute dynamically composed resources.
Legacy modules remain compatibility executors.

## RRM authority and compatibility projections

RRM is now constructed by `ApplicationFactory` with no default/demo catalog.
`RuntimeResourceProjection` projects the capabilities, agents and Providers that
the executable composition actually contains. The projection records executor
kind and ID while RRM owns resource availability truth.

`CanonicalCapabilityRegistry` remains temporarily as an execution-binding
registry because it holds live Python executor objects. COR RegistryCatalog
remains an ECC compatibility catalog. New capability-first code reads only RRM.

Mock is projected as demonstration-only and ineligible. It cannot satisfy an
external-resource requirement.

## Capability runtime integration

`CognitiveCapabilityRuntime` receives user input, IUE interpretation, AME
context, project context, persistent constraints and authorized permissions.
It performs:

1. capability requirement discovery;
2. Constitution-governed RRM/tool resolution;
3. declarative composition;
4. explicit Chat/Mission mode decision;
5. no execution.

ProductBridge invokes it immediately after IUE and before local compatibility
branches. Kernel invokes it after IntentEngine parsing when the interface has not
already supplied an analysis. The result is available in runtime context and
ProductBridge diagnostics.

Domain is retained only as `domain_hint`. Existing domain routing remains behind
the characterized compatibility execution path until equivalent capability
execution and response assembly exist.

## Chat versus Mission

Canonical modes:

- `LOCAL_RESPONSE`: deterministic system guidance;
- `CONVERSATION`: no supervised external effect required;
- `MISSION`: an available external/persistent action requires planning and gates;
- `EXTERNAL_REASONING_REQUIRED`: no eligible reasoning Provider;
- `AUTHORIZATION_REQUIRED`: resource exists but permission is absent;
- `BLOCKED`: Constitution denied resolution;
- `UNKNOWN`: action capability is missing or state cannot be proven.

The mode decision does not execute. A future Mission handoff must still pass CPE,
Mission Engine, MissionRuntime, Tool Authorization, Action Gate and Verification.

## ProductBridge thinning map

| ProductBridge behavior | Canonical owner | Status |
|---|---|---|
| Financial field filling | IUE + CDM | Characterized legacy |
| Application/product field filling | IUE + CDM | Characterized legacy |
| Memory candidate ingestion | AME | Already delegated, bridge triggers |
| Memory retrieval | AME + response assembler | Already delegated, formatting legacy |
| Zero-provider handling | BCC + capability runtime | Partially converged |
| Session persistence | Gateway/session repository | Legacy bridge ownership |
| Provider fallback | ProviderManager | Already delegated |
| Mission dispatch | Mission Engine/Runtime | Kernel route partial; bridge still coordinates errors |
| Capability assessment | Capability runtime | Converged before legacy branches |
| Response formatting | CognitiveResponseAssembler | Not implemented |

No working branch was removed. Thinning requires parity tests before each transfer.

## Capability truth states

Resolution uses only:

- `CAPABILITY_AVAILABLE`;
- `CAPABILITY_PARTIAL`;
- `CAPABILITY_MISSING`;
- `AUTHORIZATION_REQUIRED`;
- `EXTERNAL_RESOURCE_REQUIRED`;
- `BLOCKED_BY_POLICY`;
- `UNKNOWN`.

A missing capability does not create a fake Provider or Tool. Partial composition
lists missing requirements. Mock is not eligible as external reasoning.

## Constitution gate

`CapabilityFirstResolver.resolve` calls the canonical ConstitutionEngine before
resource lookup. A denial returns `BLOCKED_BY_POLICY` with no candidates. Existing
capability execution, knowledge ingest and Kernel input gates remain unchanged.

Future work must enrich the gate payload with normalized privacy, environment and
composition restrictions. No constitutional rule changed in this cycle.

## AgentBlueprint foundation

`AgentBlueprint` describes a possible future bounded executor. It is not an
Agent instance. It includes mission scope, required/optional capabilities,
tools/resources, memory/instruction scope, environment, privacy, cost, latency,
verification, retention, provenance and lifecycle.

Lifecycle is represented without transitions or execution:

`PROPOSED → VALIDATED → AUTHORIZED → INSTANTIATED → ACTIVE → DEGRADED →
RETIRED/DISCARDED`

Default retention is `discard_after_mission`. No blueprint is automatically
instantiated or persisted.

## Agent resolution

`AgentBlueprintResolver` searches eligible RRM agents first and ranks by:

- capability coverage;
- availability;
- historical reliability;
- cost;
- latency;
- privacy constraints;
- environment requirements;
- project allow-list.

Only complete coverage selects an existing agent. Otherwise it proposes a
blueprint and reports missing capabilities. No domain-to-agent mapping exists.

## Permissioned discovery boundary

`SystemResourceDiscoveryPort` is a declarative Protocol with:

- `discover_candidates(context)`;
- `describe_capabilities(resource_id)`;
- `describe_permissions(resource_id)`;
- `describe_health(resource_id)`.

`DiscoveredResourceCandidate` represents application, OS capability, filesystem,
browser, database, API, AI Provider, local model, connected service, device, tool
or custom resource. No real host scanner was added.

Truth states are distinct:

`DISCOVERED`, `CONFIGURED`, `AUTHORIZED`, `AVAILABLE`, `DEGRADED`,
`UNAVAILABLE`, `BLOCKED`.

A candidate is executable only when it is AVAILABLE, requires no further
authorization and its permission state is explicitly granted.

## Novel-domain integration evidence

### Small workshop

Input produces capabilities including:

- `service_order.management`;
- `inventory.parts`;
- `customer.records`;
- `maintenance.history` where stated.

No OficinaModule is used.

### Invoice processing

Input produces:

- `document.read`;
- `document.extract_structured_data`;
- `data.normalize`;
- `report.aggregate`;
- `report.explain`.

No AccountingModule is used.

### Installed application control

Input produces `application.launch` and `application.control`. With no authorized
resource, the decision is `UNKNOWN`, composition is non-executable and nothing is
launched.

## Safe debt fixes

### pytest shadowing

Confirmed. Repository-level `pytest.py` intercepted `python -m pytest` and
returned without collecting tests. The obsolete shim was removed. The normal
command now invokes the installed pytest package and collects the full suite.

### WAITING_CONTEXT JavaScript contract

Confirmed as a test-contract defect. ECC canonically returns no execution plan
while waiting for required context. Gateway tests now assert `null` in
`WAITING_CONTEXT` and require a plan only in planning states.

### EventBus async isolation

Confirmed. One throwing subscriber prevented later subscribers from receiving the
event. EventBus now isolates handler exceptions, continues delivery and stores a
redacted failure record containing event type, handler name and exception class.

### Permission revoke scope

Confirmed. Revocation always wrote PROJECT scope. It now preserves the original
grant scope unless an explicit replacement scope is supplied.

## Deferred boundaries

- no real OS/application discovery or control;
- no AgentFactory execution;
- no generated-agent persistence;
- no legacy deletion;
- no response assembler;
- no merge to main.

## Readiness

- Movement 6B, governed AgentFactory runtime: `READY_WITH_PREREQUISITES`.
  Requires blueprint validation/authorization gates and an instance repository.
- Movement 7B, read-only discovery adapters: `READY_WITH_PREREQUISITES`.
  Requires per-adapter privacy policy, opt-in and RRM candidate ingestion.
- Movement 8, CognitiveResponseAssembler: `READY_WITH_PREREQUISITES`.
  Requires canonical Chat/Mission result contracts and output Constitution gate.
- Movement 9, verified learning: `BLOCKED` until Mission verification and approved
  reusable-composition evidence are canonical.
- Movement 10, legacy retirement: `BLOCKED` until ProductBridge thinning,
  capability execution parity and reachability telemetry are complete.

