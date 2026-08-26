"""Deterministic Rule-Based Semantic Verifier — M26.2.

Pure, deterministic, in-memory semantic rule verification for action results.
Provider-independent, side-effect free, fail-closed.

SIX operators: equals_field, sum_equals, greater_than_field, less_than_field,
all_unique, conditional_required.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

MAX_RULES = 100
MAX_COLLECTION_ITEMS = 1000

_ALLOWED_OPS = frozenset({
    "equals_field",
    "sum_equals",
    "greater_than_field",
    "less_than_field",
    "all_unique",
    "conditional_required",
})

# Keys each operator is allowed to contain
_OP_ALLOWED_KEYS: Dict[str, frozenset[str]] = {
    "equals_field": frozenset({"op", "left", "right"}),
    "sum_equals": frozenset({"op", "fields", "target"}),
    "greater_than_field": frozenset({"op", "left", "right"}),
    "less_than_field": frozenset({"op", "left", "right"}),
    "all_unique": frozenset({"op", "field"}),
    "conditional_required": frozenset({"op", "if_field", "equals", "then_required"}),
}


def rule_set_hash(rules: List[Dict[str, Any]]) -> str:
    """Canonical SHA-256 identity for a semantic rule set.

    Rule order is part of the contract — different order → different hash.
    """
    canonical = json.dumps(
        rules, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Any) -> Optional[Decimal]:
    """Convert a finite numeric value to canonical Decimal form.

    Returns None if value is not a finite numeric type (bool excluded).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        return Decimal(str(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return value
    return None


def _type_safe_equal(a: Any, b: Any) -> bool:
    """Type-safe equality. bool != int, int != float."""
    a_type = _structural_type(a)
    b_type = _structural_type(b)
    if a_type != b_type:
        return False
    if a_type == "null":
        return True
    if a_type == "boolean":
        return a is b or (isinstance(a, bool) and isinstance(b, bool) and a == b)
    if a_type == "integer":
        return a == b
    if a_type == "number":
        da, db = _canonical_decimal(a), _canonical_decimal(b)
        if da is None or db is None:
            return False
        return da == db
    if a_type == "string":
        return a == b
    if a_type == "array":
        if len(a) != len(b):
            return False
        return all(_type_safe_equal(ai, bi) for ai, bi in zip(a, b))
    if a_type == "object":
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_type_safe_equal(a[k], b[k]) for k in a)
    return a == b


def _structural_type(value: Any) -> str:
    """Deterministic structural type name."""
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


class RuleValidationResult:
    """Result of rule contract validation."""

    __slots__ = ("valid", "errors")

    def __init__(self, valid: bool, errors: Optional[List[str]] = None) -> None:
        self.valid = valid
        self.errors = errors or []


class RuleEvaluationResult:
    """Result of evaluating a single rule."""

    __slots__ = ("index", "op", "passed", "reason_code")

    def __init__(self, index: int, op: str, passed: bool, reason_code: str = "") -> None:
        self.index = index
        self.op = op
        self.passed = passed
        self.reason_code = reason_code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "op": self.op,
            "passed": self.passed,
            "reason_code": self.reason_code,
        }


class SemanticVerificationResult:
    """Result of full semantic rule set verification."""

    __slots__ = ("passed", "rule_results", "errors")

    def __init__(
        self,
        passed: bool,
        rule_results: Optional[List[RuleEvaluationResult]] = None,
        errors: Optional[List[str]] = None,
    ) -> None:
        self.passed = passed
        self.rule_results = rule_results or []
        self.errors = errors or []


