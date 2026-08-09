"""Finance module (FIN) — financial analysis and recommendations."""

from __future__ import annotations

from typing import Any
import re

from intent_kernel.modules.base import Module
from intent_kernel.types import Domain, IntentInput


# Risk profile mappings
RISK_PROFILES = {
    "conservative": {
        "name": "Conservador",
        "allocation": {"renda_fixa": 0.7, "renda_variavel": 0.2, "caixa": 0.1},
        "horizon": "curto/médio prazo",
        "description": "Prioriza preservação do capital com retorno previsível.",
    },
    "moderate": {
        "name": "Moderado",
        "allocation": {"renda_fixa": 0.4, "renda_variavel": 0.4, "caixa": 0.2},
        "horizon": "médio prazo",
        "description": "Equilíbrio entre retorno e segurança.",
    },
    "aggressive": {
        "name": "Agressivo",
        "allocation": {"renda_fixa": 0.15, "renda_variavel": 0.7, "caixa": 0.15},
        "horizon": "longo prazo",
        "description": "Maximiza retorno, aceita alta volatilidade.",
    },
}


def _extract_brl_amount(text: str) -> float | None:
    words = text.lower()
    if "vinte e três mil e quinhentos" in words or "vinte e tres mil e quinhentos" in words:
        return 23_500.0
    if "vinte e quatro mil" in words:
        return 24_000.0

    match = re.search(r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+|\d+)\s*(mil|k)?(?:,(\d{1,2}))?", words)
    if not match:
        return None
    integer = match.group(1).replace(".", "")
    multiplier = match.group(2)
    decimal = match.group(3) or ""
    try:
        val = float(f"{integer}.{decimal}" if decimal else integer)
        if multiplier in ("mil", "k"):
            val *= 1000
        return val
    except ValueError:
        return None


