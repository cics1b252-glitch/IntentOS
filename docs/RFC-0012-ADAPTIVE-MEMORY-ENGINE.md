# RFC-0012: Adaptive Memory Engine (AME) & Knowledge Object Model (KOM)

- **Status**: IMPLEMENTED / CANONICAL
- **Domain**: Cognitive Memory Infrastructure & Epistemic Persistence
- **Author**: Intent OS Kernel Engineering

---

## 1. Executive Summary

The **Adaptive Memory Engine (AME)** is the cognitive memory layer of Intent OS. It establishes that **memory is not storing everything**, but actively deciding what to remember, ignore, update, supersede, or purge.

The AME is underpinned by the **Knowledge Object Model (KOM)**, which defines `KnowledgeObject` as the canonical semantic primitive across the kernel.

---

## 2. Core Philosophy & Architectural Invariants

### 2.1 The Core Mantra
> "MEMÓRIA NÃO É ARMAZENAR TUDO."

### 2.2 Boundary Invariants
1. **Does NOT replace the ECC**: ECC remains the pipeline supervisor.
2. **Does NOT run agents**: Execution is handled by COR/Capabilities.
3. **Does NOT run tools**: Tool invocation belongs to COR.
4. **Does NOT call or select Providers**: AME is completely provider-agnostic.
5. **Does NOT manage RRM resources**: AME consumes resource IDs (e.g., `project_id`) without administering RRM catalogs.
6. **Does NOT dictate Constitutional truth**: Policy decisions remain governed by the Constitution.
7. **Does NOT store secrets**: Rejects API keys, bearer tokens, passwords, or credential material.
8. **Decoupled from DBs**: Operates via abstract persistence ports (`KnowledgeObjectRepositoryPort`, `VectorSearchPort`, `GraphEdgeStoragePort`, `BlobStoragePort`).

---

## 3. Knowledge Object Model (KOM)

`KnowledgeObject` fields:
- `object_id`: Unique identifier (UUID v4)
- `object_type`: Semantic taxonomy label
- `memory_class`: `EPISODIC`, `SEMANTIC`, `PREFERENCE`, `GOAL`, `DECISION`, `CORRECTION`, `PROCEDURAL`, `PROJECT_CONTEXT`, `TEMPORARY_CONTEXT`, `SYSTEM_LEARNING`
- `knowledge_nature`: `FACT`, `INFERENCE`, `ASSUMPTION`, `PREFERENCE`, `GOAL`, `DECISION`, `CORRECTION`, `OBSERVATION`
- `content`: Primary payload
- `summary`: High-level summary
- `project_id`: Scope boundary (`GLOBAL` or specific project ID)
- `user_scope`: `GLOBAL_SCOPE` or `PROJECT_SCOPE`
- `provenance`: `ProvenanceRecord` (source_type, source_id, timestamp, correlation_id, evidence)
- `confidence`: Epistemic score [0.0 - 1.0]
- `importance`: Salience score [0.0 - 1.0]
- `sensitivity`: `normal`, `confidential`, `secret`
- `status`: `ACTIVE`, `PENDING_VALIDATION`, `SUPERSEDED`, `EXPIRED`, `ARCHIVED`, `REJECTED`, `DELETED`
- `valid_from` / `valid_until`: Temporal validity bounds
- `version` / `supersedes` / `superseded_by`: Versioning lineage
- `retention_policy`: `SESSION`, `SHORT_TERM`, `LONG_TERM`, `PERMANENT`, `UNTIL_DATE`, `PROJECT_LIFETIME`

---

## 4. Memory Decision Engine

Evaluates every `MemoryCandidate` through deterministic rules:
1. **Secret Exclusion**: Rejects candidates containing secret patterns (`sk-`, `sk_live_`, `AIza`, etc.).
2. **Noise Filter**: Ignores conversational trivialities ("hi", "ok", "thanks").
3. **Correction Priority**: User corrections ("Corrigindo:", "Correction:") automatically `SUPERSEDE` prior active contradictory objects and increase version counter.
4. **Temporary Context Detection**: Time-bound statements ("Esta semana...") trigger `TEMPORARY` decision with `valid_until` ISO date.
5. **Deduplication**: Suppresses exact or overlapping statements already active in the scope.
6. **Project Scope Isolation**: Keeps `PROJECT_ATLAS` memories separated from `OEM_STUDIO` memories.

---

## 5. Pipeline Integration Ports

- `IUEContextPort`: Injects cognitive memory before asking redundant questions.
- `CDMContextPort`: Supplies known contextual state to dialogue decision logic.
- `CPEContextPort`: Injects prior decisions and architectural constraints into planning graphs.
- `ECCMemoryControlPort`: Authorizes or blocks memory access based on sensitivity.
- `RRMBoundary`: Validates project boundary references cleanly.
- `Bootstrap Cognitive Cortex (BCC)` Extension Points: Provides query and summary interfaces (`query_for_bcc`, `get_bcc_memory_summary`) for future offline cortex integrations.
