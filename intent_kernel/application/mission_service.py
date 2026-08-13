"""Canonical coordination boundary for Mission lifecycle decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intent_kernel.application.mission_engine import MissionEngine
from intent_kernel.contracts import Mission, MissionContext, MissionStatus
from intent_kernel.tools.authorization import ToolAuthorizationGate
from intent_kernel.tools.models import ToolAuthorizationDecisionState


@dataclass(frozen=True, slots=True)
class MissionAuthorizationBoundary:
    decision: ToolAuthorizationDecisionState
    lifecycle_status: MissionStatus | None
    response_status: str
    execution_mode: str
    text: str
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    authorization_requirements: tuple[str, ...] = field(default_factory=tuple)
    confirmation_state: str | None = None

    @property
    def execution_eligible(self) -> bool:
        return self.decision is ToolAuthorizationDecisionState.ALLOW


class CanonicalMissionService:
    """Coordinate MissionEngine and authorization without owning their truth."""

    def __init__(
        self,
        mission_engine: MissionEngine,
        tool_authorization_gate: ToolAuthorizationGate,
    ) -> None:
        self.mission_engine = mission_engine
        self.tool_authorization_gate = tool_authorization_gate

    async def create_started(
        self,
        objective: str,
        *,
        context: MissionContext,
    ) -> Mission:
        mission = await self.mission_engine.create(objective, context=context)
        return await self.mission_engine.start(mission.id)

    async def block_planning(self, mission: Mission) -> Mission:
        return await self.mission_engine.pause(
            mission.id,
            status=MissionStatus.BLOCKED,
            blocker={"source": "constitution", "phase": "planning"},
        )

    async def authorize_tool(
        self,
        mission: Mission,
        candidate: Any,
        tool: Any,
        *,
        project_id: str,
        required_permissions: list[str],
    ) -> MissionAuthorizationBoundary:
        decision = await self.tool_authorization_gate.evaluate_tool(
            candidate,
            tool,
            project_id=project_id,
        )
        boundary = self._authorization_boundary(decision, required_permissions)
        if not boundary.execution_eligible and boundary.lifecycle_status is not None:
            await self.mission_engine.pause(
                mission.id,
                status=boundary.lifecycle_status,
                blocker={
                    "source": "tool_authorization_gate",
                    "decision": decision.value,
                    "execution_eligible": False,
                },
            )
        return boundary

    @staticmethod
    def _authorization_boundary(
        decision: ToolAuthorizationDecisionState,
        required_permissions: list[str],
    ) -> MissionAuthorizationBoundary:
        boundaries = {
            ToolAuthorizationDecisionState.ALLOW: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=None,
                response_status="AUTHORIZATION_REQUIRED",
                execution_mode="MISSION",
                text="A ferramenta está autorizada para o runtime controlado.",
            ),
            ToolAuthorizationDecisionState.DENY: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.BLOCKED,
                response_status="BLOCKED",
                execution_mode="BLOCKED",
                text="A ferramenta selecionada foi bloqueada pela política de autorização.",
                next_actions=("Selecionar um recurso autorizado",),
            ),
            ToolAuthorizationDecisionState.REQUEST_PERMISSION: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.WAITING_FOR_PERMISSION,
                response_status="AUTHORIZATION_REQUIRED",
                execution_mode="MISSION",
                text="A missão aguarda autorização para usar a ferramenta selecionada.",
                next_actions=("Autorizar o uso da ferramenta",),
                authorization_requirements=tuple(required_permissions),
            ),
            ToolAuthorizationDecisionState.REQUEST_CONFIRMATION: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.WAITING_FOR_DECISION,
                response_status="AUTHORIZATION_REQUIRED",
                execution_mode="MISSION",
                text="A ferramenta está elegível, mas esta ação específica aguarda confirmação.",
                next_actions=("Confirmar a ação específica",),
                authorization_requirements=("user.confirmation",),
                confirmation_state="WAITING_USER_CONFIRMATION",
            ),
            ToolAuthorizationDecisionState.WAIT_TOOL: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.WAITING_FOR_INFORMATION,
                response_status="EXTERNAL_RESOURCE_REQUIRED",
                execution_mode="MISSION",
                text="A missão aguarda a disponibilidade da ferramenta selecionada.",
                next_actions=("Aguardar recurso elegível",),
            ),
            ToolAuthorizationDecisionState.RESELECT_TOOL: MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.WAITING_FOR_DECISION,
                response_status="EXTERNAL_RESOURCE_REQUIRED",
                execution_mode="MISSION",
                text="A ferramenta atual não pode executar esta ação e deve ser substituída.",
                next_actions=("Selecionar outra ferramenta elegível",),
            ),
        }
        return boundaries.get(
            decision,
            MissionAuthorizationBoundary(
                decision=decision,
                lifecycle_status=MissionStatus.BLOCKED,
                response_status="BLOCKED",
                execution_mode="BLOCKED",
                text="A decisão de autorização não permite execução.",
                next_actions=("Reavaliar a autorização",),
            ),
        )
