"""Test: Intent OS Monitor 2.0 — The Nervous System."""

import pytest
from intent_kernel.monitor.v2 import IntentOSMonitorV2
from intent_kernel.kernel import Kernel


@pytest.fixture
def monitor():
    kernel = Kernel()
    return IntentOSMonitorV2(kernel)


@pytest.fixture
def monitor_no_kernel():
    return IntentOSMonitorV2()


# ---------------------------------------------------------------------------
# 1. Architecture
# ---------------------------------------------------------------------------

def test_architecture(monitor):
    arch = monitor.get_architecture()
    assert arch["total"] >= 10
    ids = [c["id"] for c in arch["components"]]
    assert "kernel" in ids
    assert "constitution" in ids
    assert "guardians" in ids
    assert "pipeline" in ids
    assert "knowledge_core" in ids


def test_architecture_offline(monitor_no_kernel):
    arch = monitor_no_kernel.get_architecture()
    kernel = next(c for c in arch["components"] if c["id"] == "kernel")
    assert kernel["status"] == "offline"


# ---------------------------------------------------------------------------
# 2. Pipeline
# ---------------------------------------------------------------------------

def test_pipeline_stages(monitor):
    stages = monitor.get_pipeline_stages()
    assert len(stages) == 9
    assert stages[0]["id"] == "intake"
    assert stages[-1]["id"] == "deliver"


def test_record_pipeline_run(monitor):
    monitor.record_pipeline_run({
        "id": "run-1",
        "stages": ["intake", "classify", "build"],
        "total_time_ms": 150,
        "domain": "finance",
        "mode": "basic",
        "events_generated": 2,
    })
    runs = monitor.get_pipeline_runs()
    assert len(runs) == 1
    assert runs[0]["domain"] == "finance"


# ---------------------------------------------------------------------------
# 3. KC Explorer
# ---------------------------------------------------------------------------

def test_kc_explorer(monitor):
    explorer = monitor.get_kc_explorer()
    assert "categories" in explorer
    assert len(explorer["categories"]) >= 8
    assert explorer["total_items"] >= 0


# ---------------------------------------------------------------------------
# 4. Cognitive Timeline
# ---------------------------------------------------------------------------

def test_cognitive_timeline(monitor):
    timeline = monitor.get_cognitive_timeline()
    assert isinstance(timeline, list)


# ---------------------------------------------------------------------------
# 5. Cognitive Health
# ---------------------------------------------------------------------------

def test_cognitive_health(monitor):
    health = monitor.get_cognitive_health()
    assert "grade" in health
    assert "total_events" in health


def test_cognitive_health_offline(monitor_no_kernel):
    health = monitor_no_kernel.get_cognitive_health()
    assert health["grade"] == "N/A"


# ---------------------------------------------------------------------------
# 6. Constitution Live
# ---------------------------------------------------------------------------

def test_constitution_live(monitor):
    const = monitor.get_constitution_live()
    assert const["constitution_active"] is True
    assert const["total_guardians"] >= 6
    for g in const["guardians"]:
        assert g["status"] == "active"


# ---------------------------------------------------------------------------
# 7. Capability Explorer
# ---------------------------------------------------------------------------

def test_capability_explorer(monitor):
    caps = monitor.get_capability_explorer()
    assert caps["total"] >= 10
    assert any(c["name"] == "knowledge" for c in caps["capabilities"])


# ---------------------------------------------------------------------------
# 8. Symbiotic Layer Live
# ---------------------------------------------------------------------------

def test_symbiotic_live(monitor):
    sym = monitor.get_symbiotic_live()
    assert sym["status"] == "active"
    assert "os" in sym
    assert "cpu" in sym
    assert "ram" in sym


# ---------------------------------------------------------------------------
# 9. Cognitive Map
# ---------------------------------------------------------------------------

def test_cognitive_map(monitor):
    cmap = monitor.get_cognitive_map()
    assert "nodes" in cmap
    assert "edges" in cmap


# ---------------------------------------------------------------------------
# 10. Developer Mode
# ---------------------------------------------------------------------------

def test_developer_toggle(monitor):
    assert monitor._developer_mode is False
    monitor.toggle_developer_mode()
    assert monitor._developer_mode is True
    monitor.toggle_developer_mode()
    assert monitor._developer_mode is False


def test_developer_view(monitor):
    view = monitor.get_developer_view()
    assert "uptime_seconds" in view
    assert "events_logged" in view


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_log_event(monitor):
    monitor.log("kernel", "started", "Kernel initialized")
    events = monitor.get_events()
    assert len(events) == 1
    assert events[0]["category"] == "kernel"


def test_log_filter_by_category(monitor):
    monitor.log("kernel", "started", "Kernel")
    monitor.log("pipeline", "complete", "Pipeline ran")
    events = monitor.get_events(category="kernel")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Full snapshot
# ---------------------------------------------------------------------------

def test_full_snapshot(monitor):
    snapshot = monitor.get_full_snapshot()
    assert "architecture" in snapshot
    assert "pipeline_stages" in snapshot
    assert "kc_explorer" in snapshot
    assert "cognitive_health" in snapshot
    assert "constitution" in snapshot
    assert "capabilities" in snapshot
    assert "symbiotic" in snapshot


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_monitor_name(monitor):
    assert monitor.name == "intent_os_monitor_v2"


def test_monitor_version(monitor):
    assert monitor.version == "2.0.0"
