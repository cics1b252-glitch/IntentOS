"""Test: Symbiotic Layer — Phase 2: Host Environment Awareness."""

import pytest
from intent_kernel.symbiotic import SymbioticLayer, SystemInfo, EnvironmentSnapshot


@pytest.fixture
def symbiotic():
    return SymbioticLayer()


# ---------------------------------------------------------------------------
# System scan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_completes(symbiotic):
    snapshot = await symbiotic.scan()
    assert isinstance(snapshot, EnvironmentSnapshot)
    assert snapshot.system.os_name  # not empty
    assert snapshot.system.python_version
    assert snapshot.system.cpu_count > 0


@pytest.mark.asyncio
async def test_system_info(symbiotic):
    snapshot = await symbiotic.scan()
    assert snapshot.system.os_name in ("Linux", "Darwin", "Windows")
    assert snapshot.system.hostname
    assert "python" in snapshot.system.python_version.lower() or "." in snapshot.system.python_version


@pytest.mark.asyncio
async def test_python_envs_detected(symbiotic):
    snapshot = await symbiotic.scan()
    assert isinstance(snapshot.python_environments, list)


@pytest.mark.asyncio
async def test_programs_detected(symbiotic):
    snapshot = await symbiotic.scan()
    assert isinstance(snapshot.installed_programs, list)
    # At minimum, python3 or python should be detected
    assert len(snapshot.installed_programs) > 0


@pytest.mark.asyncio
async def test_env_vars_captured(symbiotic):
    snapshot = await symbiotic.scan()
    assert "PATH" in snapshot.environment_vars


@pytest.mark.asyncio
async def test_key_directories(symbiotic):
    snapshot = await symbiotic.scan()
    assert isinstance(snapshot.key_directories, list)


@pytest.mark.asyncio
async def test_timestamp(symbiotic):
    snapshot = await symbiotic.scan()
    assert snapshot.timestamp  # not empty


# ---------------------------------------------------------------------------
# Knowledge Core integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_without_kernel(symbiotic):
    snapshot = await symbiotic.scan()
    result = await symbiotic.sync_to_knowledge_core(snapshot)
    assert "error" in result


@pytest.mark.asyncio
async def test_sync_with_kernel(symbiotic):
    from intent_kernel.kernel import Kernel
    symbiotic.kernel = Kernel()
    snapshot = await symbiotic.scan()
    result = await symbiotic.sync_to_knowledge_core(snapshot)
    assert result.get("synced") is True


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_symbiotic_name(symbiotic):
    assert symbiotic.name == "symbiotic_layer"
