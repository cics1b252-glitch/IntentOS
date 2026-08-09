"""IntentEngine — parses and classifies user intent."""

from __future__ import annotations

import re
from intent_kernel.types import (
    Domain,
    EpistemicStatus,
    IntentInput,
    Mode,
    ParsedIntent,
)


# Domain keyword mappings
DOMAIN_KEYWORDS: dict[Domain, list[str]] = {
    Domain.FINANCE: [
        "investir", "investimento", "dinheiro", "carteira", "renda",
        "financ", "ação", "ações", "etf", "renda fixa", "poupança",
        "orçamento", "budget", "financial", "invest", "aporte", "aportes",
        "mensal", "mensais", "único", "unico", "reserva", "juros", "taxa",
    ],
    Domain.EDUCATION: [
        "estud", "aprend", "curso", "escola", "ensino", "aula",
        "data science", "machine learning", "python", "programação",
        "tutorial", "learn", "study", "course",
    ],
    Domain.BUSINESS: [
        "negócio", "business", "startup", "empresa", "saas",
        "receita", "venda", "marketing", "cliente", "mercado",
        "modelo de negócio", "pitch", "investidor",
    ],
    Domain.ENGINEERING: [
        "código", "code", "program", "desenvolv", "software",
        "api", "backend", "frontend", "deploy", "infra",
        "docker", "kubernetes", "sistema", "arquitetura",
    ],
    Domain.WRITING: [
        "escrev", "texto", "artigo", "blog", "redação",
        "copywriting", "rfc", "documento", "memorando",
    ],
    Domain.RESEARCH: [
        "pesquis", "research", "análise", "estudo", "relatório",
        "dados", "data", "statistic", "estatístic",
    ],
    Domain.PLANNING: [
        "planej", "plano", "roadmap", "estratégia", "strategy",
        "objetivo", "meta", "goal", "projeto", "project",
    ],
    Domain.CREATIVITY: [
        "criativ", "ideia", "brainstorm", "design", "brand",
        "visual", "arte", "content",
    ],
    Domain.LEGAL: [
        "lei", "legal", "jurídic", "contrato", "regulament",
        "compliance", "advocacia",
    ],
    Domain.LIFE: [
        "vida", "saúde", "bem-estar", "rotina", "hábito",
        "casa", "família", "relacionamento",
    ],
}

# Mode complexity indicators
MODE_INDICATORS: dict[Mode, list[str]] = {
    Mode.QUICK: [
        "rápido", "resumo", "breve", "curto", "quick",
    ],
    Mode.DETAIL: [
        "detalhe", "detalhado", "completo", "aprofund", "explic",
    ],
    Mode.EXPERT: [
        "expert", "avançado", "complexo", "análise profunda",
        "trade-off", "risco", "compar",
    ],
    Mode.ARCHITECT: [
        "sistema", "arquitetura", "plano completo", "roadmap",
        "fases", "longo prazo", "estrutura",
    ],
}


class IntentEngine:
    """Parses user intent and classifies domain + mode."""

    async def parse(self, text: str, context: dict[str, Any] | None = None) -> ParsedIntent:
        """Parse intent text into structured form.

        Returns ParsedIntent with:
        - Cleaned intent text
        - Domain classification
        - Mode assessment
        - Detected entities
        - Ambiguities found
        """
        # Clean and normalize
        clean_text = text.strip()

        # Detect domain
        domain = self._detect_domain(clean_text, context=context)

        # Detect mode
        mode = self._detect_mode(clean_text)

        # Extract entities (simple keyword extraction)
        entities = self._extract_entities(clean_text)

        # Detect ambiguities
        ambiguities = self._detect_ambiguities(clean_text)

        return ParsedIntent(
            raw_text=text,
            intent=clean_text,
            domain=domain,
            mode=mode,
            entities=entities,
            ambiguities=ambiguities,
        )

    def _detect_domain(self, text: str, context: dict[str, Any] | None = None) -> Domain:
        """Detect the primary domain from text."""
        text_lower = text.lower()

        from intent_kernel.iue import is_financial_text
        if is_financial_text(text_lower):
            return Domain.FINANCE

        scores: dict[Domain, int] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[domain] = score

        if scores:
            return max(scores, key=scores.get)

        if context:
            # 1. Check structured_intent from IUE if passed
            s_intent = context.get("structured_intent")
            if isinstance(s_intent, dict) and s_intent.get("domain"):
                d_str = s_intent.get("domain")
                try:
                    return Domain(d_str)
                except ValueError:
                    pass

            # 2. Check pending_dialogue
            pending = context.get("pending_dialogue")
            if isinstance(pending, dict):
                tf = pending.get("target_field")
                p_dom = pending.get("domain") or pending.get("known_context", {}).get("domain")
                if p_dom:
                    try:
                        return Domain(p_dom)
                    except ValueError:
                        pass
                if tf in ("recurrence", "investment_frequency", "amount") or "invest" in str(pending):
                    return Domain.FINANCE

        return Domain.OTHER

    def _detect_mode(self, text: str) -> Mode:
        """Detect the appropriate processing mode."""
        text_lower = text.lower()
        scores: dict[Mode, int] = {}

        for mode, indicators in MODE_INDICATORS.items():
            score = sum(1 for ind in indicators if ind in text_lower)
            if score > 0:
                scores[mode] = score

        # Default to BASIC if no strong signal
        if not scores:
            # Check length as a heuristic
            if len(text) > 200:
                return Mode.DETAIL
            elif len(text) < 30:
                return Mode.QUICK
            return Mode.BASIC

        return max(scores, key=scores.get)

    def _extract_entities(self, text: str) -> list[str]:
        """Extract key entities from text (simple approach)."""
        entities = []

        # Look for quoted strings
        quoted = re.findall(r'"([^"]+)"', text)
        entities.extend(quoted)

        # Look for numbers with context
        numbers = re.findall(r'(\d+[\.,]?\d*)\s*(reais|k|mil|milhão|milhões|%)', text.lower())
        for num, unit in numbers:
            entities.append(f"{num} {unit}")

        # Look for proper nouns (simple heuristic)
        words = text.split()
        for word in words:
            if word[0:1].isupper() and len(word) > 2 and word not in ("Eu", "Você", "O", "A"):
                entities.append(word)

        return list(set(entities))[:10]  # max 10 entities

    def _detect_ambiguities(self, text: str) -> list[str]:
        """Detect potential ambiguities in the intent."""
        ambiguities = []

        # Very short text
        if len(text.split()) < 3:
            ambiguities.append("Texto muito curto — intenção pode ser ambígua")

        # Multiple question marks
        if text.count("?") > 2:
            ambiguities.append("Múltiplas perguntas — qual é a prioridade?")

        # Generic terms
        generic = ["coisa", "algo", "aquilo", "isso", "tal"]
        for term in generic:
            if term in text.lower():
                ambiguities.append(f"Termo genérico '{term}' — pode precisar de especificação")
                break

        # Missing context indicators
        context_words = ["por que", "como", "quando", "onde", "quem"]
        if not any(w in text.lower() for w in context_words):
            if len(text.split()) > 10:
                ambiguities.append("Sem pergunta explícita — intenção inferida")

        return ambiguities
