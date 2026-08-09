"""Canonical Agent Orchestrator with bounded execution."""

from __future__ import annotations

import asyncio

from intent_kernel.contracts import (
    Agent,
    AgentRequest,
    CapabilityResult,
    ErrorCode,
)


class CanonicalAgentOrchestrator:
    """Selects and invokes agents; never changes Mission lifecycle."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[str(agent.agent_id)] = agent

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def discover(self, capability: str | None = None) -> list[Agent]:
        agents = list(self._agents.values())
        if capability is None:
            return agents
        return [
            agent
            for agent in agents
            if capability in {
                item.name for item in agent.capabilities
            }
        ]

    def select(self, capability: str) -> Agent | None:
        compatible = self.discover(capability)
        return compatible[0] if compatible else None

    async def execute(
        self,
        request: AgentRequest,
        *,
        agent_id: str | None = None,
    ) -> CapabilityResult:
        agent = (
            self.get(agent_id)
            if agent_id is not None
            else self.select(request.capability)
        )
        if agent is None or request.capability not in {
            item.name for item in agent.capabilities
        }:
            return CapabilityResult(
                capability=request.capability,
                success=False,
                error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
            )
        timeout = min(
            request.limits.timeout_seconds,
            agent.limits.timeout_seconds,
        )
        try:
            result = await asyncio.wait_for(
                agent.execute(request),
                timeout=timeout,
            )
        except TimeoutError:
            return CapabilityResult(
                capability=request.capability,
                success=False,
                error_code=ErrorCode.EXECUTION_FAILURE,
                metadata={
                    "agent_id": str(agent.agent_id),
                    "reason": "timeout",
                },
            )
        if isinstance(result.output, str):
            limit = min(
                request.limits.max_output_chars,
                agent.limits.max_output_chars,
            )
            result.output = result.output[:limit]
        result.metadata.setdefault("agent_id", str(agent.agent_id))
        return result

    @property
    def agents(self) -> tuple[Agent, ...]:
        return tuple(self._agents.values())