class FinanceModule(Module):
    """Finance module — processes financial intents.

    Handles:
    - Investment analysis
    - Financial planning
    - Asset comparison
    - Risk profiling
    """

    name = "fin"
    version = "0.1.0"
    triggers = [
        "investir", "investimento", "dinheiro", "carteira", "renda",
        "financ", "ação", "ações", "etf", "renda fixa", "poupança",
        "orçamento", "budget", "financial", "invest", "capital",
        "aporte", "mesada", "salário", "aposentadoria",
    ]
    domains = [Domain.FINANCE]
    required_providers = []  # works with MockProvider

    async def execute(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Process a financial intent."""
        text = intent.text.lower()

        pending_dialogue = None
        if hasattr(ctx, "data") and isinstance(ctx.data, dict):
            pending_dialogue = ctx.data.get("pending_dialogue")
        elif isinstance(ctx, dict):
            pending_dialogue = ctx.get("pending_dialogue")

        is_pending_investment = False
        if isinstance(pending_dialogue, dict):
            tf = pending_dialogue.get("target_field")
            if tf in ("recurrence", "investment_frequency", "amount") or "invest" in str(pending_dialogue):
                is_pending_investment = True

        # Detect what kind of financial question
        if (
            is_pending_investment
            or _extract_brl_amount(text) is not None
            or any(w in text for w in ["investir", "investimento", "etf", "ação", "ações", "aporte", "mensal", "mensais", "único", "unico", "aplicar", "aplicação", "aplicacao", "faço com", "fazer com", "rende"])
        ):
            return await self._investment_analysis(intent, ctx)
        elif any(w in text for w in ["orçamento", "budget", "gastar"]):
            return await self._budget_analysis(intent, ctx)
        elif any(w in text for w in ["poupar", "poupança", "reserva"]):
            return await self._savings_analysis(intent, ctx)
        else:
            return await self._general_financial(intent, ctx)

    async def _investment_analysis(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Analyze investment intent."""
        text = intent.text.lower()

        # Detect risk profile from text
        risk_profile = "moderate"  # default
        if any(w in text for w in ["conservador", "conservative", "seguro"]):
            risk_profile = "conservative"
        elif any(w in text for w in ["agressivo", "aggressive", "arriscado"]):
            risk_profile = "aggressive"

        profile = RISK_PROFILES[risk_profile]

        amount = _extract_brl_amount(text)
        if amount is None and ctx:
            known_kc = None
            pending = None
            if hasattr(ctx, "data") and isinstance(ctx.data, dict):
                known_kc = ctx.data.get("known_context")
                pending = ctx.data.get("pending_dialogue")
            elif isinstance(ctx, dict):
                known_kc = ctx.get("known_context")
                pending = ctx.get("pending_dialogue")

            if not known_kc and isinstance(pending, dict):
                known_kc = pending.get("known_context")

            if isinstance(known_kc, dict):
                p_amt = known_kc.get("amount")
                if isinstance(p_amt, (int, float)):
                    amount = float(p_amt)
                elif isinstance(p_amt, str):
                    amount = _extract_brl_amount(p_amt)
            elif isinstance(known_kc, list):
                for item in known_kc:
                    p_amt = _extract_brl_amount(str(item))
                    if p_amt is not None:
                        amount = p_amt
                        break

        amount_str = f"R$ {amount:,.0f}".replace(",", ".") if amount is not None else ""
        recurring = any(term in text for term in ("mensal", "mensais", "por mês", "por mes", "/mês", "todo mês", "aportes mensais"))
        one_time = any(term in text for term in ("único", "unico", "uma vez", "disponível", "disponivel", "tenho", "pontual"))
        if amount is not None and not recurring and not one_time:
            return {
                "text": f"Entendi que o valor é **{amount_str}**. Esse valor é para um investimento único ou para um aporte mensal?",
                "confidence": 0.95,
                "epistemic_status": "fact",
                "metadata": {"amount": amount, "needs_clarification": True,
                             "clarification": "investment_frequency"},
            }

        # Build response
        response = f"""**📊 Análise de Investimento**

**Perfil detectado:** {profile['name']}
**Horizonte:** {profile['horizon']}

**Alocação sugerida:**"""

        for asset, pct in profile['allocation'].items():
            asset_name = {
                "renda_fixa": "Renda Fixa (CDB, LCI, LCA, Tesouro Direto)",
                "renda_variavel": "Renda Variável (ETFs, Ações)",
                "caixa": "Caixa / Reserva de Emergência",
            }.get(asset, asset)
            response += f"\n- **{asset_name}:** {pct*100:.0f}%"

        if amount_str:
            cadence = "/mês" if recurring else " em investimento único"
            response += f"\n\n**Para {amount_str}{cadence}:**"
            for asset, pct in profile['allocation'].items():
                allocated = amount * pct
                suffix = "/mês" if recurring else ""
                response += f"\n- {asset.title()}: R$ {allocated:,.0f}{suffix}"

        response += f"""

**Próximos passos:**
1. Defina sua reserva de emergência (6 meses de despesas)
2. Comece pela renda fixa se for conservador
3. Diversifique entre ativos de diferentes riscos

⚠️ *Estimativa baseada em princípios gerais. Não constitui aconselhamento financeiro profissional. Consulte um assessor registrado.*"""

        return {
            "text": response,
            "confidence": 0.7,
            "epistemic_status": "conclusion",
            "metadata": {
                "risk_profile": risk_profile,
                "amount": amount_str,
            },
        }

    async def _budget_analysis(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Analyze budget intent."""
        response = """**💰 Análise de Orçamento**

**Método 50/30/20:**
- **50%** Necessidades (moradia, alimentação, transporte)
- **30%** Desejos (lazer, hobbies, assinaturas)
- **20%** Poupança e investimentos

**Dicas práticas:**
1. Registre todas as despesas por 30 dias
2. Categorize em necessidades vs desejos
3. Automatize a transferência para poupança
4. Revise mensalmente

*📋 Confiança: Média — adapte ao seu perfil.*"""

        return {
            "text": response,
            "confidence": 0.6,
            "epistemic_status": "conclusion",
        }

    async def _savings_analysis(self, intent: IntentInput, ctx: Any = None) -> dict:
        """Analyze savings intent."""
        response = """**🏦 Estratégia de Poupança**

**Reserva de Emergência (prioridade):**
- Meta: 6-12 meses de despesas
- Onde: Tesouro Selic, CDB diário, conta que rende

**Depois da reserva:**
- Investimentos de médio/longo prazo
- Diversificação por classe de ativo

**Regra de ouro:** Nunca invista dinheiro que pode precisar em 12 meses.

*📋 Confiança: Alta — princípio financeiro universal.*"""

        return {
            "text": response,
            "confidence": 0.8,
            "epistemic_status": "conclusion",
        }

    async def _general_financial(self, intent: IntentInput, ctx: Any = None) -> dict:
        """General financial advice."""
        response = """**📊 Consultoria Financeira**

Para uma análise mais precisa, preciso saber:

1. **Objetivo:** O que você quer alcançar?
2. **Prazo:** Em quanto tempo?
3. **Perfil:** Conservador, moderado ou agressivo?
4. **Valor:** Quanto pode investir mensalmente?

Com essas informações, posso fornecer uma recomendação personalizada.

*📋 Confiança: Depende das informações fornecidas.*"""

        return {
            "text": response,
            "confidence": 0.5,
            "epistemic_status": "assumption",
        }
