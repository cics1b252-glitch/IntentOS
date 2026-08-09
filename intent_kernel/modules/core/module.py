"""CORE module — default module for general intents."""

from __future__ import annotations

from typing import Any

from intent_kernel.modules.base import Module
from intent_kernel.types import Domain, IntentInput


class CoreModule(Module):
    """Default module — handles general-purpose intents.

    This is the fallback module when no domain-specific module matches.
    It provides basic response generation using the available provider.
    """

    name = "core"
    version = "0.1.0"
    triggers = []  # catches everything as fallback
    domains = [
        Domain.WRITING,
        Domain.PROGRAMMING,
        Domain.RESEARCH,
        Domain.PLANNING,
        Domain.BUSINESS,
        Domain.MARKETING,
        Domain.DATA,
        Domain.ENGINEERING,
        Domain.FINANCE,
        Domain.EDUCATION,
        Domain.CREATIVITY,
        Domain.LEGAL,
        Domain.LIFE,
        Domain.OTHER,
    ]
    required_providers = []  # works with MockProvider

    async def execute(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Execute core processing."""
        # In Sprint 0, we use the provider to generate a response
        # The Pipeline passes the provider via ctx
        if ctx and hasattr(ctx, "provider"):
            from intent_kernel.types import Message
            messages = [
                Message(role="system", content=self._system_prompt()),
                Message(role="user", content=intent.text),
            ]
            result = await ctx.provider.complete(messages)
            return {
                "text": result.text,
                "confidence": 0.6,
                "epistemic_status": "conclusion",
            }

        # Fallback without provider
        return {
            "text": self._fallback_response(intent),
            "confidence": 0.4,
            "epistemic_status": "assumption",
        }

    def _system_prompt(self) -> str:
        return (
            "Você é o Intent OS, um sistema operacional cognitivo. "
            "Sua função é processar intenções do usuário e entregar respostas "
            "estruturadas, claras e honestas. "
            "Sempre classifique sua resposta com: "
            "confiança (0-1) e status epistêmico (fato/estimativa/conclusão/suposição)."
        )

    def _fallback_response(self, intent: IntentInput) -> str:
        """Generate a fallback response without a provider."""
        return (
            f"**Processamento Intent OS**\n\n"
            f"Intenção detectada: \"{intent.text[:100]}\"\n\n"
            f"**Classificação:**\n"
            f"- Domínio: {intent.domain.value}\n"
            f"- Modo: {intent.mode.value}\n\n"
            f"**Resposta:**\n"
            f"Para processar completamente esta intenção, "
            f"um provedor de LLM é necessário. "
            f"Configure um provider para respostas mais detalhadas.\n\n"
            f"📋 *Suposição operacional: resposta sem LLM.*"
        )
