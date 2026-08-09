# Knowledge Object Model (KOM) — Architectural Design Document

**Document Version:** 1.1.0-DESIGN  
**Status:** ARCHITECTURAL SPECIFICATION (APPROVED FOR AME & RFC-0012)  
**Target Component:** `intent_kernel/kom.py` (Future Knowledge Primitive Layer)  
**Classification:** Intent OS Core Architecture Specification  

---

## 1. Formal Definition & Motivation

### What Is a Knowledge Object (KO)?
A **Knowledge Object (KO)** is the primary **canonical semantic unit of knowledge** within Intent OS. It encapsulates structured memory nodes, epistemic classification, version trees, evidence trails, temporal validity, and relational bindings into a single governed cognitive entity.

```
+-------------------------------------------------------------------------------+
|                           KNOWLEDGE OBJECT (KO)                               |
+-------------------------------------------------------------------------------+
|  Identity     : ko_id, canonical_uri, version_id, canonical_name             |
|  Metadata     : Access Scope, Retention Class, Timestamps, Author, Tags       |
|  Epistemics   : Type (FACT, DECISION...), Source Authority, Temporal Bounds  |
|  Quality Vector: Confidence (0-1) | Stability (0-1) | Strategic Value (0-1)   |
|  Content      : Composite Memory Nodes (Owner: this KO)                       |
|  Lineage      : Multi-Parent Version Graph (v1 -> v2 [Branch] -> v3 [Merge])  |
|  Bindings     : Structural DAG Edges & Cyclic Semantic Edges                  |
|  Provenance   : Evidence Pointer Array & Auditable Transformation Lineage     |
+-------------------------------------------------------------------------------+
```

### Distinguishing Memory Nodes and Knowledge Objects
To ensure architectural precision, Intent OS maintains a clear boundary between atomic memory attributes and semantic knowledge objects:

- **Memory Node:** The granular, atomic unit of structured memory (e.g., an individual key-value pair, attribute slot, or parameters tuple like `python_version = "3.10"`). Every Memory Node possesses a single canonical `owner_ko_id`.
- **Knowledge Object:** The canonical semantic unit of knowledge. It is a composite entity that groups related Memory Nodes, defines their epistemic nature, governs their lifecycle, tracks their lineage, and binds them to evidence and semantic relationships.

### Why Isolated Memory Nodes Are Insufficient
Isolated memory nodes suffer from fundamental cognitive limitations when used independently:
1. **Context Fragmentation:** A loose key-value pair lacks knowledge of *why* it was set, *which decision* mandated it, or *which project goal* depends on it.
2. **Brittle Contradiction Handling:** Overwriting a single value destroys ancestral context and prevents auditability or rollback.
3. **No Structural Relational Context:** Isolated nodes cannot represent complex multi-entity dependencies (e.g., "Architecture decision A implements Policy B, constrained by Quota C, and invalidates Decision D").
4. **Token & Index Inefficiency:** Retrieving hundreds of loose memory fragments saturates context windows with redundant metadata rather than coherent semantic units.

### Core Problems Solved by the Knowledge Object Model
- **Semantic Cohesion:** Groups related memory nodes into a single, addressable, version-controlled object.
- **Traceable Provenance & Evidence:** Every statement within a Knowledge Object anchors directly to verifiable evidence (conversations, commit SHAs, RFCs, user confirmations) without storing credentials.
- **Domain & Project Boundary Protection:** Enforces strict multi-tenant isolation at the object level with explicit access scopes.
- **Deterministic Evolutionary Audit:** Tracks how goals, decisions, and architectures evolve over time without data loss.

---

## 2. System Hierarchy & Structural Organization

The Intent OS Knowledge Architecture is organized into a flexible 8-level structural hierarchy where project scoping is optional at the domain level:

```
Level 1: KNOWLEDGE SYSTEM (Global Intent OS Knowledge Base)
   │
   ├── Level 2: DOMAIN (Isolated Knowledge Domains: Intent OS, Atlas, OEM Studio)
   │      │
   │      └── Level 3: [OPTIONAL] PROJECT (Scoped Workspaces: e.g., "Product Alpha", "Kernel Core")
   │             │
   │             └── Level 4: KNOWLEDGE OBJECT (Canonical Semantic Unit: Goal, Decision, Policy)
   │                    │
   │                    ├── Level 5: MEMORY NODES (Granular Atomic Attribute Key-Values, owner_ko_id)
   │                    │
   │                    ├── Level 6: VERSION GRAPH (Multi-Parent Lineage: Ancestors, Branches, Heads)
   │                    │
   │                    ├── Level 7: RELATIONSHIPS (Structural DAG Edges & Semantic Cyclic Edges)
   │                    │
   │                    └── Level 8: LIFECYCLE & RETENTION STATE (Active, Superseded, Archived, Forgotten)
```

