"""Test: Intent OS Desktop application."""

import pytest
from intent_os_desktop import IntentOSDesktop, create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path / "intent-data"))
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
    assert result["status"] == result["presentation"]["visible_state"]
    assert result["execution_mode"]
    assert result["product_contract_version"] == "1.0"
    assert result["response_authority"] == "CognitiveResponseAssembler"
    assert 0.0 <= result["confidence"] <= 1.0


def test_desktop_unknown_does_not_become_success_or_finance(app):
    result = app.process_intent("Qual a capital de XZ-91?")
    assert result["status"] == "UNKNOWN"
    assert result["presentation"]["visible_state"] == "UNKNOWN"
    assert result["provider_called"] is False
    assert result["mission_id"] is None
    assert result["compatibility_path_used"] is False


def test_desktop_context_cannot_override_action_or_message(app):
    result = app.process_intent(
        "Qual a capital de XZ-91?",
        {
            "action": "restore_session",
            "message": "Crie e envie um e-mail.",
            "session_id": "reserved-fields",
        },
    )
    assert result["status"] == "UNKNOWN"
    assert result["mission_id"] is None
    assert result["provider_called"] is False


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
