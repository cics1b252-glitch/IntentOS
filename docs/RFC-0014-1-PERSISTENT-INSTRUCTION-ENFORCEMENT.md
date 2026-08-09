# RFC-0014.1 — PERSISTENT INSTRUCTION ENFORCEMENT & BCC HARDENING GATE

## Context & Motivation

Memorizing an instruction does not guarantee that an AI agent will comply with it.
Intent OS bridges this fundamental gap by transforming persistent instructions stored in the Adaptive Memory Engine (AME) into verifiable mission constraints and enforced output contracts.

## Core Architectural Principle

```
MEMÓRIA PERSISTENTE NÃO É APENAS: RECORDAR.
É: RECORDAR → RECUPERAR → APLICAR → VERIFICAR → CORRIGIR QUANDO NECESSÁRIO.
```

## Flow Architecture

```
AME / KnowledgeObject
        │
        ▼
PersistentInstructionResolver
        │  (precedence, scope filtering, project isolation, secret rejection)
        ▼
MissionConstraints & OutputContract
        │
        ▼
ECC (Executive Cognitive Controller)
        │
        ▼
Cognitive Execution Pipeline
        │
        ▼
Candidate Output
        │
        ▼
OutputContractValidator
        │
        ├─ Valid → Completion Evidence Registered → Completion Allowed
        └─ Invalid → Violation Memory Registered → Correction Loop Request
```

## Key Components

1. **PersistentInstruction Model**:
   - Stores user and project rules (format preferences, delivery rules, safety preferences, project rules) as KnowledgeObjects in AME.
   - Enforces scope isolation (`GLOBAL_USER`, `PROJECT`, `MISSION`, `SESSION`).
   - Enforces secret rejection (blocks credential or API token persistence).

2. **PersistentInstructionResolver**:
   - Queries AME for active persistent instructions.
   - Applies strict precedence hierarchy:
     1. Constitution / Safety
     2. Current Explicit Mission Requirements
     3. Persistent Project Rules
     4. Persistent User Rules
     5. Session Preferences
     6. Agent Defaults
   - Handles supersession (v2 replaces v1).
   - Resolves rules into `MissionConstraint` objects and `OutputContract`.

3. **OutputContract & OutputContractValidator**:
   - Enforces delivery layout contracts (e.g., `single_block_required`, `text_outside_block_allowed = False`, `max_blocks = 1`).
   - Rejects text outside code blocks when single-block constraint is active.
   - Generates `CompletionEvidence` and `InstructionViolation` records.
   - Strictly enforces `CLAIM != VERIFIED STATE`.

4. **BCC Hardening Gate**:
   - Verifies zero-provider operation, UNKNOWN knowledge boundaries, provider neutrality, and auto-registration in RRM with `ResourceOrigin.CONFIGURATION`.
