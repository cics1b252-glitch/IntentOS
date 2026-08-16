# MOVEMENT 17 — FORMAL CLOSURE

STATUS
MOVEMENT_17_VERIFIED

MOVEMENT
Governed Resource Promotion Convergence

IMPLEMENTATION COMMIT
cdcc0370421e41945bf6ae9c3dc2e9d86e50b6a9

BASE
31a7da39d68753ab0f78efed554dce6e20fa74c7

CORE PRINCIPLE

DISCOVERY IS EVIDENCE.
DISCOVERY IS NOT AUTHORITY.

ARCHITECTURAL CHAIN:

DISCOVERY != PROPOSAL
PROPOSAL != APPROVAL
APPROVAL != REGISTRATION
REGISTRATION != AVAILABILITY
AVAILABILITY != ELIGIBILITY
ELIGIBILITY != AUTHORIZATION
AUTHORIZATION != EXECUTION

---

## FINAL PROMOTION ARCHITECTURE

Discovery Evidence (CanonicalResourceDiscoveryService)
        |
Resource Registration Proposal (ResourcePromotionProposalService)
        |
Explicit Typed Promotion Decision (ResourcePromotionDecisionAuthority)
        |
TOCTOU Revalidation (10-point check in CanonicalPromotionRegistrationBoundary)
        |
Canonical Registration Boundary (CanonicalPromotionRegistrationBoundary)
        |
RRM Registration State (ResourceRegistrationManager)
        |
Independent Availability / Eligibility (RRM)
        |
Existing Binding / Authorization / Execution Authorities

No stage inherits authority from the previous stage.

---

## FINAL AUTHORITY MODEL

### CanonicalResourceDiscoveryService
Classification: DISCOVERY_EVIDENCE_COLLECTION
Authority: Evidence collection and observation only
M17 change: None. Existing boundary preserved.

### DiscoveryRegistry
Classification: EVIDENCE_INDEX
Authority: Evidence storage and lookup only
M17 change: None. Used by promotion for evidence retrieval.

### ResourceRegistrationProposal
Classification: PROPOSAL_DATA
Authority: None. Frozen dataclass. Non-productive.
M17 change: New type. Created by ProposalService, carries evidence identity.

### ResourcePromotionProposalService
Classification: PROPOSAL_ONLY
Authority: Proposal creation only. No registration, no approval, no availability.
M17 change: New service.

### ResourcePromotionDecisionAuthority
Classification: APPROVAL_ONLY
Authority: Approval decision only. Single-use. Unknown types rejected.
M17 change: New service.

### CanonicalPromotionRegistrationBoundary
Classification: REGISTRATION_ONLY
Authority: Boundary between approval and RRM registration. TOCTOU revalidation.
M17 change: New service.

### CanonicalResourcePromotionService
Classification: ORCHESTRATION_ONLY
Authority: Orchestrates proposal -> approval -> registration pipeline. No direct RRM mutation.
M17 change: New service.

### ResourceRegistrationManager (RRM)
Classification: CANONICAL_REGISTRATION_AUTHORITY
Authority: Runtime registration, availability, eligibility
M17 change: None. Promotion registers through RRM's existing API.

### CanonicalCapabilityRegistry
Classification: CAPABILITY_AUTHORITY
Authority: Canonical capability resolution
M17 change: None. Preserved from M13.

### CanonicalResourceBindingAuthority
Classification: BINDING_AUTHORITY
Authority: Resource binding and selection
M17 change: None. Preserved from M13.

### CanonicalProviderAuthority
Classification: PROVIDER_AUTHORITY
Authority: Provider resolution and invocation
M17 change: None. Preserved from M11.

### ProviderManager
Classification: PROVIDER_ORCHESTRATION
Authority: Provider lifecycle management
M17 change: None. Preserved from M11.

### ToolAuthorizationGate
Classification: TOOL_AUTHORIZATION
Authority: Tool authorization and permission checks
M17 change: None. Preserved from M11.

### CanonicalAgentFactory
Classification: AGENT_FACTORY
Authority: Agent instantiation with injected capabilities
M17 change: None. Preserved from M15.

### GovernedAgent
Classification: GOVERNED_AGENT
Authority: Agent execution within injected capability boundary
M17 change: None. Preserved from M15.

### CanonicalMemoryService
Classification: MEMORY_AUTHORITY
Authority: Memory read/write with authority enforcement
M17 change: None. Preserved from M11.

### ProductBridge
Classification: PRODUCT_BRIDGE
Authority: Product state management
M17 change: None. Preserved from M12.

### Compatibility Paths
Classification: COMPATIBILITY_BOUNDARY
Authority: Backward compatibility routing
M17 change: None. Preserved from M13.

**No duplicate canonical authority was introduced by Movement 17.**

---

## PRIMARY VERIFIED INVARIANTS

