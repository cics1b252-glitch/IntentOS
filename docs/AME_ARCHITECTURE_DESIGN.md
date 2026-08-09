# Adaptive Memory Engine (AME) — Architectural Design Document

**Document Version:** 1.0.0-DESIGN  
**Status:** ARCHITECTURAL SPECIFICATION (APPROVED FOR RFC-0012)  
**Target Component:** `intent_kernel/ame.py` (Future Implementation)  
**Classification:** Intent OS Core Architecture  

---

## 1. Executive Mission & Core Scope

The **Adaptive Memory Engine (AME)** is the cognitive memory backbone of Intent OS. Unlike passive vector databases, standard session stores, or simple key-value caches, the AME is an **active, governed, multi-tiered cognitive memory system** designed to maintain context, project boundaries, personal preferences, institutional policies, and historical evolution across multi-session execution lifecycles.

### Primary Directives
1. **Contextual Fidelity Without Bloat:** Provide the Cognitive Pipeline (IUE, CDM, CPE, COR, ECC) with minimal, highly relevant, verified memory state while decaying or archiving stale data.
2. **Deterministic Project Isolation:** Maintain strict, unbreachable memory walls between projects (e.g., `Intent OS`, `Atlas`, `OEM Studio`, `App Sinta`). Cross-project knowledge leakage is strictly prohibited unless explicit sharing rules exist.
3. **Epistemic Traceability:** Track provenance, source, confidence, and version history for every persisted memory node.
4. **Constitutional Alignment:** Enforce privacy policies, governance rules, and user consent gates prior to persisting, updating, or deleting high-impact memory nodes.

---

## 2. Memory Definition, Boundaries & Operational Rules

### What Is Memory in Intent OS?
In Intent OS, memory is **structured cognitive state with operational semantics**. It is not raw transcript text; it is synthesized, categorized, confidence-scored knowledge nodes that influence reasoning, dialogue, planning, and capability execution.

### What MUST NEVER Be Stored
- **Unsanitized Secrets:** Raw passwords, plain-text API keys, JWTs, OAuth tokens, private cryptographic keys, or payment card numbers.
- **Unverified Assumptions as Facts:** Guesses made by generative agents during execution without explicit user confirmation or strong operational evidence.
- **Transient Audio/Stream Payloads:** Raw audio buffers, binary stream frames, or temporary IPC payloads.
- **Out-of-Scope PII:** Unnecessary personal identification data not relevant to system execution.

### What MUST Be Learned
- **Explicit User Preferences:** Formatting preferences, communication styles, operational constraints, approved tools.
- **Active Project Goals & Decisions:** Project objectives, architectural decisions, design choices, rejected alternatives.
- **System Operational Capabilities & Latencies:** Execution performance of agents, environments, and capability providers.
- **Recurring Constraints & Policies:** Compliance requirements, runtime rules, security guidelines.

### Operational Lifecycle Matrix

| Operational Action | Trigger / Condition | Mechanism / Policy |
| :--- | :--- | :--- |
| **Update** | Fact or preference refinement observed with higher confidence or newer timestamp | Non-destructive in-place update for low-impact fields; version increment for structural nodes |
| **Supersede / Replace** | Direct contradiction where newer information invalidates old facts | Old node marked `superseded`, new node linked as active successor |
| **Version** | Core goals, architectural policies, or project scopes change | Version tag bumped (v1 -> v2), ancestral chain preserved |
| **Archive** | Memory node reaches decay threshold or project is marked inactive | Soft archive into long-term cold store, removed from active prompt contexts |
| **Ask User Confirmation** | Low confidence (<0.7) on high-importance facts or direct contradiction on core goals | CDM triggers a single candidate clarification question before mutating persistent state |

---

## 3. Taxonomy & Memory Classification

Memory in AME is structured into 14 distinct functional categories grouped under 3 fundamental layers:

