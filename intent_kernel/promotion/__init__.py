"""Movement 17 — Governed Resource Promotion.

DISCOVERY IS EVIDENCE.
DISCOVERY IS NOT AUTHORITY.

A proposal may request registration.
A decision may authorize promotion.
Only the canonical registration boundary may mutate canonical resource state.
"""

from intent_kernel.promotion.models import (
    ResourcePromotionDecision,
    ResourcePromotionDecisionType,
    ResourcePromotionProposal,
    ResourcePromotionResult,
    ResourcePromotionStatus,
)

__all__ = [
    "ResourcePromotionDecision",
    "ResourcePromotionDecisionType",
    "ResourcePromotionProposal",
    "ResourcePromotionResult",
    "ResourcePromotionStatus",
]
