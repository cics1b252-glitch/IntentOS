"""Official Composition Root for Intent OS architecture v2.0."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from intent_kernel.adapters import (
    InMemoryMissionStoreAdapter,
    InMemoryIdempotencyStoreAdapter,
    LegacyAgentAdapter,
    LegacyCapabilityExecutorAdapter,
    LegacyEventPublisherAdapter,
    LegacyKnowledgeStoreAdapter,
    LegacyProviderAdapter,
)
from intent_kernel.agents import (
    EngineeringAgent,
    FinanceAgent,
    KnowledgeAgent,
)
from intent_kernel.application.mission_engine import MissionEngine
from intent_kernel.application.mission_service import CanonicalMissionService
from intent_kernel.application.migration import MigrationTelemetry
from intent_kernel.bus import EventBus
from intent_kernel.constitution import (
    CanonicalConstitutionEngine,
    Constitution,
    ConstitutionPipeline,
    create_default_constitution,
)
from intent_kernel.cdm import CognitiveDialogueManager
from intent_kernel.conversation import CognitiveConversationService
from intent_kernel.contracts import CapabilityExecutor, ConstitutionEngine
from intent_kernel.cognition import (
    CapabilityFirstResolver,
    CapabilityRequirementDiscovery,
    CognitiveCapabilityRuntime,
)
from intent_kernel.core_apps import (
    AtlasCoreApp,
    CapabilityRouter,
    LogosCoreApp,
    OEMStudioCoreApp,
)
from intent_kernel.kernel import Kernel
from intent_kernel.iue import IntentUnderstandingEngine
from intent_kernel.modules.core import CoreModule
from intent_kernel.modules.fin import FinanceModule
from intent_kernel.orchestration import (
    CanonicalAgentOrchestrator,
    CanonicalCapabilityRegistry,
    CapabilityExecutionService,
)
from intent_kernel.pkb import JsonFileStore
from intent_kernel.providers import (
    CanonicalProviderAuthority,
    ManagedProvider,
    MockProvider,
    ProviderManager,
)
from intent_kernel.router import ModuleRouter
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.rrm.binding import CanonicalResourceBindingAuthority
from intent_kernel.rrm.models import CapabilityResource, ResourceOrigin, AvailabilitySource
from intent_kernel.runtime import MissionRuntime
from intent_kernel.tools.authorization import ToolAuthorizationGate

LEGACY_ADAPTERS = (
    "ModuleRouter",
    "CoreModule",
    "FinanceModule",
    "LegacyCapabilityExecutorAdapter",
    "LegacyKnowledgeStoreAdapter",
    "LegacyProviderAdapter",
)


@dataclass(slots=True)
class ApplicationComponents:
    kernel: Kernel
    knowledge_store: LegacyKnowledgeStoreAdapter
    provider: LegacyProviderAdapter
    mission_store: InMemoryMissionStoreAdapter
    idempotency_store: InMemoryIdempotencyStoreAdapter
    event_publisher: LegacyEventPublisherAdapter
    capability_executor: CapabilityExecutor
    capability_router: CapabilityRouter
    legacy_capability_executor: LegacyCapabilityExecutorAdapter
    core_apps: tuple[AtlasCoreApp | LogosCoreApp | OEMStudioCoreApp, ...]
    module_router: ModuleRouter
    capability_registry: CanonicalCapabilityRegistry
    agent_orchestrator: CanonicalAgentOrchestrator
    capability_execution_service: CapabilityExecutionService
    constitution_engine: ConstitutionEngine
    constitution_pipeline: ConstitutionPipeline
    mission_engine: MissionEngine
    mission_service: CanonicalMissionService
    provider_manager: ProviderManager
    provider_authority: CanonicalProviderAuthority
    knowledge_pipeline: Any
    resource_manager: RegistryResourceManager
    cognitive_capability_runtime: CognitiveCapabilityRuntime
    iue: IntentUnderstandingEngine
    cdm: CognitiveDialogueManager
    conversation_service: CognitiveConversationService
    tool_authorization_gate: ToolAuthorizationGate
    mission_runtime: MissionRuntime
    migration_telemetry: MigrationTelemetry
    bootstrap_mode: str = "canonical"
    legacy_adapters: tuple[str, ...] = LEGACY_ADAPTERS


class KernelBuilder:
    """Build the complete canonical application graph in one place."""

    def __init__(self):
        self._constitution: Constitution | None = None
        self._store: Any | None = None
        self._provider_manager: ProviderManager | None = None
        self._event_bus: EventBus | None = None
        self._router: ModuleRouter | None = None
        self._capability_router: CapabilityRouter | None = None
        self._pkb_path: str | None = None
        self._provider_registrations: list[tuple[str, Any, bool]] = []

    def with_constitution(self, constitution: Constitution) -> "KernelBuilder":
        self._constitution = constitution
        return self

    def with_store(self, store: Any) -> "KernelBuilder":
        self._store = store
        return self

    def with_provider_manager(
        self,
        manager: ProviderManager,
    ) -> "KernelBuilder":
        self._provider_manager = manager
        return self

    def with_event_bus(self, event_bus: EventBus) -> "KernelBuilder":
        self._event_bus = event_bus
        return self

    def with_router(self, router: ModuleRouter) -> "KernelBuilder":
        self._router = router
        return self

    def with_capability_router(
        self,
        router: CapabilityRouter,
    ) -> "KernelBuilder":
        self._capability_router = router
        return self

    def with_pkb_path(self, path: str | Path) -> "KernelBuilder":
        self._pkb_path = str(path)
        return self

    def with_provider(
        self,
        name: str,
        provider: Any,
        *,
        default: bool = False,
    ) -> "KernelBuilder":
        """Register infrastructure providers at the Composition Root."""
        self._provider_registrations.append((name, provider, default))
        return self

    def with_environment(self, environ: dict[str, str]) -> "KernelBuilder":
        """Configure optional providers from an explicit environment mapping."""
        default_name = environ.get("INTENTOS_DEFAULT_PROVIDER", "openai")
        openai_key = environ.get("OPENAI_API_KEY")
        if openai_key:
            try:
                from intent_kernel.providers.openai_provider import OpenAIProvider
                self.with_provider(
                    "openai", OpenAIProvider(api_key=openai_key),
                    default=default_name == "openai",
                )
            except ImportError:
                pass
        gemini_key = environ.get("GEMINI_API_KEY")
        if gemini_key:
            from intent_kernel.providers.gemini_provider import GeminiProvider
            self.with_provider(
                "gemini", GeminiProvider(api_key=gemini_key),
                default=default_name == "gemini",
            )
        return self

    def build(self) -> ApplicationComponents:
        constitution = self._constitution or create_default_constitution()
        store = self._store or JsonFileStore(
            self._pkb_path or "~/.intent-os/pkb"
        )
        providers = self._provider_manager or ProviderManager()
        for name, provider, default in self._provider_registrations:
            providers.register(name, provider)
            if default:
                providers.set_default(name)
        if not providers.available:
            providers.register("mock", MockProvider())
        event_bus = self._event_bus or EventBus()
        migration_telemetry = MigrationTelemetry(
            dependency_counts={
                "FIN": 5,
                "ModuleRouter": 3,
                "CoreModule": 4,
                "historical_registry_calls": 0,
                "historical_orchestrator_calls": 0,
            }
        )
        router = self._router or _default_router(migration_telemetry)
        knowledge_store = LegacyKnowledgeStoreAdapter(store)
        event_publisher = LegacyEventPublisherAdapter(event_bus)
        capability_router = self._capability_router or CapabilityRouter()
        default_provider = ManagedProvider(providers)
        core_apps = (
            AtlasCoreApp(),
            LogosCoreApp(
                knowledge_store=knowledge_store,
                provider=default_provider,
            ),
            OEMStudioCoreApp(provider=default_provider),
        )
        if not capability_router.registered_apps:
            for app in core_apps:
                capability_router.register(app)
        capability_executor = capability_router
        constitution_engine = CanonicalConstitutionEngine(
            constitution,
            event_publisher=event_publisher,
        )
        constitution_pipeline = ConstitutionPipeline(constitution_engine)
        mission_store = InMemoryMissionStoreAdapter()
        idempotency_store = InMemoryIdempotencyStoreAdapter()
        mission_engine = MissionEngine(mission_store)

        kernel = Kernel(
            constitution=constitution,
            store=store,
            provider_manager=providers,
            constitution_engine=constitution_engine,
            knowledge_store=knowledge_store,
            event_publisher=event_publisher,
            capability_executor=capability_executor,
            event_bus=event_bus,
            router=router,
            mission_engine=mission_engine,
            bootstrap_mode="canonical",
            migration_telemetry=migration_telemetry,
        )
        agent_orchestrator = CanonicalAgentOrchestrator()
        for legacy_agent in (
            FinanceAgent(),
            KnowledgeAgent(),
            EngineeringAgent(),
        ):
            agent_orchestrator.register(
                LegacyAgentAdapter(legacy_agent)
            )
        capability_registry = CanonicalCapabilityRegistry()
        resource_manager = RegistryResourceManager(populate_defaults=False)
        projection = RuntimeResourceProjection(resource_manager)
        providers.set_resource_projection(projection.project_provider)
        for app in core_apps:
            capability_registry.register_core_app(app)
            projection.project_core_app(app)
        for agent in agent_orchestrator.agents:
            capability_registry.register_agent(agent)
            projection.project_agent(agent)
        for provider_name in providers.available:
            provider = providers.get(provider_name)
            capability_registry.register_provider(provider)
            projection.project_provider(provider)
        provider_authority = CanonicalProviderAuthority(
            resource_manager, providers
        )
        for capability_id in (
            "memory.write", "memory.retrieve", "productivity.spreadsheet"
        ):
            resource_manager.register_capability(CapabilityResource(
                capability_id=capability_id,
                name=capability_id,
                description="Explicit ProductBridge compatibility binding",
                resource_origin=ResourceOrigin.MIGRATION,
                availability_source=AvailabilitySource.CONFIGURATION,
                metadata={"executor_kind": "ame", "compatibility": True},
            ))
        cognitive_capability_runtime = CognitiveCapabilityRuntime(
            discovery=CapabilityRequirementDiscovery(),
            resolver=CapabilityFirstResolver(
                rrm=resource_manager,
                constitution=constitution_engine,
            ),
        )
        iue = IntentUnderstandingEngine(pkb=getattr(kernel, "pkb", None))
        cdm = CognitiveDialogueManager()
        conversation_service = CognitiveConversationService(
            iue=iue,
            cdm=cdm,
            capability_runtime=cognitive_capability_runtime,
        )
        capability_execution_service = CapabilityExecutionService(
            mission_engine=mission_engine,
            constitution=constitution_engine,
            capability_router=capability_router,
            registry=capability_registry,
            agent_orchestrator=agent_orchestrator,
            provider_manager=providers,
            knowledge_pipeline=kernel.knowledge.pipeline,
            event_publisher=event_publisher,
            idempotency_store=idempotency_store,
            resource_authority=CanonicalResourceBindingAuthority(
                resource_manager, capability_registry
            ),
        )
        tool_authorization_gate = ToolAuthorizationGate(constitution_engine)
        mission_service = CanonicalMissionService(
            mission_engine,
            tool_authorization_gate,
        )
        mission_runtime = MissionRuntime(
            rrm_service=resource_manager,
            constitution=constitution_engine,
            mission_engine=mission_engine,
        )
        legacy_capability_executor = LegacyCapabilityExecutorAdapter(
            router,
            mission_engine=mission_engine,
            execution_service=capability_execution_service,
            telemetry=migration_telemetry,
        )
        kernel.attach_canonical_execution(capability_execution_service)
        kernel.attach_cognitive_capability_runtime(cognitive_capability_runtime)
        kernel.set_runtime_description(
            {
                "bootstrap_mode": "canonical",
                "mission_engine": "active",
                "constitution": "canonical",
                "capability_router": "canonical",
                "capability_registry": "canonical",
                "resource_authority": "RRM",
                "capability_resolution": "canonical_non_executing",
                "conversation_authority": "CognitiveConversationService",
                "mission_lifecycle_authority": "MissionEngine",
                "mission_completion_authority": "MissionCompletionGate",
                "tool_authorization_authority": "ToolAuthorizationGate",
                "agent_orchestrator": "canonical",
                "provider_manager": tuple(providers.available),
                "provider_selection_authority": "RRM",
                "core_apps": tuple(app.app_id for app in core_apps),
                "knowledge_pipeline": "canonical",
                "mission_store": type(mission_store).__name__,
                "knowledge_store": type(store).__name__,
                "audit_store": "EventBus",
                "idempotency_store": "in-memory",
                "legacy_adapters": LEGACY_ADAPTERS,
            }
        )

        return ApplicationComponents(
            kernel=kernel,
            knowledge_store=knowledge_store,
            provider=LegacyProviderAdapter(default_provider),
            mission_store=mission_store,
            idempotency_store=idempotency_store,
            event_publisher=event_publisher,
            capability_executor=capability_executor,
            capability_router=capability_router,
            legacy_capability_executor=legacy_capability_executor,
            core_apps=core_apps,
            module_router=router,
            capability_registry=capability_registry,
            agent_orchestrator=agent_orchestrator,
            capability_execution_service=capability_execution_service,
            constitution_engine=constitution_engine,
            constitution_pipeline=constitution_pipeline,
            mission_engine=mission_engine,
            mission_service=mission_service,
            provider_manager=providers,
            provider_authority=provider_authority,
            knowledge_pipeline=kernel.knowledge.pipeline,
            resource_manager=resource_manager,
            cognitive_capability_runtime=cognitive_capability_runtime,
            iue=iue,
            cdm=cdm,
            conversation_service=conversation_service,
            tool_authorization_gate=tool_authorization_gate,
            mission_runtime=mission_runtime,
            migration_telemetry=migration_telemetry,
        )


class ApplicationFactory:
    """Authority that provides one application graph to every interface."""

    def __init__(self, builder: KernelBuilder | None = None):
        self._builder = builder or KernelBuilder()
        self._components: ApplicationComponents | None = None

    def get_components(self) -> ApplicationComponents:
        if self._components is None:
            self._components = self._builder.build()
        return self._components

    def get_kernel(self) -> Kernel:
        return self.get_components().kernel


def _default_router(
    telemetry: MigrationTelemetry | None = None,
) -> ModuleRouter:
    router = ModuleRouter(telemetry=telemetry)
    router.register(CoreModule())
    router.register(FinanceModule())
    return router
