"""Verification Gate & Mission Completion Gate — RFC-0015 (STUDIO 10.2).

Enforces post-execution verification on individual action nodes and whole-mission completion
gates to ensure ACTION_EXECUTED != ACTION_SUCCEEDED and AGENT_CLAIM != VERIFIED_RESULT.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from intent_kernel.instructions import (
    CompletionEvidence,
    InstructionViolation,
    MissionConstraint,
    OutputContract,
    OutputContractValidator,
    OutputValidationResult,
)
from intent_kernel.runtime.models import (
    ActionContract,
    MissionRuntimeInstance,
    RuntimeNode,
    RuntimeNodeState,
    VerificationStatus,
)


class ActionVerificationPort(ABC):
    """Abstract port interface for post-execution action verification."""

    @abstractmethod
    async def verify(
        self,
        action: ActionContract,
        result: Any,
    ) -> VerificationStatus:
        """Verify an execution result against expected output or contract rules."""
        pass


class InMemoryActionVerificationAdapter(ActionVerificationPort):
    """Concrete verification adapter for test actions."""

    async def verify(
        self,
        action: ActionContract,
        result: Any,
    ) -> VerificationStatus:
        if action.expected_output is not None:
            if result == action.expected_output:
                return VerificationStatus.VERIFIED_SUCCESS
            else:
                return VerificationStatus.VERIFIED_FAILURE

        # Default verification for successful return without explicit expected_output
        if result is not None and not isinstance(result, Exception):
            return VerificationStatus.VERIFIED_SUCCESS

        return VerificationStatus.VERIFIED_FAILURE


class VerificationGate:
    """Post-execution validation gate for individual action nodes."""

    def __init__(self, verifier: Optional[ActionVerificationPort] = None) -> None:
        self.verifier = verifier or InMemoryActionVerificationAdapter()

    async def evaluate_node(
        self,
        node: RuntimeNode,
        action: ActionContract,
        result: Any,
    ) -> Tuple[VerificationStatus, CompletionEvidence]:
        """Verify a node execution result and generate canonical CompletionEvidence."""
        if not action.verification_required:
            status = VerificationStatus.VERIFIED_SUCCESS
        else:
            status = await self.verifier.verify(action, result)

        is_verified = status == VerificationStatus.VERIFIED_SUCCESS

        evidence = CompletionEvidence(
            claim=f"Node {node.node_id} executed capability {action.capability}",
            evidence_type="ACTION_VERIFICATION",
            source="VerificationGate",
            verified=is_verified,
            verification_method=f"{self.verifier.__class__.__name__}.verify()",
            details={
                "node_id": node.node_id,
                "capability": action.capability,
                "verification_status": status.value if hasattr(status, "value") else str(status),
                "expected": action.expected_output,
                "observed": result,
            },
        )

        return status, evidence


class MissionCompletionGate:
    """Whole-mission completion gate evaluating node verifications and OutputContracts."""

    def __init__(self, output_validator: Optional[OutputContractValidator] = None) -> None:
        self.output_validator = output_validator or OutputContractValidator()

    async def evaluate_mission_completion(
        self,
        instance: MissionRuntimeInstance,
        final_output: Optional[str] = None,
        output_contract: Optional[OutputContract] = None,
        constraints: Optional[List[MissionConstraint]] = None,
    ) -> Tuple[bool, List[CompletionEvidence], List[str]]:
        """Evaluate if a mission is allowed to transition to COMPLETED."""
        evidence_list: List[CompletionEvidence] = []
        violations: List[str] = []

        # 1. Check Mandatory Nodes Completion & Verification
        for node_id, node in instance.nodes.items():
            if node.state != RuntimeNodeState.SUCCEEDED:
                violations.append(f"Mandatory node '{node_id}' is in state {node.state.value}, not SUCCEEDED.")

            if node.verification_result != VerificationStatus.VERIFIED_SUCCESS:
                violations.append(f"Node '{node_id}' verification status is {node.verification_result}, not VERIFIED_SUCCESS.")

        # 2. Evaluate OutputContract if required
        if output_contract and output_contract.validation_required:
            output_text = final_output or ""
            val_result: OutputValidationResult = self.output_validator.validate(output_text, output_contract)

            out_evidence = self.output_validator.generate_completion_evidence("Final mission output structure", val_result)
            evidence_list.append(out_evidence)

            if not val_result.valid:
                for b_viol in val_result.blocking_violations:
                    violations.append(f"OutputContract violation: {b_viol}")

        # 3. Final Decision
        is_completed = len(violations) == 0

        # Create whole-mission evidence
        mission_evidence = CompletionEvidence(
            claim=f"Mission {instance.mission_id} completion gate evaluation",
            evidence_type="POLICY_VALIDATION",
            source="MissionCompletionGate",
            verified=is_completed,
            verification_method="MissionCompletionGate.evaluate_mission_completion()",
            details={
                "mission_id": instance.mission_id,
                "violations_count": len(violations),
                "violations": violations,
            },
        )
        evidence_list.append(mission_evidence)

        return is_completed, evidence_list, violations
