"""Movement 18 — Governed Resource Activation.

ACTIVATION MUST VERIFY PREREQUISITE TRUTH.
ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH.
ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.

The activation pipeline:
  INDEPENDENT EVIDENCE → AUTHORITY VALIDATES → APPROVED →
  BOUNDARY APPLIES TRANSITION → RRM DERIVES ELIGIBILITY

Evidence is INPUT to activation.
Approval is NOT evidence.
"""

from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
from intent_kernel.activation.service import CanonicalResourceActivationService, ActivationError
from intent_kernel.activation.models import (
    ResourceActivationStatus,
    ResourceActivationDecisionType,
    ResourceActivationRequest,
    ResourceActivationDecision,
    ResourceActivationResult,
    ResourceActivationEvidence,
    ActivationEvidenceType,
)

__all__ = [
    "CanonicalResourceActivationAuthority",
    "ActivationApplicationBoundary",
    "CanonicalResourceActivationService",
    "ActivationError",
    "ResourceActivationStatus",
    "ResourceActivationDecisionType",
    "ResourceActivationRequest",
    "ResourceActivationDecision",
    "ResourceActivationResult",
    "ResourceActivationEvidence",
    "ActivationEvidenceType",
]
