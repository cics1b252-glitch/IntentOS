"""Real product-path contracts for Movements 5B/5C/5D, 6B and 8."""

from __future__ import annotations

import pytest

from intent_kernel.cognition.runtime import (
    CognitiveExecutionDecision,
    CognitiveExecutionMode,
)
from intent_kernel.contracts import MissionId, MissionStatus
from product_bridge import ProductBridge
from intent_kernel.tools.models import ToolAuthorizationDecisionState


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


@pytest.mark.asyncio
async def test_unknown_interrupts_pending_finance_without_consuming_it(bridge):
    first = await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil por mês.",
        "session_id": "pending-unknown",
    })
    saved_before = bridge._load_session("pending-unknown")

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Qual a capital de um planeta fictício chamado XZ-91?",
        "session_id": "pending-unknown",
    })
    saved_after = bridge._load_session("pending-unknown")

    assert first["status"] == "WAITING_CONTEXT"
    assert response["status"] == "UNKNOWN"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert "R$ 91" not in response["text"]
    assert "investimento" not in response["text"].casefold()
    assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]
    assert saved_after["mission_id"] == saved_before["mission_id"]


@pytest.mark.asyncio
async def test_blocked_interrupts_pending_dialogue_without_mutation(
    bridge, monkeypatch
):
    await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "pending-blocked",
    })
    saved_before = bridge._load_session("pending-blocked")

    async def blocked(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.BLOCKED,
            reason="test policy denial",
            domain_hint="other",
        )

    monkeypatch.setattr(
        bridge.components.cognitive_capability_runtime,
        "analyze",
        blocked,
    )
    response = await bridge.dispatch({
        "action": "chat",
        "message": "entrada bloqueada",
        "session_id": "pending-blocked",
    })
    saved_after = bridge._load_session("pending-blocked")

    assert response["status"] == "BLOCKED"
    assert response["execution_mode"] == "BLOCKED"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert saved_after == saved_before


@pytest.mark.asyncio
async def test_explicit_compatibility_cannot_override_unknown(bridge):
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Qual a capital de um planeta fictício chamado XZ-91?",
        "session_id": "explicit-unknown",
        "allow_compatibility_fallback": True,
    })

    assert response["status"] == "UNKNOWN"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert "R$ 91" not in response["text"]


@pytest.mark.asyncio
async def test_valid_recurrence_and_goal_answers_continue_pending_finance(bridge):
    first = await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "valid-continuation",
    })
    recurrence = await bridge.dispatch({
        "action": "chat",
        "message": "com aportes mensais",
        "session_id": "valid-continuation",
    })
    goal = await bridge.dispatch({
        "action": "chat",
        "message": "para aposentadoria",
        "session_id": "valid-continuation",
    })

    assert first["target_field"] == "recurrence"
    assert recurrence["status"] == "WAITING_CONTEXT"
    assert recurrence["target_field"] == "goal"
    assert first["mission_id"] is None
    assert recurrence["mission_id"] is None
    assert recurrence["compatibility_dialogue_id"] == first["compatibility_dialogue_id"]
    assert goal["status"] == "WAITING_CONTEXT"
    assert goal["target_field"] == "risk_profile"
    assert goal["mission_id"] is None
    assert goal["compatibility_dialogue_id"] == first["compatibility_dialogue_id"]


@pytest.mark.asyncio
async def test_unrelated_explanation_interrupts_pending_finance(bridge):
    await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "pending-explanation",
    })
    saved_before = bridge._load_session("pending-explanation")
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Explique juros compostos.",
        "session_id": "pending-explanation",
    })
    saved_after = bridge._load_session("pending-explanation")

    assert response["status"] == "EXTERNAL_RESOURCE_REQUIRED"
    assert response["mission_id"] is None
    assert "perfil de risco" not in response["text"].casefold()
    assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]
    assert saved_after["conversation_state"]["known_context"] == saved_before["conversation_state"]["known_context"]


@pytest.mark.asyncio
async def test_zero_provider_unknown_interrupts_pending_finance(bridge):
    await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "pending-zero-provider",
    })
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Qual a população da Islândia em 2025?",
        "session_id": "pending-zero-provider",
    })

    assert response["status"] == "UNKNOWN"
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert response["provider_called"] is False


