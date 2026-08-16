"""Governed Resource Discovery — read-only evidence layer (Movement 16).

Discovery is evidence.
Discovery is NOT authority.
"""

from intent_kernel.discovery.adapter import ResourceDiscoveryAdapter
from intent_kernel.discovery.models import (
    ResourceDiscoveryCorrelation,
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoverySnapshot,
    ResourceDiscoveryStatus,
)
from intent_kernel.discovery.proposal import ResourceRegistrationProposal
from intent_kernel.discovery.registry import DiscoveryRegistry
from intent_kernel.discovery.service import CanonicalResourceDiscoveryService

__all__ = [
    "CanonicalResourceDiscoveryService",
    "DiscoveryRegistry",
    "ResourceDiscoveryAdapter",
    "ResourceDiscoveryCorrelation",
    "ResourceDiscoveryEvidence",
    "ResourceDiscoveryKind",
    "ResourceDiscoverySnapshot",
    "ResourceDiscoveryStatus",
    "ResourceRegistrationProposal",
]
