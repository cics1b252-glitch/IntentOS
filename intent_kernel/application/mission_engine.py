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
from intent_kernel.runtime.verification import MissionCompletionDecision


class MissionTransitionError(ValueError):
    """Raised when a lifecycle transition is not currently valid."""


class MissionCompletionEvidenceError(MissionTransitionError):
    """Raised when a caller attempts completion without canonical evidence."""


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

    async def reject(self, mission_id: MissionId) -> Mission:
        """Move a pending-decision Mission to the canonical non-executing CANCELLED state.

        Rejection is part of the typed confirmation protocol: it transitions a
        Mission that is awaiting a user decision (WAITING_FOR_DECISION) to the
        canonical CANCELLED state so no controlled execution can ever resume.
        """
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.WAITING_FOR_DECISION:
            self._reject(mission, MissionStatus.CANCELLED)
        return await self._transition(mission, MissionStatus.CANCELLED)

    async def complete(
        self,
        mission_id: MissionId,
        *,
        completion_decision: MissionCompletionDecision | None = None,
        output: str = "",
        artifacts: list[str] | None = None,
    ) -> MissionResult:
        """Complete only with an allowed MissionCompletionGate decision."""
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.RUNNING:
            self._reject(mission, MissionStatus.COMPLETED)
        if not isinstance(completion_decision, MissionCompletionDecision):
            raise MissionCompletionEvidenceError(
                "Mission completion requires a MissionCompletionGate decision"
            )
        if completion_decision.authority != "MissionCompletionGate":
            raise MissionCompletionEvidenceError(
                "Mission completion decision has an invalid authority"
            )
        if completion_decision.mission_id != str(mission.id):
            raise MissionCompletionEvidenceError(
                "Mission completion decision identity does not match lifecycle record"
            )
        if not completion_decision.evidence_complete:
            raise MissionCompletionEvidenceError(
                "Mission completion requires execution, verification and completion evidence"
            )
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
            evidence=[
                *completion_decision.execution_evidence,
                *completion_decision.verification_evidence,
                *completion_decision.completion_evidence,
            ],
            artifacts=list(mission.artifacts),
            metadata={"completion_authority": completion_decision.authority},
        )

    async def await_verification(self, mission_id: MissionId) -> Mission:
        """Record that execution returned but canonical verification is pending."""
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.RUNNING:
            self._reject(mission, MissionStatus.VERIFYING)
        return await self._transition(mission, MissionStatus.VERIFYING)

    async def synchronize_runtime_state(
        self,
        mission_id: MissionId,
        runtime_state: str,
        *,
        completion_decision: MissionCompletionDecision | None = None,
        output: str = "",
    ) -> Mission | MissionResult:
        """Apply a controlled-runtime report to the canonical lifecycle record."""
        normalized = str(runtime_state).upper()
        if normalized == "COMPLETED":
            if completion_decision is None:
                raise MissionCompletionEvidenceError(
                    "Runtime completion requires a canonical completion decision"
                )
            return await self.complete(
                mission_id,
                completion_decision=completion_decision,
                output=output,
            )

        targets = {
            "WAITING_USER_CONFIRMATION": MissionStatus.WAITING_FOR_DECISION,
            "WAITING_RESOURCE": MissionStatus.WAITING_FOR_INFORMATION,
            "BLOCKED": MissionStatus.BLOCKED,
            "PAUSED": MissionStatus.PAUSED,
            "FAILED": MissionStatus.FAILED_RECOVERABLE,
        }
        target = targets.get(normalized)
        mission = await self._require(mission_id)
        if target is None or mission.status is target:
            return deepcopy(mission)
        if mission.status is not MissionStatus.RUNNING:
            self._reject(mission, target)
        return await self.pause(
            mission_id,
            status=target,
            blocker={
                "source": "MissionRuntime",
                "runtime_state": normalized,
                "transition_authority": "MissionEngine",
            },
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
