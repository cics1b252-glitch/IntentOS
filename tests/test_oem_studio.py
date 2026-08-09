"""Test: OEM Studio — Core App #3: Engenharia e Desenvolvimento."""

import pytest
from intent_kernel.modules.oem_studio import (
    OEMStudio,
    EngineeringProject,
    Part,
    TechDocument,
    Version,
    PrintJob,
    ProjectPhase,
    PartCategory,
    FileType,
    VersionStatus,
)


@pytest.fixture
def oem():
    return OEMStudio()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def test_create_project(oem):
    p = oem.create_project("CarPlay Module", "OEM integration for vehicle")
    assert p.name == "CarPlay Module"
    assert p.phase == ProjectPhase.CONCEITO


def test_update_phase(oem):
    p = oem.create_project("Test")
    oem.update_phase(p.id, ProjectPhase.DESIGN)
    assert p.phase == ProjectPhase.DESIGN


def test_list_projects_by_phase(oem):
    oem.create_project("P1")
    oem.create_project("P2")
    oem.update_phase(list(oem.projects.values())[0].id, ProjectPhase.DESIGN)
    assert len(oem.list_projects(phase=ProjectPhase.DESIGN)) == 1


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

def test_create_part(oem):
    p = oem.create_project("Test")
    pt = oem.create_part("Mounting Bracket", p.id, PartCategory.MECANICA, material="Aluminum")
    assert pt.name == "Mounting Bracket"
    assert pt.material == "Aluminum"
    assert pt.id in p.parts


def test_add_file_to_part(oem):
    pt = oem.create_part("Part", "proj-1")
    oem.add_file_to_part(pt.id, "bracket.step", FileType.STEP)
    assert len(pt.files) == 1
    assert pt.files[0]["type"] == "step"
    assert pt.version == 2  # incremented by add_file


def test_list_parts_by_category(oem):
    oem.create_part("P1", "proj-1", PartCategory.MECANICA)
    oem.create_part("P2", "proj-1", PartCategory.ELETRONICA)
    assert len(oem.list_parts(category=PartCategory.MECANICA)) == 1


# ---------------------------------------------------------------------------
# Technical Documents
# ---------------------------------------------------------------------------

def test_create_document(oem):
    p = oem.create_project("Test")
    doc = oem.create_document("Assembly Manual", "Step by step", project_id=p.id, doc_type="manual")
    assert doc.title == "Assembly Manual"
    assert doc.doc_type == "manual"
    assert doc.id in p.documents


def test_update_document(oem):
    doc = oem.create_document("Doc", "v1")
    oem.update_document(doc.id, "v2")
    assert doc.content == "v2"
    assert doc.version == 2


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def test_create_version(oem):
    p = oem.create_project("Test")
    v = oem.create_version("project", p.id, "Initial design", ["Created project"])
    assert v.version_number == 1
    assert v.entity_type == "project"


def test_version_history(oem):
    p = oem.create_project("Test")
    oem.create_version("project", p.id, "v1")
    oem.create_version("project", p.id, "v2", ["Added parts"])
    history = oem.get_version_history("project", p.id)
    assert len(history) == 2
    assert history[0].version_number == 1
    assert history[1].version_number == 2


# ---------------------------------------------------------------------------
# 3D Print Jobs
# ---------------------------------------------------------------------------

def test_create_print_job(oem):
    pt = oem.create_part("Bracket", "proj-1")
    job = oem.create_print_job(pt.id, material="PETG", infill_pct=30)
    assert job is not None
    assert job.material == "PETG"
    assert job.infill_pct == 30


def test_create_print_job_invalid_part(oem):
    job = oem.create_print_job("invalid-part")
    assert job is None


def test_update_print_status(oem):
    pt = oem.create_part("Part", "proj-1")
    job = oem.create_print_job(pt.id)
    oem.update_print_status(job.id, "printing")
    assert job.status == "printing"


def test_list_print_jobs(oem):
    pt = oem.create_part("Part", "proj-1")
    oem.create_print_job(pt.id)
    oem.create_print_job(pt.id)
    assert len(oem.list_print_jobs()) == 2


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard(oem):
    p = oem.create_project("Test")
    oem.create_part("Part1", p.id)
    oem.create_part("Part2", p.id)
    oem.create_document("Doc1", "c1", project_id=p.id)

    dash = oem.get_dashboard()
    assert dash["projects"] == 1
    assert dash["parts"] == 2
    assert dash["documents"] == 1


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_oem_name(oem):
    assert oem.name == "oem_studio"


def test_oem_version(oem):
    assert oem.version == "0.1.0"


# ---------------------------------------------------------------------------
# Part dimensions
# ---------------------------------------------------------------------------

def test_part_dimensions():
    pt = Part(name="Test", dimensions={"x": 100, "y": 50, "z": 20, "unit": "mm"})
    assert pt.dimensions["x"] == 100
    assert pt.dimensions["unit"] == "mm"
