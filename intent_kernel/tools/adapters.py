"""Tool Adapters & Safe Simulation Tools — RFC-0016 (STUDIO 10.3).

Provides in-memory simulation tool adapters for testing email, calendar, filesystem,
and browser capabilities. Enforces dry run contracts and guarantees zero external side effects.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from intent_kernel.runtime.executor_port import ActionExecutorPort
from intent_kernel.runtime.models import ActionContract
from intent_kernel.tools.authorization import ToolAuthorizationGate
from intent_kernel.tools.health import InMemoryToolHealthAdapter, ToolHealthPort
from intent_kernel.tools.models import (
    DryRunRequest,
    DryRunResult,
    PermissionScope,
    ToolAuthorizationDecisionState,
    ToolResource,
    ToolStatus,
    ToolType,
)
from intent_kernel.tools.registry import InMemoryToolRegistry
from intent_kernel.tools.router import CapabilityRouter
from intent_kernel.tools.secret_resolver import FakeSecretResolver, SecretResolverPort


class InMemoryToolAdapter:
    """Base class for safe in-memory simulation tool adapters."""

    def __init__(self, tool_resource: ToolResource) -> None:
        self.tool_resource = tool_resource

    async def dry_run(self, request: DryRunRequest) -> DryRunResult:
        """Perform a safe preview of the requested action without execution."""
        return DryRunResult(
            tool_id=self.tool_resource.tool_id,
            capability=request.capability,
            intended_action=f"Simulated execution of {request.capability}",
            affected_resource=f"simulated_resource_{request.capability}",
            expected_effect="Simulated state change",
            required_permissions=self.tool_resource.required_permissions,
            risk_level=self.tool_resource.risk_profile,
            reversibility=True,
            confirmation_required=self.tool_resource.side_effect_profile in ("EXTERNAL_IRREVERSIBLE", "EXTERNAL_REVERSIBLE"),
            simulated_output={"status": "SIMULATED", "inputs": request.inputs},
            executed=False,
        )

    async def execute_simulated(self, capability: str, inputs: Dict[str, Any]) -> Any:
        """Execute safe simulated logic in memory."""
        return {"status": "SIMULATED_SUCCESS", "capability": capability, "inputs": inputs}


class EmailSimulationTool(InMemoryToolAdapter):
    """Safe simulation adapter for email capabilities (test.email / external.email.send)."""

    def __init__(self, tool_id: str = "tool_sim_email") -> None:
        resource = ToolResource(
            tool_id=tool_id,
            name="Simulated Email Tool",
            description="Safe in-memory email tool adapter",
            provider_family="simulation",
            tool_type=ToolType.EMAIL,
            status=ToolStatus.AVAILABLE,
            capabilities=["test.email", "external.email.send"],
            required_permissions=["email.send"],
            side_effect_profile="EXTERNAL_IRREVERSIBLE",
            supports_dry_run=True,
            supports_verification=True,
            supports_idempotency=True,
        )
        super().__init__(resource)


class CalendarSimulationTool(InMemoryToolAdapter):
    """Safe simulation adapter for calendar capabilities (test.calendar / external.calendar.create)."""

    def __init__(self, tool_id: str = "tool_sim_calendar") -> None:
        resource = ToolResource(
            tool_id=tool_id,
            name="Simulated Calendar Tool",
            description="Safe in-memory calendar tool adapter",
            provider_family="simulation",
            tool_type=ToolType.CALENDAR,
            status=ToolStatus.AVAILABLE,
            capabilities=["test.calendar", "external.calendar.create"],
            required_permissions=["calendar.create"],
            side_effect_profile="EXTERNAL_REVERSIBLE",
            supports_dry_run=True,
            supports_verification=True,
            supports_idempotency=True,
        )
        super().__init__(resource)


class FilesystemSimulationTool(InMemoryToolAdapter):
    """Safe simulation adapter for filesystem capabilities (test.filesystem / filesystem.read)."""

    def __init__(self, tool_id: str = "tool_sim_filesystem") -> None:
        resource = ToolResource(
            tool_id=tool_id,
            name="Simulated Filesystem Tool",
            description="Safe in-memory filesystem tool adapter",
            provider_family="simulation",
            tool_type=ToolType.FILESYSTEM,
            status=ToolStatus.AVAILABLE,
            capabilities=["test.filesystem", "filesystem.read", "filesystem.write"],
            required_permissions=["filesystem.read"],
            side_effect_profile="LOCAL_REVERSIBLE",
            supports_dry_run=True,
            supports_verification=True,
            supports_idempotency=True,
        )
        super().__init__(resource)


class BrowserSimulationTool(InMemoryToolAdapter):
    """Safe simulation adapter for browser capabilities (test.browser / browser.navigate)."""

    def __init__(self, tool_id: str = "tool_sim_browser") -> None:
        resource = ToolResource(
            tool_id=tool_id,
            name="Simulated Browser Tool",
            description="Safe in-memory browser tool adapter",
            provider_family="simulation",
            tool_type=ToolType.BROWSER,
            status=ToolStatus.AVAILABLE,
            capabilities=["test.browser", "browser.navigate", "browser.read"],
            required_permissions=["browser.navigate"],
            side_effect_profile="NONE",
            supports_dry_run=True,
            supports_verification=True,
            supports_idempotency=True,
        )
        super().__init__(resource)


class ToolAccessExecutorAdapter(ActionExecutorPort):
    """Bridge between MissionRuntime's ActionExecutorPort and Tool Access Layer (RFC-0016)."""

    def __init__(
        self,
        capability_router: CapabilityRouter,
        tool_auth_gate: ToolAuthorizationGate,
        secret_resolver: Optional[SecretResolverPort] = None,
        tool_health_adapter: Optional[ToolHealthPort] = None,
        tool_registry: Optional[InMemoryToolRegistry] = None,
    ) -> None:
        self.capability_router = capability_router
        self.tool_auth_gate = tool_auth_gate
        self.secret_resolver = secret_resolver or FakeSecretResolver()
        self.tool_health_adapter = tool_health_adapter or InMemoryToolHealthAdapter()
        self.tool_registry = tool_registry or capability_router.registry
        self._simulation_tools: Dict[str, InMemoryToolAdapter] = {}
        self._execution_history: Dict[str, Any] = {}
        self._status_map: Dict[str, str] = {}

    async def register_simulation_tool(self, tool: InMemoryToolAdapter) -> None:
        """Register a simulation tool with the registry, capability router, and internal executor map."""
        await self.tool_registry.register_tool(tool.tool_resource)
        await self.capability_router.registry.register_tool(tool.tool_resource)
        self._simulation_tools[tool.tool_resource.tool_id] = tool

    async def can_execute(self, action: ActionContract) -> bool:
        """Check if candidate tools exist for the action capability."""
        candidates = await self.capability_router.route_capability(action.capability)
        return len(candidates) > 0

    async def execute(self, action: ActionContract) -> Any:
        """Execute action by routing to authorized simulation tool."""
        self._status_map[action.action_id] = "EXECUTING"
        candidates = await self.capability_router.route_capability(action.capability)
        inputs = getattr(action, "inputs", None) or getattr(action, "inputs_reference", {})
        if not candidates:
            # Fallback for echo or unmapped capabilities
            if action.capability in ("test.echo", "test.calculate", "test.transform", "test.store_temporary") or action.capability.startswith("core.") or action.capability.startswith("retrieval.") or action.capability.startswith("analysis.") or action.capability.startswith("synthesis.") or action.capability.startswith("validation."):
                res = {"status": "SIMULATED_SUCCESS", "capability": action.capability, "inputs": inputs}
                self._execution_history[action.action_id] = res
                self._status_map[action.action_id] = "SUCCEEDED"
                return res
            self._status_map[action.action_id] = "FAILED"
            raise RuntimeError(f"No candidate tools found for capability {action.capability}")

        top_candidate = candidates[0]
        sim_tool = self._simulation_tools.get(top_candidate.tool_id)
        tool_res = sim_tool.tool_resource if sim_tool else ToolResource(
            tool_id=top_candidate.tool_id,
            capabilities=[top_candidate.capability],
            status=ToolStatus.AVAILABLE,
        )

        decision = await self.tool_auth_gate.evaluate_tool(
            candidate=top_candidate,
            tool=tool_res,
        )

        if decision != ToolAuthorizationDecisionState.ALLOW:
            self._status_map[action.action_id] = "BLOCKED"
            raise PermissionError(
                f"Tool {top_candidate.tool_id} authorization failed: decision={decision}"
            )

        if sim_tool:
            if inputs.get("dry_run", False):
                dry_req = DryRunRequest(
                    capability=action.capability,
                    inputs=inputs,
                    project_id="GLOBAL",
                )
                res = await sim_tool.dry_run(dry_req)
                result_data = res.to_dict()
            else:
                result_data = await sim_tool.execute_simulated(action.capability, inputs)
        else:
            result_data = {
                "status": "SIMULATED_SUCCESS",
                "tool_id": top_candidate.tool_id,
                "capability": action.capability,
                "inputs": inputs,
            }

        self._execution_history[action.action_id] = result_data
        self._status_map[action.action_id] = "SUCCEEDED"
        return result_data

    async def cancel(self, action_id: str) -> bool:
        """Cancel an in-flight execution."""
        if action_id in self._status_map:
            self._status_map[action_id] = "CANCELLED"
            return True
        return False

    async def get_status(self, action_id: str) -> str:
        """Get status of an action execution."""
        return self._status_map.get(action_id, "UNKNOWN")