### DOMAIN_IDENTITY_INVARIANT
> **Invariant Rule:** A domain possesses a **canonical semantic identity**. No agent, memory, example, or inference process may silently alter this identity. Changing a domain's semantic identity requires an explicit, versioned administrative operation.

Examples of canonical domain identities in Intent OS:
- **`Intent OS` Domain:** System architecture, Kernel decisions, Cognitive Pipeline policies, runtime governance.
- **`Atlas` Domain:** Financial management, investment portfolios, risk models, asset allocation, performance metrics.
- **`OEM Studio` Domain:** Application builder tools, UI generator states, workspace layout configs, deployment profiles.

### Layer Responsibility Matrix

| Hierarchy Level | Scope / Boundary | Primary Governance Actor |
| :--- | :--- | :--- |
| **Knowledge System** | Global system configuration and constitutional bounds | Constitution & System Admin |
| **Domain** | Domain-level isolation (e.g., Intent OS, Atlas, OEM Studio) | System Governor / ECC |
| **Project (Optional)**| Scoped workspace execution boundary (e.g., Kernel Core) | Project Owner / User |
| **Knowledge Object** | Canonical semantic entity (e.g., `DECISION_ARCH_V3`) | AME Engine / Authorized Actor |
| **Memory Node** | Atomic attribute key-value pair inside object (`owner_ko_id`) | AME Internal Index |
| **Version Graph** | Lineage graph tracking object revisions & merges | AME Version Engine |
| **Relationships** | Structural DAG and semantic graph connecting objects | AME Graph Index |
| **Lifecycle State** | State machine governing object visibility/retention | AME Decay & Governance Engine |

---

## 3. Taxonomy of Knowledge Objects

Knowledge Objects are categorized into 15 distinct functional types:

```
+-------------------------------------------------------------------------------+
|                       KNOWLEDGE OBJECT TYPES MATRIX                           |
+-------------------+---------------------------------------+-------------------+
| Type Name         | Description                           | Typical Volatility|
+-------------------+---------------------------------------+-------------------+
| `GOAL`            | Target outcome, objective, or key result| Low - Medium      |
| `DECISION`        | Immutable choice or trade-off made    | Very Low (Static) |
| `PROJECT`         | Project definition & workspace scope  | Very Low (Static) |
| `PERSON`          | User or stakeholder profile           | Low               |
| `ORGANIZATION`    | Company, team, or institution entity  | Very Low          |
| `MISSION`         | Bound execution sprint or milestone   | Medium            |
| `CONVERSATION`    | Dialogue session summary and log      | High (Transient)  |
| `ARCHITECTURE`    | System topology or structural design  | Very Low          |
| `CAPABILITY`      | Available tool, provider, or agent skill| Low               |
| `CONSTRAINT`      | Non-negotiable limit or quota         | Low               |
| `POLICY`          | Regulatory, constitutional, or safety rule| Very Low      |
| `ASSET`           | Document, artifact, code repo, or image| Medium            |
| `EVENT`           | Immutable temporal milestone or failure| Very Low (Logged) |
| `RELATIONSHIP`    | First-class explicit graph mapping    | Medium            |
| `SKILL`           | Validated operational playbook/routine| Low               |
+-------------------+---------------------------------------+-------------------+
```

---

## 4. Internal Structure & Identity Model

### Identity Attribute Separation
To prevent identity corruption when human-readable titles change, identity is split into 4 distinct fields:
- **`ko_id`:** Immutable system-generated internal identifier (e.g., `ko_dec_8f92a14b`).
- **`canonical_uri`:** Semantic location address (e.g., `ko://intentos/kernel/decision/dec_rfc0011_1`).
- **`version_id`:** Immutable revision tag (e.g., `v2.0.0`).
- **`canonical_name`:** Mutable human-readable title (e.g., "RFC-0011.1 Stabilization Policy").

### Typed JSON Schema

