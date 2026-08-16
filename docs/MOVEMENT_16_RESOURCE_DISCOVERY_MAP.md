# MOVEMENT 16 — RESOURCE DISCOVERY AUTHORITY MAP

> Governed Resource Discovery Convergence

## CORE PRINCIPLE

```
DISCOVERY IS EVIDENCE.
DISCOVERY IS NOT AUTHORITY.
```

---

## PRIMARY INVARIANT

```
DISCOVERED
  != REGISTERED
  != AVAILABLE
  != ELIGIBLE
  != SELECTED
  != AUTHORIZED
  != BOUND
  != ATTEMPTED
  != USED
  != VERIFIED
```

No discovery result may skip any canonical authority boundary established in
Movements 11–15.

---

## COMPONENT AUTHORITY MATRIX

| Component | Classification | Responsibility |
|---|---|---|
| `CanonicalResourceDiscoveryService` | **DISCOVERY_ONLY** | Accepts adapters, orchestrates observations, normalizes evidence, deduplicates, produces deterministic snapshots, exposes discovery truth for inspection. Never executes, invokes, authorizes, binds, or mutates RRM. |
| `DiscoveryRegistry` | **DISCOVERY_REGISTRY_ONLY** | Stores discovery evidence only. Presence means "observed" — not "available", "eligible", "authorized", "bound", or "trusted". |
| `ResourceDiscoveryEvidence` | **DERIVED** | Immutable typed evidence record of a single observation. Contains provenance, confidence, health, credential metadata. Never mutates runtime state. |
| `ResourceDiscoverySnapshot` | **DERIVED** | Deterministic read-only snapshot of all discovery evidence with optional derived RRM cross-reference. |
| `ResourceDiscoveryCorrelation` | **DERIVED** | Derived read-only cross-reference between discovery evidence and RRM truth. Never written to or mutated by discovery. |
| `ResourceDiscoveryAdapter` | **READ_ONLY** | Narrow protocol for pluggable observation sources. Returns evidence only. |
| `ResourceDiscoveryStatus` | **DERIVED** | Discovery-specific states (OBSERVED, STALE, REVOKED, UNAVAILABLE_AT_SOURCE, UNKNOWN, INVALID). Distinct from RRM lifecycle statuses. |
| `ResourceDiscoveryKind` | **DERIVED** | Observed resource category (PROVIDER, TOOL, CAPABILITY, ENVIRONMENT, AGENT, LOCAL_PROGRAM, MCP_RESOURCE, CONNECTED_SERVICE, DEVICE, CUSTOM). |
| `ResourceRegistrationProposal` | **PROPOSAL_ONLY** | Non-productive typed proposal for future registration. Never registers anything. Never mutates RRM. |
| `RegistryResourceManager` (RRM) | **CANONICAL_AUTHORITY** (unchanged) | Sole runtime availability/eligibility authority. Discovery never modifies RRM. |
| `CanonicalResourceBindingAuthority` | **EXECUTION_BINDING** (unchanged) | Sole runtime binding gatekeeper. Discovery never produces bindings. |
| `CanonicalCapabilityRegistry` | **EXECUTION_BINDING** (unchanged) | Runtime execution binding registry. Discovery never writes to it. |
| `CapabilityExecutionService` | **EXECUTION_BINDING** (unchanged) | Mission-authorized execution dispatch. Discovery never triggers execution. |
| `MissionEngine` | **CANONICAL_AUTHORITY** (unchanged) | Sole Mission identity/lifecycle authority. Discovery never creates or mutates Missions. |
| `ToolAuthorizationGate` | **AUTHORIZATION_ONLY** (unchanged) | Tool authorization decisions. Discovery never grants authorization. |
| `ActionGate` | **EXECUTION_BINDING** (unchanged) | Action safety and confirmation requirement. Discovery never bypasses it. |
| `CanonicalConfirmationService` | **CANONICAL_AUTHORITY** (unchanged) | Typed confirmation. Discovery never produces confirmation. |
| `VerificationGate` | **EXECUTION_BINDING** (unchanged) | Post-execution verification. Discovery never verifies. |
| `MissionCompletionGate` | **CANONICAL_AUTHORITY** (unchanged) | Sole Mission completion authority. Discovery never completes. |
| `CanonicalProviderAuthority` | **CANONICAL_AUTHORITY** (unchanged) | Provider selection/invocation. Discovery never invokes providers. |
| `CanonicalMemoryService` | **CANONICAL_AUTHORITY** (unchanged) | Memory scoping. Discovery evidence is not automatically durable memory. |
| `CanonicalAgentFactory` | **FACTORY_ONLY** (unchanged) | Agent creation. Discovery never creates agents. |
| `CanonicalAgentRegistry` | **REGISTRY_ONLY** (unchanged) | Agent registry. Discovery never registers agents. |
| `GovernedAgent` | **EXECUTION_PARTICIPANT** (unchanged) | Passive identity/lifecycle. Agents may consume discovery as read-only context; they cannot promote it. |
| `ProductBridge` | **PRODUCT_CONTRACT_LAYER** (unchanged) | Transport/presentation. Discovery diagnostics are read-only if exposed. |
| `Legacy Components` | **COMPATIBILITY_ONLY** (unchanged) | Legacy discovery/catalog may coexist temporarily. They must not override canonical RRM or binding authorities. |
| `SymbioticLayer` | **READ_ONLY** (unchanged) | Host environment observation. May be an adapter source. |

