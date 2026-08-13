"""Canonical user-visible response contract and governed assembler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ResponseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    WAITING_CONTEXT = "WAITING_CONTEXT"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    EXTERNAL_RESOURCE_REQUIRED = "EXTERNAL_RESOURCE_REQUIRED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FAILED = "FAILED"


@dataclass(slots=True)
class CognitiveResponse:
    text: str
    status: ResponseStatus
    execution_mode: str
    epistemic_status: str
    confidence: float
    provider: str | None = None
    provider_called: bool = False
    resource_provenance: list[str] = field(default_factory=list)
    mission_id: str | None = None
    verification_evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    authorization_requirements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


class CognitiveResponseAssembler:
    """Creates normalized responses and applies the canonical output policy."""

    def __init__(self, constitution: Any) -> None:
        self.constitution = constitution

    @staticmethod
    def from_result(
        result: dict[str, Any], *, default_execution_mode: str = "CONVERSATION"
    ) -> CognitiveResponse:
        """Translate a service/compatibility result into the canonical envelope.

        Upstream services retain ownership of their text and evidence.  Status,
        epistemic defaults and provider attribution are normalized here so an
        interface adapter cannot independently invent their product meaning.
        """
        raw = dict(result)
        raw_status = str(raw.get("status", "COMPLETED")).upper()
        aliases = {
            "CONCLUÍDO": "COMPLETED",
            "CONCLUIDO": "COMPLETED",
            "WAITING_USER_CONFIRMATION": "WAITING_CONFIRMATION",
        }
        raw_status = aliases.get(raw_status, raw_status)
        try:
            status = ResponseStatus(raw_status)
        except ValueError:
            status = (
                ResponseStatus.FAILED
                if not raw.get("ok", True)
                else ResponseStatus.COMPLETED
            )

        provider_called = bool(raw.get("provider_called", False))
        provider = raw.get("provider")
        provenance = list(raw.get("resource_provenance", []))
        if provider_called and provider:
            provider_ref = f"provider:{provider}"
            if provider_ref not in provenance:
                provenance.append(provider_ref)

        epistemic_default = {
            ResponseStatus.UNKNOWN: "unknown",
            ResponseStatus.EXTERNAL_RESOURCE_REQUIRED: "unknown",
            ResponseStatus.BLOCKED: "fact",
            ResponseStatus.AUTHORIZATION_REQUIRED: "fact",
            ResponseStatus.WAITING_CONFIRMATION: "fact",
            ResponseStatus.FAILED: "unknown",
        }.get(status, "conclusion")
        confidence_default = (
            1.0
            if status in {
                ResponseStatus.UNKNOWN,
                ResponseStatus.BLOCKED,
                ResponseStatus.AUTHORIZATION_REQUIRED,
                ResponseStatus.EXTERNAL_RESOURCE_REQUIRED,
                ResponseStatus.WAITING_CONFIRMATION,
            }
            else 0.5
        )
        return CognitiveResponse(
            text=str(raw.get("text") or raw.get("error") or ""),
            status=status,
            execution_mode=str(
                raw.get("execution_mode") or default_execution_mode
            ),
            epistemic_status=str(
                raw.get("epistemic_status", epistemic_default)
            ),
            confidence=float(raw.get("confidence", confidence_default)),
            provider=provider,
            provider_called=provider_called,
            resource_provenance=provenance,
            mission_id=raw.get("mission_id"),
            verification_evidence=list(raw.get("verification_evidence", [])),
            limitations=list(raw.get("limitations", [])),
            missing_capabilities=list(raw.get("missing_capabilities", [])),
            authorization_requirements=list(
                raw.get("authorization_requirements", [])
            ),
            next_actions=list(raw.get("next_actions", [])),
        )

    async def assemble(self, response: CognitiveResponse, context: dict[str, Any]) -> CognitiveResponse:
        verdict = await self.constitution.evaluate(
            "response.output", response.to_dict(), dict(context)
        )
        if verdict.allowed:
            return response
        return CognitiveResponse(
            text=f"Resposta bloqueada pela Constitution: {verdict.reason}",
            status=ResponseStatus.BLOCKED,
            execution_mode="BLOCKED",
            epistemic_status="fact",
            confidence=1.0,
            limitations=[verdict.reason],
        )