```
+-------------------------------------------------------------------------------+
|                           AME TAXONOMY LAYERS                                 |
+-----------------------------------+-------------------------------------------+
| Layer                             | Categories Included                       |
+-----------------------------------+-------------------------------------------+
| 1. Epistemic & Preference Layer   | Facts, Preferences, Constraints, Policies |
| 2. Execution & Operational Layer  | Goals, Projects, Decisions, Sessions,     |
|                                   | Temporary Context, Historical Events      |
| 3. Relationship & Cognition Layer | Relationships, Skills, Learned Behaviour, |
|                                   | Long Term Knowledge                       |
+-----------------------------------+-------------------------------------------+
```

### Detailed Taxonomy Breakdown

1. **Facts (`FACT`):** Objective statements verified through direct user input or system execution (e.g., "Python version is 3.10").
2. **Preferences (`PREFERENCE`):** User inclinations regarding formatting, language, interaction frequency, or tool selection.
3. **Goals (`GOAL`):** Explicit targets, milestones, or outcome specifications for sessions or projects.
4. **Projects (`PROJECT`):** Project scope definitions, root parameters, and metadata isolating domain execution.
5. **Decisions (`DECISION`):** Architectural choices, technology selections, or trade-offs made during dialogue or execution.
6. **Relationships (`RELATIONSHIP`):** Entity linkages, dependency maps between components, agents, or external tools.
7. **Skills (`SKILL`):** Identified execution capabilities, agent skill sets, or user domain expertise levels.
8. **Constraints (`CONSTRAINT`):** Hard rules, bounds, quotas, or non-negotiable operational requirements.
9. **Policies (`POLICY`):** System governance, safety rules, compliance guidelines, and constitutional bounds.
10. **Sessions (`SESSION`):** Operational logs, state snapshots, and turn counters for active or past user interactions.
11. **Temporary Context (`TEMP_CONTEXT`):** In-flight slots, scratchpad variables, and intermediate execution artifacts.
12. **Long Term Knowledge (`LONG_TERM`):** Cross-session domain knowledge, persistent architectural concepts, and reference models.
13. **Learned Behaviour (`LEARNED_BEHAVIOR`):** System-observed patterns (e.g., "User prefers short summaries for CLI tools").
14. **Historical Events (`HISTORICAL_EVENT`):** Immutable log of milestone occurrences, system failures, and resolution audits.

---

## 4. Memory Node Lifecycle & State Machine

Every memory node within AME moves through a strictly governed finite state machine:

```
 +-------------+        +-------------+        +-------------+
 |   CREATED   | -----> |  VALIDATED  | -----> |   ACTIVE    |
 +-------------+        +-------------+        +-------------+
        |                      |                      |
        | (Invalidated)        v (Failed)             v (Newer Fact)
        |               +-------------+        +-------------+
        +-------------> | DEPRECATED  | <----- | SUPERSEDED  |
                        +-------------+        +-------------+
                               |                      |
                               v (Decay / Expire)     v (Archived)
                        +-------------+        +-------------+
                        |  FORGOTTEN  | <----- |  ARCHIVED   |
                        +-------------+        +-------------+
                               |
                               v (Explicit Purge / GDPR)
                        +-------------+
                        |   DELETED   |
                        +-------------+
```

### State Definitions & Transition Rules

1. **CREATED:** Newly extracted or candidate memory node, unverified, stored in temporary staging.
2. **VALIDATED:** Passed confidence checks, schema validation, and privacy policies.
3. **ACTIVE:** Promoted to active working memory or project persistent store; actively retrieved during pipeline execution.
4. **SUPERSEDED:** Invalidated by a newer, higher-confidence fact/version; preserved for lineage audit.
5. **DEPRECATED:** Declared outdated due to policy updates, component deprecation, or context decay.
6. **ARCHIVED:** Shifted to cold storage due to inactivity or project completion; non-indexable for active prompts unless explicitly queried.
7. **FORGOTTEN:** Automatically evicted from index and store based on decay mechanics and relevance scores.
8. **DELETED:** Permanently erased from physical store (e.g., upon user privacy request or explicit memory purge).

