# CORE v1 FREEZE BASELINE — M27.2-P04

**Status:** PROPOSED (awaiting separate integration authorization)
**Prepared:** 2026-10-09
**Scope:** Intent OS governed core; feature-branch freeze reference.

---

## 1. IDENTITY

| Field | Value |
|-------|-------|
| Repository | IntentOS |
| Remote | https://github.com/cics1b252-glitch/IntentOS.git |
| Branch | `architecture/governed-resource-activation-convergence` |
| Frozen HEAD | `7d8fbd766730867043af78aea0769c689ff10b76` |
| Frozen HEAD parent | `66fa6219ab2af95e7747310afe5d0842d6232d31` |
| Remote feature ref | `7d8fbd766730867043af78aea0769c689ff10b76` |
| `main` (local) | `76cdd5cb39b5e0f59d8144907b30373de4e95884` |
| `origin/main` | `76cdd5cb39b5e0f59d8144907b30373de4e95884` |
| Tracked worktree | CLEAN |

**Frozen commit** `7d8fbd7` — `fix(resume): bind durable gate proof and enforce resume integrity (M27.2-P04)` — 6 files:

| File | Status | Lines |
|------|--------|-------|
| `intent_kernel/runtime/mission_runtime.py` | MODIFIED | +356/-30 |
| `intent_kernel/runtime/verification.py` | MODIFIED | +27 |
| `tests/test_m27_2_p04_r4_gate_proof_bridge.py` | ADDED | +550 |
| `tests/test_m27_2_r1_resume_integrity.py` | ADDED | +349 |
| `tests/test_m28_2_resource_evidence.py` | MODIFIED | +6/-2 |
| `tests/test_m29_2_production_external_evidence.py` | MODIFIED | +6/-2 |

---

## 2. FROZEN GOVERNANCE CAPABILITIES

Core is the single source of truth; the Product may present and trigger but never grants, mutates, or bypasses (see Section 9).

| # | Capability | Frozen Core surfaces |
|---|------------|----------------------|
| 1 | Authority & Ceilings | Canonical authority, delegation, ceilings, request binding, exact executor binding |
| 2 | Mission Lifecycle | `MissionRecord`, state machine, revision history, durable state |
| 3 | Delegation & Grants | Grant/revoke, parent-child chains, ceilings, expiry, verification |
| 4 | Execution & Dispatch | Guard, handoff, idempotency, executor binding, verification gates |
| 5 | Request Binding / Exact Digest | `request_semantics_digest`, payload binding |
| 6 | Plan / Intent | Immutable plan, definition digest |
| 7 | Verification / Evidence | `VerificationGate`, `MissionCompletionGate`, proof objects, evidence chain |
| 8 | Evidence / Audit | Canonical `capability.audit` events/logs |
| 9 | Confirmation / Human Decision | `confirmation_basis_digest`, durable requirement, single-use tokens |
| 10 | RRM / Resource Governance | Registration, generation, eligibility, tombstones, retirement |
| 11 | Constitution / Policy | ConstitutionEngine, guardians, verdicts |
| 12 | Identity / Continuity | Installation identity, continuity file, `installation_id` |
| 13 | PKB / Knowledge | Canonical KnowledgePipeline, canonical events |
| 14 | Idempotency / Replay | Durable idempotency keys, `DispatchAttemptSpec`, replay posture |

Governed-agent prohibition (frozen): an agent cannot execute, select provider, select resource, authorize a tool, complete a Mission, mutate lifecycle, or write activation evidence.

---

## 3. AEAC / ISACR AUTHORITY INVARIANTS

**AEAC — Authority-Expansion Adversarial Coverage** (`tests/test_aeac_competitive_coverage.py`):
- `AEAC-SELF-GENERATED-SKILL-AUTHORITY` — a self-generated capability cannot expand executable authority beyond granted scope. Expected: NO AUTHORITY EXPANSION.
- `AEAC-DYNAMIC-SUBAGENT-DELEGATION` — a dynamically created subagent cannot exceed the parent grant. Expected: DENY.

**ISACR — In-System Authority Containment Regime:**

- `ISACR-REV-01` (`test_isacr_rev01_observation.py`): external signal is never sovereign authority.
- `ISACR-REV-02` (finality): POST_REVOCATION_UNAUTHORIZED_EFFECTS == 0 for every authority vector governing effects; caller token is provenance-only (`NOT_APPLICABLE_TO_EFFECT_AUTHORITY`).
- `ISACR-REV-03` (signal-not-authority): `AUTHENTICATED_SIGNAL != AUTHORITY`, `VALID_TOKEN != VALID_AUTHORITY`, `RISK_STATE != AUTHORITY_GRANT`, `EXTERNAL_REVOCATION_SIGNAL != AUTHORITY_GRANT`.

---

## 4. M27.2-R1 AND P04 SECURITY EVIDENCE

