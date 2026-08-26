"""Verification Gate & Mission Completion Gate — RFC-0015 (STUDIO 10.2).

Enforces post-execution verification on individual action nodes and whole-mission completion
gates to ensure ACTION_EXECUTED != ACTION_SUCCEEDED and AGENT_CLAIM != VERIFIED_RESULT.
"""

from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
from intent_kernel.runtime.semantic_verifier import (
    DeterministicRuleVerifier,
    rule_set_hash,
)


_COMPLETION_AUTHORITY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class MissionCompletionDecision:
    """Evidence-bearing authorization for the lifecycle COMPLETED transition.

    Executor, provider and response text are deliberately absent as authorities.
    Only :class:`MissionCompletionGate` produces this canonical decision after
    examining execution and verification evidence for the whole runtime DAG.
    """

    mission_id: str
    allowed: bool
    execution_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verification_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    completion_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    violations: tuple[str, ...] = field(default_factory=tuple)
    authority: str = "MissionCompletionGate"
    _authority_token: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def evidence_complete(self) -> bool:
        return bool(
            self.allowed
            and self.execution_evidence
            and self.verification_evidence
            and self.completion_evidence
            and self._authority_token is _COMPLETION_AUTHORITY_TOKEN
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

        # Without an explicit verification contract, no result can be considered
        # verified. Mere execution or result existence is not verification.
        return VerificationStatus.VERIFIED_FAILURE


class DeterministicStructuralVerifier(ActionVerificationPort):
    """Deterministic structural contract verifier — M25.2 STRUCTURAL CONTRACT SUBSET.

    Validates action results against a bounded structural contract. Supports:
    type, required, properties, minimum, maximum, const, items.

    This is NOT full JSON Schema. It implements only the M25.2 bounded subset.
    """

    _SUPPORTED_KEYWORDS = frozenset({
        "type", "required", "properties", "minimum", "maximum", "const", "items",
    })

    _SUPPORTED_TYPES = frozenset({
        "string", "number", "integer", "boolean", "array", "object", "null",
    })

    @staticmethod
    def contract_hash(schema: Dict[str, Any]) -> str:
        """Deterministic SHA-256 identity for a structural contract."""
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def verify(
        self,
        action: ActionContract,
        result: Any,
    ) -> VerificationStatus:
        schema = action.verification_schema
        if schema is None or not isinstance(schema, dict):
            return VerificationStatus.VERIFIED_FAILURE

        errors: List[str] = []
        self._validate_schema_keywords(schema, errors, path="$")
        if errors:
            return VerificationStatus.VERIFIED_FAILURE

        resolved = self._resolve_json_input(result)
        if resolved is _PARSE_FAILED:
            return VerificationStatus.VERIFIED_FAILURE

        self._validate_value(resolved, schema, errors, path="$")
        return VerificationStatus.VERIFIED_SUCCESS if not errors else VerificationStatus.VERIFIED_FAILURE

    # --- Schema keyword validation ---

    def _validate_schema_keywords(
        self, schema: Dict[str, Any], errors: List[str], path: str,
    ) -> None:
        # M25-03/04/05/06/07/08: Comprehensive contract validity checks
        for key in schema:
            if key not in self._SUPPORTED_KEYWORDS:
                errors.append(f"{path}: unsupported contract keyword '{key}'")
        schema_type = schema.get("type")
        if schema_type is not None and schema_type not in self._SUPPORTED_TYPES:
            errors.append(f"{path}: unsupported type '{schema_type}'")

        # M25-04: required must be list[str]
        if "required" in schema:
            req = schema["required"]
            if not isinstance(req, list):
                errors.append(f"{path}: 'required' must be a list")
            else:
                for entry in req:
                    if not isinstance(entry, str):
                        errors.append(
                            f"{path}: 'required' entries must be strings, "
                            f"got {type(entry).__name__}: {entry!r}"
                        )

        # M25-05: properties must be dict with STRING keys
        if "properties" in schema:
            props = schema["properties"]
            if not isinstance(props, dict):
                errors.append(f"{path}: 'properties' must be an object")
            else:
                for k in props:
                    if not isinstance(k, str):
                        errors.append(
                            f"{path}: 'properties' keys must be strings, "
                            f"got {type(k).__name__}: {k!r}"
                        )

        if "items" in schema and not isinstance(schema["items"], dict):
            errors.append(f"{path}: 'items' must be an object")

        # M25-07/M25-08: numeric bounds must be finite real numbers (not bool, NaN, inf)
        for keyword in ("minimum", "maximum"):
            if keyword in schema:
                val = schema[keyword]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(f"{path}: '{keyword}' must be a finite number")
                elif not math.isfinite(val):
                    errors.append(f"{path}: '{keyword}' must be finite, got {val}")

        # M25-03: minimum <= maximum coherence
        if "minimum" in schema and "maximum" in schema:
            min_val = schema["minimum"]
            max_val = schema["maximum"]
            if (
                isinstance(min_val, (int, float)) and not isinstance(min_val, bool)
                and isinstance(max_val, (int, float)) and not isinstance(max_val, bool)
                and math.isfinite(min_val) and math.isfinite(max_val)
                and min_val > max_val
            ):
                errors.append(
                    f"{path}: minimum ({min_val}) must be <= maximum ({max_val})"
                )

        # M25-06: required fields must have corresponding properties
        if "required" in schema and "properties" in schema:
            req = schema["required"]
            props = schema["properties"]
            if isinstance(req, list) and isinstance(props, dict):
                for entry in req:
                    if isinstance(entry, str) and entry not in props:
                        errors.append(
                            f"{path}: required field '{entry}' has no corresponding property contract"
                        )

        if "const" in schema:
            pass  # const can be any JSON value

        # Recurse into nested property schemas
        props = schema.get("properties", {})
        if isinstance(props, dict):
            for pname, pschema in props.items():
                if isinstance(pschema, dict):
                    self._validate_schema_keywords(pschema, errors, f"{path}.properties.{pname}")

    # --- JSON input resolution ---

    @staticmethod
    def _resolve_json_input(result: Any) -> Any:
        if result is None or isinstance(result, (dict, list, int, float, bool)):
            return result
        if isinstance(result, str):
            stripped = result.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    return _PARSE_FAILED
            return result
        return _PARSE_FAILED

    # --- Value validation ---

    def _validate_value(
        self, value: Any, schema: Dict[str, Any], errors: List[str], path: str,
    ) -> None:
        schema_type = schema.get("type")
        if schema_type is not None:
            self._check_type(value, schema_type, errors, path)

        if "const" in schema:
            if not self._const_matches(value, schema["const"]):
                errors.append(f"{path}: const mismatch: expected {schema['const']!r}, got {value!r}")

        if schema_type == "object" and isinstance(value, dict):
            self._validate_object(value, schema, errors, path)
        elif schema_type == "array" and isinstance(value, list):
            self._validate_array(value, schema, errors, path)
        elif schema_type in ("number", "integer") and isinstance(value, (int, float)):
            self._validate_numeric(value, schema, errors, path)
            self._validate_result_numeric_finiteness(value, schema_type, errors, path)

    def _check_type(
        self, value: Any, expected: str, errors: List[str], path: str,
    ) -> None:
        actual = self._python_type_name(value)
        if expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{path}: type mismatch: expected integer, got {actual}")
        elif expected == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{path}: type mismatch: expected number, got {actual}")
        elif expected == "boolean":
            if not isinstance(value, bool):
                errors.append(f"{path}: type mismatch: expected boolean, got {actual}")
        elif expected == "string":
            if not isinstance(value, str):
                errors.append(f"{path}: type mismatch: expected string, got {actual}")
        elif expected == "array":
            if not isinstance(value, list):
                errors.append(f"{path}: type mismatch: expected array, got {actual}")
        elif expected == "object":
            if not isinstance(value, dict):
                errors.append(f"{path}: type mismatch: expected object, got {actual}")
        elif expected == "null":
            if value is not None:
                errors.append(f"{path}: type mismatch: expected null, got {actual}")

    def _validate_object(
        self, value: Dict[str, Any], schema: Dict[str, Any], errors: List[str], path: str,
    ) -> None:
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in value:
                errors.append(f"{path}: missing required field '{field_name}'")
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in value and isinstance(prop_schema, dict):
                self._validate_value(value[prop_name], prop_schema, errors, f"{path}.{prop_name}")

    def _validate_array(
        self, value: List[Any], schema: Dict[str, Any], errors: List[str], path: str,
    ) -> None:
        items_schema = schema.get("items")
        if items_schema is not None and isinstance(items_schema, dict):
            for i, item in enumerate(value):
                self._validate_value(item, items_schema, errors, f"{path}[{i}]")

    def _validate_numeric(
        self, value: Any, schema: Dict[str, Any], errors: List[str], path: str,
    ) -> None:
        if "minimum" in schema:
            if value < schema["minimum"]:
                errors.append(f"{path}: below minimum: {value} < {schema['minimum']}")
        if "maximum" in schema:
            if value > schema["maximum"]:
                errors.append(f"{path}: above maximum: {value} > {schema['maximum']}")

    def _validate_result_numeric_finiteness(
        self, value: Any, schema_type: str, errors: List[str], path: str,
    ) -> None:
        """M25-08: Reject non-finite numeric values (NaN, Infinity) in results."""
        if schema_type in ("number", "integer") and isinstance(value, float):
            if not math.isfinite(value):
                errors.append(f"{path}: numeric value must be finite, got {value}")

    @staticmethod
    def _python_type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return type(value).__name__

    @staticmethod
    def _const_matches(value: Any, const: Any) -> bool:
        """Type-safe const comparison. Python bool/int equality is NOT used.

        Same structural type + same deterministic value = match.
        Different structural type = mismatch.

        M25.2.1 semantics:
        - True != 1, False != 0 (bool and integer are distinct structural types)
        - 1 != 1.0 (integer and number are distinct structural types)
        - "1" != 1 (string and integer are distinct structural types)
        """
        v_type = DeterministicStructuralVerifier._python_type_name(value)
        c_type = DeterministicStructuralVerifier._python_type_name(const)
        if v_type != c_type:
            return False
        # Same structural type — compare values directly
        if v_type == "object":
            return value == const and set(value.keys()) == set(const.keys())
        if v_type == "array":
            if len(value) != len(const):
                return False
            return all(
                DeterministicStructuralVerifier._const_matches(vi, ci)
                for vi, ci in zip(value, const)
            )
        return value == const


_PARSE_FAILED = object()


class VerificationGate:
    """Post-execution validation gate for individual action nodes."""

    def __init__(self, verifier: Optional[ActionVerificationPort] = None) -> None:
        self._exact_verifier = verifier or InMemoryActionVerificationAdapter()
        self._structural_verifier = DeterministicStructuralVerifier()
        self._rule_verifier = DeterministicRuleVerifier()

    async def evaluate_node(
        self,
        node: RuntimeNode,
        action: ActionContract,
        result: Any,
    ) -> Tuple[VerificationStatus, CompletionEvidence]:
        """Verify a node execution result and generate canonical CompletionEvidence.

        Composition model:
        - EXACT/None + no semantic_rules → EXACT only
        - STRUCTURAL + no semantic_rules → STRUCTURAL only
        - EXACT/None + semantic_rules → semantic rules required
        - STRUCTURAL + semantic_rules → STRUCTURAL AND semantic rules required

        Failure dominates. Both required and both success → VERIFIED_SUCCESS.
        """
        verification_type = getattr(action, "verification_type", None)
        semantic_rules = getattr(action, "semantic_rules", None)
        has_semantic = isinstance(semantic_rules, list) and len(semantic_rules) > 0

        if not action.verification_required:
            status = VerificationStatus.VERIFIED_SUCCESS
            verifier_name = self._exact_verifier.__class__.__name__
        else:
            # --- Primary verification (EXACT or STRUCTURAL) ---
            primary_status: VerificationStatus
            if verification_type == "STRUCTURAL":
                if action.verification_schema is None:
                    primary_status = VerificationStatus.VERIFIED_FAILURE
                    verifier_name = "VerificationGate"
                else:
                    primary_status = await self._structural_verifier.verify(action, result)
                    verifier_name = self._structural_verifier.__class__.__name__
            elif verification_type == "EXACT" or verification_type is None:
                if has_semantic:
                    # Semantic-only or semantic+EXACT: primary passes to semantic
                    primary_status = VerificationStatus.VERIFIED_SUCCESS
                    verifier_name = "DeterministicRuleVerifier"
                else:
                    primary_status = await self._exact_verifier.verify(action, result)
                    verifier_name = self._exact_verifier.__class__.__name__
            else:
                primary_status = VerificationStatus.VERIFIED_FAILURE
                verifier_name = "VerificationGate"

            # --- Semantic verification (if rules present) ---
            semantic_eval = None
            if has_semantic and primary_status == VerificationStatus.VERIFIED_SUCCESS:
                semantic_eval = self._rule_verifier.evaluate(semantic_rules, result)
                if not semantic_eval.passed:
                    status = VerificationStatus.VERIFIED_FAILURE
                    verifier_name = "DeterministicRuleVerifier"
                else:
                    status = VerificationStatus.VERIFIED_SUCCESS
            else:
                status = primary_status

        is_verified = status == VerificationStatus.VERIFIED_SUCCESS
        contract_hash: str | None = None
        if verification_type == "STRUCTURAL" and action.verification_schema is not None:
            contract_hash = DeterministicStructuralVerifier.contract_hash(action.verification_schema)

        # Semantic evidence fields
        semantic_hash: str | None = None
        semantic_rule_count: int = 0
        semantic_outcomes: list = []
        if has_semantic:
            semantic_hash = rule_set_hash(semantic_rules)
            semantic_rule_count = len(semantic_rules)
            if semantic_eval is not None:
                semantic_outcomes = [r.to_dict() for r in semantic_eval.rule_results]
            elif not (not action.verification_required):
                sem_result = self._rule_verifier.evaluate(semantic_rules, result)
                semantic_outcomes = [r.to_dict() for r in sem_result.rule_results]

        evidence = CompletionEvidence(
            claim=f"Node {node.node_id} executed capability {action.capability}",
            evidence_type="ACTION_VERIFICATION",
            source="VerificationGate",
            verified=is_verified,
            verification_method=f"{verifier_name}.verify()",
            details={
                "node_id": node.node_id,
                "capability": action.capability,
                "verification_status": status.value if hasattr(status, "value") else str(status),
                "verification_type": verification_type or "EXACT",
                "expected": action.expected_output,
                "observed": result,
                "contract_hash": contract_hash,
                "rule_set_hash": semantic_hash,
                "semantic_rule_count": semantic_rule_count,
                "semantic_rule_outcomes": semantic_outcomes,
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
        decision = await self.decide(
            instance,
            final_output=final_output,
            output_contract=output_contract,
            constraints=constraints,
        )
        return (
            decision.allowed,
            [
                CompletionEvidence(**evidence)
                for evidence in decision.completion_evidence
            ],
            list(decision.violations),
        )

    async def decide(
        self,
        instance: MissionRuntimeInstance,
        final_output: Optional[str] = None,
        output_contract: Optional[OutputContract] = None,
        constraints: Optional[List[MissionConstraint]] = None,
    ) -> MissionCompletionDecision:
        """Produce the only decision eligible to complete a canonical Mission."""
        evidence_list: List[CompletionEvidence] = []
        violations: List[str] = []
        execution_evidence: List[dict[str, Any]] = []
        verification_evidence: List[dict[str, Any]] = []

        if not instance.nodes:
            violations.append("Mission has no executable nodes or execution evidence.")

        # 1. Check Mandatory Nodes Completion & Verification
        for node_id, node in instance.nodes.items():
            if node.attempt_count <= 0:
                violations.append(
                    f"Mandatory node '{node_id}' has no execution attempt evidence."
                )
            else:
                execution_evidence.append({
                    "node_id": node_id,
                    "attempt_count": node.attempt_count,
                    "state": node.state.value,
                })
            if node.state != RuntimeNodeState.SUCCEEDED:
                violations.append(f"Mandatory node '{node_id}' is in state {node.state.value}, not SUCCEEDED.")

            if node.verification_result != VerificationStatus.VERIFIED_SUCCESS:
                violations.append(f"Node '{node_id}' verification status is {node.verification_result}, not VERIFIED_SUCCESS.")

            node_evidence = [
                evidence for evidence in instance.completion_evidence
                if evidence.get("source") == "VerificationGate"
                and evidence.get("verified") is True
                and evidence.get("details", {}).get("node_id") == node_id
            ]
            if not node_evidence:
                violations.append(
                    f"Mandatory node '{node_id}' has no verified VerificationGate evidence."
                )
            else:
                verification_evidence.extend(node_evidence)

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

        serialized_completion = tuple(evidence.to_dict() for evidence in evidence_list)
        return MissionCompletionDecision(
            mission_id=instance.mission_id,
            allowed=is_completed,
            execution_evidence=tuple(execution_evidence),
            verification_evidence=tuple(verification_evidence),
            completion_evidence=serialized_completion,
            violations=tuple(violations),
            _authority_token=_COMPLETION_AUTHORITY_TOKEN,
        )