---

## 5. Temporary Memory Tier (Short-Term / Working Storage)

The Temporary Tier handles immediate interaction loops and task execution.

```
+-------------------------------------------------------------------------------+
|                            TEMPORARY MEMORY TIER                              |
+-------------------+----------------+------------------+-----------------------+
| Component         | Life Scope     | Persistence      | Eviction Trigger      |
+-------------------+----------------+------------------+-----------------------+
| Working Memory    | Single Turn    | In-Memory (RAM)  | Turn completion       |
| Conversation Mem  | Single Session | Session Store    | Session closure/TTL   |
| Mission Memory    | Single Mission | File/JSON Snapshot| Mission completion    |
| Execution Memory  | Single Plan    | Process Scope    | Plan terminal state   |
+-------------------+----------------+------------------+-----------------------+
```

### Eviction & Cleanup Mechanics
- **TTL (Time-To-Live):** Conversation memory expires after 2 hours of inactivity unless converted to persistent project memory.
- **Capacity Caps:** Working memory is limited to the N most recent turns (configurable, default: 10 turns) with adaptive summarization upon cap overflow.

---

## 6. Persistent Memory Tier (Long-Term Storage)

The Persistent Tier anchors long-term knowledge across five distinct scope boundaries:

```
+-------------------------------------------------------------------------------+
|                            PERSISTENT MEMORY TIER                             |
+-------------------+---------------------------------+-------------------------+
| Scope             | Visibility / Access Boundary    | Storage Engine          |
+-------------------+---------------------------------+-------------------------+
| Personal Memory   | Single User (Cross-Project)     | Encypted User Store     |
| Project Memory    | Single Project Boundary         | Isolated Project DB     |
| System Memory     | System-Wide Core Rules          | Kernel System Store     |
| Organizational    | Multi-User Organization Scope   | Enterprise Policy Store |
| Shared Memory     | Explicitly Exported Cross-Proj  | Knowledge Exchange Bus  |
+-------------------+---------------------------------+-------------------------+
```

---

## 7. Conflict Resolution & Contradiction Handling

When new input contradicts existing memory nodes (e.g., Goal A: "Target Python 3.9" vs Goal B: "Target Python 3.11"), AME applies a **4-Step Conflict Resolution Algorithm**:

```
                     +-----------------------------------+
                     |      New Memory Candidate        |
                     +-----------------------------------+
                                       |
                                       v
                     +-----------------------------------+
                     |   Contradiction Detector (IUE)    |
                     +-----------------------------------+
                                       |
                   +-------------------+-------------------+
                   | Direct Contradiction Detected?        |
                   +-------------------+-------------------+
                                       |
                      +----------------+----------------+
                      | Yes                             | No
                      v                                 v
   +-----------------------------------+     +---------------------+
   | Check Confidence & Source Delta   |     | Normal Persist Path |
   +-----------------------------------+     +---------------------+
                      |
      +---------------+---------------+
      | Difference                    | Difference
      | > Threshold (0.3)             | <= Threshold (0.3)
      v                               v
+-----------------------------+ +-----------------------------+
| Auto-Supersede & Version    | | Trigger CDM Clarification   |
| (Mark old as SUPERSEDED)    | | ("Did you mean to update?") |
+-----------------------------+ +-----------------------------+
```

### Rule Guidelines
- **Higher Authority Overrides:** System Policies > User Explicit Constraints > Agent Inferences.
- **Recency Primacy for Preferences:** If source authority is identical, newer preferences update older ones, provided confidence >= 0.8.
- **Version Preserving:** Goals and Decisions are NEVER blindly overwritten; they create a new version lineage (`v1` -> `v2`).

---

## 8. Trust, Confidence & Provenance Model

Every memory node contains mandatory metadata attributes for quality governance:

