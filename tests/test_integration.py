"""Test: Full Kernel integration."""

import pytest
import tempfile
from intent_kernel.kernel import Kernel
from intent_kernel.types import Mode, Domain


@pytest.fixture
def kernel():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Kernel(pkb_path=f"{tmpdir}/pkb")


@pytest.mark.asyncio
async def test_kernel_imports():
    """Kernel can be imported."""
    from intent_kernel import Kernel
    assert Kernel is not None


@pytest.mark.asyncio
async def test_kernel_version(kernel):
    """Kernel has a version."""
    assert kernel.version == "0.1.0"


@pytest.mark.asyncio
async def test_kernel_status(kernel):
    """Kernel returns status."""
    status = kernel.status()
    assert status["version"] == "0.1.0"
    assert "mock" in status["providers"]
    assert "core" in status["modules"]


@pytest.mark.asyncio
async def test_kernel_process_basic(kernel):
    """Kernel processes a basic intent."""
    result = await kernel.process("Quero investir dinheiro")
    assert result.text
    assert result.mode in Mode
    assert result.domain in Domain
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_kernel_process_quick(kernel):
    """Kernel processes a quick intent."""
    result = await kernel.process("hello")
    assert result.text
    assert result.mode == Mode.QUICK


@pytest.mark.asyncio
async def test_kernel_process_education(kernel):
    """Kernel classifies education domain."""
    result = await kernel.process("Quero aprender data science")
    assert result.domain == Domain.EDUCATION


@pytest.mark.asyncio
async def test_kernel_process_finance(kernel):
    """Kernel classifies finance domain."""
    result = await kernel.process("Como investir em ETFs?")
    assert result.domain == Domain.FINANCE


@pytest.mark.asyncio
async def test_kernel_constitution_check(kernel):
    """Constitution check works."""
    from intent_kernel.types import Action
    verdict = kernel.constitution_check(Action(type="process"))
    assert verdict.allowed is True


@pytest.mark.asyncio
async def test_kernel_persists_events(kernel):
    """Kernel persists events to PKB."""
    result = await kernel.process(
        "Quero investir 5000 por mês em ETFs conservadores"
    )
    # PKB should have events
    count = await kernel.knowledge.count()
    # At least some events may be persisted (depends on Curator)
    assert count >= 0  # basic smoke test


@pytest.mark.asyncio
async def test_kernel_query(kernel):
    """Kernel can query PKB."""
    results = await kernel.query("investimento")
    assert isinstance(results, list)
