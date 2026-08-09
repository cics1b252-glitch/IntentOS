# RFC-0010: Capability Orchestrator (COR)

**Status:** Approved & Implemented  
**Date:** 2026-08-07  
**Layer:** Intent Kernel / Orchestration Layer  
**Target Component:** `intent_kernel/cor.py`  

---

## 1. Executive Summary & Context

The **Capability Orchestrator (COR)** is the canonical orchestration component of **Intent OS**. While the **Cognitive Planning Engine (CPE)** answers *what to do* (`ExecutionPlan`), the **Capability Orchestrator (COR)** answers *who does it* by generating a distributed, capability-matched **ExecutionGraph**.

COR maps abstract step requirements to concrete agent candidates, AI provider profiles, and service accounts registered in the system **Registry**, calculating multi-factorial scores without triggering real-world execution or calling external LLM APIs directly.

### Pipeline Location
```
[ User Input ]
       │
       ▼
[ IUE: Intent Understanding Engine ] ──► StructuredIntent (IQI)
       │
       ▼
[ CDM: Cognitive Dialogue Manager ] ──► DialogueDecision (can_proceed?)
       │
       ▼
[ CPE: Cognitive Planning Engine ] ──► ExecutionPlan (PQI)
       │
       ▼
[ COR: Capability Orchestrator ] ──► ExecutionGraph (Orchestration)
       │
       ▼
[ Mission Candidate / Execution Runtime ]
```

---

## 2. Fundamental Principles

1. **Planning vs. Orchestration**: Planning (`CPE`) determines *what* needs to be done. Orchestration (`COR`) determines *who* executes each step.
2. **Zero Side-Effect Decoupling**: COR does not invoke LLMs, send network messages, run scripts, or move funds. It produces a declarative execution blueprint.
3. **Capability-First Discovery**: Steps request abstract capabilities (`retrieval.financial_context`, `code.backend_logic`). COR queries the `RegistryCatalog` for matching providers and agents rather than relying on hardcoded agent names.
4. **Multi-Factorial Scoring & Ranking**:
   - **Agent Ranking**: Evaluates capability coverage (40%), historical confidence (30%), specialization (20%), and cost efficiency (10%).
   - **Provider Ranking**: Evaluates reasoning match (35%), privacy tier (25%), context window (20%), availability (10%), and token cost (10%).
   - **Account Selection**: Selects accounts based on quota availability (40%), priority tier (40%), and rate limits (20%).
5. **Parallel DAG Grouping**: Automatically groups independent steps into topological execution stages (`execution_groups`) to optimize parallel execution.
6. **Graceful Fallback**: Supports `reassign_fallback(graph, failed_step_id, failure_reason)` to re-rank and route to secondary candidates if a step fails at runtime, avoiding full plan regeneration.
7. **Complete Audit Trail**: Every assignment records full candidate rankings, capability matches, provider choices, and human-readable justification.

---

## 3. Data Contracts

### 3.1 `NodeAssignment`
```json
{
  "step_id": "step_1",
  "capability": "retrieval.financial_context",
  "agent_id": "agent_financial_atlas",
  "agent_name": "Atlas Financial Engine",
  "agent_score": 0.95,
  "provider_id": "provider_gemini_ultra",
  "provider_name": "Gemini 1.5 Pro / Ultra Profile",
  "provider_score": 0.92,
  "account_id": "acc_primary_gcp_01",
  "account_name": "Primary GCP Studio Enterprise Account",
  "account_score": 0.90,
  "match_score": 0.93,
  "reasoning": "Atribuído Agente 'Atlas Financial Engine' (score: 0.95) via Provider 'Gemini 1.5 Pro / Ultra Profile'...",
  "status": "assigned"
}
```

### 3.2 `ExecutionGraph`
```json
{
  "graph_id": "graph_a1b2c3d4",
  "plan_id": "plan_12345678",
  "status": "ready",
  "nodes": { ... },
  "edges": [
    { "from": "step_1", "to": "step_2" }
  ],
  "assignments": { ... },
  "execution_groups": [
    ["step_1", "step_2"],
    ["step_3"]
  ],
  "estimated_parallelism": 2.0,
  "estimated_cost": 0.0045,
  "estimated_latency": 0.25,
  "execution_policy": {
    "active_policies": ["standard", "high_privacy"]
  },
  "validation": [
    "Atribuição de capacidades e agentes efetuada com sucesso.",
    "Grafo de dependência validado como DAG acíclico."
  ],
  "created_at": "2026-08-07T02:37:00Z"
}
```

---

## 4. Mandatory Example Scenarios

- **Case A (Financial Advisory)**: Maps financial steps to `Atlas Financial Engine` via `Gemini Ultra` and primary GCP enterprise account.
- **Case B (Deep Research)**: Distributes parallel research steps to `Deep Research Scout` and `Senior Researcher` running in parallel execution groups.
- **Case C (Software Engineering)**: Separates architectural design, scaffold generation, UI layout, backend logic, and testing among specialized coding agents.
- **Case D (Financial Analysis)**: Combines Atlas, Research Scout, and provider profiles dynamically based on domain requirements without vendor lock-in.

---

## 5. Verification & Compliance

- **Unit Tests**: `tests/test_cor.py` (100% pass rate across 44 unit tests).
- **Gateway Endpoints**: `/api/orchestrate` and `/api/cor` integrated in Express gateway (`server.ts`), Adapter (`gateway/adapter.ts`), and Product Bridge (`product_bridge.py`).
- **Inspector UI**: Real-time visual tracking of Execution Graph, parallel stages, agent/provider/account assignments, estimated cost, and latency in `index.html`.
- **Architectural Isolation**: COR imports zero network/LLM/tool execution libraries.
