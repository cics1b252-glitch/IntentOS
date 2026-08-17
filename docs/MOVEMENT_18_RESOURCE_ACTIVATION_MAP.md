# Movement 18 — Resource Activation Authority Map

## Canonical Activation Pipeline

```
REGISTERED RESOURCE
  → ACTIVATION REQUEST (typed, immutable)
  → PREREQUISITE EVALUATION (ACTIVATION_ONLY authority)
  → TYPED DECISION (APPROVE / REJECT)
  → TOCTOU REVALIDATION (ACTIVATION_APPLICATION_ONLY boundary)
  → ACTIVATION APPLICATION (mutates lifecycle fields)
  → ACTIVATED RESOURCE
```

## Design Principle

**Activation is the governed transition between REGISTERED and RUNTIME-AVAILABLE.**

Registration proves the resource is known to the canonical system.
Activation proves the resource satisfies governed prerequisites.
Activation does NOT manufacture eligibility, authorization, or execution.

## Separation of Concerns

### Authority — ACTIVATION_ONLY

Evaluates structural invariants:
- Resource is registered in RRM
- Resource is not a template
- Resource origin is not TEMPLATE
- Resource status is ACTIVE

Does NOT check resource-kind-specific prerequisites (is_configured, has_active_account, is_executable, is_enabled, installation_state, is_discovered, secret_reference) because those are the fields activation itself establishes.

### Application Boundary — ACTIVATION_APPLICATION_ONLY

Applies activation decisions to RRM lifecycle fields with 12-point TOCTOU revalidation:
1. Activation request still exists
2. Decision still exists
3. Decision is APPROVED
4. Decision matches exact request
5. Request matches exact resource
6. Resource is still registered
7. Registration/provenance unchanged
8. Resource object/identity not silently replaced
9. Pre-activation prerequisites remain satisfied
10. Scope remains valid
11. Decision has not been consumed (single-use)
12. Required binding/configuration still matches

### Service — ORCHESTRATION_ONLY

Delegates to authority and boundary; contains no independent mutation logic.

## Resource Kind → RRM Type Mapping

| Discovery Kind | RRM Type | Activation Fields |
|---|---|---|
| PROVIDER | Provider | is_configured, has_active_account |
| CAPABILITY | Capability | is_executable |
| AGENT | Agent | is_enabled, installation_state |
| ENVIRONMENT | ExecutionEnvironment | is_discovered |
| CONNECTED_SERVICE | Account | is_configured |
| DEVICE | Capability | is_executable |
| LOCAL_PROGRAM | Capability | is_executable |
| CUSTOM | Capability | is_executable |

## Anti-Bypass Containment

### RA-18-01: Ungoverned Activation Authority

**Defect:** Multiple paths create eligible resources without governed activation.

**Containment:**
- Authority evaluates structural invariants only
- Boundary applies activation fields with TOCTOU revalidation
- Single-use decision consumption
- No authority-bearing fields in activation models
- No discovery, promotion, or registration authority leak

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

48 tests across A-Z matrix + adversarial scenarios:
- Models frozen and immutable
- Status lifecycle enums
- Authority-bearing field rejection
- Provider/Capability/Agent/Environment/Account prerequisites
- Unsupported resource kind rejection
- Decision not found / consumed / not approved
- Request not found
- TOCTOU revalidation (resource not registered, became template, not active)
- Successful activation application (all resource kinds)
- Single-use enforcement
- Service pipeline (create, evaluate, activate)
- Consumption tracking
- Adversarial: no mutation without authority
- Adversarial: no discovery/promotion/registration/execution authority leak
- Composition wiring