@pytest.mark.asyncio
async def test_local_response_interrupts_pending_finance(bridge):
    first = await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "pending-local",
    })
    response = await bridge.dispatch({
        "action": "chat",
        "message": "O que você consegue fazer?",
        "session_id": "pending-local",
    })

    assert response["status"] == "COMPLETED"
    assert response["execution_mode"] == "LOCAL_RESPONSE"
    assert response["mission_id"] is None
    assert first["mission_id"] is None
    assert first["compatibility_dialogue_id"]


@pytest.mark.asyncio
async def test_authorization_and_mission_override_pending_finance(bridge):
    first = await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": "pending-action",
    })
    authorization = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "session_id": "pending-action",
    })
    mission = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "session_id": "pending-action",
        "authorized_permissions": ["email.send"],
    })

    assert authorization["status"] == "AUTHORIZATION_REQUIRED"
    assert authorization["mission_id"] is None
    assert mission["execution_mode"] == "MISSION"
    assert mission["runtime_status"] == "WAITING_USER_CONFIRMATION"
    assert mission["mission_id"] != first["mission_id"]


async def _advance_finance_to(bridge, session_id, target_field):
    response = await bridge.dispatch({
        "action": "chat", "message": "Quero investir 24 mil.",
        "session_id": session_id,
    })
    steps = {
        "recurrence": [],
        "goal": ["com aportes mensais"],
        "risk_profile": ["com aportes mensais", "para aposentadoria"],
        "time_horizon": [
            "com aportes mensais", "para aposentadoria", "sou moderado",
        ],
    }
    for answer in steps[target_field]:
        response = await bridge.dispatch({
            "action": "chat", "message": answer, "session_id": session_id,
        })
    assert response["target_field"] == target_field
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("target_field,message", [
    ("goal", "Minha casa é azul."),
    ("recurrence", "Minha reunião mensal terminou."),
    ("risk_profile", "O carro está seguro."),
    ("time_horizon", "O projeto dura cinco anos."),
])
async def test_marker_collision_is_not_pending_continuation(
    bridge, target_field, message
):
    session_id = f"false-positive-{target_field}"
    pending_response = await _advance_finance_to(
        bridge, session_id, target_field
    )
    saved_before = bridge._load_session(session_id)

    response = await bridge.dispatch({
        "action": "chat", "message": message, "session_id": session_id,
    })
    saved_after = bridge._load_session(session_id)

    assert response["pending_dialogue_match"]["match_status"] == "NOT_A_CONTINUATION"
    assert response["mission_id"] is None
    assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]
    assert saved_after["conversation_state"]["known_context"] == saved_before["conversation_state"]["known_context"]
    assert pending_response["mission_id"] is None
    assert pending_response["compatibility_dialogue_id"] == saved_before["mission_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("target_field,message,candidate", [
    ("goal", "para aposentadoria", "aposentadoria"),
    ("goal", "quero investir para comprar uma casa", "compra de imóvel"),
    ("recurrence", "com aportes mensais", "mensal"),
    ("risk_profile", "sou moderado", "moderado"),
    ("time_horizon", "por cinco anos", "cinco anos"),
])
async def test_typed_pending_answers_remain_valid_continuations(
    bridge, target_field, message, candidate
):
    session_id = f"valid-semantic-{target_field}-{candidate}"
    pending_response = await _advance_finance_to(
        bridge, session_id, target_field
    )
    response = await bridge.dispatch({
        "action": "chat", "message": message, "session_id": session_id,
    })

    assert response["pending_dialogue_match"]["match_status"] == "VALID_CONTINUATION"
    assert response["pending_dialogue_match"]["candidate_value"] == candidate
    assert response["mission_id"] is None
    assert response["compatibility_dialogue_id"] == pending_response["compatibility_dialogue_id"]


