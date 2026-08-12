"""Real product-path contracts for Movements 5B/5C/5D, 6B and 8."""

from __future__ import annotations

import pytest

from product_bridge import ProductBridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return ProductBridge()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "Qual a população da Islândia em 2025?",
    "Qual a capital de um planeta fictício chamado XZ-91?",
])
async def test_grounded_lookup_never_becomes_money_or_mission(bridge, message):
    response = await bridge.dispatch({"action": "chat", "message": message})
    assert response["status"] == "UNKNOWN"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert response["provider_called"] is False


@pytest.mark.asyncio
async def test_invoice_monthly_is_capability_decomposition_not_finance(bridge):
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Quero analisar automaticamente notas fiscais recebidas, organizar os dados e produzir um resumo mensal.",
    })
    requirements = {
        item["capability_id"]
        for item in response["capability_analysis"]["requirements"]
    }
    assert {"document.read", "data.normalize", "report.aggregate"} <= requirements
    assert response["status"] == "UNKNOWN"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None


@pytest.mark.asyncio
async def test_compound_interest_explanation_is_not_profile_collection(bridge):
    response = await bridge.dispatch({
        "action": "chat", "message": "Explique juros compostos."
    })
    assert response["status"] == "EXTERNAL_RESOURCE_REQUIRED"
    assert "perfil de risco" not in response["text"].casefold()
    assert response["mission_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("message,permission", [
    ("Crie e envie um e-mail.", "email.send"),
    ("Modifique estes arquivos.", "filesystem.write"),
])
async def test_inflected_actions_require_authorization(bridge, message, permission):
    response = await bridge.dispatch({"action": "chat", "message": message})
    assert response["status"] == "AUTHORIZATION_REQUIRED"
    assert permission in response["authorization_requirements"]
    assert response["mission_id"] is None


@pytest.mark.asyncio
async def test_authorized_action_reaches_mission_runtime_without_real_effect(bridge):
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
    })
    assert response["execution_mode"] == "MISSION"
    assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    assert response["authorization_gate"] == "ALLOW"
    assert response["mission_id"]
    assert response["verification_evidence"] == []


@pytest.mark.asyncio
async def test_local_bcc_response_is_governed_without_mission(bridge):
    response = await bridge.dispatch({
        "action": "chat", "message": "O que você consegue fazer?"
    })
    assert response["status"] == "COMPLETED"
    assert response["execution_mode"] == "LOCAL_RESPONSE"
    assert response["mission_id"] is None
    assert response["epistemic_status"]


@pytest.mark.asyncio
async def test_project_memory_survives_restart_without_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    first = ProductBridge()
    await first.dispatch({"action": "chat", "message": "Este projeto usa Flutter.", "project_id": "PROJECT_A", "session_id": "a"})
    await first.dispatch({"action": "chat", "message": "Este projeto usa React.", "project_id": "PROJECT_B", "session_id": "b"})

    restarted = ProductBridge()
    a = await restarted.dispatch({"action": "chat", "message": "Qual tecnologia este projeto usa?", "project_id": "PROJECT_A", "session_id": "a2"})
    b = await restarted.dispatch({"action": "chat", "message": "Qual tecnologia este projeto usa?", "project_id": "PROJECT_B", "session_id": "b2"})
    assert "Flutter" in a["text"] and "React" not in a["text"]
    assert "React" in b["text"] and "Flutter" not in b["text"]


@pytest.mark.asyncio
async def test_preference_memory_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    await ProductBridge().dispatch({"action": "chat", "message": "Prefiro respostas curtas.", "session_id": "p"})
    response = await ProductBridge().dispatch({"action": "chat", "message": "Como prefiro suas respostas?", "session_id": "p2"})
    assert "Prefiro respostas curtas" in response["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "Quero organizar ordens de serviço, peças, clientes e manutenção de uma pequena oficina.",
    "Quero controlar produção, custos, perdas e vendas de uma horta comercial.",
    "Quero aprender japonês e acompanhar meu progresso.",
])
async def test_novel_domains_respect_nonexecutable_composition(bridge, message):
    response = await bridge.dispatch({"action": "chat", "message": message})
    assert response["status"] in {"UNKNOWN", "EXTERNAL_RESOURCE_REQUIRED"}
    assert response["mission_id"] is None
    assert response["missing_capabilities"]
    assert response["provider_called"] is False
