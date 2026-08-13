"""Movement 11.5: one governed durable memory authority."""

from datetime import timedelta
import pytest
from intent_kernel.application.memory_service import CanonicalMemoryService
from intent_kernel.ame import AdaptiveMemoryEngine, LocalKnowledgeObjectRepository
from intent_kernel.kom import KnowledgeObject, KnowledgeState
from intent_kernel.time_utils import utc_now
from product_bridge import ProductBridge

@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return ProductBridge()

async def chat(bridge, message, project="PROJECT_A", session="memory-session"):
    return await bridge.dispatch({"action": "chat", "message": message, "project_id": project, "session_id": session})

@pytest.mark.asyncio
async def test_project_fact_correction_supersedes_only_same_scoped_truth(bridge):
    await chat(bridge, "Este projeto usa Flutter.")
    await chat(bridge, "Na verdade este projeto agora usa Kotlin.")
    await chat(bridge, "Este projeto usa React.", project="PROJECT_B")
    current_a = await bridge.memory_service.recall("projeto usa", project_id="PROJECT_A")
    current_b = await bridge.memory_service.recall("projeto usa", project_id="PROJECT_B")
    history_a = await bridge.ame_repo.query(project_id="PROJECT_A", status=None, include_global=False)
    assert [item.content for item in current_a.objects] == ["Na verdade este projeto agora usa Kotlin."]
    assert [item.content for item in current_b.objects] == ["Este projeto usa React."]
    flutter = next(item for item in history_a if "Flutter" in item.content)
    kotlin = next(item for item in history_a if "Kotlin" in item.content)
    assert flutter.status is KnowledgeState.SUPERSEDED
    assert flutter.superseded_by == kotlin.object_id
    assert kotlin.supersedes == flutter.object_id
    assert kotlin.version == 2

@pytest.mark.asyncio
async def test_preference_correction_leaves_one_current_truth(bridge):
    await chat(bridge, "Prefiro respostas curtas.")
    await chat(bridge, "Agora prefiro respostas detalhadas.")
    result = await bridge.memory_service.recall("prefiro respostas", project_id="PROJECT_A")
    assert [item.content for item in result.objects] == ["Agora prefiro respostas detalhadas."]

@pytest.mark.asyncio
async def test_question_never_becomes_durable_fact(bridge):
    await chat(bridge, "Este projeto usa Flutter?")
    assert await bridge.ame_repo.query(project_id="PROJECT_A", include_global=False) == []

@pytest.mark.asyncio
async def test_session_known_context_is_not_durable_memory(bridge):
    await chat(bridge, "Quero investir 24 mil por mês.")
    saved = bridge._load_session("memory-session")
    assert saved["conversation_state"]["known_context"]
    assert await bridge.ame_repo.query(project_id="PROJECT_A", include_global=False) == []

@pytest.mark.asyncio
async def test_expired_and_confidential_memory_fail_closed():
    ame = AdaptiveMemoryEngine(repository=LocalKnowledgeObjectRepository())
    service = CanonicalMemoryService(ame)
    await ame.store_object(KnowledgeObject(object_id="expired", content="fato expirado", project_id="P", valid_until=(utc_now() - timedelta(days=1)).isoformat()))
    await ame.store_object(KnowledgeObject(object_id="confidential", content="plano confidencial", project_id="P", sensitivity="confidential"))
    normal = await service.recall("fato plano", project_id="P")
    privileged = await service.recall("plano confidencial", project_id="P", sensitivity_limit="confidential")
    assert normal.objects == []
    assert [item.object_id for item in privileged.objects] == ["confidential"]

@pytest.mark.asyncio
async def test_memory_write_does_not_create_parallel_pkb_truth(bridge):
    before = await bridge.components.knowledge_pipeline.count()
    await chat(bridge, "Este projeto usa Flutter.")
    assert await bridge.components.knowledge_pipeline.count() == before
    current = await bridge.memory_service.recall("Flutter", project_id="PROJECT_A")
    assert len(current.objects) == 1
    assert current.objects[0].metadata["pkb_role"] == "curation_projection_only"

@pytest.mark.asyncio
async def test_restart_preserves_corrected_project_truth(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    first = ProductBridge()
    await chat(first, "Este projeto usa Flutter.")
    await chat(first, "Na verdade este projeto agora usa Kotlin.")
    restarted = ProductBridge()
    answer = await chat(restarted, "Qual tecnologia este projeto usa?")
    assert "Kotlin" in answer["text"]
    assert "Flutter" not in answer["text"]
    assert answer["mission_id"] is None
