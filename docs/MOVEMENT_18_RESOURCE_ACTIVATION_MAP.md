# Movement 18 — Resource Activation Authority Map

## Canonical Activation Pipeline

```
REGISTERED RESOURCE
  + INDEPENDENT PREREQUISITE EVIDENCE
  → EVIDENCE VALIDATION (CanonicalActivationEvidenceAuthority)
  → ACTIVATION REQUEST (typed, immutable)
  → PREREQUISITE EVALUATION WITH EVIDENCE (ACTIVATION_ONLY authority)
  → TYPED DECISION (APPROVE / REJECT)
  → TOCTOU REVALIDATION (ACTIVATION_APPLICATION_ONLY boundary)
  → ACTIVATION APPLICATION (observes, does not fabricate)
  → ACTIVATED RESOURCE
```

## Design Principle

**ACTIVATION MUST VERIFY PREREQUISITE TRUTH.**
**ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH.**
**ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.**
**CALLER ASSERTION ≠ CANONICAL SOURCE OF TRUTH.**

Evidence is INPUT to activation.
Approval is NOT evidence.
Activation verifies that prerequisite facts already exist.
Activation does NOT create prerequisite facts.

## Invariant Chain

```
INDEPENDENT EVIDENCE
  ≠ ACTIVATION DECISION
  ≠ ACTIVATION APPLICATION
  ≠ RRM ELIGIBILITY
  ≠ AUTHORIZATION
  ≠ EXECUTION
```

## Separation of Concerns

### Evidence Authority — EVIDENCE_COLLECTION_ONLY

Derives activation evidence from canonical sources. Callers cannot construct arbitrary evidence:

- `collect_for_resource()` queries canonical source and produces **TRUSTED** evidence
- Only `collect_for_resource()` produces evidence in the canonical trusted store
- Provider: is_configured + has_active_account derived from RRM state
- Capability: is_executable + binding_identity derived from capability registry
- Agent: is_enabled + installation_state derived from RRM state
- Environment: is_discovered derived from RRM state
- Account: secret_reference derived from RRM state
- `validate_and_store()` is **COMPATIBILITY_ONLY / TEST_ONLY** — stores in compatibility store, does NOT grant trusted status
- `is_evidence_trusted(evidence_id)` checks canonical trusted store

### Authority — ACTIVATION_ONLY

Validates ALL prerequisites including resource-kind-specific evidence:
- Resource is registered in RRM
- Resource is not a template
- Resource origin is not TEMPLATE
- Resource status is ACTIVE
- Provider: is_configured + has_active_account (via evidence)
- Capability: is_executable (via evidence)
- Agent: is_enabled + installation_state (via evidence, privileged roles rejected)
- Environment: is_discovered (via evidence)
- Account: secret_reference (via evidence)

For every APPROVED decision, diagnostics identify which prerequisite categories
were verified. Evidence must be independent of activation.

### Application Boundary — ACTIVATION_APPLICATION_ONLY

Applies activation decisions with 15-point TOCTOU revalidation:
1. Activation request still exists
2. Decision still exists
3. Decision is APPROVED
4. Decision matches exact request
5. Request matches exact resource
6. Resource is still registered
7. Registration/provenance unchanged
8. Resource object/identity not silently replaced
9. Prerequisite evidence still exists and is valid
10. Evidence still applies to exact resource
11. Evidence not stale/revoked
12. Binding/configuration identity unchanged
13. Scope remains valid
14. Decision has not been consumed (single-use)
15. Evidence revalidated against canonical source (TOCTOU)

The boundary MUST NOT manufacture prerequisite truth.
The boundary MAY apply an activation transition already justified by evidence.
For governed resources, only this boundary may apply legitimate updates.

### Service — ORCHESTRATION_ONLY

Delegates to authority and boundary; contains no independent mutation logic.

## Activation Evidence Model

### ResourceActivationEvidence (frozen, immutable)

| Field | Description |
|---|---|
| evidence_id | Unique identifier |
| resource_id | Target resource |
| resource_kind | Discovery kind |
| evidence_type | Typed category |
| source | Canonical source |
| source_identity | Source identity for validation |
| observed_at | Timestamp |
| scope | Scope where applicable |
| binding_identity | Binding identity where applicable |
| revoked | Revocation flag |

### ActivationEvidenceType

| Type | Resource Kind | What It Proves |
|---|---|---|
| PROVIDER_CONFIGURATION | Provider | is_configured = True |
| PROVIDER_ACCOUNT | Provider | has_active_account = True |
| CAPABILITY_EXECUTABLE | Capability | is_executable = True |
| AGENT_IDENTITY | Agent | is_enabled = True, installation_state valid |
| ENVIRONMENT_DISCOVERY | Environment | is_discovered = True |
| ACCOUNT_SECRET | Account | secret_reference exists |

## Resource Kind → Evidence Requirements

