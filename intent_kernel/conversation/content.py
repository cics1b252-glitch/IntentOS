"""Canonical conversation content runtime (Movement 24.2).

Single canonical owner of content generation for the runtime-reachable
non-Mission conversation fallback path.

Authority chain:
    USER TURN
    -> CognitiveConversationService (decision)
    -> CognitiveExecutionDecision(mode=CONVERSATION)
    -> CanonicalConversationContentService (content generation)
    -> CanonicalConstitutionEngine (governance)
    -> ProviderManager (routing + execution)
    -> CanonicalTurnResult (truthful provenance)
    -> CognitiveResponseAssembler -> CognitiveProductPresenter

Canonical conversation content remains canonical_mission = False.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.contracts.models import (
    ProviderRequest,
    ProviderMessage,
)
from intent_kernel.providers.manager import ProviderManager
from intent_kernel.providers.authority import ProviderSelectionDecision
from intent_kernel.response import CanonicalTurnResult
from intent_kernel.types import Mode


class CanonicalConversationContentService:
    """Canonical authority for non-Mission conversational content generation.

    Owns:
        - Constitution validation for conversation content
        - Provider routing (exact selected provider = dispatched provider)
        - Provider invocation for content generation
        - CanonicalTurnResult production with truthful provenance

    Does NOT own:
        - Mission creation or execution
        - Authorization gates
        - Productive side effects
        - Turn classification (CognitiveConversationService owns that)
    """

    def __init__(
        self,
        *,
        constitution_engine: Any,
        provider_manager: ProviderManager,
    ) -> None:
        self._constitution_engine = constitution_engine
        self._provider_manager = provider_manager

    async def process(
        self,
        message: str,
        context: dict[str, Any],
        provider_selection: ProviderSelectionDecision,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> CanonicalTurnResult:
        """Generate conversational content via the canonical provider path.

        Args:
            message: The user's message text.
            context: Runtime context dict (session_id, project_id, etc.).
            provider_selection: Pre-selected provider from CanonicalProviderAuthority.
            history: Conversation history for context.

        Returns:
            CanonicalTurnResult with truthful provider provenance.
        """
        serializable_context = {
            key: value
            for key, value in context.items()
            if key != "flow_event"
        }

        # 1. Constitution validation
        verdict = await self._constitution_engine.evaluate(
            "conversation.content",
            message,
            serializable_context,
        )
        if not verdict.allowed:
            return CanonicalTurnResult.blocked(
                text=(
                    f"Conteudo bloqueado pela Constitution: "
                    f"{verdict.violated_rule or verdict.reason}"
                ),
                reason=verdict.violated_rule or verdict.reason or "constitution_denied",
                metadata={
                    "canonical_authority": "CanonicalConversationContentService",
                    "canonical_mission": False,
                    "classification": "CANONICAL_CONVERSATION_CONTENT",
                    "constitution_verdict": verdict.decision.value,
                    "constitution_reason": verdict.reason,
                },
            )

        # 2. Route provider (exact selected provider = dispatched provider)
        managed_provider = await self._provider_manager.route(
            Mode.QUICK,
            selection=provider_selection,
        )

        if managed_provider is None:
            return CanonicalTurnResult.failed(
                text=(
                    "Nenhum provider externo esta disponivel para "
                    "gerar conteudo conversacional (UNKNOWN)."
                ),
                metadata={
                    "canonical_authority": "CanonicalConversationContentService",
                    "canonical_mission": False,
                    "classification": "CANONICAL_CONVERSATION_CONTENT",
                    "provider_available": False,
                    "provider_selection": provider_selection.to_dict(),
                },
            )

        # 3. Build provider request
        messages = [
            ProviderMessage(role="user", content=message),
        ]
        request = ProviderRequest(
            messages=messages,
            metadata={"source": "canonical_conversation_content"},
        )

        # 4. Execute provider
        try:
            provider_response = await managed_provider.execute(request)
        except Exception as exc:
            return CanonicalTurnResult.failed(
                text=(
                    "Falha na invocacao do provider para conteudo "
                    f"conversacional: {type(exc).__name__}"
                ),
                provider_id=provider_selection.provider_id,
                provider_invoked=True,
                metadata={
                    "canonical_authority": "CanonicalConversationContentService",
                    "canonical_mission": False,
                    "classification": "CANONICAL_CONVERSATION_CONTENT",
                    "provider_error": type(exc).__name__,
                    "provider_selection": provider_selection.to_dict(),
                },
            )

        # 5. Map provider response to CanonicalTurnResult
        response_text = provider_response.text or ""
        if not response_text.strip():
            return CanonicalTurnResult.failed(
                text=(
                    "Provider retornou resposta vazia para conteudo "
                    "conversacional (UNKNOWN)."
                ),
                provider_id=provider_selection.provider_id,
                provider_invoked=True,
                metadata={
                    "canonical_authority": "CanonicalConversationContentService",
                    "canonical_mission": False,
                    "classification": "CANONICAL_CONVERSATION_CONTENT",
                    "provider_empty": True,
                    "provider_selection": provider_selection.to_dict(),
                },
            )

        # 6. Successful content generation
        used_provider = (
            self._provider_manager.last_used
            or provider_selection.provider_id
            or "local"
        )
        invoked = bool(used_provider and used_provider != "local")

        return CanonicalTurnResult.provider(
            response_text,
            provider_id=used_provider,
            invoked=invoked,
            resource_ids=(
                (f"provider:{used_provider}",) if invoked else ("RRM",)
            ),
            metadata={
                "canonical_authority": "CanonicalConversationContentService",
                "canonical_mission": False,
                "classification": "CANONICAL_CONVERSATION_CONTENT",
                "provider_selection": provider_selection.to_dict(),
                "provider_dispatched": used_provider,
                "provider_selected": provider_selection.provider_id,
                "provider_explanation": None if invoked else (
                    "A capability Atlas respondeu localmente; "
                    "o provider externo nao foi necessario."
                ),
            },
        )