---

## AUTHORITY RULES

| # | Rule |
|---|---|
| 1 | Discovery is read-only evidence, not runtime authority. |
| 2 | Discovery does not create runtime availability. |
| 3 | Discovery does not create runtime eligibility. |
| 4 | Discovery does not create authorization. |
| 5 | Discovery does not create executable binding. |
| 6 | Discovery does not invoke provider/tool/resource. |
| 7 | RRM remains sole runtime availability/eligibility authority. |
| 8 | Existing canonical execution path remains mandatory. |
| 9 | Agent cannot promote discovery into authority. |
| 10 | Compatibility cannot promote discovery into authority. |
| 11 | Discovery identity/source provenance is preserved. |
| 12 | Stale/replaced observations cannot silently substitute identity. |
| 13 | Discovery metadata cannot inject authority. |
| 14 | Zero-provider truth remains intact. |
| 15 | RA-13-01 remains fixed. |
| 16 | M14 confirmation/resume authority remains intact. |
| 17 | M15 Agent authority containment remains intact. |
| 18 | M11–M15 regressions pass. |
| 19 | No productive external execution is introduced. |
| 20 | Full available regression suite passes. |

---

## OBLIGATIONS

| # | Obligation |
|---|---|
| 1 | Every discovery adapter must return typed `ResourceDiscoveryEvidence`. |
| 2 | Every evidence record must preserve `source`, `source_type`, `observed_at`, `observed_by`. |
| 3 | Confidence values must be clamped to [0.0, 1.0]. |
| 4 | Discovery status must not reuse RRM lifecycle statuses. |
| 5 | Snapshots must be deterministic given the same registry state. |
| 6 | RRM cross-reference must be derived, never written. |
| 7 | Revocation must fail closed (missing ID → return False). |
| 8 | Staleness must fail closed (missing ID → return False). |
| 9 | Discovery must not write to project/user memory. |
| 10 | Discovery evidence must be treated as untrusted input. |
| 11 | Adapter errors must not propagate as execution failures. |
| 12 | Proposal must not mutate any runtime state. |

---

## DISCOVERY FLOW

```
External / Local Environment
        ↓
ResourceDiscoveryAdapter  (READ_ONLY)
        ↓
CanonicalResourceDiscoveryService  (DISCOVERY_ONLY)
        ↓
normalize + deduplicate + preserve provenance
        ↓
DiscoveryRegistry  (DISCOVERY_REGISTRY_ONLY)
        ↓
ResourceDiscoveryEvidence  (DERIVED — stored)
        ↓
ResourceDiscoverySnapshot  (DERIVED — read-only view)
        ↓
ResourceDiscoveryCorrelation  (DERIVED — RRM cross-reference)
        ↓
        ╳  BOUNDARY: Discovery ends here
        ↓
EXPLICIT canonical registration/projection path  (NOT part of M16)
        ↓
RRM  (CANONICAL_AUTHORITY)
        ↓
availability / eligibility
        ↓
CanonicalResourceBindingAuthority  (EXECUTION_BINDING)
        ↓
exact execution binding
        ↓
execution
```

---

## DISCOVERY STATUS SEMANTICS

| Status | Meaning | Runtime Implication |
|---|---|---|
| OBSERVED | Fresh observation, evidence valid | None — read-only |
| STALE | Evidence not refreshed, may be outdated | None — read-only |
| REVOKED | Source explicitly revoked this observation | None — read-only |
| UNAVAILABLE_AT_SOURCE | Source reported the resource as unavailable | None — read-only |
| UNKNOWN | Could not determine observation validity | None — read-only |
| INVALID | Malformed or rejected evidence | None — read-only |

All statuses produce the same runtime result: **no execution, no authority, no binding.**

---

## RRM CROSS-REFERENCE

The snapshot may include derived `ResourceDiscoveryCorrelation` entries that
show whether a discovered resource also appears in RRM. This is READ-ONLY
observational data:

| Correlation Status | Meaning |
|---|---|
| no_match | Resource not found in RRM |
| partial_match | Resource found in RRM but not eligible |
| exact_match | Resource found in RRM and eligible |
| no_rrm | No RRM instance configured |

**Critical:** `exact_match` correlation does NOT mean the resource is
authorized or bound. It means the resource exists in both truth domains.
Execution still requires the full canonical path through
`CanonicalResourceBindingAuthority`.
