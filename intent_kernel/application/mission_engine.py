"""Initial canonical Mission Engine.

This Sprint 2 implementation provides lifecycle and continuity only. It does
not plan, select capabilities, or execute user work.
"""

from __future__ import annotations

from copy import deepcopy

from intent_kernel.contracts import (
    Mission,
    MissionContext,
    MissionId,
    MissionResult,
    MissionStatus,
    MissionStore,
)
from intent_kernel.contracts.models import utcnow


class MissionTransitionError(ValueError):
    """Raised when a lifecycle transition is not currently valid."""


class MissionEngine:
    """Coordinates the minimal persistent lifecycle of a Mission."""

    _RESUMABLE = {
        MissionStatus.PAUSED,
        MissionStatus.BLOCKED,
        MissionStatus.WAITING_FOR_INFORMATION,
        MissionStatus.WAITING_FOR_DECISION,
        MissionStatus.WAITING_FOR_PERMISSION,
        MissionStatus.FAILED_RECOVERABLE,
    }
    _TERMINAL = {
        MissionStatus.COMPLETED,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED_FINAL,
    }

    def __init__(self, store: MissionStore):
        self._store = store

    async def create(
        self,
        objective: str,
        *,
        mission_id: MissionId | None = None,
        context: MissionContext | None = None,
        success_criteria: list[str] | None = None,
        scope: list[str] | None = None,
    ) -> Mission:
        mission = Mission(
            objective=objective,
            id=mission_id or MissionId(),
            context=context or MissionContext(),
            success_criteria=list(success_criteria or []),
            scope=list(scope or []),
        )
        await self._store.save(mission)
        return deepcopy(mission)

    async def start(self, mission_id: MissionId) -> Mission:
        mission = await self._require(mission_id)
        if mission.status not in {
            MissionStatus.CREATED,
            MissionStatus.READY,
        }:
            self._reject(mission, MissionStatus.RUNNING)
        return await self._transition(mission, MissionStatus.RUNNING)

    async def pause(
        self,
        mission_id: MissionId,
        *,
        status: MissionStatus = MissionStatus.PAUSED,
        blocker: dict | None = None,
    ) -> Mission:
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.RUNNING:
            self._reject(mission, status)
        if status not in self._RESUMABLE:
            raise MissionTransitionError(
                f"{status.value} is not a resumable pause state"
            )
        if blocker:
            mission.blockers.append(deepcopy(blocker))
        return await self._transition(mission, status)

    async def resume(self, mission_id: MissionId) -> Mission:
        mission = await self._require(mission_id)
        if mission.status not in self._RESUMABLE:
            self._reject(mission, MissionStatus.RUNNING)
        return await self._transition(mission, MissionStatus.RUNNING)

    async def complete(
        self,
        mission_id: MissionId,
        *,
        output: str = "",
        artifacts: list[str] | None = None,
    ) -> MissionResult:
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.RUNNING:
            self._reject(mission, MissionStatus.COMPLETED)
        mission.artifacts.extend(artifacts or [])
        mission = await self._transition(
            mission,
            MissionStatus.COMPLETED,
        )
        return MissionResult(
            mission_id=mission.id,
            status=mission.status,
            output=output,
            success=True,
            artifacts=list(mission.artifacts),
        )

    async def get(self, mission_id: MissionId) -> Mission | None:
        mission = await self._store.get(mission_id)
        return deepcopy(mission) if mission is not None else None

    async def _require(self, mission_id: MissionId) -> Mission:
        mission = await self._store.get(mission_id)
        if mission is None:
            raise KeyError(f"Mission {mission_id} not found")
        return mission

    async def _transition(
        self,
        mission: Mission,
        status: MissionStatus,
    ) -> Mission:
        if mission.status in self._TERMINAL:
            self._reject(mission, status)
        mission.status = status
        mission.updated_at = utcnow()
        await self._store.save(mission)
        return deepcopy(mission)

    @staticmethod
    def _reject(mission: Mission, target: MissionStatus) -> None:
        raise MissionTransitionError(
            f"Cannot transition mission from "
            f"{mission.status.value} to {target.value}"
        )
