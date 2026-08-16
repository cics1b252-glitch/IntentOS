"""Governed Agent Instantiation — Movement 15.

AGENT IS A GOVERNED EXECUTION PARTICIPANT. AGENT IS NOT SYSTEM AUTHORITY.

Movement 15 introduces the smallest canonical architecture for governed Agent
instantiation and lifecycle:

- CanonicalAgentFactory  (FACTORY_ONLY): instantiates governed agents. Creates
  zero default agents.
- CanonicalAgentRegistry (REGISTRY_ONLY): duplicate-identity rejection,
  fail-closed revocation, lookup. Presence in the registry is NOT authorization.
- GovernedAgent          (EXECUTION_PARTICIPANT): passive identity + lifecycle
  record bound to an explicit Mission. Output is evidence/input only.
- AgentSpec              (DERIVED): typed declaration. Declared capabilities are
  claims, never RRM availability or authorization. Unknown fields are rejected.
- AgentLifecycleState    (DERIVED): guarded lifecycle state machine.

The factory does not invent Missions, authorize, select resources, invoke
providers, execute productively during creation, complete Missions, fabricate
verification, or mutate a product response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from intent_kernel.contracts import AgentId
from intent_kernel.time_utils import utc_iso


class AgentLifecycleState(str, Enum):
    """Guarded lifecycle states for a governed agent (DERIVED)."""

    CREATED = "CREATED"
    READY = "READY"
    BOUND = "BOUND"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVOKED = "REVOKED"

    @property
    def terminal(self) -> bool:
        return self in {
            AgentLifecycleState.COMPLETED,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.REVOKED,
        }


_TRANSITIONS: dict[AgentLifecycleState, frozenset[AgentLifecycleState]] = {
    AgentLifecycleState.CREATED: frozenset(
        {AgentLifecycleState.READY, AgentLifecycleState.REVOKED}
    ),
    AgentLifecycleState.READY: frozenset(
        {AgentLifecycleState.BOUND, AgentLifecycleState.REVOKED}
    ),
    AgentLifecycleState.BOUND: frozenset(
        {
            AgentLifecycleState.RUNNING,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.REVOKED,
        }
    ),
    AgentLifecycleState.RUNNING: frozenset(
        {
            AgentLifecycleState.WAITING,
            AgentLifecycleState.COMPLETED,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.REVOKED,
        }
    ),
    AgentLifecycleState.WAITING: frozenset(
        {
            AgentLifecycleState.RUNNING,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.REVOKED,
        }
    ),
    AgentLifecycleState.COMPLETED: frozenset(),
    AgentLifecycleState.FAILED: frozenset(),
    AgentLifecycleState.REVOKED: frozenset(),
}


class AgentFactoryError(Exception):
    """Base error for governed agent factory operations."""


class InvalidAgentSpecError(AgentFactoryError):
    """Raised when an AgentSpec is malformed or unknown fields are present."""


class AgentIdentityError(AgentFactoryError):
    """Raised on duplicate identity, revoked use, or forbidden identity input."""


class AgentLifecycleError(AgentFactoryError):
    """Raised on forbidden lifecycle transitions."""


class MissionBindingError(AgentFactoryError):
    """Raised when a Mission binding is missing or already present."""


@dataclass(frozen=True, slots=True)
class AgentExecutionConstraints:
    """Bounded execution constraints (DERIVED). No authority is granted."""

    allowed_tools: tuple[str, ...] = ()
    allowed_resources: tuple[str, ...] = ()
    max_output_chars: int = 4000
    timeout_seconds: float = 30.0
    allow_external_effects: bool = False

    def __post_init__(self) -> None:
        if self.max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Typed declaration for a governed agent (DERIVED).

    Declared capabilities are claims, never RRM availability or authorization.
    Unknown fields are rejected by the dataclass constructor (TypeError), which
    prevents silently widening the declaration surface.
    """

    agent_type: str
    role: str
    description: str
    declared_capabilities: tuple[str, ...] = ()
    allowed_scope: str = "mission"
    project_id: str = "GLOBAL"
    mission_id: str | None = None
    memory_scope: str = "mission"
    provider_requirements: tuple[str, ...] = ()
    resource_requirements: tuple[str, ...] = ()
    execution_constraints: AgentExecutionConstraints | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.agent_type.strip():
            raise ValueError("AgentSpec.agent_type cannot be empty")
        if not self.role.strip():
            raise ValueError("AgentSpec.role cannot be empty")
        if self.mission_id is not None and not str(self.mission_id).strip():
            raise ValueError("AgentSpec.mission_id cannot be empty")
        if not self.description.strip():
            raise ValueError("AgentSpec.description cannot be empty")
        for capability in self.declared_capabilities:
            if not capability.strip():
                raise ValueError(
                    "AgentSpec.declared_capabilities cannot contain empty strings"
                )
        if self.memory_scope and self.memory_scope not in {
            "mission",
            "project",
            "none",
        }:
            raise ValueError(
                "AgentSpec.memory_scope must be one of mission, project, none"
            )


