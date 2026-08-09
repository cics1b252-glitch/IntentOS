"""Multi-Agent System — Intent OS as orchestrator.

Multiple specialized agents working together, coordinated by the Kernel.
Each agent has expertise in a domain. Intent OS routes work to the best agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import asyncio


@dataclass
class AgentCapability:
    """A capability of an agent."""
    name: str
    description: str
    domains: list[str] = field(default_factory=list)


@dataclass
class AgentMessage:
    """A message between agents."""
    from_agent: str
    to_agent: str
    content: str
    message_type: str = "request"  # request, response, delegation
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result from an agent."""
    agent_id: str
    content: str
    confidence: float = 0.0
    domain: str = ""
    events_created: int = 0


class BaseAgent:
    """Base class for all agents."""

    def __init__(self, agent_id: str, name: str, description: str, kernel: Any = None):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.kernel = kernel
        self.capabilities: list[AgentCapability] = []
        self._messages: list[AgentMessage] = []

    @property
    def domains(self) -> list[str]:
        domains = []
        for cap in self.capabilities:
            domains.extend(cap.domains)
        return list(set(domains))

    async def process(self, text: str, context: dict | None = None) -> AgentResult:
        """Process a request. Override in subclasses."""
        return AgentResult(
            agent_id=self.agent_id,
            content=f"{self.name} received: {text}",
            confidence=0.5,
        )

    def receive_message(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def get_messages(self) -> list[AgentMessage]:
        return list(self._messages)


class FinanceAgent(BaseAgent):
    """Specialized agent for financial matters."""

    def __init__(self, kernel: Any = None):
        super().__init__(
            agent_id="finance",
            name="Atlas",
            description="Agente financeiro especializado",
            kernel=kernel,
        )
        self.capabilities = [
            AgentCapability("investment_analysis", "Análise de investimentos", ["finance"]),
            AgentCapability("portfolio", "Gestão de carteira", ["finance"]),
            AgentCapability("retirement", "Planejamento de aposentadoria", ["finance"]),
        ]

    async def process(self, text: str, context: dict | None = None) -> AgentResult:
        text_lower = text.lower()

        if any(w in text_lower for w in ["investir", "investimento", "fiis", "etf"]):
            return await self._investment_response(text, context)
        elif any(w in text_lower for w in ["aposentadoria", "aposentar"]):
            return await self._retirement_response(text, context)
        else:
            return AgentResult(
                agent_id=self.agent_id,
                content="Posso ajudar com investimentos, carteira ou aposentadoria. O que você precisa?",
                confidence=0.6,
                domain="finance",
            )

    async def _investment_response(self, text: str, context: dict | None) -> AgentResult:
        return AgentResult(
            agent_id=self.agent_id,
            content="Vou analisar sua situação de investimento. Para uma recomendação personalizada, preciso saber: quanto pretende investir, seu perfil de risco e seu objetivo.",
            confidence=0.7,
            domain="finance",
        )

    async def _retirement_response(self, text: str, context: dict | None) -> AgentResult:
        return AgentResult(
            agent_id=self.agent_id,
            content="Planejamento de aposentadoria é uma decisão de longo prazo. Vou ajudar a calcular quanto você precisa e quanto tempo levará.",
            confidence=0.7,
            domain="finance",
        )


class KnowledgeAgent(BaseAgent):
    """Specialized agent for knowledge management."""

    def __init__(self, kernel: Any = None):
        super().__init__(
            agent_id="knowledge",
            name="Logos",
            description="Agente de gestão do conhecimento",
            kernel=kernel,
        )
        self.capabilities = [
            AgentCapability("project_management", "Gestão de projetos", ["knowledge"]),
            AgentCapability("decision_tracking", "Registro de decisões", ["knowledge"]),
            AgentCapability("research", "Pesquisa organizada", ["knowledge"]),
        ]

    async def process(self, text: str, context: dict | None = None) -> AgentResult:
        text_lower = text.lower()

        if any(w in text_lower for w in ["projeto", "project"]):
            return AgentResult(
                agent_id=self.agent_id,
                content="Vou ajudar a organizar seu projeto. Qual é o nome e o objetivo?",
                confidence=0.7,
                domain="knowledge",
            )
        elif any(w in text_lower for w in ["decisão", "decision", "escolher"]):
            return AgentResult(
                agent_id=self.agent_id,
                content="Vou ajudar a registrar essa decisão. Qual é a pergunta, quais alternativas e qual sua escolha?",
                confidence=0.7,
                domain="knowledge",
            )
        else:
            return AgentResult(
                agent_id=self.agent_id,
                content="Posso ajudar com projetos, decisões ou organização do conhecimento. O que você precisa?",
                confidence=0.6,
                domain="knowledge",
            )


class EngineeringAgent(BaseAgent):
    """Specialized agent for engineering."""

    def __init__(self, kernel: Any = None):
        super().__init__(
            agent_id="engineering",
            name="OEM Studio",
            description="Agente de engenharia",
            kernel=kernel,
        )
        self.capabilities = [
            AgentCapability("cad", "Projetos CAD", ["engineering"]),
            AgentCapability("documentation", "Documentação técnica", ["engineering"]),
        ]

    async def process(self, text: str, context: dict | None = None) -> AgentResult:
        return AgentResult(
            agent_id=self.agent_id,
            content="Vou ajudar com seu projeto de engenharia. Conte mais detalhes sobre o que precisa.",
            confidence=0.6,
            domain="engineering",
        )


class AgentOrchestrator:
    """Orchestrates multiple agents. Intent OS is the brain.

    Routes requests to the best agent based on domain and capability.
    Manages inter-agent communication.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.agents: dict[str, BaseAgent] = {}
        self._register_default_agents()

    def _register_default_agents(self) -> None:
        self.register(FinanceAgent(self.kernel))
        self.register(KnowledgeAgent(self.kernel))
        self.register(EngineeringAgent(self.kernel))

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str) -> BaseAgent | None:
        return self.agents.get(agent_id)

    def find_best_agent(self, text: str) -> BaseAgent | None:
        """Find the best agent for a given text."""
        text_lower = text.lower()
        scores = {}

        # Domain keywords mapping
        domain_keywords = {
            "finance": ["investir", "investimento", "fiis", "etf", "ações", "carteira", "renda", "financeiro", "finance", "aposentadoria"],
            "knowledge": ["projeto", "project", "decisão", "decision", "rfc", "documento", "nota", "pesquisa"],
            "engineering": ["api", "código", "sistema", "deploy", "engenharia", "engineering", "hardware", "software"],
        }

        for agent_id, agent in self.agents.items():
            score = 0
            for domain in agent.domains:
                keywords = domain_keywords.get(domain, [])
                for kw in keywords:
                    if kw in text_lower:
                        score += 10
            # Also check agent name
            if agent.name.lower() in text_lower:
                score += 15
            if score > 0:
                scores[agent_id] = score

        if not scores:
            # Default to knowledge agent
            return self.agents.get("knowledge")

        best_id = max(scores, key=scores.get)
        return self.agents.get(best_id)

    async def process(self, text: str, context: dict | None = None) -> AgentResult:
        """Route and process a request through the best agent."""
        agent = self.find_best_agent(text)
        if not agent:
            return AgentResult(
                agent_id="orchestrator",
                content="Não encontrei um agente especializado para isso. Posso ajudar de forma geral.",
                confidence=0.3,
            )

        result = await agent.process(text, context)

        # Log to KC if kernel available
        if self.kernel:
            try:
                from intent_kernel.pkb.models import KnowledgeEvent
                from intent_kernel.types import EventType, Domain

                domain_map = {
                    "finance": Domain.FINANCE,
                    "knowledge": Domain.PLANNING,
                    "engineering": Domain.ENGINEERING,
                }

                event = KnowledgeEvent(
                    type=EventType.CONTEXT if hasattr(EventType, 'CONTEXT') else EventType.FACT,
                    domain=domain_map.get(result.domain, Domain.OTHER),
                    title=f"Agente {agent.name}: {text[:50]}",
                    content={"agent": agent.agent_id, "input": text, "output": result.content},
                    summary=result.content[:200],
                    confidence=result.confidence,
                    source=agent.agent_id,
                    tags=["multi_agent", agent.agent_id, result.domain],
                )
                await self.kernel.knowledge.ingest([event])
                result.events_created = 1
            except Exception:
                pass

        return result

    def list_agents(self) -> list[dict]:
        return [
            {
                "id": a.agent_id,
                "name": a.name,
                "description": a.description,
                "domains": a.domains,
                "capabilities": [c.name for c in a.capabilities],
            }
            for a in self.agents.values()
        ]

    def status(self) -> dict:
        return {
            "total_agents": len(self.agents),
            "agents": self.list_agents(),
        }
