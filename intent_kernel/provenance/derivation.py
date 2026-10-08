"""FRONT-F.M4.1 — Per-edge Authority Derivation Evidence (read-only).

Explains, for each delegation edge and authority dimension:

    PARENT AUTHORITY -> REQUESTED CHILD AUTHORITY -> DIMENSION DERIVATION
    -> ACCEPTED / REJECTED -> REASON

CANONICAL INVARIANT
    AUTHORITY_DERIVATION_EVIDENCE != AUTHORITY
    PROVENANCE_RECORD        != AUTHORITY
    POWER_TO_EXPLAIN         != POWER_TO_ACT

Deleting, altering, replaying, forging or presenting this evidence MUST NOT
create, amplify, revoke or resurrect productive authority.

NO SECOND AUTHORITY ENGINE
    This module NEVER decides whether a delegation is valid. It has no walker,
    no subset prover, no eligibility logic and no independent judgment. Every
    ACCEPTED/REJECTED verdict and every reason recorded here is COPIED from a
    decision already produced by the canonical authority subsystem
    (``intent_kernel.mission.delegation``) and passed in by its caller.

    The only values computed here are (a) the deterministic evidence digest and
    (b) pure projections of already-durable grant facts (parent/child scope),
    which are read-only observations, not authority claims.

Rejected-edge note: a rejected derivation leaves no durable grant, so its
evidence must be supplied by the holder of the canonical outcome. This module
provides the typed record constructor for that purpose and refuses to derive a
verdict on its own.

Quantity: represented only as a generic, opaque dimension payload so a future
canonical quantity derivation result can be consumed. OBSERVED_QUANTITY !=
AUTHORIZED_QUANTITY; quantity evidence never raises a ceiling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Stable vocabulary mirroring the canonical authority reason strings. This
# module does not define new authority semantics; it only labels dimensions.
DIMENSION_CAPABILITY = "capability"
DIMENSION_OPERATION = "operation"
DIMENSION_TARGET = "target"
DIMENSION_RESOURCE = "resource"
DIMENSION_RISK = "risk_level"
DIMENSION_SIDE_EFFECT = "side_effect"
DIMENSION_TIMEOUT = "timeout"
DIMENSION_VERIFICATION = "verification"
DIMENSION_LIFETIME = "lifetime"
DIMENSION_MISSION_PIN = "mission_pin"
DIMENSION_GENERATION = "generation"
DIMENSION_QUANTITY = "quantity"

DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED = "REJECTED"

# Canonical reason -> dimension. Evidence classification only; no judgment.
_REASON_DIMENSION: Dict[str, str] = {
    "capability-escalation": DIMENSION_CAPABILITY,
    "child-binding-outside-grant:capability": DIMENSION_CAPABILITY,
    "operation-escalation": DIMENSION_OPERATION,
    "target-escalation": DIMENSION_TARGET,
    "child-binding-outside-grant:target": DIMENSION_TARGET,
    "resource-escalation": DIMENSION_RESOURCE,
    "child-binding-outside-grant:resource": DIMENSION_RESOURCE,
    "constraint-weakening:risk": DIMENSION_RISK,
    "constraint-weakening:side-effect": DIMENSION_SIDE_EFFECT,
    "constraint-weakening:timeout": DIMENSION_TIMEOUT,
    "constraint-weakening:verification": DIMENSION_VERIFICATION,
    "lifetime-extension": DIMENSION_LIFETIME,
    "mission-pin-mismatch:root": DIMENSION_MISSION_PIN,
    "mission-pin-mismatch:parent": DIMENSION_MISSION_PIN,
    "root-ceiling-divergence": DIMENSION_GENERATION,
    "quantity-escalation": DIMENSION_QUANTITY,
    # C2/C3/G1.3 canonical quantity narrowing rejection.
    "constraint-weakening:quantity": DIMENSION_QUANTITY,
}

# Whole-scope ACCEPTED observation of a durable grant (not a single dimension).
DIMENSION_ACCEPTED_SCOPE = "accepted_scope"


def dimension_for_reason(reason: str) -> str:
    """Map a CANONICAL reason string to an evidence dimension label."""
    if not reason:
        return DIMENSION_CAPABILITY
    if reason in _REASON_DIMENSION:
        return _REASON_DIMENSION[reason]
    head = reason.split(":", 1)[0]
    return _REASON_DIMENSION.get(head, "unknown")


@dataclass(frozen=True)
class DerivationEvidenceRecord:
    """Immutable, typed per-edge derivation evidence. NOT authority."""

    mission_id: str
    parent_grant_id: str
    child_grant_id: str
    requested_child_identity: str
    dimension: str
    parent_value: Any
    requested_child_value: Any
    decision: str
    reason: str
    evidence_digest: str
    observed_at: str = ""
    canonical_reference: str = ""

    def __post_init__(self) -> None:
        for label in ("mission_id", "parent_grant_id", "requested_child_identity"):
            if not isinstance(getattr(self, label), str) or not getattr(self, label):
                raise ValueError(f"{label} must be a non-empty string")
        if self.decision not in (DECISION_ACCEPTED, DECISION_REJECTED):
            raise ValueError("decision must be ACCEPTED or REJECTED")
        if self.dimension not in (
            set(_REASON_DIMENSION.values()) | {"unknown", DIMENSION_ACCEPTED_SCOPE}
        ):
            raise ValueError(f"unknown evidence dimension: {self.dimension}")
        expected = self.compute_evidence_digest()
        if self.evidence_digest != expected:
            raise ValueError(
                "evidence_digest does not match the recorded derivation"
            )

    def compute_evidence_digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    self.mission_id,
                    self.parent_grant_id,
                    self.child_grant_id,
                    self.requested_child_identity,
                    self.dimension,
                    self.parent_value,
                    self.requested_child_value,
                    self.decision,
                    self.reason,
                ],
                sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False, default=str,
            ).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "parent_grant_id": self.parent_grant_id,
            "child_grant_id": self.child_grant_id,
            "requested_child_identity": self.requested_child_identity,
            "dimension": self.dimension,
            "parent_value": self.parent_value,
            "requested_child_value": self.requested_child_value,
            "decision": self.decision,
            "reason": self.reason,
            "evidence_digest": self.evidence_digest,
            "observed_at": self.observed_at,
            "canonical_reference": self.canonical_reference,
        }


def record_derivation_evidence(
    *,
    mission_id: str,
    parent_grant_id: str,
    requested_child_identity: str,
    canonical_ok: bool,
    canonical_reason: str = "",
    dimension: str = "",
    parent_value: Any = None,
    requested_child_value: Any = None,
    child_grant_id: str = "",
    observed_at: str = "",
    canonical_reference: str = "",
) -> DerivationEvidenceRecord:
    """Record a derivation outcome ALREADY DECIDED by canonical authority.

    ``canonical_ok`` / ``canonical_reason`` MUST be the verbatim result of the
    canonical authority subsystem. This function performs no judgment: it does
    not re-evaluate the edge, and a caller cannot use it to manufacture an
    ACCEPTED verdict that canonical authority did not produce.
    """
    if not isinstance(canonical_ok, bool):
        raise ValueError("canonical_ok must be the canonical boolean verdict")
    decision = DECISION_ACCEPTED if canonical_ok else DECISION_REJECTED
    dim = dimension or dimension_for_reason(canonical_reason)
    partial = DerivationEvidenceRecord.__new__(DerivationEvidenceRecord)
    for key, value in (
        ("mission_id", mission_id),
        ("parent_grant_id", parent_grant_id),
        ("child_grant_id", child_grant_id),
        ("requested_child_identity", requested_child_identity),
        ("dimension", dim),
        ("parent_value", parent_value),
        ("requested_child_value", requested_child_value),
        ("decision", decision),
        ("reason", canonical_reason),
        ("evidence_digest", ""),
        ("observed_at", observed_at),
        ("canonical_reference", canonical_reference),
    ):
        object.__setattr__(partial, key, value)
    return DerivationEvidenceRecord(
        mission_id=mission_id,
        parent_grant_id=parent_grant_id,
        child_grant_id=child_grant_id,
        requested_child_identity=requested_child_identity,
        dimension=dim,
        parent_value=parent_value,
        requested_child_value=requested_child_value,
        decision=decision,
        reason=canonical_reason,
        evidence_digest=partial.compute_evidence_digest(),
        observed_at=observed_at,
        canonical_reference=canonical_reference,
    )


def parent_scope_facts(grant: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Read-only projection of a durable parent grant (a FACT, not authority)."""
    if not isinstance(grant, Mapping):
        return {}
    return {
        "capability": list(grant.get("delegation_allowed_capabilities", ()) or ()),
        "resource": [
            dict(item) if isinstance(item, Mapping) else item
            for item in (grant.get("delegation_allowed_resources", ()) or ())
        ],
        "target": list(grant.get("delegation_allowed_targets", ()) or ()),
        "risk_level": str(grant.get("delegation_max_risk_level", "") or ""),
        "side_effect": str(grant.get("delegation_max_side_effect", "") or ""),
        "timeout_seconds": grant.get("delegation_max_timeout_seconds", 0),
        "require_verification": grant.get("delegation_require_verification", None),
        "expires_at": str(grant.get("delegation_expires_at", "") or ""),
        "root_mission_id": str(grant.get("delegation_root_mission_id", "") or ""),
        "root_generation": grant.get("delegation_root_generation", 0),
        "grant_id": str(grant.get("delegation_id", "") or ""),
        "state": str(grant.get("delegation_state", "") or ""),
    }


