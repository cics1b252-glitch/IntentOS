# RFC-0008 — Cognitive Dialogue Manager (CDM)

**Status**: Approved & Implemented  
**Date**: August 2026  
**Authors**: Intent OS Core Cognitive Architecture Team  
**Module**: `intent_kernel/cdm.py`  

---

## 1. Executive Summary & Fundamental Principle

The **Cognitive Dialogue Manager (CDM)** is the decision-making layer of the Intent OS cognitive pipeline responsible for controlling how the system interacts with the user to bridge the gap between human language and execution.

### Fundamental Principle
> **The best conversation is not the one that asks the most questions.**  
> **It is the one that asks the smallest necessary number of questions to correctly understand intent.**

The CDM never asks questions automatically or out of habit. Before interacting with the user, the CDM evaluates three core rational questions:
1. *Can I proceed directly with the current information?* (`can_proceed`)
2. *Do I need to ask a question?* (`requires_question`)
3. *Is asking worth the user's cognitive effort?* (`net_value` vs threshold)

---

## 2. Architectural Guarantees & Constraints

1. **No Direct Provider Invocation**: The CDM does **NOT** call LLM Providers directly.
2. **No Conversational Answer Generation**: The CDM does **NOT** construct final conversational replies or chit-chat.
3. **No Capability/Agent Execution**: The CDM does **NOT** trigger agent tools or capabilities.
4. **No Direct Mission State Mutation**: The CDM does **NOT** instantiate or execute Missions directly.
5. **Single Question Constraint**: The CDM selects at most **ONE** question per interaction turn, picking the question with the highest net IQI gain and lowest user friction.

---

## 3. Cognitive Pipeline & Integration

```
  Human Input (Text)
          │
          ▼
┌───────────────────┐
│       IUE         │  (Intent Understanding Engine — RFC-0007)
└─────────┬─────────┘
          │
          ▼  StructuredIntent
┌───────────────────┐
│       CDM         │  (Cognitive Dialogue Manager — RFC-0008)
└─────────┬─────────┘
          │
          ├─── [READY_TO_EXECUTE / can_proceed = True] ─────────► Mission Builder / CPE
          │
          └─── [NEEDS_CONTEXT / requires_question = True] ─────► Single High-Impact Question
```

---

## 4. Dialogue Decision States

| State | Description | `can_proceed` |
|---|---|---|
| `READY_TO_EXECUTE` | Intent is sufficiently clear and complete (IQI high, no blocking missing context). | `True` |
| `NEEDS_CONTEXT` | Material missing information blocks execution; a targeted question yields significant IQI gain. | `False` |
| `NEEDS_CONFIRMATION` | Intent is understood, but high-impact parameters require user confirmation before execution. | `False` |
| `MULTIPLE_VALID_PATHS` | Intent admits distinct valid technical or strategic trajectories (e.g. web vs mobile vs desktop). | `False` |
| `LOW_CONFIDENCE` | Classifier or IUE confidence is low (< 0.60), requiring grounding. | `False` |
| `INSUFFICIENT_INFORMATION` | Extremely brief or vague input ("Monte um aplicativo") with extreme structural uncertainty. | `False` |

---

## 5. Question Planner & Decision Algorithm

### Candidate Question Structure (`CandidateQuestion`)
Each candidate question evaluated by the Question Planner contains:
- `question_id`: Unique identifier
- `question`: Formatted Portuguese string targeting the missing gap
- `expected_iqi_gain`: Expected delta in IQI score (+0.10 to +0.50)
- `estimated_information_gain`: Entropy reduction score (0.0 to 1.0)
- `estimated_user_effort`: Estimated cognitive effort requested from user (0.0 = choice/short answer, 1.0 = open essay)
- `reason`: Structural reason for generating the candidate
- `target_field`: Domain field being clarified (e.g. `financial_goal_and_horizon`)

### Net Value Ranking Equation
$$\text{Net Value} = \frac{\text{expected\_iqi\_gain} \times (1.0 + \text{estimated\_information\_gain})}{1.0 + (0.5 \times \text{estimated\_user\_effort})}$$

### Memory & Context Deduplication Filter
Before ranking candidates, the CDM cross-references candidates against:
- `StructuredIntent.known_context`
- `StructuredIntent.known_context_provenance`
- `session_context["user_profile"]`

Any candidate question whose target information is already known in memory is **immediately filtered out**, preventing redundant questions.

---

## 6. Internal Justification & Cognitive Transparency

The CDM generates an internal justification dictionary (`justification`) for telemetry and auditing:
- `eval_state`: Active dialogue state
- `initial_iqi_score`: IQI score before question
- `selection_reasoning`: Explicit justification explaining why the top question was selected
- `discarded_candidates_reasons`: Detailed list explaining why other candidate questions were rejected (lower net value, higher user friction, or redundant with known context)

---

## 7. Learning Loop Integration (CLE)

The CDM includes `record_feedback()`, registering:
- `question_id` & `question_text`
- `target_field` & `user_response`
- `initial_iqi`, `actual_iqi_after`, `actual_iqi_gain`
- `was_helpful`: boolean (`actual_gain >= 0.5 * expected_gain`)

These records build the training logs for the upcoming **Cognitive Learning Engine (CLE)**.

---

## 8. Real Practical Scenarios

### Case 1: "Quero investir 23.500." (No Prior Context)
- **IUE Output**: `domain="finance"`, `amount=23.500`, `missing_context=["Objetivo", "Perfil de risco", "Prazo"]`.
- **CDM Evaluation**:
  - Raw candidates generated: Amount (filtered: already known), Goal + Horizon, Risk Profile, Recurrence.
  - Candidate 1 (Goal + Horizon): Expected IQI gain +0.38, Net Value 0.73.
  - Candidate 2 (Risk Profile): Expected IQI gain +0.22, Net Value 0.44.
- **Decision**: State = `NEEDS_CONTEXT`, `selected_question` = Goal + Horizon.

### Case 2: "Quero investir 23.500." (Financial Context in Profile)
- **Input Profile**: `financial_goal="Reserva de emergência"`, `risk_tolerance="Conservador"`, `liquidity_preference="Diária"`.
- **IUE Output**: Facts added to `known_context` from profile. `missing_context` = `[]`.
- **CDM Memory Filter**: Filters out all candidates as redundant.
- **Decision**: State = `READY_TO_EXECUTE`, `can_proceed = True`, `selected_question = None`.

### Case 3: "Monte um aplicativo." (High Uncertainty)
- **Input**: 3 words, generic software request.
- **IUE Output**: `domain="coding"`, `missing_context=["Finalidade e plataforma do aplicativo"]`.
- **CDM Evaluation**: Identifies structural ambiguity across multiple implementation trajectories.
- **Decision**: State = `INSUFFICIENT_INFORMATION` / `MULTIPLE_VALID_PATHS`, `selected_question` = Application architecture and purpose.