```json
{
  "node_id": "mem_fact_8f92a1",
  "category": "FACT",
  "key": "python_version",
  "value": "3.10.12",
  "confidence": 0.95,
  "source": "system_environment_inspection",
  "provenance": {
    "session_id": "sess_2026_08_07_001",
    "step_id": "step_inspect_env",
    "agent_id": "agent_local_diagnostics"
  },
  "validation_status": "VALIDATED",
  "last_confirmation": "2026-08-07T08:30:00Z",
  "last_usage": "2026-08-07T09:15:00Z",
  "importance": 0.8,
  "volatility": 0.2,
  "version": 1
}
```

### Attribute Specifications
- **`confidence` (0.0 – 1.0):** Certainty score derived from source reliability and extraction quality.
- **`importance` (0.0 – 1.0):** Priority weight for context inclusion during token-constrained reasoning.
- **`volatility` (0.0 – 1.0):** Expected rate of decay (0.0 = static/permanent fact, 1.0 = highly transient).

---

## 9. Forgetting & Decay Mechanics

To prevent context pollution and memory explosion, AME implements an **Adaptive Exponential Decay Model**:

$$\text{Relevance}(t) = \text{Importance} \times e^{-\lambda \times \text{Volatility} \times (t - t_{\text{last\_used}})}$$

```
Relevance Score
1.0 |-------------------\
    |                    \   Active Memory Zone
0.7 |---------------------\----------------------- (Retention Threshold)
    |                      \  Decay / Soft Archive Zone
0.3 |-----------------------\--------------------- (Eviction Threshold)
    |                        \ Forgotten Zone
0.0 +-----------------------------------------------> Time
```

### Eviction Policies
- **Relevance < 0.3:** Node is removed from active search indexes and moved to `FORGOTTEN` / `ARCHIVED`.
- **Pinned Nodes:** Nodes with `volatility = 0.0` or explicit `pinned = true` flag are exempt from decay.

---

## 10. Project Memory Isolation Protocol

Project isolation is enforced at the **storage, query, and context injection boundaries**.

```
+-------------------------------------------------------------------------------+
|                          PROJECT MEMORY ISOLATION                             |
+-------------------------------------------------------------------------------+
|                                                                               |
|   +-----------------------+                       +-----------------------+   |
|   |   Project: IntentOS   |                       |     Project: Atlas    |   |
|   |  +-----------------+  |   STRICT ISOLATION    |  +-----------------+  |   |
|   |  | Memory Store A  |  | <===================> |  | Memory Store B  |  |   |
|   |  +-----------------+  |   Zero Cross-Read     |  +-----------------+  |   |
|   +-----------------------+                       +-----------------------+   |
|               \                                               /               |
|                \                                             /                |
|                 +-------------------------------------------+                 |
|                 | Shared Memory Bus (Explicit Export Only)  |                 |
|                 +-------------------------------------------+                 |
+-------------------------------------------------------------------------------+
```

### Isolation Rules
1. Every query from IUE, CPE, CDM, COR, or ECC MUST include a validated `project_id`.
2. Storage adapters append `WHERE project_id = :project_id` to all database/index operations.
3. Attempting to query across project boundaries without an explicit multi-project token raises `MemoryAccessViolationError`.

---

## 11. Shared Memory & Knowledge Transfer Protocol

Controlled cross-project sharing is permitted **only via explicit export contracts**:

```
  +--------------------+                     +--------------------+
  | Source Project     |                     | Target Project     |
  | (e.g. Intent OS)   |                     | (e.g. OEM Studio)  |
  +--------------------+                     +--------------------+
            |                                          ^
            | 1. Export Request (Select Node)          |
            v                                          |
  +------------------------------------------------+   |
  | Shared Knowledge Exchange Gateway              |   |
  | - Anonymization & PII Scrubbing                |   |
  | - Security & Consent Verification              |   |
  | - Version Linkage Creation                     |   |
  +------------------------------------------------+   |
            |                                          |
            +------------------------------------------+
                     2. Import & Adapt Node
```

---

## 12. Memory Versioning System

Structural memory entities (`GOAL`, `DECISION`, `PROJECT`, `POLICY`) maintain an immutable lineage tree:

