# RFC-0015 — CONTROLLED COGNITIVE EXECUTION RUNTIME & ACTION / VERIFICATION GATES

## Status
APPROVED & IMPLEMENTED (STUDIO 10.2)

## Context & Motivation

In Intent OS, an Execution Graph approved by the Executive Cognitive Controller (ECC) represents an abstract execution strategy. Prior to RFC-0015, no dedicated Mission Runtime existed to control, verify, and persist the execution of action graph nodes safely.

## Core Architectural Principles

```
PLAN != EXECUTION
ACTION_REQUESTED != ACTION_EXECUTED
ACTION_EXECUTED != ACTION_SUCCEEDED
AGENT_CLAIM != VERIFIED_RESULT
MISSION_GENERATED != MISSION_COMPLETED
```

A mission is only considered completed when sufficient evidence demonstrates that all success criteria and output contracts have been verified.

## Architecture & Components

```
User / Intent OS
       │
      ECC (Supervisor)
       │
MissionRuntime (MR Engine)
       │
   ActionGate (Pre-Execution Checks)
       │
ActionExecutorPort (Safe In-Memory / Test Executor)
       │
VerificationGate (Post-Execution Verification)
       │
MissionCompletionGate (OutputContract & Evidence Gate)
       │
      ECC
```

### 1. MissionRuntime & States
- **MissionRuntimeStates**: `CREATED`, `READY`, `RUNNING`, `WAITING_DEPENDENCY`, `WAITING_USER_CONFIRMATION`, `WAITING_RESOURCE`, `WAITING_VERIFICATION`, `PAUSED`, `RECOVERING`, `BLOCKED`, `FAILED`, `CANCELLED`, `COMPLETED`.
- **RuntimeNodeStates**: `PENDING`, `READY`, `EXECUTING`, `WAITING_CONFIRMATION`, `WAITING_RESOURCE`, `WAITING_VERIFICATION`, `SUCCEEDED`, `FAILED`, `BLOCKED`, `SKIPPED`, `CANCELLED`.

### 2. ActionGate Precedence Order
1. Constitution / Safety
2. Explicit Deny Execution Policy
3. Persistent Mission Constraints
4. Required User Confirmation (`EXTERNAL_IRREVERSIBLE`, `EXTERNAL_REVERSIBLE`)
5. Resource Availability (RRM Revalidation)
6. Environment Eligibility
7. Idempotency Check
8. Normal Execution

### 3. Verification & Completion Gates
- `VerificationGate`: Evaluates node results with `ActionVerificationPort` and generates `CompletionEvidence`.
- `MissionCompletionGate`: Validates that all mandatory nodes are `SUCCEEDED` and verified, and validates `OutputContract` structure via `OutputContractValidator`.

### 4. Checkpoints & Resume
- `MissionCheckpointRepositoryPort`: Persists runtime checkpoints.
- `resume()`: Restores completed nodes without re-executing them upon restart.
