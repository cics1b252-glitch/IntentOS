"""OEM Studio — Core App #3: Engenharia e Desenvolvimento.

Responsabilities:
- Projetos de engenharia
- CAD (Computer-Aided Design)
- Impressão 3D
- Documentação técnica
- Versionamento de projetos
- Gerenciamento de peças
- Integração entre documentos, modelos e decisões
- Engenharia automotiva / CarPlay

Uses Kernel services exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from intent_kernel.types import Domain, new_id, utcnow


# ---------------------------------------------------------------------------
# OEM Studio Types
# ---------------------------------------------------------------------------

class ProjectPhase(str, Enum):
    """Engineering project phases."""
    CONCEITO = "conceito"
    DESIGN = "design"
    PROTOTIPACAO = "prototipacao"
    TESTE = "teste"
    PRODUCAO = "producao"
    CONCLUIDO = "concluido"


class PartCategory(str, Enum):
    """Part categories."""
    MECANICA = "mecanica"
    ELETRONICA = "eletronica"
    ESTRUTURAL = "estrutural"
    CARPLAY = "carplay"
    SENSOR = "sensor"
    CASING = "casing"
    OUTRO = "outro"


class FileType(str, Enum):
    """CAD/file types."""
    STEP = "step"
    STL = "stl"
    OBJ = "obj"
    F3D = "f3d"       # Fusion 360
    SLDPRT = "sldprt"  # SolidWorks
    IGES = "iges"
    PDF = "pdf"
    IMAGE = "image"
    OTHER = "other"


class VersionStatus(str, Enum):
    """Version status."""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class EngineeringProject:
    """An engineering project."""
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    phase: ProjectPhase = ProjectPhase.CONCEITO
    domain: str = "engineering"
    tags: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)       # part IDs
    documents: list[str] = field(default_factory=list)    # doc IDs
    decisions: list[str] = field(default_factory=list)    # decision IDs
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    @property
    def part_count(self) -> int:
        return len(self.parts)


@dataclass
class Part:
    """An engineering part/component."""
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    category: PartCategory = PartCategory.OUTRO
    project_id: str = ""
    version: int = 1
    material: str = ""
    dimensions: dict = field(default_factory=dict)  # {"x": 100, "y": 50, "z": 20, "unit": "mm"}
    weight_grams: float = 0.0
    files: list[dict] = field(default_factory=list)  # [{"name": "part.step", "type": "step", "url": "..."}]
    specifications: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    def add_file(self, name: str, file_type: FileType, url: str = "") -> None:
        """Add a CAD file to the part."""
        self.files.append({
            "name": name,
            "type": file_type.value,
            "url": url,
            "added_at": utcnow().isoformat(),
        })
        self.version += 1
        self.updated_at = utcnow().isoformat()


@dataclass
class TechDocument:
    """Technical documentation."""
    id: str = field(default_factory=new_id)
    title: str = ""
    content: str = ""
    project_id: str = ""
    doc_type: str = "spec"  # spec, manual, datasheet, report
    version: int = 1
    status: VersionStatus = VersionStatus.DRAFT
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    def update_content(self, new_content: str) -> None:
        self.content = new_content
        self.version += 1
        self.updated_at = utcnow().isoformat()


@dataclass
class Version:
    """A version snapshot of a project or part."""
    id: str = field(default_factory=new_id)
    entity_type: str = ""  # "project" | "part" | "document"
    entity_id: str = ""
    version_number: int = 1
    description: str = ""
    changes: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)
    status: VersionStatus = VersionStatus.DRAFT
    created_at: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class PrintJob:
    """A 3D print job."""
    id: str = field(default_factory=new_id)
    part_id: str = ""
    part_name: str = ""
    material: str = "PLA"
    layer_height_mm: float = 0.2
    infill_pct: int = 20
    estimated_time_hours: float = 0.0
    estimated_grams: float = 0.0
    status: str = "pending"  # pending, printing, completed, failed
    notes: str = ""
    created_at: str = field(default_factory=lambda: utcnow().isoformat())


# ---------------------------------------------------------------------------
# OEM Studio Core App
# ---------------------------------------------------------------------------

class OEMStudio:
    """OEM Studio — Engenharia e Desenvolvimento.

    Core App #3 for Intent OS.
    Uses Kernel services exclusively.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.projects: dict[str, EngineeringProject] = {}
        self.parts: dict[str, Part] = {}
        self.documents: dict[str, TechDocument] = {}
        self.versions: dict[str, Version] = {}
        self.print_jobs: dict[str, PrintJob] = {}

    @property
    def name(self) -> str:
        return "oem_studio"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Engenharia e Desenvolvimento"

    # -------------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        description: str = "",
        domain: str = "engineering",
        tags: list[str] | None = None,
    ) -> EngineeringProject:
        project = EngineeringProject(
            name=name,
            description=description,
            domain=domain,
            tags=tags or [],
        )
        self.projects[project.id] = project
        return project

    def get_project(self, project_id: str) -> EngineeringProject | None:
        return self.projects.get(project_id)

    def update_phase(self, project_id: str, phase: ProjectPhase) -> EngineeringProject | None:
        project = self.projects.get(project_id)
        if not project:
            return None
        project.phase = phase
        project.updated_at = utcnow().isoformat()
        return project

    def list_projects(self, phase: ProjectPhase | None = None) -> list[EngineeringProject]:
        results = list(self.projects.values())
        if phase:
            results = [p for p in results if p.phase == phase]
        return results

    # -------------------------------------------------------------------
    # Parts
    # -------------------------------------------------------------------

    def create_part(
        self,
        name: str,
        project_id: str,
        category: PartCategory = PartCategory.OUTRO,
        description: str = "",
        material: str = "",
        dimensions: dict | None = None,
    ) -> Part:
        part = Part(
            name=name,
            description=description,
            category=category,
            project_id=project_id,
            material=material,
            dimensions=dimensions or {},
        )
        self.parts[part.id] = part

        if project_id in self.projects:
            self.projects[project_id].parts.append(part.id)

        return part

    def get_part(self, part_id: str) -> Part | None:
        return self.parts.get(part_id)

    def add_file_to_part(
        self,
        part_id: str,
        name: str,
        file_type: FileType,
        url: str = "",
    ) -> Part | None:
        part = self.parts.get(part_id)
        if not part:
            return None
        part.add_file(name, file_type, url)
        return part

    def list_parts(
        self,
        project_id: str | None = None,
        category: PartCategory | None = None,
    ) -> list[Part]:
        results = list(self.parts.values())
        if project_id:
            results = [p for p in results if p.project_id == project_id]
        if category:
            results = [p for p in results if p.category == category]
        return results

    # -------------------------------------------------------------------
    # Technical Documents
    # -------------------------------------------------------------------

    def create_document(
        self,
        title: str,
        content: str,
        project_id: str = "",
        doc_type: str = "spec",
        tags: list[str] | None = None,
    ) -> TechDocument:
        doc = TechDocument(
            title=title,
            content=content,
            project_id=project_id,
            doc_type=doc_type,
            tags=tags or [],
        )
        self.documents[doc.id] = doc

        if project_id in self.projects:
            self.projects[project_id].documents.append(doc.id)

        return doc

    def get_document(self, doc_id: str) -> TechDocument | None:
        return self.documents.get(doc_id)

    def update_document(self, doc_id: str, new_content: str) -> TechDocument | None:
        doc = self.documents.get(doc_id)
        if not doc:
            return None
        doc.update_content(new_content)
        return doc

    # -------------------------------------------------------------------
    # Versioning
    # -------------------------------------------------------------------

    def create_version(
        self,
        entity_type: str,
        entity_id: str,
        description: str = "",
        changes: list[str] | None = None,
    ) -> Version:
        """Create a version snapshot."""
        # Get current state
        snapshot = {}
        if entity_type == "project" and entity_id in self.projects:
            p = self.projects[entity_id]
            snapshot = {"name": p.name, "phase": p.phase.value, "parts": len(p.parts)}
        elif entity_type == "part" and entity_id in self.parts:
            pt = self.parts[entity_id]
            snapshot = {"name": pt.name, "version": pt.version, "files": len(pt.files)}
        elif entity_type == "document" and entity_id in self.documents:
            d = self.documents[entity_id]
            snapshot = {"title": d.title, "version": d.version}

        # Count existing versions for this entity
        existing = [v for v in self.versions.values()
                    if v.entity_type == entity_type and v.entity_id == entity_id]
        version_number = len(existing) + 1

        version = Version(
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=version_number,
            description=description,
            changes=changes or [],
            snapshot=snapshot,
        )
        self.versions[version.id] = version
        return version

    def get_version_history(self, entity_type: str, entity_id: str) -> list[Version]:
        return sorted(
            [v for v in self.versions.values()
             if v.entity_type == entity_type and v.entity_id == entity_id],
            key=lambda v: v.version_number,
        )

    # -------------------------------------------------------------------
    # 3D Print Jobs
    # -------------------------------------------------------------------

    def create_print_job(
        self,
        part_id: str,
        material: str = "PLA",
        layer_height_mm: float = 0.2,
        infill_pct: int = 20,
    ) -> PrintJob | None:
        part = self.parts.get(part_id)
        if not part:
            return None

        job = PrintJob(
            part_id=part_id,
            part_name=part.name,
            material=material,
            layer_height_mm=layer_height_mm,
            infill_pct=infill_pct,
        )
        self.print_jobs[job.id] = job
        return job

    def update_print_status(self, job_id: str, status: str) -> PrintJob | None:
        job = self.print_jobs.get(job_id)
        if not job:
            return None
        job.status = status
        return job

    def list_print_jobs(self, status: str | None = None) -> list[PrintJob]:
        results = list(self.print_jobs.values())
        if status:
            results = [j for j in results if j.status == status]
        return results

    # -------------------------------------------------------------------
    # Knowledge Core Integration (via Kernel)
    # -------------------------------------------------------------------

    async def sync_to_knowledge_core(self) -> dict:
        """Sync OEM Studio data to the Knowledge Core via Kernel."""
        if not self.kernel:
            return {"error": "Kernel not connected"}

        from intent_kernel.pkb.models import KnowledgeEvent
        from intent_kernel.types import EventType

        events = []

        # Sync project decisions
        for project in self.projects.values():
            for dec_id in project.decisions:
                if dec_id in self.decisions:
                    d = self.decisions[dec_id]
                    event = KnowledgeEvent(
                        type=EventType.DECISION,
                        domain=Domain.ENGINEERING,
                        title=f"Eng: {d.question[:60]}",
                        content={"question": d.question, "chosen": d.chosen},
                        summary=d.rationale[:200],
                        confidence=0.8,
                        source="oem_studio",
                        tags=["oem_studio", "engineering", "decision"],
                    )
                    events.append(event)

        if events:
            result = await self.kernel.knowledge.ingest(events)
            return {"synced": True, "events_created": result.approved + result.candidate}

        return {"synced": True, "events_created": 0}

    # -------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------

    def get_dashboard(self) -> dict:
        """Get a complete OEM Studio dashboard."""
        return {
            "projects": len(self.projects),
            "active_projects": sum(
                1 for p in self.projects.values()
                if p.phase not in (ProjectPhase.CONCLUIDO,)
            ),
            "parts": len(self.parts),
            "total_files": sum(len(p.files) for p in self.parts.values()),
            "documents": len(self.documents),
            "versions": len(self.versions),
            "print_jobs": len(self.print_jobs),
            "pending_prints": sum(1 for j in self.print_jobs.values() if j.status == "pending"),
            "phases": {
                phase.value: sum(1 for p in self.projects.values() if p.phase == phase)
                for phase in ProjectPhase
            },
        }
