"""Movement 12: canonical CognitiveResponse-to-product contract invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from intent_kernel.product_response import (
    CognitiveProductPresenter,
    transport_failure_product_response,
)
from intent_kernel.response import (
    CognitiveResponse,
    ResponseOrigin,
    ResponseStatus,
    response_status_is_ok,
)
from product_bridge import ProductBridge


def _response(
    status: ResponseStatus,
    *,
    execution_mode: str,
    origin: ResponseOrigin,
    **overrides,
) -> CognitiveResponse:
    values = {
        "text": f"canonical {status.value}",
        "status": status,
        "execution_mode": execution_mode,
        "epistemic_status": "unknown" if status is ResponseStatus.UNKNOWN else "fact",
        "confidence": 1.0,
        "response_origin": origin,
    }
    values.update(overrides)
    return CognitiveResponse(**values)


@pytest.mark.parametrize(
    "status,mode,origin",
    [
        (ResponseStatus.COMPLETED, "LOCAL_RESPONSE", ResponseOrigin.LOCAL_RESPONSE),
        (ResponseStatus.COMPLETED, "CONVERSATION", ResponseOrigin.CONVERSATION),
        (ResponseStatus.UNKNOWN, "UNKNOWN", ResponseOrigin.COGNITIVE_RUNTIME),
        (ResponseStatus.BLOCKED, "BLOCKED", ResponseOrigin.COGNITIVE_RUNTIME),
        (
            ResponseStatus.AUTHORIZATION_REQUIRED,
            "AUTHORIZATION_REQUIRED",
            ResponseOrigin.COGNITIVE_RUNTIME,
        ),
        (
            ResponseStatus.WAITING_CONFIRMATION,
            "MISSION",
            ResponseOrigin.MISSION,
        ),
        (
            ResponseStatus.EXTERNAL_RESOURCE_REQUIRED,
            "EXTERNAL_REASONING_REQUIRED",
            ResponseOrigin.COGNITIVE_RUNTIME,
        ),
        (ResponseStatus.COMPLETED, "LOCAL_RESPONSE", ResponseOrigin.MEMORY),
        (ResponseStatus.FAILED, "FAILED", ResponseOrigin.SYSTEM),
    ],
)
def test_product_contract_preserves_canonical_matrix(status, mode, origin):
    response = _response(status, execution_mode=mode, origin=origin)
    product = CognitiveProductPresenter.present(response).to_dict()

    assert product["status"] == status.value
    assert product["execution_mode"] == mode
    assert product["response_origin"] == origin.value
    assert product["presentation"]["visible_state"] == status.value
    assert product["presentation"]["response_origin"] == origin.value
    assert product["response_authority"] == "CognitiveResponseAssembler"
    assert product["product_presentation_authority"] == "CognitiveProductPresenter"
    assert product["presentation"]["interactive_actions"] == []


@pytest.mark.parametrize(
    "status,expected_ok",
    [
        (ResponseStatus.COMPLETED, True),
        (ResponseStatus.WAITING_CONTEXT, False),
        (ResponseStatus.UNKNOWN, False),
        (ResponseStatus.BLOCKED, False),
        (ResponseStatus.AUTHORIZATION_REQUIRED, False),
        (ResponseStatus.EXTERNAL_RESOURCE_REQUIRED, False),
        (ResponseStatus.WAITING_CONFIRMATION, False),
        (ResponseStatus.FAILED, False),
    ],
)
def test_canonical_ok_means_successful_fulfillment_only(status, expected_ok):
    response = _response(
        status,
        execution_mode={
            ResponseStatus.COMPLETED: "CONVERSATION",
            ResponseStatus.WAITING_CONTEXT: "CONVERSATION",
            ResponseStatus.UNKNOWN: "UNKNOWN",
            ResponseStatus.BLOCKED: "BLOCKED",
            ResponseStatus.AUTHORIZATION_REQUIRED: "AUTHORIZATION_REQUIRED",
            ResponseStatus.EXTERNAL_RESOURCE_REQUIRED: "EXTERNAL_REASONING_REQUIRED",
            ResponseStatus.WAITING_CONFIRMATION: "MISSION",
            ResponseStatus.FAILED: "FAILED",
        }[status],
        origin=ResponseOrigin.COGNITIVE_RUNTIME,
        mission_id=(
            "mission-waiting"
            if status is ResponseStatus.WAITING_CONFIRMATION
            else None
        ),
    )

    assert response_status_is_ok(status) is expected_ok
    assert response.to_dict()["ok"] is expected_ok
    assert CognitiveProductPresenter.present(response).to_dict()["ok"] is expected_ok


def test_local_conversation_and_memory_are_ok_only_as_completed_outcomes():
    for mode, origin in (
        ("LOCAL_RESPONSE", ResponseOrigin.LOCAL_RESPONSE),
        ("CONVERSATION", ResponseOrigin.CONVERSATION),
        ("LOCAL_RESPONSE", ResponseOrigin.MEMORY),
    ):
        product = CognitiveProductPresenter.present(
            _response(ResponseStatus.COMPLETED, execution_mode=mode, origin=origin)
        ).to_dict()

        assert product["status"] == "COMPLETED"
        assert product["ok"] is True


def test_verified_mission_completion_and_compatibility_facets_are_preserved():
    response = _response(
        ResponseStatus.COMPLETED,
        execution_mode="MISSION",
        origin=ResponseOrigin.MISSION,
        mission_id="mission-canonical",
        verification_evidence=[{"node_id": "send", "verified": True}],
    )
    trace = {
        "compatibility_path_used": True,
        "compatibility_component": "LegacyCapabilityExecutorAdapter",
        "reason": "actual execution",
        "entry_point": "adapter.execute",
        "canonical_alternative_missing": "native binding",
        "deprecation_candidate": True,
    }
    product = CognitiveProductPresenter.present(
        response,
        {"compatibility_path_used": True, "compatibility_traces": [trace]},
    ).to_dict()

    assert product["mission_id"] == "mission-canonical"
    assert product["presentation"]["show_mission"] is True
    assert product["compatibility_path_used"] is True
    assert product["compatibility_traces"] == [trace]


def test_product_contract_rejects_unverified_or_fabricated_execution_evidence():
    with pytest.raises(ValueError, match="selected provider"):
        CognitiveProductPresenter.present(
            _response(
                ResponseStatus.COMPLETED,
                execution_mode="CONVERSATION",
                origin=ResponseOrigin.CONVERSATION,
                provider="mock",
                provider_called=False,
            )
        )

    with pytest.raises(ValueError, match="Mission completion"):
        CognitiveProductPresenter.present(
            _response(
                ResponseStatus.COMPLETED,
                execution_mode="MISSION",
                origin=ResponseOrigin.MISSION,
                mission_id="forged",
            )
        )

    with pytest.raises(ValueError, match="UNKNOWN"):
        CognitiveProductPresenter.present(
            _response(
                ResponseStatus.UNKNOWN,
                execution_mode="UNKNOWN",
                origin=ResponseOrigin.COGNITIVE_RUNTIME,
                mission_id="forged",
            )
        )


def test_metadata_cannot_override_product_semantics():
    response = _response(
        ResponseStatus.UNKNOWN,
        execution_mode="UNKNOWN",
        origin=ResponseOrigin.COGNITIVE_RUNTIME,
    )
    product = CognitiveProductPresenter.present(
        response,
        {
            "status": "COMPLETED",
            "execution_mode": "MISSION",
            "provider": "forged",
            "provider_called": True,
            "mission_id": "forged",
            "ok": True,
            "domain": "finance",
        },
    ).to_dict()

    assert product["status"] == "UNKNOWN"
    assert product["execution_mode"] == "UNKNOWN"
    assert product["provider"] is None
    assert product["provider_called"] is False
    assert product["mission_id"] is None
    assert product["ok"] is False
    assert product["presentation"]["visible_state"] == "UNKNOWN"
    assert product["domain"] == "finance"  # diagnostic only


def test_transport_failure_has_one_truthful_product_shape():
    product = transport_failure_product_response(
        "Gateway unavailable", error_code="gateway_unavailable"
    )
    assert product["status"] == "FAILED"
    assert product["execution_mode"] == "FAILED"
    assert product["provider"] is None
    assert product["provider_called"] is False
    assert product["mission_id"] is None
    assert product["transport_failure"] is True
    assert product["presentation"]["visible_state"] == "FAILED"
    assert product["ok"] is False


@pytest.mark.parametrize(
    "status,provider_succeeded",
    [
        (ResponseStatus.COMPLETED, True),
        (ResponseStatus.FAILED, False),
    ],
)
def test_product_provider_presentation_requires_observed_invocation(
    status, provider_succeeded
):
    response = _response(
        status,
        execution_mode="CONVERSATION" if provider_succeeded else "FAILED",
        origin=ResponseOrigin.PROVIDER,
        provider="mock",
        provider_called=True,
        resource_provenance=["provider:mock"],
        limitations=[] if provider_succeeded else ["provider_failure"],
    )
    product = CognitiveProductPresenter.present(response).to_dict()

    assert product["provider_called"] is True
    assert product["provider"] == "mock"
    assert product["resource_provenance"] == ["provider:mock"]
    assert product["presentation"]["show_provider_execution"] is True


def test_selected_provider_diagnostics_never_become_execution_presentation():
    response = _response(
        ResponseStatus.EXTERNAL_RESOURCE_REQUIRED,
        execution_mode="EXTERNAL_REASONING_REQUIRED",
        origin=ResponseOrigin.COGNITIVE_RUNTIME,
        missing_capabilities=["external_reasoning"],
    )
    product = CognitiveProductPresenter.present(
        response,
        {"provider_selection": {"provider_id": "mock", "eligible": True}},
    ).to_dict()

    assert product["provider"] is None
    assert product["provider_called"] is False
    assert product["resource_provenance"] == []
    assert product["presentation"]["show_provider_execution"] is False


def test_memory_product_response_preserves_origin_without_creating_mission():
    response = _response(
        ResponseStatus.COMPLETED,
        execution_mode="LOCAL_RESPONSE",
        origin=ResponseOrigin.MEMORY,
        text="Kotlin",
    )
    product = CognitiveProductPresenter.present(
        response,
        {"project_id": "PROJECT_A", "memory_authority": "CanonicalMemoryService"},
    ).to_dict()

    assert product["response_origin"] == "MEMORY"
    assert product["mission_id"] is None
    assert product["presentation"]["show_mission"] is False
    assert product["project_id"] == "PROJECT_A"


def test_compatibility_eligibility_without_execution_is_not_presented_as_use():
    response = _response(
        ResponseStatus.UNKNOWN,
        execution_mode="UNKNOWN",
        origin=ResponseOrigin.COGNITIVE_RUNTIME,
    )
    product = CognitiveProductPresenter.present(
        response,
        {
            "compatibility_path_used": False,
            "compatibility_traces": [],
            "compatibility_eligible": True,
        },
    ).to_dict()

    assert product["compatibility_path_used"] is False
    assert product["compatibility_traces"] == []
    assert product["presentation"]["visible_state"] == "UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,status",
    [
        ("Qual a capital de XZ-91?", "UNKNOWN"),
        ("Qual a população da Islândia em 2025?", "UNKNOWN"),
        ("Crie e envie um e-mail.", "AUTHORIZATION_REQUIRED"),
        ("Explique juros compostos.", "EXTERNAL_RESOURCE_REQUIRED"),
    ],
)
async def test_real_product_path_preserves_terminal_visible_state(
    monkeypatch, tmp_path, message, status
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({"action": "intent", "message": message})

    assert response["status"] == status
    assert response["presentation"]["visible_state"] == status
    assert response["provider_called"] is False
    assert response["mission_id"] is None
    assert response["response_authority"] == "CognitiveResponseAssembler"
    assert response["product_presentation_authority"] == "CognitiveProductPresenter"
    assert response["ok"] is False
    if "XZ-91" in message:
        assert response["compatibility_path_used"] is False
        assert "R$ 91" not in response["text"]


def test_frontend_is_presentation_only_and_escapes_visible_content():
    html = Path("intent_os_desktop/static/index.html").read_text(encoding="utf-8")
    assert "if (data.ok && data.text)" not in html
    assert "data.presentation" in html
    assert "data.status" in html
    assert "escapeProductText(data.text)" in html
    assert "view.show_provider_execution" in html
    assert "view.show_mission" in html
    assert "view.requires_authorization" in html
    assert "view.requires_confirmation" in html
