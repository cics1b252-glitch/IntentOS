"""Canonical, governed capability execution flow."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

# MissionEngine imported lazily to avoid circular import
# with application/composition -> orchestration -> execution
from intent_kernel.contracts import (
    AgentLimits,
    AgentRequest,
    CapabilityRequest,
    CapabilityResult,
    ConstitutionEngine,
    EffectType,
    ErrorCode,
    EventPublisher,
    IdempotencyStore,
    KnowledgeEvent,
    KnowledgeLifecycle,
    MissionId,
    MissionStatus,
    ProviderMessage,
    ProviderRequest,
)
from intent_kernel.core_apps import CapabilityRouter
from intent_kernel.orchestration.agents import CanonicalAgentOrchestrator
from intent_kernel.orchestration.registry import (
    CanonicalCapabilityRegistry,
    ExecutorKind,
)
from intent_kernel.pkb import KnowledgePipeline
from intent_kernel.providers import ProviderManager
# CanonicalResourceBindingAuthority imported at top level
from intent_kernel.rrm.binding import CanonicalResourceBindingAuthority
from intent_kernel.mission.dispatch_guard import _canonical_request_digest

# ExecutionPrecondition and PreconditionKind imported lazily to avoid circular import
# with orchestration/__init__.py -> orchestration/execution.py -> rrm/binding.py -> orchestration/registry


@dataclass(slots=True)
class CapabilityExecutionOutcome:
    result: CapabilityResult
    constitution_verdict: Any = None
    knowledge_event_ids: list[str] = field(default_factory=list)


class CapabilityExecutionService:
    """Mission-authorized execution across app, agent or provider."""

    _IDEMPOTENT_EFFECTS = {
        EffectType.PERSIST,
        EffectType.EXTERNAL_CHANGE,
        EffectType.IRREVERSIBLE,
    }

    def __init__(
        self,
        *,
        mission_engine: "MissionEngine",
        constitution: ConstitutionEngine,
        capability_router: CapabilityRouter,
        registry: CanonicalCapabilityRegistry,
        agent_orchestrator: CanonicalAgentOrchestrator,
        provider_manager: ProviderManager,
        knowledge_pipeline: KnowledgePipeline,
        event_publisher: EventPublisher,
        idempotency_store: IdempotencyStore,
        resource_authority: CanonicalResourceBindingAuthority,
        dispatch_guard: Any = None,
    ):
        self.mission_engine = mission_engine
        self.constitution = constitution
        self.capability_router = capability_router
        self.registry = registry
        self.agent_orchestrator = agent_orchestrator
        self.provider_manager = provider_manager
        self.knowledge_pipeline = knowledge_pipeline
        self.event_publisher = event_publisher
        self.idempotency_store = idempotency_store
        self.resource_authority = resource_authority
        # M32B-2 productive convergence: optional durable dispatch guard
        # (duck-typed ProductiveDispatchGuard; no mission imports here to
        # avoid cycles). None preserves legacy behavior exactly. When set
        # AND the call carries a bound durable_action spec, dispatch follows
        # durable attempt authority: decide -> cache -> Hd freshness ->
        # durable intent -> handoff -> durable result -> cache publication.
        self.dispatch_guard = dispatch_guard

    async def execute(
        self,
        mission_id: MissionId,
        capability: str,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        preferred_kind: ExecutorKind | None = None,
        idempotency_key: str = "",
        confirmed: bool = False,
        durable_action: Any = None,
    ) -> CapabilityExecutionOutcome:
        """Execute with optional durable attempt binding.

        durable_action is an optional caller-presented attempt spec (see
        mission.dispatch_guard.DispatchAttemptSpec; duck-typed here).
        Without both a guard and a spec, behavior is exactly legacy.
        """
        mission = await self.mission_engine.get(mission_id)
        if mission is None:
            return self._error(capability, ErrorCode.NOT_FOUND)
        if mission.status is not MissionStatus.RUNNING:
            return self._error(capability, ErrorCode.CONFLICT)

        resource_decision = await self.resource_authority.resolve(
            capability,
            preferred_kind=preferred_kind,
        )
        registration = resource_decision.registration
        if registration is None:
            return self._error(
                capability,
                ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={"resource_resolution": resource_decision.to_dict()},
            )
        descriptor = registration.capability
        verdict = await self.constitution.evaluate(
            "capability.execute",
            {
                "mission_id": str(mission.id),
                "capability": capability,
                "executor": registration.executor_id,
                "binding_identity": registration.binding_identity,
                "effect": descriptor.effect.value,
                "confirmed": confirmed,
            },
            {
                "correlation_id": mission.context.correlation_id,
                "idempotency_key": idempotency_key,
            },
        )
        if not verdict.allowed:
            outcome = self._error(capability, ErrorCode.POLICY_DENIED)
            outcome.result.metadata["resource_resolution"] = (
                resource_decision.to_dict()
            )
            outcome.constitution_verdict = verdict
            await self._audit(
                mission,
                registration,
                outcome.result,
                verdict,
                0.0,
                idempotency_key,
            )
            return outcome
        if (
            descriptor.effect in self._IDEMPOTENT_EFFECTS
            and not idempotency_key
        ):
            outcome = self._error(capability, ErrorCode.INVALID_REQUEST)
            outcome.result.metadata["resource_resolution"] = (
                resource_decision.to_dict()
            )
            outcome.constitution_verdict = verdict
            await self._audit(
                mission,
                registration,
                outcome.result,
                verdict,
                0.0,
                idempotency_key,
            )
            return outcome
        if descriptor.requires_confirmation and not confirmed:
            outcome = self._error(
                capability,
                ErrorCode.PERMISSION_REQUIRED,
            )
            outcome.result.metadata["resource_resolution"] = (
                resource_decision.to_dict()
            )
            outcome.constitution_verdict = verdict
            await self._audit(
                mission,
                registration,
                outcome.result,
                verdict,
                0.0,
                idempotency_key,
            )
            return outcome
        revalidation = await self.resource_authority.revalidate(resource_decision)
        if not revalidation:
            return self._error(
                capability,
                ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={
                    "resource_resolution": resource_decision.to_dict(),
                    "resource_revalidation": revalidation.to_dict(),
                },
            )
        # M31.3B-1A: structural execution-precondition identity verification MUST
        # precede any idempotency replay opportunity. A cached result must never
        # bypass structural identity validation (closes the STEP_09-before-STEP_11
        # ordering defect).
        if not self._verify_precondition_identity(resource_decision, revalidation):
            return self._error(
                capability,
                ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={
                    "resource_resolution": resource_decision.to_dict(),
                    "resource_revalidation": revalidation.to_dict(),
                    "precondition_identity_mismatch": True,
                },
            )

        # M31.3B-1A Hc: current canonical freshness check BEFORE the single
        # idempotency lookup. Prevents stale cached SUCCESS from being replayed
        # when the current RRM generation/lineage no longer matches the selected
        # ExecutionPrecondition. READ-ONLY observation; never mutates RRM.
        freshness_reason = self._check_current_freshness(
            registration.executor_kind,
            resource_decision.execution_preconditions,
        )
        if freshness_reason is not None:
            return self._error(
                capability,
                ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={
                    "resource_resolution": resource_decision.to_dict(),
                    "resource_revalidation": revalidation.to_dict(),
                    "freshness": freshness_reason,
                    "freshness_phase": "hc",
                },
            )

        cache_key = (str(mission.id), capability, idempotency_key)
        # M32B-2 productive convergence: durable attempt authority governs
        # before any cache/dispatch step (opt-in via guard + bound spec).
        guard = self.dispatch_guard
        use_guard = guard is not None and durable_action is not None
        bound_posture = ""
        if use_guard:
            try:
                bound_decision = guard.decide(
                    durable_action,
                    confirmation_required=(
                        descriptor.requires_confirmation and not confirmed
                    ),
                )
                bound_posture = str(
                    getattr(bound_decision, "value", bound_decision)
                )
            except Exception as exc:
                return self._error(
                    capability,
                    ErrorCode.CONFLICT,
                    metadata={
                        "resource_resolution": resource_decision.to_dict(),
                        "durable_decision_failed": str(exc),
                    },
                )
            if bound_posture != "MAY_DISPATCH":
                if bound_posture in ("DO_NOT_REDISPATCH", "ALREADY_COMPLETED"):
                    cached = await self.idempotency_store.get(cache_key)
                    if cached is not None:
                        replay = cached
                        replay.result.metadata["idempotent_replay"] = True
                        await self._audit(
                            mission,
                            registration,
                            replay.result,
                            verdict,
                            0.0,
                            idempotency_key,
                        )
                        return replay
                return self._error(
                    capability,
                    ErrorCode.CONFLICT,
                    metadata={
                        "resource_resolution": resource_decision.to_dict(),
                        "durable_replay_posture": bound_posture,
                        "duplicate_dispatch_prevented": True,
                    },
                )
        cached = await self.idempotency_store.get(cache_key)
        if cached is not None:
            if use_guard:
                # Durable authority wins over a stale/foreign cache entry:
                # MAY_DISPATCH with a cache hit proceeds to a fresh governed
                # dispatch and overwrites the cache afterwards.
                pass
            else:
                replay = cached
                replay.result.metadata["idempotent_replay"] = True
                await self._audit(
                    mission,
                    registration,
                    replay.result,
                    verdict,
                    0.0,
                    idempotency_key,
                )
                return replay

        # M31.3B-1A Hd: on cache MISS only, perform a second canonical freshness
        # observation immediately before dispatch. idempotency_store.get is an await
        # point, so a resource may legitimately advance between Hc and dispatch.
        # This is the LAST current-generation RRM observation before local dispatch.
        # READ-ONLY observation; never mutates RRM.
        freshness_reason = self._check_current_freshness(
            registration.executor_kind,
            resource_decision.execution_preconditions,
        )
        if freshness_reason is not None:
            return self._error(
                capability,
                ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={
                    "resource_resolution": resource_decision.to_dict(),
                    "resource_revalidation": revalidation.to_dict(),
                    "freshness": freshness_reason,
                    "freshness_phase": "hd",
                },
            )

# C1.1: Exact presented request ↔ authorized durable request binding.
        # Recompute presented request digest and compare to durable authorized digest.
        # Must happen before guard.acquire() to ensure zero durable mutation on mismatch.
        if use_guard and durable_action is not None:
            # Get the authorized request_semantics_digest from the durable
            # MissionRecord (canonical source), not from mission.plan.
            # Support both MissionId objects (with .value) and plain strings.
            mission_id_raw = getattr(mission, "id", "")
            mission_id_str = mission_id_str = mission_id.value if hasattr(mission_id_raw, "value") else str(mission_id_raw)
            if not mission_id_str:
                return self._error(
                    capability,
                    ErrorCode.INVALID_REQUEST,
                    metadata={"c1_mismatch": "no_mission_id"},
                )
            authorized_digest = self.dispatch_guard.get_authorized_request_digest(
                mission_id_str, durable_action.action_id
            )
            if not authorized_digest:
                return self._error(
                    capability,
                    ErrorCode.INVALID_REQUEST,
                    metadata={"c1_mismatch": "no_authorized_digest_for_action"},
                )
            # Recompute presented request digest from caller parameters.
            # C2/C3/G1.2 §4: the digest binds capability + OPERATION + payload
            # + idempotency_key, matching spec_for_legacy_dispatch exactly.
            # The presented operation is read from the AUTHORIZED durable plan
            # entry, so an operation substitution cannot silently re-derive a
            # matching digest; a caller that presents a different operation is
            # rejected by the guard's authoritative operation check.
            authorized_operation = self.dispatch_guard.get_authorized_operation(
                mission_id_str, durable_action.action_id
            )
            presented_digest = _canonical_request_digest(
                capability, authorized_operation, payload or {}, idempotency_key
            )
            if presented_digest != authorized_digest:
                return self._error(
                    capability,
                    ErrorCode.INVALID_REQUEST,
                    metadata={
                        "c1_mismatch": "presented_request_digest_mismatch",
                        "authorized_action_id": durable_action.action_id,
                    },
                )

            # C2/C3/G1.3 §3 ADVISORY CHECK (non-authorizing).
            # Runs after the initial C1 verification and produces a DIAGNOSTIC
            # ONLY. It never authorizes, never grants a quantity ceiling, and
            # never advances durable state. The authoritative refusal lives in
            # the revision-anchored acquire proof below; this surface exists so
            # a quantity-semantics problem is visible before dispatch.
            advisory_refusal = self._quantity_advisory_refusal(
                mission_id_str, durable_action.action_id
            )
            if advisory_refusal is not None:
                return self._error(
                    capability,
                    ErrorCode.INVALID_REQUEST,
                    metadata={
                        "quantity_advisory": "refused",
                        "authoritative": False,
                        **advisory_refusal,
                    },
                )

        started = perf_counter()
        # Durable intent BEFORE any external handoff (guarded calls only).
        # Failure here means ZERO DISPATCH.
        ownership = None
        if use_guard:
            try:
                ownership = guard.acquire(
                    durable_action,
                    requested_by="capability-execution-service",
                    confirmation_required=(
                        descriptor.requires_confirmation and not confirmed
                    ),
                )
            except Exception as exc:
                return self._error(
                    capability,
                    ErrorCode.CONFLICT,
                    metadata={
                        "resource_resolution": resource_decision.to_dict(),
                        "durable_intent_failed": str(exc),
                    },
                )
        try:
            result = await self._dispatch(
                mission,
                registration,
                payload or {},
                context or {},
                execution_preconditions=resource_decision.execution_preconditions,
            )
        except Exception:
            if use_guard and ownership is not None:
                # Certainty lost: persist ambiguity. Never returns to
                # PENDING, never redispatches. Secondary failures are
                # swallowed: the durable INTENT already forbids redispatch.
                try:
                    guard.record_ambiguity(
                        ownership,
                        reason="execution-handoff-exception",
                        requested_by="capability-execution-service",
                    )
                except Exception:
                    pass
            raise
        duration_ms = (perf_counter() - started) * 1000
        event_ids = await self._propose_agent_knowledge(
            mission,
            registration.executor_kind,
            registration.executor_id,
            result,
        )
        result.metadata.setdefault("executor", registration.executor_id)
        result.metadata.setdefault(
            "executor_kind",
            registration.executor_kind.value,
        )
        result.metadata.setdefault("effect", descriptor.effect.value)
        result.metadata.setdefault("binding_identity", registration.binding_identity)
        result.metadata.setdefault("selected_binding", resource_decision.selected_binding)
        result.metadata.setdefault(
            "resource_resolution", resource_decision.to_dict()
        )
        result.metadata.setdefault(
            "resource_revalidation", revalidation.to_dict()
        )
        result.metadata.setdefault(
            "execution_preconditions",
            [pc.to_dict() for pc in resource_decision.execution_preconditions],
        )
        outcome = CapabilityExecutionOutcome(
            result=result,
            constitution_verdict=verdict,
            knowledge_event_ids=event_ids,
        )
        await self._audit(
            mission,
            registration,
            result,
            verdict,
            duration_ms,
            idempotency_key,
        )
        if use_guard and ownership is not None:
            # Durable result authority BEFORE cache publication: the cache
            # must never outrun durable truth. Recording failure fails
            # closed (the durable INTENT still forbids redispatch).
            try:
                # C2/C3/G1.3 GAP 1: the durable result summary carries the
                # real post-effect observation, if the provider produced one.
                # Success alone is NOT an observation: when no observed
                # quantity exists the evidence status is UNKNOWN.
                _summary = _durable_capability_summary(result)
                _observed = _extract_observed_quantity(_summary)
                guard.record_result(
                    ownership,
                    result_summary=_summary,
                    provider_effect_id="",
                    requested_by="capability-execution-service",
                    observed_quantity=_observed,
                )
            except Exception as exc:
                return self._error(
                    capability,
                    ErrorCode.CONFLICT,
                    metadata={
                        "resource_resolution": resource_decision.to_dict(),
                        "durable_result_failed": str(exc),
                    },
                )
        if idempotency_key:
            await self.idempotency_store.save(cache_key, outcome)
        return outcome

    def _read_current_resource(self, executor_kind: Any, resource_id: str) -> Any:
        """Read the current canonical immutable snapshot for a dispatched resource.

        READ-ONLY observation via existing public RRM observation APIs. Never
        mutates RRM and never takes the RRM mutation lock. Returns None for an
        unknown executor kind so callers fail closed.
        """
        rrm = self.resource_authority.rrm
        if executor_kind is ExecutorKind.PROVIDER:
            return rrm.get_provider(resource_id)
        if executor_kind is ExecutorKind.AGENT:
            return rrm.get_agent(resource_id)
        if executor_kind is ExecutorKind.CORE_APP:
            return rrm.get_capability(resource_id)
        return None

    def _check_current_freshness(
        self,
        executor_kind: Any,
        preconditions: tuple[Any, ...],
    ) -> str | None:
        """M31.3B-1A current canonical freshness validation (Hc / Hd).

        Data-only, READ-ONLY RRM observation. Returns None when the current
        canonical RRM identities exactly match every ExecutionPrecondition, else a
        fail-closed reason string. Exact equality only — no ">= expected" shortcut.

        Supported emitted resource kinds: PROVIDER / AGENT / CAPABILITY.
        """
        # Lazy import to avoid circular import
        from intent_kernel.rrm.binding import PreconditionKind
        from intent_kernel.rrm.generation import is_valid_generation

        for pc in preconditions:
            kind = getattr(pc, "kind", None)
            resource_id = getattr(pc, "resource_id", None)
            expected_grid = getattr(pc, "governed_registration_id", None)
            expected_gen = getattr(pc, "expected_generation", None)

            # Malformed precondition => fail closed.
            if not isinstance(resource_id, str) or not resource_id:
                return "malformed_precondition"

            if kind is PreconditionKind.EXISTING_RESOURCE:
                # Fail closed on malformed expectations carried by the precondition.
                if not isinstance(expected_grid, str) or not expected_grid:
                    return "malformed_precondition"
                if (
                    not isinstance(expected_gen, int)
                    or isinstance(expected_gen, bool)
                    or not is_valid_generation(expected_gen)
                ):
                    return "malformed_precondition"

                snapshot = self._read_current_resource(executor_kind, resource_id)
                if snapshot is None:
                    return "resource_not_found"
                current_grid = getattr(snapshot, "governed_registration_id", None)
                current_gen = getattr(snapshot, "generation", None)
                if not isinstance(current_grid, str) or not current_grid:
                    return "registration_lineage_mismatch"
                if not is_valid_generation(current_gen):
                    return "legacy_unversioned"
                if current_grid != expected_grid:
                    return "registration_lineage_mismatch"
                if current_gen != expected_gen:
                    return "generation_mismatch"
            else:
                # EXPECTED_ABSENCE / unknown kinds cannot be emitted in this dispatch
                # path; keep handling fail-closed and minimal.
                return "unsupported_precondition"
        return None

    async def _dispatch(
        self,
        mission: Any,
        registration: Any,
        payload: dict[str, Any],
        context: dict[str, Any],
        execution_preconditions: tuple[ExecutionPrecondition, ...] = (),
    ) -> CapabilityResult:
        # Lazy import to avoid circular import
        from intent_kernel.rrm.binding import ExecutionPrecondition

        if registration.executor_kind is ExecutorKind.CORE_APP:
            # Dispatch the exact selected binding directly — no second router lookup.
            # The registration.object (executor) is the same object that was selected
            # by CanonicalResourceBindingAuthority and revalidated. Using a fresh
            # CapabilityRouter lookup after revalidation violates the identity invariant:
            #   SELECTED = REVALIDATED = DISPATCHED
            # Using the registration's executor directly prevents TOCTOU binding
            # replacement where the router's internal maps are swapped between
            # selection and dispatch.
            executor = registration.executor
            if executor is None:
                return CapabilityResult(
                    capability=registration.capability.name,
                    success=False,
                    error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
                    metadata={"mission_id": str(mission.id)},
                )
            result = await executor.execute(
                CapabilityRequest(
                    mission=mission,
                    capability=registration.capability.name,
                    payload=deepcopy(payload or {}),
                    context=deepcopy(context or {}),
                )
            )
            result.metadata.setdefault(
                "core_app", getattr(executor, "app_id", registration.executor_id)
            )
            result.metadata.setdefault("mission_id", str(mission.id))
            result.metadata.setdefault(
                "dispatched_binding", registration.binding_identity
            )
            return result
        if registration.executor_kind is ExecutorKind.AGENT:
            return await self.agent_orchestrator.execute(
                AgentRequest(
                    mission=mission,
                    capability=registration.capability.name,
                    task=str(payload.get("text", mission.objective)),
                    context=deepcopy(context),
                    limits=AgentLimits(),
                ),
                agent_id=registration.executor_id,
                expected_executor=registration.executor,
            )
        self.provider_manager.reset_execution_tracking()
        provider = self.provider_manager.bind_selected(
            registration.executor_id,
            expected_binding=registration.executor,
        )
        if provider is None:
            return CapabilityResult(
                capability=registration.capability.name,
                success=False,
                error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={"provider_invocation_attempted": False},
            )
        response = await provider.execute(
            ProviderRequest(
                messages=[
                    ProviderMessage(
                        role="user",
                        content=str(payload.get("text", mission.objective)),
                    )
                ],
                required_capabilities={
                    registration.capability.name.removeprefix("provider.")
                },
                metadata={"mission_id": str(mission.id)},
            )
        )
        return CapabilityResult(
            capability=registration.capability.name,
            success=response.error_code is None,
            output=response.text,
            confidence=0.0,
            error_code=response.error_code,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "usage": response.usage,
                "provider_invocation_attempted": (
                    self.provider_manager.last_attempted is not None
                ),
                "provider_invocation_succeeded": (
                    self.provider_manager.last_used is not None
                ),
            },
        )

    async def _propose_agent_knowledge(
        self,
        mission: Any,
        kind: ExecutorKind,
        executor_id: str,
        result: CapabilityResult,
    ) -> list[str]:
        if kind is not ExecutorKind.AGENT or not result.success:
            return []
        raw = str(result.output)
        event = KnowledgeEvent(
            event_type="agent_result",
            title=f"Agent result: {executor_id}",
            content={"raw": raw[:500]},
            summary=raw[:200],
            domain=mission.context.domain,
            confidence=result.confidence,
            lifecycle=KnowledgeLifecycle.OBSERVED,
            source=f"agent:{executor_id}",
            mission_id=mission.id,
            session_id=mission.context.session_id,
            correlation_id=mission.context.correlation_id,
            metadata={
                "capability": result.capability,
                "candidate": True,
            },
        )
        report = await self.knowledge_pipeline.ingest([event])
        return list(report.event_ids)

    async def _audit(
        self,
        mission: Any,
        registration: Any,
        result: CapabilityResult,
        verdict: Any,
        duration_ms: float,
        idempotency_key: str,
    ) -> None:
        await self.event_publisher.publish(
            "capability.audit",
            {
                "mission_id": str(mission.id),
                "capability": registration.capability.name,
                "executor": registration.executor_id,
                "executor_kind": registration.executor_kind.value,
                "duration_ms": round(duration_ms, 3),
                "success": result.success,
                "error": (
                    result.error_code.value if result.error_code else None
                ),
                "effect": registration.capability.effect.value,
                "constitution_decision": verdict.decision.value,
                "constitution_audit_id": verdict.metadata.get("audit_id"),
                "idempotency_key_present": bool(idempotency_key),
            },
            correlation_id=mission.context.correlation_id,
        )

    @staticmethod
    def _error(
        capability: str,
        code: ErrorCode,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityExecutionOutcome:
        return CapabilityExecutionOutcome(
            result=CapabilityResult(
                capability=capability,
                success=False,
                error_code=code,
                metadata=dict(metadata or {}),
            )
        )

    def _verify_precondition_identity(
        self,
        decision: Any,  # ResourceBindingDecision
        revalidation: Any,  # ResourceBindingRevalidation
    ) -> bool:
        """M31.2A: Structural revalidation of execution preconditions at dispatch.

        Verifies that the preconditions attached to the binding decision are
        structurally identical to those in the revalidation. This is a structural
        identity check only — it does NOT claim atomic resource freshness enforcement.

        Returns True if preconditions match (or both are empty), False if mismatch.
        """
        # Lazy import to avoid circular import
        from intent_kernel.rrm.binding import PreconditionKind

        decision_preconditions = getattr(decision, "execution_preconditions", ())
        revalidation_preconditions = getattr(revalidation, "execution_preconditions", ())

        # Both empty = compatible (no precondition claim)
        if not decision_preconditions and not revalidation_preconditions:
            return True

        # Length mismatch = structural divergence
        if len(decision_preconditions) != len(revalidation_preconditions):
            return False

        # Compare each precondition structurally (kind, resource_id, governed_registration_id, expected_generation)
        for dp, rp in zip(decision_preconditions, revalidation_preconditions):
            if dp.kind != rp.kind:
                return False
            if dp.resource_id != rp.resource_id:
                return False
            if dp.governed_registration_id != rp.governed_registration_id:
                return False
            if dp.expected_generation != rp.expected_generation:
                return False

        return True

    @staticmethod
    def _error(
        capability: str,
        code: ErrorCode,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityExecutionOutcome:
        return CapabilityExecutionOutcome(
            result=CapabilityResult(
                capability=capability,
                success=False,
                error_code=code,
                metadata=dict(metadata or {}),
            )
        )

    def _quantity_advisory_refusal(
        self,
        mission_id: str,
        action_id: str,
    ) -> dict[str, Any] | None:
        """C2/C3/G1.3 §3: non-authorizing quantity advisory diagnostic.

        Reads the durable record and reports a quantity-semantics problem
        (missing quantity authority for a quantitative operation, or an
        undeclared operation) so it is visible BEFORE dispatch. This helper
        deliberately has NO effect on authority or durable state: it returns
        a diagnostic dict or None, and never approves anything. The
        authoritative proof remains the revision-anchored acquire path.
        """
        try:
            from intent_kernel.mission.quantity import (
                QuantityAuthorityRecord,
                resolve_quantity_applicability,
            )

            store = getattr(self.dispatch_guard, "store", None)
            if store is None:
                store = getattr(self.dispatch_guard, "_store", None)
            if store is None:
                return None
            data = store.load(mission_id)
            if not isinstance(data, dict):
                return None
            entry = None
            for plan_entry in data.get("plan", ()):
                if (
                    isinstance(plan_entry, dict)
                    and plan_entry.get("action_id") == action_id
                ):
                    entry = plan_entry
                    break
            if entry is None:
                return None
            operation = str(entry.get("operation", "") or "")
            determination = resolve_quantity_applicability(operation)
            if determination.state.value == "NOT_APPLICABLE":
                return None
            raw_authority = (data.get("mission_definition") or {}).get(
                "quantity_authority"
            )
            if not isinstance(raw_authority, dict):
                return {
                    "quantity_reason": "missing_quantity_authority",
                    "operation": operation,
                }
            if not QuantityAuthorityRecord.from_dict(raw_authority).ceilings:
                return {
                    "quantity_reason": "empty_quantity_authority",
                    "operation": operation,
                }
            return None
        except Exception as exc:  # diagnostic only, never a hard failure
            return {
                "quantity_reason": "advisory_unavailable",
                "detail": str(exc),
            }


def _extract_observed_quantity(
    summary: dict[str, Any],
) -> Any | None:
    """Read a real post-effect observed quantity, or None.

    Success alone is never an observation. Only an explicit observable
    quantity in the durable summary becomes ObservedQuantity.
    """
    try:
        from intent_kernel.mission.quantity import ObservedQuantity, Quantity

        raw = summary.get("observed_quantity")
        if raw is None:
            return None
        if isinstance(raw, ObservedQuantity):
            return raw
        if isinstance(raw, dict):
            return ObservedQuantity.from_quantity(Quantity.from_dict(raw))
    except Exception:
        return None
    return None


def _durable_capability_summary(result: Any) -> dict[str, Any]:
    """Minimal JSON-safe handoff-result summary for durable recording.

    Duck-typed (never raises). Provider effect tokens are NOT invented
    here; absence stays absent.
    """
    try:
        success = bool(getattr(result, "success", True))
    except Exception:
        success = False
    try:
        output = str(getattr(result, "output", result))
    except Exception:
        output = "<unrenderable-result>"
    try:
        error_code = getattr(result, "error_code", None)
        error_code = str(error_code) if error_code is not None else ""
    except Exception:
        error_code = ""
    summary = {
        "success": success,
        "output": output[:2000],
        "error_code": error_code,
    }
    # C2/C3/G1.3 GAP 1: carry a REAL post-effect observed quantity when the
    # provider reported one, so the durable result path can distinguish
    # OBSERVED from REQUESTED. Absence stays absent (UNKNOWN) - success is
    # never converted into an observation.
    observed = None
    try:
        observed = getattr(result, "observed_quantity", None)
    except Exception:
        observed = None
    if observed is None:
        try:
            metadata = getattr(result, "metadata", None)
            if isinstance(metadata, dict):
                observed = metadata.get("observed_quantity")
        except Exception:
            observed = None
    if observed is not None:
        try:
            if hasattr(observed, "to_dict"):
                summary["observed_quantity"] = observed.to_dict()
            elif isinstance(observed, dict):
                summary["observed_quantity"] = dict(observed)
        except Exception:
            pass
    return summary
