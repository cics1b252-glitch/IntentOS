"""Canonical, non-executing cognitive capability runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from intent_kernel.cognition.capabilities import (
    CapabilityComposition,
    CapabilityFirstResolver,
    CapabilityRequirement,
    CapabilityRequirementDiscovery,
    CapabilityResolutionStatus,
)
from intent_kernel.rrm.models import ResourceQueryFilter, ResourceType


class CognitiveExecutionMode(str, Enum):
    CONVERSATION = "CONVERSATION"
    MISSION = "MISSION"
    LOCAL_RESPONSE = "LOCAL_RESPONSE"
    EXTERNAL_REASONING_REQUIRED = "EXTERNAL_REASONING_REQUIRED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class CognitiveExecutionDecision:
    mode: CognitiveExecutionMode
    reason: str
    requirements: list[CapabilityRequirement] = field(default_factory=list)
    composition: CapabilityComposition | None = None
    domain_hint: str = "other"
    project_id: str = "GLOBAL"
    provenance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        if self.composition is not None:
            value["composition"]["status"] = self.composition.status.value
        return value


class CognitiveCapabilityRuntime:
    """Understand, discover and resolve without executing side effects."""

    _LOCAL_RESPONSE_MARKERS = (
        "o que voce consegue fazer",
        "quais suas capacidades",
        "como funciona",
        "ajuda",
    )
    _MISSION_CAPABILITIES = {
        "external.communication",
        "filesystem.modify",
        "application.launch",
        "application.control",
    }

    def __init__(
        self,
        *,
        discovery: CapabilityRequirementDiscovery,
        resolver: CapabilityFirstResolver,
    ) -> None:
        self.discovery = discovery
        self.resolver = resolver

    async def analyze(
        self,
        user_input: str,
        *,
        structured_intent: Any | None = None,
        ame_context: dict[str, Any] | None = None,
        project_context: dict[str, Any] | None = None,
        persistent_constraints: Iterable[str] = (),
        authorized_permissions: Iterable[str] = (),
    ) -> CognitiveExecutionDecision:
        project_context = dict(project_context or {})
        project_id = str(project_context.get("project_id", "GLOBAL"))
        requirements = self.discovery.discover(
            user_input,
            structured_intent=structured_intent,
            ame_context=ame_context,
            project_context=project_context,
            persistent_constraints=persistent_constraints,
        )
        composition = await self.resolver.compose(
            user_input,
            requirements,
            authorized_permissions=authorized_permissions,
            context={"project_id": project_id},
        )
        normalized = self.discovery._normalize(user_input)
        capability_ids = {item.capability_id for item in requirements}
        domain = self._domain_hint(structured_intent)

        if composition.status is CapabilityResolutionStatus.BLOCKED_BY_POLICY:
            mode = CognitiveExecutionMode.BLOCKED
            reason = "Constitution blocked capability resolution"
        elif composition.status is CapabilityResolutionStatus.AUTHORIZATION_REQUIRED:
            mode = CognitiveExecutionMode.AUTHORIZATION_REQUIRED
            reason = "A selected resource requires explicit authorization"
        elif any(item in normalized for item in self._LOCAL_RESPONSE_MARKERS):
            mode = CognitiveExecutionMode.LOCAL_RESPONSE
            reason = "The request can be answered by local system guidance"
        elif (
            capability_ids & self._MISSION_CAPABILITIES
            and composition.status is CapabilityResolutionStatus.AVAILABLE
        ):
            mode = CognitiveExecutionMode.MISSION
            reason = "The request implies an external or persistent effect"
        elif capability_ids & self._MISSION_CAPABILITIES:
            mode = CognitiveExecutionMode.UNKNOWN
            reason = "Action capabilities are missing or unavailable"
        elif composition.status is CapabilityResolutionStatus.EXTERNAL_RESOURCE_REQUIRED:
            mode = CognitiveExecutionMode.EXTERNAL_REASONING_REQUIRED
            reason = "No eligible external reasoning resource is configured"
        elif composition.status in {
            CapabilityResolutionStatus.MISSING,
            CapabilityResolutionStatus.UNKNOWN,
        }:
            mode = CognitiveExecutionMode.UNKNOWN
            reason = "Required capabilities are not currently available"
        else:
            mode = CognitiveExecutionMode.CONVERSATION
            reason = "No supervised external action is required"
        return CognitiveExecutionDecision(
            mode=mode,
            reason=reason,
            requirements=requirements,
            composition=composition,
            domain_hint=domain,
            project_id=project_id,
            provenance=["IUE", "AME", "CapabilityRequirementDiscovery", "RRM"],
        )

    @staticmethod
    def _domain_hint(structured_intent: Any | None) -> str:
        value = getattr(structured_intent, "domain", None)
        if hasattr(value, "value"):
            value = value.value
        return str(value or "other")


class AgentLifecycle(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    AUTHORIZED = "AUTHORIZED"
    INSTANTIATED = "INSTANTIATED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"
    DISCARDED = "DISCARDED"


@dataclass(frozen=True, slots=True)
class AgentBlueprint:
    mission_scope: str
    required_capabilities: tuple[str, ...]
    blueprint_id: str = field(default_factory=lambda: f"blueprint_{uuid4().hex[:8]}")
    optional_capabilities: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allowed_resources: tuple[str, ...] = ()
    memory_scope: str = "mission"
    instruction_scope: str = "mission"
    execution_environment_requirements: tuple[str, ...] = ()
    privacy_constraints: tuple[str, ...] = ()
    cost_constraints: tuple[str, ...] = ()
    latency_constraints: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()
    retention_policy: str = "discard_after_mission"
    provenance: tuple[str, ...] = ()
    lifecycle: AgentLifecycle = AgentLifecycle.PROPOSED


@dataclass(slots=True)
class AgentResolution:
    selected_agent_id: str | None = None
    coverage: float = 0.0
    blueprint: AgentBlueprint | None = None
    missing_capabilities: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)


class AgentBlueprintResolver:
    """Search existing agents first; propose a blueprint without instantiation."""

    def __init__(self, rrm: Any) -> None:
        self.rrm = rrm

    def resolve(
        self,
        requirements: list[CapabilityRequirement],
        *,
        mission_scope: str,
        privacy_constraints: Iterable[str] = (),
        project_constraints: dict[str, Any] | None = None,
    ) -> AgentResolution:
        required = {item.capability_id for item in requirements}
        required_environments = {
            environment
            for item in requirements
            for environment in item.environment_requirements
        }
        privacy = set(privacy_constraints) | {
            rule
            for item in requirements
            for rule in item.privacy_requirements
        }
        project_constraints = dict(project_constraints or {})
        allowed_agents = set(project_constraints.get("allowed_agents", ()))
        agents = self.rrm.query_resources(ResourceQueryFilter(
            resource_type=ResourceType.AGENT,
            only_eligible=True,
            include_templates=False,
        ))
        ranked: list[tuple[float, Any]] = []
        for agent in agents:
            if allowed_agents and agent.agent_id not in allowed_agents:
                continue
            metadata = getattr(agent, "metadata", {}) or {}
            privacy_class = str(metadata.get("privacy_class", "standard"))
            if privacy and privacy_class not in privacy:
                continue
            environments = set(metadata.get("environments", ()))
            if required_environments and not required_environments <= environments:
                continue
            capabilities = set(getattr(agent, "capabilities", ()))
            coverage = len(required & capabilities) / max(1, len(required))
            reliability = float(getattr(agent, "historical_confidence", 0.5))
            availability = float(getattr(agent, "availability", 0.0))
            cost = float(getattr(agent, "cost_tier", 0.0))
            latency = float(getattr(agent, "latency_tier", 0.0))
            score = coverage * 0.6 + reliability * 0.2 + availability * 0.2
            score -= cost * 0.05 + latency * 0.02
            ranked.append((score, agent))
        ranked.sort(key=lambda item: (-item[0], item[1].agent_id))
        if ranked:
            agent = ranked[0][1]
            caps = set(agent.capabilities)
            coverage = len(required & caps) / max(1, len(required))
            if coverage == 1.0:
                return AgentResolution(
                    selected_agent_id=agent.agent_id,
                    coverage=coverage,
                    provenance=["RRM", "existing_agent_first"],
                )
        missing = sorted(required)
        return AgentResolution(
            coverage=ranked[0][0] if ranked else 0.0,
            blueprint=AgentBlueprint(
                mission_scope=mission_scope,
                required_capabilities=tuple(sorted(required)),
                privacy_constraints=tuple(sorted(privacy)),
                execution_environment_requirements=tuple(sorted(required_environments)),
                cost_constraints=tuple(project_constraints.get("cost_constraints", ())),
                latency_constraints=tuple(project_constraints.get("latency_constraints", ())),
                verification_requirements=tuple(sorted({
                    rule
                    for requirement in requirements
                    for rule in requirement.verification_requirements
                })),
                provenance=("capability_gap", "RRM_agent_search"),
            ),
            missing_capabilities=missing,
            provenance=["RRM", "blueprint_proposal_only"],
        )
