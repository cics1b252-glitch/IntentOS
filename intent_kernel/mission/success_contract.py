"""FRONT-TP-09E: inert semantic success contract.

    PLANNER-GENERATED CRITERION != AUTHORITATIVE SUCCESS
    AUTHORIZED APPROVER REFERENCE != SUCCESS EVIDENCE
    CONTRACT VERSION != EVALUATION SEMANTICS

This module defines a VERSIONED, PROVENANCE-AWARE success-criterion contract
that is deliberately INERT. It evaluates criteria against evidence and returns
UNKNOWN / SATISFIED / UNSATISFIED. It is NOT wired into MissionCompletionGate,
does not alter MissionRecord definition-digest semantics, and cannot
authoritative anything by itself.

Design constraints:
  * ``success_criteria: tuple[str, ...]`` on MissionDefinition remains plain
    strings (legacy). This contract is a richer, OPTIONAL layer.
  * A criterion whose provenance is PLANNER_GENERATED can never produce
    SATISFIED. Planner output is advisory only.
  * Only a criterion with provenance AUTHORIZED_APPROVER AND a non-empty
    ``approver_ref`` may produce SATISFIED.
  * The predicate vocabulary is a CLOSED set. Anything else is INVALID and
    fails closed to UNKNOWN.
  * Every criterion names the evidence documents it requires. A missing
    evidence document yields UNKNOWN, never SATISFIED.
  * The contract carries a digest over its own content. A mismatch means
    tampering and yields UNKNOWN.
  * Unsupported evaluation versions yield UNKNOWN.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

CONTRACT_VERSION = "1.0.0"
SUPPORTED_VERSIONS = ("1.0.0",)

# Closed predicate vocabulary. Anything outside this set is INVALID.
_PREDICATE_EQUALS = "equals"
_PREDICATE_EXISTS = "exists"
_PREDICATE_NOT_EXISTS = "not_exists"
_PREDICATE_TYPE = "type"
_PREDICATE_CONTAINS = "contains"
PREDICATES = frozenset({
    _PREDICATE_EQUALS, _PREDICATE_EXISTS, _PREDICATE_NOT_EXISTS,
    _PREDICATE_TYPE, _PREDICATE_CONTAINS,
})

_TYPE_MAP = {
    "string": str, "number": (int, float), "boolean": bool,
    "object": dict, "array": list, "null": type(None),
}


class CriterionProvenance(str, Enum):
    """Where a success criterion came from. PLANNER is never authoritative."""

    PLANNER_GENERATED = "planner_generated"
    AUTHORIZED_APPROVER = "approved_approver"


class CriterionVerdict(str, Enum):
    UNKNOWN = "UNKNOWN"
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"


@dataclass(frozen=True)
class SemanticCriterion:
    """One versioned, provenance-aware success criterion.

    Inert by construction: this is data plus a pure predicate description.
    It is never consulted by the completion gate.
    """

    criterion_id: str
    objective: str
    provenance: str
    predicate: str
    json_path: str
    expected: Any = None
    evidence_refs: Tuple[str, ...] = ()
    approver_ref: str = ""
    evaluation_version: str = CONTRACT_VERSION
    contract_digest: str = ""

    def __post_init__(self) -> None:
        if not self.criterion_id or not self.criterion_id.strip():
            raise ValueError("criterion_id required")
        if not self.objective or not self.objective.strip():
            raise ValueError("objective required")
        if self.provenance not in (p.value for p in CriterionProvenance):
            raise ValueError(f"invalid provenance: {self.provenance}")
        if self.predicate not in PREDICATES:
            raise ValueError(f"unsupported predicate: {self.predicate}")
        if self.evaluation_version not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"unsupported evaluation_version: {self.evaluation_version}")
        if self.provenance == CriterionProvenance.AUTHORIZED_APPROVER.value \
                and not self.approver_ref.strip():
            raise ValueError(
                "authorized criteria require a non-empty approver_ref")
        if self.predicate in (_PREDICATE_EQUALS, _PREDICATE_CONTAINS,
                              _PREDICATE_TYPE) and self.expected is None:
            raise ValueError(f"predicate {self.predicate} requires expected")
        expected = compute_contract_digest(self)
        if self.contract_digest and self.contract_digest != expected:
            raise ValueError("contract_digest does not match criterion content")
        object.__setattr__(self, "contract_digest", expected)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "objective": self.objective,
            "provenance": self.provenance,
            "predicate": self.predicate,
            "json_path": self.json_path,
            "expected": self.expected,
            "evidence_refs": list(self.evidence_refs),
            "approver_ref": self.approver_ref,
            "evaluation_version": self.evaluation_version,
            "contract_digest": self.contract_digest,
        }


def compute_contract_digest(criterion: SemanticCriterion) -> str:
    """Deterministic digest over everything except the digest itself."""
    payload = {
        "criterion_id": criterion.criterion_id,
        "objective": criterion.objective,
        "provenance": criterion.provenance,
        "predicate": criterion.predicate,
        "json_path": criterion.json_path,
        "expected": criterion.expected,
        "evidence_refs": list(criterion.evidence_refs),
        "approver_ref": criterion.approver_ref,
        "evaluation_version": criterion.evaluation_version,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _resolve_path(document: Any, path: str) -> Tuple[bool, Any]:
    """Resolve a dotted JSON path. Returns (found, value)."""
    if not path:
        return True, document
    current = document
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


def _evaluate_predicate(criterion: SemanticCriterion,
                        evidence: Dict[str, Any]) -> CriterionVerdict:
    """Evaluate ONE criterion. Fails closed to UNKNOWN on any anomaly."""
    if criterion.predicate not in PREDICATES:
        return CriterionVerdict.UNKNOWN
    document = evidence.get("__result__")
    if document is None:
        return CriterionVerdict.UNKNOWN
    found, value = _resolve_path(document, criterion.json_path)
    if criterion.predicate == _PREDICATE_EXISTS:
        return (CriterionVerdict.SATISFIED if found
                else CriterionVerdict.UNSATISFIED)
    if criterion.predicate == _PREDICATE_NOT_EXISTS:
        return (CriterionVerdict.UNSATISFIED if found
                else CriterionVerdict.SATISFIED)
    if not found:
        return CriterionVerdict.UNKNOWN
    if criterion.predicate == _PREDICATE_TYPE:
        expected_type = criterion.expected
        if expected_type not in _TYPE_MAP:
            return CriterionVerdict.UNKNOWN
        return (CriterionVerdict.SATISFIED
                if isinstance(value, _TYPE_MAP[expected_type])
                else CriterionVerdict.UNSATISFIED)
    if criterion.predicate == _PREDICATE_CONTAINS:
        needle = criterion.expected
        return (CriterionVerdict.SATISFIED
                if isinstance(value, str) and isinstance(needle, str)
                and needle in value
                else CriterionVerdict.UNSATISFIED)
    if criterion.predicate == _PREDICATE_EQUALS:
        return (CriterionVerdict.SATISFIED
                if value == criterion.expected
                else CriterionVerdict.UNSATISFIED)
    return CriterionVerdict.UNKNOWN


def evaluate_success_contract(
    criteria: List[SemanticCriterion],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate the contract. Pure, deterministic, inert.

    Overall verdict:
      * any UNSATISFIED -> UNSATISFIED
      * else any UNKNOWN -> UNKNOWN
      * else SATISFIED
    Empty criteria -> UNKNOWN (vacuous truth is never success).
    """
    if not criteria:
        return {"overall": CriterionVerdict.UNKNOWN.value,
                "criteria": [], "reason": "no criteria"}
    per_criterion: List[Dict[str, Any]] = []
    saw_unsatisfied = False
    saw_unknown = False
    for criterion in criteria:
        # Tamper check: recompute digest.
        if compute_contract_digest(criterion) != criterion.contract_digest:
            per_criterion.append({"criterion_id": criterion.criterion_id,
                                  "verdict": CriterionVerdict.UNKNOWN.value,
                                  "reason": "digest-mismatch"})
            saw_unknown = True
            continue
        # Evidence completeness.
        missing = [ref for ref in criterion.evidence_refs
                   if ref not in evidence]
        if missing:
            per_criterion.append({
                "criterion_id": criterion.criterion_id,
                "verdict": CriterionVerdict.UNKNOWN.value,
                "reason": f"missing evidence: {missing}"})
            saw_unknown = True
            continue
        # Planner-generated criteria are advisory only.
        if criterion.provenance == CriterionProvenance.PLANNER_GENERATED.value:
            per_criterion.append({
                "criterion_id": criterion.criterion_id,
                "verdict": CriterionVerdict.UNKNOWN.value,
                "reason": "planner-generated criteria are advisory"})
            saw_unknown = True
            continue
        if criterion.provenance != CriterionProvenance.AUTHORIZED_APPROVER.value:
            per_criterion.append({
                "criterion_id": criterion.criterion_id,
                "verdict": CriterionVerdict.UNKNOWN.value,
                "reason": "unrecognized provenance"})
            saw_unknown = True
            continue
        verdict = _evaluate_predicate(criterion, evidence)
        per_criterion.append({"criterion_id": criterion.criterion_id,
                              "verdict": verdict.value,
                              "reason": "evaluated"})
        if verdict is CriterionVerdict.UNSATISFIED:
            saw_unsatisfied = True
        elif verdict is CriterionVerdict.UNKNOWN:
            saw_unknown = True
    if saw_unsatisfied:
        overall = CriterionVerdict.UNSATISFIED
    elif saw_unknown:
        overall = CriterionVerdict.UNKNOWN
    else:
        overall = CriterionVerdict.SATISFIED
    return {"overall": overall.value, "criteria": per_criterion,
            "contract_version": CONTRACT_VERSION}


__all__ = [
    "CONTRACT_VERSION",
    "CriterionProvenance",
    "CriterionVerdict",
    "SemanticCriterion",
    "compute_contract_digest",
    "evaluate_success_contract",
]