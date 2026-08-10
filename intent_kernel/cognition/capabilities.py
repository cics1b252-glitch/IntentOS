"""Minimal capability-first discovery and composition boundary.

This module deliberately stops before execution. It represents what an intent
needs, asks the existing RRM and Tool Registry what is actually available, and
produces an auditable declarative composition. Mission Runtime remains the only
future execution authority.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

from intent_kernel.rrm.models import ResourceQueryFilter, ResourceType


class CapabilityResolutionStatus(str, Enum):
    AVAILABLE = "CAPABILITY_AVAILABLE"
    PARTIAL = "CAPABILITY_PARTIAL"
    MISSING = "CAPABILITY_MISSING"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    EXTERNAL_RESOURCE_REQUIRED = "EXTERNAL_RESOURCE_REQUIRED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability_id: str
    description: str
    required_inputs: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    risk_level: str = "low"
    side_effect_level: str = "none"
    privacy_requirements: tuple[str, ...] = ()
    environment_requirements: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()
    preferred_execution_mode: str = "any"
    allows_external_reasoning: bool = False
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id cannot be empty")


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    resource_id: str
    resource_type: str
    score: float
    available: bool
    authorized: bool = True
    reasons: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()


@dataclass(slots=True)
class CapabilityResolution:
    requirement: CapabilityRequirement
    status: CapabilityResolutionStatus
    candidates: list[CapabilityCandidate] = field(default_factory=list)
    selected_strategy: str = ""
    missing_requirements: list[str] = field(default_factory=list)
    authorization_requirements: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True, slots=True)
class CapabilityCompositionStep:
    step_id: str
    capability_id: str
    strategy: str
    dependencies: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()


@dataclass(slots=True)
class CapabilityComposition:
    objective: str
    steps: list[CapabilityCompositionStep]
    status: CapabilityResolutionStatus
    executable: bool
    missing_capabilities: list[str] = field(default_factory=list)
    authorization_requirements: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)


class CapabilityRequirementDiscovery:
    """Small, domain-neutral semantic decomposition for architecture tests.

    The rules identify reusable operations (track, model, explain, design), not
    business domains or destination modules. Provider-backed understanding can
    replace these conservative bootstrap rules later without changing contracts.
    """

    _RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("criar", "sistema"), "requirements.discovery", "Discover requirements"),
        (("sistema",), "data.modeling", "Model the information required by the system"),
        (("sistema",), "workflow.design", "Design the operational workflow"),
        (("sistema",), "software.architecture", "Design a software architecture"),
        (("sistema",), "storage.selection", "Select an appropriate storage strategy"),
        (("sistema",), "interface.design", "Design a usable interface"),
        (("manutencao",), "maintenance.tracking", "Track maintenance activities"),
        (("maquinas",), "asset.tracking", "Track physical assets"),
        (("estoque",), "inventory.tracking", "Track inventory"),
        (("inventario",), "inventory.tracking", "Track inventory"),
        (("plantio",), "production.tracking", "Track production cycles"),
        (("producao",), "production.tracking", "Track production"),
        (("custos",), "cost.tracking", "Track costs"),
        (("vendas",), "sales.tracking", "Track sales"),
        (("aprender",), "learning.goal_management", "Manage a learning goal"),
        (("evolucao",), "learning.progress_tracking", "Track learning progress"),
        (("acompanhasse",), "learning.progress_tracking", "Track learning progress"),
        (("japones",), "content.explain", "Explain learning content"),
        (("aprender",), "assessment.plan", "Plan assessments"),
        (("lembr",), "memory.retrieve", "Retrieve relevant memory"),
    )

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    def discover(self, text: str) -> list[CapabilityRequirement]:
        normalized = self._normalize(text)
        requirements: dict[str, CapabilityRequirement] = {}
        for tokens, capability_id, description in self._RULES:
            if all(re.search(rf"\b{re.escape(token)}\b", normalized) for token in tokens):
                requirements.setdefault(
                    capability_id,
                    CapabilityRequirement(
                        capability_id=capability_id,
                        description=description,
                        expected_outputs=("structured_result",),
                        verification_requirements=("result_matches_objective",),
                        allows_external_reasoning=capability_id in {
                            "requirements.discovery",
                            "data.modeling",
                            "workflow.design",
                            "software.architecture",
                            "storage.selection",
                            "interface.design",
                            "content.explain",
                            "assessment.plan",
                        },
                        provenance=("bootstrap_semantic_decomposition",),
                    ),
                )
        if not requirements:
            requirements["intent.analyze"] = CapabilityRequirement(
                capability_id="intent.analyze",
                description="Analyze an intent not covered by local capability rules",
                expected_outputs=("capability_requirements",),
                allows_external_reasoning=True,
                provenance=("unknown_intent_fallback",),
            )
        return list(requirements.values())


class CapabilityFirstResolver:
    """Resolve abstract requirements against real, authorized resources."""

    def __init__(
        self,
        *,
        rrm: Any,
        tool_registry: Any | None = None,
        constitution: Any | None = None,
    ) -> None:
        self.rrm = rrm
        self.tool_registry = tool_registry
        self.constitution = constitution

    async def resolve(
        self,
        requirement: CapabilityRequirement,
        *,
        authorized_permissions: Iterable[str] = (),
        context: dict[str, Any] | None = None,
    ) -> CapabilityResolution:
        context = dict(context or {})
        if self.constitution is not None:
            verdict = await self.constitution.evaluate(
                "capability.resolve",
                {"capability": requirement.capability_id},
                context,
            )
            if not verdict.allowed:
                return CapabilityResolution(
                    requirement=requirement,
                    status=CapabilityResolutionStatus.BLOCKED_BY_POLICY,
                    selected_strategy="constitution_block",
                    confidence=1.0,
                    provenance=["constitution:denied"],
                )

        candidates: list[CapabilityCandidate] = []
        capability = getattr(self.rrm, "get_capability", lambda _id: None)(
            requirement.capability_id
        )
        if capability is not None:
            candidates.append(self._candidate(capability, "capability", 1.0))

        agents = self.rrm.query_resources(
            ResourceQueryFilter(
                resource_type=ResourceType.AGENT,
                capability=requirement.capability_id,
                include_templates=False,
            )
        )
        for agent in agents:
            confidence = float(getattr(agent, "historical_confidence", 0.5))
            cost = float(getattr(agent, "cost_tier", 0.0))
            latency = float(getattr(agent, "latency_tier", 0.0))
            score = max(0.0, min(1.0, confidence - cost - (latency * 0.1)))
            candidates.append(self._candidate(agent, "agent", score))

        environments = self.rrm.query_resources(
            ResourceQueryFilter(
                resource_type=ResourceType.EXECUTION_ENVIRONMENT,
                capability=requirement.capability_id,
                include_templates=False,
            )
        )
        for environment in environments:
            candidates.append(self._candidate(environment, "environment", 0.75))

        authorization_requirements: list[str] = []
        authorized = set(authorized_permissions)
        if self.tool_registry is not None:
            tools = await self.tool_registry.get_tools_for_capability(
                requirement.capability_id
            )
            for tool in tools:
                permissions = set(getattr(tool, "required_permissions", ()))
                missing = sorted(permissions - authorized)
                authorization_requirements.extend(missing)
                candidates.append(
                    CapabilityCandidate(
                        resource_id=str(getattr(tool, "tool_id", "unknown")),
                        resource_type="tool",
                        score=0.9 if not missing else 0.6,
                        available=self._eligible(tool),
                        authorized=not missing,
                        reasons=tuple(f"permission:{item}" for item in missing),
                        provenance=("tool_registry",),
                    )
                )

        usable = [item for item in candidates if item.available and item.authorized]
        if usable:
            usable.sort(key=lambda item: (-item.score, item.resource_type, item.resource_id))
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.AVAILABLE,
                candidates=candidates,
                selected_strategy=f"{usable[0].resource_type}:{usable[0].resource_id}",
                confidence=usable[0].score,
                provenance=["rrm", "capability_first_resolution"],
            )
        if candidates and authorization_requirements:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.AUTHORIZATION_REQUIRED,
                candidates=candidates,
                selected_strategy="await_authorization",
                authorization_requirements=sorted(set(authorization_requirements)),
                confidence=1.0,
                provenance=["tool_registry", "permission_boundary"],
            )
        if candidates:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.PARTIAL,
                candidates=candidates,
                selected_strategy="resource_unavailable",
                missing_requirements=[requirement.capability_id],
                confidence=0.5,
                provenance=["rrm", "ineligible_candidates"],
            )
        if requirement.allows_external_reasoning:
            providers = self.rrm.query_resources(
                ResourceQueryFilter(
                    resource_type=ResourceType.PROVIDER,
                    only_eligible=True,
                    include_templates=False,
                )
            )
            if providers:
                provider = providers[0]
                return CapabilityResolution(
                    requirement=requirement,
                    status=CapabilityResolutionStatus.AVAILABLE,
                    candidates=[self._candidate(provider, "provider", 0.7)],
                    selected_strategy=f"provider:{provider.provider_id}",
                    confidence=0.7,
                    provenance=["rrm", "external_reasoning"],
                )
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.EXTERNAL_RESOURCE_REQUIRED,
                selected_strategy="connect_reasoning_provider",
                missing_requirements=["eligible_reasoning_provider"],
                confidence=1.0,
                provenance=["rrm", "truthful_capability_gap"],
            )
        return CapabilityResolution(
            requirement=requirement,
            status=CapabilityResolutionStatus.MISSING,
            selected_strategy="none",
            missing_requirements=[requirement.capability_id],
            confidence=1.0,
            provenance=["rrm", "truthful_capability_gap"],
        )

    async def compose(
        self,
        objective: str,
        requirements: list[CapabilityRequirement],
        *,
        authorized_permissions: Iterable[str] = (),
        context: dict[str, Any] | None = None,
    ) -> CapabilityComposition:
        resolutions = [
            await self.resolve(
                requirement,
                authorized_permissions=authorized_permissions,
                context=context,
            )
            for requirement in requirements
        ]
        steps: list[CapabilityCompositionStep] = []
        previous_step = ""
        for index, resolution in enumerate(resolutions, 1):
            step_id = f"capability_step_{index}"
            steps.append(
                CapabilityCompositionStep(
                    step_id=step_id,
                    capability_id=resolution.requirement.capability_id,
                    strategy=resolution.selected_strategy,
                    dependencies=(previous_step,) if previous_step else (),
                    verification_requirements=(
                        resolution.requirement.verification_requirements
                    ),
                )
            )
            previous_step = step_id

        statuses = {resolution.status for resolution in resolutions}
        blocked = CapabilityResolutionStatus.BLOCKED_BY_POLICY in statuses
        authorization = CapabilityResolutionStatus.AUTHORIZATION_REQUIRED in statuses
        unavailable = statuses & {
            CapabilityResolutionStatus.MISSING,
            CapabilityResolutionStatus.EXTERNAL_RESOURCE_REQUIRED,
            CapabilityResolutionStatus.PARTIAL,
            CapabilityResolutionStatus.UNKNOWN,
        }
        if blocked:
            status = CapabilityResolutionStatus.BLOCKED_BY_POLICY
        elif authorization:
            status = CapabilityResolutionStatus.AUTHORIZATION_REQUIRED
        elif unavailable:
            status = (
                CapabilityResolutionStatus.PARTIAL
                if CapabilityResolutionStatus.AVAILABLE in statuses
                else next(
                    item
                    for item in (
                        CapabilityResolutionStatus.EXTERNAL_RESOURCE_REQUIRED,
                        CapabilityResolutionStatus.MISSING,
                        CapabilityResolutionStatus.PARTIAL,
                        CapabilityResolutionStatus.UNKNOWN,
                    )
                    if item in unavailable
                )
            )
        else:
            status = CapabilityResolutionStatus.AVAILABLE

        return CapabilityComposition(
            objective=objective,
            steps=steps,
            status=status,
            executable=status is CapabilityResolutionStatus.AVAILABLE,
            missing_capabilities=[
                item.requirement.capability_id
                for item in resolutions
                if item.status not in {CapabilityResolutionStatus.AVAILABLE}
            ],
            authorization_requirements=sorted(
                {
                    permission
                    for item in resolutions
                    for permission in item.authorization_requirements
                }
            ),
            provenance=[
                f"{item.requirement.capability_id}:{item.status.value}"
                for item in resolutions
            ],
        )

    @staticmethod
    def _eligible(resource: Any) -> bool:
        value = getattr(resource, "is_eligible", None)
        if value is not None:
            return bool(value)
        status = getattr(resource, "status", None)
        return str(getattr(status, "value", status)).lower() in {
            "active",
            "available",
            "enabled",
            "ready",
        }

    @classmethod
    def _candidate(
        cls,
        resource: Any,
        resource_type: str,
        score: float,
    ) -> CapabilityCandidate:
        resource_id = (
            getattr(resource, "capability_id", None)
            or getattr(resource, "agent_id", None)
            or getattr(resource, "environment_id", None)
            or getattr(resource, "provider_id", None)
            or "unknown"
        )
        return CapabilityCandidate(
            resource_id=str(resource_id),
            resource_type=resource_type,
            score=score,
            available=cls._eligible(resource),
            provenance=("rrm",),
        )
