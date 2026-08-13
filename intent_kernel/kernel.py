"""Intent OS Kernel — the sacred core.

Pure Python library, zero external dependencies (except pydantic).
This is the heart of the Cognitive Operating System.
"""

from __future__ import annotations

import asyncio
from typing import Any

from intent_kernel.adapters import (
    LegacyCapabilityExecutorAdapter,
    LegacyEventPublisherAdapter,
    LegacyKnowledgeStoreAdapter,
)
from intent_kernel.constitution import (
    CanonicalConstitutionEngine,
    Constitution,
    create_default_constitution,
)
from intent_kernel.contracts import (
    CapabilityExecutor,
    ConstitutionEngine,
    Domain as CanonicalDomain,
    EventPublisher,
    IntentMode as CanonicalIntentMode,
    KnowledgeStore,
    MissionContext,
    MissionStatus,
)
from intent_kernel.bus import EventBus
from intent_kernel.pkb import KnowledgeManager, JsonFileStore
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.router import ModuleRouter
from intent_kernel.providers import ProviderManager, MockProvider
from intent_kernel.engine import IntentEngine, PipelineDAG
from intent_kernel.engine import nodes
from intent_kernel.modules.core import CoreModule
from intent_kernel.modules.fin import FinanceModule
from intent_kernel.types import (
    Action,
    ConstitutionVerdict,
    Domain,
    EpistemicStatus,
    EventType,
    IntentInput,
    IntentOutput,
    Mode,
    QueryFilters,
    new_id,
)


