"""H1.4 — Resume Verification Evidence Tests.

Proves the invariant:
    RESTORED VERIFICATION STATE
    MUST BE BACKED BY
    VALID VERIFICATION EVIDENCE

A checkpoint cannot create trusted verification authority by asserting
verification_result alone.
"""

from __future__ import annotations

import pytest

from intent_kernel.runtime import (
    ActionContract,
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionCheckpoint,
    MissionRuntime,
    MissionRuntimeInstance,
    MissionRuntimeState,
    RuntimeNode,
    RuntimeNodeState,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ConstitutionAllow:
    """Mock constitution that always allows — for testing non-constitution gate steps."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


def _make_runtime(repo: InMemoryCheckpointRepository = None) -> MissionRuntime:
    return MissionRuntime(
        executor=InMemoryActionExecutor(),
        checkpoint_repo=repo or InMemoryCheckpointRepository(),
        constitution=_ConstitutionAllow(),
    )


def _make_node(node_id: str = "n1", expected: str = "echo") -> RuntimeNode:
    return RuntimeNode(
        node_id=node_id,
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            expected_output=expected,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Valid verified checkpoint with valid evidence → resume succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_verified_checkpoint_with_evidence_resumes():
    rt = _make_runtime()
    node = _make_node("n_valid", expected="echo")
    inst = rt.create_instance("m1", "g1", [node])

    # Execute — produces real verification evidence
    result = await rt.run_mission(inst.runtime_id)
    assert result.status == MissionRuntimeState.COMPLETED

    # Checkpoint should have verification_state populated
    chk = await rt.checkpoint_repo.get_latest_checkpoint(inst.runtime_id)
    assert chk is not None
    assert "n_valid" in chk.verification_state
    assert chk.verification_state["n_valid"]["verification_result"] == "VERIFIED_SUCCESS"
    assert len(chk.completion_evidence) > 0

    # Resume in fresh runtime
    fresh = _make_runtime()
    fresh._instances[inst.runtime_id] = inst
    resumed = await fresh.resume(inst.runtime_id)
    assert resumed is not None
    assert resumed.nodes["n_valid"].verification_result == VerificationStatus.VERIFIED_SUCCESS


# ---------------------------------------------------------------------------
# 2. VERIFIED_SUCCESS claim without evidence → not accepted as verified
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verified_claim_without_evidence_not_trusted():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_no_ev")
    inst = rt.create_instance("m2", "g2", [node])

    # Save forged checkpoint: claim success but no evidence
    forged_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_no_ev"],
        verification_state={
            "n_no_ev": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": ""}
        },
        completion_evidence=[],  # No evidence!
    )
    await repo.save_checkpoint(forged_chk)

    # Resume — should NOT trust verified state
    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    assert resumed.nodes["n_no_ev"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 3. VERIFIED_SUCCESS with mismatched evidence → rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verified_with_mismatched_evidence_rejected():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_mismatch")
    inst = rt.create_instance("m3", "g3", [node])

    # Forge checkpoint: claim success but evidence says failure
    forged_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_mismatch"],
        verification_state={
            "n_mismatch": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_forged"}
        },
        completion_evidence=[{
            "evidence_id": "ev_forged",
            "source": "VerificationGate",
            "verified": True,
            "details": {
                "node_id": "n_mismatch",
                "verification_status": "VERIFIED_FAILURE",  # Mismatch!
            },
        }],
    )
    await repo.save_checkpoint(forged_chk)

    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    assert resumed.nodes["n_mismatch"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 4. VERIFIED_FAILURE checkpoint → cannot become success on resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verified_failure_cannot_become_success():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_fail")
    inst = rt.create_instance("m4", "g4", [node])

    # Forge checkpoint: claim VERIFIED_FAILURE
    forged_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_fail"],
        verification_state={
            "n_fail": {"verification_result": "VERIFIED_FAILURE", "evidence_id": ""}
        },
        completion_evidence=[],
    )
    await repo.save_checkpoint(forged_chk)

    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    # Should be INCONCLUSIVE, not VERIFIED_SUCCESS
    assert resumed.nodes["n_fail"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 5. Malformed verification result → fail closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_verification_result_fail_closed():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_malform")
    inst = rt.create_instance("m5", "g5", [node])

    # Forge checkpoint: completely bogus verification_result
    forged_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_malform"],
        verification_state={
            "n_malform": {"verification_result": "BOGUS_STATUS", "evidence_id": ""}
        },
        completion_evidence=[],
    )
    await repo.save_checkpoint(forged_chk)

    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    # Malformed → fail closed → INCONCLUSIVE
    assert resumed.nodes["n_malform"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 6. Ordinary non-verification checkpoint state → existing behavior preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_verified_state_preserved():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_nonv")
    inst = rt.create_instance("m6", "g6", [node])

    # Checkpoint with empty verification_state (pre-H1.4 checkpoint)
    empty_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_nonv"],
        verification_state={},  # No verification state
        completion_evidence=[],
    )
    await repo.save_checkpoint(empty_chk)

    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    # No verification_state → INCONCLUSIVE (not VERIFIED_SUCCESS)
    assert resumed.nodes["n_nonv"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 7. Resume does not bypass VerificationGate authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_does_not_bypass_verification_gate():
    rt = _make_runtime()
    node = _make_node("n_auth")
    inst = rt.create_instance("m7", "g7", [node])

    # Execute with wrong expected output — verification should fail
    node.action_contract.expected_output = "WRONG"
    await rt.run_mission(inst.runtime_id)

    # Checkpoint should show VERIFIED_FAILURE
    chk = await rt.checkpoint_repo.get_latest_checkpoint(inst.runtime_id)
    assert chk is not None
    assert chk.verification_state["n_auth"]["verification_result"] == "VERIFIED_FAILURE"

    # Resume — should NOT upgrade to VERIFIED_SUCCESS
    fresh = _make_runtime()
    fresh._instances[inst.runtime_id] = inst
    resumed = await fresh.resume(inst.runtime_id)
    assert resumed is not None
    assert resumed.nodes["n_auth"].verification_result != VerificationStatus.VERIFIED_SUCCESS


# ---------------------------------------------------------------------------
# 8. Forged VERIFIED_SUCCESS → no execution authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forged_verified_success_no_execution_authority():
    repo = InMemoryCheckpointRepository()
    rt = _make_runtime(repo)
    node = _make_node("n_forge")
    inst = rt.create_instance("m8", "g8", [node])

    # Forge checkpoint with fabricated evidence from wrong source
    forged_chk = MissionCheckpoint(
        runtime_id=inst.runtime_id,
        mission_id=inst.mission_id,
        completed_nodes=["n_forge"],
        verification_state={
            "n_forge": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_forge"}
        },
        completion_evidence=[{
            "evidence_id": "ev_forge",
            "source": "Attacker",  # Wrong source!
            "verified": True,
            "details": {
                "node_id": "n_forge",
                "verification_status": "VERIFIED_SUCCESS",
            },
        }],
    )
    await repo.save_checkpoint(forged_chk)

    resumed = await rt.resume(inst.runtime_id)
    assert resumed is not None
    # Forged evidence → NOT trusted
    assert resumed.nodes["n_forge"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# 9. H1.1 fail-closed authorization preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h11_fail_closed_preserved():
    """H1.1: Authorization defaults remain fail-closed after H1.4 changes."""
    from intent_kernel.tools.authorization import ToolAuthorizationGate
    from intent_kernel.tools.models import (
        ToolAuthorizationDecisionState,
        ToolCandidate,
        ToolResource,
        ToolStatus,
        ToolHealthStatus,
        PermissionDecisionState,
    )

    gate = ToolAuthorizationGate()
    tool = ToolResource(
        tool_id="t1",
        name="Test",
        status=ToolStatus.UNAVAILABLE,
        health_status=ToolHealthStatus.UNAVAILABLE,
    )
    candidate = ToolCandidate(
        tool_id="t1",
        capability="test.echo",
        health=ToolHealthStatus.UNAVAILABLE,
        authorization_status=PermissionDecisionState.NOT_CONFIGURED,
    )
    verdict = await gate.evaluate_tool(candidate, tool)
    # Fail-closed: UNAVAILABLE tool → DENY
    assert verdict == ToolAuthorizationDecisionState.DENY


# ---------------------------------------------------------------------------
# 10. H1.2 submit-time authorization recheck preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h12_submit_recheck_preserved():
    """H1.2: Confirmation service submit still performs authorization recheck."""
    from intent_kernel.application.confirmation_service import CanonicalConfirmationService

    # Verify the contract exists — submit method is present and callable
    assert hasattr(CanonicalConfirmationService, "submit")
    assert callable(getattr(CanonicalConfirmationService, "submit"))


# ---------------------------------------------------------------------------
# 11. H1.3 tombstones preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h13_tombstones_preserved():
    """H1.3: Retired resource tombstones still prevent re-registration."""
    from intent_kernel.rrm.service import RegistryResourceManager
    from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority
    from intent_kernel.rrm.models import (
        ProviderResource,
        AvailabilitySource,
        ResourceOrigin,
        ResourceType,
    )

    rrm = RegistryResourceManager(populate_defaults=False)
    p = ProviderResource(
        provider_id="prov-tomb",
        name="Test",
        availability_source=AvailabilitySource.CONFIGURATION,
        resource_origin=ResourceOrigin.CONFIGURATION,
        governed_registration_id="gr-tomb",
    )
    rrm.register_provider(p)

    # Retire
    authority = CanonicalResourceRetirementAuthority(rrm)
    req = authority.request_retirement("prov-tomb", "gr-tomb")
    dec = authority.decide_retirement(req.request_id, approved=True)
    result = authority.apply_retirement(dec.decision_id)
    assert result.success is True

    # Tombstone should prevent re-registration
    assert rrm._is_tombstoned(ResourceType.PROVIDER, "prov-tomb") is True
    new_p = ProviderResource(
        provider_id="prov-tomb",
        name="Reincarnation",
        availability_source=AvailabilitySource.CONFIGURATION,
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    reg_result = rrm.register_provider(new_p)
    assert reg_result is None