**M27.2-R1 — Productive Resume Verification Integrity** — `tests/test_m27_2_r1_resume_integrity.py` (12 tests):
`STALE_EVIDENCE != VERIFIED_SUCCESS`; `CHANGED_CONTRACT != PREVIOUS_VERIFICATION_AUTHORITY`; `AGENT_GENERATED_STATE != TRUSTED_RESUME_EVIDENCE`; `VERIFICATION_EVIDENCE != AUTHORITY_GRANT`; `RESUME != AUTHORIZATION_BYPASS`.

**M27.2-P04-R4 — Durable Gate-Proof Bridge** — `tests/test_m27_2_p04_r4_gate_proof_bridge.py` (13 tests): genuine verification anchors a gate-issued `ActionVerificationProof` through the canonical `RESULT_RECORDED -> VERIFICATION_REQUIRED -> VERIFIED` sequence; an unforgeable in-process gate issuance token is required to mint a proof (caller-fabricated and verification-bypass evidence can never back a proof); the durable proof digest is mirrored into the checkpoint and cross-checked on resume; resume never re-mints or re-dispatches.

Both fixes are load-bearing (ablation proof: with source reverted to `66fa6219`, R1 invariants `a02b`/`a03a`/`a04a`/`a04b` fail and the R4 suite is unimportable).

---

## 5. PASSING ADVERSARIAL / AUTHORITY TEST COUNTS

| Suite | Passed |
|-------|--------|
| AEAC competitive coverage | 2 |
| ISACR-REV-01 / REV-02 / REV-03 | 8 / 16 / 4 |
| J14 adversarial / 2C-R / J14.3 | 4 / 24 / 12 |
| M32B2 action authority / productive dispatch | 70 / 21 |
| M32B1 mission store / restart reconciliation | 31 / 14 |
| M32B4R2 permanent regression | 13 (+2 skip) |
| M27.2-R1 / P04-R4 / exact evidence binding | 12 / 13 / 20 |
| **Authority + adversarial total** | **264 passed / 2 skipped** |

Focused P04 + R1 + M27.2-base gate: **45/45 passed**.

---

## 6. KNOWN HISTORICAL TEST FAILURES

Full relevant regression batch (34 files): **65 failed, 859 passed, 2 skipped**.

### 6.1 Partition (exact node IDs in Appendix A)

| Bucket | Count | Root cause | Nature |
|--------|-------|-----------|--------|
| `test_movement_14_confirmation_resume.py` | 50 | asserts `status == "WAITING_CONFIRMATION"`, actual `"BLOCKED"` | deterministic baseline |
| `test_m28_2_resource_evidence.py` | 13 | `RuntimeError: no current event loop` (Py3.13 `asyncio.get_event_loop()`) | deterministic infra |
| `test_m27_2_reproduction.py` | 2 | pre-fix adversarial proof of the vulnerable behavior | historical red (by design) |
| `TEST_POLLUTION_FLAKY` | **0** | — | none |
| **Total** | **65** | | |

### 6.2 `TEST_POLLUTION_FLAKY` subtotal — RESOLVED (exact node IDs)

Each failing file was re-run in isolation; results are byte-identical to the batch:

- `test_movement_14_confirmation_resume.py`: **50 failed / 25 passed**
- `test_m28_2_resource_evidence.py`: **13 failed / 133 passed**
- `test_m27_2_reproduction.py`: **2 failed**

Therefore **0 of 65 failures are pollution/order-dependent**; corrected partition `50 + 13 + 2 + 0 = 65`. No test cases invented or omitted.

### 6.3 65-failure historical comparison

Prior run `base_all.txt`: **65 failed / 718 passed / 2 skipped**. This baseline: **65 failed / 859 passed / 2 skipped**. The 65 failing node-ID sets are byte-identical (0 added, 0 removed). The pass-count delta (+141) has no retained invocation manifest.

**Status: `NOT_RECONCILABLE_FROM_AVAILABLE_EVIDENCE`.**

---

## 7. EXPLICIT LIMITATIONS AND EXCLUSIONS

- **No real external effects.** All suites use in-memory / JSON-file executors and simulated providers; no network, cloud, or host effect is performed or governed.
- **External signals are provenance-only.** No signal, token, authenticated callback, or risk state grants authority (ISACR-REV-01/03).
- **Provider effect identity is opaque** (digest only).
- **Gate issuance token is in-process.** A forged on-disk record carries a digest but cannot reconstitute the token; resume validates by digest binding, not token presence.
- **Movement-14 confirmation-resume divergence.** 50 red tests expect `WAITING_CONFIRMATION`; runtime yields `BLOCKED`. Known baseline divergence, not fixed in this freeze.
- **Python 3.13 asyncio sensitivity.** 13 m28_2 failures are environment-induced, not governance failures.
- **Historical red reproduction.** `test_m27_2_reproduction.py` preserved and must remain unstaged.

---

## 8. RSA / AWS APPLICABILITY FINDINGS

- **RSA — NOT APPLICABLE as a governed authority surface.** The core performs no RSA/crypto operations and holds no key authority. Its only RSA-relevant behavior is secret detection: `intent_kernel/kom.py:153` matches `-----BEGIN (RSA |EC |PGP )?PRIVATE KEY-----`, rejecting such PEM blocks pre-storage with zero leakage to decision reasons/diagnostics/context (`tests/test_ame_hardening.py` tests 04–05).
- **AWS — NOT APPLICABLE as a governed authority surface.** No AWS provider/control-plane integration exists; "AWS" occurs only as inert user content in an epistemic-nature test (`tests/test_ame_hardening.py:324`). Cloud effect governance is out of scope.

