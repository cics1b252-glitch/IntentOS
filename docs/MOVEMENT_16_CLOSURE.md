# MOVEMENT 16 — FORMAL CLOSURE

> Governed Resource Discovery Convergence

## MOVEMENT

**16** — Governed Resource Discovery Convergence

## STATUS

**MOVEMENT_16_VERIFIED**

## VERIFIED HEAD

`a09049e0cb8a4b5321c3c442a07e9a25a0cbec12`

## MOVEMENT 15 CLOSURE BASE

`933fa056c0eeefae20c176e6245c1967767681d2`

## COMMIT

```
a09049e0cb8a4b5321c3c442a07e9a25a0cbec12
feat: add governed resource discovery
```

---

## CORE PRINCIPLE

```
DISCOVERY IS EVIDENCE.
DISCOVERY IS NOT AUTHORITY.
```

---

## FINAL DISCOVERY AUTHORITY MODEL

| Component | Classification | Responsibility |
|---|---|---|
| `CanonicalResourceDiscoveryService` | **DISCOVERY_ONLY** | Observes resources via adapters; stores evidence; cross-references with RRM (read-only); fail-closed error handling. No execute, invoke, authorize, bind, register, promote, or mutate API. |
| `DiscoveryRegistry` | **DISCOVERY_REGISTRY_ONLY** | Stores evidence (frozen dataclasses) in a dict; dedup on kind+resource_id+source; fail-closed revoke/stale. No external mutation API beyond add/get/revoke/mark_stale/list_*. |
| `ResourceDiscoveryEvidence` | **FROZEN_EVIDENCE** | Immutable dataclass; status is observed (OBSERVED/STALE/REVOKED only). Has no `available`, `eligible`, `authorized`, `verified`, `registered` attribute. |
| `ResourceDiscoveryAdapter` | **PROTOCOL** | Defines adapter interface: `adapter_id`, `adapter_type`, `discover()`. Adapters are evidence sources only. |
| `ResourceDiscoveryCorrelation` | **FROZEN_CORRELATION** | Derived read-only cross-reference between discovery evidence and RRM state. `rrm_registered`, `rrm_available`, `rrm_eligible` are derived booleans, never injected by discovery. |
| `ResourceDiscoverySnapshot` | **FROZEN_SNAPSHOT** | Immutable point-in-time view of discoveries + cross-references. No mutation API. |
| `ResourceRegistrationProposal` | **PROPOSAL_ONLY** | Frozen proposal for registering a discovered resource. `accept()`/`reject()` return new instances; never commits to RRM, registry, or any authority. No execute/register/promote/commit API. |
| `ResourceDiscoveryStatus` | **ENUM** | 6 states: `OBSERVED`, `STALE`, `REVOKED`, `UNKNOWN`, `DEGRADED`, `UNHEALTHY`. |
| `ResourceDiscoveryKind` | **ENUM** | 10 kinds: `CAPABILITY`, `TOOL`, `PROVIDER`, `AGENT`, `ENVIRONMENT`, `MEMORY`, `KNOWLEDGE`, `EVENT`, `WORKFLOW`, `OTHER`. |
| `ApplicationComponents.resource_discovery_service` | **ADDITIVE_FIELD** | New field (+7 lines in composition.py). Constructed with `rrm=resource_manager`. Wired additively; existing fields/logic untouched. |
| `MissionEngine` | **CANONICAL_AUTHORITY** | Sole Mission identity and lifecycle authority. Unchanged by M16. |
| `MissionCompletionGate` | **CANONICAL_AUTHORITY** | Sole canonical Mission completion authority. Unchanged by M16. |
| `CanonicalConfirmationService` | **CANONICAL_AUTHORITY** | Typed human/owner confirmation. Unchanged by M16. |
| `ToolAuthorizationGate` | **AUTHORIZATION_ONLY** | Tool authorization decisions. Unchanged by M16. |
| `CanonicalResourceBindingAuthority` | **EXECUTION_BINDING** | Exact binding selection/revalidation. Unchanged by M16. |
| `ProductBridge` | **PRODUCT_CONTRACT_LAYER** | Transport and presentation. Unchanged by M16. |
| `ResourceBindingAuthority` (RRM) | **CANONICAL_AUTHORITY** | Resource binding rules. Unchanged by M16. |

No component other than RRM `ResourceBindingAuthority` binds resources.
No component other than `ToolAuthorizationGate` authorizes tools.
Discovery is evidence input to these authorities; it never replaces them.

---

## PRIMARY INVARIANT

```
DISCOVERY IS NOT AUTHORITY.

DISCOVERY != RRM AUTHORITY
DISCOVERY != BINDING AUTHORITY
DISCOVERY != AUTHORIZATION AUTHORITY
DISCOVERY != PROVIDER AUTHORITY
DISCOVERY != TOOL AUTHORITY
DISCOVERY != AGENT PROMOTION AUTHORITY
DISCOVERY != MISSION AUTHORITY
DISCOVERY != PRODUCT-RESPONSE AUTHORITY
DISCOVERY != PRODUCTBRIDGE AUTHORITY
DISCOVERY != MEMORY AUTHORITY
```

