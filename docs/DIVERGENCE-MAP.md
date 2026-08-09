# Divergence Map — Python vs RFC-0003 v3 + TS Canonical

**Author:** Dali
**Date:** 2026-07-22
**Reference:** RFC-0003 v3 (Pasteur), TS Canonical Implementation (Pasteur/Klimt)

---

## Summary

My Python implementation covers ~40% of the RFC-0003 v3 spec. The TS implementation covers ~95%. Below is the complete mapping of what's missing, what's different, and what's aligned.

---

## 🔴 CRITICAL — Missing entirely

### C1. Knowledge Score Calculator

**RFC-0003 Section 6:** Score-based decision mechanism with 5 weighted variables.

| Variable | Weight | My Python |
|---|---|---|
| relevance | 0.30 | ❌ Not implemented |
| persistence | 0.25 | ❌ Not implemented |
| reuse | 0.20 | ❌ Not implemented |
| impact | 0.15 | ❌ Not implemented |
| goalAlignment | 0.10 | ❌ Not implemented |

**Thresholds:**
| Score | Level | My Python |
|---|---|---|
| 0-29 | DISCARD | Uses confidence < 0.3 (different signal) |
| 30-69 | CANDIDATE | Uses confidence 0.3-0.6 (different signal) |
| 70-89 | APPROVED | Uses confidence > 0.6 (different signal) |
| 90-100 | CONSTITUTIONAL | ❌ Not implemented |

**Impact:** My Curator classifies by `confidence` (a subjective float), not by `Knowledge Score` (a computed composite). This is a fundamentally different decision mechanism.

### C2. Constitution as Active Gate

**RFC-0003 Section 4.4:** Constitution evaluates every KE before scoring.

```typescript
// TS: 4 active checks
checkSoberania(event)   // privacy/sensitive data detection
checkVerdade(event)     // inference confidence validation
checkContinuidade(event) // EPHEMERAL ≠ CONSTITUTIONAL
checkEvolucao(event)    // observe signals, never block
```

**My Python:**
```python
# Only validates constraint formatting
def validate(self, action):
    for constraint in self.all_constraints:
        if not constraint.id or not constraint.rule:
            return ConstitutionVerdict(allowed=False, ...)
    return ConstitutionVerdict(allowed=True)
```

**Missing checks:**
- `checkSoberania`: Detects sensitive declarations (passwords, CPF, API keys)
- `checkVerdade`: Blocks DECISION with inference confidence < 0.7, flags < 0.5
- `checkContinuidade`: Prevents EPHEMERAL from becoming CONSTITUTIONAL
- `checkEvolucao`: Observes CORRECTION/PATTERN/DECISION signals

### C3. Curator Pipeline

**RFC-0003 Section 7.1:** Full pipeline with Constitution gate → Score → Threshold → Conflict → Action.

```
Detecção → Constitution Gate → Score Calculation → Threshold → Conflict Detection → Action → Audit
```

**My Python:** Simple threshold chain:
```
if confidence < 0.3 → TRANSIENT
if confidence 0.3-0.6 → CANDIDATE
if confidence > 0.6 → APPROVED
```

**Missing steps:**
1. Constitution gate (active validation)
2. Knowledge Score calculation
3. Conflict detection
4. Merge logic
5. Audit logging

### C4. Curator Actions

**RFC-0003 Section 7:** 7 possible actions.

| Action | TS | My Python |
|---|---|---|
| APPROVE | ✅ | ✅ (via lifecycle transition) |
| REJECT | ✅ | ⚠️ (returns TRANSIENT, not explicit REJECT) |
| MERGE | ✅ | ❌ Not implemented |
| ESCALATE | ✅ | ❌ Not implemented |
| EXPIRE | ✅ | ❌ Not implemented |
| DELETE | ✅ | ❌ Not implemented |
| SCORE_RECALC | ✅ | ❌ Not implemented |

### C5. Audit Log

**RFC-0003 Section 11:** Every Curator operation generates an audit entry.

```yaml
audit_entry:
  ke_id: ke-<uuid>
  action: APPROVE | REJECT | MERGE | ESCALATE | EXPIRE | DELETE | SCORE_RECALC
  reason: "string"
  score_at_action: 0-100
  timestamp: <iso8601>
  session_id: <session>
  module: <module_name>
```

**My Python:** No audit log at all.

### C6. Auto-Promote

**RFC-0003 Section 10:** CANDIDATE with 3+ recalculations gets reuse boosted → may cross 70 threshold.

**My Python:** `should_promote()` exists but uses different logic (confidence >= 0.5 or type check).

---

## 🟡 SIGNIFICANT — Different implementation

