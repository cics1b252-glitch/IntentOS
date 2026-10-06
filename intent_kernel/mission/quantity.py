"""C2/C3/G1 — Canonical Quantity Authority.

Quantity type, applicability state machine, intent quantity authority,
plan quantity proof, delegated quantity ceiling (C2), C1 request binding,
C3 pre-effect enforcement, and G1 provenance.

Canonical invariants:

OPERATIONAL_BUDGET != EFFECT_AUTHORITY
QUOTA_POSSESSION != USER_AUTHORITY
OBSERVED_QUANTITY != AUTHORIZED_QUANTITY

EFFECT_QUANTITY
<=
ACTION_QUANTITY_CEILING
<=
DELEGATED_QUANTITY_CEILING
<=
PARENT_DELEGATABLE_QUANTITY_CEILING
<=
VALID_INTENT_QUANTITY_AUTHORITY
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple


class QuantityError(ValueError):
    """Quantity authority establishment or validation failed closed."""


class QuantityDimension(str, Enum):
    """Closed set of supported quantity dimensions.

    Each dimension has a canonical unit. No unit inference.
    """
    MONETARY_AMOUNT = "monetary_amount"
    AFFECTED_OBJECTS = "affected_objects"
    RECIPIENT_COUNT = "recipient_count"
    ATTACHMENT_BYTES = "attachment_bytes"


# Canonical units per dimension. No unit inference.
DIMENSION_CANONICAL_UNIT: Dict[QuantityDimension, str] = {
    QuantityDimension.MONETARY_AMOUNT: "BRL_CENT",
    QuantityDimension.AFFECTED_OBJECTS: "COUNT",
    QuantityDimension.RECIPIENT_COUNT: "COUNT",
    QuantityDimension.ATTACHMENT_BYTES: "BYTE",
}


@dataclass(frozen=True, slots=True)
class Quantity:
    """Immutable typed quantity with dimension and canonical unit.

    Amount: integer >= 0, no float, no bool, no NaN.
    Unit: canonical for the dimension. No unit inference.
    """
    dimension: QuantityDimension
    amount: int
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, QuantityDimension):
            raise QuantityError("dimension must be a QuantityDimension")
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise QuantityError("amount must be an integer (no float, no bool)")
        if self.amount < 0:
            raise QuantityError("amount must be >= 0")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise QuantityError("unit must be a non-empty string")
        expected_unit = DIMENSION_CANONICAL_UNIT.get(self.dimension)
        if expected_unit and self.unit != expected_unit:
            raise QuantityError(f"unit must be '{expected_unit}' for dimension {self.dimension.value}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Quantity":
        if not isinstance(data, Mapping):
            raise QuantityError("Quantity must be a mapping")
        amount = data["amount"]
        # Fail closed on stringified numbers: no implicit conversion.
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise QuantityError(
                "malformed Quantity: amount must be an integer "
                "(no string, no float, no bool)"
            )
        try:
            return cls(
                dimension=QuantityDimension(data["dimension"]),
                amount=amount,
                unit=str(data["unit"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantityError(f"malformed Quantity: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "amount": self.amount,
            "unit": self.unit,
        }

    def same_dimension_and_unit(self, other: "Quantity") -> bool:
        return self.dimension == other.dimension and self.unit == other.unit

    def __le__(self, other: "Quantity") -> bool:
        if not self.same_dimension_and_unit(other):
            return False
        return self.amount <= other.amount


@dataclass(frozen=True, slots=True)
class QuantityCeiling:
    """Immutable quantity ceiling for a specific dimension/unit.

    Amount: integer >= 0. Zero means exactly zero quantity authorized.
    """
    quantity: Quantity

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Quantity):
            raise QuantityError("quantity must be a Quantity")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuantityCeiling":
        if not isinstance(data, Mapping):
            raise QuantityError("QuantityCeiling must be a mapping")
        try:
            return cls(quantity=Quantity.from_dict(data["quantity"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantityError(f"malformed QuantityCeiling: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {"quantity": self.quantity.to_dict()}


class ApplicabilityState(str, Enum):
    """Exhaustive applicability determination states.

    NOT_APPLICABLE — operation is non-quantitative (evidence: registry/semantics).
    AUTHORIZED — quantity-bearing, valid authority exists.
    UNPROVEN — quantity-bearing, authority absent (DEFAULT DENY).
    INVALID — malformed/tampered quantity (ALWAYS DENY).
    UNKNOWN — applicability indeterminate (ALWAYS DENY).
    """
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AUTHORIZED = "AUTHORIZED"
    UNPROVEN = "UNPROVEN"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ApplicabilityDetermination:
    """Result of quantity applicability determination.

    Includes the state and, when applicable, the required quantity dimension.
    """
    state: ApplicabilityState
    dimension: Optional[QuantityDimension] = None
    reason: str = ""

    @classmethod
    def not_applicable(cls) -> "ApplicabilityDetermination":
        return cls(state=ApplicabilityState.NOT_APPLICABLE)

    @classmethod
    def authorized(cls, dimension: QuantityDimension) -> "ApplicabilityDetermination":
        return cls(state=ApplicabilityState.AUTHORIZED, dimension=dimension)

    @classmethod
    def unproven(cls, dimension: QuantityDimension, reason: str = "") -> "ApplicabilityDetermination":
        return cls(state=ApplicabilityState.UNPROVEN, dimension=dimension, reason=reason)

    @classmethod
    def invalid(cls, dimension: Optional[QuantityDimension], reason: str) -> "ApplicabilityDetermination":
        return cls(state=ApplicabilityState.INVALID, dimension=dimension, reason=reason)

    @classmethod
    def unknown(cls, dimension: Optional[QuantityDimension], reason: str) -> "ApplicabilityDetermination":
        return cls(state=ApplicabilityState.UNKNOWN, dimension=dimension, reason=reason)


class QuantityApplicabilityRegistry:
    """Canonical registry of operation quantity applicability.

    C2/C3/G1.1 §3: NOT_APPLICABLE requires POSITIVE PROOF that the operation
    is non-quantitative. Missing metadata is NEVER NOT_APPLICABLE — it is
    UNKNOWN, which always denies.

    This is a read-only registry: it declares semantics, it never grants
    quantity authority.
    """

    __slots__ = ("_by_operation",)

    def __init__(self, declarations: Optional[Mapping[str, Any]] = None) -> None:
        self._by_operation: Dict[str, Any] = {}
        for key, value in (declarations or {}).items():
            self.declare(key, value)

    def declare(self, operation: str, declaration: Any) -> None:
        """Declare applicability for one exact operation string.

        Accepted declarations:
          - ``None``                       -> positive NOT_APPLICABLE proof
          - ``QuantityDimension``           -> AUTHORIZED, that dimension
          - ``(ApplicabilityState, dim)``   -> explicit state
        """
        if not isinstance(operation, str) or not operation.strip():
            raise QuantityError("operation must be a non-empty string")
        self._by_operation[operation] = declaration

    def is_declared(self, operation: str) -> bool:
        return operation in self._by_operation

    def resolve(self, operation: str) -> ApplicabilityDetermination:
        """Resolve applicability. Undeclared -> UNKNOWN (never NOT_APPLICABLE)."""
        if not isinstance(operation, str) or not operation.strip():
            return ApplicabilityDetermination.unknown(
                None, "missing operation semantics"
            )
        if operation not in self._by_operation:
            return ApplicabilityDetermination.unknown(
                None, f"undeclared operation semantics: {operation}"
            )
        declaration = self._by_operation[operation]
        if declaration is None:
            # Explicit positive proof of non-quantitative operation.
            return ApplicabilityDetermination.not_applicable()
        if isinstance(declaration, QuantityDimension):
            return ApplicabilityDetermination.authorized(declaration)
        if isinstance(declaration, ApplicabilityDetermination):
            return declaration
        return ApplicabilityDetermination.unknown(
            None, f"malformed applicability declaration: {declaration!r}"
        )


#: Process-wide default registry. Empty: every operation is UNKNOWN until a
#: capability owner declares its semantics positively. This is the
#: fail-closed default required by C2/C3/G1.1 §3.
DEFAULT_QUANTITY_APPLICABILITY = QuantityApplicabilityRegistry()

# C2/C3/G1.2 §6: canonical operation semantics that are POSITIVELY
# non-quantitative. Each entry is an explicit registry declaration backed by
# real operation semantics — NOT a permissive default and NOT a bypass.
#   READ : pure read; produces no bounded external quantity effect.
#   SIMULATED : the bridge's non-executing synthetic echo (G8); by
#               construction performs no external effect, so it carries no
#               effect quantity.
DEFAULT_QUANTITY_APPLICABILITY.declare("READ", None)
DEFAULT_QUANTITY_APPLICABILITY.declare("SIMULATED", None)


def resolve_quantity_applicability(
    operation: str,
    registry: Optional[QuantityApplicabilityRegistry] = None,
) -> ApplicabilityDetermination:
    """Resolve applicability from canonical operation semantics.

    Delegates to the registry. Undeclared/unknown lookup -> UNKNOWN.
    """
    active = registry if registry is not None else DEFAULT_QUANTITY_APPLICABILITY
    return active.resolve(operation)


def determine_applicability(
    capability: str,
    operation: str,
    capability_registry: Mapping[str, Any],
) -> ApplicabilityDetermination:
    """Legacy metadata-driven applicability determination.

    C2/C3/G1.1 §3: missing metadata must NOT become NOT_APPLICABLE. This
    helper now fails closed to UNKNOWN unless the metadata positively proves
    non-quantitative semantics (``quantity_dimensions`` explicitly empty) or
    positively declares a dimension.
    """
    cap_meta = capability_registry.get(capability)
    if cap_meta is None:
        return ApplicabilityDetermination.unknown(
            None, f"unregistered capability: {capability}"
        )

    if not hasattr(cap_meta, "quantity_dimensions"):
        # Absent metadata is UNKNOWN, never NOT_APPLICABLE.
        return ApplicabilityDetermination.unknown(
            None,
            f"no quantity applicability declaration for capability: {capability}",
        )

    quantity_dims = getattr(cap_meta, "quantity_dimensions")
    if quantity_dims is None or quantity_dims == ():
        # Explicit empty declaration = positive proof of non-quantitative.
        return ApplicabilityDetermination.not_applicable()

    dims = list(quantity_dims)
    if len(dims) != 1:
        # Ambiguous semantics -> UNKNOWN (never guessed).
        return ApplicabilityDetermination.unknown(
            None,
            f"ambiguous quantity dimensions for capability {capability}",
        )
    return ApplicabilityDetermination.authorized(dims[0])


@dataclass(frozen=True, slots=True)
class PlanQuantity:
    """Quantity declared by a plan action (from the C1-bound request)."""
    quantity: Quantity

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Quantity):
            raise QuantityError("quantity must be a Quantity")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanQuantity":
        if not isinstance(data, Mapping):
            raise QuantityError("PlanQuantity must be a mapping")
        try:
            return cls(quantity=Quantity.from_dict(data["quantity"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantityError(f"malformed PlanQuantity: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {"quantity": self.quantity.to_dict()}


def prove_plan_quantity_against_ceiling(
    plan_quantity: PlanQuantity,
    ceiling: QuantityCeiling,
) -> Tuple[bool, str]:
    """Pure proof: PLAN_QUANTITY <= QUANTITY_CEILING.

    Returns (True, "") if plan quantity is within ceiling.
    Returns (False, reason) if ceiling exceeded or mismatched.
    
    Zero ceiling amount means exactly zero quantity authorized (not unlimited).
    """
    if not plan_quantity.quantity.same_dimension_and_unit(ceiling.quantity):
        return False, "quantity-dimension-unit-mismatch"

    if plan_quantity.quantity.amount > ceiling.quantity.amount:
        return False, "quantity-escalation"

    return True, ""


@dataclass(frozen=True, slots=True)
class DelegatedQuantityCeiling:
    """Quantity ceiling carried by a delegation grant (C2).

    Child quantity must be <= parent delegatable quantity.
    """
    ceilings: Tuple[QuantityCeiling, ...] = ()

    def __post_init__(self) -> None:
        for c in self.ceilings:
            if not isinstance(c, QuantityCeiling):
                raise QuantityError("each ceiling must be a QuantityCeiling")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DelegatedQuantityCeiling":
        if not isinstance(data, Mapping):
            raise QuantityError("DelegatedQuantityCeiling must be a mapping")
        try:
            ceilings = tuple(
                QuantityCeiling.from_dict(c) for c in data.get("ceilings", [])
            )
            return cls(ceilings=ceilings)
        except (TypeError, ValueError) as exc:
            raise QuantityError(f"malformed DelegatedQuantityCeiling: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {"ceilings": [c.to_dict() for c in self.ceilings]}


@dataclass(frozen=True, slots=True)
class QuantityAuthorityRecord:
    """Provenance record for established quantity authority.

    The AUTHORITY is the ceilings. This record only proves origin.
    """
    source_type: str
    source_identity: str
    established_at: str
    ceilings: Tuple[QuantityCeiling, ...]
    authority_digest: str

    def __post_init__(self) -> None:
        for label in ("source_type", "source_identity", "established_at"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise QuantityError(f"{label} must be a non-empty string")
        if not isinstance(self.ceilings, tuple):
            raise QuantityError("ceilings must be a tuple")
        for c in self.ceilings:
            if not isinstance(c, QuantityCeiling):
                raise QuantityError("ceilings must contain QuantityCeiling objects")
        if not isinstance(self.authority_digest, str) or not self.authority_digest:
            raise QuantityError("authority_digest must be a non-empty string")
        expected = self.compute_authority_digest()
        if self.authority_digest != expected:
            raise QuantityError("authority_digest does not match the attested authority")

    def compute_authority_digest(self) -> str:
        import hashlib, json
        return hashlib.sha256(
            json.dumps(
                [
                    str(self.source_type or ""),
                    str(self.source_identity or ""),
                    str(self.established_at or ""),
                    [c.to_dict() for c in self.ceilings],
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
            "ceilings": [c.to_dict() for c in self.ceilings],
            "authority_digest": self.authority_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuantityAuthorityRecord":
        if not isinstance(data, Mapping):
            raise QuantityError("quantity_authority must be a mapping")
        try:
            ceilings = tuple(
                QuantityCeiling.from_dict(c) for c in data.get("ceilings", [])
            )
            return cls(
                source_type=str(data.get("source_type", "") or ""),
                source_identity=str(data.get("source_identity", "") or ""),
                established_at=str(data.get("established_at", "") or ""),
                ceilings=ceilings,
                authority_digest=str(data.get("authority_digest", "") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantityError(f"malformed quantity authority: {exc}")


def establish_quantity_authority(
    *,
    ceilings: Tuple[QuantityCeiling, ...],
    source_type: str,
    source_identity: str,
    established_at: str,
) -> QuantityAuthorityRecord:
    """Establish canonical quantity authority from explicit ceilings.

    Fail-closed:
      - empty ceilings -> error (absence != unlimited)
      - duplicate dimensions -> error
    """
    if not ceilings:
        raise QuantityError("at least one explicit quantity ceiling required")

    # Check for duplicate dimensions
    seen = set()
    for c in ceilings:
        dim_key = (c.quantity.dimension, c.quantity.unit)
        if dim_key in seen:
            raise QuantityError(f"duplicate quantity dimension/unit: {dim_key}")
        seen.add(dim_key)

    for label, value in (("source_type", source_type),
                         ("source_identity", source_identity),
                         ("established_at", established_at)):
        if not isinstance(value, str) or not value.strip():
            raise QuantityError(f"{label} must be a non-empty string")

    provisional = QuantityAuthorityRecord.__new__(QuantityAuthorityRecord)
    object.__setattr__(provisional, "source_type", source_type)
    object.__setattr__(provisional, "source_identity", source_identity)
    object.__setattr__(provisional, "established_at", established_at)
    object.__setattr__(provisional, "ceilings", ceilings)
    object.__setattr__(provisional, "authority_digest", "")
    digest = provisional.compute_authority_digest()
    return QuantityAuthorityRecord(
        source_type=source_type,
        source_identity=source_identity,
        established_at=established_at,
        ceilings=ceilings,
        authority_digest=digest,
    )


def prove_plan_quantities_against_authority(
    authority: Optional[QuantityAuthorityRecord],
    plan_quantities: List[Any],
) -> None:
    """Prove every plan quantity <= established quantity authority.

    Fail-closed: absent authority denies if any plan_quantity is quantity-bearing.
    Accepts PlanQuantity objects or dicts with 'quantity' key.
    """
    if authority is None:
        if plan_quantities:
            raise QuantityError("no canonical quantity authority: cannot authorize quantity-bearing actions")
        return

    for pq in plan_quantities:
        # Convert dict to PlanQuantity if needed
        if isinstance(pq, dict):
            try:
                q = Quantity.from_dict(pq["quantity"])
                pq_obj = PlanQuantity(q)
            except Exception as e:
                raise QuantityError(f"invalid plan quantity dict: {e}")
        elif isinstance(pq, PlanQuantity):
            pq_obj = pq
        else:
            raise QuantityError(f"plan quantity must be PlanQuantity or dict, got {type(pq)}")
        
        matched = False
        for ceiling in authority.ceilings:
            if pq_obj.quantity.same_dimension_and_unit(ceiling.quantity):
                ok, reason = prove_plan_quantity_against_ceiling(pq_obj, ceiling)
                if not ok:
                    raise QuantityError(f"plan quantity outside authority: {reason}")
                matched = True
                break
        if not matched:
            raise QuantityError(f"plan quantity dimension not covered by authority: {pq_obj.quantity.dimension.value}")


def prove_plan_quantity_against_delegated_ceiling(
    plan_quantity: PlanQuantity,
    delegated_ceiling: DelegatedQuantityCeiling,
) -> None:
    """Prove plan quantity <= delegated quantity ceiling (C2).

    Fail-closed: no match → DENY.
    In delegation, 0 = explicit ceiling of 0 (zero quantity allowed, not unlimited).
    """
    for ceiling in delegated_ceiling.ceilings:
        if plan_quantity.quantity.same_dimension_and_unit(ceiling.quantity):
            if plan_quantity.quantity.amount > ceiling.quantity.amount:
                raise QuantityError("plan quantity exceeds delegated ceiling: quantity-escalation")
            return
    # No matching ceiling in delegation
    raise QuantityError(f"plan quantity dimension not covered by delegated ceiling: {plan_quantity.quantity.dimension.value}")


# ---------------------------------------------------------------------------
# G1 — read-only observation / evidence (NEVER authority)
# ---------------------------------------------------------------------------


class QuantityComplianceStatus(str, Enum):
    """Post-effect observation classification.

    COMPLIANT — observed <= authorized, within bounds.
    VIOLATION — observed > authorized. The EFFECT ALREADY OCCURRED; this is
        never reported as "denied" or "prevented".
    UNKNOWN — actual quantity could not be established. Observed quantity is
        never invented from requested quantity.
    """

    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ObservedQuantity:
    """Read-only record of what an effect ACTUALLY produced."""

    dimension: QuantityDimension
    amount: int
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, QuantityDimension):
            raise QuantityError("dimension must be a QuantityDimension")
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise QuantityError("observed amount must be an integer")
        if self.amount < 0:
            raise QuantityError("observed amount must be >= 0")
        expected_unit = DIMENSION_CANONICAL_UNIT.get(self.dimension)
        if expected_unit and self.unit != expected_unit:
            raise QuantityError(
                f"observed unit must be '{expected_unit}' for dimension "
                f"{self.dimension.value}"
            )

    @classmethod
    def from_quantity(cls, quantity: Quantity) -> "ObservedQuantity":
        return cls(
            dimension=quantity.dimension,
            amount=quantity.amount,
            unit=quantity.unit,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "amount": self.amount,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class QuantityEvidence:
    """Read-only post-effect quantity evidence.

    PROVENANCE_RECORD != AUTHORITY. This binds what was authorized, what was
    requested, what was dispatched and what was observed. It grants nothing,
    repairs nothing, increases no ceiling, and never converts observation
    into authorization.
    """

    mission_id: str
    action_id: str
    authorized_quantity: Optional[Quantity]
    requested_quantity: Optional[Quantity]
    observed_quantity: Optional[ObservedQuantity]
    request_digest: str
    status: QuantityComplianceStatus
    reason: str = ""
    authority_reference: str = ""

    def __post_init__(self) -> None:
        for label in ("mission_id", "action_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise QuantityError(f"{label} must be a non-empty string")
        if not isinstance(self.request_digest, str):
            raise QuantityError("request_digest must be a string")
        if not isinstance(self.status, QuantityComplianceStatus):
            raise QuantityError("status must be a QuantityComplianceStatus")
        for label in ("authorized_quantity", "requested_quantity"):
            value = getattr(self, label)
            if value is not None and not isinstance(value, Quantity):
                raise QuantityError(f"{label} must be a Quantity or None")
        if self.observed_quantity is not None and not isinstance(
            self.observed_quantity, ObservedQuantity
        ):
            raise QuantityError("observed_quantity must be ObservedQuantity or None")
        # UNKNOWN status requires an absent observation: observed quantity is
        # never invented from the requested quantity.
        if self.status is QuantityComplianceStatus.UNKNOWN:
            if self.observed_quantity is not None:
                raise QuantityError(
                    "UNKNOWN status requires absent observed quantity"
                )

    @property
    def is_violation(self) -> bool:
        return self.status is QuantityComplianceStatus.VIOLATION

    @property
    def prevents_nothing(self) -> bool:
        """Post-effect observation never retroactively prevents an effect."""
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "authorized_quantity": (
                self.authorized_quantity.to_dict()
                if self.authorized_quantity
                else None
            ),
            "requested_quantity": (
                self.requested_quantity.to_dict()
                if self.requested_quantity
                else None
            ),
            "observed_quantity": (
                self.observed_quantity.to_dict()
                if self.observed_quantity
                else None
            ),
            "request_digest": self.request_digest,
            "status": self.status.value,
            "reason": self.reason,
            "authority_reference": self.authority_reference,
            "grants_authority": False,
            "prevented_effect": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuantityEvidence":
        if not isinstance(data, Mapping):
            raise QuantityError("QuantityEvidence must be a mapping")

        def _q(key: str) -> Optional[Quantity]:
            raw = data.get(key)
            return Quantity.from_dict(raw) if raw else None

        observed_raw = data.get("observed_quantity")
        return cls(
            mission_id=str(data.get("mission_id", "") or ""),
            action_id=str(data.get("action_id", "") or ""),
            authorized_quantity=_q("authorized_quantity"),
            requested_quantity=_q("requested_quantity"),
            observed_quantity=(
                ObservedQuantity.from_quantity(Quantity.from_dict(observed_raw))
                if observed_raw
                else None
            ),
            request_digest=str(data.get("request_digest", "") or ""),
            status=QuantityComplianceStatus(
                str(data.get("status", "") or "UNKNOWN")
            ),
            reason=str(data.get("reason", "") or ""),
            authority_reference=str(data.get("authority_reference", "") or ""),
        )


def classify_quantity_observation(
    *,
    mission_id: str,
    action_id: str,
    authorized_quantity: Optional[Quantity],
    requested_quantity: Optional[Quantity],
    observed_quantity: Optional[ObservedQuantity],
    request_digest: str,
    authority_reference: str = "",
) -> QuantityEvidence:
    """Classify a post-effect observation into read-only evidence.

    AUTHORIZATION (may the effect occur?) and OBSERVATION (what effect
    actually occurred?) remain separate. An observed quantity exceeding the
    authorized quantity is a VIOLATION — never a retroactive "denied".
    """
    status = QuantityComplianceStatus.UNKNOWN
    reason = "actual quantity could not be established"

    if observed_quantity is not None:
        if authorized_quantity is None:
            status = QuantityComplianceStatus.UNKNOWN
            reason = "no authorized quantity to compare against"
        elif (
            observed_quantity.dimension != authorized_quantity.dimension
            or observed_quantity.unit != authorized_quantity.unit
        ):
            status = QuantityComplianceStatus.UNKNOWN
            reason = "observed dimension/unit differs from authorized"
        elif observed_quantity.amount > authorized_quantity.amount:
            status = QuantityComplianceStatus.VIOLATION
            reason = "observed effect exceeded authorized quantity"
        else:
            status = QuantityComplianceStatus.COMPLIANT
            reason = "observed effect within authorized quantity"

    return QuantityEvidence(
        mission_id=mission_id,
        action_id=action_id,
        authorized_quantity=authorized_quantity,
        requested_quantity=requested_quantity,
        observed_quantity=observed_quantity,
        request_digest=request_digest,
        status=status,
        reason=reason,
        authority_reference=authority_reference,
    )


__all__ = [
    "QuantityError",
    "QuantityDimension",
    "DIMENSION_CANONICAL_UNIT",
    "Quantity",
    "QuantityCeiling",
    "ApplicabilityState",
    "ApplicabilityDetermination",
    "QuantityApplicabilityRegistry",
    "DEFAULT_QUANTITY_APPLICABILITY",
    "resolve_quantity_applicability",
    "PlanQuantity",
    "QuantityAuthorityRecord",
    "DelegatedQuantityCeiling",
    "QuantityComplianceStatus",
    "ObservedQuantity",
    "QuantityEvidence",
    "classify_quantity_observation",
    "determine_applicability",
    "prove_plan_quantity_against_ceiling",
    "prove_plan_quantity_against_delegated_ceiling",
    "establish_quantity_authority",
    "prove_plan_quantities_against_authority",
]