"""FRONT-TP-09K: trusted semantic evaluator.

    CALLER-SUPPLIED VERDICT != TRUSTED EVALUATION
    POSSESSION OF A TOKEN   == OPERATOR APPROVAL (only via the registry)
    SATISFIED (objective)   != EXECUTION AUTHORITY

This module layers AUTHENTICATED approval and mission binding on top of the
inert :mod:`intent_kernel.mission.success_contract`. Evaluation runs ONLY when
a valid, single-use approval exists that is bound to:

  * the exact mission-contract digest (over the criterion set + mission id),
  * the mission identity, and
  * the evaluation version.

Design constraints (all fail closed):
  * No approval -> TrustedEvaluationError, never a verdict.
  * Criteria changing after approval -> digest mismatch -> refused.
  * Planner-only provenance stays UNKNOWN (advisory).
  * Missing, stale, conflicting or untrusted evidence never yields SATISFIED.
  * The result is a typed, internally-constructed value; a caller cannot pass
    in a verdict.
  * This evaluator grants NO execution authority and is NOT wired into
    MissionCompletionGate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from intent_kernel.mission.success_contract import (
    CONTRACT_VERSION,
    CriterionVerdict,
    SemanticCriterion,
    compute_contract_digest,
    evaluate_success_contract,
)
from intent_kernel.preview.trusted_approval import (
    TrustedApprovalError,
    require_semantic_approval,
)

#: Evidence keys that, when present and true, invalidate a SATISFIED verdict.
_STALE_MARKER = "__stale__"
_CONFLICT_MARKER = "__conflict__"


class TrustedEvaluationError(RuntimeError):
    """Evaluation attempted without valid authenticated approval."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def compute_mission_contract_digest(
    criteria: List[SemanticCriterion], mission_id: str,
) -> str:
    """Deterministic digest over mission identity + the full criterion set.

    Order-independent: two identical criterion sets hash identically, and any
    change to any criterion (or the mission id) changes the digest.
    """
    parts = sorted(compute_contract_digest(c) for c in criteria)
    payload = {"mission_id": mission_id, "criteria": parts}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrustedSemanticResult:
    """Typed result of a TRUSTED evaluation. Constructed internally only."""

    overall: str
    mission_id: str
    evaluation_version: str
    contract_digest: str
    trusted: bool
    criteria: Tuple[Dict[str, Any], ...] = ()
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall,
            "mission_id": self.mission_id,
            "evaluation_version": self.evaluation_version,
            "contract_digest": self.contract_digest,
            "trusted": self.trusted,
            "criteria": [dict(c) for c in self.criteria],
            "reason": self.reason,
        }


class TrustedSemanticEvaluator:
    """Authenticated, mission-bound evaluation of a semantic success contract.

    Stateless. Approval is proven by consuming a single-use token from the
    trusted-approval registry; the evaluator never mints, infers or accepts a
    caller-authored verdict.
    """

    def evaluate(
        self,
        criteria: List[SemanticCriterion],
        evidence: Dict[str, Any],
        approval_token: str,
        mission_id: str,
        evaluation_version: str = CONTRACT_VERSION,
        now: Optional[Any] = None,
    ) -> TrustedSemanticResult:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise TrustedEvaluationError("mission-id-required")
        if not criteria:
            raise TrustedEvaluationError("no-criteria")

        contract_digest = compute_mission_contract_digest(criteria, mission_id)

        # Authenticate FIRST. Any mismatch/expiry/replay -> fail closed.
        try:
            require_semantic_approval(
                approval_token,
                contract_digest,
                mission_id,
                evaluation_version,
                now=now,
            )
        except TrustedApprovalError as exc:
            raise TrustedEvaluationError(f"approval:{exc.code}") from exc

        # Reuse the inert, deterministic evaluator for predicate semantics.
        base = evaluate_success_contract(criteria, evidence)
        overall = base["overall"]
        reason = "evaluated"

        # Trust gates that can only DOWNGRADE, never upgrade.
        if evidence.get(_STALE_MARKER) is True:
            overall = CriterionVerdict.UNKNOWN.value
            reason = "stale-evidence"
        elif evidence.get(_CONFLICT_MARKER) is True:
            overall = CriterionVerdict.UNKNOWN.value
            reason = "conflicting-evidence"
        # Any criterion left UNKNOWN keeps the whole result non-SATISFIED,
        # already handled by evaluate_success_contract's aggregation.

        return TrustedSemanticResult(
            overall=overall,
            mission_id=mission_id,
            evaluation_version=evaluation_version,
            contract_digest=contract_digest,
            trusted=True,
            criteria=tuple(base["criteria"]),
            reason=reason,
        )


__all__ = [
    "TrustedEvaluationError",
    "TrustedSemanticResult",
    "TrustedSemanticEvaluator",
    "compute_mission_contract_digest",
]
