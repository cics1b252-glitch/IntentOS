"""Sprint 0 characterization tests.

These assertions intentionally document the current behavior. They are not a
statement that the behavior is ideal, and must not be relaxed to hide future
changes.
"""

from __future__ import annotations

from intent_kernel.__main__ import interactive_loop
from intent_kernel.constitution import create_default_constitution
from intent_kernel.engine.intent_engine import IntentEngine
from intent_kernel.engine.pipeline import PipelineDAG
from intent_kernel.kernel import Kernel
from intent_kernel.pkb.curator import KnowledgeCurator
from intent_kernel.pkb.json_store import JsonFileStore
from intent_kernel.pkb.knowledge_manager import KnowledgeManager
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.providers.manager import ProviderManager
from intent_kernel.providers.mock_provider import MockProvider
from intent_kernel.types import (
    Domain,
    EventLifecycle,
    EventType,
    Message,
    Mode,
    ParsedIntent,
    PipelineContext,
    QueryFilters,
)


async def test_kernel_process_uses_current_finance_path(tmp_path):
    kernel = Kernel(pkb_path=str(tmp_path / "pkb"))

    result = await kernel.process("Como investir dinheiro?")

    assert result.domain is Domain.FINANCE
    assert result.mode is Mode.QUICK
    assert result.text
    assert "Consultar um profissional financeiro registrado" in result.next_steps
    assert kernel.status()["providers"] == ["mock"]


async def test_intent_engine_current_short_input_heuristics():
    parsed = await IntentEngine().parse("Oi")

    assert parsed.intent == "Oi"
    assert parsed.domain is Domain.OTHER
    assert parsed.mode is Mode.QUICK
    assert len(parsed.ambiguities) == 1


async def test_pipeline_dag_current_quick_path_order():
    seen: list[str] = []
    pipeline = PipelineDAG()

    def node(name):
        async def run(context: PipelineContext) -> PipelineContext:
            seen.append(name)
            context.output_text = name
            return context

        return run

    for name in ("intake", "classify", "build", "deliver"):
        pipeline.register(name, node(name))

    intent = ParsedIntent("oi", "oi", Domain.OTHER, Mode.QUICK)
    result = await pipeline.execute(intent, Mode.QUICK)

    assert seen == ["intake", "classify", "build", "deliver"]
    assert result.output_text == "deliver"


async def test_provider_manager_routes_every_mode_to_first_provider():
    manager = ProviderManager()
    first = MockProvider()
    second = MockProvider()
    manager.register("first", first)
    manager.register("second", second)

    assert manager.default == "first"
    assert await manager.route(Mode.QUICK) is first
    assert await manager.route(Mode.ARCHITECT) is first


async def test_mock_provider_current_finance_template():
    result = await MockProvider().complete(
        [Message(role="user", content="Quero investir dinheiro")]
    )

    assert result.model == "mock-v1"
    assert result.usage == {"prompt_tokens": 0, "completion_tokens": 0}
    assert result.text.startswith("**Análise Financeira**")
    assert "Não constitui aconselhamento financeiro" in result.text


def test_current_constitution_shape():
    constitution = create_default_constitution()

    assert constitution.version == "1.0.0"
    assert [pillar.id for pillar in constitution.pillars] == [
        "soberania",
        "verdade",
        "continuidade",
        "evolucao",
    ]


async def test_knowledge_manager_current_transient_and_memory_behavior(tmp_path):
    manager = KnowledgeManager(JsonFileStore(str(tmp_path / "pkb")))
    transient = KnowledgeEvent(
        type=EventType.DECISION,
        title="Baixa confiança",
        summary="Caracterização",
        confidence=0.2,
    )
    memory = KnowledgeEvent(
        type=EventType.MEMORY,
        title="Preferência",
        summary="Caracterização",
        confidence=0.1,
    )

    result = await manager.ingest([transient, memory])

    assert result.total == 2
    assert result.transient == 1
    assert result.approved == 1
    assert await manager.count() == 1


async def test_curator_v1_current_threshold_boundaries():
    curator = KnowledgeCurator()

    at_point_three = KnowledgeEvent(title="A", summary="A", confidence=0.3)
    at_point_six = KnowledgeEvent(title="B", summary="B", confidence=0.6)

    assert await curator.evaluate(at_point_three) is EventLifecycle.CANDIDATE
    assert await curator.evaluate(at_point_six) is EventLifecycle.APPROVED


async def test_json_file_store_current_round_trip_and_index(tmp_path):
    store = JsonFileStore(str(tmp_path / "pkb"))
    event = KnowledgeEvent(
        type=EventType.DECISION,
        domain=Domain.PLANNING,
        title="Baseline",
        summary="Sprint 0",
        confidence=0.8,
    )

    event_id = await store.append(event)
    restored = await store.get(event_id)

    assert restored is not None
    assert restored.title == "Baseline"
    assert store.index_path.exists()
    assert len(await store.query(QueryFilters(search_text="baseline"))) == 1


async def test_cli_current_quit_flow(monkeypatch, capsys, tmp_path):
    answers = iter(["/status", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    kernel = Kernel(pkb_path=str(tmp_path / "pkb"))

    await interactive_loop(kernel)

    output = capsys.readouterr().out
    assert "Intent OS v0.1.0" in output
    assert "Status do Kernel" in output
    assert "mock" in output


async def test_fastapi_current_status_contract(monkeypatch, tmp_path):
    from httpx import ASGITransport, AsyncClient
    import intent_kernel.server.app as server_module

    monkeypatch.setattr(
        server_module,
        "_kernel",
        Kernel(pkb_path=str(tmp_path / "pkb")),
    )
    transport = ASGITransport(app=server_module.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["version"] == "0.1.0"
    assert response.json()["providers"] == ["mock"]