```json
{
  "identity": {
    "ko_id": "ko_dec_8f92a14b",
    "canonical_uri": "ko://intentos/kernel/decision/dec_rfc0011_1",
    "version_id": "v2.0.0",
    "canonical_name": "RFC-0011.1 Architecture Stabilization & Environment Policy"
  },
  "metadata": {
    "domain_id": "domain_intentos",
    "project_id": "proj_kernel_core",
    "access_scope": "PROJECT",
    "retention_class": "PERMANENT",
    "created_at": "2026-08-07T15:28:00Z",
    "updated_at": "2026-08-07T15:34:00Z",
    "author": {
      "type": "USER",
      "id": "user_primary_owner"
    },
    "tags": ["architecture", "stabilization", "rfc0011_1", "cor_policy"]
  },
  "epistemics": {
    "epistemic_type": "DECISION",
    "source_authority": 0.95,
    "valid_from": "2026-08-07T15:28:00Z",
    "valid_until": null,
    "observed_at": "2026-08-07T15:28:00Z"
  },
  "quality_vector": {
    "confidence": 0.98,
    "stability": 0.95,
    "strategic_value": 0.90,
    "lifecycle_stage": "ACTIVE",
    "pinned": true,
    "cognitive_context_eligible": true
  },
  "content": {
    "summary": "Stabilized execution environment policies and registry behavior for empty catalog fallback.",
    "attributes": {
      "empty_registry_action": "NO_ENVIRONMENT_AVAILABLE",
      "implicit_catalog_population": false,
      "assignment_policy": "STRICT_MATCH_OR_BLOCK"
    },
    "memory_nodes": [
      {
        "node_id": "mem_node_cor_registry_001",
        "owner_ko_id": "ko_dec_8f92a14b",
        "key": "empty_registry_action",
        "value": "NO_ENVIRONMENT_AVAILABLE"
      }
    ]
  },
  "version_graph": {
    "current_version": "v2.0.0",
    "parent_versions": ["v1.0.0"],
    "branches": [],
    "ancestral_chain": ["v1.0.0"]
  },
  "relationships": [
    {
      "edge_type": "implements",
      "target_uri": "ko://intentos/kernel/architecture/arch_rfc0011",
      "weight": 1.0
    },
    {
      "edge_type": "supersedes",
      "target_uri": "ko://intentos/kernel/decision/dec_rfc0011_legacy_env",
      "weight": 1.0
    }
  ],
  "evidence": [
    {
      "evidence_id": "ev_doc_rfc0011_1",
      "source_type": "FILE",
      "reference": "docs/RFC-0011-1-ARCHITECTURE-STABILIZATION.md",
      "verification_signature_reference": "sig_sha256_e3b0c44298fc1c149afb",
      "confirmation_id": "conf_usr_20260807_01"
    }
  ]
}
```

---

## 5. Epistemic Nature, Temporal Validity & Stability

### Epistemic Classification (`epistemic_type`)
Every Knowledge Object or Memory Node MUST explicitly specify its epistemic nature:
- **`FACT`:** Verifiable objective statement confirmed by direct system observation or authoritative user input.
- **`ASSERTION`:** Unverified claim submitted by an actor awaiting confirmation.
- **`INFERENCE`:** Derived conclusion generated by Cognitive Pipeline agents (e.g., CLE, IUE).
- **`ASSUMPTION`:** Temporary working premise accepted for plan generation under uncertainty.
- **`DECISION`:** Explicit selection among alternatives by an authorized actor.
- **`PREFERENCE`:** Subjective user choice or stylistic constraint.
- **`POLICY`:** Non-negotiable system or governance rule.
- **`OBSERVATION`:** Raw, unanalyzed system or execution output.
- **`PREDICTION`:** Forecast of future state or behavior.

> **Epistemic Promotion Invariant:** An `INFERENCE` or `ASSUMPTION` MUST NEVER be silently promoted to a `FACT`. Promotion requires explicit validation or authoritative user confirmation.

### Source Authority vs. Confidence
- **`confidence` ($C \in [0, 1]$):** Epistemic probability that the statement is factually true.
- **`source_authority` ($A \in [0, 1]$):** Weight of trust assigned to the originating source:
  - *Direct Explicit User Statement:* $A = 1.0$ for personal preference.
  - *System Code / Official Spec:* $A = 0.95$ for documented technical behavior.
  - *Agent Inference / CLE:* $A = 0.60$ (requires verification for high-impact mutations).
  - *External Web Source:* Variable ($A \in [0.2, 0.7]$) depending on domain reputation.

### Temporal Validity vs. Logical Contradiction
To distinguish historical changes from logical contradictions, Knowledge Objects record temporal validity boundaries:
- **`valid_from`:** Timestamp when the knowledge becomes active.
- **`valid_until`:** Timestamp when the knowledge ceases to be valid (null if open-ended).
- **`observed_at`:** Timestamp when the knowledge was recorded.

