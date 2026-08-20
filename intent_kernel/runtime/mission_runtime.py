"""Mission Runtime — RFC-0015 (STUDIO 10.2).

Controlled Cognitive Execution Runtime executing approved ExecutionGraphs with strict DAG ordering,
Action Gate checks, confirmation handling, executor port dispatching, Verification Gate checks,
and persistent checkpoint / resume mechanisms.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from intent_kernel.instructions import (
    MissionConstraint,
    OutputContract,
    OutputContractValidator,
)
from intent_kernel.runtime.action_gate import ActionGate
from intent_kernel.runtime.checkpoints import (
    InMemoryCheckpointRepository,
    MissionCheckpointRepositoryPort,
)
from intent_kernel.runtime.executor_port import (
    ActionExecutorPort,
    InMemoryActionExecutor,
)
from intent_kernel.runtime.models import (
    ActionContract,
    ActionGateDecision,
    ConfirmationState,
    ExecutionConfirmationRequest,
    FailureCategory,
    FailureReport,
    MissionCheckpoint,
    MissionRuntimeInstance,
    MissionRuntimeState,
    RuntimeNode,
    RuntimeNodeState,
    RuntimeTraceRecord,
    SideEffectLevel,
    VerificationStatus,
)
from intent_kernel.runtime.verification import (
    MissionCompletionGate,
    VerificationGate,
)
from intent_kernel.time_utils import utc_iso


class MissionRuntime:
    """Controlled cognitive execution runtime engine."""

    def __init__(
        self,
        executor: Optional[ActionExecutorPort] = None,
        checkpoint_repo: Optional[MissionCheckpointRepositoryPort] = None,
        rrm_service: Optional[Any] = None,
        constitution: Optional[Any] = None,
        mission_engine: Optional[Any] = None,
    ) -> None:
        self.executor = executor or InMemoryActionExecutor()
        self.checkpoint_repo = checkpoint_repo or InMemoryCheckpointRepository()
        self.action_gate = ActionGate(rrm_service=rrm_service, constitution=constitution)
        self.verification_gate = VerificationGate()
        self.completion_gate = MissionCompletionGate()
        self.mission_engine = mission_engine

        self._instances: Dict[str, MissionRuntimeInstance] = {}
        self._confirmations: Dict[str, ExecutionConfirmationRequest] = {}
        self._traces: List[RuntimeTraceRecord] = []
        self._failure_reports: List[FailureReport] = []
        self._completed_missions_count = 0
        self._failed_missions_count = 0

    def create_instance(
        self,
        mission_id: str,
        execution_graph_id: str,
        nodes: List[RuntimeNode],
        project_id: str = "GLOBAL",
        execution_policy: Optional[Dict[str, Any]] = None,
    ) -> MissionRuntimeInstance:
        """Create a new MissionRuntimeInstance with initialized nodes."""
        instance = MissionRuntimeInstance(
            mission_id=mission_id,
            execution_graph_id=execution_graph_id,
            project_id=project_id,
            status=MissionRuntimeState.CREATED,
            execution_policy=execution_policy or {},
        )

        for n in nodes:
            instance.nodes[n.node_id] = n
            instance.pending_nodes.append(n.node_id)

        instance.status = MissionRuntimeState.READY
        self._instances[instance.runtime_id] = instance
        return instance

    def get_instance(self, runtime_id: str) -> Optional[MissionRuntimeInstance]:
        """Retrieve an active or stored runtime instance."""
        return self._instances.get(runtime_id)

    async def run_mission(
        self,
        runtime_id: str,
        mission_constraints: Optional[List[MissionConstraint]] = None,
        output_contract: Optional[OutputContract] = None,
        final_output_candidate: Optional[str] = None,
    ) -> MissionRuntimeInstance:
        """Run or resume execution of a mission instance."""
        instance = self._instances.get(runtime_id)
        if not instance:
            raise ValueError(f"Runtime instance {runtime_id} not found.")

        if instance.status in (MissionRuntimeState.COMPLETED, MissionRuntimeState.FAILED, MissionRuntimeState.CANCELLED):
            return instance

        await self._ensure_lifecycle_running(instance)
        instance.status = MissionRuntimeState.RUNNING
        if not instance.started_at:
            instance.started_at = utc_iso()

        # DAG Execution Loop
        while True:
            ready_nodes = self._get_ready_nodes(instance)
            if not ready_nodes:
                break

            for node in ready_nodes:
                contract = node.action_contract or ActionContract(capability=node.capability)

                # Check ActionGate
                conf_req = self._get_pending_confirmation_for_node(instance.mission_id, contract.action_id)
                gate_decision = await self.action_gate.evaluate(
                    node=node,
                    contract=contract,
                    mission_constraints=mission_constraints,
                    execution_policy=instance.execution_policy,
                    confirmation=conf_req,
                )

                if gate_decision == ActionGateDecision.DENY:
                    node.state = RuntimeNodeState.BLOCKED
                    if node.node_id in instance.pending_nodes:
                        instance.pending_nodes.remove(node.node_id)
                    instance.blocked_nodes.append(node.node_id)

                    report = FailureReport(
                        runtime_id=instance.runtime_id,
                        mission_id=instance.mission_id,
                        node_id=node.node_id,
                        category=FailureCategory.POLICY_BLOCK,
                        message=f"ActionGate denied execution of node {node.node_id}.",
                        retryable=False,
                    )
                    self._failure_reports.append(report)
                    instance.status = MissionRuntimeState.BLOCKED
                    await self.save_checkpoint(instance)
                    await self._sync_lifecycle(instance)
                    return instance

                elif gate_decision == ActionGateDecision.REQUIRE_CONFIRMATION:
                    node.state = RuntimeNodeState.WAITING_CONFIRMATION
                    instance.status = MissionRuntimeState.WAITING_USER_CONFIRMATION

                    # Generate confirmation request if not already present
                    if not conf_req:
                        conf_req = ExecutionConfirmationRequest(
                            mission_id=instance.mission_id,
                            action_id=contract.action_id,
                            description=f"Action node {node.node_id} requires confirmation for side-effects.",
                            effect=f"Execute capability {contract.capability}",
                            reversibility=contract.reversibility,
                            risk_level=contract.risk_level,
                            runtime_id=instance.runtime_id,
                        )
                        self._confirmations[conf_req.confirmation_id] = conf_req

                    await self.save_checkpoint(instance)
                    await self._sync_lifecycle(instance)
                    return instance

                elif gate_decision == ActionGateDecision.WAIT_RESOURCE:
                    node.state = RuntimeNodeState.WAITING_RESOURCE
                    instance.status = MissionRuntimeState.WAITING_RESOURCE

                    report = FailureReport(
                        runtime_id=instance.runtime_id,
                        mission_id=instance.mission_id,
                        node_id=node.node_id,
                        category=FailureCategory.RESOURCE_UNAVAILABLE,
                        message=f"Resource for node {node.node_id} is unavailable.",
                        retryable=True,
                    )
                    self._failure_reports.append(report)
                    await self.save_checkpoint(instance)
                    await self._sync_lifecycle(instance)
                    return instance

                # Proceed to Execute
                node.state = RuntimeNodeState.EXECUTING
                node.attempt_count += 1

                try:
                    raw_result = await self.executor.execute(contract)
                    node.result = raw_result

                    # Post-execution verification gate
                    verif_status, evidence = await self.verification_gate.evaluate_node(
                        node=node,
                        action=contract,
                        result=raw_result,
                    )
                    node.verification_result = verif_status
                    instance.completion_evidence.append(evidence.to_dict())

                    if verif_status == VerificationStatus.VERIFIED_SUCCESS:
                        node.state = RuntimeNodeState.SUCCEEDED
                        if node.node_id in instance.pending_nodes:
                            instance.pending_nodes.remove(node.node_id)
                        if node.node_id not in instance.completed_nodes:
                            instance.completed_nodes.append(node.node_id)

                        # Record idempotency key execution
                        if contract.idempotency_key:
                            self.action_gate.mark_idempotency_key_executed(contract.idempotency_key)
                    else:
                        node.state = RuntimeNodeState.FAILED
                        if node.node_id in instance.pending_nodes:
                            instance.pending_nodes.remove(node.node_id)
                        instance.failed_nodes.append(node.node_id)

                        report = FailureReport(
                            runtime_id=instance.runtime_id,
                            mission_id=instance.mission_id,
                            node_id=node.node_id,
                            category=FailureCategory.VALIDATION_FAILURE,
                            message=f"Verification failed for node {node.node_id}.",
                            retryable=node.attempt_count < contract.retry_policy.get("max_attempts", 3),
                        )
                        self._failure_reports.append(report)

                except Exception as ex:
                    node.state = RuntimeNodeState.FAILED
                    node.error_message = str(ex)
                    if node.node_id in instance.pending_nodes:
                        instance.pending_nodes.remove(node.node_id)
                    instance.failed_nodes.append(node.node_id)

                    report = FailureReport(
                        runtime_id=instance.runtime_id,
                        mission_id=instance.mission_id,
                        node_id=node.node_id,
                        category=FailureCategory.EXECUTION_FAILURE,
                        message=str(ex),
                        retryable=node.attempt_count < contract.retry_policy.get("max_attempts", 3),
                    )
                    self._failure_reports.append(report)

                # Record Trace
                trace = RuntimeTraceRecord(
                    runtime_id=instance.runtime_id,
                    mission_id=instance.mission_id,
                    node_id=node.node_id,
                    action=contract.capability,
                    state_before="READY",
                    state_after=node.state.value,
                    result_status=str(node.result),
                    verification_status=node.verification_result.value if node.verification_result else "",
                )
                self._traces.append(trace)

                await self.save_checkpoint(instance)

        # Evaluate Whole Mission Completion
        if len(instance.failed_nodes) > 0:
            instance.status = MissionRuntimeState.FAILED
            self._failed_missions_count += 1
            await self.save_checkpoint(instance)
            await self._sync_lifecycle(instance)
            return instance

        if len(instance.completed_nodes) == len(instance.nodes):
            completion_decision = await self.completion_gate.decide(
                instance=instance,
                final_output=final_output_candidate,
                output_contract=output_contract,
                constraints=mission_constraints,
            )

            instance.completion_evidence.extend(
                completion_decision.completion_evidence
            )
            instance.completion_authority = completion_decision.authority

            if completion_decision.allowed:
                instance.status = MissionRuntimeState.COMPLETED
                instance.completed_at = utc_iso()
                instance.verification_status = VerificationStatus.VERIFIED_SUCCESS
                self._completed_missions_count += 1
            else:
                instance.status = MissionRuntimeState.BLOCKED
                instance.verification_status = VerificationStatus.VERIFIED_FAILURE

            await self.save_checkpoint(instance)
            await self._sync_lifecycle(
                instance,
                completion_decision=completion_decision,
                output=final_output_candidate or "",
            )

        return instance

    async def _sync_lifecycle(
        self,
        instance: MissionRuntimeInstance,
        *,
        completion_decision: Any | None = None,
        output: str = "",
    ) -> None:
        if self.mission_engine is None:
            return
        lifecycle = await self.mission_engine.synchronize_runtime_state(
            self._mission_id(instance.mission_id),
            instance.status.value,
            completion_decision=completion_decision,
            output=output,
        )
        instance.lifecycle_status = lifecycle.status.value

    async def _ensure_lifecycle_running(
        self,
        instance: MissionRuntimeInstance,
    ) -> None:
        """Resume only the canonical record before a controlled runtime retry."""
        if self.mission_engine is None:
            return
        mission_id = self._mission_id(instance.mission_id)
        lifecycle = await self.mission_engine.get(mission_id)
        if lifecycle is None:
            raise ValueError(
                f"Canonical Mission {instance.mission_id} not found for runtime"
            )
        if lifecycle.status.value in {
            "paused",
            "blocked",
            "waiting_for_information",
            "waiting_for_decision",
            "waiting_for_permission",
            "failed_recoverable",
        }:
            lifecycle = await self.mission_engine.resume(mission_id)
        instance.lifecycle_status = lifecycle.status.value

    @staticmethod
    def _mission_id(value: str) -> Any:
        from intent_kernel.contracts import MissionId

        return MissionId(value)

    def submit_confirmation(self, confirmation_id: str, approved: bool) -> Optional[ExecutionConfirmationRequest]:
        """Submit user confirmation or refusal for a pending action node.

        Only a requirement in the canonical ``WAITING_CONFIRMATION`` state may
        be approved; replaying an already confirmed/consumed/expired/rejected
        requirement is a no-op (defense in depth for Movement 14).
        """
        conf = self._confirmations.get(confirmation_id)
        if not conf:
            return None
        if conf.state is not ConfirmationState.WAITING_CONFIRMATION:
            return conf

        conf.approved = approved
        conf.approved_at = utc_iso()

        # Update runtime instance if waiting confirmation
        for instance in self._instances.values():
            if instance.mission_id == conf.mission_id and instance.status == MissionRuntimeState.WAITING_USER_CONFIRMATION:
                instance.status = MissionRuntimeState.READY

        return conf

    def get_confirmation(self, confirmation_id: str) -> Optional[ExecutionConfirmationRequest]:
        """Public lookup of any confirmation requirement by its typed ID."""
        return self._confirmations.get(confirmation_id)

    def get_pending_confirmation(self, mission_id: str) -> Optional[ExecutionConfirmationRequest]:
        """Return the active WAITING_CONFIRMATION requirement for a Mission."""
        for conf in self._confirmations.values():
            if conf.mission_id == mission_id and conf.state is ConfirmationState.WAITING_CONFIRMATION:
                return conf
        return None

    def cancel_instance(self, mission_id: str) -> None:
        """Cancel runtime instances of a Mission (used by canonical rejection)."""
        for instance in self._instances.values():
            if instance.mission_id != mission_id:
                continue
            if instance.status in (MissionRuntimeState.COMPLETED, MissionRuntimeState.CANCELLED):
                continue
            instance.status = MissionRuntimeState.CANCELLED
            for node in instance.nodes.values():
                if node.state in (
                    RuntimeNodeState.PENDING,
                    RuntimeNodeState.READY,
                    RuntimeNodeState.WAITING_CONFIRMATION,
                    RuntimeNodeState.WAITING_RESOURCE,
                ):
                    node.state = RuntimeNodeState.CANCELLED

    async def pause(self, runtime_id: str) -> Optional[MissionRuntimeInstance]:
        """Pause execution of an active mission and create a checkpoint."""
        instance = self._instances.get(runtime_id)
        if not instance:
            return None

        if instance.status in (MissionRuntimeState.RUNNING, MissionRuntimeState.READY):
            instance.status = MissionRuntimeState.PAUSED
            await self.save_checkpoint(instance)

        return instance

    async def resume(self, runtime_id: str) -> Optional[MissionRuntimeInstance]:
        """Resume execution of a paused or restarted mission from its latest checkpoint."""
        # Load latest checkpoint if available
        chk = await self.checkpoint_repo.get_latest_checkpoint(runtime_id)
        instance = self._instances.get(runtime_id)

        if chk and instance:
            instance.completed_nodes = chk.completed_nodes.copy()
            instance.pending_nodes = [n for n in instance.nodes.keys() if n not in instance.completed_nodes]
            # H1.4: Restore completion_evidence from checkpoint
            instance.completion_evidence = chk.completion_evidence.copy()
            instance.status = MissionRuntimeState.READY

            # H1.4: Validate evidence before restoring verification state
            for nid in instance.completed_nodes:
                if nid in instance.nodes:
                    instance.nodes[nid].state = RuntimeNodeState.SUCCEEDED
                    # H1.4: Reset verification_result — rebuild from checkpoint evidence only
                    instance.nodes[nid].verification_result = None

                    # Check checkpoint has verification evidence for this node
                    chk_evidence = chk.verification_state.get(nid, {})
                    claimed_status = chk_evidence.get("verification_result", "")

                    if (
                        claimed_status == VerificationStatus.VERIFIED_SUCCESS.value
                        and self._validate_resume_evidence(
                            nid, claimed_status, chk.completion_evidence
                        )
                    ):
                        # Evidence valid — restore verified state
                        instance.nodes[nid].verification_result = VerificationStatus.VERIFIED_SUCCESS
                    else:
                        # H1.4: Evidence missing or invalid — do not trust verified claim
                        instance.nodes[nid].verification_result = VerificationStatus.INCONCLUSIVE

        if instance and instance.status in (MissionRuntimeState.PAUSED, MissionRuntimeState.READY):
            instance.status = MissionRuntimeState.RUNNING

        return instance

    async def save_checkpoint(self, instance: MissionRuntimeInstance) -> MissionCheckpoint:
        """Create and persist a checkpoint for the instance."""
        # H1.4: Persist per-node verification state and evidence
        verification_state: Dict[str, Any] = {}
        for nid, node in instance.nodes.items():
            if node.verification_result is not None:
                verification_state[nid] = {
                    "verification_result": node.verification_result.value,
                    "evidence_id": self._find_evidence_id(instance, nid),
                }

        chk = MissionCheckpoint(
            runtime_id=instance.runtime_id,
            mission_id=instance.mission_id,
            runtime_status=instance.status,
            completed_nodes=instance.completed_nodes.copy(),
            pending_nodes=instance.pending_nodes.copy(),
            failed_nodes=instance.failed_nodes.copy(),
            correlation_id=instance.correlation_id,
            verification_state=verification_state,
            completion_evidence=instance.completion_evidence.copy(),
        )
        await self.checkpoint_repo.save_checkpoint(chk)
        instance.checkpoint_id = chk.checkpoint_id
        return chk

    # --- H1.4 Resume Verification Evidence ---

    def _find_evidence_id(self, instance: MissionRuntimeInstance, node_id: str) -> str:
        """Find the evidence_id for a node's verification evidence."""
        for ev in instance.completion_evidence:
            details = ev.get("details", {})
            if details.get("node_id") == node_id:
                return ev.get("evidence_id", "")
        return ""

    def _validate_resume_evidence(
        self,
        node_id: str,
        claimed_status: str,
        evidence_list: List[Dict[str, Any]],
    ) -> bool:
        """Validate that verification evidence is consistent for a node on resume.

        Returns True only if:
        - An evidence entry exists for this node
        - The evidence source is VerificationGate
        - The evidence claims verified=True
        - The evidence verification_status matches the claimed status
        """
        for ev in evidence_list:
            details = ev.get("details", {})
            if details.get("node_id") != node_id:
                continue
            # Evidence must originate from VerificationGate
            if ev.get("source") != "VerificationGate":
                return False
            # Evidence must claim verified
            if not ev.get("verified", False):
                return False
            # Evidence verification_status must match claimed status
            ev_status = details.get("verification_status", "")
            if ev_status != claimed_status:
                return False
            return True
        return False

    def _get_ready_nodes(self, instance: MissionRuntimeInstance) -> List[RuntimeNode]:
        """Find pending nodes whose dependencies are ALL satisfied."""
        ready: List[RuntimeNode] = []
        for nid in instance.pending_nodes:
            node = instance.nodes.get(nid)
            if not node:
                continue
            if node.state not in (RuntimeNodeState.PENDING, RuntimeNodeState.READY, RuntimeNodeState.WAITING_CONFIRMATION):
                continue

            # Check dependencies
            deps_satisfied = all(
                dep in instance.completed_nodes and instance.nodes[dep].state == RuntimeNodeState.SUCCEEDED
                for dep in node.dependencies
            )
            if deps_satisfied:
                ready.append(node)

        return ready

    def _get_pending_confirmation_for_node(self, mission_id: str, action_id: str) -> Optional[ExecutionConfirmationRequest]:
        """Lookup pending user confirmation request for a mission and action ID."""
        for conf in self._confirmations.values():
            if conf.mission_id == mission_id and conf.action_id == action_id:
                return conf
        return None

    async def get_diagnostics(self) -> Dict[str, Any]:
        """Produce safe diagnostic metrics without exposing sensitive data."""
        return {
            "active_runtime_count": len(self._instances),
            "running_nodes": sum(1 for inst in self._instances.values() for n in inst.nodes.values() if n.state == RuntimeNodeState.EXECUTING),
            "waiting_confirmation": sum(1 for inst in self._instances.values() if inst.status == MissionRuntimeState.WAITING_USER_CONFIRMATION),
            "waiting_resource": sum(1 for inst in self._instances.values() if inst.status == MissionRuntimeState.WAITING_RESOURCE),
            "failed_nodes": sum(len(inst.failed_nodes) for inst in self._instances.values()),
            "completed_missions": self._completed_missions_count,
            "completion_authority": "MissionCompletionGate",
            "lifecycle_authority": "MissionEngine",
            "failed_missions": self._failed_missions_count,
            "failure_reports_count": len(self._failure_reports),
            "trace_records_count": len(self._traces),
        }
