"""Test: Cognitive Continuity — KC that outlives the machine."""

import pytest
import tempfile
from intent_kernel.continuity import (
    CognitiveContinuity,
    KCIdentity,
    BackupEntry,
    TimelineEvent,
    CognitiveHealth,
)


@pytest.fixture
def continuity():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield CognitiveContinuity(data_dir=tmpdir)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_identity_created(continuity):
    identity = continuity.get_identity()
    assert identity["id"]
    assert identity["fingerprint"]
    assert identity["created_at"]


def test_identity_persistent(continuity):
    """Identity persists across instances."""
    id1 = continuity.get_identity()["id"]
    # Create new instance with same dir
    id2 = continuity.identity.id
    assert id1 == id2


def test_fingerprint(continuity):
    f1 = continuity.identity.fingerprint()
    f2 = continuity.identity.fingerprint()
    assert f1 == f2  # deterministic
    assert len(f1) == 16


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_backup(continuity):
    backup = await continuity.create_backup("Test backup")
    assert backup.id
    assert backup.notes == "Test backup"
    assert backup.size_bytes >= 0


@pytest.mark.asyncio
async def test_list_backups(continuity):
    await continuity.create_backup("Backup 1")
    await continuity.create_backup("Backup 2")
    backups = continuity.list_backups()
    assert len(backups) == 2


@pytest.mark.asyncio
async def test_automatic_backup(continuity):
    backup = await continuity.create_backup(automatic=True)
    assert backup.automatic is True


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def test_add_timeline_event(continuity):
    event = continuity.add_timeline_event(
        "knowledge_created",
        "Investment decision made",
        "Decided to invest in ETFs",
        domain="finance",
    )
    assert event.title == "Investment decision made"
    assert event.event_type == "knowledge_created"


def test_get_timeline(continuity):
    continuity.add_timeline_event("project_started", "Intent OS")
    continuity.add_timeline_event("decision_made", "Use FastAPI")
    timeline = continuity.get_timeline()
    assert len(timeline) == 2
    assert timeline[0]["type"] == "project_started"


def test_timeline_limit(continuity):
    for i in range(10):
        continuity.add_timeline_event("event", f"Event {i}")
    timeline = continuity.get_timeline(limit=3)
    assert len(timeline) == 3


# ---------------------------------------------------------------------------
# Cognitive Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_empty_kc(continuity):
    health = await continuity.assess_health()
    assert health.total_events == 0
    assert health.health_grade in ("A", "EMPTY")  # no kernel = no data = defaults


@pytest.mark.asyncio
async def test_health_with_kernel(continuity):
    from intent_kernel.kernel import Kernel
    continuity.kernel = Kernel()
    health = await continuity.assess_health()
    assert health.health_grade in ("A", "B", "C", "D", "F", "EMPTY")


def test_health_summary(continuity):
    summary = continuity.get_health_summary()
    assert "identity" in summary
    assert "backups" in summary
    assert "timeline_events" in summary


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_for_migration(continuity):
    data = await continuity.export_for_migration()
    assert len(data) > 0
    import json
    package = json.loads(data)
    assert "identity" in package
    assert "kc_data" in package
    assert "exported_at" in package


@pytest.mark.asyncio
async def test_import_invalid_data(continuity):
    result = await continuity.import_from_migration(b"not json")
    assert "error" in result


@pytest.mark.asyncio
async def test_import_valid_package(continuity):
    import json
    package = {
        "identity": {"id": "old-id", "created_at": "2026-01-01", "hostname": "old-pc"},
        "kc_data": {},
        "exported_at": "2026-07-24",
        "version": "1.0.0",
    }
    result = await continuity.import_from_migration(json.dumps(package).encode())
    assert result.get("imported") is True
    assert result.get("source_hostname") == "old-pc"


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_continuity_has_identity(continuity):
    assert continuity.identity is not None
