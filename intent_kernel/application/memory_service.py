"""Canonical ownership contract for durable cognitive memory."""

from __future__ import annotations

from dataclasses import dataclass

from intent_kernel.ame import AdaptiveMemoryEngine, MemoryCandidate, MemoryQuery
from intent_kernel.kom import ProvenanceRecord, SourceType


@dataclass(frozen=True, slots=True)
class MemoryAuthorityContract:
    durable_authority: str = "AME/KOM"
    project_scope_required: bool = True
    subject_scope: str = "user_within_project"
    provenance_required: bool = True
    currentness_model: str = "one_active_object_per_authority_key"
    correction_model: str = "versioned_supersession_with_history"
    expiration_model: str = "validity_window_excludes_current_retrieval"
    sensitivity_model: str = "caller_access_limit_and_secret_exclusion"
    curation_layer: str = "KnowledgePipeline/PKB"
    curation_relationship: str = "governed_projection_not_current_truth"
    session_authority: str = "transient_dialogue_only"
    session_projection_rule: str = "never_promote_without_memory_candidate"
    compatibility_role: str = "read_through_only"


class CanonicalMemoryService:
    """The sole product-facing service for durable memory reads and writes."""

    def __init__(self, ame: AdaptiveMemoryEngine) -> None:
        self.ame = ame
        self.contract = MemoryAuthorityContract()

    async def remember(
        self, content: str, *, project_id: str, authority_key: str,
        source: str = "user_chat", sensitivity: str = "normal",
    ):
        candidate = MemoryCandidate(
            proposed_content=content,
            reason_to_remember=f"Memória informada no projeto {project_id}",
            source=source,
            project_id=project_id,
            proposed_importance=0.9,
            sensitivity=sensitivity,
            provenance=ProvenanceRecord(
                source_type=SourceType.USER_INPUT,
                source_id=source,
                project_id=project_id,
            ),
            metadata={
                "authority_key": authority_key,
                "durable_authority": self.contract.durable_authority,
                "pkb_role": "curation_projection_only",
            },
        )
        return await self.ame.process_candidate(candidate)

    async def recall(self, query_text: str, *, project_id: str,
                     sensitivity_limit: str = "normal"):
        return await self.ame.retrieve_memory(MemoryQuery(
            query_text=query_text,
            project_id=project_id,
            sensitivity_limit=sensitivity_limit,
        ))

    @staticmethod
    def authority_key(content: str) -> str:
        lowered = content.casefold()
        if "projeto" in lowered:
            return "project.technology"
        if "pref" in lowered or "respostas" in lowered:
            return "user.response_style"
        return "user.scoped_fact"