---

## 9. PRODUCT ALPHA SEPARATION

Per `PRODUCT_ALPHA_BOUNDARY_SPEC.md`:

- **Core (single source of truth):** authority, delegation, ceilings, request binding, exact executor binding, Mission/Plan state, verification proofs, confirmation binding, RRM, constitution, identity, idempotency.
- **Product** presents, collects input, and triggers; it **cannot mutate** Core state, grants, plans, or evidence.
- Product-facing read surfaces: `ExecutionStatus`, `EvidenceRecord`, completion/status views.

**Rule:** Product Alpha consumes frozen Core contracts; it must not silently expand authority.

---

## 10. REAL-HOST / REAL-EXTERNAL-EFFECT EXCLUSIONS

Out of scope for this freeze: real host effects; AWS or any cloud control-plane effect; RSA/EC/PGP key operations; external network callbacks as authority; interpretation of provider payloads. The frozen guarantees apply to in-process authority only.

---

## 11. CHANGE CONTROL (BASELINE PROTECTION)

- **Rule A — Frozen Core contracts are change-controlled.** No Core contract in Section 2 may change without: (1) a documented security/compatibility reason; (2) focused tests that fail before and pass after; (3) independent review.
- **Rule B — Product Alpha consumes, never expands.** Product may present/collect/trigger; it may not grant, mutate, or bypass Core authority or silently expand scope.
- **Rule C — Additive integration only.** Feature-branch commits are additive and fast-forward-only; never force, rebase, or amend; never stage the historical red test; never mutate `main`.

---

## 12. EVIDENCE MANIFEST

Canonical machine-readable manifest: `docs/CORE_V1_FREEZE_EVIDENCE_MANIFEST.json`.

---

## FINAL VERDICT

**`CORE_V1_FREEZE_BASELINE_PREPARED`**

Produced in the existing development environment. No production code changed; no commit or push performed; `main` untouched.

---

## APPENDIX A — EXACT 65 FAILING NODE IDs

```
test_movement_14_confirmation_resume.py  (50)
  test_A_waiting_confirmation_never_executes
  test_adversarial_phrase_after_completion_never_reexecutes[continue|não|ok|pode executar|sim]
  test_adversarial_phrase_against_cancelled_mission_never_executes[confirmo|continue|ok|pode|sim]
  test_adversarial_phrase_against_expired_confirmation_never_executes[confirmo|continue|ok|sim, mas não agora|sim]
  test_adversarial_phrase_does_not_cross_sessions[cancele|confirmo|continue|não|ok|pode executar|sim, mas não agora|sim]
  test_adversarial_phrase_with_pending_mission_never_executes[cancele|confirmo|continue|depois|não|ok|pode executar|pode|sim, mas não agora|sim|talvez]
  test_B_valid_confirm_resumes_same_mission
  test_C_wrong_token_fails_closed_then_correct_binding_executes_once
  test_D_rejection_never_executes_and_cancels_mission
  test_E_ambiguous_confirmation_never_executes
  test_F_wrong_mission_never_executes
  test_G_replay_never_duplicates_execution
  test_g8_bridge_restart_regression_durable_record_governs_resume
  test_H_binding_replaced_while_waiting_never_executes
  test_I_binding_removed_while_waiting_fails_closed
  test_K_unhealthy_binding_on_resume_fails_closed
  test_L_authorization_revoked_on_resume_never_executes
  test_M_no_provider_invocation_on_resume
  test_N_replaced_tool_binding_cannot_inherit
  test_Q_verified_execution_completes_via_completion_gate
  test_T_confirm_for_completed_mission_never_reexecutes

test_m28_2_resource_evidence.py  (13)
  TestProducerSeparation::test_c3_verification_status_still_computed_by_gate
  TestVerificationGateComposition::test_d1_external_evidence_success
  TestVerificationGateComposition::test_d2_external_evidence_failure_blocks
  TestVerificationGateComposition::test_d3_no_external_evidence_unaffected
  TestVerificationGateComposition::test_d4_all_required_multiple_success
  TestVerificationGateComposition::test_d5_all_required_one_failure_blocks_all
  TestVerificationGateComposition::test_d6_no_adapter_fails_closed
  TestVerificationGateComposition::test_d7_invalid_requirement_contract_failure
  TestVerificationGateComposition::test_d8_evidence_details_contain_external_fields
  TestVerificationGateComposition::test_d9_semantic_and_external_compose
  TestVerificationGateComposition::test_d10_semantic_failure_stops_before_external
  TestAuthorityPreservation::test_g1_no_evidence_for_verified_when_external_fails
  TestAuthorityPreservation::test_g2_success_only_when_all_pass

test_m27_2_reproduction.py  (2)
  TestM27_01Reproduction::test_exact_evidence_lacks_contract_hash
  TestM27_01Reproduction::test_resume_accepts_changed_expected_output
```