> **Temporal Succession Rule:** If Fact A ("Default Provider is Gemini") has `valid_until = 2026-01-01` and Fact B ("Default Provider is Claude") has `valid_from = 2026-01-01`, this represents **Temporal Succession**, NOT a contradiction. The system maintains both in historical lineage without triggering a contradiction alert.

### Stability vs. Confidence Matrix
`Stability` ($S \in [0, 1]$) measures resistance to decay or state fluctuation over time, independent of `Confidence`:

| Entity Example | Confidence ($C$) | Stability ($S$) | Architectural Behavior |
| :--- | :--- | :--- | :--- |
| **User Name / Date of Birth** | High ($0.99$) | High ($0.99$) | Static fact; exempt from decay. |
| **Active Architectural Decision** | High ($0.98$) | Medium ($0.80$) | Stable until explicit version update. |
| **Provider Operational Status** | High ($0.95$) | Low ($0.20$) | Rapid decay; requires frequent re-validation. |
| **Market Trend Inference** | Variable ($0.50$) | Low ($0.10$) | Volatile forecast; auto-expires quickly. |

### Multi-Factor Strategic Value
`Strategic Value` ($V \in [0, 1]$) is NOT derived merely from graph edge density. It is computed from:
1. **Explicit User Priority Designation:** User-pinned or flagged core goals.
2. **Goal Criticality:** Alignment with active top-level project goals.
3. **Impact on Downstream Decisions:** Number of dependent decisions and policies.
4. **Architectural & Compliance Risk:** Safety or constitutional impact if violated.

Rarely queried Knowledge Objects (e.g., an emergency rollback policy) retain high `Strategic Value` and are protected against eviction despite low access frequency.

---

## 6. Graph Rules & Topology

Knowledge Objects form a **Scoped Hybrid Graph** governed by strict edge type constraints:

```
                      +-----------------------------+
                      |  KO: ARCHITECTURE_V3        |
                      +-----------------------------+
                              ^             ^
                 implements   |             |   implements
               (DAG Edge)     |             | (DAG Edge)
              +---------------+             +---------------+
              |                                             |
   +--------------------------+                   +--------------------------+
   | KO: DECISION_RFC0011     | <---------------- | KO: DECISION_RFC0006     |
   +--------------------------+    contradicts    +--------------------------+
              ^                  (Semantic Edge)            ^
              | supersedes                                  | depends_on
              | (DAG Edge)                                  | (DAG Edge)
   +--------------------------+                   +--------------------------+
   | KO: DECISION_RFC0011_1   |                   | KO: GATEWAY_TRANSPORT    |
   +--------------------------+                   +--------------------------+
```

### Relationship Edge Classification

1. **Structural Edges (Strict DAG - Acyclic Enforced):**
   - `depends_on`, `implements`, `extends`, `supersedes`, `belongs_to`, `successor`, `ancestor`.
   - **Enforcement:** Cyclic dependencies in structural edges are strictly forbidden. The AME Graph Index performs cycle detection during `LINK` operations and rejects cyclic structural edge requests.

2. **Semantic Edges (Cyclic Permitted):**
   - `related_to`, `references`, `supports`, `contradicts`.
   - **Enforcement:** Semantic edges may form cycles (e.g., KO A `contradicts` KO B while KO B `references` KO A). `contradicts` edges freeze automated promotion until resolved.

---

## 7. Version Graph & Restore Mechanics

Knowledge Objects maintain a **Multi-Parent Directed Version Graph** for lineage tracking, branching, merging, and non-destructive restoration:

```
                   +-----------------------+
                   | Goal v1.0.0 (Base)    |
                   +-----------------------+
                               |
            +------------------+------------------+
            | Branch A                            | Branch B
            v                                     v
+-----------------------+             +-----------------------+
| Goal v1.1.0-A         |             | Goal v1.1.0-B         |
| (Target Python 3.10)  |             | (Target Python 3.11)  |
+-----------------------+             +-----------------------+
            |                                     |
            +------------------+------------------+
                               |
                               | MERGE Operation
                               v
                   +-----------------------+
                   | Goal v2.0.0 (Canonical|
                   | Target Python 3.10    |
                   | + Dual Support)       |
                   +-----------------------+
```

