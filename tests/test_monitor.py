"""Test: Intent OS Monitor — first official UI."""

import pytest
from intent_kernel.monitor import IntentOSMonitor, MonitorSnapshot
from intent_kernel.kernel import Kernel


@pytest.fixture
def monitor_with_kernel():
    kernel = Kernel()
    return IntentOSMonitor(kernel)


@pytest.fixture
def monitor_without_kernel():
    return IntentOSMonitor()


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def test_snapshot_structure(monitor_with_kernel):
    snapshot = monitor_with_kernel.get_snapshot()
    assert isinstance(snapshot, MonitorSnapshot)
    assert snapshot.timestamp
    assert snapshot.kernel["status"] == "online"
    assert snapshot.constitution["status"] == "active"
    assert snapshot.guardians["status"] == "active"
    assert snapshot.pipeline["status"] == "ready"
    assert snapshot.capabilities["status"] == "active"
    assert snapshot.providers["status"] == "active"
    assert snapshot.knowledge_core["status"] == "active"
    assert snapshot.core_apps["status"] == "active"


def test_snapshot_without_kernel(monitor_without_kernel):
    snapshot = monitor_without_kernel.get_snapshot()
    assert snapshot.kernel["status"] == "offline"
    assert snapshot.constitution["status"] == "offline"
    assert snapshot.guardians["status"] == "offline"


# ---------------------------------------------------------------------------
# Kernel observation
# ---------------------------------------------------------------------------

def test_kernel_observed(monitor_with_kernel):
    k = monitor_with_kernel._observe_kernel()
    assert k["status"] == "online"
    assert "version" in k
    assert "uptime_seconds" in k
    assert "uptime_human" in k
    assert "providers" in k
    assert "modules" in k


def test_uptime_formatting(monitor_with_kernel):
    assert monitor_with_kernel._format_uptime(5) == "5s"
    assert monitor_with_kernel._format_uptime(65) == "1m 5s"
    assert monitor_with_kernel._format_uptime(3661) == "1h 1m"


# ---------------------------------------------------------------------------
# Constitution observation
# ---------------------------------------------------------------------------

def test_constitution_observed(monitor_with_kernel):
    c = monitor_with_kernel._observe_constitution()
    assert c["status"] == "active"
    assert c["pillars"] >= 4
    assert c["constraints"] > 0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def test_log_event(monitor_with_kernel):
    monitor_with_kernel.log_event("info", "Test event", {"key": "value"})
    logs = monitor_with_kernel._get_recent_logs()
    assert len(logs) == 1
    assert logs[0]["type"] == "info"
    assert logs[0]["message"] == "Test event"


def test_log_rotation(monitor_with_kernel):
    for i in range(1100):
        monitor_with_kernel.log_event("info", f"Event {i}")
    logs = monitor_with_kernel._get_recent_logs(limit=1100)
    assert len(logs) == 1000  # max_log_size


# ---------------------------------------------------------------------------
# User summary
# ---------------------------------------------------------------------------

def test_user_summary(monitor_with_kernel):
    summary = monitor_with_kernel.get_user_summary()
    assert "Kernel Online" in summary
    assert "Constitution Ativa" in summary
    assert "Guardians" in summary
    assert "Knowledge Core" in summary


def test_user_summary_offline(monitor_without_kernel):
    summary = monitor_without_kernel.get_user_summary()
    assert "Kernel Offline" in summary


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_metrics(monitor_with_kernel):
    metrics = monitor_with_kernel._compute_metrics()
    assert "uptime_seconds" in metrics
    assert "events_logged" in metrics
    assert metrics["monitor_version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_monitor_name(monitor_with_kernel):
    assert monitor_with_kernel.name == "intent_os_monitor"


def test_monitor_version(monitor_with_kernel):
    assert monitor_with_kernel.version == "0.1.0"


# ---------------------------------------------------------------------------
# Pipeline observation
# ---------------------------------------------------------------------------

def test_pipeline_observed(monitor_with_kernel):
    p = monitor_with_kernel._observe_pipeline()
    assert p["status"] == "ready"
    assert "QUICK" in p["modes"]
    assert "intake" in p["nodes"]
