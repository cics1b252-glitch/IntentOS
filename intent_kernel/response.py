"""Canonical user-visible response contract and governed assembler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ResponseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    WAITING_CONTEXT = "WAITING_CONTEXT"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    EXTERNAL_RESOURCE_REQUIRED = "EXTERNAL_RESOURCE_REQUIRED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FAILED = "FAILED"


SUCCESSFUL_RESPONSE_STATUSES = frozenset({ResponseStatus.COMPLETED})


def response_status_is_ok(status: ResponseStatus) -> bool:
    """Return whether the canonical outcome fulfilled the user-visible request."""

    return status in SUCCESSFUL_RESPONSE_STATUSES


@dataclass(frozen=True, slots=True)
class CanonicalOutcomeSemantics:
    """Deterministic epistemic contract for a canonical product status."""

    epistemic_status: str
    confidence: float


CANONICAL_OUTCOME_SEMANTICS: Mapping[
    ResponseStatus, CanonicalOutcomeSemantics
] = MappingProxyType(
    {
        ResponseStatus.COMPLETED: CanonicalOutcomeSemantics("conclusion", 0.5),
        ResponseStatus.WAITING_CONTEXT: CanonicalOutcomeSemantics("conclusion", 0.5),
        ResponseStatus.UNKNOWN: CanonicalOutcomeSemantics("unknown", 1.0),
        ResponseStatus.BLOCKED: CanonicalOutcomeSemantics("fact", 1.0),
        ResponseStatus.AUTHORIZATION_REQUIRED: CanonicalOutcomeSemantics("fact", 1.0),
        ResponseStatus.EXTERNAL_RESOURCE_REQUIRED: CanonicalOutcomeSemantics(
            "unknown", 1.0
        ),
        ResponseStatus.WAITING_CONFIRMATION: CanonicalOutcomeSemantics("fact", 1.0),
        ResponseStatus.FAILED: CanonicalOutcomeSemantics("unknown", 0.5),
    }
)


def canonical_outcome_semantics(status: ResponseStatus) -> CanonicalOutcomeSemantics:
    """Return Python-owned epistemic semantics for product contract 1.0."""

    return CANONICAL_OUTCOME_SEMANTICS[status]


class CanonicalResultKind(str, Enum):
    """Typed outcome emitted by a canonical runtime owner.

    This is deliberately smaller than :class:`CognitiveResponse`: callers
    describe what actually happened and the assembler alone derives the
    user-visible semantic envelope.
    """

    LOCAL_RESPONSE = "LOCAL_RESPONSE"
    CONVERSATION = "CONVERSATION"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    EXTERNAL_RESOURCE_REQUIRED = "EXTERNAL_RESOURCE_REQUIRED"
    WAITING_CONTEXT = "WAITING_CONTEXT"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    FAILED = "FAILED"


class ResponseOrigin(str, Enum):
    """Canonical origin of response evidence, independent of visible status."""

    COGNITIVE_RUNTIME = "COGNITIVE_RUNTIME"
    LOCAL_RESPONSE = "LOCAL_RESPONSE"
    CONVERSATION = "CONVERSATION"
    MEMORY = "MEMORY"
    MISSION = "MISSION"
    PROVIDER = "PROVIDER"
    SYSTEM = "SYSTEM"
    LEGACY_COMPATIBILITY = "LEGACY_COMPATIBILITY"


@dataclass(frozen=True, slots=True)
class ProviderInvocationEvidence:
    """Observed provider invocation, not provider preference/configuration."""

    provider_id: str
    invoked: bool
    resource_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalTurnResult:
    """Non-presentational evidence consumed by CognitiveResponseAssembler."""

    text: str
    kind: CanonicalResultKind
    origin: ResponseOrigin | None = None
    local_source: bool = False
    provider_evidence: ProviderInvocationEvidence | None = None
    mission_id: str | None = None
    verification_evidence: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    authorization_requirements: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_cognitive_decision(cls, decision: Any) -> CanonicalTurnResult | None:
        """Create a terminal result from authoritative cognitive evidence."""
        mode = str(getattr(getattr(decision, "mode", None), "value", ""))
        mapping = {
            "UNKNOWN": (
                CanonicalResultKind.UNKNOWN,
                "Não há capacidade ou recurso elegível suficiente para atender esta solicitação com segurança.",
            ),
            "BLOCKED": (
                CanonicalResultKind.BLOCKED,
                "A solicitação foi bloqueada pela Constitution.",
            ),
            "AUTHORIZATION_REQUIRED": (
                CanonicalResultKind.AUTHORIZATION_REQUIRED,
                "Esta ação exige autorização explícita antes de qualquer execução.",
            ),
            "EXTERNAL_REASONING_REQUIRED": (
                CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED,
                "Não tenho conhecimento local suficiente e não há Provider externo elegível conectado.",
            ),
        }
        outcome = mapping.get(mode)
        if outcome is None:
            return None
        kind, text = outcome
        composition = getattr(decision, "composition", None)
        return cls(
            text=text,
            kind=kind,
            origin=ResponseOrigin.COGNITIVE_RUNTIME,
            missing_capabilities=tuple(
                getattr(composition, "missing_capabilities", ()) or ()
            ),
            authorization_requirements=tuple(
                getattr(composition, "authorization_requirements", ()) or ()
            ),
            metadata={
                "domain": getattr(decision, "domain_hint", "general"),
                "capability_analysis": decision.to_dict(),
            },
        )

    @classmethod
    def local(
        cls,
        text: str,
        *,
        kind: CanonicalResultKind = CanonicalResultKind.LOCAL_RESPONSE,
        metadata: Mapping[str, Any] | None = None,
        limitations: tuple[str, ...] = (),
        missing_capabilities: tuple[str, ...] = (),
        authorization_requirements: tuple[str, ...] = (),
        next_actions: tuple[str, ...] = (),
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=kind,
            origin=ResponseOrigin.LOCAL_RESPONSE,
            local_source=True,
            limitations=limitations,
            missing_capabilities=missing_capabilities,
            authorization_requirements=authorization_requirements,
            next_actions=next_actions,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def blocked(
        cls,
        text: str,
        *,
        reason: str,
        mission_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=CanonicalResultKind.BLOCKED,
            origin=ResponseOrigin.COGNITIVE_RUNTIME,
            local_source=True,
            mission_id=mission_id,
            limitations=(reason,),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def memory(
        cls,
        text: str,
        *,
        found: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=(
                CanonicalResultKind.LOCAL_RESPONSE
                if found
                else CanonicalResultKind.UNKNOWN
            ),
            origin=ResponseOrigin.MEMORY,
            local_source=True,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def waiting_context(
        cls, text: str, *, metadata: Mapping[str, Any] | None = None
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=CanonicalResultKind.WAITING_CONTEXT,
            origin=ResponseOrigin.CONVERSATION,
            local_source=True,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def provider(
        cls,
        text: str,
        *,
        provider_id: str | None,
        invoked: bool,
        resource_ids: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        evidence = (
            ProviderInvocationEvidence(provider_id, invoked, resource_ids)
            if provider_id
            else None
        )
        return cls(
            text=text,
            kind=CanonicalResultKind.CONVERSATION,
            origin=ResponseOrigin.PROVIDER,
            # This constructor represents a provider-path result. Local
            # cognitive sources use ``local()``; absence of invocation evidence
            # means no provider attribution rather than "provider=local".
            local_source=False,
            provider_evidence=evidence,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def mission(
        cls,
        text: str,
        *,
        kind: CanonicalResultKind,
        mission_id: str,
        verification_evidence: tuple[dict[str, Any], ...] = (),
        authorization_requirements: tuple[str, ...] = (),
        next_actions: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=kind,
            origin=ResponseOrigin.MISSION,
            local_source=True,
            mission_id=mission_id,
            verification_evidence=verification_evidence,
            authorization_requirements=authorization_requirements,
            next_actions=next_actions,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_mission_authorization(
        cls,
        boundary: Any,
        *,
        mission_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        decision = str(getattr(getattr(boundary, "decision", None), "value", ""))
        kind_by_decision = {
            "DENY": CanonicalResultKind.BLOCKED,
            "REQUEST_PERMISSION": CanonicalResultKind.AUTHORIZATION_REQUIRED,
            "REQUEST_CONFIRMATION": CanonicalResultKind.WAITING_CONFIRMATION,
            "WAIT_TOOL": CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED,
            "RESELECT_TOOL": CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED,
        }
        if decision not in kind_by_decision:
            raise ValueError(f"authorization state is not a waiting result: {decision}")
        return cls.mission(
            str(boundary.text),
            kind=kind_by_decision[decision],
            mission_id=mission_id,
            authorization_requirements=tuple(
                getattr(boundary, "authorization_requirements", ()) or ()
            ),
            next_actions=tuple(getattr(boundary, "next_actions", ()) or ()),
            metadata=metadata,
        )

    @classmethod
    def waiting_confirmation(
        cls,
        text: str,
        *,
        mission_id: str,
        verification_evidence: tuple[dict[str, Any], ...] = (),
        authorization_requirements: tuple[str, ...] = (),
        next_actions: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        return cls.mission(
            text,
            kind=CanonicalResultKind.WAITING_CONFIRMATION,
            mission_id=mission_id,
            verification_evidence=verification_evidence,
            authorization_requirements=authorization_requirements,
            next_actions=next_actions,
            metadata=metadata,
        )

    @classmethod
    def failed(
        cls,
        text: str,
        *,
        provider_id: str | None = None,
        provider_invoked: bool = False,
        mission_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalTurnResult:
        return cls(
            text=text,
            kind=CanonicalResultKind.FAILED,
            origin=(
                ResponseOrigin.PROVIDER
                if provider_id
                else ResponseOrigin.MISSION
                if mission_id
                else ResponseOrigin.SYSTEM
            ),
            provider_evidence=(
                ProviderInvocationEvidence(provider_id, provider_invoked)
                if provider_id
                else None
            ),
            mission_id=mission_id,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class CognitiveResponse:
    text: str
    status: ResponseStatus
    execution_mode: str
    epistemic_status: str
    confidence: float
    response_origin: ResponseOrigin = ResponseOrigin.SYSTEM
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
        value["response_origin"] = self.response_origin.value
        value["ok"] = response_status_is_ok(self.status)
        return value


class CognitiveResponseAssembler:
    """Creates normalized responses and applies the canonical output policy."""

    def __init__(self, constitution: Any) -> None:
        self.constitution = constitution

    @staticmethod
    def from_result(
        result: CanonicalTurnResult | dict[str, Any],
        *,
        default_execution_mode: str = "CONVERSATION",
    ) -> CognitiveResponse:
        """Translate typed runtime evidence into the canonical envelope.

        Dictionaries remain accepted only for direct legacy callers. Product
        adapters use :class:`CanonicalTurnResult`, so their raw fields cannot
        redefine canonical status, epistemology, confidence, Mission meaning,
        or provider provenance.
        """
        if isinstance(result, CanonicalTurnResult):
            canonical = result
        else:
            # Compatibility-only adapter for callers outside ProductBridge.
            raw = dict(result)
            raw_status = str(raw.get("status", "COMPLETED")).upper()
            aliases = {
                "CONCLUÍDO": CanonicalResultKind.CONVERSATION,
                "CONCLUIDO": CanonicalResultKind.CONVERSATION,
                "COMPLETED": CanonicalResultKind.CONVERSATION,
                "WAITING_USER_CONFIRMATION": CanonicalResultKind.WAITING_CONFIRMATION,
            }
            try:
                kind = CanonicalResultKind(aliases.get(raw_status, raw_status))
            except ValueError:
                kind = (
                    CanonicalResultKind.FAILED
                    if not raw.get("ok", True)
                    else CanonicalResultKind.CONVERSATION
                )
            provider_id = raw.get("provider")
            invoked = bool(raw.get("provider_called", False))
            canonical = CanonicalTurnResult(
                text=str(raw.get("text") or raw.get("error") or ""),
                kind=kind,
                origin=(
                    ResponseOrigin(str(raw["response_origin"]))
                    if raw.get("response_origin") in {item.value for item in ResponseOrigin}
                    else ResponseOrigin.LEGACY_COMPATIBILITY
                ),
                local_source=provider_id == "local" and not invoked,
                provider_evidence=(
                    ProviderInvocationEvidence(
                        str(provider_id), invoked,
                        tuple(raw.get("resource_provenance", ())),
                    )
                    if provider_id
                    else None
                ),
                mission_id=raw.get("mission_id"),
                verification_evidence=tuple(raw.get("verification_evidence", ())),
                limitations=tuple(raw.get("limitations", ())),
                missing_capabilities=tuple(raw.get("missing_capabilities", ())),
                authorization_requirements=tuple(
                    raw.get("authorization_requirements", ())
                ),
                next_actions=tuple(raw.get("next_actions", ())),
            )

        status_by_kind = {
            CanonicalResultKind.LOCAL_RESPONSE: ResponseStatus.COMPLETED,
            CanonicalResultKind.CONVERSATION: ResponseStatus.COMPLETED,
            CanonicalResultKind.UNKNOWN: ResponseStatus.UNKNOWN,
            CanonicalResultKind.BLOCKED: ResponseStatus.BLOCKED,
            CanonicalResultKind.AUTHORIZATION_REQUIRED: ResponseStatus.AUTHORIZATION_REQUIRED,
            CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED: ResponseStatus.EXTERNAL_RESOURCE_REQUIRED,
            CanonicalResultKind.WAITING_CONTEXT: ResponseStatus.WAITING_CONTEXT,
            CanonicalResultKind.WAITING_CONFIRMATION: ResponseStatus.WAITING_CONFIRMATION,
            CanonicalResultKind.MISSION_COMPLETED: ResponseStatus.COMPLETED,
            CanonicalResultKind.FAILED: ResponseStatus.FAILED,
        }
        status = status_by_kind[canonical.kind]
        mode_by_kind = {
            CanonicalResultKind.LOCAL_RESPONSE: "LOCAL_RESPONSE",
            CanonicalResultKind.CONVERSATION: "CONVERSATION",
            CanonicalResultKind.UNKNOWN: "UNKNOWN",
            CanonicalResultKind.BLOCKED: "BLOCKED",
            CanonicalResultKind.AUTHORIZATION_REQUIRED: "AUTHORIZATION_REQUIRED",
            CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED: "EXTERNAL_REASONING_REQUIRED",
            CanonicalResultKind.WAITING_CONTEXT: "CONVERSATION",
            CanonicalResultKind.WAITING_CONFIRMATION: "MISSION",
            CanonicalResultKind.MISSION_COMPLETED: "MISSION",
            CanonicalResultKind.FAILED: "FAILED",
        }
        execution_mode = mode_by_kind.get(canonical.kind, default_execution_mode)
        origin = canonical.origin or {
            CanonicalResultKind.LOCAL_RESPONSE: ResponseOrigin.LOCAL_RESPONSE,
            CanonicalResultKind.CONVERSATION: ResponseOrigin.CONVERSATION,
            CanonicalResultKind.WAITING_CONTEXT: ResponseOrigin.CONVERSATION,
            CanonicalResultKind.WAITING_CONFIRMATION: ResponseOrigin.MISSION,
            CanonicalResultKind.MISSION_COMPLETED: ResponseOrigin.MISSION,
        }.get(canonical.kind, ResponseOrigin.COGNITIVE_RUNTIME)

        evidence = canonical.provider_evidence
        provider_called = bool(evidence and evidence.invoked)
        provider = evidence.provider_id if evidence else (
            "local" if canonical.local_source else None
        )
        provenance = list(evidence.resource_ids if evidence else ())
        if provider_called and provider:
            provider_ref = f"provider:{provider}"
            if provider_ref not in provenance:
                provenance.append(provider_ref)

        outcome_semantics = canonical_outcome_semantics(status)
        return CognitiveResponse(
            text=canonical.text,
            status=status,
            execution_mode=execution_mode,
            epistemic_status=outcome_semantics.epistemic_status,
            confidence=outcome_semantics.confidence,
            response_origin=origin,
            provider=provider,
            provider_called=provider_called,
            resource_provenance=provenance,
            mission_id=canonical.mission_id,
            verification_evidence=list(canonical.verification_evidence),
            limitations=list(canonical.limitations),
            missing_capabilities=list(canonical.missing_capabilities),
            authorization_requirements=list(canonical.authorization_requirements),
            next_actions=list(canonical.next_actions),
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
            response_origin=ResponseOrigin.COGNITIVE_RUNTIME,
            limitations=[verdict.reason],
        )
