"""Test: Cognitive Workspace — unified main screen."""

import pytest
from intent_kernel.workspace import CognitiveWorkspace, ContextEngine, CommandItem
from intent_kernel.kernel import Kernel


@pytest.fixture
def ws():
    kernel = Kernel()
    return CognitiveWorkspace(kernel)


@pytest.fixture
def ws_no_kernel():
    return CognitiveWorkspace()


# ---------------------------------------------------------------------------
# Context Engine
# ---------------------------------------------------------------------------

def test_context_finance():
    ctx = ContextEngine()
    result = ctx.analyze("Quero investir 5000/mês")
    assert result["domain"] == "finance"
    assert result["action"] in ("query", "create", "simulate")


def test_context_engineering():
    ctx = ContextEngine()
    result = ctx.analyze("Criar uma API REST")
    assert result["domain"] == "engineering"


def test_context_knowledge():
    ctx = ContextEngine()
    result = ctx.analyze("Registrar uma decisão")
    assert result["domain"] == "knowledge"


def test_recommended_panels():
    ctx = ContextEngine()
    ctx.analyze("investir em ETFs")
    panels = ctx.get_recommended_panels()
    assert "atlas" in panels
    assert "chat" in panels


# ---------------------------------------------------------------------------
# Workspace panels
# ---------------------------------------------------------------------------

def test_workspace_panels(ws):
    state = ws.get_workspace_state()
    assert len(state["panels"]) >= 8
    assert any(p["id"] == "chat" for p in state["panels"])


def test_process_input(ws):
    result = ws.process_input("Quero investir")
    assert "context" in result
    assert "recommended_panels" in result
    assert "atlas" in result["recommended_panels"]


def test_process_input_adapts(ws):
    ws.process_input("Criar API para sistema")
    state = ws.get_workspace_state()
    # Engineering panel should be visible
    oem = next(p for p in state["panels"] if p["id"] == "oem_studio")
    assert oem["visible"]


# ---------------------------------------------------------------------------
# Universal Search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_universal_search_commands(ws_no_kernel):
    result = await ws_no_kernel.universal_search("backup")
    assert result["total"] >= 1
    assert any(c["label"] == "Gerar Backup" for c in result["commands"])


@pytest.mark.asyncio
async def test_universal_search_knowledge(ws):
    result = await ws.universal_search("test")
    assert "knowledge" in result


# ---------------------------------------------------------------------------
# Command Palette
# ---------------------------------------------------------------------------

def test_get_commands(ws):
    commands = ws.get_commands()
    assert len(commands) >= 10


def test_filter_commands(ws):
    commands = ws.get_commands("backup")
    assert any(c["label"] == "Gerar Backup" for c in commands)


def test_execute_command(ws):
    result = ws.execute_command("create_project")
    assert result["executed"] is True


def test_execute_unknown_command(ws):
    result = ws.execute_command("nonexistent")
    assert result["executed"] is False


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard(ws):
    dash = await ws.get_dashboard()
    assert "workspace" in dash
    assert "health" in dash


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_ws_name(ws):
    assert ws.name == "cognitive_workspace"