class Kernel:
    """The Intent OS Kernel.

    A pure Python library that processes user intents through:
    1. Constitution validation
    2. Intent parsing + classification
    3. Pipeline execution (DAG)
    4. Knowledge curation + persistence
    5. Response delivery

    Usage:
        kernel = Kernel()
        result = await kernel.process("Quero investir 5000/mês")
    """

    def __init__(
        self,
        constitution: Constitution | None = None,
        store: JsonFileStore | None = None,
        provider_manager: ProviderManager | None = None,
        pkb_path: str | None = None,
        *,
        constitution_engine: ConstitutionEngine | None = None,
        knowledge_store: KnowledgeStore | None = None,
        event_publisher: EventPublisher | None = None,
        capability_executor: CapabilityExecutor | None = None,
        event_bus: EventBus | None = None,
        router: ModuleRouter | None = None,
        mission_engine: Any | None = None,
        bootstrap_mode: str = "compatibility",
        migration_telemetry: Any | None = None,
    ):
        if bootstrap_mode == "canonical":
            required = {
                "constitution": constitution,
                "store": store,
                "provider_manager": provider_manager,
                "constitution_engine": constitution_engine,
                "knowledge_store": knowledge_store,
                "event_publisher": event_publisher,
                "capability_executor": capability_executor,
                "event_bus": event_bus,
                "router": router,
                "mission_engine": mission_engine,
                "migration_telemetry": migration_telemetry,
            }
            missing = [
                name for name, value in required.items()
                if value is None
            ]
            if missing:
                raise ValueError(
                    "Canonical Kernel requires injected dependencies: "
                    + ", ".join(missing)
                )
        self.bootstrap_mode = bootstrap_mode
        self.migration_telemetry = migration_telemetry
        self._canonical_execution_service: Any | None = None
        self._cognitive_capability_runtime: Any | None = None
        self._runtime_description: dict[str, Any] = {
            "bootstrap_mode": bootstrap_mode,
            "legacy_adapters": (
                "Kernel() direct compatibility composition",
            ) if bootstrap_mode == "compatibility" else (),
        }
        # Constitution — loaded first, validates everything
        self.constitution = constitution or create_default_constitution()
        # Event Bus
        self.event_bus = event_bus or EventBus()
        self._event_publisher = (
            event_publisher
            or LegacyEventPublisherAdapter(self.event_bus)
        )
        self._constitution_engine = (
            constitution_engine
            or CanonicalConstitutionEngine(
                self.constitution,
                event_publisher=self._event_publisher,
            )
        )

        # PKB
        store_path = pkb_path or "~/.intent-os/pkb"
        self.store = (
            store
            or getattr(knowledge_store, "_store", None)
            or JsonFileStore(store_path)
        )
        self._knowledge_store = (
            knowledge_store
            or LegacyKnowledgeStoreAdapter(self.store)
        )
        self.knowledge = KnowledgeManager(
            self._knowledge_store,
            self.constitution,
            legacy_store=self.store,
            constitution_engine=self._constitution_engine,
            event_publisher=self._event_publisher,
        )

        # Providers
        self.providers = provider_manager or ProviderManager()
        if not self.providers.available:
            self.providers.register("mock", MockProvider())

        # Module Router
        self.router = router or ModuleRouter()
        if not self.router.registered_modules:
            self.router.register(CoreModule())
            self.router.register(FinanceModule())
        self._capability_executor = (
            capability_executor
            or LegacyCapabilityExecutorAdapter(self.router)
        )
        self.mission_engine = mission_engine

        # Intent Engine
        self.intent_engine = IntentEngine()

        # Pipeline
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> PipelineDAG:
        """Build the processing pipeline DAG."""
        pipeline = PipelineDAG()
        pipeline.register("intake", nodes.intake_node)
        pipeline.register("classify", nodes.classify_node)
        pipeline.register("diagnose", nodes.diagnose_node)
        pipeline.register("plan", nodes.plan_node)
        pipeline.register("build", nodes.build_node)
        pipeline.register("stress_test", nodes.stress_test_node)
        pipeline.register("review", nodes.review_node)
        pipeline.register("knowledge_check", nodes.knowledge_check_node)
        pipeline.register("deliver", nodes.deliver_node)
        return pipeline

    async def process(
        self,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> IntentOutput:
        """Process a user intent through the full Kernel pipeline.

        Flow:
        1. Constitution.validate
        2. IntentEngine.parse
        3. Pipeline.execute
        4. KnowledgeManager.ingest
        5. Return IntentOutput
        """
        # Runtime callbacks belong to the host process and must never enter
        # canonical/deep-copied mission or Constitution data.
        runtime_context = context or {}
        serializable_context = {
            key: value for key, value in runtime_context.items()
            if key != "flow_event"
        }

        # 1. Constitution validation
        verdict = await self._constitution_engine.evaluate(
            "process",
            user_input,
            serializable_context,
        )
        if not verdict.allowed:
            return IntentOutput(
                text=f"Operação bloqueada pela Constitution: {verdict.reason}",
                mode=Mode.QUICK,
                domain=Domain.OTHER,
                confidence=1.0,
                epistemic_status=EpistemicStatus.FACT,
            )

        # 2. Parse intent
        parsed = await self.intent_engine.parse(user_input, serializable_context)
        if self._cognitive_capability_runtime is not None:
            analysis = serializable_context.get("capability_analysis")
            if analysis is None:
                decision = await self._cognitive_capability_runtime.analyze(
                    user_input,
                    structured_intent=parsed,
                    project_context=serializable_context,
                    persistent_constraints=serializable_context.get(
                        "persistent_constraints", ()
                    ),
                    authorized_permissions=serializable_context.get(
                        "authorized_permissions", ()
                    ),
                )
                analysis = decision.to_dict()
            runtime_context["capability_analysis"] = analysis
        flow_event = (context or {}).get("flow_event")
        if callable(flow_event):
            flow_event("intent_created", domain=parsed.domain.value,
                       mode=parsed.mode.value)
            flow_event("intent_validated", result="success")

        # 3. Get provider for pipeline
        provider = await self.providers.route(parsed.mode)

        session_id = str((context or {}).get("session_id") or new_id())
        canonical_result = await self._execute_canonical_route(
            parsed,
            user_input,
            context or {},
            session_id,
        )

        # 4. Execute pipeline
        extra = {
            "provider": provider,
            "router": self.router,
            "canonical_capability_result": canonical_result,
            "session_id": session_id,
            **(context or {}),
        }
        result = await self.pipeline.execute(parsed, parsed.mode, extra)

        # 5. Ingest events to PKB
        events = result.events if hasattr(result, "events") else []
        if events:
            await self.knowledge.ingest(events)

        # 6. Publish event
        await self._event_publisher.publish("kernel.process.done", {
            "domain": result.domain.value,
            "mode": result.mode.value,
            "confidence": result.confidence,
        })

        return IntentOutput(
            text=result.output_text,
            mode=result.mode,
            domain=result.domain,
            confidence=result.confidence,
            epistemic_status=result.epistemic_status,
            events=events,
            alternatives=[],
            next_steps=self._suggest_next_steps(parsed, result),
        )

    async def _execute_canonical_route(
        self,
        parsed: Any,
        user_input: str,
        context: dict[str, Any],
        session_id: str,
    ) -> Any | None:
        """Execute an explicitly selected capability; Domain is metadata only."""
        service = self._canonical_execution_service
        analysis = context.get("capability_analysis") or {}
        if analysis.get("mode") != "MISSION":
            return None
        steps = (analysis.get("composition") or {}).get("steps") or []
        selected = [
            step for step in steps
            if str(step.get("strategy", "")).startswith("capability:")
        ]
        capability = selected[0]["capability_id"] if selected else None
        if service is None or self.mission_engine is None or capability is None:
            return None
        canonical_domain = CanonicalDomain(parsed.domain.value)
        canonical_mode = CanonicalIntentMode(parsed.mode.value)
        flow_event = context.get("flow_event")
        resume_id = context.get("resume_mission_id")
        mission = None
        if resume_id:
            from intent_kernel.contracts import MissionId
            mission = await self.mission_engine.get(MissionId(str(resume_id)))
            if mission is not None and mission.status in {
                MissionStatus.PAUSED, MissionStatus.BLOCKED,
                MissionStatus.WAITING_FOR_INFORMATION,
                MissionStatus.WAITING_FOR_DECISION,
                MissionStatus.WAITING_FOR_PERMISSION,
                MissionStatus.FAILED_RECOVERABLE,
            }:
                mission = await self.mission_engine.resume(mission.id)
            elif mission is not None and mission.status is not MissionStatus.RUNNING:
                mission = None
        if mission is None:
            custom_mid = MissionId(str(resume_id)) if resume_id else None
            mission = await self.mission_engine.create(
                user_input,
                mission_id=custom_mid,
                context=MissionContext(
                    session_id=session_id,
                    correlation_id=str(context.get("correlation_id", "")),
                    domain=canonical_domain,
                    mode=canonical_mode,
                    values={key: value for key, value in context.items()
                            if key != "flow_event"},
                ),
            )
            if callable(flow_event):
                flow_event("mission_compiled", mission_id=str(mission.id))
                flow_event("mission_persisted", mission_id=str(mission.id), result="success")
        context["mission_id"] = str(mission.id)
        context["intent_model"] = {
            "text": parsed.intent,
            "domain": parsed.domain.value,
            "mode": parsed.mode.value,
            "entities": list(parsed.entities),
            "ambiguities": list(parsed.ambiguities),
        }
        if mission.status.value != "running":
            mission = await self.mission_engine.start(mission.id)
        outcome = await service.execute(
            mission.id,
            capability,
            payload={"text": user_input},
            context={key: value for key, value in context.items()
                     if key != "flow_event"},
        )
        # A capability result is execution output, not verified Mission
        # completion. The lifecycle remains VERIFYING until MissionRuntime and
        # MissionCompletionGate supply canonical completion evidence.
        await self.mission_engine.await_verification(mission.id)
        outcome.result.metadata.setdefault(
            "mission_lifecycle_status", MissionStatus.VERIFYING.value
        )
        outcome.result.metadata.setdefault(
            "completion_authority", "MissionCompletionGate"
        )
        if self.migration_telemetry is not None:
            self.migration_telemetry.record_canonical(parsed.domain.value)
        return outcome.result

    async def query(self, question: str) -> list[KnowledgeEvent]:
        """Query the PKB directly."""
        return await self.knowledge.query(
            QueryFilters(search_text=question)
        )

    def constitution_check(self, action: Action) -> ConstitutionVerdict:
        """Legacy synchronous Constitution facade."""
        return self.constitution.validate(action)

    @property
    def constitution_engine(self) -> ConstitutionEngine:
        return self._constitution_engine

    @property
    def knowledge_store(self) -> KnowledgeStore:
        return self._knowledge_store

    @property
    def event_publisher(self) -> EventPublisher:
        return self._event_publisher

    @property
    def capability_executor(self) -> CapabilityExecutor:
        return self._capability_executor

    def attach_canonical_execution(self, service: Any) -> None:
        """Bind the already-composed execution service at the composition root."""
        self._canonical_execution_service = service

    def attach_cognitive_capability_runtime(self, runtime: Any) -> None:
        """Attach non-executing capability analysis to the canonical input path."""
        self._cognitive_capability_runtime = runtime

    def set_runtime_description(self, description: dict[str, Any]) -> None:
        """Expose non-sensitive composition health to interfaces and Monitor."""
        self._runtime_description = dict(description)

    @property
    def runtime_description(self) -> dict[str, Any]:
        return dict(self._runtime_description)

    def _suggest_next_steps(
        self,
        parsed: Any,
        result: Any,
    ) -> list[str]:
        """Suggest next steps based on the result."""
        steps = []

        if result.confidence < 0.5:
            steps.append("Fornecer mais contexto para aumentar a confiança")

        if parsed.ambiguities:
            steps.append("Esclarecer ambiguidades identificadas")

        if parsed.mode in (Mode.QUICK, Mode.BASIC):
            steps.append("Solicitar detalhamento (modo DETAIL)")

        if parsed.domain == Domain.FINANCE:
            steps.append("Consultar um profissional financeiro registrado")

        return steps

    @property
    def version(self) -> str:
        """Kernel version."""
        return "0.1.0"

    def status(self) -> dict:
        """Get Kernel status."""
        status = {
            "version": self.version,
            "constitution_version": self.constitution.version,
            "providers": self.providers.available,
            "modules": self.router.registered_modules,
            "pkb_path": str(self.store.base_path),
            "bootstrap_mode": self.bootstrap_mode,
        }
        status["canonical"] = self.runtime_description
        return status
