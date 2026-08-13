"""Movement 11.2 adversarial tests for canonical conversation authority."""

from __future__ import annotations

from copy import deepcopy

import pytest

from intent_kernel.conversation import (
    CognitiveConversationService,
    ConversationTurnRelation,
)
from product_bridge import ProductBridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return ProductBridge()


async def _pending_finance(bridge: ProductBridge, session_id: str):
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Quero investir 24 mil.",
        "session_id": session_id,
        "project_id": "PROJECT_A",
    })
    assert response["status"] == "WAITING_CONTEXT"
    assert response["target_field"] == "recurrence"
    return response


@pytest.mark.asyncio
async def test_product_bridge_delegates_turn_boundary_to_canonical_service(
    bridge, monkeypatch
):
    assert bridge.conversation_service is bridge.components.conversation_service
    assert bridge.kernel.runtime_description["conversation_authority"] == (
        "CognitiveConversationService"
    )
    calls = 0
    original = bridge.conversation_service.analyze_turn

    async def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(bridge.conversation_service, "analyze_turn", counted)
    response = await bridge.dispatch({
        "action": "chat",
        "message": "O que você consegue fazer?",
        "session_id": "canonical-owner",
    })

    assert calls == 1
    assert response["conversation_authority"]["authority"] == (
        "CognitiveConversationService"
    )
    assert response["conversation_authority"]["relation"] == (
        "NEW_CONVERSATION_TURN"
    )
    diagnostics = await bridge.dispatch({"action": "diagnostics"})
    assert diagnostics["conversation_authority"] == response["conversation_authority"]


@pytest.mark.asyncio
async def test_ordinary_independent_conversation_does_not_invent_mission_id(
    bridge,
):
    response = await bridge.dispatch({
        "action": "chat",
        "message": "Este projeto usa Kotlin.",
        "session_id": "ordinary-conversation",
        "project_id": "PROJECT_A",
    })

    assert response["execution_mode"] == "CONVERSATION"
    assert response["mission_id"] is None
    assert response["conversation_authority"]["relation"] == (
        "NEW_CONVERSATION_TURN"
    )


@pytest.mark.asyncio
async def test_independent_nonterminal_turn_cannot_inherit_pending_finance(
    bridge,
):
    first = await _pending_finance(bridge, "independent-memory-write")
    before = bridge._load_session("independent-memory-write")

    response = await bridge.dispatch({
        "action": "chat",
        "message": "Este projeto usa Kotlin.",
        "session_id": "independent-memory-write",
        "project_id": "PROJECT_A",
        "resume_mission_id": first["compatibility_dialogue_id"],
    })
    after = bridge._load_session("independent-memory-write")

    authority = response["conversation_authority"]
    assert authority["relation"] == "INDEPENDENT_INTENT_INTERRUPTION"
    assert authority["pending_context_eligible"] is False
    assert authority["resume_mission_id"] is None
    assert response["domain"] != "finance"
    assert response["mission_id"] is None
    assert "aporte" not in response["text"].casefold()
    assert after["pending_dialogue"] == before["pending_dialogue"]
    assert after["mission_id"] == before["mission_id"]
    assert (
        after["conversation_state"]["known_context"]
        == before["conversation_state"]["known_context"]
    )


@pytest.mark.asyncio
async def test_interrupted_pending_dialogue_remains_explicitly_resumable(bridge):
    first = await _pending_finance(bridge, "resume-after-interruption")
    await bridge.dispatch({
        "action": "chat",
        "message": "Este projeto usa Kotlin.",
        "session_id": "resume-after-interruption",
        "project_id": "PROJECT_A",
    })

    resumed = await bridge.dispatch({
        "action": "chat",
        "message": "com aportes mensais",
        "session_id": "resume-after-interruption",
        "project_id": "PROJECT_A",
    })

    assert resumed["conversation_authority"]["relation"] == (
        "VALID_PENDING_CONTINUATION"
    )
    assert resumed["target_field"] == "goal"
    assert resumed["mission_id"] is None
    assert resumed["compatibility_dialogue_id"] == first["compatibility_dialogue_id"]


