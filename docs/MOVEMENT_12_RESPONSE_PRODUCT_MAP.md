# Movement 12 — Response-to-Product Authority Map

## Audited snapshot

- Source branch: `architecture/runtime-authority-convergence`
- Source HEAD: `b5b856d01d571131d8a3e3c373021ceffc29b5d1`
- Verified runtime baseline: `31e44bd6c8c7dac38e813b952e478f2d66eef130`
- Movement 11: `MOVEMENT_11_VERIFIED`

This map records the response path before Movement 12 implementation. It
distinguishes semantic truth, transport, presentation, diagnostics, and retained
compatibility behavior.

## Observed product paths

| Entry point | Runtime source | Transport | Visible consumer | Pre-Movement 12 authority finding |
| --- | --- | --- | --- | --- |
| Node `/api/intent` | `ProductBridge` → `CanonicalTurnResult` → `CognitiveResponseAssembler` | `IntentGatewayAdapter`/JSON lines | Desktop static chat | Runtime semantics are canonical, but the UI treats `ok` as success and hides canonical status distinctions. |
| `IntentOSDesktop.process_intent` | Direct `Kernel.process` | Python dictionary | CLI/desktop caller | Bypasses `CognitiveResponse` and exposes legacy mode/domain semantics. |
| FastAPI `/api/v1/process` | Direct `Kernel.process` | Pydantic `ProcessResponse` | API client | Bypasses `CognitiveResponse`; request `mode` can override runtime mode. |
| Gateway unavailable/error | Gateway/HTTP exception | Ad-hoc dictionaries | UI/API client | Several shapes collapse transport failure into `mode=unavailable` or a generic `error`. |

## Field authority map

| Semantic field | Runtime source of truth | Current transport | Current presentation | Duplicate interpretation risk |
| --- | --- | --- | --- | --- |
| `status` | `CognitiveResponseAssembler` | Preserved by ProductBridge, untyped in TypeScript | Ignored by chat UI | High: UI uses `ok` instead. |
| `execution_mode` | `CognitiveResponseAssembler` | Preserved | Not displayed | Medium: legacy desktop/API expose a different `mode`. |
| `epistemic_status` | `CognitiveResponseAssembler` | Preserved | Not displayed | Medium: UI cannot distinguish known/unknown conclusions. |
| `confidence` | `CognitiveResponseAssembler` | Preserved | Legacy UI may display IUE confidence instead | Medium: cognitive confidence and intent-quality scores can be confused. |
| `text` | Canonical runtime result, governed by `response.output` | Preserved | Rendered with unescaped `innerHTML` | High: canonical text is shown without semantic state and unsafe HTML handling. |
| `provider` | `ProviderInvocationEvidence`/assembler | Preserved | Chat UI does not distinguish selected from invoked | Medium. |
| `provider_called` | Actual ProviderManager invocation evidence | Preserved | Ignored | High if future UI displays configured providers as executed. |
| `resource_provenance` | Canonical invocation evidence | Preserved | Ignored | Medium. |
| `mission_id` | `MissionEngine` identity admitted by ProductBridge governance | Preserved | Ignored | Medium: legacy desktop/API do not use this contract. |
| Mission state | `MissionEngine`/`MissionRuntime` metadata | Extra JSON metadata | Ignored | Medium. |
| Authorization state | Typed canonical result and gate metadata | Preserved | Collapsed into generic success/error branch | High. |
| `missing_capabilities` | Capability composition/assembler | Preserved | Ignored | High: UNKNOWN/resource-required explanations are hidden. |
| `limitations` | Canonical result/Constitution | Preserved | Usually text only | Medium. |
| Compatibility participation | Boundary-originated `CompatibilityTrace` | Preserved | Not shown to normal users | Low for users, medium for diagnostics if inferred later. |
| `ok`/error | `CognitiveResponse.to_dict` protocol outcome | Preserved | Used as semantic success | High: `UNKNOWN` and `BLOCKED` are processed responses, not successful answers. |

## Pre-implementation authority conclusions

1. `CognitiveResponseAssembler` is the semantic authority for the ProductBridge
   path, but there is no typed product contract at the TypeScript boundary.
2. The static chat is a duplicate interpretation point because it decides that
   `ok && text` is a successful answer and otherwise renders a generic error.
3. The Python desktop and FastAPI process endpoints remain legacy product paths
   that bypass the verified cognitive response envelope.
4. Gateway failures use ad-hoc response shapes instead of one explicit transport
   failure contract.
5. Provider, Mission, authorization, missing-capability and epistemic distinctions
   reach transport but do not govern visible behavior.

## Target ownership

| Layer | Target role |
| --- | --- |
| Canonical runtime services | Produce typed execution, resource, memory, Mission and provider evidence. |
| `CognitiveResponseAssembler` | Sole semantic response authority. |
| Cognitive product presenter | Derive a typed, non-authoritative visible-state projection from `CognitiveResponse`. |
| ProductBridge | Transport governed typed results and non-semantic diagnostics. |
| Gateway adapter | Validate/preserve the product contract; create only evidence-based transport failures. |
| HTTP/IPC | Byte transport only. |
| Frontend | Escape and display canonical text/state; enable controls only from canonical presentation flags. |
| Compatibility | Remain explicit, traced and subordinate; never inferred by presentation. |

The machine-readable companion is
[`movement_12_response_product_map.json`](movement_12_response_product_map.json).
