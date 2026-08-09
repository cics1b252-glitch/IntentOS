"""Persistent Instruction Resolver — RFC-0014.1 (STUDIO 10.1).

Retrieves persistent instructions from AME, evaluates precedence, handles supersession,
enforces project isolation and secret safety, and converts instructions into MissionConstraints
and OutputContracts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from intent_kernel.kom import (
    KnowledgeObject,
    KnowledgeState,
    MemoryClass,
    KnowledgeNature,
    RetentionPolicy,
    ScopeType,
    SourceType,
    ProvenanceRecord,
    SECRET_PATTERNS,
)
from intent_kernel.ame import AdaptiveMemoryEngine, LocalKnowledgeObjectRepository
from intent_kernel.time_utils import utc_iso, utc_now

from intent_kernel.instructions.models import (
    InstructionScope,
    InstructionType,
    MissionConstraint,
    OutputContract,
    PersistentInstruction,
    PrecedenceLevel,
)


class SecretInstructionError(ValueError):
    """Raised when an instruction contains forbidden credentials or secret tokens."""
    pass


class PersistentInstructionResolver:
    """Canonical resolver for persistent instructions stored in AME."""

    def __init__(self, ame: Optional[Any] = None) -> None:
        self._ame = ame or AdaptiveMemoryEngine()
        self._output_validation_failures = 0
        self._correction_attempts = 0

    def _get_repo(self) -> Any:
        if hasattr(self._ame, "_repo") and self._ame._repo:
            return self._ame._repo
        if hasattr(self._ame, "repository"):
            return self._ame.repository
        return None

    def _contains_secret(self, text: str) -> bool:
        if not text:
            return False
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                return True
        return False

    async def save_instruction(self, instruction: PersistentInstruction) -> PersistentInstruction:
        """Persist a instruction through canonical AME ports while enforcing secret rejection."""
        # 1. Secret Safety Check
        combined_text = f"{instruction.description} {instruction.constraint} {instruction.rule_key}"
        if self._contains_secret(combined_text):
            raise SecretInstructionError("Persistent instruction contains secret or credential tokens and is rejected.")

        # 2. Check for supersession / version update of existing rule
        repo = self._get_repo()
        if repo:
            if hasattr(repo, "query"):
                active_kos = await repo.query(project_id=instruction.project_id, status=KnowledgeState.ACTIVE)
            elif hasattr(repo, "list_active"):
                active_kos = await repo.list_active(project_id=instruction.project_id)
            else:
                active_kos = []
            for ko in active_kos:
                if ko.object_type == "persistent_instruction":
                    meta = ko.metadata or {}
                    rule_key = meta.get("rule_key") or ko.summary
                    scope = meta.get("scope")
                    if rule_key == instruction.rule_key and scope == instruction.scope.value:
                        if instruction.supersedes is None:
                            instruction.supersedes = ko.object_id
                        ko.status = KnowledgeState.SUPERSEDED
                        ko.superseded_by = instruction.instruction_id
                        ko.updated_at = utc_iso()
                        await repo.save(ko)

        # 3. Create KnowledgeObject
        ko_scope = ScopeType.GLOBAL_SCOPE if instruction.scope == InstructionScope.GLOBAL_USER else ScopeType.PROJECT_SCOPE

        ko = KnowledgeObject(
            object_id=instruction.instruction_id,
            object_type="persistent_instruction",
            memory_class=MemoryClass.PREFERENCE,
            knowledge_nature=KnowledgeNature.PREFERENCE,
            content=instruction.constraint,
            summary=instruction.description or instruction.rule_key,
            project_id=instruction.project_id,
            user_scope=ko_scope,
            status=KnowledgeState.ACTIVE if instruction.active else KnowledgeState.ARCHIVED,
            tags=["persistent_instruction", instruction.scope.value, instruction.instruction_type.value],
            version=instruction.version,
            supersedes=instruction.supersedes,
            created_at=instruction.created_at,
            updated_at=instruction.updated_at,
            metadata={
                "instruction_id": instruction.instruction_id,
                "scope": instruction.scope.value,
                "instruction_type": instruction.instruction_type.value,
                "rule_key": instruction.rule_key,
                "priority": instruction.priority,
                "source": instruction.source,
                "active": instruction.active,
                "provenance": instruction.provenance,
            },
        )

        if repo:
            await repo.save(ko)

        return instruction

    async def get_active_instructions(
        self,
        project_id: str = "GLOBAL",
        include_global_user: bool = True,
    ) -> List[PersistentInstruction]:
        """Fetch active, non-expired instructions applicable to project_id and/or global user scope."""
        instructions: List[PersistentInstruction] = []
        repo = self._get_repo()
        if not repo:
            return instructions

        # Gather for project_id and optionally GLOBAL
        project_ids = [project_id]
        if include_global_user and project_id != "GLOBAL":
            project_ids.append("GLOBAL")

        seen_ids = set()
        for pid in project_ids:
            if hasattr(repo, "query"):
                active_kos = await repo.query(project_id=pid, status=KnowledgeState.ACTIVE)
            elif hasattr(repo, "list_active"):
                active_kos = await repo.list_active(project_id=pid)
            else:
                active_kos = []
            for ko in active_kos:
                if ko.object_type != "persistent_instruction":
                    continue
                if not ko.is_valid_at():
                    continue
                if ko.contains_secret():
                    continue
                if ko.object_id in seen_ids:
                    continue

                meta = ko.metadata or {}
                scope_str = meta.get("scope", InstructionScope.GLOBAL_USER.value)

                # Project Isolation Rule:
                # If instruction scope is PROJECT, it MUST match project_id exactly.
                if scope_str == InstructionScope.PROJECT.value and ko.project_id != project_id:
                    continue

                inst = PersistentInstruction.from_dict({
                    "instruction_id": ko.object_id,
                    "scope": scope_str,
                    "project_id": ko.project_id,
                    "instruction_type": meta.get("instruction_type", InstructionType.FORMAT_PREFERENCE.value),
                    "rule_key": meta.get("rule_key", ko.summary),
                    "description": ko.summary,
                    "constraint": str(ko.content),
                    "priority": meta.get("priority", 50),
                    "source": meta.get("source", "user"),
                    "created_at": ko.created_at,
                    "updated_at": ko.updated_at,
                    "active": ko.status == KnowledgeState.ACTIVE,
                    "version": ko.version,
                    "supersedes": ko.supersedes,
                    "provenance": meta.get("provenance", {}),
                })

                if inst.active:
                    instructions.append(inst)
                    seen_ids.add(inst.instruction_id)

        # Sort by scope priority & instruction priority
        instructions.sort(key=lambda x: (x.priority, x.created_at))
        return instructions

    async def resolve_constraints(
        self,
        goal: str,
        project_id: str = "GLOBAL",
        explicit_current_instruction: Optional[str] = None,
    ) -> Tuple[List[MissionConstraint], OutputContract]:
        """Resolve active instructions into MissionConstraints and OutputContract applying precedence."""
        active_instructions = await self.get_active_instructions(project_id=project_id)
        constraints: List[MissionConstraint] = []

        single_block_required = False
        text_outside_allowed = True
        required_sections: List[str] = []
        forbidden_sections: List[str] = []
        max_blocks = 100

        # Process explicit current mission requirement if provided (Precedence 2)
        if explicit_current_instruction:
            exp_lower = explicit_current_instruction.lower()
            if "resumo" in exp_lower or "summary" in exp_lower:
                # Override format preferences if requested
                pass

        # Apply active persistent instructions
        for inst in active_instructions:
            constraint_text = inst.constraint.lower()
            desc_text = inst.description.lower()
            combined = f"{constraint_text} {desc_text}"

            precedence = (
                PrecedenceLevel.PERSISTENT_PROJECT_RULE.value
                if inst.scope == InstructionScope.PROJECT
                else PrecedenceLevel.PERSISTENT_USER_RULE.value
            )

            mc = MissionConstraint(
                source_instruction_id=inst.instruction_id,
                constraint_type=inst.instruction_type.value,
                expected_behavior=inst.constraint,
                validation_strategy="SYNTACTIC",
                severity="high" if inst.priority < 30 else "medium",
                blocking=True,
                scope=inst.scope.value,
                reason=f"Derived from persistent instruction {inst.rule_key}",
                precedence=precedence,
            )
            constraints.append(mc)

            # Check single block / delivery rules
            if any(k in combined for k in ["único bloco", "unico bloco", "single block", "sem texto fora", "one block"]):
                single_block_required = True
                text_outside_allowed = False
                max_blocks = 1

        # Build output contract
        contract = OutputContract(
            single_block_required=single_block_required,
            text_outside_block_allowed=text_outside_allowed,
            required_sections=required_sections,
            forbidden_sections=forbidden_sections,
            max_blocks=max_blocks,
            validation_required=True,
        )

        return constraints, contract

    def record_validation_failure(self) -> None:
        self._output_validation_failures += 1

    def record_correction_attempt(self) -> None:
        self._correction_attempts += 1

    async def get_diagnostics(self) -> Dict[str, Any]:
        """Produce safe diagnostic metrics without exposing sensitive content."""
        all_insts = await self.get_active_instructions(project_id="GLOBAL", include_global_user=True)
        return {
            "persistent_instruction_count": len(all_insts),
            "active_instruction_count": len([i for i in all_insts if i.active]),
            "project_instruction_count": len([i for i in all_insts if i.scope == InstructionScope.PROJECT]),
            "resolved_constraints_count": len(all_insts),
            "output_validation_failures": self._output_validation_failures,
            "correction_attempts": self._correction_attempts,
        }
