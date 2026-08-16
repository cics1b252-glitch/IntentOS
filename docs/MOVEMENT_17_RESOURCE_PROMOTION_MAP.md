# Movement 17: Governed Resource Promotion Convergence

## Core Principle

**PROMOTION IS A GOVERNED TRANSITION.** Discovery does not imply registration. Registration does not imply eligibility. Eligibility does not imply availability.

## Primary Invariant

```
DISCOVERED != PROPOSED != APPROVED != REGISTERED != AVAILABLE != ELIGIBLE != SELECTED != AUTHORIZED != BOUND != ATTEMPTED != USED != VERIFIED
```

## Architecture

### Three-Segment Boundary

| Segment | Service | Classification |
|---------|---------|----------------|
| Proposal | `ResourcePromotionProposalService` | PROPOSAL_ONLY |
| Decision | `ResourcePromotionDecisionAuthority` | APPROVAL_ONLY |
| Registration | `CanonicalPromotionRegistrationBoundary` | REGISTRATION_ONLY |

Orchestrated by: `CanonicalResourcePromotionService`

### Lifecycle

```
Discovery Evidence
    |
    v
[PENDING] --reject--> [REJECTED]
    |
    v
[APPROVED] --consume--> [CONSUMED]
    |
    v
Registration (TOCTOU revalidation)
```

### TOCTOU Revalidation (10-Point Check)

1. Proposal exists
2. Proposal is APPROVED
3. Decision belongs to proposal
4. Decision is APPROVE type
5. Evidence still exists in discovery
6. Evidence not deleted
7. Evidence not revoked
8. Evidence not stale
9. No conflicting canonical resource in RRM
10. Resource kind supported for registration

### Registration Kinds

| Discovery Kind | RRM Registration Type |
|----------------|----------------------|
| PROVIDER | provider |
| AGENT | agent |
| ENVIRONMENT | environment |
| CAPABILITY | capability |
| TOOL | capability (fallback) |
| DEVICE | capability (fallback) |
| CUSTOM | capability (fallback) |
| CONNECTED_SERVICE | capability (fallback) |

## Invariants

- Discovery alone never triggers registration
- Proposal alone never triggers registration
- Rejection never triggers registration
- Expiration never triggers registration
- Revocation never triggers registration
- Approval alone never triggers registration (decision consumed at registration)
- Decision IDs are single-use (consumed after registration attempt)
- Proposal IDs are deterministic from evidence identity
- TOCTOU revalidation prevents stale registration
- Unknown decision types are rejected
- Agents cannot self-promote
- Providers cannot invoke themselves through promotion
- Tools cannot execute through promotion
- Metadata cannot escalate scope
- Composition wiring is additive only (+9 lines)

## Files

```
intent_kernel/promotion/
    __init__.py                         # Package exports
    models.py                           # Enums + frozen dataclasses
    proposal_service.py                 # PROPOSAL_ONLY service
    decision_authority.py               # APPROVAL_ONLY authority
    registration_boundary.py            # REGISTRATION_ONLY boundary
    promotion_service.py                # ORCHESTRATION service
```

### Composition Wiring

`intent_kernel/application/composition.py` (+9 lines additive):
- Import promotion services
- Add `_promotion_*` fields to composition
- Construct services with shared RRM and discovery references
- Expose through `promotion_*` properties
