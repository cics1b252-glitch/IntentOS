# RFC-0009: Cognitive Planning Engine (CPE)

**Status:** Approved & Implemented  
**Date:** 2026-08-07  
**Layer:** Intent Kernel / Planning Layer  
**Target Component:** `intent_kernel/cpe.py`  

---

## 1. Executive Summary & Context

The **Cognitive Planning Engine (CPE)** is the canonical planning module of **Intent OS**. It accepts an understood, structured intent (`StructuredIntent` from IUE) and a dialogue evaluation decision (`DialogueDecision` from CDM), and decomposes the user goal into a verifiable, dependency-aware, capability-first **ExecutionPlan** without triggering real-world side effects.

### Architecture Pipeline Location
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
[ Mission Candidate / Execution Runtime ]
```

---

## 2. Fundamental Principles

1. **Zero Unintended Execution**: CPE generates declarative plans. It does not execute external APIs, move money, send emails, or run shell scripts directly.
2. **Capability-First Decoupling**: Steps specify abstract capabilities (`retrieval.financial_context`, `external.communication`) rather than hardcoding vendor names (e.g. OpenAI, Gemini) or specific model versions.
3. **Strict Dialogue Readiness Gate**: If CDM reports `can_proceed == False` or `state != READY_TO_EXECUTE`, CPE returns a blocked draft plan with `status="blocked"` and confirmation gate explaining that dialogue/clarification is required first.
4. **Explicit Risk & Reversibility**: Every step classifies risk level (`low`, `medium`, `high`, `critical`) and reversibility (`reversible`, `partially_reversible`, `irreversible`). Any step with external/irreversible effects requires a mandatory `confirmation_points` gate.
5. **DAG Dependency Validation**: Step dependencies form a Directed Acyclic Graph. CPE detects circular dependencies and marks the plan as `blocked` if a cycle is present.

---

## 3. Data Contracts

### 3.1 `PlanStep`
```json
{
  "step_id": "step_1",
  "objective": "Resgatar histórico financeiro e perfil do usuário",
  "action_type": "retrieve",
  "inputs": {},
  "expected_output": "Perfil financeiro e restrições consolidados.",
  "dependencies": [],
  "required_capabilities": ["retrieval.financial_context"],
  "candidate_agents": ["atlas", "financial_agent"],
  "risk_level": "low",
  "reversibility": "reversible",
  "requires_confirmation": false,
  "validation": ["Perfil financeiro possui objetivo e nível de risco."],
  "retry_policy": { "max_retries": 2, "backoff": "exponential" },
  "status": "pending"
}
```

### 3.2 `PlanQualityIndex` (PQI)
| Metric | Description | Weight |
| :--- | :--- | :--- |
| `goal_alignment` | Alignment between step objectives and user intent goal | 25% |
| `completeness` | Coverage of required domain steps | 20% |
| `feasibility` | Feasibility under known constraints | 20% |
| `dependency_integrity` | Graph validity (1.0 = acyclic DAG, 0.0 = cycle detected) | 15% |
| `risk_awareness` | Presence of confirmation gates for high-risk steps | 10% |
| `validation_coverage` | Proportion of steps with explicit validation criteria | 10% |

#### Difference between IQI and PQI
- **IQI (Intent Quality Index)**: Measures how clearly and completely the system *understands* the human user's input.
- **PQI (Plan Quality Index)**: Measures how complete, safe, feasible, and verifiable the *generated execution plan* is.

### 3.3 `ExecutionPlan`
```json
{
  "plan_id": "plan_a1b2c3d4",
  "intent_id": "iue_12345678",
  "goal": "Recomendação de investimento para R$ 23.500",
  "status": "ready",
  "mission_candidate_id": "mission_987654",
  "assumptions": [
    { "text": "Usuário busca alocação em renda fixa conservadora", "provenance": "IUE" }
  ],
  "constraints": ["Perfil conservador"],
  "steps": [ ... ],
  "dependencies": [ { "from": "step_2", "to": "step_1" } ],
  "required_capabilities": ["retrieval.financial_context", "modeling.allocation_scenarios"],
  "candidate_agents": ["atlas", "financial_agent"],
  "provider_requirements": {
    "reasoning": "high",
    "context_window": "medium",
    "tool_use": true,
    "structured_output": true,
    "privacy": "standard"
  },
  "confirmation_points": [],
  "validation_rules": [
    "Todas as premissas devem estar explicitamente documentadas."
  ],
  "confidence": 0.90,
  "provenance": [
    { "fact": "Goal: Recomendação de investimento", "origin": "IUE", "type": "FACT" }
  ],
  "plan_quality_index": {
    "goal_alignment": 0.95,
    "completeness": 0.90,
    "feasibility": 0.95,
    "dependency_integrity": 1.0,
    "risk_awareness": 0.95,
    "validation_coverage": 1.0,
    "overall_score": 0.95
  },
  "created_at": "2026-08-07T02:28:00Z"
}
```

---

## 4. Re-planning Mechanism (`replan`)

When execution fails at runtime (e.g. external service down), `cpe.replan(...)` preserves completed steps, marks the failing step as `failed`, injects a `recovery_step` with `action_type="analyze_and_fallback"`, and updates downstream dependencies without restarting the whole plan from scratch.

---

## 5. Mandatory Example Cases

- **Case A (Financial Advisory)**: `"Quero investir R$ 23.500."` — Generates multi-step advisory plan (retrieve context -> analyze constraints -> calculate allocation -> evaluate risk -> synthesize recommendation -> validate). No money movement.
- **Case B (Software Development)**: `"Monte um aplicativo para controlar manutenção do meu carro."` — Generates software engineering plan (design architecture -> generate scaffold -> verify functionality).
- **Case C (Irreversible Communication)**: `"Envie um e-mail para João informando que aceito a proposta."` — Identifies external effect, sets `requires_confirmation: true` and attaches a `confirmation_points` gate. Does not dispatch email.
- **Case D (Parallel Execution)**: `"Pesquise três alternativas e compare."` — Steps `step_research_alt_1`, `step_research_alt_2`, `step_research_alt_3` run in parallel (no dependencies), while `step_compare_alternatives` depends on all three.

---

## 6. Verification and Compliance

- Unit tests in `tests/test_cpe.py` (100% pass)
- Gateway integration in `gateway/adapter.ts`, `server.ts`, and `product_bridge.py`
- Architectural isolation: CPE imports zero concrete provider SDKs or external execution tools.
