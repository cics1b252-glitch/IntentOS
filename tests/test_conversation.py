"""Test: Conversation Orchestrator — natural conversation layer."""

import pytest
from intent_kernel.conversation import ConversationOrchestrator, ConversationContext


@pytest.fixture
def orch():
    return ConversationOrchestrator()


# ---------------------------------------------------------------------------
# Basic conversation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_greeting(orch):
    response = await orch.process_message("Olá")
    assert response
    assert "pipeline" not in response.lower()
    assert "curator" not in response.lower()
    assert "score" not in response.lower()


@pytest.mark.asyncio
async def test_finance_asks_questions(orch):
    response = await orch.process_message("Quero investir em FIIs")
    assert "ajudar" in response.lower() or "investir" in response.lower()
    # Should ask for more info, not dump technical details
    assert "curator" not in response.lower()
    assert "pipeline" not in response.lower()


@pytest.mark.asyncio
async def test_no_technical_jargon(orch):
    """User should never see technical messages."""
    responses = []
    for msg in ["quero investir", "5000", "conservador"]:
        resp = await orch.process_message(msg)
        responses.append(resp)

    full_response = " ".join(responses).lower()
    assert "pipeline" not in full_response
    assert "curator" not in full_response
    assert "score" not in full_response
    assert "knowledge missing" not in full_response
    assert "guardian" not in full_response


# ---------------------------------------------------------------------------
# Context collection
# ---------------------------------------------------------------------------

def test_collect_info(orch):
    orch.collect_info("amount", "R$ 5.000")
    ctx = orch.get_context()
    assert ctx.collected_info["amount"] == "R$ 5.000"


def test_context_persists(orch):
    orch.collect_info("goal", "renda passiva")
    ctx = orch.get_context()
    assert ctx.collected_info["goal"] == "renda passiva"


# ---------------------------------------------------------------------------
# Intent analysis
# ---------------------------------------------------------------------------

def test_intent_finance(orch):
    intent = orch._analyze_intent("Quero investir em ETFs")
    assert intent["domain"] == "finance"


def test_intent_knowledge(orch):
    intent = orch._analyze_intent("Criar um projeto")
    assert intent["domain"] == "knowledge"


def test_intent_engineering(orch):
    intent = orch._analyze_intent("Criar uma API")
    assert intent["domain"] == "engineering"


# ---------------------------------------------------------------------------
# Conversation context
# ---------------------------------------------------------------------------

def test_conversation_turns(orch):
    ctx = orch.get_context("session1")
    assert ctx.turns == []


def test_multiple_sessions(orch):
    orch.get_context("s1")
    orch.get_context("s2")
    assert len(orch.contexts) == 2
