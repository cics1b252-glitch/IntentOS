"""Conversation Orchestrator — transforms Pipeline execution into natural conversation.

The user never sees: pipeline, provider, knowledge missing, guardian, curator, score.
The user only experiences: a conversation with a system that understands.

Architecture:
    User → Conversation Orchestrator → Intent Pipeline → Atlas/Logos/OEM
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intent_kernel.conversation.content import CanonicalConversationContentService
from intent_kernel.conversation.runtime import (
    CognitiveConversationService,
    ConversationAuthorityDecision,
    ConversationTurnRelation,
)
from intent_kernel.conversation.policy import (
    ApplicationFieldFillingResult,
    FinanceFieldFillingResult,
    classify_application_turn,
    classify_finance_turn,
    detect_application_domain,
    detect_finance_domain,
    is_application_complete,
    is_finance_complete,
    is_spreadsheet_domain,
    next_application_field,
    next_finance_field,
)


@dataclass
class ConversationTurn:
    """A turn in the conversation."""
    role: str        # "user" or "assistant"
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ConversationContext:
    """Context maintained across conversation turns."""
    turns: list[ConversationTurn] = field(default_factory=list)
    collected_info: dict = field(default_factory=dict)
    pending_questions: list[str] = field(default_factory=list)
    domain: str = ""
    ready_to_process: bool = False


class ConversationOrchestrator:
    """Legacy standalone compatibility conversation helper.

    This class is not composed into the ProductBridge runtime. New product
    conversation decisions belong to :class:`CognitiveConversationService`.

    Rules:
    1. User never sees technical messages
    2. When context is missing, ask naturally
    3. Each user response feeds the Knowledge Core
    4. Pipeline is completely invisible
    """

    authority_classification = "COMPATIBILITY_ONLY"

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.contexts: dict[str, ConversationContext] = {}

    def get_context(self, session_id: str = "default") -> ConversationContext:
        if session_id not in self.contexts:
            self.contexts[session_id] = ConversationContext()
        return self.contexts[session_id]

    async def process_message(self, user_input: str, session_id: str = "default") -> str:
        """Process a user message and return a natural response."""
        ctx = self.get_context(session_id)
        ctx.turns.append(ConversationTurn(role="user", content=user_input))

        # Detect what the user needs
        intent = self._analyze_intent(user_input)

        # Check if we have enough context
        missing = self._check_missing_context(intent, ctx)

        if missing:
            # Ask for missing info naturally
            response = self._ask_naturally(missing, intent, ctx)
            ctx.turns.append(ConversationTurn(role="assistant", content=response))
            return response

        # We have enough context — process and respond naturally
        response = await self._process_and_respond(intent, ctx)
        ctx.turns.append(ConversationTurn(role="assistant", content=response))
        return response

    def _analyze_intent(self, text: str) -> dict:
        """Analyze user intent without exposing technical details."""
        text_lower = text.lower()

        # Domain detection
        domain = "general"
        if any(w in text_lower for w in ["investir", "investimento", "fiis", "ações", "etf", "carteira", "renda"]):
            domain = "finance"
        elif any(w in text_lower for w in ["projeto", "rfc", "decisão", "documento", "nota"]):
            domain = "knowledge"
        elif any(w in text_lower for w in ["código", "api", "sistema", "deploy", "engenharia"]):
            domain = "engineering"

        # Action detection
        action = "query"
        if any(w in text_lower for w in ["criar", "novo", "adicionar"]):
            action = "create"
        elif any(w in text_lower for w in ["buscar", "procurar", "onde"]):
            action = "search"

        return {"domain": domain, "action": action, "text": text}

    def _check_missing_context(self, intent: dict, ctx: ConversationContext) -> list[str]:
        """Check what information is missing for a good response."""
        missing = []
        domain = intent["domain"]

        if domain == "finance":
            if "amount" not in ctx.collected_info:
                missing.append("amount")
            if "goal" not in ctx.collected_info:
                missing.append("goal")
            if "risk_profile" not in ctx.collected_info:
                missing.append("risk_profile")

        return missing

    def _ask_naturally(self, missing: list[str], intent: dict, ctx: ConversationContext) -> str:
        """Ask for missing information in a natural way."""
        questions = []

        if intent["domain"] == "finance":
            if "amount" in missing:
                questions.append("Quanto pretende investir?")
            if "goal" in missing:
                questions.append("Seu objetivo é renda mensal ou crescimento do patrimônio?")
            if "risk_profile" in missing:
                questions.append("Você prefere mais segurança ou está disposto a arriscar por mais retorno?")

        if questions:
            return "Posso ajudar com isso.\n\nAntes, preciso entender melhor seu cenário:\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

        return "Entendi. Deixe-me processar isso."

    async def _process_and_respond(self, intent: dict, ctx: ConversationContext) -> str:
        """Process the intent and return a natural response."""
        if intent["domain"] == "finance":
            return self._finance_response(intent, ctx)
        elif intent["domain"] == "knowledge":
            return self._knowledge_response(intent, ctx)
        elif intent["domain"] == "engineering":
            return self._engineering_response(intent, ctx)
        else:
            return self._general_response(intent, ctx)

    def _finance_response(self, intent: dict, ctx: ConversationContext) -> str:
        """Generate a natural finance response."""
        amount = ctx.collected_info.get("amount", "um valor")
        goal = ctx.collected_info.get("goal", "crescimento")
        risk = ctx.collected_info.get("risk_profile", "moderado")

        return (
            f"Entendi. Vou ajudar com sua situação financeira.\n\n"
            f"Com base no que você me contou:\n"
            f"- Valor: {amount}\n"
            f"- Objetivo: {goal}\n"
            f"- Perfil: {risk}\n\n"
            f"Vou analisar as melhores opções para você."
        )

    def _knowledge_response(self, intent: dict, ctx: ConversationContext) -> str:
        return "Vou ajudar com seu projeto. O que você precisa?"

    def _engineering_response(self, intent: dict, ctx: ConversationContext) -> str:
        return "Vou ajudar com seu projeto de engenharia. Conte mais detalhes."

    def _general_response(self, intent: dict, ctx: ConversationContext) -> str:
        return "Entendi. Como posso ajudar?"

    def collect_info(self, key: str, value: str, session_id: str = "default") -> None:
        """Collect information from user responses."""
        ctx = self.get_context(session_id)
        ctx.collected_info[key] = value
