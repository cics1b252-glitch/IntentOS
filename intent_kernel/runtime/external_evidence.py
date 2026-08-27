"""External Evidence Adapter — M28.2 RRM Resource State Evidence.

First canonical external deterministic evidence mechanism.
Observer-only: reads RRM state, reports facts. VerificationGate decides truth.

Supported evidence types: PROVIDER_RESOURCE_STATE only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

MAX_EXTERNAL_EVIDENCE_REQUIREMENTS = 32

_APPROVED_EXPECTED_STATE_KEYS = frozenset({"status", "is_eligible"})

_VALID_EVIDENCE_TYPES = frozenset({"PROVIDER_RESOURCE_STATE"})


@dataclass(frozen=True, slots=True)
class ExternalEvidenceRequirement:
    """Declarative external evidence requirement on an ActionContract."""

    evidence_type: str
    resource_id: str
    expected_state: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExternalObservationResult:
    """Read-only observation facts from an external evidence adapter.

    The observer MUST NOT return VerificationStatus.
    The observer MUST NOT return verified=True.
    The observer reports FACTS. VerificationGate decides truth.
    """

    evidence_type: str
    resource_id: str
    observer_id: str
    observer_version: str
    observed_state: Dict[str, Any]
    observed_at: str
    matched: bool
    reason_code: str


def external_evidence_contract_hash(
    requirements: List[ExternalEvidenceRequirement],
) -> str:
    """Canonical SHA-256 identity for external evidence requirements.

    Deterministic, type-safe, order-sensitive.
    """
    canonical = json.dumps(
        [
            {
                "evidence_type": r.evidence_type,
                "resource_id": r.resource_id,
                "expected_state": dict(sorted(r.expected_state.items())),
            }
            for r in requirements
        ],
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExternalEvidenceRequirementValidator:
    """Validates external evidence requirements before observation."""

    def validate(
        self, requirements: Any,
    ) -> _RequirementValidationResult:
        if not isinstance(requirements, list) or len(requirements) == 0:
            return _RequirementValidationResult(
                False, ["external_evidence must be a non-empty list"]
            )
        if len(requirements) > MAX_EXTERNAL_EVIDENCE_REQUIREMENTS:
            return _RequirementValidationResult(
                False,
                [
                    f"too many requirements: {len(requirements)} "
                    f"exceeds limit of {MAX_EXTERNAL_EVIDENCE_REQUIREMENTS}"
                ],
            )

        errors: List[str] = []
        for i, req in enumerate(requirements):
            path = f"requirement[{i}]"
            if not isinstance(req, ExternalEvidenceRequirement):
                errors.append(f"{path}: must be an ExternalEvidenceRequirement")
                continue
            if req.evidence_type not in _VALID_EVIDENCE_TYPES:
                errors.append(
                    f"{path}: unsupported evidence_type '{req.evidence_type}'"
                )
            if not isinstance(req.resource_id, str) or not req.resource_id:
                errors.append(f"{path}: resource_id must be a non-empty string")
            if not isinstance(req.expected_state, dict) or len(req.expected_state) == 0:
                errors.append(f"{path}: expected_state must be a non-empty dict")
            else:
                for key in req.expected_state:
                    if key not in _APPROVED_EXPECTED_STATE_KEYS:
                        errors.append(
                            f"{path}: unsupported expected_state key '{key}'"
                        )

        if errors:
            return _RequirementValidationResult(False, errors)
        return _RequirementValidationResult(True)


@dataclass(frozen=True, slots=True)
class _RequirementValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


@runtime_checkable
class ResourceQueryReadPort(Protocol):
    """Read-only interface for resource state observation."""

    def get_provider(self, provider_id: str) -> Optional[Any]: ...


class RRMEvidenceAdapter:
    """Observer-only adapter for RRM provider resource state evidence.

    Reads canonical RRM state. Never mutates. Never authorizes.
    """

    OBSERVER_ID = "RRMEvidenceAdapter"
    OBSERVER_VERSION = "1"

    def __init__(self, rrm: ResourceQueryReadPort) -> None:
        self._rrm = rrm

    def observe(
        self, requirement: ExternalEvidenceRequirement,
    ) -> ExternalObservationResult:
        """Observe the current canonical state of a provider resource.

        Returns observation facts. Never returns VerificationStatus.
        """
        from intent_kernel.time_utils import utc_iso
        from intent_kernel.rrm.models import ResourceStatus

        if requirement.evidence_type != "PROVIDER_RESOURCE_STATE":
            return ExternalObservationResult(
                evidence_type=requirement.evidence_type,
                resource_id=requirement.resource_id,
                observer_id=self.OBSERVER_ID,
                observer_version=self.OBSERVER_VERSION,
                observed_state={},
                observed_at=utc_iso(),
                matched=False,
                reason_code="unsupported_evidence_type",
            )

        resource = self._rrm.get_provider(requirement.resource_id)
        if resource is None:
            return ExternalObservationResult(
                evidence_type=requirement.evidence_type,
                resource_id=requirement.resource_id,
                observer_id=self.OBSERVER_ID,
                observer_version=self.OBSERVER_VERSION,
                observed_state={},
                observed_at=utc_iso(),
                matched=False,
                reason_code="resource_not_found",
            )

        observed: Dict[str, Any] = {}
        for key in requirement.expected_state:
            if key == "status":
                observed["status"] = resource.status.value if hasattr(resource.status, "value") else str(resource.status)
            elif key == "is_eligible":
                observed["is_eligible"] = resource.is_eligible

        matched = observed == requirement.expected_state
        reason = "" if matched else "state_mismatch"

        return ExternalObservationResult(
            evidence_type=requirement.evidence_type,
            resource_id=requirement.resource_id,
            observer_id=self.OBSERVER_ID,
            observer_version=self.OBSERVER_VERSION,
            observed_state=observed,
            observed_at=utc_iso(),
            matched=matched,
            reason_code=reason,
        )