def explain_accepted_edges(
    mission_data: Mapping[str, Any],
) -> List[DerivationEvidenceRecord]:
    """Explain ACCEPTED edges already present in a durable mission record.

    Purely read-only: durable grants ARE the canonical accepted outcome, so an
    ACCEPTED record here restates canonical truth rather than re-deriving it.
    Rejected edges are never inferred here.
    """
    from intent_kernel.mission.delegation import grant_view

    states = mission_data.get("action_states", {})
    if not isinstance(states, Mapping):
        return []
    out: List[DerivationEvidenceRecord] = []
    for action_id, action in sorted(states.items()):
        if not isinstance(action, Mapping):
            continue
        grant = grant_view(action)
        if grant is None:
            continue
        parent = parent_scope_facts(grant)
        out.append(
            _accepted_record(mission_data, action_id, grant, parent)
        )
    return out


def _accepted_record(
    mission_data: Mapping[str, Any],
    action_id: str,
    grant: Mapping[str, Any],
    parent: Mapping[str, Any],
) -> DerivationEvidenceRecord:
    """Build one ACCEPTED record; ``dimension`` stays canonical-vocabulary."""
    partial = DerivationEvidenceRecord.__new__(DerivationEvidenceRecord)
    for key, value in (
        ("mission_id", str(mission_data.get("mission_id", "") or "")),
        ("parent_grant_id", str(grant.get("delegation_parent_delegation_id", "")
                                or "ROOT")),
        ("child_grant_id", str(grant.get("delegation_id", "") or "")),
        ("requested_child_identity", str(action_id)),
        ("dimension", DIMENSION_ACCEPTED_SCOPE),
        ("parent_value", dict(parent)),
        ("requested_child_value", {
            "capability": list(grant.get("delegation_allowed_capabilities", ()) or ()),
            "target": list(grant.get("delegation_allowed_targets", ()) or ()),
        }),
        ("decision", DECISION_ACCEPTED),
        ("reason", "durable-grant-present"),
        ("evidence_digest", ""),
        ("observed_at", ""),
        ("canonical_reference", f"durable_action_states.{action_id}"),
    ):
        object.__setattr__(partial, key, value)
    return DerivationEvidenceRecord(
        mission_id=partial.mission_id,
        parent_grant_id=partial.parent_grant_id,
        child_grant_id=partial.child_grant_id,
        requested_child_identity=partial.requested_child_identity,
        dimension=DIMENSION_ACCEPTED_SCOPE,
        parent_value=partial.parent_value,
        requested_child_value=partial.requested_child_value,
        decision=DECISION_ACCEPTED,
        reason="durable-grant-present",
        evidence_digest=partial.compute_evidence_digest(),
        canonical_reference=partial.canonical_reference,
    )


__all__ = [
    "DECISION_ACCEPTED",
    "DECISION_REJECTED",
    "DerivationEvidenceRecord",
    "dimension_for_reason",
    "explain_accepted_edges",
    "parent_scope_facts",
    "record_derivation_evidence",
]