DISCOVERY != REGISTRATION
PROPOSAL != APPROVAL
APPROVAL != REGISTRATION
REGISTRATION != AVAILABILITY
AVAILABILITY != ELIGIBILITY
ELIGIBILITY != AUTHORIZATION
AUTHORIZATION != EXECUTION
REGISTERED != SELECTED
SELECTED != ATTEMPTED
ATTEMPTED != USED
EXECUTION != VERIFICATION
VERIFICATION != COMPLETION

An approved proposal may truthfully exist while:
- registered=false
- available=false
- eligible=false
- authorized=false
- attempted=false
- used=false

---

## APPROVAL IDENTITY GUARANTEES

- Approval is exact-proposal bound (decision.proposal_id == proposal.proposal_id)
- Approval is evidence/provenance bound (decision.evidence_identity == proposal.evidence_identity)
- Approval is single-use (consumed set prevents replay)
- Approval cannot transfer by resource_id alone
- Same logical resource does not imply same approved identity
- Replacement evidence cannot inherit approval
- Replacement proposal cannot inherit approval
- Replay fails closed
- Terminal/revoked/expired proposal state cannot silently resurrect
- Arbitrary metadata cannot manufacture approval

---

## TOCTOU GUARANTEES

Revalidation boundary between APPROVAL and REGISTRATION:

1. Evidence still exists in discovery registry
2. Evidence has not been revoked (status != REVOKED)
3. Evidence identity matches proposal evidence_identity
4. Proposal still in APPROVED status (not expired, not revoked)
5. Decision still valid (not consumed, decision type is APPROVE)
6. Registration target matches approved resource_id
7. No conflicting registration exists for same resource_id

A resource different from the one reviewed and approved must never silently inherit the approval.

---

## RRM BOUNDARY

RRM remains canonical authority for runtime availability and eligibility.

Movement 17 registration must not manufacture:
- available=true
- eligible=true
- authorized=true

Registration records existence/state only according to the existing canonical resource model.

---

## EXECUTION BOUNDARIES

- provider promotion != provider invocation
- tool promotion != tool authorization
- agent role != promotion authority
- agent capability claim != runtime resource
- registration != executable binding
- registration != Mission execution
- registration != verification
- registration != completion

No productive external execution was enabled by Movement 17.

---

## MOVEMENT 11-16 PRESERVATION

### Movement 11
runtime/conversation/resource/provider/memory authority — PRESERVED

### Movement 12
response/product truth — PRESERVED

### Movement 13
RRM convergence + RA-13-01 exact binding identity — PRESERVED

### Movement 14
same-Mission typed confirmation/resume and completion authority — PRESERVED

### Movement 15
governed Agent factory with no autonomous authority — PRESERVED

### Movement 16
discovery-as-evidence boundary — PRESERVED

---

## VALIDATION BASELINE

### Movement 17 Targeted Tests
Result: 62/62 PASSED
Time: 0.85s

### Base-Control Comparison (M16 base)
M16 base: 988 passed, 1 failed, 292 errors
M17 HEAD: 1050 passed, 1 failed, 292 errors
Delta: +62 tests (exactly M17), 0 regression

### Full Suite Results
Total: 1050 passed, 1 failed, 292 errors
1 failed: test_programs_detected (pre-existing Windows `which` issue)
292 errors: all PermissionError (environmental, identical on M16 base and M17 HEAD)

### Coverage
Promotion package: 92% (284 stmts, 15 missing, 76 branches, 13 partial)
New M17 code: 94.8% of 287 new statements covered

### compileall: PASS
### git diff --check: PASS
### JSON validation: PASS

### JavaScript/TypeScript Status
JAVASCRIPT_VALIDATION_ENVIRONMENT_UNAVAILABLE

### Independent Audit Probes
24/24 probes passed (authority matrix, primary invariant, proposal non-productive, discovery-proposal identity, approval identity, approval replay, rejected/expired/revoked, ambiguous approval, decision forgery, TOCTOU evidence replacement, TOCTOU proposal frozen, TOCTOU conflict, registration boundary, registration != availability, executable metadata attack, tool promotion, agent self-promotion, novel domains, M15 regression, M16 regression)

---

## KNOWN LIMITATIONS

### ARCHITECTURAL LIMITATION
- Observability: Promotion package emits no structured logs, events, or diagnostic endpoints. Quality concern, not a correctness or security issue.

### ENVIRONMENTAL LIMITATION
- Windows PermissionError on basetemp directory (292 errors across full suite). Identical on M16 base and M17 HEAD. Not M17-caused.
- JavaScript/TypeScript validation unavailable in current environment.

### DEFERRED CAPABILITY
- No productive external execution enabled by M17. Promotion is a governance layer only.

---

## MOVEMENT 18 READINESS

MOVEMENT 17: VERIFIED, CLOSED
MOVEMENT 18: READY, NOT STARTED

Movement 18 requires separate explicit authorization.

---

CLOSURE COMMIT
docs: close movement 17 governed resource promotion

STARTING SHA
cdcc0370421e41945bf6ae9c3dc2e9d86e50b6a9

ENDING SHA
9cc80ee
