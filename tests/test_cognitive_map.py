"""Test: Cognitive Map — Interactive Knowledge Graph."""

import pytest
from intent_kernel.cognitive_map import CognitiveMap, MapNode, MapEdge
from intent_kernel.kernel import Kernel


@pytest.fixture
def cmap():
    kernel = Kernel()
    return CognitiveMap(kernel)


@pytest.fixture
def cmap_no_kernel():
    return CognitiveMap()


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_empty(cmap_no_kernel):
    result = await cmap_no_kernel.generate()
    assert result["nodes"] == []
    assert result["edges"] == []


@pytest.mark.asyncio
async def test_generate_with_kernel(cmap):
    result = await cmap.generate()
    assert "nodes" in result
    assert "edges" in result
    assert "stats" in result


@pytest.mark.asyncio
async def test_generate_with_domain_filter(cmap):
    result = await cmap.generate(domain_filter="finance")
    assert isinstance(result["nodes"], list)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search(cmap_no_kernel):
    result = await cmap_no_kernel.search("test")
    assert result["query"] == "test"
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_search_with_kernel(cmap):
    result = await cmap.search("invest")
    assert isinstance(result["results"], list)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_no_kernel(cmap_no_kernel):
    stats = await cmap_no_kernel.get_stats()
    assert stats["total_events"] == 0


@pytest.mark.asyncio
async def test_stats_with_kernel(cmap):
    stats = await cmap.get_stats()
    assert "total_events" in stats


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

def test_color_mapping(cmap):
    assert cmap._get_color("decision") == "#6366f1"
    assert cmap._get_color("fact") == "#22c55e"
    assert cmap._get_color("unknown") == "#6b7280"


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_map_name(cmap):
    assert cmap.name == "cognitive_map"
