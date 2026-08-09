"""Output Contract Validator — RFC-0014.1 (STUDIO 10.1).

Compares candidate output against OutputContract rules (single block, text outside blocks,
required sections, max blocks) to enforce MISSION_GENERATED != MISSION_COMPLETED.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from intent_kernel.instructions.models import (
    CompletionEvidence,
    InstructionViolation,
    OutputContract,
    OutputValidationResult,
)


class OutputContractValidator:
    """Canonical validator enforcing output structure contracts."""

    # Regex matching markdown code blocks (fenced by ```)
    CODE_BLOCK_PATTERN = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

    def __init__(self, max_output_corrections: int = 3) -> None:
        self.max_output_corrections = max_output_corrections

    def extract_code_blocks(self, text: str) -> List[str]:
        """Extract all markdown code block contents."""
        return self.CODE_BLOCK_PATTERN.findall(text)

    def extract_text_outside_blocks(self, text: str) -> str:
        """Extract all text sitting outside markdown code blocks."""
        outside = self.CODE_BLOCK_PATTERN.sub("", text)
        return outside.strip()

    def validate(self, output_text: str, contract: OutputContract) -> OutputValidationResult:
        """Validate candidate output against contract rules."""
        violations: List[str] = []
        blocking_violations: List[str] = []
        warnings: List[str] = []

        code_blocks = self.extract_code_blocks(output_text)
        text_outside = self.extract_text_outside_blocks(output_text)

        # 1. Single Block Required Check
        if contract.single_block_required:
            if len(code_blocks) == 0:
                msg = "Expected output to be contained in a single code block, but no code blocks were found."
                blocking_violations.append(msg)
                violations.append(msg)
            elif len(code_blocks) > contract.max_blocks:
                msg = f"Expected at most {contract.max_blocks} code block(s), but found {len(code_blocks)} blocks."
                blocking_violations.append(msg)
                violations.append(msg)

        # 2. Text Outside Block Allowed Check
        if not contract.text_outside_block_allowed:
            if text_outside:
                msg = f"Text outside code block is forbidden, but found non-whitespace text: '{text_outside[:60]}...'"
                blocking_violations.append(msg)
                violations.append(msg)

        # 3. Max Blocks Check
        if len(code_blocks) > contract.max_blocks:
            msg = f"Found {len(code_blocks)} blocks, exceeding max_blocks limit of {contract.max_blocks}."
            if msg not in blocking_violations:
                blocking_violations.append(msg)
                violations.append(msg)

        # 4. Required Sections Check
        for req_sec in contract.required_sections:
            if req_sec not in output_text:
                msg = f"Required section '{req_sec}' missing from output."
                blocking_violations.append(msg)
                violations.append(msg)

        # 5. Forbidden Sections Check
        for forb_sec in contract.forbidden_sections:
            if forb_sec in output_text:
                msg = f"Forbidden section '{forb_sec}' present in output."
                blocking_violations.append(msg)
                violations.append(msg)

        is_valid = len(blocking_violations) == 0

        return OutputValidationResult(
            valid=is_valid,
            violations=violations,
            blocking_violations=blocking_violations,
            warnings=warnings,
            expected={
                "single_block_required": contract.single_block_required,
                "text_outside_block_allowed": contract.text_outside_block_allowed,
                "max_blocks": contract.max_blocks,
                "required_sections": contract.required_sections,
            },
            observed={
                "code_block_count": len(code_blocks),
                "has_text_outside": bool(text_outside),
                "text_outside_sample": text_outside[:100] if text_outside else "",
            },
            correction_required=not is_valid,
        )

    def generate_completion_evidence(
        self,
        claim: str,
        result: OutputValidationResult,
    ) -> CompletionEvidence:
        """Create canonical CompletionEvidence proving CLAIM != VERIFIED STATE."""
        return CompletionEvidence(
            claim=claim,
            evidence_type="FORMAT_VALIDATION",
            source="OutputContractValidator",
            verified=result.valid,
            verification_method="OutputContractValidator.validate()",
            details=result.to_dict(),
        )

    def create_violation_record(
        self,
        instruction_id: str,
        mission_id: str,
        result: OutputValidationResult,
    ) -> InstructionViolation:
        """Create canonical InstructionViolation record."""
        return InstructionViolation(
            instruction_id=instruction_id,
            mission_id=mission_id,
            expected_behavior=str(result.expected),
            observed_behavior=str(result.observed),
            severity="high" if result.blocking_violations else "medium",
            correction_attempted=False,
            correction_succeeded=False,
        )
