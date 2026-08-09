# Intent OS Architecture — V3.0 (Cognitive Kernel & Orchestration)

## Executive Summary

Intent OS v3.0 establishes a full distributed, cognitive, intent-driven operating system. It decouples **Intent Understanding**, **Dialogue Decisioning**, **Execution Planning**, **Capability Orchestration**, and **Executive Supervision**.

---

## High-Level Architecture Diagram

```
                        ┌──────────────────────────────┐
                        │          User / UI           │
                        └──────────────┬───────────────┘
                                       │ HTTP / WebSockets
                                       ▼
                        ┌──────────────────────────────┐
                        │       Server & Gateway       │
                        │    (server.ts / adapter.ts)  │
                        └──────────────┬───────────────┘
                                       │ JSON-RPC / IPC
                                       ▼
                        ┌──────────────────────────────┐
                        │        Product Bridge        │
                        │      (product_bridge.py)     │
                        └──────────────┬───────────────┘
                                       │
                                       ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                  Executive Cognitive Controller (ECC)                    │
 │                          (intent_kernel/ecc.py)                          │
 └──────┬──────────────────────┬──────────────────────┬──────────────┬──────┘
        │                      │                      │              │
        ▼                      ▼                      ▼              ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐┌──────────────┐
│     IUE      │       │     CDM      │       │     CPE      ││     COR      │
│ Intent Under-│       │  Cognitive   │       │  Cognitive   ││ Capability   │
│   standing   │       │   Dialogue   │       │   Planning   ││ Orchestrator │
│    Engine    │       │   Manager    │       │    Engine    ││   (Graph)    │
│  (RFC-0007)  │       │  (RFC-0008)  │       │  (RFC-0009)  ││  (RFC-0010)  │
└──────────────┘       └──────────────┘       └──────────────┘└──────────────┘
```

---

## Core Components Overview

### 1. Intent Understanding Engine (IUE — RFC-0007)
* **Purpose:** Transforms raw text into a `StructuredIntent`.
* **Output:** Intent Quality Index (IQI), domain classification, explicit & implicit goals, known/missing context.

### 2. Cognitive Dialogue Manager (CDM — RFC-0008)
* **Purpose:** Evaluates structured intents and selects at most ONE single, highest-impact clarification question.
* **Output:** `DialogueDecision` with state (`READY_TO_EXECUTE`, `NEEDS_CONTEXT`, etc.) and optional candidate question.

### 3. Cognitive Planning Engine (CPE — RFC-0009)
* **Purpose:** Generates a structured `ExecutionPlan` containing ordered steps, dependencies, tool specs, and Plan Quality Index (PQI).
* **Output:** `ExecutionPlan` with fallback paths and verification strategies.

### 5. Bootstrap Cognitive Cortex (BCC — RFC-0014)
* **Purpose:** Provides local, self-aware cognitive bootstrap capabilities without requiring external LLM providers.
* **Output:** Capability assessments, local mission continuation, and RRM built-in agent registration.

### 6. Persistent Instruction Enforcement (RFC-0014.1)
* **Purpose:** Converts user & project persistent instructions stored in AME into enforceable `MissionConstraints` and `OutputContracts`.
* **Output:** `MissionConstraint`, `OutputContract`, `OutputValidationResult` via `PersistentInstructionResolver` and `OutputContractValidator`.

* **Purpose:** Translates an abstract `ExecutionPlan` into a concrete `ExecutionGraph` by mapping plan steps to agents, capabilities, provider profiles, and account credentials.
* **Output:** `ExecutionGraph` containing nodes, edges, capability assignments, estimated cost, parallelism, and latency.

### 7. Mission Runtime (MR — RFC-0015)
* **Purpose:** Controlled execution engine executing approved `ExecutionGraph` instances with Action Gate, Verification Gate, and Completion Gate validation.
* **Output:** Node results, `CompletionEvidence`, checkpoints, and whole-mission completion status.

### 8. Capability & Tool Access Layer (RFC-0016)
* **Purpose:** Controlled tool discovery, permission management, capability routing, candidate ranking, credential reference boundary, and dry run simulation.
* **Output:** Ranked `ToolCandidate` instances, `ToolAuthorizationGate` decisions, safe simulation adapters (`EmailSimulationTool`, `CalendarSimulationTool`, `FilesystemSimulationTool`, `BrowserSimulationTool`), and `ToolSelectionTrace`.

### 9. Executive Cognitive Controller (ECC — RFC-0011 & RFC-0011.1)
* **Purpose:** The centralized cognitive supervisor that enforces Quality Gates, manages state transitions (`CognitiveState`), evaluates executive policies, and records an auditing `ExecutiveTrace`.
* **Output:** `ExecutivePipelineResult` with trace, state, metrics, and quality gate validations.
* **Stabilized Contracts (RFC-0011.1):**
  * **ExecutiveQualityPolicy:** Governs cognitive quality thresholds (`min_iqi`, `min_pqi`, `max_replans`, `max_dialogue_iterations`).
  * **ExecutiveExecutionPolicy:** Governs physical and operational constraints (`max_cost`, `max_latency`, `internet_allowed`, `cloud_execution_allowed`, `offline_required`).
  * **ExecutionEnvironment:** Catalog taxonomy (`LOCAL_PROCESS`, `DESKTOP`, `BROWSER`, `MOBILE`, `SERVER`, `CLOUD`, `EDGE`, `REMOTE`) assigned by COR during orchestration.
  * **ExecutiveDecisionTable:** Declarative decision table with precedence tiers (`1_CONSTITUTION` > `2_EXECUTION_POLICY` > `3_QUALITY_POLICY` > `4_RECOVERY_LIMITS` > `5_COST_LATENCY`).
  * **Policy Provenance:** Audit tracking (`SYSTEM_DEFAULT`, `USER_OVERRIDE`, `ENVIRONMENT_POLICY`, `ENTERPRISE_POLICY`).

---

## Pipeline Implementado Atual vs. Componentes Futuros

### Pipeline Implementado
```
User ──► ECC ──► IUE ──► CDM ──► CPE ──► COR ──► Mission Runtime (Action Gate ──► Capability Router ──► Tool Authorization Gate ──► ActionExecutorPort ──► Verification Gate ──► Completion Gate) ──► COMPLETED
```
O ciclo cognitivo executa de forma segura através do Mission Runtime e Tool Access Layer, que valida cada nó com o Action Gate e Tool Authorization Gate, roteia capacidades abstratas para ferramentas concretas elegíveis e autorizadas, executa via ActionExecutorPort seguro, verifica os resultados com o Verification Gate e avalia contratos finais no Completion Gate.

### Componentes Futuros (Não Implementados Nesta Fase)
* **Adaptive Memory Engine (RFC-0012):** Memória episódica, semântica e adaptativa de longo prazo.
* **Cognitive Learning:** Aprendizado contínuo e ajuste autônomo de estratégias de planejamento.
* **Response Assembly:** Montagem de respostas multimode e relatórios finais para o usuário.