### Restore Mechanics Invariant
> **Non-Destructive Restore Rule:** Executing a `RESTORE` operation to roll back a Knowledge Object to an ancestral version (e.g., restoring `v1.0.0`) **MUST NOT** delete or overwrite subsequent version nodes (`v1.1.0`, `v2.0.0`). Instead, `RESTORE` creates a **new HEAD version** (e.g., `v3.0.0`) whose content mirrors `v1.0.0` while recording `v2.0.0` and `v1.0.0` in its ancestral graph lineage.

---

## 8. Evidence Security & Secret Reference Model

### Evidence vs. Provenance Distinction
- **Evidence:** The specific non-secret artifact or verification reference supporting a claim (e.g., document file hash, test execution log ID, explicit UI confirmation ID).
- **Provenance:** The auditable processing chain explaining how the knowledge originated and transformed across system components (e.g., `User Dialogue -> IUE Extraction -> CLE Refinement -> ECC Approval -> AME Store`).

### Evidence Security Invariant
> **Zero-Secret Evidence Rule:** Evidence records **MUST NEVER** store raw credentials, authentication tokens, API keys, passwords, bearer tokens, or OAuth secrets. Evidence points exclusively to proof references.

```
+-------------------------------------------------------------------------------+
|                       SECURE EVIDENCE REFERENCE MATRIX                        |
+-------------------+-----------------------------------+-----------------------+
| Evidence Type     | Allowed Reference Pointer         | Integrity / Proof Marker|
+-------------------+-----------------------------------+-----------------------+
| `CONVERSATION`    | `session_id:turn_number`          | Timestamp + Message ID|
| `DOCUMENT`        | `docs/RFC-0011.md`                | SHA-256 Content Hash  |
| `GIT_COMMIT`      | `commit_sha: 31921f1`             | Commit Signature      |
| `EXECUTION_LOG`   | `logs/intent-flow.jsonl:line_142` | Trace ID / Execution ID|
| `USER_ACTION`     | `confirmation_id: conf_usr_8f9`   | Actor Reference       |
+-------------------+-----------------------------------+-----------------------+
```

### External Secret Reference Model
If a Knowledge Object references an external integration requiring authentication, it MUST store a non-secret URI pointing to an external Secret Manager:

```json
{
  "secret_reference": "secret://provider/account/primary_stripe_key",
  "secret_provider": "GCP_SECRET_MANAGER"
}
```
*Plain-text keys (e.g., `sk_live_...` or `AIza...`) are strictly forbidden inside the Knowledge Object Model.*

---

## 9. Governance, Authority Matrix & Authorization Pipeline

### Memory Intent Authorization Pipeline
All operations attempting to create, mutate, or retire Knowledge Objects MUST execute through the formal authorization pipeline:

```
[ Actor Request ]
       │
       v
[ Requested Memory Intent ]
       │
       v
[ Scope & Ownership Check ]
       │
       v
[ Constitution / Policy Verdict ] (ALLOW / BLOCK / AUDIT)
       │
       v
[ AME Execution Engine ]
       │
       v
[ Security Audit Event Log ]
```

No Cognitive Pipeline component (IUE, CDM, CPE, COR, CLE) or external agent may directly alter Knowledge Objects in storage without passing through this pipeline.

### Governance Roles & Responsibilities
- **User:** Primary owner of personal and project knowledge. Possesses final override authority over user-scoped knowledge.
- **Constitution:** Enforces constitutional rules, privacy policies, and safety invariants. Returns `ALLOW`, `BLOCK`, or `AUDIT` verdicts. Does NOT inject arbitrary user memory.
- **ECC (Executive Cognitive Controller):** Supervises execution flow and approves/rejects Memory Intent proposals based on policy. Does NOT act as direct storage owner.
- **AME (Adaptive Memory Engine):** Executes authorized Memory Intents and manages physical storage, indexing, and decay.
- **CLE (Cognitive Learning Engine):** Observes execution outcomes and issues `PROPOSE` requests for new or merged knowledge. Has NO direct write authority.

### Operations Authority Matrix

| Memory Intent | User | Constitution | ECC | AME | IUE / CDM / CPE / COR | CLE | External Agents |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`STORE`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | PROPOSE | PROPOSE | PROPOSE |
| **`UPDATE`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | PROPOSE | PROPOSE | NO |
| **`MERGE`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | PROPOSE | NO |
| **`SPLIT`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | PROPOSE | NO |
| **`ARCHIVE`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | NO | NO |
| **`FORGET`** | YES | AUDIT / BLOCK | NO | AUTO (Decay)| NO | NO | NO |
| **`PIN / UNPIN`**| YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | NO | NO |
| **`LINK / UNLINK`**| YES| AUDIT / BLOCK | APPROVE | EXECUTE | PROPOSE | PROPOSE | NO |
| **`VERSION`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | NO | NO |
| **`RESTORE`** | YES | AUDIT / BLOCK | APPROVE | EXECUTE | NO | NO | NO |
| **`DELETE`** | YES | AUDIT / BLOCK | NO | EXECUTE | NO | NO | NO |

