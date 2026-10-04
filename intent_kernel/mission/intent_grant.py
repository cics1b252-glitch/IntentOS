"""J1.4 — Explicit Intent Authority Grant contract.

Five states that MUST NOT collapse:

    USER INTENT              what the user wants
    INTERPRETED REQUIREMENTS what the analyzer believes is needed
    PROPOSED AUTHORITY       bounded scope the system proposes requesting
    EXPLICIT AUTHORITY GRANT exact bounded scope explicitly approved
    CANONICAL INTENT AUTHORITY durable authority established from that grant

    INTERPRETATION != AUTHORITY
    PROPOSED_AUTHORITY != GRANTED_AUTHORITY
    FRAMEWORK_DEFAULT != AUTHORITY
    HARDCODED_GRANTED != AUTHORITY
    DISCOVERABLE_CAPABILITY != AUTHORIZED_CAPABILITY

Exact-scope binding (§3/§11):

    PROPOSED_SCOPE_DIGEST == APPROVED_SCOPE_DIGEST == ESTABLISHED_AUTHORITY_SCOPE_DIGEST

No field may expand between proposal, approval and establishment. A grant whose
scope digest does not match its ceiling fails closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from intent_kernel.mission.intent_authority import (
    IntentAuthorityError,
    IntentAuthorityRecord,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling


def compute_scope_digest(ceiling: IntentCeiling) -> str:
    """Canonical digest over the EXACT bounded authority scope.

    Deliberately excludes source/approval metadata so that proposal,
    approval and establishment of the SAME scope yield the SAME digest.
    """
    return hashlib.sha256(
        json.dumps(
            ceiling.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProposedIntentAuthority:
    """A bounded scope PROPOSAL for human approval.

    IS NOT AUTHORITY. Cannot authorize execution, cannot set GRANTED, and
    cannot be established without an explicit approval transition.
    """

    ceiling: IntentCeiling
    scope_digest: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.ceiling, IntentCeiling):
            raise IntentAuthorityError("proposal ceiling must be an IntentCeiling")
        if not self.ceiling.is_constraining:
            raise IntentAuthorityError(
                "proposed authority must contain at least one explicit "
                "constraining dimension"
            )
        expected = compute_scope_digest(self.ceiling)
        if self.scope_digest != expected:
            raise IntentAuthorityError(
                "proposed scope_digest does not match the proposed scope"
            )

    @classmethod
    def propose(
        cls, ceiling: IntentCeiling, rationale: str = ""
    ) -> "ProposedIntentAuthority":
        return cls(
            ceiling=ceiling,
            scope_digest=compute_scope_digest(ceiling),
            rationale=str(rationale or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ceiling": self.ceiling.to_dict(),
            "scope_digest": self.scope_digest,
            "rationale": self.rationale,
        }


def propose_intent_authority(
    *,
    allow_capabilities=(),
    allowed_operations=(),
    target_scope=(),
    max_risk_level: str = "",
    max_side_effect: str = "",
    require_verification: Optional[bool] = None,
    valid_from: str = "",
    valid_until: str = "",
    rationale: str = "",
) -> ProposedIntentAuthority:
    """Build a bounded proposal (never authority)."""
    return ProposedIntentAuthority.propose(
        IntentCeiling(
            allow_capabilities=tuple(allow_capabilities or ()),
            allowed_operations=tuple(allowed_operations or ()),
            target_scope=tuple(target_scope or ()),
            max_risk_level=str(max_risk_level or ""),
            max_side_effect=str(max_side_effect or ""),
            require_verification=require_verification,
            valid_from=str(valid_from or ""),
            valid_until=str(valid_until or ""),
        ),
        rationale=rationale,
    )


@dataclass(frozen=True)
class IntentAuthorityGrant:
    """EXACT bounded scope explicitly approved by an authority source.

    A grant is an approval artifact, not yet durable authority: it must still
    pass through :func:`establish_intent_authority_from_grant`.
    """

    ceiling: IntentCeiling
    approved_scope_digest: str
    authority_source_type: str
    authority_source_identity: str
    approved_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.ceiling, IntentCeiling):
            raise IntentAuthorityError("grant ceiling must be an IntentCeiling")
        if not self.ceiling.is_constraining:
            raise IntentAuthorityError(
                "granted authority must contain at least one explicit "
                "constraining dimension"
            )
        for label in ("authority_source_type", "authority_source_identity",
                      "approved_at"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise IntentAuthorityError(f"{label} must be a non-empty string")
        expected = compute_scope_digest(self.ceiling)
        if self.approved_scope_digest != expected:
            raise IntentAuthorityError(
                "approved_scope_digest does not match the granted scope "
                "(scope altered after approval)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ceiling": self.ceiling.to_dict(),
            "approved_scope_digest": self.approved_scope_digest,
            "authority_source_type": self.authority_source_type,
            "authority_source_identity": self.authority_source_identity,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntentAuthorityGrant":
        if not isinstance(data, Mapping):
            raise IntentAuthorityError("intent_authority_grant must be a mapping")
        raw = data.get("ceiling")
        if not isinstance(raw, Mapping):
            raise IntentAuthorityError("grant.ceiling must be a mapping")
        try:
            ceiling = IntentCeiling.from_dict(raw)
        except (ValueError, TypeError) as exc:
            raise IntentAuthorityError(f"malformed grant ceiling: {exc}")
        return cls(
            ceiling=ceiling,
            approved_scope_digest=str(data.get("approved_scope_digest", "") or ""),
            authority_source_type=str(data.get("authority_source_type", "") or ""),
            authority_source_identity=str(
                data.get("authority_source_identity", "") or ""
            ),
            approved_at=str(data.get("approved_at", "") or ""),
        )


def approve_intent_authority(
    proposal: ProposedIntentAuthority,
    *,
    authority_source_type: str,
    authority_source_identity: str,
    approved_at: str,
) -> IntentAuthorityGrant:
    """PROPOSED -> EXPLICITLY_APPROVED.

    The approval binds to the EXACT proposed scope. Nothing may expand here.
    A generic confirmation detached from the structured proposal cannot reach
    this function: it requires the proposal object and its scope digest.
    """
    if not isinstance(proposal, ProposedIntentAuthority):
        raise IntentAuthorityError(
            "approval requires an explicit ProposedIntentAuthority; a generic "
            "confirmation is not an authority grant"
        )
    return IntentAuthorityGrant(
        ceiling=proposal.ceiling,
        approved_scope_digest=proposal.scope_digest,
        authority_source_type=str(authority_source_type or ""),
        authority_source_identity=str(authority_source_identity or ""),
        approved_at=str(approved_at or ""),
    )


def establish_intent_authority_from_grant(
    grant: IntentAuthorityGrant, *, now_iso: str
) -> IntentAuthorityRecord:
    """EXPLICITLY_APPROVED -> CANONICAL_INTENT_AUTHORITY.

    Verifies the approved scope digest still matches the grant's ceiling
    (O/P: altered or broadened scope fails closed), then establishes durable
    authority with truthful source provenance.
    """
    if not isinstance(grant, IntentAuthorityGrant):
        raise IntentAuthorityError(
            "canonical authority requires an explicit IntentAuthorityGrant"
        )
    if compute_scope_digest(grant.ceiling) != grant.approved_scope_digest:
        raise IntentAuthorityError(
            "established scope does not match approved scope"
        )
    from intent_kernel.mission.intent_authority import (
        establish_intent_authority,
    )
    return establish_intent_authority(
        ceiling=grant.ceiling,
        source_type=grant.authority_source_type,
        source_identity=grant.authority_source_identity,
        established_at=grant.approved_at,
        now_iso=now_iso,
    )


__all__ = [
    "IntentAuthorityError",
    "IntentAuthorityGrant",
    "ProposedIntentAuthority",
    "approve_intent_authority",
    "compute_scope_digest",
    "establish_intent_authority_from_grant",
    "propose_intent_authority",
]