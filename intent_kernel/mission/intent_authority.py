"""J1.2 — Canonical Intent Authority Source.

Establishes the bounded authority that must PRECEDE planning:

    USER / AUTHORITY SOURCE
      -> CANONICAL INTENT AUTHORITY  (IntentCeiling + attested provenance)
        -> MISSION
          -> PLANNER PROPOSAL
            -> PLAN <= INTENT PROOF
              -> CANONICAL PLAN

CANONICAL POLICY (OPTION_C): NO CANONICAL INTENT AUTHORITY = NO PRODUCTIVE
AUTHORITY. Absence never means unlimited authority.

Authority is the IntentCeiling itself. IntentAuthorityRecord ATTESTS where
that ceiling came from; the record is provenance, never authority:

    PROVENANCE_RECORD != AUTHORITY

Nothing here is inferred from planner output, agent output, mission objective
text, default capability/agent, available tools, delegation, execution request,
operational budget or historical behavior. The ceiling is always supplied
explicitly by the caller and validated fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from intent_kernel.mission.intent_ceiling import (
    IntentCeiling,
    proof_plan_action_against_ceiling,
    _check_temporal_validity,
)
from intent_kernel.mission.quantity import (
    prove_plan_quantities_against_authority,
    QuantityAuthorityRecord,
)


class IntentAuthorityError(Exception):
    """Intent authority establishment or validation failed closed."""


@dataclass(frozen=True)
class IntentAuthorityRecord:
    """Attested provenance of an established intent authority.

    The AUTHORITY is ``ceiling``. This record only proves its origin,
    binding and establishment instant. It confers nothing by itself.
    """

    source_type: str
    source_identity: str
    established_at: str
    ceiling: IntentCeiling
    authority_digest: str

    def __post_init__(self) -> None:
        for label in ("source_type", "source_identity", "established_at"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise IntentAuthorityError(f"{label} must be a non-empty string")
        if not isinstance(self.ceiling, IntentCeiling):
            raise IntentAuthorityError("ceiling must be an IntentCeiling")
        if not self.ceiling.is_constraining:
            raise IntentAuthorityError(
                "intent authority ceiling must contain at least one explicit "
                "constraining dimension; absence is never unlimited authority"
            )
        expected = self.compute_authority_digest()
        if not isinstance(self.authority_digest, str) or not self.authority_digest:
            raise IntentAuthorityError("authority_digest must be a non-empty string")
        if self.authority_digest != expected:
            raise IntentAuthorityError(
                "authority_digest does not match the attested authority"
            )

    @property
    def ceilings(self) -> Tuple:
        """Return quantity ceilings from the ceiling for quantity proof."""
        return self.ceiling.quantity_ceilings

    def compute_authority_digest(self) -> str:
        """Deterministic digest over the attested authority (no clock reads)."""
        return hashlib.sha256(
            json.dumps(
                [
                    str(self.source_type or ""),
                    str(self.source_identity or ""),
                    str(self.established_at or ""),
                    self.ceiling.to_dict(),
                ],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_identity": self.source_identity,
            "established_at": self.established_at,
            "ceiling": self.ceiling.to_dict(),
            "authority_digest": self.authority_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntentAuthorityRecord":
        if not isinstance(data, Mapping):
            raise IntentAuthorityError("intent_authority must be a mapping")
        ceiling_raw = data.get("ceiling")
        if not isinstance(ceiling_raw, Mapping):
            raise IntentAuthorityError("intent_authority.ceiling must be a mapping")
        try:
            ceiling = IntentCeiling.from_dict(ceiling_raw)
        except (ValueError, TypeError) as exc:
            raise IntentAuthorityError(f"malformed intent authority ceiling: {exc}")
        return cls(
            source_type=str(data.get("source_type", "") or ""),
            source_identity=str(data.get("source_identity", "") or ""),
            established_at=str(data.get("established_at", "") or ""),
            ceiling=ceiling,
            authority_digest=str(data.get("authority_digest", "") or ""),
        )


def establish_intent_authority(
    *,
    ceiling: IntentCeiling,
    source_type: str,
    source_identity: str,
    established_at: str,
    now_iso: str = "",
) -> IntentAuthorityRecord:
    """Establish canonical intent authority from an EXPLICIT bounded ceiling.

    This is the authority-establishment boundary. It never synthesizes the
    ceiling from planner/agent/execution output: the caller must supply it.

    Fail-closed:
      - empty/unbounded ceiling -> error (absence != unlimited)
      - temporal ceiling with missing/invalid clock -> error
      - expired / not-yet-valid ceiling -> error
    """
    if not isinstance(ceiling, IntentCeiling):
        raise IntentAuthorityError("ceiling must be an IntentCeiling")
    if not ceiling.is_constraining:
        raise IntentAuthorityError(
            "explicit bounded ceiling required: an empty ceiling is not authority"
        )
    for label, value in (("source_type", source_type),
                         ("source_identity", source_identity),
                         ("established_at", established_at)):
        if not isinstance(value, str) or not value.strip():
            raise IntentAuthorityError(f"{label} must be a non-empty string")

    # Temporal authority must be evaluable NOW (UNKNOWN != VALID).
    if ceiling.valid_from or ceiling.valid_until:
        ok, reason = _check_temporal_validity(ceiling, now_iso)
        if not ok:
            raise IntentAuthorityError(f"intent authority not currently valid: {reason}")

    provisional = IntentAuthorityRecord.__new__(IntentAuthorityRecord)
    object.__setattr__(provisional, "source_type", source_type)
    object.__setattr__(provisional, "source_identity", source_identity)
    object.__setattr__(provisional, "established_at", established_at)
    object.__setattr__(provisional, "ceiling", ceiling)
    object.__setattr__(provisional, "authority_digest", "")
    digest = provisional.compute_authority_digest()
    return IntentAuthorityRecord(
        source_type=source_type,
        source_identity=source_identity,
        established_at=established_at,
        ceiling=ceiling,
        authority_digest=digest,
    )


def prove_plan_actions_against_authority(
    authority: Optional[IntentAuthorityRecord],
    actions,
    *,
    now_iso: str,
    quantity_authority: Optional[QuantityAuthorityRecord] = None,
    plan_quantities: Optional[List[Any]] = None,
) -> None:
    """Prove every proposed action <= established intent authority.

    Fail-closed: absent authority denies. Any violating action raises before
    the plan can become authority-bearing. One valid action never authorizes
    another.
    """
    if authority is None:
        raise IntentAuthorityError(
            "no canonical intent authority: mission cannot acquire productive "
            "authority (absence is never unlimited authority)"
        )
    for action in actions:
        ok, reason = proof_plan_action_against_ceiling(
            authority.ceiling,
            capability=action.get("capability", "") or "",
            operation=action.get("operation", "") or "",
            target=action.get("target", "") or "",
            risk_level=action.get("risk_level", "") or "",
            side_effect=action.get("side_effect", "") or "",
            verification_required=bool(action.get("verification_required", False)),
            now_iso=now_iso,
            quantity=action.get("quantity"),
        )
        if not ok:
            raise IntentAuthorityError(
                "plan action outside established intent authority: "
                f"action_id={action.get('action_id')} reason={reason}"
            )

    # Prove quantities against quantity authority (C2/C3/G1)
    if plan_quantities:
        from intent_kernel.mission.quantity import prove_plan_quantities_against_authority
        prove_plan_quantities_against_authority(quantity_authority, plan_quantities)


__all__ = [
    "IntentAuthorityError",
    "IntentAuthorityRecord",
    "establish_intent_authority",
    "prove_plan_actions_against_authority",
    "QuantityAuthorityRecord",
]