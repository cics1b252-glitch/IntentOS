"""Canonical capability discovery and ownership registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from intent_kernel.contracts import (
    Agent,
    Capability,
    CoreApp,
    EffectType,
    Provider,
)


class ExecutorKind(str, Enum):
    CORE_APP = "core_app"
    AGENT = "agent"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    capability: Capability
    executor_kind: ExecutorKind
    executor_id: str
    executor: Any


class CanonicalCapabilityRegistry:
    """Single official registry for apps, agents and providers."""

    def __init__(self):
        self._registrations: dict[
            str,
            list[CapabilityRegistration],
        ] = {}

    def register(
        self,
        capability: Capability,
        *,
        executor_kind: ExecutorKind,
        executor_id: str,
        executor: Any,
    ) -> CapabilityRegistration:
        registration = CapabilityRegistration(
            capability=capability,
            executor_kind=executor_kind,
            executor_id=executor_id,
            executor=executor,
        )
        entries = self._registrations.setdefault(capability.name, [])
        if not any(
            item.executor_kind is executor_kind
            and item.executor_id == executor_id
            for item in entries
        ):
            entries.append(registration)
        return registration

    def register_core_app(self, app: CoreApp) -> None:
        for capability in app.capabilities:
            self.register(
                capability,
                executor_kind=ExecutorKind.CORE_APP,
                executor_id=app.app_id,
                executor=app,
            )

    def register_agent(self, agent: Agent) -> None:
        for capability in agent.capabilities:
            self.register(
                capability,
                executor_kind=ExecutorKind.AGENT,
                executor_id=str(agent.agent_id),
                executor=agent,
            )

    def register_provider(self, provider: Provider) -> None:
        for name in provider.capabilities:
            capability = Capability(
                name=f"provider.{name}",
                description=f"Provider capability: {name}",
                requires_network=provider.name != "mock",
                effect=EffectType.GENERATE,
            )
            self.register(
                capability,
                executor_kind=ExecutorKind.PROVIDER,
                executor_id=provider.name,
                executor=provider,
            )

    def discover(
        self,
        capability: str | None = None,
        *,
        executor_kind: ExecutorKind | None = None,
    ) -> list[CapabilityRegistration]:
        if capability is None:
            entries = [
                item
                for group in self._registrations.values()
                for item in group
            ]
        else:
            entries = list(self._registrations.get(capability, []))
        if executor_kind is not None:
            entries = [
                item
                for item in entries
                if item.executor_kind is executor_kind
            ]
        return entries

    def select(
        self,
        capability: str,
        *,
        preferred_kind: ExecutorKind | None = None,
    ) -> CapabilityRegistration | None:
        entries = self.discover(
            capability,
            executor_kind=preferred_kind,
        )
        return entries[0] if entries else None

    async def available(
        self,
        registration: CapabilityRegistration,
    ) -> bool:
        health = getattr(registration.executor, "health", None)
        if health is None:
            return True
        return bool(await health())

    def validate(self) -> list[str]:
        errors: list[str] = []
        for name, entries in self._registrations.items():
            if not name.strip():
                errors.append("Capability name cannot be empty")
            for item in entries:
                if item.capability.name != name:
                    errors.append(f"Registration mismatch for {name}")
                if not item.executor_id.strip():
                    errors.append(f"Missing executor for {name}")
        return errors

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        unique: dict[str, Capability] = {}
        for entries in self._registrations.values():
            for item in entries:
                unique.setdefault(item.capability.name, item.capability)
        return tuple(unique.values())
