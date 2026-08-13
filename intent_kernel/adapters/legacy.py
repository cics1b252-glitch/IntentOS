"""Compatibility adapters around the current Sprint 0 implementation.

No legacy logic is migrated here. Adapters only translate contracts.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from intent_kernel.compatibility import attach_compatibility_trace, compatibility_trace

from intent_kernel.contracts import (
    AgentId,
    AgentLimits,
    AgentRequest,
    Capability,
    CapabilityResult,
    ConstitutionDecision,
    ConstitutionVerdict,
    Domain,
    EffectType,
    ErrorCode,
    KnowledgeEvent,
    KnowledgeLifecycle,
    Mission,
    MissionContext,
    MissionId,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
)


class LegacyProviderAdapter:
    def __init__(self, provider: Any):
        self._provider = provider

    @property
    def name(self) -> str:
        return str(self._provider.name)

    @property
    def capabilities(self) -> set[str]:
        return {"text_completion"}

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        from intent_kernel.types import Message

        legacy_messages = [
            Message(role=message.role, content=message.content)
            for message in request.messages
        ]
        result = await self._provider.complete(
            legacy_messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        response = ProviderResponse(
            text=result.text,
            provider=self.name,
            model=result.model,
            usage=dict(result.usage),
            finish_reason=result.finish_reason,
        )
        attach_compatibility_trace(
            response.metadata,
            compatibility_trace(
                "LegacyProviderAdapter",
                "legacy_provider_invocation_binding",
                entry_point="LegacyProviderAdapter.execute",
                canonical_alternative_missing="native_provider_binding",
            ),
        )
        return response

    async def health(self) -> bool:
        return bool(await self._provider.health_check())


class LegacyEventPublisherAdapter:
    def __init__(self, event_bus: Any):
        self._event_bus = event_bus

    async def publish(
        self,
        event_type: str,
        payload: Any = None,
        *,
        correlation_id: str = "",
    ) -> None:
        data = payload
        if correlation_id:
            data = {
                "payload": payload,
                "correlation_id": correlation_id,
            }
        await self._event_bus.publish(event_type, data)


class LegacyConstitutionEngineAdapter:
    def __init__(self, constitution: Any):
        self._constitution = constitution

    async def evaluate(
        self,
        action: str,
        data: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ConstitutionVerdict:
        from intent_kernel.types import Action

        legacy = self._constitution.validate(Action(type=action, data=data))
        decision = (
            ConstitutionDecision.ALLOW
            if legacy.allowed
            else ConstitutionDecision.DENY
        )
        return ConstitutionVerdict(
            decision=decision,
            reason=legacy.reason or "",
            violated_rule=legacy.violated_constraint,
            constitution_version=self._constitution.version,
            metadata={"legacy_context": deepcopy(context or {})},
        )


class LegacyGuardianAdapter:
    """Expose an official Guardian through the historical Guardian API."""

    def __init__(self, guardian: Any):
        self._guardian = guardian

    @property
    def name(self) -> str:
        return str(self._guardian.name)

    @property
    def description(self) -> str:
        return str(self._guardian.responsibility)

    @property
    def principle(self) -> str:
        return str(self._guardian.responsibility)

    def validate(
        self,
        event: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:
        from intent_kernel.constitution.canonical import GovernanceRequest
        from intent_kernel.constitution.guardians import GuardianVerdict

        result = self._guardian.evaluate(
            GovernanceRequest(
                action=str((context or {}).get("action", "knowledge.ingest")),
                data=event,
                context=deepcopy(context or {}),
            )
        )
        if result.decision is ConstitutionDecision.DENY:
            decision = "blocked"
        elif result.decision is ConstitutionDecision.ALLOW_WITH_CONDITIONS:
            decision = "flagged"
        else:
            decision = "allowed"
        return GuardianVerdict(
            guardian=result.guardian,
            decision=decision,
            reason=result.reason,
            details={
                "rule": result.rule,
                "evidence": deepcopy(result.evidence),
            },
        )

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "active": True,
            "adapter": "canonical",
        }


class LegacyKnowledgeStoreAdapter:
    def __init__(self, store: Any):
        self._store = store

    async def append(self, event: KnowledgeEvent) -> str:
        return await self._store.append(to_legacy_knowledge_event(event))

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        event = await self._store.get(event_id)
        return from_legacy_knowledge_event(event) if event is not None else None

    async def query(
        self,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeEvent]:
        from intent_kernel.types import QueryFilters

        allowed = set(QueryFilters.__dataclass_fields__)
        normalized = {
            key: value
            for key, value in (filters or {}).items()
            if key in allowed
        }
        events = await self._store.query(QueryFilters(**normalized))
        return [from_legacy_knowledge_event(event) for event in events]

    async def update(self, event: KnowledgeEvent) -> bool:
        return bool(await self._store.update(to_legacy_knowledge_event(event)))

    async def delete(self, event_id: str) -> bool:
        return bool(await self._store.delete(event_id))

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        if not filters:
            return int(await self._store.count())
        return len(await self.query(filters))

    async def snapshot(self, event_id: str) -> Any | None:
        return await self._store.version_snapshot(event_id)

    async def rollback(self, snapshot_id: str) -> bool:
        return bool(await self._store.rollback(snapshot_id))

    async def export(self) -> bytes:
        return await self._store.export_all()

    async def delete_all(self) -> bool:
        return bool(await self._store.delete_all())

    async def health(self) -> bool:
        return self._store.base_path.exists()


class LegacyCapabilityExecutorAdapter:
    def __init__(
        self,
        router: Any,
        *,
        mission_engine: Any = None,
        execution_service: Any = None,
        telemetry: Any = None,
    ):
        self._router = router
        self._mission_engine = mission_engine
        self._execution_service = execution_service
        self._telemetry = telemetry

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            Capability(name=name, description=f"Legacy module: {name}")
            for name in self._router.registered_modules
        )

    async def execute(
        self,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        domain_value = str(payload.get("domain", Domain.OTHER.value))
        canonical_domain = _canonical_domain(domain_value)
        canonical_capability = {
            Domain.FINANCE: "finance.intent",
            Domain.RESEARCH: "knowledge.intent",
            Domain.WRITING: "knowledge.intent",
            Domain.PLANNING: "knowledge.intent",
            Domain.EDUCATION: "knowledge.intent",
            Domain.ENGINEERING: "engineering.intent",
            Domain.PROGRAMMING: "engineering.intent",
        }.get(canonical_domain)
        if (
            canonical_capability is not None
            and self._mission_engine is not None
            and self._execution_service is not None
        ):
            mission = await self._mission_engine.create(
                str(payload.get("text", canonical_capability)),
                context=MissionContext(
                    domain=canonical_domain,
                    values=deepcopy(context or {}),
                ),
            )
            mission = await self._mission_engine.start(mission.id)
            outcome = await self._execution_service.execute(
                mission.id,
                canonical_capability,
                payload=payload,
                context=context,
            )
            # Compatibility execution cannot complete the canonical lifecycle.
            # Its output awaits MissionRuntime verification and the canonical
            # MissionCompletionGate decision.
            await self._mission_engine.await_verification(mission.id)
            outcome.result.metadata.setdefault(
                "mission_lifecycle_status", "verifying"
            )
            outcome.result.metadata.setdefault(
                "completion_authority", "MissionCompletionGate"
            )
            outcome.result.metadata.setdefault(
                "compatibility_path_used", True
            )
            trace = compatibility_trace(
                "LegacyCapabilityExecutorAdapter",
                "legacy_domain_was_translated_to_canonical_capability",
                entry_point="LegacyCapabilityExecutorAdapter.execute.canonical",
                canonical_alternative_missing="native_capability_request",
            )
            attach_compatibility_trace(outcome.result.metadata, trace)
            if self._telemetry is not None:
                self._telemetry.record_legacy(
                    "LegacyCapabilityExecutorAdapter"
                )
                self._telemetry.record_compatibility(trace)
            return outcome.result

        from intent_kernel.types import Domain as LegacyDomain
        from intent_kernel.types import IntentInput

        module = self._router.get_module(capability)
        if module is None:
            return CapabilityResult(
                capability=capability,
                success=False,
                error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
            )
        try:
            legacy_domain = LegacyDomain(domain_value)
        except ValueError:
            legacy_domain = LegacyDomain.OTHER
        intent = IntentInput(
            text=str(payload.get("text", "")),
            context=deepcopy(context or {}),
            domain=legacy_domain,
        )
        result = await module.execute(intent, context)
        metadata = {"legacy_result": result}
        trace = compatibility_trace(
            "LegacyCapabilityExecutorAdapter",
            "direct_legacy_module_execution",
            entry_point="LegacyCapabilityExecutorAdapter.execute.direct",
            canonical_alternative_missing="canonical_capability_binding",
        )
        attach_compatibility_trace(metadata, trace)
        if self._telemetry is not None:
            self._telemetry.record_legacy("LegacyCapabilityExecutorAdapter")
            self._telemetry.record_compatibility(trace)
        return CapabilityResult(
            capability=capability,
            success=True,
            output=result.get("text", result),
            confidence=float(result.get("confidence", 0.0)),
            metadata=metadata,
        )


class LegacyAgentAdapter:
    def __init__(self, agent: Any):
        self._agent = agent

    @property
    def agent_id(self) -> AgentId:
        return AgentId(str(self._agent.agent_id))

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            Capability(
                name=item.name,
                description=item.description,
                domains=tuple(
                    _canonical_domain(value)
                    for value in item.domains
                ),
                tags=("legacy_agent", str(self.agent_id)),
                effect=EffectType.GENERATE,
            )
            for item in self._agent.capabilities
        )

    @property
    def limits(self) -> AgentLimits:
        return AgentLimits()

    async def execute(
        self,
        request: AgentRequest | str,
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        if isinstance(request, AgentRequest):
            task = request.task
            execution_context = request.context
            capability = request.capability
        else:
            task = request
            execution_context = context or {}
            capability = str(self.agent_id)
        result = await self._agent.process(task, execution_context)
        metadata = {
            "agent_id": str(self.agent_id),
            "domain": result.domain,
            "events_created": result.events_created,
        }
        attach_compatibility_trace(
            metadata,
            compatibility_trace(
                "LegacyAgentAdapter",
                "legacy_agent_invocation_binding",
                entry_point="LegacyAgentAdapter.execute",
                canonical_alternative_missing="canonical_agent_binding",
            ),
        )
        return CapabilityResult(
            capability=capability,
            success=True,
            output=result.content,
            confidence=result.confidence,
            metadata=metadata,
        )


class InMemoryMissionStoreAdapter:
    """Non-production MissionStore used until a legacy mission store exists."""

    def __init__(self):
        self._missions: dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._missions[str(mission.id)] = deepcopy(mission)

    async def get(self, mission_id: MissionId) -> Mission | None:
        mission = self._missions.get(str(mission_id))
        return deepcopy(mission) if mission is not None else None

    async def delete(self, mission_id: MissionId) -> bool:
        return self._missions.pop(str(mission_id), None) is not None

    async def list_active(self) -> list[Mission]:
        terminal = {"completed", "cancelled", "failed_final"}
        return [
            deepcopy(mission)
            for mission in self._missions.values()
            if mission.status.value not in terminal
        ]


class InMemoryIdempotencyStoreAdapter:
    """Injected non-durable idempotency store for canonical execution."""

    def __init__(self):
        self._values: dict[tuple[str, str, str], Any] = {}

    async def get(self, key: tuple[str, str, str]) -> Any | None:
        value = self._values.get(key)
        return deepcopy(value) if value is not None else None

    async def save(
        self,
        key: tuple[str, str, str],
        value: Any,
    ) -> None:
        self._values[key] = deepcopy(value)


def to_legacy_knowledge_event(event: KnowledgeEvent) -> Any:
    from intent_kernel.pkb.models import (
        KnowledgeEvent as LegacyKnowledgeEvent,
        LifecycleTransition,
    )
    from intent_kernel.types import Domain as LegacyDomain
    from intent_kernel.types import EpistemicStatus, EventLifecycle, EventType

    try:
        event_type = EventType(event.event_type)
    except ValueError:
        event_type = EventType.EVENT
    try:
        lifecycle = EventLifecycle(event.lifecycle.value)
    except ValueError:
        lifecycle = EventLifecycle.TRANSIENT
    return LegacyKnowledgeEvent(
        id=event.id,
        type=event_type,
        domain=LegacyDomain(event.domain.value),
        title=event.title,
        content=deepcopy(event.content),
        summary=event.summary,
        confidence=event.confidence,
        epistemic_status=EpistemicStatus(event.epistemic_status),
        lifecycle=lifecycle,
        version=event.version,
        parent_event_id=event.parent_event_id,
        root_event_id=event.root_event_id,
        source=event.source,
        session_id=event.session_id,
        tags=list(event.tags),
        metadata=deepcopy(event.metadata),
        lifecycle_history=[
            LifecycleTransition(
                from_status=_legacy_lifecycle(
                    item["from_status"],
                    EventLifecycle,
                ),
                to_status=_legacy_lifecycle(
                    item["to_status"],
                    EventLifecycle,
                ),
                reason=item.get("reason", ""),
                timestamp=item.get("timestamp", event.updated_at),
            )
            for item in event.lifecycle_history
        ],
        created_at=event.created_at,
        updated_at=event.updated_at,
        expires_at=event.expires_at,
    )


def _legacy_lifecycle(value: str, enum_type: Any) -> Any:
    """Map canonical-only states to the closest legacy lifecycle."""
    try:
        return enum_type(value)
    except ValueError:
        if value in {"observed", "rejected", "deleted"}:
            return enum_type.TRANSIENT
        if value in {"archived", "merged", "superseded"}:
            return enum_type.APPROVED
        return enum_type.TRANSIENT


def _canonical_domain(value: str) -> Domain:
    aliases = {
        "knowledge": Domain.RESEARCH,
        "finance": Domain.FINANCE,
        "engineering": Domain.ENGINEERING,
    }
    try:
        return Domain(value)
    except ValueError:
        return aliases.get(value, Domain.OTHER)


def from_legacy_knowledge_event(event: Any) -> KnowledgeEvent:
    try:
        lifecycle = KnowledgeLifecycle(event.lifecycle.value)
    except ValueError:
        lifecycle = KnowledgeLifecycle.OBSERVED
    mission_id = event.metadata.get("mission_id")
    return KnowledgeEvent(
        id=event.id,
        event_type=event.type.value,
        domain=Domain(event.domain.value),
        title=event.title,
        content=deepcopy(event.content),
        summary=event.summary,
        confidence=event.confidence,
        epistemic_status=event.epistemic_status.value,
        lifecycle=lifecycle,
        source=event.source,
        mission_id=MissionId(mission_id) if mission_id else None,
        session_id=event.session_id,
        correlation_id=event.metadata.get("correlation_id", ""),
        relations=list(event.metadata.get("relations", [])),
        tags=list(event.tags),
        metadata=deepcopy(event.metadata),
        lifecycle_history=[
            {
                "from_status": item.from_status.value,
                "to_status": item.to_status.value,
                "reason": item.reason,
                "timestamp": item.timestamp,
            }
            for item in event.lifecycle_history
        ],
        version=event.version,
        parent_event_id=event.parent_event_id,
        root_event_id=event.root_event_id,
        created_at=event.created_at,
        updated_at=event.updated_at,
        expires_at=event.expires_at,
    )
