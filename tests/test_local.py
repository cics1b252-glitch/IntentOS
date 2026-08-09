"""Test: Intent OS Local Root — persistent text-based memory."""

import pytest
import tempfile
from pathlib import Path
from intent_kernel.local import LocalRoot, MemoryEntry


@pytest.fixture
def local():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield LocalRoot(tmpdir)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_creates_directories(local):
    assert (local.root / "projects").exists()
    assert (local.root / "knowledge").exists()
    assert (local.root / "backups").exists()


def test_creates_memory_files(local):
    assert (local.root / "memory.md").exists()
    assert (local.root / "decisions.md").exists()
    assert (local.root / "preferences.md").exists()
    assert (local.root / "context.md").exists()


# ---------------------------------------------------------------------------
# Memory (expandable text)
# ---------------------------------------------------------------------------

def test_append_and_read_memory(local):
    local.append_memory(MemoryEntry(
        category="decision",
        content="Investir em ETFs",
        source="finance_agent",
        tags=["finance", "investment"],
    ))
    memory = local.read_memory()
    assert "Investir em ETFs" in memory


def test_search_memory(local):
    local.append_memory(MemoryEntry(category="decision", content="Usar FastAPI"))
    local.append_memory(MemoryEntry(category="preference", content="Gostar de Python"))
    results = local.search_memory("python")
    assert len(results) >= 1


def test_memory_stats(local):
    local.append_memory(MemoryEntry(category="test", content="entry 1"))
    stats = local.get_memory_stats()
    assert stats["total_entries"] >= 1


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def test_record_decision(local):
    local.record_decision(
        question="Qual framework?",
        chosen="FastAPI",
        alternatives=["Django", "Flask"],
        rationale="Async nativo",
    )
    decisions = local.read_decisions()
    assert "FastAPI" in decisions
    assert "Qual framework?" in decisions


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def test_save_and_get_preference(local):
    local.save_preference("theme", "dark")
    assert local.get_preference("theme") == "dark"


def test_read_preferences(local):
    local.save_preference("lang", "pt-BR")
    prefs = local.read_preferences()
    assert "pt-BR" in prefs


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

def test_record_pattern(local):
    local.record_pattern("Usuário prefere respostas curtas", 0.9)
    patterns = local.read_patterns()
    assert "curtas" in patterns


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

def test_save_and_read_context(local):
    local.save_context("current_project", "Intent OS")
    ctx = local.read_context()
    assert "Intent OS" in ctx


def test_context_overwrite(local):
    local.save_context("mood", "focused")
    local.save_context("mood", "relaxed")
    ctx = local.read_context()
    assert "relaxed" in ctx


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

def test_save_and_read_knowledge(local):
    local.save_knowledge("fastapi-guide", "FastAPI é incrível", "tech")
    content = local.read_knowledge("fastapi-guide")
    assert content is not None
    assert "FastAPI" in content


def test_list_knowledge(local):
    local.save_knowledge("doc1", "content1")
    local.save_knowledge("doc2", "content2")
    items = local.list_knowledge()
    assert len(items) == 2


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_save_and_load_config(local):
    local.save_config({"theme": "dark", "version": "1.0"})
    config = local.load_config()
    assert config["theme"] == "dark"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_save_and_get_identity(local):
    local.save_identity({"id": "test-123", "hostname": "my-pc"})
    identity = local.get_identity()
    assert identity["id"] == "test-123"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status(local):
    status = local.status()
    assert "root" in status
    assert "total_files" in status
    assert status["total_files"] > 0
