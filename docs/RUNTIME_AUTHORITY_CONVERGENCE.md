# Runtime Authority Convergence — Movements 5B, 5C, 5D, 6B and 8

## Authority rule

`CognitiveExecutionDecision` is the product routing authority. Terminal modes
(`UNKNOWN`, `BLOCKED`, `EXTERNAL_REASONING_REQUIRED` and
`AUTHORIZATION_REQUIRED`) cannot fall through to domain or regex execution.
Legacy behavior is reachable only as an explicit compatibility continuation or
an explicitly requested compatibility fallback.

Domain remains metadata and policy context. It is not converted to a capability
destination in `Kernel._execute_canonical_route`. Mission execution accepts only
a capability selected by the cognitive composition.

## ProductBridge thinning ledger

| Current responsibility | Owner today | Canonical owner | Migration status | Parity test |
|---|---|---|---|---|
| Financial parsing | ProductBridge compatibility | Capability discovery + finance binding | Explicit compatibility | financial continuity tests |
| Application parsing | ProductBridge compatibility | capability discovery | Explicit compatibility | application characterization tests |
| Field filling | ProductBridge compatibility | dialogue service | Explicit continuation only | conversational continuity tests |
| Memory ingestion | ProductBridge AME adapter | AME/KOM | Governed adapter | project/preference restart tests |
| Memory retrieval | ProductBridge AME adapter | AME/KOM | Governed adapter | project isolation tests |
| BCC routing | ProductBridge | local response service | Decision-authoritative | local BCC no-Mission test |
| Zero-provider routing | cognitive runtime | cognitive runtime | Converged | lookup/novel-domain tests |
| Mission IDs | ProductBridge compatibility | MissionEngine | Mission path converged; dialogue debt remains | MissionRuntime test |
| Session persistence | ProductBridge | Session Store | Transient-only contract documented | continuity tests |
| Provider fallback | ProductBridge compatibility | ProviderManager | Explicit compatibility only | provider tests |
| Response formatting | ProductBridge compatibility | CognitiveResponseAssembler | Canonical envelope active | response contract tests |
| Route selection | ProductBridge | CognitiveExecutionDecision | Converged for terminal/Mission modes | real-path authority tests |

## Memory ownership contract

- AME/KOM is the persistent cognitive-memory authority.
- PKB/Knowledge Pipeline is the governed knowledge-curation layer and remains a
  separate integration boundary during this foundation.
- Session Store contains transient dialogue/runtime state only.
- `known_context` is not durable knowledge authority and must not be promoted
  outside AME/PKB curation.

## Resource authority contract

RRM answers what exists, is available and is eligible. Execution registries keep
temporary callable bindings only. ProviderManager, ToolRegistry and
CanonicalCapabilityRegistry must not independently promote an unavailable RRM
resource into an eligible one.

## Mission foundation

MissionEngine owns lifecycle records. MissionRuntime owns controlled action
execution. The real ProductBridge path reaches ToolAuthorizationGate and
MissionRuntime for authorized Mission-class requests. This movement deliberately
stops at user confirmation and uses only an in-memory synthetic action; it enables
no real external or destructive action.

## Response foundation

`CognitiveResponse` normalizes text, status, execution mode, epistemic status,
confidence, provenance, Mission ID, verification evidence, limitations, missing
capabilities, authorization requirements and next actions. Every ProductBridge
chat response passes the canonical output Constitution gate before serialization.
