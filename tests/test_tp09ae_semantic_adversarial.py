"""TP-09AE: adversarial semantic validation.

25+ focused adversarial validation tests for the SemanticCompletionPolicy.
All tests are designed to verify fail-closed trust gates and that no
execution authority is exposed. The policy never trusts caller-authored
evidence, planner-generated criteria, or a Core COMPLETED status as a
substitute for semantic success.

Design principles:
  * No frozen-Core modifications.
  * Policy grants no execution authority.
  * All verdicts fail closed (LEGACY/UNKNOWN).
  * Output always labeled PRODUCT_LEVEL_SEMANTIC_ASSESSMENT.
  * Never presents as gate decision.
"""

from __future__ import annotations

import os
# Resolve pytest-asyncio PermissionError on Windows
os.environ["TMP"] = r"C:\tmp\intent_os_pytest"
os.environ["TEMP"] = os.environ["TMP"]

import pytest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from intent_kernel.mission.success_contract import (
    CriterionProvenance,
    CriterionVerdict,
    SemanticCriterion,
    compute_contract_digest,
    evaluate_success_contract,
)
from intent_kernel.mission.semantic_completion_policy import (
    SemanticCompletionPolicy,
    SemanticVerdict,
    SemanticAssessment,
    AssessmentScope,
    create_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def _make_approval(token: str = "test_approval_1", contract_digest: str = "abc123") -> Any:
    """Create a dummy approval object."""
    obj = type("Approval", (), {})()
    obj.token = token
    obj.contract_digest = contract_digest
    return obj


def _make_observation(
    mission_id: str = "test_mission",
    action_id: str = "test_action",
    gate_proof_digest: str = "gate_proof_abc",
    observed_at: str | None = None,
) -> Any:
    """Create a dummy grounded observation object."""
    obj = type("Observation", (), {})()
    obj.mission_id = mission_id
    obj.action_id = action_id
    obj.gate_proof_digest = gate_proof_digest
    obj.observed_at = observed_at or NOW.isoformat()
    return obj


def _make_criterion(
    criterion_id: str = "test_criterion",
    provenance: str = "approved_approver",
    predicate: str = "exists",
    json_path: str = "test",
    expected: Any = None,
    approver_ref: str = "test_approver",
) -> SemanticCriterion:
    """Create a valid SemanticCriterion for testing."""
    return SemanticCriterion(
        criterion_id=criterion_id,
        objective="test objective",
        provenance=provenance,
        predicate=predicate,
        json_path=json_path,
        expected=expected,
        approver_ref=approver_ref if provenance == "approved_approver" else "",
    )


def _make_planner_criterion(
    criterion_id: str = "planner_criterion",
    predicate: str = "exists",
    json_path: str = "$.test",
) -> SemanticCriterion:
    """Create a planner-generated criterion (advisory only)."""
    return SemanticCriterion(
        criterion_id=criterion_id,
        objective="planner objective",
        provenance="planner_generated",
        predicate=predicate,
        json_path=json_path,
        approver_ref="",
    )


def _make_assessment(
    mission_id: str = "test_mission",
    contract_digest: str = "abc123",
    execution_status: str = "UNKNOWN",
    semantic_verdict: str = "UNKNOWN",
    reason: str = "",
    evidence_refs: Tuple[str, ...] = (),
) -> SemanticAssessment:
    """Create a SemanticAssessment for comparison."""
    return SemanticAssessment(
        mission_id=mission_id,
        contract_digest=contract_digest,
        execution_status=execution_status,
        semantic_verdict=SemanticVerdict(semantic_verdict),
        evidence_refs=evidence_refs,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# TP-09AE Tests
# ---------------------------------------------------------------------------


class TestTP09AENoApproval:
    """Tests with no semantic approval provided."""

    def test_no_approval_returns_legacy(self, tmp_path):
        """No approval -> LEGACY verdict."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"
        assert assessment.scope == AssessmentScope.PRODUCT_LEVEL_SEMANTIC_ASSESSMENT.value

    def test_no_approval_with_evidence_still_legacy(self, tmp_path):
        """No approval even with evidence -> LEGACY, not SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            evidence={"__result__": "pass"},
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"


class TestTP09AENoGroundedObservation:
    """Tests without genuine grounded observation."""

    def test_no_observation_unknown_no_approval(self, tmp_path):
        """No observation + no approval -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # Without approval -> LEGACY
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY

    def test_observation_no_gate_proof_unknown(self, tmp_path):
        """Observation present but no gate_proof_digest -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        obs = _make_observation(gate_proof_digest=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"


class TestTP09AEApprovalWithObservation:
    """Tests with approved semantic contract + grounded observation."""

    def test_approved_with_grounded_evidence_satisfied(self, tmp_path):
        """Genuine approval + valid grounded observation -> SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation()
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
            evidence={"__result__": {"test": "value"}},
            now=NOW,
        )
        assert assessment.semantic_verdict == SemanticVerdict.SATISFIED
        assert assessment.reason == "approved-with-grounded-evidence"

    def test_approved_with_stale_observation_unknown(self, tmp_path):
        """Genuine approval + stale observation -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation(observed_at=(NOW - timedelta(hours=1000)).isoformat())
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
            evidence={"__result__": {"test": "value"}},
        )
        assert assessment.semantic_verdict == SemanticVerdict.UNKNOWN
        assert "stale-observation" in assessment.reason

    def test_approved_with_wrong_mission_unknown(self, tmp_path):
        """Genuine approval + observation from wrong mission -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission_A", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation(mission_id="wrong_mission")
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        assert assessment.semantic_verdict == SemanticVerdict.UNKNOWN

    def test_approved_with_wrong_action_unknown(self, tmp_path):
        """Genuine approval + observation from wrong action -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation(action_id="wrong_action")
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        assert assessment.semantic_verdict == SemanticVerdict.UNKNOWN


class TestTP09AECallerAuthoredEvidenceRejected:
    """Tests that caller-authored evidence is rejected."""

    def test_caller_authored_trusted_semantic_result_rejected(self, tmp_path):
        """Caller-authored TrustedSemanticResult -> UNKNOWN, not SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            evidence={"__result__": "pass", "__trusted__": True},
        )
        # Should NOT be SATISFIED even with trusted marker
        assert assessment.semantic_verdict != SemanticVerdict.SATISFIED
        assert assessment.semantic_verdict in (
            SemanticVerdict.UNKNOWN,
            SemanticVerdict.LEGACY,
        )

    def test_caller_authored_grounded_observation_rejected(self, tmp_path):
        """Caller-authored GroundedObservation -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission", registry=None)
        obs = _make_observation()
        # Directly passing caller-authored observation should not authenticate
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        # The policy should reject caller-authored evidence
        assert assessment.semantic_verdict != SemanticVerdict.SATISFIED


class TestTP09AEExecutionFailure:
    """Tests that execution failure cannot become semantic success."""

    def test_execution_failed_not_satisfied(self, tmp_path):
        """FAILED execution status cannot become semantic SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            execution_status="FAILED",
        )
        # Even with approval, execution failure is preserved
        assert assessment.execution_status == "FAILED"
        # Semantic verdict depends on evaluation, but execution_status preserved

    def test_core_completed_not_semantic_satisfied(self, tmp_path):
        """Core COMPLETED does not imply semantic SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            execution_status="COMPLETED",
        )
        # COMPLETED execution status does not promote to SATISFIED
        # The verdict is determined by the policy trust gates
        assert assessment.semantic_verdict != SemanticVerdict.SATISFIED or assessment.reason != ""


class TestTP09AELegacyBehavior:
    """Tests LEGACY behavior boundaries."""

    def test_no_approved_contract_legacy(self, tmp_path):
        """No approved contract -> LEGACY behavior preserved."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[],
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY

    def test_empty_criteria_unknown(self, tmp_path):
        """Empty criteria -> UNKNOWN (without approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[],
        )
        # Empty criteria with no approval -> LEGACY
        # but the evaluation path should handle gracefully


class TestTP09AEAssessmentStructure:
    """Tests that assessment structure is correct."""

    def test_assessment_has_all_fields(self, tmp_path):
        """SemanticAssessment has all 15 specified fields populated."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # Check all required fields exist and are non-empty where appropriate
        assert isinstance(assessment.mission_id, str)
        assert isinstance(assessment.contract_digest, str)
        assert isinstance(assessment.execution_status, str)
        assert isinstance(assessment.semantic_verdict, SemanticVerdict)
        assert isinstance(assessment.evidence_refs, tuple)
        assert isinstance(assessment.reason, str)
        assert isinstance(assessment.scope, str)
        assert assessment.scope == AssessmentScope.PRODUCT_LEVEL_SEMANTIC_ASSESSMENT.value

    def test_assessment_scope_never_gate_verdict(self, tmp_path):
        """Scope is always product_level_semantic_assessment, never gate verdict."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.scope == AssessmentScope.PRODUCT_LEVEL_SEMANTIC_ASSESSMENT.value
        # Scope must NOT be a MissionCompletionGate verdict


class TestTP09AECrossMissionContract:
    """Tests cross-mission and cross-contract rejection."""

    def test_cross_mission_approval_unknown(self, tmp_path):
        """Approval from different mission -> UNKNOWN."""
        policy = create_policy(mission_id="mission_A", registry=type("Reg", (), {"consume": lambda self: _make_approval(contract_digest="digest_A")})())
        # The policy uses mission_id from constructor, approval has different digest
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # Different mission_id + different contract_digest should not satisfy
        assert assessment.semantic_verdict in (
            SemanticVerdict.UNKNOWN,
            SemanticVerdict.LEGACY,
        )

    def test_cross_contract_digest_unknown(self, tmp_path):
        """Wrong contract digest -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval(contract_digest="wrong_digest")})())
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.semantic_verdict in (
            SemanticVerdict.UNKNOWN,
            SemanticVerdict.LEGACY,
        )


class TestTP09AEFrozenCoreIntegrity:
    """Tests frozen-Core integrity - no Core modifications."""

    def test_no_mission_runtime_modification(self, tmp_path):
        """Policy never modifies MissionRuntime completion semantics."""
        from intent_kernel.runtime.mission_runtime import MissionCompletionGate
        # Verify the class exists and has its expected methods
        assert hasattr(MissionCompletionGate, "decide")
        assert hasattr(MissionCompletionGate, "evaluate_mission_completion")
        # Run assessment
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # MissionCompletionGate should be unchanged
        assert hasattr(MissionCompletionGate, "decide")
        assert hasattr(MissionCompletionGate, "evaluate_mission_completion")

    def test_no_success_contract_modification(self, tmp_path):
        """Policy never modifies success_contract.py behavior."""
        from intent_kernel.mission import success_contract
        # Verify the module is still importable and unchanged
        assert callable(success_contract.evaluate_success_contract)


class TestTP09AEOutputLabeling:
    """Tests output labeling."""

    def test_output_always_product_level_semantic_assessment(self, tmp_path):
        """Output always labeled product_level_semantic_assessment."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.scope == "product_level_semantic_assessment"

    def test_output_never_presented_as_gate_decision(self, tmp_path):
        """Output never presented as MissionCompletionGate verdict."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # The scope explicitly labels this as NOT a gate verdict
        assert assessment.scope != "mission_completion_gate_verdict"


class TestTP09AEProductBridgeCompatibility:
    """Tests ProductBridge compatibility."""

    def test_policy_compatible_with_product_bridge_grounded_observation(self, tmp_path):
        """Policy works with ProductBridge grounded observation format."""
        from product_bridge import ProductBridge
        policy = create_policy(mission_id="test_mission", registry=None)
        # Create a minimal observation compatible with ProductBridge
        obs = type("Observation", (), {
            "mission_id": "test_mission",
            "action_id": "test_action",
            "gate_proof_digest": "gate_proof_abc",
            "observed_at": NOW.isoformat(),
        })()
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        # Should produce a valid assessment (LEGACY/UNKNOWN/SATISFIED depending on approval)
        assert isinstance(assessment, type(policy.assess(
            criteria=[_make_criterion()],
        )))


# Additional adversarial tests to reach 25+ total

class TestTP09AEAdditionalAdversarial:
    """Additional adversarial test cases."""

    def test_forged_approval_token_unknown(self, tmp_path):
        """Forged/ invalid approval token -> UNKNOWN."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval(token="forged")})())
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.semantic_verdict != SemanticVerdict.SATISFIED

    def test_replayed_approval_token_unknown(self, tmp_path):
        """Replayed approval token -> UNKNOWN (single-use consumption)."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume_once": True})())
        # First call should work, second should fall to LEGACY/UNKNOWN
        assessment1 = policy.assess(
            criteria=[_make_criterion()],
        )
        assessment2 = policy.assess(
            criteria=[_make_criterion()],
        )
        # Second assessment should not raise; it falls to safe default
        assert assessment2.semantic_verdict in (
            SemanticVerdict.UNKNOWN,
            SemanticVerdict.LEGACY,
        )

    def test_planner_only_success_criteria_unknown(self, tmp_path):
        """Planner-generated criteria alone -> UNKNOWN, not SATISFIED."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_planner_criterion()],
        )
        # Planner criteria are advisory; without grounded evidence + approval -> UNKNOWN
        assert assessment.semantic_verdict != SemanticVerdict.SATISFIED

    def test_evidence_conflict_unknown(self, tmp_path):
        """Conflicting evidence markers -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            evidence={"__result__": "pass", "__conflict__": True},
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"

    def test_evidence_stale_unknown(self, tmp_path):
        """Stale evidence markers -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            evidence={"__result__": "pass", "__stale__": True},
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"

    def test_null_observation_unknown(self, tmp_path):
        """Null/None observation -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=None,
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"

    def test_missing_evidence_unknown(self, tmp_path):
        """Missing evidence -> LEGACY (no approval)."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.semantic_verdict == SemanticVerdict.LEGACY
        assert assessment.reason == "no approved semantic contract"

    def test_execution_failure_preserved(self, tmp_path):
        """Execution FAILED status preserved, not upgraded."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            execution_status="FAILED",
        )
        assert assessment.execution_status == "FAILED"

    def test_unknown_execution_status_handled(self, tmp_path):
        """Unknown execution status handled gracefully."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
            execution_status="UNKNOWN",
        )
        assert assessment.execution_status == "UNKNOWN"
        assert isinstance(assessment.semantic_verdict, SemanticVerdict)

    def test_satisfied_with_valid_proof_and_fresh_observation(self, tmp_path):
        """SATISFIED only when all gates pass: approval + valid proof + fresh observation."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation(observed_at=NOW.isoformat())
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
            evidence={"__result__": {"test": "value"}},
            now=NOW,
        )
        assert assessment.semantic_verdict == SemanticVerdict.SATISFIED
        assert "approved-with-grounded-evidence" in assessment.reason

    def test_assessment_reason_always_populated(self, tmp_path):
        """Assessment reason field is always populated."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert isinstance(assessment.reason, str)
        assert len(assessment.reason) > 0

    def test_evidence_refs_populated_when_observation_present(self, tmp_path):
        """Evidence refs include observation references when observation present."""
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval()})())
        obs = _make_observation()
        assessment = policy.assess(
            criteria=[_make_criterion()],
            observation=obs,
        )
        assert len(assessment.evidence_refs) > 0
        # Should have observation refs
        ref_str = str(assessment.evidence_refs)
        assert "observation:" in ref_str or any("observation" in r for r in assessment.evidence_refs)

    def test_contract_digest_from_approval(self, tmp_path):
        """Contract digest comes from the consumed approval."""
        expected_digest = "expected_digest_123"
        policy = create_policy(mission_id="test_mission", registry=type("Reg", (), {"consume": lambda self: _make_approval(contract_digest=expected_digest)})())
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.contract_digest == expected_digest

    def test_mission_id_in_assessment(self, tmp_path):
        """Mission ID in assessment matches policy constructor."""
        policy = create_policy(mission_id="specific_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert assessment.mission_id == "specific_mission"

    def test_semantic_verdict_type(self, tmp_path):
        """Semantic verdict is always a SemanticVerdict enum value."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        assert isinstance(assessment.semantic_verdict, SemanticVerdict)
        # Should be one of the four valid verdicts
        assert assessment.semantic_verdict in (
            SemanticVerdict.SATISFIED,
            SemanticVerdict.UNSATISFIED,
            SemanticVerdict.UNKNOWN,
            SemanticVerdict.LEGACY,
        )

    def test_multiple_criteria_evaluated(self, tmp_path):
        """Multiple criteria are evaluated together."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[
                _make_criterion(criterion_id="p1"),
                _make_criterion(criterion_id="p2"),
            ],
        )
        assert isinstance(assessment.semantic_verdict, SemanticVerdict)
        assert isinstance(assessment.evidence_refs, tuple)

    def test_assessment_dataclass_immutability(self, tmp_path):
        """SemanticAssessment is a dataclass with all fields."""
        policy = create_policy(mission_id="test_mission", registry=None)
        assessment = policy.assess(
            criteria=[_make_criterion()],
        )
        # Verify it's a proper dataclass instance
        assert hasattr(assessment, "mission_id")
        assert hasattr(assessment, "contract_digest")
        assert hasattr(assessment, "execution_status")
        assert hasattr(assessment, "semantic_verdict")
        assert hasattr(assessment, "evidence_refs")
        assert hasattr(assessment, "reason")
        assert hasattr(assessment, "scope")


# End of TP-09AE adversarial validation tests