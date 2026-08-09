"""Test: Pipeline execution."""

import pytest
from intent_kernel.engine.pipeline import PipelineDAG
from intent_kernel.engine import nodes
from intent_kernel.types import Mode, ParsedIntent, Domain


def _make_intent(text: str = "test") -> ParsedIntent:
    return ParsedIntent(
        raw_text=text,
        intent=text,
        domain=Domain.OTHER,
        mode=Mode.BASIC,
    )


@pytest.fixture
def pipeline():
    p = PipelineDAG()
    p.register("intake", nodes.intake_node)
    p.register("classify", nodes.classify_node)
    p.register("diagnose", nodes.diagnose_node)
    p.register("plan", nodes.plan_node)
    p.register("build", nodes.build_node)
    p.register("stress_test", nodes.stress_test_node)
    p.register("review", nodes.review_node)
    p.register("knowledge_check", nodes.knowledge_check_node)
    p.register("deliver", nodes.deliver_node)
    return p


@pytest.mark.asyncio
async def test_pipeline_quick_mode(pipeline):
    """QUICK mode runs minimal nodes."""
    intent = _make_intent("hello")
    intent.mode = Mode.QUICK
    result = await pipeline.execute(intent, Mode.QUICK)
    assert result.mode == Mode.QUICK
    assert result.output_text  # should have output


@pytest.mark.asyncio
async def test_pipeline_basic_mode(pipeline):
    """BASIC mode runs standard path."""
    result = await pipeline.execute(_make_intent(), Mode.BASIC)
    assert result.mode == Mode.BASIC
    assert result.output_text


@pytest.mark.asyncio
async def test_pipeline_detail_mode(pipeline):
    """DETAIL mode runs extended path."""
    result = await pipeline.execute(_make_intent(), Mode.DETAIL)
    assert result.mode == Mode.DETAIL
    assert result.output_text


@pytest.mark.asyncio
async def test_pipeline_expert_mode(pipeline):
    """EXPERT mode includes stress test."""
    result = await pipeline.execute(_make_intent(), Mode.EXPERT)
    assert result.mode == Mode.EXPERT
    assert "Stress Test" in result.output_text


@pytest.mark.asyncio
async def test_pipeline_architect_mode(pipeline):
    """ARCHITECT mode includes knowledge check."""
    result = await pipeline.execute(_make_intent(), Mode.ARCHITECT)
    assert result.mode == Mode.ARCHITECT
    assert result.output_text


@pytest.mark.asyncio
async def test_pipeline_deliver_adds_metadata(pipeline):
    """Deliver node adds mode/domain metadata."""
    result = await pipeline.execute(_make_intent("test finance"), Mode.BASIC)
    assert "BASIC" in result.output_text
    assert "Confiança" in result.output_text
