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
