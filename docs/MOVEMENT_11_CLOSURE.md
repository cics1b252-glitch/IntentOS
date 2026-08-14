# Movement 11 Closure — Runtime Authority Convergence

## Movement identity

| Field | Canonical value |
| --- | --- |
| Movement | Movement 11 |
| Name | Runtime Authority Convergence |
| Canonical branch | `architecture/runtime-authority-convergence` |
| Base SHA | `245c40b5ac640f7b38066f5586a8ad0da7756eef` |
| Final verified SHA | `31e44bd6c8c7dac38e813b952e478f2d66eef130` |
| Final audit verdict | `MOVEMENT_11_VERIFIED` |

## Final authority model

| Authority | Canonical responsibility |
| --- | --- |
| `CognitiveConversationService` | Turn boundaries, typed dialogue continuation, interruption, resumption and cognitive execution decision. |
| `CapabilityRequirementDiscovery` | Discovery of capability requirements from governed cognitive input. |
| `CapabilityFirstResolver` | Capability resolution and composition. |
| RRM | Resource availability and eligibility truth. |
| `CanonicalResourceBindingAuthority` | Execution-binding selection constrained by RRM and dispatch-time revalidation. |
| `CanonicalProviderAuthority` | Eligible provider selection over RRM truth. |
| `CanonicalMemoryService` | Governed product-facing current durable memory truth over AME/KOM. |
| `MissionEngine` | Mission identity and lifecycle state. |
| `MissionRuntime` | Controlled Mission execution after resource and authorization decisions. |
| `ToolAuthorizationGate` | Tool and resource authorization. |
| `ActionGate` | Per-action safety and confirmation. |
| `VerificationGate` | Execution-result verification evidence. |
| `MissionCompletionGate` | Sole canonical Mission completion decision. |
| `CognitiveResponseAssembler` | Final user-visible semantic envelope and `response.output` governance. |
| Compatibility | Explicit, observable, evidence-based, subordinate adapters. Compatibility cannot redefine canonical decisions, resource truth, memory truth, Mission completion or response semantics. |

## Verified critical invariants

- `UNKNOWN` is terminal.
- `BLOCKED` is terminal.
- Pending dialogue continues only through typed semantic matching; unrelated and ambiguous input fails closed without silent context mutation.
- `XZ-91` is never interpreted as `R$ 91`.
- Iceland population in 2025 never routes to finance or becomes `R$ 2.025`.
- Durable project memory remains isolated across projects and runtime restarts.
- Each scoped durable fact or preference has one current truth; corrections supersede prior values while preserving history.
- RRM eligibility is authoritative over registered, configured or healthy bindings.
- Provider selection, configuration and eligibility do not constitute provider invocation.
- Only `ToolAuthorizationGate=ALLOW` may reach `MissionRuntime`.
- A Mission cannot complete without execution evidence, verification evidence and a canonical `MissionCompletionGate` decision.
- Compatibility participation is recorded only from actual execution boundaries and remains subordinate.
- Every final product response is assembled by `CognitiveResponseAssembler` and governed by `response.output`.

## Final validation baseline

| Validation | Result |
| --- | --- |
| Python | 1043 passed, 0 failed, 0 skipped |
| JavaScript | 7 passed, 0 failed |
| TypeScript | Passed (`tsc --noEmit`) |
| Coverage | 82% |

## Movement 11 commit chain

1. `3b2aa479224aa349d136ce24a8c1b9de021a0e2f` — `docs: map runtime authority convergence`
2. `332fd48e92a6ffc0fb5dd5fcbcd8d8ede620f445` — `refactor: establish canonical conversation authority`
3. `023a2aafbf8256044f6052ca9e55a518a9995dbe` — `refactor: consolidate mission lifecycle authority`
4. `78704d9d49011c72d670306cac0afcc9cf17d2fa` — `refactor: consolidate canonical resource authority`
5. `382029c88b871cb84dcaf2c5becc3e3d9b24f8cd` — `refactor: converge canonical memory authority`
6. `89d39f93f739a62c8df50b81584a98963e6d6507` — `refactor: converge response and provider authority`
7. `e8ab6f603388e2c6ebb508b5c4c569aff0d3f166` — `refactor: contain compatibility authority`
8. `bd7bc63a7b8a4015fcbd757485354d17b5e63793` — `fix: complete runtime authority convergence`
9. `31e44bd6c8c7dac38e813b952e478f2d66eef130` — `fix: preserve truthful provider invocation evidence`

## Known limitations

- Subordinate compatibility paths remain for Kernel/PipelineDAG, ProductBridge field filling, ModuleRouter, CapabilityRouter and legacy adapters; they are explicit, traced deprecation candidates.
- `CognitiveResponseAssembler` retains a compatibility-only dictionary adapter for non-ProductBridge legacy callers; the canonical product path uses typed `CanonicalTurnResult` evidence.
- Productive external executors remain disabled.
- Mission confirmation/resume and productive verified execution remain future work.
- Registry retirement remains incomplete even though RRM owns runtime eligibility truth.
- No separate Constitution `verification` action exists; `VerificationGate` remains the effective verification-evidence authority.

## Readiness summary

| Movement | Readiness |
| --- | --- |
| Movement 12 — Full CognitiveResponse/UI convergence | `READY` |
| Movement 13 — Binding/registry convergence completion | `READY_WITH_PREREQUISITES` |
| Movement 14 — Mission confirmation/resume runtime | `READY` |
| Movement 15 — Governed AgentFactory | `READY_WITH_PREREQUISITES` |
| Movement 16 — Real read-only resource discovery | `READY_WITH_PREREQUISITES` |
| Movement 17 — Verified Cognitive Learning | `BLOCKED` |
| Movement 18 — Legacy retirement | `BLOCKED` |

## Closure statement

Movement 11 — Runtime Authority Convergence is closed with final verdict
`MOVEMENT_11_VERIFIED`.

Future work must treat commit
`31e44bd6c8c7dac38e813b952e478f2d66eef130` as the verified
runtime-authority baseline unless it is superseded by a later audited merge.
