"""PKB module — Personal Knowledge Base for the Intent OS Kernel."""

from intent_kernel.contracts import KnowledgeEvent
from intent_kernel.pkb.models import (
    KnowledgeEvent as LegacyKnowledgeEvent,
    DecisionContent,
    GoalContent,
    ArchitectureContent,
    MemoryContent,
    LessonContent,
    LifecycleTransition,
)
from intent_kernel.pkb.knowledge_manager import KnowledgeManager
from intent_kernel.pkb.canonical_curator import (
    CanonicalKnowledgeCurator,
    CurationAction,
    CurationDecision,
    KnowledgeAuditEntry,
)
from intent_kernel.pkb.knowledge_pipeline import (
    KnowledgeIngestReport,
    KnowledgePipeline,
)
from intent_kernel.pkb.json_store import JsonFileStore
from intent_kernel.pkb.score import (
    KnowledgeScoreCalculator,
    KnowledgeScore,
    KnowledgeScoreBreakdown,
)

__all__ = [
    "KnowledgeEvent",
    "LegacyKnowledgeEvent",
    "DecisionContent",
    "GoalContent",
    "ArchitectureContent",
    "MemoryContent",
    "LessonContent",
    "LifecycleTransition",
    "KnowledgeManager",
    "CanonicalKnowledgeCurator",
    "CurationAction",
    "CurationDecision",
    "KnowledgeAuditEntry",
    "KnowledgeIngestReport",
    "KnowledgePipeline",
    "JsonFileStore",
    "KnowledgeScoreCalculator",
    "KnowledgeScore",
    "KnowledgeScoreBreakdown",
]