@dataclass(slots=True)
class GovernedAgent:
    """Passive governed execution participant (EXECUTION_PARTICIPANT).

    Has no direct provider invocation, no self-verification, and no
    self-completion. Execution is only possible through the governed
    MissionRuntime path. Output is evidence/input only.
    """

    agent_id: AgentId
    spec: AgentSpec
    lifecycle: AgentLifecycleState = AgentLifecycleState.CREATED
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    @property
    def mission_id(self) -> str | None:
        return self.spec.mission_id

    def snapshot(self) -> dict[str, Any]:
        constraints = self.spec.execution_constraints
        return {
            "agent_id": str(self.agent_id),
            "agent_type": self.spec.agent_type,
            "role": self.spec.role,
            "description": self.spec.description,
            "declared_capabilities": list(self.spec.declared_capabilities),
            "allowed_scope": self.spec.allowed_scope,
            "project_id": self.spec.project_id,
            "mission_id": self.spec.mission_id,
            "memory_scope": self.spec.memory_scope,
            "provider_requirements": list(self.spec.provider_requirements),
            "resource_requirements": list(self.spec.resource_requirements),
            "execution_constraints": {
                "allowed_tools": list(constraints.allowed_tools)
                if constraints
                else [],
                "allowed_resources": list(constraints.allowed_resources)
                if constraints
                else [],
                "max_output_chars": constraints.max_output_chars
                if constraints
                else 0,
                "timeout_seconds": constraints.timeout_seconds
                if constraints
                else 0.0,
                "allow_external_effects": bool(
                    constraints and constraints.allow_external_effects
                ),
            },
            "lifecycle": self.lifecycle.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "authority": "NONE",
            "execution_path": "governed_mission_runtime_only",
            "provenance": list(self.spec.provenance),
        }


class CanonicalAgentRegistry:
    """Registry of governed agents (REGISTRY_ONLY).

    Presence in the registry is NOT authorization. Duplicate identities are
    rejected without silent replacement. Revoked agents fail closed.
    """

    def __init__(self) -> None:
        self._agents: dict[str, GovernedAgent] = {}

    def register(self, agent: GovernedAgent) -> None:
        key = str(agent.agent_id)
        if key in self._agents:
            raise AgentIdentityError(
                f"duplicate agent identity rejected: {key}"
            )
        self._agents[key] = agent

    def get(self, agent_id: str | AgentId) -> GovernedAgent | None:
        return self._agents.get(str(agent_id))

    def lookup(self, *, mission_id: str | None = None) -> tuple[GovernedAgent, ...]:
        if mission_id is None:
            return tuple(self._agents.values())
        return tuple(
            agent
            for agent in self._agents.values()
            if agent.mission_id == mission_id
        )

    def revoke(self, agent_id: str | AgentId) -> GovernedAgent:
        agent = self._agents.get(str(agent_id))
        if agent is None:
            raise AgentIdentityError(
                f"cannot revoke unknown agent: {agent_id}"
            )
        if agent.lifecycle.terminal and agent.lifecycle != AgentLifecycleState.REVOKED:
            raise AgentLifecycleError(
                f"terminal agent cannot be revoked: {agent_id}"
            )
        agent.lifecycle = AgentLifecycleState.REVOKED
        agent.updated_at = utc_iso() or agent.updated_at
        return agent

    def is_revoked(self, agent_id: str | AgentId) -> bool:
        agent = self._agents.get(str(agent_id))
        return agent is not None and agent.lifecycle == AgentLifecycleState.REVOKED

    def __len__(self) -> int:
        return len(self._agents)

    def snapshot(self) -> list[dict[str, Any]]:
        return [agent.snapshot() for agent in self._agents.values()]


