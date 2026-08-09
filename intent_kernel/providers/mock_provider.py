"""MockProvider — Sprint 0 mock LLM for testing."""

from __future__ import annotations

from intent_kernel.providers.base import LLMProvider
from intent_kernel.types import CompletionResult, Message


class MockProvider(LLMProvider):
    """Mock LLM provider that returns template responses.

    Used in Sprint 0 when no real LLM is configured.
    Generates responses based on the user's intent text.
    """

    name = "mock"
    models = ["mock-v1"]

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        """Generate a mock response based on the last user message."""
        # Get the last user message
        user_text = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_text = msg.content
                break

        # Generate a structured mock response
        response = self._generate_response(user_text)

        return CompletionResult(
            text=response,
            model="mock-v1",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            finish_reason="stop",
        )

    def _generate_response(self, intent: str) -> str:
        """Generate a structured response for the given intent."""
        intent_lower = intent.lower()

        # Finance domain
        if any(w in intent_lower for w in ["invest", "finance", "dinheiro", "carteira"]):
            return (
                f"**Análise Financeira**\n\n"
                f"Com base na sua solicitação sobre \"{intent[:60]}...\":\n\n"
                "**Recomendação:**\n"
                "1. Defina seu perfil de risco (conservador, moderado, agressivo)\n"
                "2. Estabeleça um horizonte de investimento\n"
                "3. Diversifique entre ativos de renda fixa e variável\n\n"
                "**Próximos passos:**\n"
                "- Consultar um assessor financeiro registrado\n"
                "- Definir aporte mensal compatível com seu orçamento\n\n"
                "⚠️ *Estimativa baseada em princípios gerais. Não constitui aconselhamento financeiro.*"
            )

        # Education domain
        if any(w in intent_lower for w in ["estud", "aprend", "curso", "escola", "data science"]):
            return (
                f"**Plano de Estudos**\n\n"
                f"Para \"{intent[:60]}...\":\n\n"
                "**Estrutura sugerida:**\n"
                "1. **Fase 1** (semanas 1-4): Fundamentos\n"
                "2. **Fase 2** (semanas 5-8): Prática\n"
                "3. **Fase 3** (semanas 9-12): Projeto aplicado\n\n"
                "**Metodologia:**\n"
                "- Dedique 1-2h diárias\n"
                "- Use projetos reais para praticar\n"
                "- Revise semanalmente o progresso\n\n"
                "📋 *Confiança: Média — adapte conforme seu ritmo.*"
            )

        # Business domain
        if any(w in intent_lower for w in ["negócio", "business", "startup", "empresa", "saas"]):
            return (
                f"**Análise de Negócio**\n\n"
                f"Para \"{intent[:60]}...\":\n\n"
                "**Framework de avaliação:**\n"
                "1. Problema: qual dor resolve?\n"
                "2. Mercado: quem são os clientes?\n"
                "3. Solução: como resolve melhor que alternativas?\n"
                "4. Monetização: qual o modelo de receita?\n"
                "5. Escalabilidade: cresce sem crescer custos proporcionalmente?\n\n"
                "**Recomendação:** Valide com 10 clientes potenciais antes de construir.\n\n"
                "📋 *Confiança: Média — validação com mercado real é essencial.*"
            )

        # Default
        return (
            f"**Análise**\n\n"
            f"Com base na sua solicitação:\n\n"
            f"\"{intent[:80]}\"\n\n"
            "**Entendimento:**\n"
            "Sua intenção foi identificada. Para uma resposta mais precisa, "
            "poderia fornecer mais contexto sobre:\n"
            "1. Objetivo específico\n"
            "2. Restrições ou preferências\n"
            "3. Prazo期望\n\n"
            "**Classificação:**\n"
            "- Modo: BASIC\n"
            "- Confiança: Média\n"
            "- Status epistêmico: Conclusão preliminar\n\n"
            "📋 *Suposição operacional: respondendo com base no contexto disponível.*"
        )

    async def health_check(self) -> bool:
        """Mock provider is always healthy."""
        return True