And explicitly:

- `DISCOVERY_EVIDENCE` is immutable (frozen dataclass).
- `DISCOVERY_STATUS` is observed only (OBSERVED/STALE/REVOKED).
- `DISCOVERY_CONFIDENCE` never grants authorization or eligibility.
- `DISCOVERY_HEALTH` never sets RRM eligibility.
- `DISCOVERY_METADATA` with `available`/`eligible`/`authorized`/`verified` keys is descriptive only; no attribute exposure.
- `DISCOVERY_SNAPSHOT` is derived read-only; no mutation API.
- `DISCOVERY_CROSS_REFERENCE` is derived from RRM read-only queries; never injected by discovery.
- `PROPOSAL_STATUS` transitions are instance-level; never mutate RRM, registry, or any authority.

---

## NON-PRODUCTIVE CREATION

Under full instrumentation (all productive subsystems patched to raise):

- `observe()` made **zero** productive calls (0 provider, 0 executor, 0 Mission, 0 RRM writes).
- `observe()` left the discovery service in evidence-only state.
- Service module graph contains **no** provider, executor, MissionRuntime, ActionGate,
  VerificationGate, MissionCompletionGate, ConfirmationService, ToolAuthorizationGate,
  or memory write symbols.
- Cross-reference (`_cross_reference()`) performs **read-only** `get_provider()`/`get_capability()`
  queries; never calls `register_*` or any mutation.

---

## IDENTITY RESULTS

- `ResourceDiscoveryEvidence` is frozen; field reassignment raises `FrozenInstanceError`.
- Deduplication on kind+resource_id+source: second observation of same triple returns False.
- `get()` returns the exact original object (object identity).
- Forged discovery_id in snapshot does not alter the underlying registry.
- Service has no `execute`/`invoke`/`authorize`/`bind`/`register_resource`/`create_mission` API.

### TOCTOU

Adapter replacement with different source (adapter A → adapter B):

