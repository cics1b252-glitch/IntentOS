"""Compatibility adapters for gradual architecture v2.0 adoption."""

from intent_kernel.adapters.legacy import (
    InMemoryMissionStoreAdapter,
    InMemoryIdempotencyStoreAdapter,
    LegacyAgentAdapter,
    LegacyCapabilityExecutorAdapter,
    LegacyConstitutionEngineAdapter,
    LegacyGuardianAdapter,
    LegacyEventPublisherAdapter,
    LegacyKnowledgeStoreAdapter,
    LegacyProviderAdapter,
    from_legacy_knowledge_event,
    to_legacy_knowledge_event,
)

__all__ = [
    "InMemoryMissionStoreAdapter",
    "InMemoryIdempotencyStoreAdapter",
    "LegacyAgentAdapter",
    "LegacyCapabilityExecutorAdapter",
    "LegacyConstitutionEngineAdapter",
    "LegacyGuardianAdapter",
    "LegacyEventPublisherAdapter",
    "LegacyKnowledgeStoreAdapter",
    "LegacyProviderAdapter",
    "from_legacy_knowledge_event",
    "to_legacy_knowledge_event",
]