class DeterministicRuleVerifier:
    """Pure deterministic semantic rule verifier — M26.2.

    Validates action results against a set of declarative semantic rules.
    Pure, deterministic, in-memory, provider-independent, side-effect free.
    """

    def validate_rules(self, rules: Any) -> RuleValidationResult:
        """Validate the rule contract before evaluating any result.

        INVALID RULE CONTRACT can never produce VERIFIED_SUCCESS.
        """
        if not isinstance(rules, list) or len(rules) == 0:
            return RuleValidationResult(False, ["semantic_rules must be a non-empty list"])

        if len(rules) > MAX_RULES:
            return RuleValidationResult(
                False, [f"too many rules: {len(rules)} exceeds limit of {MAX_RULES}"]
            )

        errors: List[str] = []
        for i, rule in enumerate(rules):
            path = f"rule[{i}]"
            if not isinstance(rule, dict):
                errors.append(f"{path}: must be a dict")
                continue

            op = rule.get("op")
            if op is None:
                errors.append(f"{path}: missing 'op'")
                continue
            if op not in _ALLOWED_OPS:
                errors.append(f"{path}: unknown op '{op}'")
                continue

            allowed_keys = _OP_ALLOWED_KEYS[op]
            for k in rule:
                if k not in allowed_keys:
                    errors.append(f"{path}: unexpected key '{k}' for op '{op}'")

            if op == "equals_field":
                errors.extend(self._validate_field_ref(rule, "left", path))
                errors.extend(self._validate_field_ref(rule, "right", path))
            elif op == "sum_equals":
                fields = rule.get("fields")
                if not isinstance(fields, list) or len(fields) == 0:
                    errors.append(f"{path}: 'fields' must be a non-empty list")
                else:
                    for fi, fname in enumerate(fields):
                        if not isinstance(fname, str) or not fname:
                            errors.append(f"{path}: fields[{fi}] must be a non-empty string")
                errors.extend(self._validate_field_ref(rule, "target", path))
            elif op == "greater_than_field":
                errors.extend(self._validate_field_ref(rule, "left", path))
                errors.extend(self._validate_field_ref(rule, "right", path))
            elif op == "less_than_field":
                errors.extend(self._validate_field_ref(rule, "left", path))
                errors.extend(self._validate_field_ref(rule, "right", path))
            elif op == "all_unique":
                errors.extend(self._validate_field_ref(rule, "field", path))
            elif op == "conditional_required":
                errors.extend(self._validate_field_ref(rule, "if_field", path))
                if "equals" not in rule:
                    errors.append(f"{path}: missing 'equals'")
                then_req = rule.get("then_required")
                if not isinstance(then_req, list) or len(then_req) == 0:
                    errors.append(f"{path}: 'then_required' must be a non-empty list")
                elif not all(isinstance(s, str) and s for s in then_req):
                    errors.append(f"{path}: 'then_required' entries must be non-empty strings")

        if errors:
            return RuleValidationResult(False, errors)
        return RuleValidationResult(True)

    def _validate_field_ref(self, rule: Dict[str, Any], key: str, path: str) -> List[str]:
        """Validate that a field reference is a non-empty string."""
        val = rule.get(key)
        if not isinstance(val, str) or not val:
            return [f"{path}: '{key}' must be a non-empty string"]
        return []

    def evaluate(
        self, rules: List[Dict[str, Any]], result: Any,
    ) -> SemanticVerificationResult:
        """Evaluate semantic rules against an action result.

        Result must be a mapping (dict) when rules reference fields.
        """
        # Validate rule contract first
        validation = self.validate_rules(rules)
        if not validation.valid:
            return SemanticVerificationResult(False, errors=validation.errors)

        # Result must be a dict for field-referencing rules
        resolved = result
        if isinstance(result, str):
            stripped = result.strip()
            if stripped.startswith("{"):
                try:
                    resolved = json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    return SemanticVerificationResult(
                        False, errors=["result: malformed JSON object"]
                    )
            elif not isinstance(result, dict):
                return SemanticVerificationResult(
                    False, errors=["result: must be a JSON object or dict for semantic rules"]
                )

        if not isinstance(resolved, dict):
            return SemanticVerificationResult(
                False, errors=["result: must be a mapping for semantic rules"]
            )

        rule_results: List[RuleEvaluationResult] = []
        all_passed = True

        for i, rule in enumerate(rules):
            op = rule["op"]
            try:
                passed, reason = self._evaluate_rule(op, rule, resolved)
            except Exception as exc:
                passed = False
                reason = f"exception: {type(exc).__name__}"

            rule_results.append(RuleEvaluationResult(i, op, passed, reason))
            if not passed:
                all_passed = False

        return SemanticVerificationResult(all_passed, rule_results)

    def _evaluate_rule(
        self, op: str, rule: Dict[str, Any], result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Evaluate a single rule. Returns (passed, reason_code)."""
        if op == "equals_field":
            return self._eval_equals_field(rule, result)
        if op == "sum_equals":
            return self._eval_sum_equals(rule, result)
        if op == "greater_than_field":
            return self._eval_comparison(rule, result, lambda a, b: a > b, "not_greater_than")
        if op == "less_than_field":
            return self._eval_comparison(rule, result, lambda a, b: a < b, "not_less_than")
        if op == "all_unique":
            return self._eval_all_unique(rule, result)
        if op == "conditional_required":
            return self._eval_conditional_required(rule, result)
        return False, f"unknown_op:{op}"

    def _eval_equals_field(
        self, rule: Dict[str, Any], result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        left_key = rule["left"]
        right_key = rule["right"]
        if left_key not in result:
            return False, f"missing_field:{left_key}"
        if right_key not in result:
            return False, f"missing_field:{right_key}"
        if _type_safe_equal(result[left_key], result[right_key]):
            return True, ""
        return False, "values_not_equal"

    def _eval_sum_equals(
        self, rule: Dict[str, Any], result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        fields = rule["fields"]
        target_key = rule["target"]

        if target_key not in result:
            return False, f"missing_field:{target_key}"

        target_dec = _canonical_decimal(result[target_key])
        if target_dec is None:
            return False, f"non_numeric_target:{target_key}"

        total = Decimal("0")
        for fname in fields:
            if fname not in result:
                return False, f"missing_field:{fname}"
            dval = _canonical_decimal(result[fname])
            if dval is None:
                return False, f"non_numeric_field:{fname}"
            total += dval

        if total == target_dec:
            return True, ""
        return False, "sum_mismatch"

    def _eval_comparison(
        self,
        rule: Dict[str, Any],
        result: Dict[str, Any],
        cmp_fn: Any,
        fail_code: str,
    ) -> Tuple[bool, str]:
        left_key = rule["left"]
        right_key = rule["right"]
        if left_key not in result:
            return False, f"missing_field:{left_key}"
        if right_key not in result:
            return False, f"missing_field:{right_key}"

        left_val = result[left_key]
        right_val = result[right_key]

        if isinstance(left_val, bool) or isinstance(right_val, bool):
            return False, "bool_not_numeric"

        left_dec = _canonical_decimal(left_val)
        right_dec = _canonical_decimal(right_val)
        if left_dec is None or right_dec is None:
            return False, "non_finite_number"

        if cmp_fn(left_dec, right_dec):
            return True, ""
        return False, fail_code

    def _eval_all_unique(
        self, rule: Dict[str, Any], result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        field_key = rule["field"]
        if field_key not in result:
            return False, f"missing_field:{field_key}"

        value = result[field_key]
        if not isinstance(value, list):
            return False, "not_array"

        if len(value) > MAX_COLLECTION_ITEMS:
            return False, f"collection_too_large:{len(value)}"

        seen: List[Tuple[str, Any]] = []
        for item in value:
            stype = _structural_type(item)
            if stype not in ("string", "integer", "number", "boolean", "null"):
                return False, f"unsupported_item_type:{stype}"
            for seen_type, seen_val in seen:
                if seen_type == stype and _type_safe_equal(item, seen_val):
                    return False, f"duplicate_item:{item!r}"
            seen.append((stype, item))

        return True, ""

    def _eval_conditional_required(
        self, rule: Dict[str, Any], result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        if_field = rule["if_field"]
        equals_val = rule["equals"]
        then_required = rule["then_required"]

        if if_field not in result:
            return True, ""  # condition field absent → rule passes

        if not _type_safe_equal(result[if_field], equals_val):
            return True, ""  # condition false → rule passes

        # Condition true — all then_required must exist
        for rfield in then_required:
            if rfield not in result:
                return False, f"missing_field:{rfield}"

        return True, ""
