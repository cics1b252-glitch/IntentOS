"""Knowledge Object Model (KOM) — Canonical Semantic Knowledge Primitive.

RFC-0012: Adaptive Memory Engine & Knowledge Object Model.
Defines the canonical semantic unit of knowledge (KnowledgeObject),
along with epistemic classification, temporal validity, provenance,
and lifecycle states.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from intent_kernel.time_utils import utc_iso, utc_now


class MemoryClass(str, Enum):
    """Classification of cognitive memory."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    GOAL = "goal"
    DECISION = "decision"
    CORRECTION = "correction"
    PROCEDURAL = "procedural"
    PROJECT_CONTEXT = "project_context"
    TEMPORARY_CONTEXT = "temporary_context"
    SYSTEM_LEARNING = "system_learning"  # Future contract for Cognitive Learning Engine


class KnowledgeNature(str, Enum):
    """Epistemic nature of the knowledge unit."""

    FACT = "fact"
    INFERENCE = "inference"
    ASSUMPTION = "assumption"
    PREFERENCE = "preference"
    GOAL = "goal"
    DECISION = "decision"
    CORRECTION = "correction"
    OBSERVATION = "observation"


class KnowledgeState(str, Enum):
    """Lifecycle state of a Knowledge Object."""

    ACTIVE = "active"
    PENDING_VALIDATION = "pending_validation"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    REJECTED = "rejected"
    DELETED = "deleted"


class RetentionPolicy(str, Enum):
    """Retention lifecycle policy for Knowledge Objects."""

    SESSION = "session"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    PERMANENT = "permanent"
    UNTIL_DATE = "until_date"
    PROJECT_LIFETIME = "project_lifetime"


class SourceType(str, Enum):
    """Origin source of the knowledge statement."""

    USER_INPUT = "user_input"
    CONVERSATION = "conversation"
    MISSION = "mission"
    AGENT = "agent"
    CAPABILITY = "capability"
    PROVIDER = "provider"
    DOCUMENT = "document"
    EXTERNAL_SOURCE = "external_source"
    SYSTEM_INFERENCE = "system_inference"
    MIGRATION = "migration"
    LEGACY_PKB = "legacy_pkb"


class ScopeType(str, Enum):
    """Scope boundaries for memory isolation."""

    GLOBAL_SCOPE = "global"
    PROJECT_SCOPE = "project"


@dataclass
class ProvenanceRecord:
    """Structured lineage and evidence trail for a Knowledge Object."""

    source_type: SourceType = SourceType.USER_INPUT
    source_id: str = "user"
    timestamp: str = field(default_factory=utc_iso)
    correlation_id: str = ""
    mission_id: str = ""
    project_id: str = ""
    evidence_reference: str = ""
    confidence_at_source: float = 1.0
    transformation_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type.value if isinstance(self.source_type, Enum) else str(self.source_type),
            "source_id": self.source_id,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "mission_id": self.mission_id,
            "project_id": self.project_id,
            "evidence_reference": self.evidence_reference,
            "confidence_at_source": self.confidence_at_source,
            "transformation_history": self.transformation_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceRecord:
        if not data:
            return cls()
        st = data.get("source_type", SourceType.USER_INPUT)
        if isinstance(st, str):
            try:
                st = SourceType(st)
            except ValueError:
                st = SourceType.USER_INPUT
        return cls(
            source_type=st,
            source_id=data.get("source_id", "user"),
            timestamp=data.get("timestamp", utc_iso()),
            correlation_id=data.get("correlation_id", ""),
            mission_id=data.get("mission_id", ""),
            project_id=data.get("project_id", ""),
            evidence_reference=data.get("evidence_reference", ""),
            confidence_at_source=data.get("confidence_at_source", 1.0),
            transformation_history=data.get("transformation_history", []),
        )