@pytest.mark.asyncio
async def test_local_response_during_pending_preserves_suspended_dialogue(bridge):
    first = await _pending_finance(bridge, "local-interruption")
    before = bridge._load_session("local-interruption")

    response = await bridge.dispatch({
        "action": "chat",
        "message": "O que você consegue fazer?",
        "session_id": "local-interruption",
        "project_id": "PROJECT_A",
    })
    after = bridge._load_session("local-interruption")

    assert response["execution_mode"] == "LOCAL_RESPONSE"
    assert response["mission_id"] is None
    assert response["conversation_authority"]["preserves_pending_dialogue"]
    assert response["conversation_authority"]["resume_mission_id"] is None
    assert after["pending_dialogue"] == before["pending_dialogue"]
    assert after["mission_id"] == first["compatibility_dialogue_id"]


@pytest.mark.asyncio
async def test_ambiguous_input_fails_closed_and_preserves_pending(bridge):
    await _pending_finance(bridge, "ambiguous-authority")
    before = bridge._load_session("ambiguous-authority")

    response = await bridge.dispatch({
        "action": "chat",
        "message": "talvez",
        "session_id": "ambiguous-authority",
        "project_id": "PROJECT_A",
    })
    after = bridge._load_session("ambiguous-authority")

    authority = response["conversation_authority"]
    assert authority["relation"] == "AMBIGUOUS_PENDING_INPUT"
    assert authority["pending_context_eligible"] is False
    assert authority["resume_mission_id"] is None
    assert response["mission_id"] is None
    assert after["pending_dialogue"] == before["pending_dialogue"]
    assert (
        after["conversation_state"]["known_context"]
        == before["conversation_state"]["known_context"]
    )


@pytest.mark.asyncio
async def test_session_merge_policy_does_not_mutate_inputs(bridge):
    await _pending_finance(bridge, "pure-session-merge")
    previous = bridge._load_session("pure-session-merge")
    decision = await bridge.conversation_service.analyze_turn(
        "Este projeto usa Kotlin.",
        saved_session=previous,
        project_id="PROJECT_A",
    )
    proposed = {
        "mission_id": "unrelated",
        "mission_status": "completed",
        "pending_dialogue": None,
        "conversation_state": {
            "known_context": {"technology": "Kotlin"},
            "active_mission_id": "unrelated",
        },
    }
    previous_copy = deepcopy(previous)
    proposed_copy = deepcopy(proposed)

    merged = CognitiveConversationService.merge_session_update(
        previous,
        proposed,
        decision,
    )

    assert decision.relation is ConversationTurnRelation.INDEPENDENT_INTENT_INTERRUPTION
    assert previous == previous_copy
    assert proposed == proposed_copy
    assert merged["mission_id"] == previous["mission_id"]
    assert merged["pending_dialogue"] == previous["pending_dialogue"]
    assert (
        merged["conversation_state"]["known_context"]
        == previous["conversation_state"]["known_context"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Qual a capital de um planeta fictício chamado XZ-91?",
        "Qual a população da Islândia em 2025?",
        "Crie e envie um e-mail.",
    ],
)
async def test_terminal_or_authorization_turns_never_resume_pending_mission(
    bridge,
    message,
):
    first = await _pending_finance(bridge, f"terminal-{message[:8]}")
    response = await bridge.dispatch({
        "action": "chat",
        "message": message,
        "session_id": f"terminal-{message[:8]}",
        "project_id": "PROJECT_A",
        "resume_mission_id": first["compatibility_dialogue_id"],
    })

    assert response["status"] in {"UNKNOWN", "AUTHORIZATION_REQUIRED"}
    assert response["mission_id"] is None
    assert response["conversation_authority"]["resume_mission_id"] is None
    assert response["conversation_authority"]["preserves_pending_dialogue"]
