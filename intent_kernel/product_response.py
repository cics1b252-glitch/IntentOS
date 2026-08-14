"""Typed, non-authoritative product projection of a governed CognitiveResponse."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from intent_kernel.response import (
    CognitiveResponse,
    ResponseOrigin,
    ResponseStatus,
    canonical_outcome_semantics,
)


PRODUCT_RESPONSE_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class ProductPresentation:
    """Visible-state projection derived only from canonical response evidence."""

    visible_state: str
    title: str
    tone: str
    response_origin: str
    show_provider_execution: bool
    show_mission: bool
    show_missing_capabilities: bool
    requires_authorization: bool
    requires_confirmation: bool
    suggested_actions: tuple[str, ...] = ()
    interactive_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["suggested_actions"] = list(self.suggested_actions)
        value["interactive_actions"] = list(self.interactive_actions)
        return value


@dataclass(frozen=True, slots=True)
class CognitiveProductResponse:
    """Stable product contract that preserves the CognitiveResponse unchanged."""

    cognitive_response: CognitiveResponse
    presentation: ProductPresentation
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = self.cognitive_response.to_dict()
        payload["product_contract_version"] = PRODUCT_RESPONSE_CONTRACT_VERSION
        payload["presentation"] = self.presentation.to_dict()
        for key, value in self.metadata.items():
            if key not in payload:
                payload[key] = value
        payload["response_authority"] = "CognitiveResponseAssembler"
        payload["product_presentation_authority"] = "CognitiveProductPresenter"
        return payload


class CognitiveProductPresenter:
    """Projects canonical semantics; it never changes or reclassifies them."""

    _TITLE = {
        ResponseStatus.COMPLETED: "Resposta",
        ResponseStatus.WAITING_CONTEXT: "Contexto necessário",
        ResponseStatus.UNKNOWN: "Informação desconhecida",
        ResponseStatus.BLOCKED: "Solicitação bloqueada",
        ResponseStatus.AUTHORIZATION_REQUIRED: "Autorização necessária",
        ResponseStatus.EXTERNAL_RESOURCE_REQUIRED: "Recurso externo necessário",
        ResponseStatus.WAITING_CONFIRMATION: "Confirmação necessária",
        ResponseStatus.FAILED: "Falha de execução",
    }
    _TONE = {
        ResponseStatus.COMPLETED: "neutral",
        ResponseStatus.WAITING_CONTEXT: "attention",
        ResponseStatus.UNKNOWN: "uncertain",
        ResponseStatus.BLOCKED: "blocked",
        ResponseStatus.AUTHORIZATION_REQUIRED: "authorization",
        ResponseStatus.EXTERNAL_RESOURCE_REQUIRED: "resource",
        ResponseStatus.WAITING_CONFIRMATION: "confirmation",
        ResponseStatus.FAILED: "error",
    }

    @classmethod
    def present(
        cls,
        response: CognitiveResponse,
        metadata: Mapping[str, Any] | None = None,
    ) -> CognitiveProductResponse:
        status = response.status
        outcome_semantics = canonical_outcome_semantics(status)
        if response.epistemic_status != outcome_semantics.epistemic_status:
            raise ValueError("epistemic status contradicts canonical outcome")
        if response.confidence != outcome_semantics.confidence:
            raise ValueError("confidence contradicts canonical outcome")
        provider_provenance = any(
            item.startswith("provider:") for item in response.resource_provenance
        )
        if response.provider_called and (
            not response.provider or not provider_provenance
        ):
            raise ValueError("provider invocation evidence is incomplete")
        if not response.provider_called and provider_provenance:
            raise ValueError("provider provenance exists without invocation")
        if (
            not response.provider_called
            and response.provider not in {None, "local"}
        ):
            raise ValueError("selected provider cannot be presented as invoked")
        if status is ResponseStatus.UNKNOWN and (
            response.provider_called or response.mission_id
        ):
            raise ValueError("UNKNOWN cannot expose execution evidence")
        if (
            status is ResponseStatus.COMPLETED
            and response.execution_mode == "MISSION"
            and (
                not response.mission_id
                or not response.verification_evidence
            )
        ):
            raise ValueError("Mission completion requires verified evidence")
        presentation = ProductPresentation(
            visible_state=status.value,
            title=cls._TITLE[status],
            tone=cls._TONE[status],
            response_origin=response.response_origin.value,
            show_provider_execution=bool(
                response.provider_called and response.provider
            ),
            show_mission=bool(response.mission_id),
            show_missing_capabilities=bool(response.missing_capabilities),
            requires_authorization=(
                status is ResponseStatus.AUTHORIZATION_REQUIRED
            ),
            requires_confirmation=(
                status is ResponseStatus.WAITING_CONFIRMATION
            ),
            # Suggestions are canonical text evidence. Interactive controls stay
            # disabled until a separately supported command/resume contract exists.
            suggested_actions=tuple(response.next_actions),
            interactive_actions=(),
        )
        return CognitiveProductResponse(
            cognitive_response=response,
            presentation=presentation,
            metadata=dict(metadata or {}),
        )


def transport_failure_product_response(
    text: str,
    *,
    error_code: str,
) -> dict[str, Any]:
    """Create an explicit product contract from observed transport failure."""

    response = CognitiveResponse(
        text=text,
        status=ResponseStatus.FAILED,
        execution_mode="FAILED",
        epistemic_status="unknown",
        confidence=0.5,
        response_origin=ResponseOrigin.SYSTEM,
        limitations=[error_code],
    )
    return CognitiveProductPresenter.present(
        response,
        metadata={
            "error_code": error_code,
            "transport_failure": True,
        },
    ).to_dict()