---

## 10. Deletion Semantics & User Deletion Authority

### Formal Lifecycle Deletion Mechanics

```
                  +-----------------------------------+
                  |      ACTIVE KNOWLEDGE OBJECT      |
                  +-----------------------------------+
                     /              |              \
                    /               |               \
                   /                |                \
                  v                 v                 v
        +------------------+ +-----------------+ +-------------------+
        |     ARCHIVE      | |     FORGET      | |      DELETE       |
        +------------------+ +-----------------+ +-------------------+
        | Soft-retired from| | Unlinked from   | | Permanent physical|
        | cognitive context| | pipeline search | | destruction from  |
        | Preserved in cold| | via decay.      | | database & logs.  |
        | historical store.| | Preserved in DB.| | (Irreversible)  |
        +------------------+ +-----------------+ +-------------------+
```

1. **`ARCHIVE`:** Object is removed from `cognitive_context_eligible` status. It is preserved in cold store for lineage and historical audit but is not retrieved during standard pipeline execution.
2. **`FORGET`:** Triggered by exponential decay or relevance drop below threshold. The object is unindexed from active search graphs. It remains in physical storage for potential historical audit unless purged.
3. **`DELETE`:** Complete, permanent, physical erasure of the object, its memory nodes, and derivative search indices from disk. Used for user privacy requests (GDPR) or explicit deletion commands. `FORGET` MUST NEVER be used as a synonym for `DELETE`.

### Handling User Deletion Requests
When a user issues a deletion directive ("Esqueça isso", "Apague tudo que sabe sobre X", "Remova este projeto"), the system processes the request through a 4-tier evaluation:

1. **Scope Identification:** Map target concepts to specific `ko_id` or `project_id` boundaries.
2. **Retention Policy Audit:** Check if any target Knowledge Objects are bound by non-deletable system policies or mandatory compliance audit rules.
3. **Execution Choice:**
   - *If no compliance block exists:* Execute physical `DELETE` across primary stores, memory node indexes, and derived vector caches.
   - *If compliance/audit policy requires retention:* Shift object status to `ARCHIVE` with `cognitive_context_eligible = false` and inform the user of the retention requirement.
4. **Cascade Clean-up:** Dissolve or flag relationship edges pointing to the deleted object.

---

## 11. Cross-Domain Sharing Protocol

Cross-domain knowledge transfer is **DENY-BY-DEFAULT**. Domain boundaries act as non-porous namespaces.

```
+-------------------------------------------------------------------------------+
|                       SHARED KNOWLEDGE GATEWAY PROTOCOL                       |
+-------------------------------------------------------------------------------+
|                                                                               |
|   +-----------------------+                       +-----------------------+   |
|   | Domain: Intent OS     |                       | Domain: Atlas         |   |
|   | - System Architecture |      DENY DEFAULT     | - Investment Portfolio|   |
|   | - ECC Policies        | <===================> | - Asset Allocations   |   |
|   +-----------------------+                       +-----------------------+   |
|               \                                               /               |
|                \                                             /                |
|                 +-------------------------------------------+                 |
|                 | Shared Knowledge Gateway                  |                 |
|                 | - Explicit Contract Verification          |                 |
|                 | - Scope, Purpose & Expiry Binding         |                 |
|                 | - Audit Logging                           |                 |
|                 +-------------------------------------------+                 |
+-------------------------------------------------------------------------------+
```

### Shared Knowledge Contract Requirements
When cross-domain sharing is explicitly granted by an authorized user or system governor, the gateway registers a **Cross-Domain Knowledge Contract**:
```json
{
  "contract_id": "xdc_intentos_to_atlas_001",
  "source_domain": "domain_intentos",
  "target_domain": "domain_atlas",
  "target_ko_uri": "ko://intentos/kernel/policy/pol_rate_limits",
  "purpose": "Enforce financial API rate limits in investment pipeline",
  "scope": "READ_ONLY_ATTRIBUTES",
  "expiry": "2026-12-31T23:59:59Z",
  "provenance_ref": "prov_xdc_auth_user_owner"
}
```

---

## 12. Privacy Scope & Retention Class Separation

To prevent confusion between visibility permissions and storage duration, `access_scope` and `retention_class` are strictly separated:

### Access Scope (`access_scope`)
- **`PRIVATE`:** Accessible solely by the owning user across their sessions.
- **`PROJECT`:** Accessible by all actors and pipeline executions within a specific `project_id`.
- **`ORGANIZATION`:** Accessible across projects within a shared organization boundary.
- **`PUBLIC`:** Open system reference knowledge.

### Retention Class (`retention_class`)
- **`PERMANENT`:** Exempt from automatic decay; requires explicit `ARCHIVE` or `DELETE`.
- **`EPISODIC`:** Subject to standard adaptive exponential decay based on usage and stability.
- **`TEMPORARY`:** Automatically purged or archived at session or mission closure.

---

## 13. Neutral Cognitive Terminology

Intent OS decouples its internal knowledge structures from LLM/Provider execution mechanics. 

- **Deprecated Term:** ~~`Active Prompt Inject`~~
- **Canonical Term:** `COGNITIVE_CONTEXT_ELIGIBLE`

Knowledge Objects marked with `cognitive_context_eligible = true` are eligible for retrieval and inclusion in cognitive pipeline reasoning contexts, regardless of whether the downstream execution uses LLMs, heuristic engines, rule systems, or local solvers.

---

## 14. KNOWLEDGE SECURITY INVARIANTS

The Knowledge Object Model enforces 10 non-negotiable security invariants across all operations:

```
+-------------------------------------------------------------------------------+
|                         KNOWLEDGE SECURITY INVARIANTS                         |
+-------------------------------------------------------------------------------+
|  1. ZERO SECRETS        : Raw credentials, API keys, and tokens MUST NEVER be|
|                           stored in Knowledge Objects, Memory Nodes or Evidence.|
|  2. DENY CROSS-PROJECT  : Cross-project knowledge access is DENY-BY-DEFAULT.   |
|  3. DENY CROSS-DOMAIN   : Cross-domain knowledge access is DENY-BY-DEFAULT.    |
|  4. NO SILENT PROMOTION : An INFERENCE or ASSUMPTION MUST NEVER silently      |
|                           become a FACT without explicit verification.         |
|  5. DELETED IS DELETED  : Deleted knowledge MUST NOT resurface via derived    |
|                           vector indices, caches, or background graphs.       |
|  6. ARCHIVED IS ISOLATED: Archived knowledge is NOT cognitive_context_eligible|
|                           by default.                                         |
|  7. IMMUTABLE PROVENANCE: Provenance chains CANNOT be silently altered or     |
|                           detached from Knowledge Objects.                    |
|  8. NO AUTO-PROMOTION   : Private user knowledge CANNOT be automatically        |
|                           promoted to shared, project, or public scopes.      |
|  9. AGENTS ARE NOT FINAL: External agents and cognitive modules are NEVER     |
|                           final write authorities for persistent memory.      |
| 10. AUDITABLE MUTATIONS : Every memory mutation MUST produce a tamper-evident |
|                           auditable security event log.                       |
+-------------------------------------------------------------------------------+
```

---

## 15. Cognitive Pipeline Integration (IUE, CDM, CPE, COR, ECC, CLE)

```
+-------------------------------------------------------------------------------+
|                      PIPELINE INTEGRATION INTERACTION                         |
+---------------+---------------------------------------------------------------+
| Engine        | Interaction Pattern with Knowledge Objects                    |
+---------------+---------------------------------------------------------------+
| **IUE**       | Queries `GOAL`, `PREFERENCE`, and `FACT` KOs to boost Intent  |
|               | Quality Index (IQI) and resolve ambiguous user terms.         |
| **CDM**       | Inspects `DECISION` and `FACT` KOs to suppress redundant      |
|               | clarification questions during dialogue management.           |
| **CPE**       | Ingests `CONSTRAINT`, `POLICY`, and `ARCHITECTURE` KOs to     |
|               | construct compliant Plan Step execution graphs.               |
| **COR**       | Reads `CAPABILITY` and `SKILL` KOs to route execution steps    |
|               | to optimal agent runtimes and environments.                   |
| **ECC**       | Evaluates execution proposals against `POLICY` and `DECISION` |
|               | KOs; authorizes `STORE`, `VERSION`, and `MERGE` intents.      |
| **CLE**       | Observes execution outcomes and generates `STORE`/`MERGE`      |
|               | proposals to continuously refine system knowledge.            |
+---------------+---------------------------------------------------------------+
```

---

## 16. Paradigm Comparison Matrix