class CanonicalAgentFactory:
    """Instantiates governed agents (FACTORY_ONLY).

    The factory:

    - generates identity via factory-assigned UUID (never user-supplied),
    - rejects malformed AgentSpec declarations,
    - guards every lifecycle transition,
    - requires an explicit Mission binding before an agent can become BOUND.

    The factory does NOT invent Missions, authorize, select resources,
    invoke providers, execute productively during creation, complete
    Missions, fabricate verification, or mutate a product response.
    """

    def __init__(self, registry: CanonicalAgentRegistry | None = None) -> None:
        self.registry = registry or CanonicalAgentRegistry()

    def create(self, spec: AgentSpec) -> GovernedAgent:
        """Instantiate a governed agent in CREATED state. Non-productive."""
        if not isinstance(spec, AgentSpec):
            raise InvalidAgentSpecError(
                "spec must be an AgentSpec instance"
            )
        agent_id = AgentId(f"agent_{uuid4().hex}")
        agent = GovernedAgent(agent_id=agent_id, spec=spec)
        self.registry.register(agent)
        return agent

    def instantiate(self, spec: AgentSpec) -> GovernedAgent:
        """Alias for create(); always yields a fresh governed agent."""
        return self.create(spec)

    def bind(self, agent_id: str | AgentId, mission_id: str) -> GovernedAgent:
        """Bind an explicit Mission to a CREATED or READY agent.

        The factory never invents a Mission: a governed agent cannot become
        BOUND without an explicit, non-empty Mission binding.
        """
        if mission_id is None or not str(mission_id).strip():
            raise MissionBindingError("an explicit Mission binding is required")
        agent = self.registry.get(agent_id)
        if agent is None:
            raise AgentIdentityError(f"unknown agent: {agent_id}")
        current = agent.spec.mission_id
        if current is not None and str(current) != str(mission_id):
            raise MissionBindingError(
                f"agent {agent_id} is already bound to a different Mission"
            )
        if current is None:
            agent.spec = AgentSpec(
                agent_type=agent.spec.agent_type,
                role=agent.spec.role,
                description=agent.spec.description,
                declared_capabilities=agent.spec.declared_capabilities,
                allowed_scope=agent.spec.allowed_scope,
                project_id=agent.spec.project_id,
                mission_id=str(mission_id),
                memory_scope=agent.spec.memory_scope,
                provider_requirements=agent.spec.provider_requirements,
                resource_requirements=agent.spec.resource_requirements,
                execution_constraints=agent.spec.execution_constraints,
                provenance=agent.spec.provenance,
            )
        if agent.lifecycle == AgentLifecycleState.CREATED:
            self._transition(agent, agent.lifecycle, AgentLifecycleState.READY)
        self._transition(agent, agent.lifecycle, AgentLifecycleState.BOUND)
        agent.updated_at = utc_iso() or agent.updated_at
        return agent

    def transition(
        self, agent_id: str | AgentId, to_state: AgentLifecycleState
    ) -> GovernedAgent:
        """Guard a lifecycle transition. Rejects illegal moves."""
        agent = self.registry.get(agent_id)
        if agent is None:
            raise AgentIdentityError(f"unknown agent: {agent_id}")
        self._transition(agent, agent.lifecycle, to_state)
        return agent

    def _transition(
        self,
        agent: GovernedAgent,
        from_state: AgentLifecycleState,
        to_state: AgentLifecycleState,
    ) -> None:
        if not isinstance(to_state, AgentLifecycleState):
            raise AgentLifecycleError(
                f"invalid lifecycle target: {to_state!r}"
            )
        if from_state.terminal:
            raise AgentLifecycleError(
                f"terminal lifecycle cannot transition: "
                f"{from_state.value} -> {to_state.value}"
            )
        allowed = _TRANSITIONS[from_state]
        if to_state not in allowed:
            raise AgentLifecycleError(
                f"illegal lifecycle transition: "
                f"{from_state.value} -> {to_state.value}"
            )
        agent.lifecycle = to_state

    def snapshot(self) -> list[dict[str, Any]]:
        return self.registry.snapshot()