@pytest.mark.asyncio
async def test_ambiguous_pending_answer_does_not_mutate_dialogue(bridge):
    session_id = "ambiguous-pending"
    await _advance_finance_to(bridge, session_id, "goal")
    saved_before = bridge._load_session(session_id)

    response = await bridge.dispatch({
        "action": "chat", "message": "talvez", "session_id": session_id,
    })
    saved_after = bridge._load_session(session_id)

    assert response["pending_dialogue_match"]["match_status"] == "AMBIGUOUS"
    assert response["mission_id"] is None
    assert saved_after["pending_dialogue"] == saved_before["pending_dialogue"]
    assert saved_after["conversation_state"]["known_context"] == saved_before["conversation_state"]["known_context"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gate_state,expected_status,runtime_calls,action_gate_calls,mission_status",
    [
        (ToolAuthorizationDecisionState.ALLOW, "AUTHORIZATION_REQUIRED", 1, 1, MissionStatus.WAITING_FOR_DECISION),
        (ToolAuthorizationDecisionState.DENY, "BLOCKED", 0, 0, MissionStatus.BLOCKED),
        (ToolAuthorizationDecisionState.REQUEST_PERMISSION, "AUTHORIZATION_REQUIRED", 0, 0, MissionStatus.WAITING_FOR_PERMISSION),
        (ToolAuthorizationDecisionState.REQUEST_CONFIRMATION, "AUTHORIZATION_REQUIRED", 0, 0, MissionStatus.WAITING_FOR_DECISION),
        (ToolAuthorizationDecisionState.WAIT_TOOL, "EXTERNAL_RESOURCE_REQUIRED", 0, 0, MissionStatus.WAITING_FOR_INFORMATION),
        (ToolAuthorizationDecisionState.RESELECT_TOOL, "EXTERNAL_RESOURCE_REQUIRED", 0, 0, MissionStatus.WAITING_FOR_DECISION),
    ],
)
async def test_only_allow_crosses_tool_authorization_boundary(
    bridge, monkeypatch, gate_state, expected_status, runtime_calls,
    action_gate_calls, mission_status,
):
    counters = {
        "runtime_create": 0, "runtime_run": 0,
        "action_gate": 0, "executor": 0,
    }

    async def evaluate_tool(*_args, **_kwargs):
        return gate_state

    runtime = bridge.components.mission_runtime
    original_create = runtime.create_instance
    original_run = runtime.run_mission
    original_action_gate = runtime.action_gate.evaluate
    original_execute = runtime.executor.execute

    def counted_create(*args, **kwargs):
        counters["runtime_create"] += 1
        return original_create(*args, **kwargs)

    async def counted_run(*args, **kwargs):
        counters["runtime_run"] += 1
        return await original_run(*args, **kwargs)

    async def counted_action_gate(*args, **kwargs):
        counters["action_gate"] += 1
        return await original_action_gate(*args, **kwargs)

    async def counted_execute(*args, **kwargs):
        counters["executor"] += 1
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(
        bridge.components.tool_authorization_gate,
        "evaluate_tool",
        evaluate_tool,
    )
    monkeypatch.setattr(runtime, "create_instance", counted_create)
    monkeypatch.setattr(runtime, "run_mission", counted_run)
    monkeypatch.setattr(runtime.action_gate, "evaluate", counted_action_gate)
    monkeypatch.setattr(runtime.executor, "execute", counted_execute)

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
    })

    assert response["authorization_gate"] == gate_state.value
    assert response["status"] == expected_status
    assert counters == {
        "runtime_create": runtime_calls,
        "runtime_run": runtime_calls,
        "action_gate": action_gate_calls,
        "executor": 0,
    }
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission is not None
    assert mission.status is mission_status
    if gate_state is ToolAuthorizationDecisionState.ALLOW:
        assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    else:
        assert response["runtime_id"] is None
        assert response["runtime_status"] is None


@pytest.mark.asyncio
async def test_authorization_confirmation_is_distinct_from_tool_permission(
    bridge, monkeypatch
):
    async def evaluate_tool(*_args, **_kwargs):
        return ToolAuthorizationDecisionState.REQUEST_CONFIRMATION

    monkeypatch.setattr(
        bridge.components.tool_authorization_gate,
        "evaluate_tool",
        evaluate_tool,
    )
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Crie e envie um e-mail.",
        "authorized_permissions": ["email.send"],
    })

    assert response["confirmation_state"] == "WAITING_USER_CONFIRMATION"
    assert response["authorization_gate"] == "REQUEST_CONFIRMATION"
    assert response["runtime_id"] is None
