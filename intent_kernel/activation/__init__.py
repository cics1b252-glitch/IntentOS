"""Movement 18 — Governed Resource Activation.

REGISTERED != ACTIVATED
ACTIVATED != AVAILABLE
AVAILABLE != ELIGIBLE
ELIGIBLE != SELECTED
SELECTED != AUTHORIZED
AUTHORIZED != EXECUTED

Registration proves a resource is known to the canonical system.
Activation proves a resource satisfies governed prerequisites.
Activation does NOT manufacture eligibility, authorization, or execution.
"""

from intent_kernel.activation.models import (
    ResourceActivationDecision,
    ResourceActivationDecisionType,
    ResourceActivationRequest,
    ResourceActivationResult,
    ResourceActivationStatus,
)

__all__ = [
    "ResourceActivationDecision",
    "ResourceActivationDecisionType",
    "ResourceActivationRequest",
    "ResourceActivationResult",
    "ResourceActivationStatus",
]