| Discovery Kind | RRM Type | Required Evidence | Rejected Without |
|---|---|---|---|
| PROVIDER | Provider | PROVIDER_CONFIGURATION + PROVIDER_ACCOUNT | is_configured=False, has_active_account=False |
| CAPABILITY | Capability | CAPABILITY_EXECUTABLE | is_executable=False |
| AGENT | Agent | AGENT_IDENTITY (privileged roles rejected) | is_enabled=False, invalid installation_state |
| ENVIRONMENT | ExecutionEnvironment | ENVIRONMENT_DISCOVERY | is_discovered=False |
| CONNECTED_SERVICE | Account | ACCOUNT_SECRET | secret_reference=None |
| DEVICE | Capability | CAPABILITY_EXECUTABLE | is_executable=False |
| LOCAL_PROGRAM | Capability | CAPABILITY_EXECUTABLE | is_executable=False |
| CUSTOM | Capability | CAPABILITY_EXECUTABLE | is_executable=False |

## Anti-Bypass Containment

### RA-18-01: Ungoverned Activation Authority

**Defect:** Multiple paths create eligible resources without governed activation.

**Containment:**
- Authority validates ALL prerequisites using independent evidence
- Boundary observes, does not fabricate prerequisite fields
- Single-use decision consumption
- No authority-bearing fields in activation models
- No discovery, promotion, or registration authority leak
- Compatibility/bootstrap paths documented but not silently activated
- RRM same-ID overwrite guard: compatibility sources cannot overwrite governed resources
- Governed resource provenance: requires `governed_registration_id` (origin alone insufficient)
- Same-ID/same-origin replacement of governed resources rejected
- Explicit mark_governed() API for runtime governance with registration provenance

### RA-18-02: Activation Evidence Repair

**Defect:** Boundary fabricated prerequisite fields without independent evidence.

**Repair:**
- Authority validates prerequisite evidence BEFORE approval
- Boundary MUST NOT manufacture prerequisite truth
- Evidence is INPUT to activation, not OUTPUT
- Approval is NOT evidence
- Forged/revoked/cross-resource evidence rejected
- Binding revalidation at application time

### RA-18-03: Canonical Evidence Collection (Repair Cycle 3, hardened Cycle 4)

**Defect:** Public callers could construct arbitrary evidence and have it accepted as canonical truth.

**Repair:**
- `collect_for_resource()` derives evidence from canonical sources (callers cannot construct evidence)
- Evidence authority queries RRM directly for each resource kind
- Evidence model has `_trusted` field — only `collect_for_resource()` produces trusted evidence
- `validate_and_store()` is **COMPATIBILITY_ONLY / TEST_ONLY** — does NOT produce trusted evidence
- `is_evidence_trusted(evidence_id)` checks canonical trusted store
- Service exposes `collect_and_register_evidence()` as the trusted entry point
- Evidence TOCTOU: application boundary revalidates against canonical source at application time AND verifies `is_evidence_trusted()`

### RA-18-04: Governed Resource Provenance (Repair Cycle 3, hardened Cycle 4)

**Defect:** `resource_origin` alone classified resources as governed — origin is caller-controlled.

**Repair:**
- `governed_registration_id` field on all resource models
- `_is_governed_resource()` requires canonical `governed_registration_id` (not origin alone)
- `mark_governed()` is **COMPATIBILITY_ONLY / TEST_ONLY** — not the canonical source
- Canonical `governed_registration_id` is created by `CanonicalPromotionRegistrationBoundary` (M17)
- M17 creates `governed_registration_id` automatically bound to resource_id + kind + proposal_id + decision_id
- Same-ID replacement of governed resources rejected regardless of origin

### RA-18-01 (Revised): Compatibility/Bootstrap Overwrite Guard (Repair Cycle 3, hardened Cycle 4)

**Defect:** RRM register_* methods allowed replacement of governed resources.

**Repair:**
- `_is_governed_resource()` requires `governed_registration_id` (origin alone insufficient)
- ALL `register_*` methods reject governed resource replacement **unconditionally** (no different-origin exception)
- `update_resource_status()` returns False for governed resources
- MIGRATION, CONFIGURATION, HOST_DISCOVERY origins all rejected for governed resources
- `mark_governed()` is COMPATIBILITY_ONLY — not used in canonical trust flow

### Paths Contained

| Path | Type | Containment |
|---|---|---|
| RuntimeResourceProjection | COMPATIBILITY_ONLY | Projection callback, not governed activation. Cannot overwrite governed resources. |
| RRMToCORAdapter | COMPATIBILITY_ONLY | Adapter bridge, not governed activation. Cannot overwrite governed resources. |
| ProviderManager.register | COMPATIBILITY_ONLY | Registration path, not activation. Cannot overwrite governed resources. |
| Composition direct calls | COMPATIBILITY_ONLY | Bootstrap initialization, not activation. Cannot overwrite governed resources. |
| update_resource_status | GOVERNED | Status mutation returns False for governed resources. |
| Public register_evidence | COMPATIBILITY_ONLY | Evidence validated by CanonicalActivationEvidenceAuthority; does NOT produce trusted evidence. |
| collect_for_resource | TRUSTED | Canonical evidence collection — ONLY source of trusted evidence. |

