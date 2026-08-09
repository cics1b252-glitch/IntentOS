"""Sprint 8 parity and architecture guards for domain migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from intent_kernel.adapters import LegacyCapabilityExecutorAdapter
from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.capabilities import CapabilityRegistry
from intent_kernel.contracts import (
    CapabilityRequest,
    Domain,
    ErrorCode,
    KnowledgeEvent,
    KnowledgeLifecycle,
    Mission,
    MissionContext,
    ProviderResponse,
)
from intent_kernel.core_apps import LogosCoreApp, OEMStudioCoreApp
from intent_kernel.kernel import Kernel
from intent_kernel.types import Domain as LegacyDomain
from intent_kernel.types import IntentInput


def _factory(tmp_path):
    return ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "canonical")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "domain", "owner"),
    [
        ("quero investir 5000", "finance", "atlas"),
        ("pesquisa e relatório de fontes", "research", "logos"),
        ("escreva um documento técnico", "writing", "logos"),
        ("crie um plano de projeto", "planning", "logos"),
        ("quero estudar data science", "education", "logos"),
        ("desenvolva uma api backend", "engineering", "oem_studio"),
    ],
)
async def test_migrated_domain_preserves_legacy_visible_response(
    tmp_path,
    text,
    domain,
    owner,
):
    components = _factory(tmp_path).get_components()
    legacy = Kernel(pkb_path=str(tmp_path / f"legacy-{domain}"))

    canonical_result = await components.kernel.process(text)
    legacy_result = await legacy.process(text)

    assert canonical_result.domain.value == domain
    assert canonical_result.text == legacy_result.text
    assert canonical_result.confidence == legacy_result.confidence
    assert (
        canonical_result.epistemic_status
        is legacy_result.epistemic_status
    )
    registration = components.capability_registry.select(
        {
            "finance": "finance.intent",
            "research": "knowledge.intent",
            "writing": "knowledge.intent",
            "planning": "knowledge.intent",
            "education": "knowledge.intent",
            "engineering": "engineering.intent",
            "programming": "engineering.intent",
        }[domain]
    )
    assert registration.executor_id == owner


@pytest.mark.asyncio
async def test_migrated_domains_never_invoke_module_router(tmp_path):
    components = _factory(tmp_path).get_components()

    await components.kernel.process("pesquise integração de sistemas")
    await components.kernel.process("desenvolva uma api backend")
    await components.kernel.process("quero investir 5000")
    metrics = components.migration_telemetry.snapshot()

    assert metrics["canonical_executions"] == 3
    assert metrics["fallback_executions"] == 0
    assert metrics["legacy_component_calls"].get("ModuleRouter", 0) == 0


@pytest.mark.asyncio
async def test_unmigrated_domain_records_legacy_fallback(tmp_path):
    components = _factory(tmp_path).get_components()

    module = components.module_router.route(
        IntentInput(
            text="uma solicitação sem domínio específico",
            domain=LegacyDomain.OTHER,
        )
    )
    metrics = components.migration_telemetry.snapshot()

    assert module.name == "core"
    assert metrics["fallback_executions"] == 1
    assert metrics["fallback_by_domain"]["other"] == 1
    assert metrics["legacy_component_calls"]["ModuleRouter"] == 1


@pytest.mark.asyncio
async def test_governed_legacy_executor_delegates_migrated_domain(tmp_path):
    components = _factory(tmp_path).get_components()

    result = await components.legacy_capability_executor.execute(
        "fin",
        {"text": "quero investir 5000", "domain": "finance"},
    )

    assert result.success is True
    assert result.metadata["executor"] == "atlas"
    assert (
        components.migration_telemetry.snapshot()
        ["legacy_component_calls"]
        ["LegacyCapabilityExecutorAdapter"]
        == 1
    )


@pytest.mark.asyncio
async def test_knowledge_query_empty_and_candidate_persistence_use_ports(
    tmp_path,
):
    components = _factory(tmp_path).get_components()
    logos = next(app for app in components.core_apps if app.app_id == "logos")

    empty = await logos.execute(
        CapabilityRequest(
            mission=Mission(
                objective="query",
                context=MissionContext(domain=Domain.RESEARCH),
            ),
            capability="knowledge.search",
        )
    )
    event = KnowledgeEvent(
        event_type="insight",
        title="Candidate",
        content={"raw": "candidate"},
        confidence=0.45,
        domain=Domain.RESEARCH,
    )
    report = await components.knowledge_pipeline.ingest([event])
    stored = await components.knowledge_store.get(report.event_ids[0])

    assert empty.success is True
    assert empty.output == []
    assert report.candidate == 1
    assert stored is not None
    assert stored.lifecycle is KnowledgeLifecycle.CANDIDATE


@pytest.mark.asyncio
async def test_knowledge_store_failure_remains_explicit():
    class FailingStore:
        async def query(self, filters=None):
            raise RuntimeError("store unavailable")

        async def health(self):
            return False

    app = LogosCoreApp(knowledge_store=FailingStore())
    request = CapabilityRequest(
        mission=Mission(
            objective="query",
            context=MissionContext(domain=Domain.RESEARCH),
        ),
        capability="knowledge.search",
    )

    with pytest.raises(RuntimeError, match="store unavailable"):
        await app.execute(request)


@pytest.mark.asyncio
async def test_engineering_provider_failure_is_canonical():
    class FailingProvider:
        name = "failing"
        capabilities = {"text_completion"}

        async def execute(self, request):
            return ProviderResponse(
                text="",
                provider=self.name,
                model="none",
                error_code=ErrorCode.PROVIDER_UNAVAILABLE,
            )

        async def health(self):
            return False

    app = OEMStudioCoreApp(provider=FailingProvider())
    mission = Mission(
        objective="desenvolva uma api",
        context=MissionContext(domain=Domain.ENGINEERING),
    )
    failed = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="engineering.intent",
        )
    )
    unavailable = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="engineering.missing",
        )
    )

    assert failed.success is False
    assert failed.error_code is ErrorCode.PROVIDER_UNAVAILABLE
    assert unavailable.error_code is ErrorCode.CAPABILITY_UNAVAILABLE


def test_canonical_import_boundaries_and_dependency_metrics(tmp_path):
    root = Path(__file__).parents[1] / "intent_kernel"
    production = list(root.rglob("*.py"))

    fin_imports = [
        path for path in production
        if "intent_kernel.modules.fin" in path.read_text(encoding="utf-8")
    ]
    router_imports = [
        path for path in production
        if "intent_kernel.router" in path.read_text(encoding="utf-8")
    ]
    core_imports = [
        path for path in production
        if "intent_kernel.modules.core" in path.read_text(encoding="utf-8")
    ]
    relative = lambda paths: {
        path.relative_to(root).as_posix() for path in paths
    }

    assert relative(fin_imports) == {
        "application/composition.py",
        "core_apps/apps.py",
        "kernel.py",
        "modules/__init__.py",
        "modules/fin/__init__.py",
    }
    assert relative(router_imports) == {
        "application/composition.py",
        "kernel.py",
        "router/__init__.py",
    }
    assert relative(core_imports) == {
        "application/composition.py",
        "kernel.py",
        "modules/__init__.py",
        "modules/core/__init__.py",
    }
    metrics = _factory(tmp_path).get_components().migration_telemetry.snapshot()
    assert metrics["direct_dependencies"] == {
        "FIN": 5,
        "ModuleRouter": 3,
        "CoreModule": 4,
        "historical_registry_calls": 0,
        "historical_orchestrator_calls": 0,
    }


def test_canonical_agents_do_not_import_store_or_concrete_provider():
    root = Path(__file__).parents[1] / "intent_kernel" / "orchestration"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    )

    assert "providers.openai_provider" not in source
    assert "JsonFileStore" not in source
    assert "LegacyKnowledgeStoreAdapter" not in source
    assert ".knowledge.ingest" not in source


def test_user_entrypoints_do_not_construct_kernel_directly():
    root = Path(__file__).parents[1]
    entrypoints = [
        root / "intent_kernel" / "__main__.py",
        root / "intent_kernel" / "server" / "app.py",
        root / "intent_os_desktop" / "__init__.py",
    ]

    for path in entrypoints:
        assert "Kernel(" not in path.read_text(encoding="utf-8")


def test_historical_registry_can_be_locked_against_new_registration():
    registry = CapabilityRegistry(read_only=True)

    with pytest.raises(RuntimeError, match="read-only"):
        registry.register("new", "not allowed", "legacy")
