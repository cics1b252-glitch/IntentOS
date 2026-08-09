"""Canonical Ports for Intent OS v2.0."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from intent_kernel.contracts.models import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    AgentId,
    AgentLimits,
    AgentRequest,
    ConstitutionVerdict,
    KnowledgeEvent,
    Mission,
    MissionId,
    ProviderRequest,
    ProviderResponse,
)


@runtime_checkable
class KnowledgeStore(Protocol):
    async def append(self, event: KnowledgeEvent) -> str: ...

    async def get(self, event_id: str) -> KnowledgeEvent | None: ...

    async def query(self, filters: dict[str, Any] | None = None) -> list[KnowledgeEvent]: ...

    async def update(self, event: KnowledgeEvent) -> bool: ...

    async def delete(self, event_id: str) -> bool: ...

    async def count(self, filters: dict[str, Any] | None = None) -> int: ...

    async def snapshot(self, event_id: str) -> Any | None: ...

    async def rollback(self, snapshot_id: str) -> bool: ...

    async def export(self) -> bytes: ...

    async def delete_all(self) -> bool: ...

    async def health(self) -> bool: ...


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> set[str]: ...

    async def execute(self, request: ProviderRequest) -> ProviderResponse: ...

    async def health(self) -> bool: ...


@runtime_checkable
class MissionStore(Protocol):
    async def save(self, mission: Mission) -> None: ...

    async def get(self, mission_id: MissionId) -> Mission | None: ...

    async def delete(self, mission_id: MissionId) -> bool: ...

    async def list_active(self) -> list[Mission]: ...


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(
        self,
        event_type: str,
        payload: Any = None,
        *,
        correlation_id: str = "",
    ) -> None: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    async def get(self, key: tuple[str, str, str]) -> Any | None: ...

    async def save(
        self,
        key: tuple[str, str, str],
        value: Any,
    ) -> None: ...


@runtime_checkable
class CapabilityExecutor(Protocol):
    @property
    def capabilities(self) -> tuple[Capability, ...]: ...

    async def execute(
        self,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult: ...


@runtime_checkable
class CoreApp(Protocol):
    """The only contract required of an Intent OS Core App."""

    @property
    def app_id(self) -> str: ...

    @property
    def capabilities(self) -> tuple[Capability, ...]: ...

    async def execute(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResult: ...

    async def health(self) -> bool: ...


@runtime_checkable
class Agent(Protocol):
    @property
    def agent_id(self) -> AgentId: ...

    @property
    def capabilities(self) -> tuple[Capability, ...]: ...

    @property
    def limits(self) -> AgentLimits: ...

    async def execute(
        self,
        request: AgentRequest,
    ) -> CapabilityResult: ...


@runtime_checkable
class ConstitutionEngine(Protocol):
    async def evaluate(
        self,
        action: str,
        data: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ConstitutionVerdict: ...
