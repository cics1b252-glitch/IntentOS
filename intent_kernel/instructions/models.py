"""Persistent Instruction & Output Contract Models — RFC-0014.1 (STUDIO 10.1).

Defines canonical contracts for persistent instructions, precedence rules,
mission constraints, output contracts, output validation results, completion evidence,
and instruction violations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from intent_kernel.time_utils import utc_iso


class InstructionType(str, Enum):
    """Classification of persistent instructions."""
    FORMAT_PREFERENCE = "FORMAT_PREFERENCE"
    WORKFLOW_RULE = "WORKFLOW_RULE"
    DELIVERY_RULE = "DELIVERY_RULE"
    PROJECT_RULE = "PROJECT_RULE"
    TOOL_RULE = "TOOL_RULE"
    SAFETY_PREFERENCE = "SAFETY_PREFERENCE"
    INTERACTION_PREFERENCE = "INTERACTION_PREFERENCE"


class InstructionScope(str, Enum):
    """Scope boundaries for persistent instructions."""
    GLOBAL_USER = "GLOBAL_USER"
    PROJECT = "PROJECT"
    MISSION = "MISSION"
    SESSION = "SESSION"


class PrecedenceLevel(int, Enum):
    """Strict precedence order for instruction resolution."""
    CONSTITUTION_SAFETY = 1
    CURRENT_EXPLICIT_MISSION = 2
    PERSISTENT_PROJECT_RULE = 3
    PERSISTENT_USER_RULE = 4
    SESSION_PREFERENCE = 5
    AGENT_DEFAULT = 6


@dataclass
class PersistentInstruction:
    """Canonical Persistent Instruction model."""
    instruction_id: str = field(default_factory=lambda: f"pi_{uuid4().hex[:8]}")
    scope: InstructionScope = InstructionScope.GLOBAL_USER
    project_id: str = "GLOBAL"
    instruction_type: InstructionType = InstructionType.FORMAT_PREFERENCE
    rule_key: str = "general_preference"
    description: str = ""
    constraint: str = ""
    priority: int = 50  # Lower number = higher priority within same precedence level
    source: str = "user"
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)
    active: bool = True
    version: int = 1
    supersedes: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["scope"] = self.scope.value if isinstance(self.scope, Enum) else str(self.scope)
        res["instruction_type"] = self.instruction_type.value if isinstance(self.instruction_type, Enum) else str(self.instruction_type)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PersistentInstruction:
        if not data:
            return cls()
        scope_raw = data.get("scope", InstructionScope.GLOBAL_USER)
        if isinstance(scope_raw, str):
            try:
                scope_raw = InstructionScope(scope_raw)
            except ValueError:
                scope_raw = InstructionScope.GLOBAL_USER

        type_raw = data.get("instruction_type", InstructionType.FORMAT_PREFERENCE)
        if isinstance(type_raw, str):
            try:
                type_raw = InstructionType(type_raw)
            except ValueError:
                type_raw = InstructionType.FORMAT_PREFERENCE

        return cls(
            instruction_id=data.get("instruction_id", f"pi_{uuid4().hex[:8]}"),
            scope=scope_raw,
            project_id=data.get("project_id", "GLOBAL"),
            instruction_type=type_raw,
            rule_key=data.get("rule_key", "general_preference"),
            description=data.get("description", ""),
            constraint=data.get("constraint", ""),
            priority=data.get("priority", 50),
            source=data.get("source", "user"),
            created_at=data.get("created_at", utc_iso()),
            updated_at=data.get("updated_at", utc_iso()),
            active=data.get("active", True),
            version=data.get("version", 1),
            supersedes=data.get("supersedes"),
            provenance=data.get("provenance", {}),
        )


@dataclass
class MissionConstraint:
    """Canonical Mission Constraint derived from persistent or explicit instructions."""
    constraint_id: str = field(default_factory=lambda: f"mc_{uuid4().hex[:8]}")
    source_instruction_id: str = ""
    constraint_type: str = "FORMAT"
    expected_behavior: str = ""
    validation_strategy: str = "SYNTACTIC"  # SYNTACTIC, SEMANTIC, POLICY
    severity: str = "high"  # critical, high, medium, low
    blocking: bool = True
    scope: str = "MISSION"
    reason: str = ""
    precedence: int = PrecedenceLevel.PERSISTENT_USER_RULE.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OutputContract:
    """Canonical Output Contract enforcing formatting and delivery requirements."""
    contract_id: str = field(default_factory=lambda: f"oc_{uuid4().hex[:8]}")
    single_block_required: bool = False
    text_outside_block_allowed: bool = True
    required_sections: List[str] = field(default_factory=list)
    forbidden_sections: List[str] = field(default_factory=list)
    required_format: str = "text"
    max_blocks: int = 100
    validation_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OutputValidationResult:
    """Canonical result produced by OutputContractValidator."""
    valid: bool = True
    violations: List[str] = field(default_factory=list)
    blocking_violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    expected: Dict[str, Any] = field(default_factory=dict)
    observed: Dict[str, Any] = field(default_factory=dict)
    correction_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompletionEvidence:
    """Canonical Completion Evidence proving verified state vs claims."""
    evidence_id: str = field(default_factory=lambda: f"ev_{uuid4().hex[:8]}")
    claim: str = ""
    evidence_type: str = "FORMAT_VALIDATION"  # TEST_RESULT, FILE_EXISTS, FORMAT_VALIDATION, POLICY_VALIDATION, ACTION_VERIFICATION, USER_CONFIRMATION
    source: str = "validator"
    verified: bool = False
    verification_method: str = "OutputContractValidator"
    timestamp: str = field(default_factory=utc_iso)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstructionViolation:
    """Canonical record of an instruction violation."""
    violation_id: str = field(default_factory=lambda: f"iv_{uuid4().hex[:8]}")
    instruction_id: str = ""
    mission_id: str = ""
    expected_behavior: str = ""
    observed_behavior: str = ""
    severity: str = "high"
    detected_at: str = field(default_factory=utc_iso)
    correction_attempted: bool = False
    correction_succeeded: bool = False
    recurrence_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