```
+---------------------------------------------------------------------------------------------------+
|                                    PARADIGM COMPARISON MATRIX                                     |
+----------------------+-------------------+-------------------+------------------+-----------------+
| Architectural Trait  | Relational DB     | Graph DB          | Traditional RAG  | Knowledge Object|
+----------------------+-------------------+-------------------+------------------+-----------------+
| Unit of Storage      | Table Rows        | Nodes & Edges     | Text Chunks      | Knowledge Object|
| Context Cohesion     | Low (Normalized)  | Medium            | Low (Fragmented) | High (Encapsed) |
| Lineage / Versioning | External/Triggers | Manual Schema     | None             | Multi-Parent    |
| Evidence Binding     | Foreign Keys      | Properties        | Source Doc URI   | Multi-Source Sec|
| Quality Metrics      | None              | None              | Similarity Score | Tri-Metric Vector|
| Domain Walls         | Tenant ID         | Graph Sub-queries | Namespace        | Kernel Enforced |
| Epistemic Types      | None              | None              | None             | 9 Epistemic Types|
| Cognitive Operations | SQL CRUD          | Cypher / Gremlin  | Similarity Search| 12 MemoryIntents|
+----------------------+-------------------+-------------------+------------------+-----------------+
```

---

## 17. Consistency Corrections Applied (v1.1.0-DESIGN Review)

During the Studio 7.2 Consistency & Security Review, the following architectural corrections were applied:

1. **Domain Identity Correction:** Fixed `Atlas` domain representation from incorrect "Geo/Navigation" to canonical "Financial Management & Investments". Added `DOMAIN_IDENTITY_INVARIANT`.
2. **Atomicity Definition Refinement:** Corrected description of Knowledge Objects. Defined Memory Nodes as atomic units and Knowledge Objects as canonical semantic units grouping memory nodes.
3. **Evidence Security Hardening:** Purged raw secret/auth token examples from evidence specifications. Introduced `verification_signature_reference` and `confirmation_id`.
4. **Secret Reference Model Formalization:** Added explicit `secret_reference` model pointing to external Secret Managers.
5. **Authority Matrix Overhaul:** Corrected ECC role from storage owner to supervisor/approver. Re-aligned User as owner, Constitution as policy engine, AME as executor, and CLE as proposer.
6. **Authorization Pipeline:** Formalized the 6-step Memory Intent authorization pipeline.
7. **Deletion Semantics Disambiguation:** Formally separated `ARCHIVE`, `FORGET`, and `DELETE`. Specified user deletion authority handling.
8. **Evidence vs. Provenance Separation:** Explicitly distinguished supporting evidence artifacts from origin transformation chains.
9. **Epistemic Classification:** Introduced `epistemic_type` attribute with 9 explicit types and the Epistemic Promotion Invariant.
10. **Source Authority Attribute:** Separated `source_authority` from `confidence`.
11. **Temporal Validity Modeling:** Added `valid_from`, `valid_until`, `observed_at`, and distinguished temporal succession from contradiction.
12. **Stability & Strategic Value Refinement:** Clarified multi-factor strategic value calculation independent of query frequency or graph degree.
13. **Hierarchy Scoping:** Made `project_id` optional under `Domain`.
14. **Cross-Domain Sharing Contract:** Detailed Cross-Domain Knowledge Contract requirements.
15. **Graph Topology Distinction:** Enforced DAG on structural edges while permitting cycles on semantic edges.
16. **Version Restore Mechanics:** Formally specified non-destructive `RESTORE` behavior creating a new HEAD node.
17. **Memory Node Ownership:** Assigned single canonical `owner_ko_id` to each memory node.
18. **Identity Attribute Separation:** Separated `ko_id`, `canonical_uri`, `version_id`, and `canonical_name`.
19. **Privacy Scope vs Retention Class:** Separated access permissions from storage duration.
20. **Cognitive Terminology Neutralization:** Replaced ~~`Active Prompt Inject`~~ with `COGNITIVE_CONTEXT_ELIGIBLE`.
21. **Security Invariants Section:** Added 10 explicit Knowledge Security Invariants.

---

## 18. Readiness & Next Steps for RFC-0012

This **Knowledge Object Model (KOM)** specification (Version 1.1.0-DESIGN) is complete, secure, and architecturally verified. It serves as the official, unyielding design contract for the Adaptive Memory Engine (`intent_kernel/ame.py` and `intent_kernel/kom.py`) implementation in RFC-0012.

---
*End of Knowledge Object Model Design Document (v1.1.0-DESIGN)*
