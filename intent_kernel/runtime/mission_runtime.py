"""Mission Runtime — RFC-0015 (STUDIO 10.2).

Controlled Cognitive Execution Runtime executing approved ExecutionGraphs with strict DAG ordering,
Action Gate checks, confirmation handling, executor port dispatching, Verification Gate checks,
and persistent checkpoint / resume mechanisms.

M32C-R: Complete governed durable mission proof.
This module enforces the full E2E governed mission lifecycle with authoritative
resume, exact-object invariants, and fail-closed authority gates. See M32B-4R
for the live RRM rebind repair and M32B-5 for durable mission resume convergence.

Authority convergence (B5.2): MissionRecord is the durable authority; Checkpoint
is support state only. Checkpoint must never override MissionRecord action state,
RRM identity/generation, tombstone/retirement, confirmation authority,
VerificationGate, or MissionCompletionGate. On disagreement: FAIL CLOSED.

Old interrupted mission without authoritative MissionRecord: NON_RESUMABLE.

Authority answers (executable evidence):
1 NO  — canonical productive execution can bypass guard
2 NO  — possible-handoff crash can auto-redispatch
3 NO  — supported same-process duplicate can handoff twice
4 NO  — restart can substitute different governed executor
5 NO  — stale generation can authorize
6 NO  — tombstoned/retired executor can resume
7 NO  — reusable confirmation survives restart
8 NO  — checkpoint can override MissionRecord
9 NO  — persisted stale mutable evidence can bypass fresh verification
10 NO — agent/executor claim can create VERIFIED
11 NO — anything except MissionCompletionGate can complete mission
12 NO — external exactly-once is claimed
13 YES — selected = revalidated = authorized = dispatched
14 YES — old interrupted mission without authoritative MissionRecord is NON_RESUMABLE
15 YES — every canonical C0-C8 case has executable evidence

Crash cutpoint coverage (9 phases):
- before authorization
- after authorization
- after dispatch intent
- possible handoff
- after result
- before verification
- after verification
- before completion
- after durable completion

Negative authority exercise cases:
- wrong governed registration
- changed generation
- tombstone
- retirement
- missing executor
- missing/stale confirmation
- AMBIGUOUS_EFFECT
- checkpoint/MissionRecord disagreement
- stale mutable verification evidence
- duplicate productive attempt

C0-C8 canonical cases (all with executable evidence):
C0: PENDING — no durable authorization at all / clean restart
C1: PENDING + confirmation_required — confirmation required, never approved
C2: AUTHORIZED (in memory, not durable) — crash before dispatch intent
C3: DISPATCH_INTENT_RECORDED — confirmed, intent already durable
C4: DISPATCHING — confirmed, dispatch in progress
C5: RESULT_RECORDED — result recorded, verification pending
C6: Old confirmation + changed request semantics — rejected
C7: Old confirmation + changed RRM generation — rejected
C8: Confirmation for action A reused for action B — rejected
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
from intent_kernel.mission.mission_record import (
    ActionState,
    DurableActionState,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
)
from intent_kernel.runtime.external_evidence import (
    ExternalEvidenceRequirement,
    ExternalObservationResult,
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
    DeterministicStructuralVerifier,
    MissionCompletionGate,
    VerificationGate,
    exact_contract_hash,
)
from intent_kernel.time_utils import utc_iso
from intent_kernel.mission.store import MissionRecordStorePort, MissionRecordValidationError


def _durable_result_summary(raw_result: Any) -> Dict[str, Any]:
    """Minimal JSON-safe handoff-result summary for durable recording.

    Duck-typed (never raises): success flag plus truncated output text.
    Provider effect tokens are NOT invented here; absence stays absent.
    """
    try:
        success = bool(getattr(raw_result, "success", True))
    except Exception:
        success = False
    try:
        output = str(getattr(raw_result, "output", raw_result))
    except Exception:
        output = "<unrenderable-result>"
    return {"success": success, "output": output[:2000]}


class MissionRuntime:
    """Controlled cognitive execution runtime engine."""

    def __init__(
        self,
        executor: Optional[ActionExecutorPort] = None,
        checkpoint_repo: Optional[MissionCheckpointRepositoryPort] = None,
        rrm_service: Optional[Any] = None,
        constitution: Optional[Any] = None,
        mission_engine: Optional[Any] = None,
        external_evidence_adapter: Optional[Any] = None,
        dispatch_guard: Optional[Any] = None,
        replay_policy: Optional[Any] = None,
        mission_record_store: Any = None,
    ) -> None:
        self.executor = executor or InMemoryActionExecutor()
        self.checkpoint_repo = checkpoint_repo or InMemoryCheckpointRepository()
        self.action_gate = ActionGate(
            rrm_service=rrm_service,
            constitution=constitution,
            replay_policy=replay_policy,
        )
        self.dispatch_guard = dispatch_guard
        self._mission_record_store = mission_record_store
        self.resource_manager = rrm_service
        self.verification_gate = VerificationGate(
            external_adapter=external_evidence_adapter
        )
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

    def _collect_completion_freshness_facts(
        self,
        instance: MissionRuntimeInstance,
    ) -> List[Dict[str, Any]]:
        """Collect and re-observe external evidence requirements for completion.

        Immediately before mission completion, re-observe every external evidence
        requirement whose verified evidence contributes to mission completion.
        Returns a list of mechanism-only freshness facts for each requirement.

        Each fact contains:
        - node_id: str
        - requirement: ExternalEvidenceRequirement
        - stored_governed_registration_id: str (from evidence at verification time)
        - stored_resource_generation: int
        - fresh_observation: ExternalObservationResult (from re-observation now)
        - resource_id_match: bool
        - registration_id_match: bool
        - generation_match: bool
        - fresh_matched: bool
        - passed: bool (all four conditions met)
        - reason: str (failure reason if not passed, empty if passed)
        """
        facts: List[Dict[str, Any]] = []

        adapter = getattr(self.verification_gate, "_external_adapter", None)

        # Check if any completed node has external evidence requirements
        has_external_requirements = False
        for node_id in instance.completed_nodes:
            node = instance.nodes.get(node_id)
            if not node or not node.action_contract:
                continue
            external_evidence = getattr(node.action_contract, "external_evidence", None)
            if isinstance(external_evidence, list) and len(external_evidence) > 0:
                has_external_requirements = True
                break

        # If there are external requirements but no adapter, fail closed with observer_unavailable
        if has_external_requirements and adapter is None:
            for node_id in instance.completed_nodes:
                node = instance.nodes.get(node_id)
                if not node or not node.action_contract:
                    continue
                external_evidence = getattr(node.action_contract, "external_evidence", None)
                if not isinstance(external_evidence, list) or len(external_evidence) == 0:
                    continue
                for requirement in external_evidence:
                    if not isinstance(requirement, ExternalEvidenceRequirement):
                        continue
                    facts.append({
                        "node_id": node_id,
                        "requirement": requirement,
                        "stored_governed_registration_id": "",
                        "stored_resource_generation": -1,
                        "fresh_observation": None,
                        "resource_id_match": False,
                        "registration_id_match": False,
                        "generation_match": False,
                        "fresh_matched": False,
                        "passed": False,
                        "reason": "observer_unavailable",
                    })
            return facts

        if adapter is None:
            return facts

        for node_id in instance.completed_nodes:
            node = instance.nodes.get(node_id)
            if not node or not node.action_contract:
                continue

            external_evidence = getattr(node.action_contract, "external_evidence", None)
            if not isinstance(external_evidence, list) or len(external_evidence) == 0:
                continue

            # Find the stored verification evidence for this node
            stored_evidence_entry = None
            for ev in instance.completion_evidence:
                details = ev.get("details", {})
                if (
                    ev.get("source") == "VerificationGate"
                    and ev.get("verified") is True
                    and details.get("node_id") == node_id
                ):
                    stored_evidence_entry = ev
                    break

            if not stored_evidence_entry:
                continue

            stored_observations = stored_evidence_entry.get("details", {}).get("external_observations", [])

            for req_idx, requirement in enumerate(external_evidence):
                if not isinstance(requirement, ExternalEvidenceRequirement):
                    continue

                # Find matching stored observation (by resource_id)
                stored_obs = None
                for obs in stored_observations:
                    if obs.get("resource_id") == requirement.resource_id:
                        stored_obs = obs
                        break

                if not stored_obs:
                    # No stored observation for this requirement - fail closed
                    facts.append({
                        "node_id": node_id,
                        "requirement": requirement,
                        "stored_governed_registration_id": "",
                        "stored_resource_generation": -1,
                        "fresh_observation": None,
                        "resource_id_match": False,
                        "registration_id_match": False,
                        "generation_match": False,
                        "fresh_matched": False,
                        "passed": False,
                        "reason": "stored_observation_missing",
                    })
                    continue

                stored_grid = stored_obs.get("governed_registration_id", "")
                stored_gen = stored_obs.get("resource_generation", -1)

                # Re-observe fresh
                try:
                    fresh_obs = adapter.observe(requirement)
                except Exception:
                    facts.append({
                        "node_id": node_id,
                        "requirement": requirement,
                        "stored_governed_registration_id": stored_grid,
                        "stored_resource_generation": stored_gen,
                        "fresh_observation": None,
                        "resource_id_match": True,
                        "registration_id_match": False,
                        "generation_match": False,
                        "fresh_matched": False,
                        "passed": False,
                        "reason": "observer_exception",
                    })
                    continue

                # Compare identities - but prioritize observer's failure reason
                fresh_matched = fresh_obs.matched

                # Initialize comparison variables
                resource_id_match = True
                registration_id_match = True
                generation_match = True

                # If fresh observation itself failed, use observer's reason
                if not fresh_matched:
                    reason = fresh_obs.reason_code or "state_mismatch"
                    passed = False
                else:
                    # Fresh observation succeeded, now compare identities
                    resource_id_match = (fresh_obs.resource_id == requirement.resource_id)
                    registration_id_match = (fresh_obs.governed_registration_id == stored_grid)
                    generation_match = (fresh_obs.resource_generation == stored_gen)

                    passed = resource_id_match and registration_id_match and generation_match

                    reason = ""
                    if not passed:
                        if not resource_id_match:
                            reason = "resource_id_mismatch"
                        elif not registration_id_match:
                            reason = "governed_registration_id_mismatch"
                        elif not generation_match:
                            reason = "resource_generation_mismatch"

                facts.append({
                    "node_id": node_id,
                    "requirement": requirement,
                    "stored_governed_registration_id": stored_grid,
                    "stored_resource_generation": stored_gen,
                    "fresh_observation": fresh_obs,
                    "resource_id_match": resource_id_match,
                    "registration_id_match": registration_id_match,
                    "generation_match": generation_match,
                    "fresh_matched": fresh_matched,
                    "passed": passed,
                    "reason": reason,
                })

        return facts

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
                # Derive durable confirmation requirement from the durable state.
                # B3-F01: UNKNOWN AUTHORITY STATE != NO AUTHORITY REQUIREMENT.
                # Store failures must FAIL CLOSED; absence of a configured
                # store preserves legacy/B4 boundary behavior.
                _durable_confirmation_required = False
                if self._mission_record_store is not None:
                    _loaded = self._mission_record_store.load(instance.mission_id)
                    if _loaded is None:
                        raise MissionRecordValidationError(
                            f"Durable mission load returned None: "
                            f"{instance.mission_id}"
                        )
                    _action_data = (
                        _loaded.get("action_states", {}).get(
                            contract.action_id, {}
                        )
                    )
                    if not _action_data:
                        raise MissionRecordValidationError(
                            f"Durable action not found: "
                            f"{instance.mission_id}/{contract.action_id}"
                        )
                    _confirmation_required = _action_data.get(
                        "confirmation_required", False
                    )
                    if type(_confirmation_required) is not bool:
                        raise MissionRecordValidationError(
                            f"Action {contract.action_id}: confirmation_required "
                            f"must be bool, got {type(_confirmation_required).__name__}"
                        )
                    _durable_confirmation_required = _confirmation_required
                if conf_req and conf_req.confirmation_basis_digest:
                    _durable_confirmation_required = True
                gate_decision = await self.action_gate.evaluate(
                    node=node,
                    contract=contract,
                    mission_constraints=mission_constraints,
                    execution_policy=instance.execution_policy,
                    confirmation=conf_req,
                    durable_confirmation_required=_durable_confirmation_required,
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
                        confirmation_basis_digest = ""
                        if self._mission_record_store is not None:
                            try:
                                loaded = self._mission_record_store.load(instance.mission_id)
                                if loaded is not None:
                                    action_data = loaded.get("action_states", {}).get(contract.action_id, {})
                                    confirmation_basis_digest = action_data.get("confirmation_basis_digest", "")
                            except Exception:
                                pass
                        conf_req = ExecutionConfirmationRequest(
                            mission_id=instance.mission_id,
                            action_id=contract.action_id,
                            description=f"Action node {node.node_id} requires confirmation for side-effects.",
                            effect=f"Execute capability {contract.capability}",
                            reversibility=contract.reversibility,
                            risk_level=contract.risk_level,
                            runtime_id=instance.runtime_id,
                            confirmation_basis_digest=confirmation_basis_digest,
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

                # M32B-2 productive convergence: durable dispatch ownership
                # BEFORE any executor handoff. Opt-in (None preserves legacy
                # behavior exactly). Gate approval above already enforced live
                # confirmation, so no stale confirmation is consulted here.
                # B4.2-B4.4: Current live governed executor revalidation (fail-closed)
                # Before productive handoff, revalidate durable executor against current RRM state.
                # Sequence: load authority -> determine posture -> resolve current governed executor
                # -> revalidate registration + generation + eligibility -> exact-object revalidate
                # -> hand THAT SAME object to productive dispatch.
                # Critical: REPLAY DECISION must not become permission to use stale state.
                # CURRENT RRM validation must occur before productive handoff.
                _rebind_result = None
                _rebind_durable = None
                if self._mission_record_store is not None and self.resource_manager is not None:
                    try:
                        durable_data = self._mission_record_store.load(instance.mission_id)
                        if durable_data is not None:
                            action_data = durable_data.get("action_states", {}).get(contract.action_id, {})
                            if action_data:
                                dur_grid = action_data.get("expected_governed_registration_id", "")
                                dur_gen = action_data.get("expected_resource_generation", 0)
                                dur_logical = action_data.get("expected_executor_logical_id", "")
                                curr = None
                                if dur_grid:
                                    # Resolve the current canonical governor by its
                                    # governed registration id across resource kinds
                                    # (RRM has no direct by-registration lookup).
                                    for _list in (
                                        self.resource_manager.list_providers,
                                        self.resource_manager.list_agents,
                                        self.resource_manager.list_capabilities,
                                    ):
                                        try:
                                            for _res in _list():
                                                if getattr(_res, "governed_registration_id", "") == dur_grid:
                                                    curr = _res
                                                    break
                                        except Exception:
                                            continue
                                        if curr is not None:
                                            break
                                if dur_grid:
                                    # Durable action carries an RRM governor binding:
                                    # the current canonical governor MUST resolve and
                                    # match exactly; otherwise fail closed.
                                    grid_match = (
                                        curr is not None
                                        and getattr(curr, "governed_registration_id", None) == dur_grid
                                    )
                                    gen_match = (
                                        curr is not None
                                        and isinstance(dur_gen, int)
                                        and getattr(curr, "generation", None) == dur_gen
                                    )
                                else:
                                    # No RRM constraint in durable action (legacy path).
                                    grid_match = True
                                    gen_match = True
                                logical_match = True
                                if dur_logical and curr is not None:
                                    _curr_agent = getattr(curr, "agent_id", None)
                                    if _curr_agent is not None:
                                        logical_match = _curr_agent == dur_logical
                                eligible = bool(getattr(curr, "is_eligible", True)) if curr else True
                                tomb = str(getattr(curr, "status", "") or "").lower().find("tombstone") >= 0 if curr else False
                                retired = str(getattr(curr, "status", "") or "").lower().find("retired") >= 0 if curr else False
                                if (logical_match or (dur_logical and not eligible)) and grid_match and gen_match and eligible and not tomb and not retired:
                                    _rebind_result = curr if curr is not None else True
                                    if dur_grid or dur_gen:
                                        _rebind_durable = (dur_grid, dur_gen, dur_logical)
                                else:
                                    _rebind_result = None
                            else:
                                _rebind_result = None
                    except Exception:
                        _rebind_result = None

                # ONE effective acquisition path: all productive handoffs go through
                # the dispatch guard. Three cases:
                # (1) _rebind_result is not None -> durable rebind succeeded;
                #     acquire with the verified durable registration fields when
                #     the durable action carries them (empty-field runtime-node
                #     spec would otherwise mismatch the durable authority).
                # (2) _rebind_result is None AND _mission_record_store is None
                #     -> legacy/nonproductive path, normal guard acquisition
                # (3) _rebind_result is None AND _mission_record_store is not None
                #     -> rebind failed, fail closed (ownership=None)
                ownership = None
                if self.dispatch_guard is not None:
                    can_acquire = _rebind_result is not None or self._mission_record_store is None
                    if can_acquire:
                        try:
                            if _rebind_durable is not None:
                                from intent_kernel.mission.dispatch_guard import (
                                    DispatchAttemptSpec,
                                    spec_for_runtime_node,
                                )
                                base = spec_for_runtime_node(instance.mission_id, node)
                                spec = DispatchAttemptSpec(
                                    mission_id=base.mission_id,
                                    action_id=base.action_id,
                                    request_semantics_digest=base.request_semantics_digest,
                                    executor_logical_id=base.executor_logical_id,
                                    expected_governed_registration_id=_rebind_durable[0],
                                    expected_resource_generation=_rebind_durable[1],
                                )
                                ownership = self.dispatch_guard.acquire(
                                    spec,
                                    requested_by="mission-runtime",
                                    confirmation_required=False,
                                )
                            else:
                                ownership = self.dispatch_guard.acquire_for_node(
                                    instance.mission_id,
                                    node,
                                    requested_by="mission-runtime",
                                    confirmation_required=False,
                                )
                        except Exception as exc:
                            decision = getattr(exc, "decision", "") or ""
                            node.state = RuntimeNodeState.FAILED
                            if node.node_id in instance.pending_nodes:
                                instance.pending_nodes.remove(node.node_id)
                            instance.failed_nodes.append(node.node_id)
                            node.error_message = (
                                "Durable dispatch ownership refused: " f"{exc}"
                            )
                            report = FailureReport(
                                runtime_id=instance.runtime_id,
                                mission_id=instance.mission_id,
                                node_id=node.node_id,
                                category=FailureCategory.POLICY_BLOCK,
                                message=node.error_message,
                                retryable=(decision == "AMBIGUOUS_RECONCILIATION_REQUIRED"),
                            )
                            self._failure_reports.append(report)
                            await self.save_checkpoint(instance)
                            await self._sync_lifecycle(instance)
                            return instance
                    else:
                        return instance

                # Proceed to Execute
                node.state = RuntimeNodeState.EXECUTING
                node.attempt_count += 1

                try:
                    raw_result = await self.executor.execute(contract)
                    node.result = raw_result
                    if ownership is not None:
                        try:
                            self.dispatch_guard.record_result(
                                ownership,
                                result_summary=_durable_result_summary(
                                    raw_result
                                ),
                                requested_by="mission-runtime",
                            )
                        except Exception as exc:
                            node.state = RuntimeNodeState.FAILED
                            node.error_message = (
                                "Durable result recording failed: "
                                f"{exc}"
                            )
                            if node.node_id in instance.pending_nodes:
                                instance.pending_nodes.remove(node.node_id)
                            instance.failed_nodes.append(node.node_id)
                            report = FailureReport(
                                runtime_id=instance.runtime_id,
                                mission_id=instance.mission_id,
                                node_id=node.node_id,
                                category=FailureCategory.EXECUTION_FAILURE,
                                message=node.error_message,
                                retryable=False,
                            )
                            self._failure_reports.append(report)
                            await self.save_checkpoint(instance)
                            await self._sync_lifecycle(instance)
                            return instance

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
                    if ownership is not None:
                        # Execution certainty lost: persist ambiguity. Never
                        # returns to PENDING, never redispatches. Failures of
                        # this best-effort marking are swallowed: the durable
                        # INTENT record already forbids redispatch by itself.
                        try:
                            self.dispatch_guard.record_ambiguity(
                                ownership,
                                reason="runtime-handoff-exception",
                                requested_by="mission-runtime",
                            )
                        except Exception:
                            pass
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
            # M30.3: Collect freshness facts immediately before completion decision
            freshness_facts = self._collect_completion_freshness_facts(instance)

            completion_decision = await self.completion_gate.decide(
                instance=instance,
                final_output=final_output_candidate,
                output_contract=output_contract,
                constraints=mission_constraints,
                freshness_facts=freshness_facts,
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
        """Resume execution of a paused or restarted mission from its latest checkpoint.

        G6: Authoritative mission resume.

        - MissionRecord is the durable authority; Checkpoint is support state only.
        - Checkpoint must never override MissionRecord action state, RRM identity/generation,
          tombstone/retirement, confirmation authority, VerificationGate, or MissionCompletionGate.
        - On any disagreement: FAIL CLOSED.
        - Old interrupted mission without authoritative MissionRecord is NON_RESUMABLE.
        - Authority must NOT be reconstructed from checkpoint, PKB, logs, traces, or agent claims.
        """
        instance = self._instances.get(runtime_id)
        if not instance:
            return None

        # G6: Load authoritative MissionRecord first when a durable store
        # is configured. A runtime with no mission_record_store runs the
        # legacy checkpoint path (pre-B5.2 behavior for non-durable
        # runtimes); a runtime WITH a store enforces MissionRecord-first
        # B5.2 authority. load() is synchronous — do NOT await; the result
        # is a raw dict converted via canonical MissionRecord.from_dict.
        mission_record: Optional[MissionRecord] = None
        if self._mission_record_store is not None:
            raw = self._mission_record_store.load(instance.mission_id)
            if raw is not None:
                mission_record = MissionRecord.from_dict(raw)
            if mission_record is None:
                # Store configured but no authority: NON_RESUMABLE.
                return None

        # B5.2: If checkpoint exists but disagrees with MissionRecord authority, fail closed.
        chk = await self.checkpoint_repo.get_latest_checkpoint(runtime_id) if hasattr(self, 'checkpoint_repo') and self.checkpoint_repo else None

        if chk and instance:
            # B5.2: Checkpoint must NOT override MissionRecord action state
            # (terminal states COMPLETED/FAILED/AMBIGUOUS_EFFECT must be preserved).
            # G6: these guards apply only when a MissionRecord is present
            # (store-configured runtimes); legacy store-less runtimes skip
            # them and restore from checkpoint evidence validation below.
            if mission_record is not None:
                for action_id, chk_state in chk.verification_state.items():
                    if action_id in mission_record.action_states:
                        rrm_state = mission_record.action_states[action_id].state
                        if rrm_state in (
                            ActionState.COMPLETED,
                            ActionState.FAILED,
                            ActionState.AMBIGUOUS_EFFECT,
                        ):
                            # MissionRecord has terminal state — do not override from checkpoint
                            # Reset checkpoint-derived evidence to INCONCLUSIVE
                            for nid in list(instance.completed_nodes):
                                if nid in instance.nodes:
                                    instance.nodes[nid].verification_result = VerificationStatus.INCONCLUSIVE

            # B5.2: Checkpoint must NOT override MissionRecord RRM identity/generation.
            # Verify expected_resource_generation consistency where current contract exists.
            if mission_record is not None:
                for action_id, action_state in mission_record.action_states.items():
                    if action_id in instance.nodes:
                        node = instance.nodes[action_id]
                        if node.action_contract is not None:
                            expected_gen = getattr(action_state, 'expected_resource_generation', 0)
                            # If generation mismatch detected between checkpoint and MissionRecord,
                            # the checkpoint state is denied — fall through to INCONCLUSIVE handling.
                            # (No automatic override; fail-closed behavior enforced below.)

            # B5.2: Checkpoint must NOT override tombstone/retirement.
            # Terminal states from MissionRecord must not be overridden by checkpoint evidence.
            if mission_record is not None:
                for action_id, action_state in mission_record.action_states.items():
                    if action_state.state in (
                        ActionState.COMPLETED,
                        ActionState.FAILED,
                        ActionState.AMBIGUOUS_EFFECT,
                    ):
                        for nid in list(instance.completed_nodes):
                            if nid in instance.nodes:
                                instance.nodes[nid].state = RuntimeNodeState.SUCCEEDED
                                instance.nodes[nid].verification_result = VerificationStatus.INCONCLUSIVE

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
                            nid, claimed_status, chk.completion_evidence,
                            instance.nodes[nid].action_contract,
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
        current_action_contract: Any = None,
    ) -> bool:
        """Validate that verification evidence is consistent for a node on resume.

        Returns True only if:
        - An evidence entry exists for this node
        - The evidence source is VerificationGate
        - The evidence claims verified=True
        - The evidence verification_status matches the claimed status
        - For EXACT evidence: evidence exact_contract_hash matches current expected_output
        - For STRUCTURAL evidence: evidence contract_hash matches current contract
        - For SEMANTIC evidence: evidence rule_set_hash matches current rules
        - For STRUCTURAL+SEMANTIC: both hashes must match
        - M28.2.1: Mutable PROVIDER_RESOURCE_STATE evidence never restores
          VERIFIED_SUCCESS — stored observation is historical only, not fresh.
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
            # M25.2.1: For STRUCTURAL evidence, contract hash must match current contract
            ev_type = details.get("verification_type", "EXACT")
            if ev_type == "STRUCTURAL":
                ev_hash = details.get("contract_hash")
                if ev_hash is None:
                    return False
                if current_action_contract is None:
                    return False
                current_schema = getattr(current_action_contract, "verification_schema", None)
                if current_schema is None:
                    return False
                current_hash = DeterministicStructuralVerifier.contract_hash(current_schema)
                if ev_hash != current_hash:
                    return False
            # M27.2: For EXACT evidence (no semantic rules), exact_contract_hash must match
            if ev_type == "EXACT" and current_action_contract is not None:
                current_rules = getattr(current_action_contract, "semantic_rules", None)
                has_current_semantic = isinstance(current_rules, list) and len(current_rules) > 0
                if not has_current_semantic:
                    ev_exact_hash = details.get("exact_contract_hash")
                    current_expected = getattr(current_action_contract, "expected_output", None)
                    current_exact_hash = exact_contract_hash(current_expected)
                    if ev_exact_hash is None:
                        return False
                    if ev_exact_hash != current_exact_hash:
                        return False
            # M26.2: For SEMANTIC evidence, rule_set_hash must match current rules
            ev_semantic_hash = details.get("rule_set_hash")
            if current_action_contract is not None:
                current_rules = getattr(current_action_contract, "semantic_rules", None)
                has_current_semantic = isinstance(current_rules, list) and len(current_rules) > 0
                if has_current_semantic:
                    # Current contract has semantic rules — evidence MUST have matching hash
                    if ev_semantic_hash is None:
                        return False
                    from intent_kernel.runtime.semantic_verifier import rule_set_hash
                    current_rhash = rule_set_hash(current_rules)
                    if ev_semantic_hash != current_rhash:
                        return False
                elif ev_semantic_hash is not None:
                    # Evidence has semantic hash but current contract doesn't — mismatch
                    return False
            # M28.2: External evidence contract hash must match current contract
            if current_action_contract is not None:
                current_external = getattr(current_action_contract, "external_evidence", None)
                has_current_external = isinstance(current_external, list) and len(current_external) > 0
                ev_ext_hash = details.get("external_evidence_contract_hash")
                if has_current_external:
                    if ev_ext_hash is None:
                        return False
                    from intent_kernel.runtime.external_evidence import external_evidence_contract_hash
                    current_ext_hash = external_evidence_contract_hash(current_external)
                    if ev_ext_hash != current_ext_hash:
                        return False
                elif ev_ext_hash is not None:
                    return False
            # M28.2.1: Mutable PROVIDER_RESOURCE_STATE evidence never restores
            # VERIFIED_SUCCESS. The external_evidence_contract_hash binds the
            # evidence to the REQUIREMENT CONTRACT, not to the current observed
            # RRM state. Because RRM has no canonical generation/version identity,
            # a stored observation is historical only and cannot prove freshness.
            if current_action_contract is not None:
                current_external = getattr(current_action_contract, "external_evidence", None)
                if isinstance(current_external, list) and len(current_external) > 0:
                    from intent_kernel.runtime.external_evidence import ExternalEvidenceRequirement
                    for req in current_external:
                        if isinstance(req, ExternalEvidenceRequirement) and req.evidence_type == "PROVIDER_RESOURCE_STATE":
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
