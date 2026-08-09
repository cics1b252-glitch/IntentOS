"""Test: Intent OS Desktop application."""

import pytest
from intent_os_desktop import IntentOSDesktop, create_app


@pytest.fixture
def app():
    return create_app()


def test_app_initializes(app):
    assert app.kernel is not None
    assert app.monitor is not None


def test_app_status(app):
    status = app.get_status()
    assert status["status"] == "online"
    assert "kernel" in status


def test_process_intent(app):
    result = app.process_intent("Quero investir 5000/mês")
    assert result["text"]
    assert result["mode"] in ("quick", "basic", "detail", "expert", "architect")
    assert result["domain"]
    assert 0.0 <= result["confidence"] <= 1.0


def test_dashboard(app):
    dashboard = app.get_dashboard()
    assert "kernel" in dashboard
    assert "monitor_summary" in dashboard


def test_knowledge_events(app):
    events = app.get_knowledge_events()
    assert isinstance(events, list)


def test_config(app):
    assert "theme" in app.config
    assert "language" in app.config
