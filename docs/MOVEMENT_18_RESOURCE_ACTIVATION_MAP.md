# Movement 18 — Resource Activation Authority Map

## Canonical Activation Pipeline

```
REGISTERED RESOURCE
  + INDEPENDENT PREREQUISITE EVIDENCE
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

Applies activation decisions with 14-point TOCTOU revalidation:
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

The boundary MUST NOT manufacture prerequisite truth.
The boundary MAY apply an activation transition already justified by evidence.

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

### RA-18-02: Activation Evidence Repair

**Defect:** Boundary fabricated prerequisite fields without independent evidence.

**Repair:**
- Authority validates prerequisite evidence BEFORE approval
- Boundary MUST NOT manufacture prerequisite truth
- Evidence is INPUT to activation, not OUTPUT
- Approval is NOT evidence
- Forged/revoked/cross-resource evidence rejected
- Binding revalidation at application time

### Paths Contained

| Path | Type | Containment |
|---|---|---|
| RuntimeResourceProjection | COMPATIBILITY_ONLY | Projection callback, not governed activation |
| RRMToCORAdapter | COMPATIBILITY_ONLY | Adapter bridge, not governed activation |
| ProviderManager.register | BOOTSTRAP_ONLY | Registration path, not activation |
| Composition direct calls | BOOTSTRAP_ONLY | Bootstrap initialization, not activation |
| update_resource_status | GOVERNED | Status mutation, not activation |

## Lifecycle States

```
ResourceActivationStatus:
  PENDING → APPROVED / REJECTED / EXPIRED / REVOKED → CONSUMED
```

## Test Coverage

62 tests (A-Z matrix + adversarial scenarios):
- Models frozen and immutable (including evidence)
- Evidence model (revocation, validity)
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