# Regex patterns for detecting sensitive data/credentials in text
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}", re.IGNORECASE),
    re.compile(r"sk[-_]live[-_][a-zA-Z0-9_\-]{16,}", re.IGNORECASE),
    re.compile(r"AIza[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{12,}", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*[^\s]+", re.IGNORECASE),
    re.compile(r"(bearer|token|password|passwd|pwd|secret|api_key|api-key|access_token|refresh_token|private_key)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{8,}['\"]?", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN (RSA |EC |PGP )?PRIVATE KEY-----", re.IGNORECASE),
]


@dataclass
class KnowledgeObject:
    """Canonical Semantic Unit of Knowledge in Intent OS."""

    object_id: str
    object_type: str = "GENERIC_KNOWLEDGE"
    memory_class: MemoryClass = MemoryClass.SEMANTIC
    knowledge_nature: KnowledgeNature = KnowledgeNature.FACT
    content: Any = ""
    summary: str = ""
    project_id: str = "GLOBAL"
    user_scope: ScopeType = ScopeType.PROJECT_SCOPE
    mission_id: str = ""
    source: str = "user"
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    confidence: float = 0.8
    importance: float = 0.5
    sensitivity: str = "normal"  # "normal", "confidential", "secret"
    status: KnowledgeState = KnowledgeState.ACTIVE
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    version: int = 1
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    related_objects: List[str] = field(default_factory=list)
    retention_policy: RetentionPolicy = RetentionPolicy.LONG_TERM
    evidence_refs: List[str] = field(default_factory=list)
    cognitive_context_eligible: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_valid_at(self, check_time_iso: Optional[str] = None) -> bool:
        """Check temporal validity of the Knowledge Object at a given timestamp."""
        if self.status != KnowledgeState.ACTIVE:
            return False

        now_str = check_time_iso or utc_iso()
        if self.valid_from and now_str < self.valid_from:
            return False
        if self.valid_until and now_str > self.valid_until:
            return False
        return True

    def contains_secret(self) -> bool:
        """Scan content, summary, sensitivity, and metadata for potential credential or secret exposure."""
        if self.sensitivity and str(self.sensitivity).lower() == "secret":
            return True
        if self.metadata and (str(self.metadata.get("sensitivity")).lower() == "secret" or self.metadata.get("secret") is True):
            return True

        text_content = str(self.content) + " " + self.summary + " " + str(self.metadata)
        for pat in SECRET_PATTERNS:
            if pat.search(text_content):
                return True
        return False

    def supersede_with(self, new_object: KnowledgeObject) -> None:
        """Mark this object as superseded by a newer object version."""
        self.status = KnowledgeState.SUPERSEDED
        self.superseded_by = new_object.object_id
        self.updated_at = utc_iso()

        new_object.supersedes = self.object_id
        new_object.version = self.version + 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize Knowledge Object to canonical dictionary."""
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "memory_class": self.memory_class.value if isinstance(self.memory_class, Enum) else str(self.memory_class),
            "knowledge_nature": self.knowledge_nature.value if isinstance(self.knowledge_nature, Enum) else str(self.knowledge_nature),
            "content": self.content,
            "summary": self.summary,
            "project_id": self.project_id,
            "user_scope": self.user_scope.value if isinstance(self.user_scope, Enum) else str(self.user_scope),
            "mission_id": self.mission_id,
            "source": self.source,
            "provenance": self.provenance.to_dict() if isinstance(self.provenance, ProvenanceRecord) else self.provenance,
            "confidence": self.confidence,
            "importance": self.importance,
            "sensitivity": self.sensitivity,
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "version": self.version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "related_objects": list(self.related_objects),
            "retention_policy": self.retention_policy.value if isinstance(self.retention_policy, Enum) else str(self.retention_policy),
            "evidence_refs": list(self.evidence_refs),
            "cognitive_context_eligible": self.cognitive_context_eligible,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnowledgeObject:
        """Reconstruct Knowledge Object from canonical dictionary."""
        def parse_enum(val, enum_cls, default_val):
            if isinstance(val, enum_cls):
                return val
            if isinstance(val, str):
                try:
                    return enum_cls(val)
                except ValueError:
                    return default_val
            return default_val

        prov_data = data.get("provenance", {})
        prov = ProvenanceRecord.from_dict(prov_data) if isinstance(prov_data, dict) else ProvenanceRecord()

        return cls(
            object_id=data["object_id"],
            object_type=data.get("object_type", "GENERIC_KNOWLEDGE"),
            memory_class=parse_enum(data.get("memory_class"), MemoryClass, MemoryClass.SEMANTIC),
            knowledge_nature=parse_enum(data.get("knowledge_nature"), KnowledgeNature, KnowledgeNature.FACT),
            content=data.get("content", ""),
            summary=data.get("summary", ""),
            project_id=data.get("project_id", "GLOBAL"),
            user_scope=parse_enum(data.get("user_scope"), ScopeType, ScopeType.PROJECT_SCOPE),
            mission_id=data.get("mission_id", ""),
            source=data.get("source", "user"),
            provenance=prov,
            confidence=data.get("confidence", 0.8),
            importance=data.get("importance", 0.5),
            sensitivity=data.get("sensitivity", "normal"),
            status=parse_enum(data.get("status"), KnowledgeState, KnowledgeState.ACTIVE),
            tags=data.get("tags", []),
            created_at=data.get("created_at", utc_iso()),
            updated_at=data.get("updated_at", utc_iso()),
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            version=data.get("version", 1),
            supersedes=data.get("supersedes"),
            superseded_by=data.get("superseded_by"),
            related_objects=data.get("related_objects", []),
            retention_policy=parse_enum(data.get("retention_policy"), RetentionPolicy, RetentionPolicy.LONG_TERM),
            evidence_refs=data.get("evidence_refs", []),
            cognitive_context_eligible=data.get("cognitive_context_eligible", True),
            metadata=data.get("metadata", {}),
        )
