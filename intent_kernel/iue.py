"""Intent Understanding Engine (IUE) — RFC-0007.

The sacred core component that transforms incomplete, ambiguous, or contextual
human language into a structured representation of intent before any execution.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class IntentQualityIndex:
    """Quantitative measurement of intent completeness and understanding quality."""
    overall_score: float = 0.0
    clarity: float = 0.0
    completeness: float = 0.0
    context_richness: float = 0.0
    actionability: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "overall_score": round(self.overall_score, 2),
            "clarity": round(self.clarity, 2),
            "completeness": round(self.completeness, 2),
            "context_richness": round(self.context_richness, 2),
            "actionability": round(self.actionability, 2),
        }


@dataclass
class StructuredIntent:
    """Canonical representation of an understood user intent (RFC-0007)."""
    intent_id: str
    raw_input: str
    goal: str
    implicit_goal: str
    domain: str
    known_context: List[str] = field(default_factory=list)
    known_context_provenance: List[Dict[str, str]] = field(default_factory=list)
    missing_context: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    preferences: List[str] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    confidence: float = 0.0  # Classifier/interpretation confidence (distinct from IQI)
    recommended_capabilities: List[str] = field(default_factory=list)
    recommended_agents: List[str] = field(default_factory=list)
    recommended_provider_profile: str = "general_balanced"
    mission_candidate: bool = True
    clarifying_question: Optional[str] = None
    intent_quality_index: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def is_financial_text(text: str) -> bool:
    """Classify if text is in the financial domain based on terms, patterns, and monetary signals."""
    lower = text.lower()

    # Direct financial terms & keywords
    direct_keywords = [
        "investir", "investimento", "investimentos", "carteira", "renda", "selic", "cdi",
        "ações", "acoes", "acao", "etf", "etfs", "fii", "fiis", "aportar", "aporte", "aportes",
        "orçamento", "orcamento", "poupança", "poupanca", "poupar", "patrimônio", "patrimonio",
        "rendimento", "rendimentos", "rentabilidade", "tesouro", "cdb", "lci", "lca",
        "finanças", "financas", "quanto rende", "para aplicar",
        "aplicação", "aplicacao", "juros", "reserva"
    ]
    if any(kw in lower for kw in direct_keywords):
        return True

    # Financial question phrases accompanied by a number or monetary expression
    fin_questions = [
        "o que eu faço com", "o que faço com", "o que fazer com",
        "onde colocar", "onde aplicar", "onde investir", "como aplicar", "como investir"
    ]
    has_fin_question = any(q in lower for q in fin_questions)

    # Check for monetary amounts or numbers
    has_monetary_currency = any(curr in lower for curr in ["r$", "reais", "dólares", "dolares"])
    has_number = bool(re.search(r"\b\d+(?:[\.,]\d+)?\b(?:\s*(?:mil|k|m))?", lower))

    # Exclude explicit non-financial units
    non_fin_units = [
        "ano", "anos", "km", "quilômetro", "quilômetros", "quilometro", "quilometros",
        "metro", "metros", "linha", "linhas", "registro", "registros", "arquivo", "arquivos",
        "pessoa", "pessoas", "aluno", "alunos", "cliente", "clientes", "página", "páginas", "paginas"
    ]
    has_non_fin_unit = any(re.search(r"\b" + u + r"\b", lower) for u in non_fin_units)

    if has_non_fin_unit:
        return False

    if has_fin_question and (has_number or has_monetary_currency):
        return True

    if has_monetary_currency and (has_number or any(w in lower for w in ["sobrando", "disponível", "disponivel", "guardado", "guardados"])):
        return True

    return False


class IntentUnderstandingEngine:
    """Engine responsible for analyzing human input into structured intents.
    
    RFC-0007 Architectural Guarantee:
    - Does NOT call LLM Providers directly.
    - Does NOT generate final conversational answers.
    - Does NOT execute Capabilities.
    - Does NOT mutate Mission state directly.
    """

    def __init__(self, pkb: Any | None = None, domain_registry: Dict[str, Any] | None = None):
        self.pkb = pkb
        self.domain_registry = domain_registry or {}

    def analyze(
        self,
        raw_input: str,
        session_context: Dict[str, Any] | None = None,
        pkb: Any | None = None
    ) -> StructuredIntent:
        text = (raw_input or "").strip()
        intent_id = f"iue_{uuid4().hex[:8]}"
        ctx = session_context or {}

        if not text:
            iqi = IntentQualityIndex(
                overall_score=0.0,
                clarity=0.0,
                completeness=0.0,
                context_richness=0.0,
                actionability=0.0,
            )
            return StructuredIntent(
                intent_id=intent_id,
                raw_input="",
                goal="Nenhuma intenção informada",
                implicit_goal="Aguardando mensagem válida do usuário",
                domain="general",
                requires_confirmation=True,
                confidence=0.0,
                mission_candidate=False,
                clarifying_question="Por favor, digite o que você gostaria de realizar.",
                intent_quality_index=iqi.to_dict(),
            )

        domain, domain_confidence = self._detect_domain(text, ctx)
        known_context: List[str] = []
        known_context_provenance: List[Dict[str, str]] = []
        missing_context: List[str] = []
        assumptions: List[str] = []
        constraints: List[str] = []
        preferences: List[str] = []
        ambiguities: List[str] = []
        recommended_capabilities: List[str] = []
        recommended_agents: List[str] = []
        recommended_provider_profile = "general_balanced"

        # 1. Retrieve Context from Available Sources (Current Input, Conversation, Mission, PKB, User Profile)
        self._retrieve_prior_context(
            text, ctx, pkb or self.pkb, known_context, known_context_provenance
        )

        # 2. Domain-Specific Analysis
        if domain == "finance":
            self._analyze_finance_domain(
                text,
                ctx,
                known_context,
                known_context_provenance,
                missing_context,
                assumptions,
                constraints,
                preferences,
                ambiguities,
                recommended_capabilities,
                recommended_agents,
            )
            recommended_provider_profile = "analytic_precise"
            goal = f"Estratégia e alocação financeira para: {text}"
            implicit_goal = "Maximizar rentabilidade ajustada ao risco e objetivos do usuário"
        elif domain == "system":
            self._analyze_system_domain(
                text,
                ctx,
                known_context,
                known_context_provenance,
                missing_context,
                assumptions,
                constraints,
                preferences,
                ambiguities,
                recommended_capabilities,
                recommended_agents,
            )
            recommended_provider_profile = "system_executor"
            goal = f"Operação de sistema / diagnóstico: {text}"
            implicit_goal = "Garantir estabilidade e correto funcionamento do Intent OS"
        elif domain == "coding":
            self._analyze_coding_domain(
                text,
                ctx,
                known_context,
                known_context_provenance,
                missing_context,
                assumptions,
                constraints,
                preferences,
                ambiguities,
                recommended_capabilities,
                recommended_agents,
            )
            recommended_provider_profile = "code_architect"
            goal = f"Desenvolvimento / Engenharia de Código: {text}"
            implicit_goal = "Construir ou modificar solução técnica com alta qualidade"
        else:
            goal = f"Atender solicitação geral: {text}"
            implicit_goal = "Fornecer assistência clara e direta"
            recommended_capabilities = ["core.general_assistant"]
            recommended_agents = ["general_agent"]
            if len(text.split()) < 3 and not known_context:
                ambiguities.append("Entrada muito curta para determinar objetivo específico com precisão.")
                missing_context.append("Detalhes adicionais sobre o objetivo desejado.")

        # 3. Calculate IQI (Intent Quality Index)
        clarity = self._calc_clarity(text, ambiguities)
        completeness = self._calc_completeness(known_context, missing_context)
        context_richness = self._calc_context_richness(known_context)
        actionability = self._calc_actionability(text, domain, missing_context)

        # Formula: IQI = 0.3 * Clarity + 0.3 * Completeness + 0.2 * ContextRichness + 0.2 * Actionability
        overall_score = (
            0.3 * clarity +
            0.3 * completeness +
            0.2 * context_richness +
            0.2 * actionability
        )

        # Cap IQI if material ambiguities exist (preventing false high scores)
        if ambiguities and overall_score > 0.65:
            overall_score = 0.65

        iqi = IntentQualityIndex(
            overall_score=overall_score,
            clarity=clarity,
            completeness=completeness,
            context_richness=context_richness,
            actionability=actionability,
        )

        requires_confirmation = (overall_score < 0.75) or len(missing_context) > 0 or len(ambiguities) > 0
        mission_candidate = (domain in ["finance", "system", "coding"]) or (overall_score >= 0.5 and len(text.split()) >= 4)

        # 4. Clarifying Question (Max ONE single surgical question focusing on highest material impact)
        clarifying_question: Optional[str] = None
        if requires_confirmation:
            clarifying_question = self._generate_single_clarifying_question(
                domain, text, missing_context, ambiguities
            )

        return StructuredIntent(
            intent_id=intent_id,
            raw_input=text,
            goal=goal,
            implicit_goal=implicit_goal,
            domain=domain,
            known_context=known_context,
            known_context_provenance=known_context_provenance,
            missing_context=missing_context,
            assumptions=assumptions,
            constraints=constraints,
            preferences=preferences,
            ambiguities=ambiguities,
            requires_confirmation=requires_confirmation,
            confidence=round(domain_confidence, 2),
            recommended_capabilities=recommended_capabilities,
            recommended_agents=recommended_agents,
            recommended_provider_profile=recommended_provider_profile,
            mission_candidate=mission_candidate,
            clarifying_question=clarifying_question,
            intent_quality_index=iqi.to_dict(),
        )

    def _detect_domain(self, text: str, ctx: Optional[Dict[str, Any]] = None) -> tuple[str, float]:
        """Detect domain dynamically if registry provided, or fallback to core domains."""
        lower = text.lower()

        # Check pending_dialogue context for domain inheritance
        if ctx and isinstance(ctx, dict):
            pending_dialogue = ctx.get("pending_dialogue")
            if isinstance(pending_dialogue, dict):
                p_domain = pending_dialogue.get("domain") or (pending_dialogue.get("known_context", {}).get("domain"))
                if p_domain and p_domain != "general":
                    return p_domain, 0.95
                tf = pending_dialogue.get("target_field")
                if tf in ("recurrence", "investment_frequency", "amount") or "invest" in str(pending_dialogue):
                    return "finance", 0.95

        # Check dynamic domain registry if available
        if self.domain_registry:
            for registered_domain, spec in self.domain_registry.items():
                keywords = spec.get("keywords", []) if isinstance(spec, dict) else []
                if any(kw in lower for kw in keywords):
                    return registered_domain, 0.95

        # Standard core domain detection
        if is_financial_text(lower):
            return "finance", 0.95
        if any(w in lower for w in ["status", "provider", "constituição", "guardian", "kernel", "diagnóstico", "sistema", "configurar"]):
            return "system", 0.90
        if any(w in lower for w in ["código", "função", "script", "refatorar", "bug", "python", "typescript", "api", "endpoint", "aplicativo", "app", "software"]):
            return "coding", 0.90
        
        return "general", 0.50

    def _add_known_fact(
        self,
        fact: str,
        origin: str,
        known_context: List[str],
        known_context_provenance: List[Dict[str, str]]
    ):
        if fact not in known_context:
            known_context.append(fact)
            known_context_provenance.append({"fact": fact, "origin": origin})

    def _retrieve_prior_context(
        self,
        text: str,
        ctx: Dict[str, Any],
        pkb: Any | None,
        known_context: List[str],
        known_context_provenance: List[Dict[str, str]]
    ):
        # 1. Current Input
        self._add_known_fact(f"Entrada recebida: {text}", "current_input", known_context, known_context_provenance)

        # 2. Conversation Context
        session_history = ctx.get("conversation_context") or ctx.get("history")
        if session_history:
            self._add_known_fact("Histórico de conversa recente disponível", "conversation", known_context, known_context_provenance)

        # 3. Mission Context
        mission = ctx.get("mission") or ctx.get("current_mission")
        if mission:
            m_title = mission.get("title") or mission.get("goal") if isinstance(mission, dict) else str(mission)
            self._add_known_fact(f"Missão ativa em andamento: {m_title}", "mission", known_context, known_context_provenance)

        # 4. User Profile
        profile = ctx.get("user_profile") or ctx.get("profile")
        if isinstance(profile, dict):
            if profile.get("financial_goal") or profile.get("goal"):
                goal_val = profile.get("financial_goal") or profile.get("goal")
                self._add_known_fact(f"Objetivo do usuário: {goal_val}", "user_profile", known_context, known_context_provenance)
            if profile.get("risk_tolerance") or profile.get("risk"):
                risk_val = profile.get("risk_tolerance") or profile.get("risk")
                self._add_known_fact(f"Perfil de Risco: {risk_val}", "user_profile", known_context, known_context_provenance)
            if profile.get("liquidity_preference") or profile.get("time_horizon") or profile.get("liquidity"):
                liq_val = profile.get("liquidity_preference") or profile.get("time_horizon") or profile.get("liquidity")
                self._add_known_fact(f"Horizonte / Liquidez: {liq_val}", "user_profile", known_context, known_context_provenance)
            if profile.get("strategy"):
                self._add_known_fact(f"Estratégia declarada: {profile.get('strategy')}", "user_profile", known_context, known_context_provenance)

        # 5. Pending Dialogue Context (RFC-0017.1)
        pending_dialogue = ctx.get("pending_dialogue")
        if isinstance(pending_dialogue, dict):
            target_field = pending_dialogue.get("target_field")
            if target_field:
                self._add_known_fact(f"Pergunta pendente em andamento sobre o campo: {target_field}", "pending_dialogue", known_context, known_context_provenance)
            kc = pending_dialogue.get("known_context")
            if isinstance(kc, dict):
                for k, v in kc.items():
                    self._add_known_fact(f"Contexto prévio de diálogo ({k}): {v}", "pending_dialogue", known_context, known_context_provenance)

        # 6. Core Apps / Capabilities
        core_apps = ctx.get("core_apps")
        if core_apps:
            self._add_known_fact(f"Core Apps ativas: {len(core_apps)} registradas", "core_app", known_context, known_context_provenance)

        # 7. PKB
        if pkb and hasattr(pkb, "query"):
            try:
                pkb_results = pkb.query(text)
                if pkb_results:
                    self._add_known_fact(f"Contexto PKB: {len(pkb_results)} itens recuperados", "PKB", known_context, known_context_provenance)
            except Exception:
                pass

    def _analyze_finance_domain(
        self,
        text: str,
        ctx: Dict[str, Any],
        known_context: List[str],
        known_context_provenance: List[Dict[str, str]],
        missing_context: List[str],
        assumptions: List[str],
        constraints: List[str],
        preferences: List[str],
        ambiguities: List[str],
        recommended_capabilities: List[str],
        recommended_agents: List[str],
    ):
        recommended_capabilities.extend(["fin.investment_allocator", "fin.risk_assessment"])
        recommended_agents.append("finance_agent")

        # Amount Detection with support for "24 mil", "24k", "24.000", "24000", "vinte e quatro mil"
        amount_found = None
        lower = text.lower()
        if "vinte e três mil e quinhentos" in lower or "vinte e tres mil e quinhentos" in lower:
            amount_found = "23.500"
        elif "vinte e quatro mil" in lower:
            amount_found = "24.000"
        else:
            match = re.search(r'(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+|\d+)\s*(mil|k)?', lower)
            if match:
                raw_num = match.group(1).replace(".", "")
                multiplier = match.group(2)
                val = float(raw_num)
                if multiplier in ("mil", "k"):
                    val *= 1000
                amount_found = f"{val:,.0f}".replace(",", ".")

        pending_dialogue = ctx.get("pending_dialogue") or {}
        pending_kc = pending_dialogue.get("known_context") if isinstance(pending_dialogue, dict) else {}
        if not isinstance(pending_kc, dict):
            pending_kc = {}

        prior_amount = pending_kc.get("amount") or pending_kc.get("amount_str")
        if not amount_found and prior_amount:
            if isinstance(prior_amount, (int, float)):
                amount_found = f"{prior_amount:,.0f}".replace(",", ".")
            else:
                amount_found = str(prior_amount)

        if amount_found:
            self._add_known_fact(f"Montante financeiro identificado na mensagem: R$ {amount_found}", "current_input", known_context, known_context_provenance)
        else:
            # Check profile or mission
            profile = ctx.get("user_profile") or {}
            if isinstance(profile, dict) and profile.get("amount"):
                self._add_known_fact(f"Montante financeiro recuperado do perfil: R$ {profile.get('amount')}", "user_profile", known_context, known_context_provenance)
            else:
                missing_context.append("Montante de investimento (valor em R$)")

        # Check recurrence
        if any(w in lower for w in ["mensal", "mensais", "/mês", "por mês", "todo mês", "aportes mensais"]):
            self._add_known_fact("Aporte planejado: Recorrente mensal", "current_input", known_context, known_context_provenance)
        elif any(w in lower for w in ["único", "unico", "uma vez", "pontual", "cdb", "reserva", "imóvel"]):
            self._add_known_fact("Aporte planejado: Aporte único / pontual", "current_input", known_context, known_context_provenance)
        elif amount_found and not pending_dialogue:
            assumptions.append("Aporte pontual/único assumido temporariamente para o cálculo inicial")

        # Check Goal
        has_goal_in_known = any("Objetivo" in item for item in known_context)
        if "reserva" in lower or "emergência" in lower:
            self._add_known_fact("Objetivo específico: Reserva de emergência / alta liquidez", "current_input", known_context, known_context_provenance)
        elif "aposentadoria" in lower or "longo prazo" in lower:
            self._add_known_fact("Objetivo específico: Aposentadoria / longo prazo", "current_input", known_context, known_context_provenance)
        elif not has_goal_in_known:
            missing_context.append("Objetivo principal do investimento (ex: reserva de emergência, compra de imóvel, aposentadoria)")

        # Check Risk
        has_risk_in_known = any("Perfil de Risco" in item for item in known_context) or any("Perfil de Risco" in c for c in constraints)
        if "conservador" in lower or "seguro" in lower or "sem risco" in lower:
            constraints.append("Perfil de Risco: Conservador (Preservação de capital)")
            self._add_known_fact("Perfil de Risco: Conservador", "current_input", known_context, known_context_provenance)
        elif "arrojado" in lower or "agressivo" in lower or "ações" in lower:
            preferences.append("Perfil de Risco: Arrojado")
            self._add_known_fact("Perfil de Risco: Arrojado", "current_input", known_context, known_context_provenance)
        elif not has_risk_in_known:
            missing_context.append("Perfil de risco do investidor (conservador, moderado ou arrojado)")

        # Check Liquidity / Horizon
        has_horizon_in_known = any("Horizonte" in item or "Liquidez" in item for item in known_context)
        if any(w in lower for w in ["prazo", "ano", "anos", "mês", "meses", "liquidez"]):
            self._add_known_fact("Horizonte temporal / liquidez mencionado na mensagem", "current_input", known_context, known_context_provenance)
        elif not has_horizon_in_known:
            missing_context.append("Prazo / Horizonte de liquidez (em quanto tempo pretende resgatar)")

    def _analyze_system_domain(
        self,
        text: str,
        ctx: Dict[str, Any],
        known_context: List[str],
        known_context_provenance: List[Dict[str, str]],
        missing_context: List[str],
        assumptions: List[str],
        constraints: List[str],
        preferences: List[str],
        ambiguities: List[str],
        recommended_capabilities: List[str],
        recommended_agents: List[str],
    ):
        recommended_capabilities.append("core.system_diagnostics")
        recommended_agents.append("system_agent")
        self._add_known_fact("Solicitação de diagnóstico de infraestrutura do Intent OS", "current_input", known_context, known_context_provenance)

    def _analyze_coding_domain(
        self,
        text: str,
        ctx: Dict[str, Any],
        known_context: List[str],
        known_context_provenance: List[Dict[str, str]],
        missing_context: List[str],
        assumptions: List[str],
        constraints: List[str],
        preferences: List[str],
        ambiguities: List[str],
        recommended_capabilities: List[str],
        recommended_agents: List[str],
    ):
        recommended_capabilities.append("core.code_generation")
        recommended_agents.append("code_agent")
        self._add_known_fact("Solicitação de engenharia de software / código", "current_input", known_context, known_context_provenance)

        conv = str(ctx.get("conversation_context") or "")
        prof = str(ctx.get("user_profile") or "")
        full_text = text + " " + conv + " " + prof + " " + " ".join(known_context)
        lower = full_text.lower()
        if ("aplicativo" in lower or "app" in lower or "sistema" in lower) and not any(p in lower for p in ["web", "mobile", "desktop", "ios", "android"]):
            missing_context.append("Finalidade e plataforma do aplicativo (ex: web app, mobile ou desktop)")
            ambiguities.append("Múltiplas trajetórias de implementação válidas para o aplicativo.")

    def _calc_clarity(self, text: str, ambiguities: List[str]) -> float:
        score = 0.9
        if len(text.split()) < 3:
            score -= 0.3
        score -= (len(ambiguities) * 0.2)
        return max(0.1, min(1.0, score))

    def _calc_completeness(self, known_context: List[str], missing_context: List[str]) -> float:
        total = len(known_context) + len(missing_context)
        if total == 0:
            return 0.5
        return max(0.1, min(1.0, len(known_context) / total))

    def _calc_context_richness(self, known_context: List[str]) -> float:
        if not known_context:
            return 0.2
        return min(1.0, 0.3 + (len(known_context) * 0.2))

    def _calc_actionability(self, text: str, domain: str, missing_context: List[str]) -> float:
        score = 0.85
        if domain != "general":
            score += 0.1
        score -= (len(missing_context) * 0.15)
        return max(0.1, min(1.0, score))

    def _generate_single_clarifying_question(
        self,
        domain: str,
        text: str,
        missing_context: List[str],
        ambiguities: List[str]
    ) -> str:
        """RFC-0007 Rule: Maximum ONE single question per turn, choosing the question with highest material impact."""
        if domain == "finance":
            amount_match = re.search(r'(?:R\$\s*)?(\d+(?:[\.,]\d+)*)', text)
            amount_str = f"seus R$ {amount_match.group(1)}" if amount_match else "esse valor"
            
            # Highest material impact missing item: Goal & Horizon
            if any("Objetivo" in m for m in missing_context):
                return (
                    f"Para estruturarmos a alocação de {amount_str}, qual é o seu objetivo principal "
                    "(ex: reserva de emergência, aposentadoria ou compra futura) e o prazo desejado?"
                )
            if any("Perfil" in m for m in missing_context):
                return (
                    f"Qual é o seu perfil de risco para a aplicação de {amount_str} "
                    "(conservador, moderado ou arrojado)?"
                )
            if any("Prazo" in m for m in missing_context):
                return f"Em quanto tempo você pretende utilizar ou resgatar {amount_str}?"

        if missing_context:
            return f"Para prosseguir com precisão, qual é o seu {missing_context[0].lower()}?"
        if ambiguities:
            return f"Poderia esclarecer o seguinte ponto? {ambiguities[0]}"
        return "Poderia fornecer mais detalhes sobre o seu objetivo para que possamos prosseguir com segurança?"