## Lifecycle States

```
ResourceActivationStatus:
  PENDING → APPROVED / REJECTED / EXPIRED / REVOKED → CONSUMED
```

## Test Coverage

102 tests (A-Z matrix + RA-18-03 canonical evidence collection + RA-18-04 governed provenance + RA-18-01 overwrite guard + Cycle 4 comprehensive matrices):
- Models frozen and immutable (including evidence)
- Evidence model (revocation, validity, source_identity)
- Authority rejects unsupported/unregistered resources
- Provider: no evidence → reject, wrong evidence type → reject, revoked → reject
- Provider: not configured → reject, no active account → reject
- Provider: valid evidence + configured → approve
- Capability: no evidence → reject, not executable → reject, valid → approve
- Agent: no evidence → reject, not enabled → reject, privileged roles → reject
- Agent: valid evidence + enabled → approve
- Environment: no evidence → reject, not discovered → reject, valid → approve
- Account: no secret → reject, valid → approve
- Approval alone never changes eligibility fields
- Forged evidence → reject
- Cross-resource evidence → reject
- Revoked evidence after approval → application fails
- Decision replay → fails
- Binding replaced after approval → application fails
- Compatibility writer cannot bypass governed activation
- update_resource_status cannot bypass governed activation
- Zero-provider truth remains intact
- RA-13-01 remains fixed
- Activation ≠ authorization ≠ confirmation ≠ execution
- RA-18-01 containment
- TOCTOU revalidation (template, unregistered)
- Boundary observe-only (all resource kinds)
- RA-18-03: Canonical evidence collection (16 tests)
  - collect_for_resource returns empty for unregistered resource
  - collect_for_resource returns empty for unsupported kind
  - Provider: configuration/account evidence derived from canonical source
  - Provider: no evidence when not configured / no active account
  - Capability: executable evidence derived from canonical registry
  - Capability: no evidence when not executable
  - Agent: identity evidence derived from canonical RRM
  - Agent: no evidence when disabled / unavailable
  - Environment: discovery evidence derived from canonical source
  - Environment: no evidence when not discovered
  - Account: secret evidence derived from canonical source
  - Account: no evidence when no secret reference
  - Collected evidence has source_identity set
- RA-18-04: Governed provenance (12 tests)
  - Origin-only is NOT governed
  - mark_governed with registration_id makes resource governed
  - mark_governed without registration_id does NOT make resource governed
  - governed_registration_id on resource makes it governed
  - Same-ID/same-origin replacement rejected for governed resources
  - Same-ID/different-origin replacement allowed for governed resources
  - Compatibility source cannot overwrite governed resource
  - Non-governed resource can be freely registered
  - mark_governed sets governed_registration_id on resource
  - Agent/capability: same-origin replacement rejected when governed
  - Environment: compatibility cannot overwrite governed resource
- RA-18-01: RRM overwrite guard (13 tests)
  - Origin-only does NOT make resource governed (Cycle 3 fix)
  - Compatibility source CAN overwrite non-governed resource
  - Explicitly governed resource protected from compatibility
  - Same-origin replacement rejected for governed resources
  - Configuration/host discovery cannot overwrite governed resource
  - Non-governed resource can be freely registered
  - mark_governed with registration_id is persisted
  - Agent/capability/account/environment: compatibility cannot overwrite governed
  - Account: same-origin replacement rejected when governed
  - Agent capability account environment overwrite protection
- Cycle 4 — Canonical Trust Root (41 new tests):
  - RA-18-03 trust matrix (15 tests):
    - Caller-constructed evidence NOT trusted
    - collect_for_resource() evidence IS trusted
    - validate_and_store() stores in compatibility, NOT trusted
    - Source string alone NOT sufficient for trust
    - Evidence IDs unique; matches canonical source state
    - Trusted store is additive
    - All resource kinds produce trusted evidence
  - RA-18-04 provenance matrix (9 tests):
    - mark_governed() is COMPATIBILITY_ONLY
    - Origin alone insufficient for governed (USER_REGISTRATION, CONFIGURATION, MIGRATION, HOST_DISCOVERY)
    - Empty/special-character governed IDs handled correctly
  - RA-18-01 comprehensive origin matrix (11 tests):
    - ALL origins × ALL resource types rejected for governed replacement
    - No different-origin exception
  - RA-18-02 regression (2 tests):
    - Full pipeline still succeeds with trusted evidence
    - Boundary applies with trusted evidence
  - RA-13-01 exact identity (4 tests):
    - Typed enums; frozen evidence model rejects mutation
