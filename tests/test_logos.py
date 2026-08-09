"""Test: Logos — Core App #2: Gestão do Conhecimento."""

import pytest
from intent_kernel.modules.logos import (
    Logos,
    Project,
    Document,
    Decision,
    Note,
    Research,
    ProjectStatus,
    DocumentType,
    DecisionStatus,
    NoteCategory,
)


@pytest.fixture
def logos():
    return Logos()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def test_create_project(logos):
    p = logos.create_project("Intent OS", "Cognitive Operating System", domain="engineering")
    assert p.name == "Intent OS"
    assert p.domain == "engineering"
    assert p.id in logos.projects


def test_update_project_status(logos):
    p = logos.create_project("Test")
    logos.update_project_status(p.id, ProjectStatus.EM_ANDAMENTO)
    assert p.status == ProjectStatus.EM_ANDAMENTO


def test_list_projects(logos):
    logos.create_project("A", domain="finance")
    logos.create_project("B", domain="engineering")
    assert len(logos.list_projects(domain="finance")) == 1


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_create_document(logos):
    p = logos.create_project("Test")
    doc = logos.create_document("RFC-0001", "Content", DocumentType.RFC, project_id=p.id)
    assert doc.title == "RFC-0001"
    assert doc.doc_type == DocumentType.RFC
    assert doc.id in p.documents


def test_update_document(logos):
    doc = logos.create_document("Doc", "v1")
    logos.update_document(doc.id, "v2")
    assert doc.content == "v2"
    assert doc.version == 2


def test_search_documents(logos):
    logos.create_document("Finance Report", "Investment analysis")
    logos.create_document("Tech Spec", "Architecture design")
    results = logos.search_documents("investment")
    assert len(results) == 1


def test_list_documents_by_project(logos):
    p = logos.create_project("Test")
    logos.create_document("Doc1", "c1", project_id=p.id)
    logos.create_document("Doc2", "c2")
    assert len(logos.list_documents(project_id=p.id)) == 1


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def test_record_decision(logos):
    d = logos.record_decision(
        question="Which framework?",
        chosen="FastAPI",
        alternatives=["Django", "Flask"],
        rationale="Async support",
    )
    assert d.question == "Which framework?"
    assert d.chosen == "FastAPI"
    assert d.status == DecisionStatus.TOMADA


def test_review_decision(logos):
    d = logos.record_decision("Q1", "A1", ["A2"], "R1")
    logos.review_decision(d.id, "A2", "R2 — better fit")
    assert d.chosen == "A2"
    assert d.status == DecisionStatus.REVISADA


def test_list_decisions_by_status(logos):
    logos.record_decision("Q1", "A1", [], "R1")
    logos.record_decision("Q2", "A2", [], "R2")
    assert len(logos.list_decisions(status=DecisionStatus.TOMADA)) == 2


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def test_create_note(logos):
    n = logos.create_note("Idea", "Build a knowledge OS", NoteCategory.IDEA)
    assert n.title == "Idea"
    assert n.category == NoteCategory.IDEA


def test_search_notes(logos):
    logos.create_note("Python tip", "Use dataclasses for clean code")
    logos.create_note("Meeting", "Discussed architecture")
    results = logos.search_notes("dataclass")
    assert len(results) == 1


def test_list_notes_by_category(logos):
    logos.create_note("N1", "c1", NoteCategory.IDEA)
    logos.create_note("N2", "c2", NoteCategory.OBSERVATION)
    assert len(logos.list_notes(category=NoteCategory.IDEA)) == 1


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

def test_create_research(logos):
    r = logos.create_research("Best DB for knowledge base?")
    assert r.question == "Best DB for knowledge base?"


def test_add_finding(logos):
    r = logos.create_research("Q?")
    logos.add_finding(r.id, "PostgreSQL supports JSONB")
    logos.add_finding(r.id, "SQLite is simpler")
    assert len(r.findings) == 2


def test_conclude_research(logos):
    r = logos.create_research("Q?")
    logos.add_finding(r.id, "Finding 1")
    logos.conclude_research(r.id, "Use PostgreSQL", 0.85)
    assert r.conclusion == "Use PostgreSQL"
    assert r.confidence == 0.85


# ---------------------------------------------------------------------------
# Context Recovery
# ---------------------------------------------------------------------------

def test_recover_context(logos):
    p = logos.create_project("Finance")
    logos.create_document("ETF Guide", "How to invest in ETFs", project_id=p.id)
    logos.create_note("My strategy", "Conservative ETF allocation", project_id=p.id)
    logos.record_decision("Which ETF?", "IVVB11", [], "S&P 500 exposure", project_id=p.id)

    ctx = logos.recover_context("ETF")
    assert ctx["total_results"] >= 2


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard(logos):
    logos.create_project("P1")
    logos.create_document("D1", "c1")
    logos.record_decision("Q1", "A1", [], "R1")
    logos.create_note("N1", "c1")
    logos.create_research("R1?")

    dash = logos.get_dashboard()
    assert dash["projects"] == 1
    assert dash["documents"] == 1
    assert dash["decisions"] == 1
    assert dash["notes"] == 1
    assert dash["researches"] == 1


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_logos_name(logos):
    assert logos.name == "logos"


def test_logos_version(logos):
    assert logos.version == "0.1.0"
