"""Canonical authority for cognitive conversation turn boundaries.

This service composes the existing IUE, typed CDM pending-dialogue matcher and
capability runtime.  It does not persist sessions, author final text, call a
provider or execute a Mission.  Its output is the sole decision consumed by
interfaces when deciding whether a saved pending dialogue may influence the
current turn.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from intent_kernel.cdm import (
    CognitiveDialogueManager,
    PendingDialogueContext,
    PendingDialogueMatch,
    PendingDialogueMatchStatus,
)
from intent_kernel.cognition import CognitiveExecutionDecision
from intent_kernel.conversation.policy import (
    FinanceFieldFillingResult,
    classify_finance_turn,
    detect_finance_domain,
    is_finance_complete,
    next_finance_field,
)
from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent


class ConversationTurnRelation(str, Enum):
    """Relationship between the current utterance and saved dialogue state."""

    NEW_CONVERSATION_TURN = "NEW_CONVERSATION_TURN"
    VALID_PENDING_CONTINUATION = "VALID_PENDING_CONTINUATION"
    INDEPENDENT_INTENT_INTERRUPTION = "INDEPENDENT_INTENT_INTERRUPTION"
    AMBIGUOUS_PENDING_INPUT = "AMBIGUOUS_PENDING_INPUT"


@dataclass(frozen=True, slots=True)
class ConversationAuthorityDecision:
    """Canonical, non-executing decision for one conversational turn."""

    relation: ConversationTurnRelation
    independent_intent: StructuredIntent
    structured_intent: StructuredIntent
    pending_match: PendingDialogueMatch
    capability_decision: CognitiveExecutionDecision
    active_pending_dialogue: dict[str, Any] | None = None
    suspended_pending_dialogue: dict[str, Any] | None = None
    resume_mission_id: str | None = None

    @property
    def continues_pending_dialogue(self) -> bool:
        return self.relation is ConversationTurnRelation.VALID_PENDING_CONTINUATION

    @property
    def preserves_pending_dialogue(self) -> bool:
        return self.suspended_pending_dialogue is not None

    @property
    def pending_context_eligible(self) -> bool:
        """Whether compatibility may consume the saved pending field context."""
        return self.continues_pending_dialogue

    def to_dict(self) -> dict[str, Any]:
        """Return safe authority diagnostics without suspended Mission identity."""
        return {
            "authority": "CognitiveConversationService",
            "relation": self.relation.value,
            "continues_pending_dialogue": self.continues_pending_dialogue,
            "preserves_pending_dialogue": self.preserves_pending_dialogue,
            "pending_context_eligible": self.pending_context_eligible,
            "resume_mission_id": (
                self.resume_mission_id
                if self.continues_pending_dialogue else None
            ),
            "pending_dialogue_match": self.pending_match.to_dict(),
            "cognitive_execution_mode": self.capability_decision.mode.value,
        }


class CognitiveConversationService:
    """Compose existing cognitive contracts into one conversation authority."""

    def __init__(
        self,
        *,
        iue: IntentUnderstandingEngine,
        cdm: CognitiveDialogueManager,
        capability_runtime: Any,
    ) -> None:
        self.iue = iue
        self.cdm = cdm
        self.capability_runtime = capability_runtime

    async def analyze_turn(
        self,
        message: str,
        *,
        saved_session: dict[str, Any] | None = None,
        conversation_context: str = "",
        project_id: str = "GLOBAL",
        user_profile: dict[str, Any] | None = None,
        requested_resume_mission_id: str | None = None,
        persistent_constraints: Iterable[str] = (),
        authorized_permissions: Iterable[str] = (),
    ) -> ConversationAuthorityDecision:
        """Analyze a turn before any compatibility field or session mutation."""
        saved = dict(saved_session or {})
        stored_pending = saved.get("pending_dialogue")
        pending_context = (
            PendingDialogueContext.from_dict(stored_pending)
            if isinstance(stored_pending, dict) else None
        )
        independent_context = {
            "conversation_context": conversation_context,
            "user_profile": dict(user_profile or {}),
            "project_id": project_id,
        }
        independent_intent = self.iue.analyze(
            message,
            session_context=independent_context,
        )
        pending_match = self.cdm.match_pending_response(
            message,
            pending_context,
            independent_intent,
        )
        relation = self._relation(stored_pending, pending_match)
        active_pending = (
            deepcopy(stored_pending)
            if relation is ConversationTurnRelation.VALID_PENDING_CONTINUATION
            else None
        )
        suspended_pending = (
            deepcopy(stored_pending)
            if isinstance(stored_pending, dict) and active_pending is None
            else None
        )
        resume_mission_id = self._resume_mission_id(
            relation=relation,
            active_pending=active_pending,
            requested=requested_resume_mission_id,
        )
        structured_intent = independent_intent
        if active_pending is not None:
            structured_intent = self.iue.analyze(
                message,
                session_context={
                    **independent_context,
                    "pending_dialogue": active_pending,
                },
            )
        capability_decision = await self.capability_runtime.analyze(
            message,
            structured_intent=structured_intent,
            ame_context={"conversation_context": conversation_context},
            project_context={
                "project_id": project_id,
                "pending_dialogue": active_pending,
                "pending_dialogue_match": pending_match.to_dict(),
            },
            persistent_constraints=persistent_constraints,
            authorized_permissions=authorized_permissions,
        )
        return ConversationAuthorityDecision(
            relation=relation,
            independent_intent=independent_intent,
            structured_intent=structured_intent,
            pending_match=pending_match,
            capability_decision=capability_decision,
            active_pending_dialogue=active_pending,
            suspended_pending_dialogue=suspended_pending,
            resume_mission_id=resume_mission_id,
        )

    @staticmethod
    def compatibility_known_context(
        saved_session: dict[str, Any],
        decision: ConversationAuthorityDecision,
    ) -> dict[str, Any]:
        """Project only context that the canonical turn decision made eligible."""
        if decision.active_pending_dialogue is not None:
            values = decision.active_pending_dialogue.get("known_context")
            return deepcopy(values) if isinstance(values, dict) else {}
        if decision.preserves_pending_dialogue:
            return {}
        conversation_state = saved_session.get("conversation_state")
        if not isinstance(conversation_state, dict):
            return {}
        values = conversation_state.get("known_context")
        return deepcopy(values) if isinstance(values, dict) else {}

    @staticmethod
    def merge_session_update(
        previous_session: dict[str, Any],
        proposed_session: dict[str, Any],
        decision: ConversationAuthorityDecision,
    ) -> dict[str, Any]:
        """Persist a new turn without consuming an interrupted pending dialogue."""
        proposed = deepcopy(proposed_session)
        if not decision.preserves_pending_dialogue:
            return proposed

        previous = deepcopy(previous_session)
        for key in ("pending_dialogue", "mission_id", "mission_status"):
            if key in previous:
                proposed[key] = previous[key]
            else:
                proposed.pop(key, None)

        prior_state = previous.get("conversation_state")
        current_state = proposed.get("conversation_state")
        if isinstance(prior_state, dict):
            merged_state = (
                deepcopy(current_state) if isinstance(current_state, dict) else {}
            )
            for key in (
                "known_context",
                "missing_context",
                "pending_question",
                "active_mission_id",
            ):
                if key in prior_state:
                    merged_state[key] = deepcopy(prior_state[key])
                else:
                    merged_state.pop(key, None)
            proposed["conversation_state"] = merged_state
        proposed["conversation_authority"] = {
            "relation": decision.relation.value,
            "pending_dialogue_preserved": True,
        }
        return proposed

    # ── Finance field-collection delegation (Movement 23.2) ──────────────

    @staticmethod
    def resolve_finance_pending(
        known_context: dict[str, Any],
    ) -> FinanceFieldFillingResult:
        """Delegate finance field-collection to the canonical typed policy.

        This replaces the inline ``is_fin and lower != "investir"`` block
        in ProductBridge.  The CDM's ``match_pending_response`` still handles
        typed value extraction; this method only determines which field to
        ask next and whether the conversation is complete.
        """
        return classify_finance_turn(known_context)

    @staticmethod
    def finance_domain_detected(
        message_lower: str,
        known_context: dict[str, Any] | None = None,
        pending_dialogue: dict[str, Any] | None = None,
    ) -> bool:
        """Canonical finance domain detection replacing inline ``is_fin``."""
        return detect_finance_domain(
            message_lower=message_lower,
            known_context=known_context,
            pending_dialogue=pending_dialogue,
        )

    @staticmethod
    def finance_next_field(
        known_context: dict[str, Any],
    ) -> tuple[str, str] | None:
        """Return the next missing finance field and its question, or None."""
        return next_finance_field(known_context)

    @staticmethod
    def finance_is_complete(known_context: dict[str, Any]) -> bool:
        """Return True when all required finance fields are collected."""
        return is_finance_complete(known_context)

    @staticmethod
    def _relation(
        stored_pending: Any,
        pending_match: PendingDialogueMatch,
    ) -> ConversationTurnRelation:
        if not isinstance(stored_pending, dict):
            return ConversationTurnRelation.NEW_CONVERSATION_TURN
        if pending_match.match_status is PendingDialogueMatchStatus.VALID_CONTINUATION:
            return ConversationTurnRelation.VALID_PENDING_CONTINUATION
        if pending_match.match_status is PendingDialogueMatchStatus.AMBIGUOUS:
            return ConversationTurnRelation.AMBIGUOUS_PENDING_INPUT
        return ConversationTurnRelation.INDEPENDENT_INTENT_INTERRUPTION

    @staticmethod
    def _resume_mission_id(
        *,
        relation: ConversationTurnRelation,
        active_pending: dict[str, Any] | None,
        requested: str | None,
    ) -> str | None:
        if relation is ConversationTurnRelation.VALID_PENDING_CONTINUATION:
            return str(
                requested
                or (active_pending or {}).get("mission_id")
                or ""
            ) or None
        if relation is ConversationTurnRelation.NEW_CONVERSATION_TURN:
            return str(requested or "") or None
        return None