```
  +--------------------+       Superseded By       +--------------------+
  |  Goal Node v1      | ------------------------> |  Goal Node v2      |
  |  id: goal_101_v1   |                           |  id: goal_101_v2   |
  |  status: SUPERSEDED|                           |  status: ACTIVE    |
  +--------------------+                           +--------------------+
            ^                                                |
            | Ancestral Lineage                              v
            +------------------------------------------------+
```

---

## 13. Governance & Access Control Matrix

Permissions across memory operations are restricted by actor role:

```
+-------------------------------------------------------------------------------+
|                         GOVERNANCE ACCESS MATRIX                              |
+-------------------+--------+--------+--------+--------+-------+---------------+
| Actor             | Read   | Create | Update | Delete | Purge | Override Conf |
+-------------------+--------+--------+--------+--------+-------+---------------+
| User (Owner)      | YES    | YES    | YES    | YES    | YES   | YES           |
| Constitution      | AUDIT  | NO     | NO     | BLOCK  | BLOCK | NO            |
| ECC               | YES    | YES    | YES    | ARCHIVE| NO    | YES           |
| AME (Internal)    | YES    | AUTO   | AUTO   | DECAY  | NO    | AUTO          |
| CLE (Learner)     | READ   | PROPOSE| PROPOSE| NO     | NO    | NO            |
| External Agents   | SCOPED | NO     | NO     | NO     | NO    | NO            |
+-------------------+--------+--------+--------+--------+-------+---------------+
```

---

## 14. Privacy & Visibility Levels

1. **PRIVATE:** Visible only to the creating user; never used in shared contexts or telemetry.
2. **PROJECT:** Visible to all operations within a specific project.
3. **ORGANIZATION:** Visible across projects belonging to the same organization.
4. **PUBLIC:** Open reference knowledge (e.g., standard API specifications).
5. **TEMPORARY:** Volatile execution state auto-deleted at session end.

---

## 15. Pipeline Integration — Executive Cognitive Controller (ECC)

```
 [ User Intent Input ]
           |
           v
+--------------------+      Queries Memory Context      +--------------------+
|  Pipeline Core     | ==============================> | Adaptive Memory    |
|  (IUE / CPE)       | <==============================  | Engine (AME)       |
+--------------------+      Returns Ranked Context      +--------------------+
           |
           v
+--------------------+
| Executive Cognitive| ----> Evaluates Quality, Governance & Memory Consistency
| Controller (ECC)   |
+--------------------+
```

---

## 16. Pipeline Integration — Intent Understanding Engine (IUE)

- **Input:** Raw user intent + active session context.
- **AME Query:** Fetches user preferences, domain facts, and active project goals.
- **Impact on IQI:** High contextual match increases Intent Quality Index (IQI) by clarifying ambiguous terms without requesting user input.

---

## 17. Pipeline Integration — Cognitive Dialogue Manager (CDM)

- **Redundancy Prevention:** CDM queries AME before generating candidate questions.
- **Rule:** If a fact or preference already exists in AME with `confidence >= 0.8`, CDM suppression logic drops candidate questions asking for that same information.

---

## 18. Pipeline Integration — Cognitive Planning Engine (CPE)

- **Plan Constraints:** CPE queries AME for `CONSTRAINT`, `POLICY`, and `DECISION` nodes.
- **Impact:** Automatically injects project-specific limits (e.g., "Do not use external APIs") into plan step candidate generation.

---

## 19. Pipeline Integration — Capability Orchestrator (COR)

- **Agent Routing:** COR queries AME for historical agent performance and latency scores stored in `LEARNED_BEHAVIOR`.
- **Impact:** Prefers agents/environments with higher historical reliability for specific capability requests.

---

## 20. Cognitive Learning Engine (CLE) Future Readiness