### D1. Event Types

**RFC-0003:** FACT, PREFERENCE, DECISION, CONTEXT, PATTERN, CORRECTION, EPHEMERAL

**My Python:** DECISION, STRATEGY, FACT, INSIGHT, LESSON, REQUIREMENT, GOAL, MISSION, PARAMETER, RFC, ARCHITECTURE, DOCUMENT, ARTIFACT, PLUGIN, MEMORY, EVENT

**Overlap:** DECISION, FACT
**Missing from mine:** PREFERENCE, CONTEXT, PATTERN, CORRECTION, EPHEMERAL
**Extra in mine:** 10 types not in RFC

### D2. KnowledgeEvent Structure

**RFC-0003 has, my Python lacks:**

| Field | RFC-0003 | My Python |
|---|---|---|
| `score` (KnowledgeScore) | ✅ value + breakdown + recalculations | ❌ |
| `governance.ttl` | ✅ per-domain TTL | ❌ |
| `governance.privacy` | ✅ public/private/sensitive | ❌ |
| `governance.conflictsWith` | ✅ conflict tracking | ❌ |
| `governance.supersededBy` | ✅ version chain | ❌ |
| `content.raw` | ✅ original text | ❌ (uses title/summary) |
| `content.normalized` | ✅ normalized text | ❌ |
| `content.source` | ✅ conversation/inference/correction | ❌ (uses source string) |

**My Python has, RFC-0003 lacks:**

| Field | My Python | RFC-0003 |
|---|---|---|
| `epistemic_status` | ✅ | ❌ (handled by Constitution checkVerdade) |
| `tags` | ✅ | ❌ |
| `root_event_id` | ✅ | ❌ (uses supersededBy) |

### D3. Confidence vs Score

**My Python:** Uses `confidence` (0.0-1.0 float) as the sole decision signal.
**RFC-0003:** Uses `Knowledge Score` (0-100 composite) with `confidence` as one input to the score.

These are different concepts:
- `confidence` = how sure the system is about the data
- `Knowledge Score` = how valuable the data is for long-term retention

---

## ✅ ALIGNED — Working correctly

| Feature | RFC-0003 | My Python | Status |
|---|---|---|---|
| EventLifecycle enum (4 states) | ✅ | ✅ | ✅ |
| Lifecycle transitions | ✅ | ✅ | ✅ |
| Versioning (version, parent_event_id) | ✅ | ✅ | ✅ |
| JsonFileStore persistence | ✅ | ✅ | ✅ |
| QueryFilters | ✅ | ✅ | ✅ |
| Duplicate detection | ✅ (via conflict) | ✅ (via _is_duplicate) | ✅ |
| MEMORY → always Approved | ✅ | ✅ | ✅ |
| Content schemas (Decision, Goal, etc.) | ✅ | ✅ | ✅ |

---

## Migration Plan

### Phase 1 — Knowledge Score (Critical)
1. Add `KnowledgeScoreCalculator` class
2. Add `score` field to `KnowledgeEvent`
3. Update Curator to use score instead of confidence for lifecycle decisions
4. Add thresholds: DISCARD < 30, CANDIDATE 30-69, APPROVED 70-89, CONSTITUTIONAL 90+

### Phase 2 — Constitution Gate (Critical)
1. Add 4 pillar checks: `checkSoberania`, `checkVerdade`, `checkContinuidade`, `checkEvolucao`
2. Add `ConstitutionEvaluate` interface
3. Update `validate()` to return `allowed/blocked/flagged`
4. Add declaration pattern detection for sensitive data

### Phase 3 — Curator Pipeline (High)
1. Add ESCALATE action
2. Add MERGE logic with combined score
3. Add conflict detection
4. Add audit log
5. Add auto-promote for CANDIDATEs

### Phase 4 — Event Model Alignment (Medium)
1. Align EventType enum with RFC-0003 (add PREFERENCE, PATTERN, CORRECTION, EPHEMERAL; keep extras as extensions)
2. Add `governance` field (ttl, privacy, conflictsWith, supersededBy)
3. Add `content.raw` and `content.normalized`

---

## Code Inventory

| Component | TS Lines | Python Lines | Completeness |
|---|---|---|---|
| Types | ~120 | ~180 | 60% (different structure) |
| Constitution | ~110 | ~80 | 20% (missing 4 checks) |
| Knowledge Score | ~40 | 0 | 0% |
| Curator | ~130 | ~70 | 30% (missing pipeline) |
| Knowledge Core/Store | ~60 | ~150 | 70% (different API) |
| Kernel | ~90 | ~120 | 50% (different flow) |
| Tests | 34 | 50 | Different coverage |
