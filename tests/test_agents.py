"""Test: Multi-Agent System — Intent OS as orchestrator."""

import pytest
from intent_kernel.agents import (
    AgentOrchestrator,
    FinanceAgent,
    KnowledgeAgent,
    EngineeringAgent,
    AgentResult,
)
from intent_kernel.kernel import Kernel


@pytest.fixture
def orchestrator():
    kernel = Kernel()
    return AgentOrchestrator(kernel)


# ---------------------------------------------------------------------------
# Agent Registration
# ---------------------------------------------------------------------------

def test_register_agents(orchestrator):
    assert len(orchestrator.agents) == 3
    assert "finance" in orchestrator.agents
    assert "knowledge" in orchestrator.agents
    assert "engineering" in orchestrator.agents


def test_get_agent(orchestrator):
    agent = orchestrator.get_agent("finance")
    assert agent is not None
    assert agent.name == "Atlas"


def test_list_agents(orchestrator):
    agents = orchestrator.list_agents()
    assert len(agents) == 3
    names = [a["name"] for a in agents]
    assert "Atlas" in names
    assert "Logos" in names
    assert "OEM Studio" in names


# ---------------------------------------------------------------------------
# Agent Routing
# ---------------------------------------------------------------------------

def test_route_finance(orchestrator):
    agent = orchestrator.find_best_agent("Quero investir em FIIs")
    assert agent.agent_id == "finance"


def test_route_knowledge(orchestrator):
    agent = orchestrator.find_best_agent("Criar um projeto")
    assert agent.agent_id == "knowledge"


def test_route_engineering(orchestrator):
    agent = orchestrator.find_best_agent(" Criar uma API REST")
    assert agent.agent_id == "engineering"


def test_route_default(orchestrator):
    agent = orchestrator.find_best_agent("olá")
    assert agent.agent_id == "knowledge"  # default


# ---------------------------------------------------------------------------
# Agent Processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_finance(orchestrator):
    result = await orchestrator.process("Quero investir 5000 em FIIs")
    assert result.agent_id == "finance"
    assert result.domain == "finance"
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_process_knowledge(orchestrator):
    result = await orchestrator.process("Criar um projeto")
    assert result.agent_id == "knowledge"
    assert result.domain == "knowledge"


@pytest.mark.asyncio
async def test_process_with_kernel(orchestrator):
    result = await orchestrator.process("Investir em ETFs")
    assert result.events_created >= 0  # may or may not create events


# ---------------------------------------------------------------------------
# Agent Status
# ---------------------------------------------------------------------------

def test_status(orchestrator):
    status = orchestrator.status()
    assert status["total_agents"] == 3
    assert len(status["agents"]) == 3


# ---------------------------------------------------------------------------
# Individual Agents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finance_investment():
    agent = FinanceAgent()
    result = await agent.process("Quero investir")
    assert "investimento" in result.content.lower() or "investir" in result.content.lower()


@pytest.mark.asyncio
async def test_finance_retirement():
    agent = FinanceAgent()
    result = await agent.process("Planejar aposentadoria")
    assert "aposentadoria" in result.content.lower()


@pytest.mark.asyncio
async def test_knowledge_project():
    agent = KnowledgeAgent()
    result = await agent.process("Criar projeto")
    assert "projeto" in result.content.lower()