AME prepares structural interfaces for the future Cognitive Learning Engine (CLE):
- **Observation Hooks:** AME exposes read-only execution logs for CLE pattern extraction.
- **Proposal Queue:** CLE writes learning recommendations to an `AME_PROPOSAL` queue for ECC/User approval before promoting to `LEARNED_BEHAVIOR`.

---

## 21. Architectural Textual ASCII Diagrams

### Comprehensive Cognitive Memory Pipeline Flow
```
 +-----------------------------------------------------------------------------+
 |                         INTENT OS COGNITIVE PIPELINE                        |
 +-----------------------------------------------------------------------------+
        |                                                               
        v                                                               
 +--------------+       Query Preferences & Facts      +-----------------------+
 |  IUE Phase   | ===================================> |                       |
 +--------------+ <=================================== |                       |
        |               Enriched Intent & IQI          |                       |
        v                                              |                       |
 +--------------+       Suppress Known Questions       |                       |
 |  CDM Phase   | ===================================> |                       |
 +--------------+ <=================================== |                       |
        |               Unambiguous State              |    ADAPTIVE MEMORY    |
        v                                              |      ENGINE (AME)     |
 +--------------+       Fetch Project Constraints      |                       |
 |  CPE Phase   | ===================================> |  - Temp Memory Tier   |
 +--------------+ <=================================== |  - Persistent Tier    |
        |               Constrained Plan               |  - Project Isolator   |
        v                                              |                       |
 +--------------+       Fetch Agent Latencies & Quotas |                       |
 |  COR Phase   | ===================================> |                       |
 +--------------+ <=================================== |                       |
        |               Assigned Execution Graph       |                       |
        v                                              |                       |
 +--------------+       Validate Against Policies      |                       |
 |  ECC Phase   | ===================================> |                       |
 +--------------+ <=================================== |                       |
        |               Approved Execution             +-----------------------+
        v                                                       ^
 +--------------+                                               |
 | Execution    | ----------------------------------------------+
 | & Feedback   |            Persist New Facts & Events
 +--------------+
```

---

## 22. Risk Matrix & Mitigations

```
+-------------------------------------------------------------------------------+
|                           RISK MATRIX & MITIGATIONS                           |
+----------------------+------------+----------+--------------------------------+
| Identified Risk      | Severity   | Likelihood| Architectural Mitigation       |
+----------------------+------------+----------+--------------------------------+
| Cross-Project Leak   | CRITICAL   | LOW      | Hard SQL/Index isolation boundary|
| Memory Explosion     | HIGH       | HIGH     | Exponential decay & archiving  |
| Stale/Inaccurate Fact| HIGH       | MEDIUM   | Confidence decay & recency rule|
| Contradictory Goals  | MEDIUM     | HIGH     | Version lineage & CDM gates    |
| Token Overflow Bloat | HIGH       | MEDIUM   | Top-K importance context filter|
+----------------------+------------+----------+--------------------------------+
```

---

## 23. Paradigm Comparison

```
+---------------------------------------------------------------------------------------+
|                                  PARADIGM COMPARISON                                  |
+------------------------+------------------+------------------+------------------------+
| Feature / Dimension    | Traditional Chat | Vector-Only RAG  | Adaptive Memory Engine |
+------------------------+------------------+------------------+------------------------+
| Structure              | Unstructured Text| Unstructured Vec | Taxonomical Multi-Layer|
| Conflict Handling      | None (Appends)   | Similarity Only  | Contradiction & Version|
| Project Isolation      | Manual Prompting | Index Isolation  | Kernel Enforced Wall   |
| Governance & Decay     | Manual Truncation| None (Static)    | Exponential Decay      |
| Pipeline Integration   | Passive Buffer   | Retrieval Hook   | Active Cognitive Loop  |
+------------------------+------------------+------------------+------------------------+
```

---

## 24. Readiness & Next Steps for RFC-0012

This architecture design document establishes the complete conceptual and structural foundation for AME. Implementation will proceed under **RFC-0012 (Adaptive Memory Engine Implementation)** without requiring revisions to fundamental memory paradigms.

---
*End of Architectural Design Document*
