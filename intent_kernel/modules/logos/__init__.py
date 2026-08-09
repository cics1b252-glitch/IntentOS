"""Logos — Core App #2: Gestão do Conhecimento.

Responsibilities:
- Gerenciamento de projetos
- RFCs
- Constitution (gestão, não validação — isso é do Kernel)
- Documentação
- Notas
- Decisões
- Pesquisas
- Organização do Knowledge Core
- Recuperação inteligente de contexto

Uses Kernel services exclusively — no parallel persistence/memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from intent_kernel.types import Domain, new_id, utcnow


# ---------------------------------------------------------------------------
# Logos Types
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    """Project status."""
    PLANEJAMENTO = "planejamento"
    EM_ANDAMENTO = "em_andamento"
    PAUSADO = "pausado"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"


class DocumentType(str, Enum):
    """Types of documents."""
    RFC = "rfc"
    SPEC = "spec"
    README = "readme"
    GUIDE = "guide"
    NOTE = "note"
    DECISION = "decision"
    MEETING = "meeting"
    RESEARCH = "research"


class DecisionStatus(str, Enum):
    """Decision status."""
    PENDENTE = "pendente"
    TOMADA = "tomada"
    REVISADA = "revisada"
    DESATUALIZADA = "desatualizada"


class NoteCategory(str, Enum):
    """Note categories."""
    IDEA = "idea"
    OBSERVATION = "observation"
    LEARNING = "learning"
    CORRECTION = "correction"
    INSIGHT = "insight"
    TODO = "todo"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """A knowledge project."""
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    status: ProjectStatus = ProjectStatus.PLANEJAMENTO
    domain: str = "general"
    tags: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)  # document IDs
    decisions: list[str] = field(default_factory=list)   # decision IDs
    notes: list[str] = field(default_factory=list)       # note IDs
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def decision_count(self) -> int:
        return len(self.decisions)

    @property
    def note_count(self) -> int:
        return len(self.notes)


@dataclass
class Document:
    """A knowledge document."""
    id: str = field(default_factory=new_id)
    title: str = ""
    content: str = ""
    doc_type: DocumentType = DocumentType.NOTE
    project_id: str = ""
    version: int = 1
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    def update_content(self, new_content: str) -> None:
        """Update document content with version bump."""
        self.content = new_content
        self.version += 1
        self.updated_at = utcnow().isoformat()


@dataclass
class Decision:
    """A recorded decision with rationale."""
    id: str = field(default_factory=new_id)
    question: str = ""
    chosen: str = ""
    alternatives: list[str] = field(default_factory=list)
    rationale: str = ""
    status: DecisionStatus = DecisionStatus.TOMADA
    project_id: str = ""
    confidence: float = 0.8
    reversible: bool = True
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    reviewed_at: str = ""

    def review(self, new_chosen: str, new_rationale: str) -> None:
        """Review and update a decision."""
        self.chosen = new_chosen
        self.rationale = new_rationale
        self.status = DecisionStatus.REVISADA
        self.reviewed_at = utcnow().isoformat()


@dataclass
class Note:
    """A knowledge note."""
    id: str = field(default_factory=new_id)
    title: str = ""
    content: str = ""
    category: NoteCategory = NoteCategory.OBSERVATION
    project_id: str = ""
    tags: list[str] = field(default_factory=list)
    related_docs: list[str] = field(default_factory=list)
    related_decisions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class Research:
    """A research session with sources and findings."""
    id: str = field(default_factory=new_id)
    question: str = ""
    sources: list[dict] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.5
    project_id: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())


# ---------------------------------------------------------------------------
# Logos Core App
# ---------------------------------------------------------------------------

class Logos:
    """Logos — Gestão do Conhecimento.

    Core App #2 for Intent OS.
    Uses Kernel services exclusively.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.projects: dict[str, Project] = {}
        self.documents: dict[str, Document] = {}
        self.decisions: dict[str, Decision] = {}
        self.notes: dict[str, Note] = {}
        self.researches: dict[str, Research] = {}

    @property
    def name(self) -> str:
        return "logos"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Gestão do Conhecimento"

    # -------------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        description: str = "",
        domain: str = "general",
        tags: list[str] | None = None,
    ) -> Project:
        """Create a new knowledge project."""
        project = Project(
            name=name,
            description=description,
            domain=domain,
            tags=tags or [],
        )
        self.projects[project.id] = project
        return project

    def get_project(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def update_project_status(self, project_id: str, status: ProjectStatus) -> Project | None:
        project = self.projects.get(project_id)
        if not project:
            return None
        project.status = status
        project.updated_at = utcnow().isoformat()
        return project

    def list_projects(
        self,
        status: ProjectStatus | None = None,
        domain: str | None = None,
    ) -> list[Project]:
        """List projects with optional filters."""
        results = list(self.projects.values())
        if status:
            results = [p for p in results if p.status == status]
        if domain:
            results = [p for p in results if p.domain == domain]
        return sorted(results, key=lambda p: p.updated_at, reverse=True)

    # -------------------------------------------------------------------
    # Documents
    # -------------------------------------------------------------------

    def create_document(
        self,
        title: str,
        content: str,
        doc_type: DocumentType = DocumentType.NOTE,
        project_id: str = "",
        tags: list[str] | None = None,
    ) -> Document:
        """Create a new document."""
        doc = Document(
            title=title,
            content=content,
            doc_type=doc_type,
            project_id=project_id,
            tags=tags or [],
        )
        self.documents[doc.id] = doc

        # Link to project
        if project_id and project_id in self.projects:
            self.projects[project_id].documents.append(doc.id)

        return doc

    def get_document(self, doc_id: str) -> Document | None:
        return self.documents.get(doc_id)

    def update_document(self, doc_id: str, new_content: str) -> Document | None:
        doc = self.documents.get(doc_id)
        if not doc:
            return None
        doc.update_content(new_content)
        return doc

    def search_documents(self, query: str) -> list[Document]:
        """Full-text search across documents."""
        q = query.lower()
        return [
            doc for doc in self.documents.values()
            if q in doc.title.lower() or q in doc.content.lower()
        ]

    def list_documents(
        self,
        project_id: str | None = None,
        doc_type: DocumentType | None = None,
    ) -> list[Document]:
        results = list(self.documents.values())
        if project_id:
            results = [d for d in results if d.project_id == project_id]
        if doc_type:
            results = [d for d in results if d.doc_type == doc_type]
        return results

    # -------------------------------------------------------------------
    # Decisions
    # -------------------------------------------------------------------

    def record_decision(
        self,
        question: str,
        chosen: str,
        alternatives: list[str],
        rationale: str,
        project_id: str = "",
        confidence: float = 0.8,
        reversible: bool = True,
        tags: list[str] | None = None,
    ) -> Decision:
        """Record a decision."""
        decision = Decision(
            question=question,
            chosen=chosen,
            alternatives=alternatives,
            rationale=rationale,
            project_id=project_id,
            confidence=confidence,
            reversible=reversible,
            tags=tags or [],
        )
        self.decisions[decision.id] = decision

        # Link to project
        if project_id and project_id in self.projects:
            self.projects[project_id].decisions.append(decision.id)

        return decision

    def get_decision(self, decision_id: str) -> Decision | None:
        return self.decisions.get(decision_id)

    def review_decision(
        self,
        decision_id: str,
        new_chosen: str,
        new_rationale: str,
    ) -> Decision | None:
        decision = self.decisions.get(decision_id)
        if not decision:
            return None
        decision.review(new_chosen, new_rationale)
        return decision

    def list_decisions(
        self,
        project_id: str | None = None,
        status: DecisionStatus | None = None,
    ) -> list[Decision]:
        results = list(self.decisions.values())
        if project_id:
            results = [d for d in results if d.project_id == project_id]
        if status:
            results = [d for d in results if d.status == status]
        return results

    # -------------------------------------------------------------------
    # Notes
    # -------------------------------------------------------------------

    def create_note(
        self,
        title: str,
        content: str,
        category: NoteCategory = NoteCategory.OBSERVATION,
        project_id: str = "",
        tags: list[str] | None = None,
    ) -> Note:
        """Create a note."""
        note = Note(
            title=title,
            content=content,
            category=category,
            project_id=project_id,
            tags=tags or [],
        )
        self.notes[note.id] = note

        if project_id and project_id in self.projects:
            self.projects[project_id].notes.append(note.id)

        return note

    def get_note(self, note_id: str) -> Note | None:
        return self.notes.get(note_id)

    def search_notes(self, query: str) -> list[Note]:
        q = query.lower()
        return [
            note for note in self.notes.values()
            if q in note.title.lower() or q in note.content.lower()
        ]

    def list_notes(
        self,
        project_id: str | None = None,
        category: NoteCategory | None = None,
    ) -> list[Note]:
        results = list(self.notes.values())
        if project_id:
            results = [n for n in results if n.project_id == project_id]
        if category:
            results = [n for n in results if n.category == category]
        return results

    # -------------------------------------------------------------------
    # Research
    # -------------------------------------------------------------------

    def create_research(
        self,
        question: str,
        project_id: str = "",
        tags: list[str] | None = None,
    ) -> Research:
        """Start a research session."""
        research = Research(
            question=question,
            project_id=project_id,
            tags=tags or [],
        )
        self.researches[research.id] = research
        return research

    def add_finding(self, research_id: str, finding: str) -> Research | None:
        research = self.researches.get(research_id)
        if not research:
            return None
        research.findings.append(finding)
        return research

    def add_source(self, research_id: str, source: dict) -> Research | None:
        research = self.researches.get(research_id)
        if not research:
            return None
        research.sources.append(source)
        return research

    def conclude_research(self, research_id: str, conclusion: str, confidence: float) -> Research | None:
        research = self.researches.get(research_id)
        if not research:
            return None
        research.conclusion = conclusion
        research.confidence = confidence
        return research

    # -------------------------------------------------------------------
    # Knowledge Core Integration (via Kernel)
    # -------------------------------------------------------------------

    async def sync_to_knowledge_core(self) -> dict:
        """Sync all Logos data to the Knowledge Core via Kernel.

        This is the integration point — Logos uses Kernel services exclusively.
        """
        if not self.kernel:
            return {"error": "Kernel not connected"}

        from intent_kernel.pkb.models import KnowledgeEvent
        from intent_kernel.types import EventType

        events = []

        # Sync decisions
        for decision in self.decisions.values():
            event = KnowledgeEvent(
                type=EventType.DECISION,
                domain=Domain.PLANNING,
                title=f"Decisão: {decision.question[:60]}",
                content={
                    "question": decision.question,
                    "chosen": decision.chosen,
                    "alternatives": decision.alternatives,
                    "rationale": decision.rationale,
                },
                summary=decision.rationale[:200],
                confidence=decision.confidence,
                source="logos",
                tags=["logos", "decision"] + decision.tags,
            )
            events.append(event)

        # Sync research conclusions
        for research in self.researches.values():
            if research.conclusion:
                event = KnowledgeEvent(
                    type=EventType.INSIGHT,
                    domain=Domain.RESEARCH,
                    title=f"Pesquisa: {research.question[:60]}",
                    content={
                        "question": research.question,
                        "conclusion": research.conclusion,
                        "sources_count": len(research.sources),
                        "findings_count": len(research.findings),
                    },
                    summary=research.conclusion[:200],
                    confidence=research.confidence,
                    source="logos",
                    tags=["logos", "research"] + research.tags,
                )
                events.append(event)

        if events:
            result = await self.kernel.knowledge.ingest(events)
            return {
                "synced": True,
                "events_created": result.approved + result.candidate,
            }

        return {"synced": True, "events_created": 0}

    # -------------------------------------------------------------------
    # Context Recovery
    # -------------------------------------------------------------------

    def recover_context(self, query: str) -> dict:
        """Recover context related to a query.

        Searches across projects, documents, decisions, and notes.
        """
        matching_docs = self.search_documents(query)
        matching_notes = self.search_notes(query)
        matching_decisions = [
            d for d in self.decisions.values()
            if query.lower() in d.question.lower() or query.lower() in d.chosen.lower()
        ]

        return {
            "query": query,
            "documents": [
                {"id": d.id, "title": d.title, "type": d.doc_type.value}
                for d in matching_docs[:5]
            ],
            "notes": [
                {"id": n.id, "title": n.title, "category": n.category.value}
                for n in matching_notes[:5]
            ],
            "decisions": [
                {"id": d.id, "question": d.question, "chosen": d.chosen, "status": d.status.value}
                for d in matching_decisions[:5]
            ],
            "total_results": len(matching_docs) + len(matching_notes) + len(matching_decisions),
        }

    # -------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------

    def get_dashboard(self) -> dict:
        """Get a complete Logos dashboard."""
        return {
            "projects": len(self.projects),
            "active_projects": sum(
                1 for p in self.projects.values()
                if p.status in (ProjectStatus.PLANEJAMENTO, ProjectStatus.EM_ANDAMENTO)
            ),
            "documents": len(self.documents),
            "decisions": len(self.decisions),
            "pending_decisions": sum(
                1 for d in self.decisions.values()
                if d.status == DecisionStatus.PENDENTE
            ),
            "notes": len(self.notes),
            "researches": len(self.researches),
            "completed_researches": sum(
                1 for r in self.researches.values()
                if r.conclusion
            ),
        }