- Original evidence source preserved (A's records remain).
- New adapter creates new records (B's source).
- No silent substitution.
- **Fails closed.**

---

## RRM CROSS-REFERENCE RESULTS

- Discovered resource absent from RRM: `rrm_registered=False`, `rrm_available=False`, `rrm_eligible=False`, `correlation_status="no_match"`.
- Discovered present in RRM but unavailable: `rrm_registered=True`, `rrm_available=False`, `rrm_eligible=False`, `correlation_status="partial_match"`.
- Discovered present and eligible in RRM but no binding: `rrm_registered=True`, `rrm_eligible=True`, `correlation_status="exact_match"`.
- RRM state change **after** discovery: cross-reference reflects live RRM truth (derived, read-only).
- Discovery revocation/stale **does not** mutate RRM.
- Cross-reference is **derived** — never written by discovery.

---

## ADVERSARIAL RESULTS

| Attack Vector | Result |
|---|---|
| RRM Promotion (metadata `available`/`eligible`/`authorized`/`verified`) | **BLOCKED** — RRM unchanged, no attribute exposure |
| Registry/Binding Injection | **BLOCKED** — no mutation API |
| Provider Discovery → Invocation | **BLOCKED** — zero providers registered |
| Tool Discovery → Authorization | **BLOCKED** — no authorization API |
| Agent Promotion | **BLOCKED** — no promotion API |
| Compatibility Promotion | **BLOCKED** — no override API |
| Source Identity Collision (same resource_id, different sources) | **DISTINCT** — no silent overwrite |
| Resource ID Collision (same ID, different kinds) | **DISTINCT** — cross-kind preserved |
| Stale Evidence Replay | **STALE PRESERVED** — stale status survives new observations |
| Adapter Replacement TOCTOU | **PROVENANCE PRESERVED** — original records untouched |
| Adapter Failure | **FAIL-CLOSED** — error caught, zero evidence stored |
| Confidence 0.0 / 0.5 / 1.0 | **NEVER GRANTS AUTHORITY** — no authorized/eligible attributes |
| Health (healthy/degraded/unhealthy) | **NEVER SETS RRM ELIGIBILITY** — no eligible/available attributes |
| RRM change after discovery | **DISCOVERY TRUTH INDEPENDENT** — cross-reference derives live state |
| Discovery change does not mutate RRM | **PROVEN** — revocation/stale do not touch RRM |
| Proposal non-productive | **PROVEN** — no execute/register/promote/commit API |
| ProductBridge boundary | **PROVEN** — no set_status/set_ok/set_epistemic/set_confidence/set_provider_called |
| Memory boundary | **PROVEN** — no write_memory/store_to_memory/persist_to_project |

**22/22 independent adversarial probes PASSED.**

---

## AUTHORITY RULES (from movement_16_resource_discovery_map.json)

Movement 16 establishes 25 authority rules, 20 component responsibilities, and 12 obligations:

| # | Rule |
|---|---|
| 1 | Discovery is evidence, not authority. |
| 2 | Discovery != RRM authority. |
| 3 | Discovery != binding authority. |
| 4 | Discovery != authorization authority. |
| 5 | Discovery != provider authority. |
| 6 | Discovery != tool authority. |
| 7 | Discovery != agent promotion authority. |
| 8 | Discovery != mission authority. |
| 9 | Discovery != product-response authority. |
| 10 | Discovery != ProductBridge authority. |
| 11 | Discovery != memory authority. |
| 12 | Evidence is immutable (frozen dataclass). |
| 13 | Status is observed only (OBSERVED/STALE/REVOKED). |
| 14 | Confidence never grants authorization or eligibility. |
| 15 | Health never sets RRM eligibility. |
| 16 | Metadata with authority keywords is descriptive only. |
| 17 | Snapshot is derived read-only. |
| 18 | Cross-reference is derived from RRM read-only queries. |
| 19 | Proposal status transitions never mutate any authority. |
| 20 | Deduplication on kind+resource_id+source. |
| 21 | Adapter failure is fail-closed. |
| 22 | Discovery does not bind resources. |
| 23 | Discovery does not invoke providers. |
| 24 | Discovery does not authorize tools. |
| 25 | M16 is additive: existing RRM, binding, authorization untouched. |

Full detail: `docs/MOVEMENT_16_RESOURCE_DISCOVERY_MAP.md` + `docs/movement_16_resource_discovery_map.json`.

---

## FINAL VALIDATION BASELINE

| Metric | Result |
|---|---|
| Movement 16 targeted tests | **58 passed** |
| Matrix A–Z (26) | 26 passed |
| Adversarial (15) | 15 passed |
| Novel domains (6) | 6 passed |
| Governance (11) | 11 passed |
| Independent adversarial probes (outside repo) | **22/22 passed** |
| Movement 14/15 regressions | **102 passed** |
| Full Python suite | **1279 passed, 2 pre-existing env failures** |
| Environmental failures | `test_symbiotic.py::test_programs_detected` (Windows `which`), `test_frontend_*` (CWD path) |
| Coverage | **86%** (`intent_kernel` + `product_bridge`; `discovery/` **100%**) |
| `compileall` | **PASS** |
| `git diff --check` | **PASS** |
| Movement 16 JSON map | **PASS** (movement=16, components=25, authority_rules=20, obligations=12) |
| JavaScript / TypeScript | **JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE** |

---

## NOVEL DOMAINS

Movement 16 tested six independently-chosen novel domains:

- `medical_imaging_device` (MRI scanner, X-ray, ultrasound)
- `agricultural_sensor` (soil moisture, weather, irrigation)
- `translation_service` (EN↔PT, EN↔ES, EN↔FR)
- `warehouse_robot` (AMR, forklift, conveyor)
- `clinical_trial_assistant` (protocol matching, enrollment, eligibility)
- `energy_grid_monitor` (solar inverter, wind turbine, transformer)

All observed as evidence only. None produced RRM resource creation, provider invocation, binding, authorization, or authority escalation. No default/finance contamination.

---

## KNOWN LIMITATIONS

1. `DiscoveryRegistry._evidence` is technically mutable via direct dict access; this grants no authority and no execution path consumes it.
2. `ResourceDiscoveryEvidence.metadata` is a dict (not frozen); authority keyword keys (`available`, `eligible`) are descriptive only — no attribute exposure.
3. JavaScript validation unavailable in this environment.
4. Evidence persistence across process restarts is not implemented (in-memory only).
5. `ResourceRegistrationProposal` is not wired to any automated registration workflow; this is intentional (PROPOSAL_ONLY).
6. Discovery adapters are not dynamically loaded (register/unregister only); plugin architecture is a future consideration.

These are **NOT** Movement 16 blockers.

---

## DELIVERY ARTIFACTS

- Commit: `a09049e` "feat: add governed resource discovery" (10 files, +2156)
- Bundle: `intentos-m16-governed-resource-discovery.bundle`
  - Size: 19826 bytes
  - SHA-256: `F3A32542B2ADA8AD4AB71F6EC186F190548872C106935F08555D93464BABFED4`
  - Contains: HEAD `a09049e`; requires base `933fa05`
  - `git bundle verify`: OK
  - Base64 round-trip: rebuilt SHA-256 identical; verify OK

---

## MOVEMENT 17 READINESS

Movement 17: **NOT READY**

Movement 16 establishes the governed resource discovery evidence layer. Movement 17
would require defining what happens when discovery evidence triggers a governed action
(e.g., auto-registration proposals, health-based rebinding, discovery-driven tool
selection) — which must be a separate, explicitly authorized movement with its own
authority proofs.

**DO NOT BEGIN MOVEMENT 17 without separate authorization.**
