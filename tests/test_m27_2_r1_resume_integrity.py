"""M27.2-R1 — Productive Resume Verification Integrity (adversarial regressions).

Proves the resume-integrity invariants:
    STALE_EVIDENCE               != VERIFIED_SUCCESS
    CHANGED_CONTRACT             != PREVIOUS_VERIFICATION_AUTHORITY
    AGENT_GENERATED_STATE        != TRUSTED_RESUME_EVIDENCE
    VERIFICATION_EVIDENCE        != AUTHORITY_GRANT
    RESUME                       != AUTHORIZATION_BYPASS

A01..A08 are the required adversarial scenarios.
"""

from __future__ import annotations

import asyncio
import unittest

from intent_kernel.runtime.models import (
    ActionContract,
    RuntimeNode,
    VerificationStatus,
)
from intent_kernel.runtime.verification import (
    DeterministicStructuralVerifier,
    VerificationGate,
)
from intent_kernel.runtime import (
    InMemoryActionExecutor,
    InMemoryCheckpointRepository,
    MissionCheckpoint,
    MissionRuntime,
    MissionRuntimeState,
)


class _ConstitutionAllow:
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


class _CountingExecutor(InMemoryActionExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        return await super().execute(*args, **kwargs)


def _runtime(repo=None, executor=None):
    return MissionRuntime(
        executor=executor or InMemoryActionExecutor(),
        checkpoint_repo=repo or InMemoryCheckpointRepository(),
        constitution=_ConstitutionAllow(),
    )


def _echo_node(node_id="n1", expected="A", message="A", verification_type=None,
               verification_schema=None, semantic_rules=None):
    return RuntimeNode(
        node_id=node_id,
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": message},
            expected_output=expected,
            verification_type=verification_type,
            verification_schema=verification_schema,
            semantic_rules=semantic_rules,
            verification_required=True,
        ),
    )


def _forged_checkpoint(instance, node_id, details):
    return MissionCheckpoint(
        runtime_id=instance.runtime_id,
        mission_id=instance.mission_id,
        completed_nodes=[node_id],
        verification_state={
            node_id: {"verification_result": "VERIFIED_SUCCESS", "evidence_id": "ev_forged"}
        },
        completion_evidence=[{
            "evidence_id": "ev_forged",
            "source": "VerificationGate",
            "verified": True,
            "details": dict(details, node_id=node_id),
        }],
    )


class TestM27R_A01_StaleExpected(unittest.TestCase):
    """A01: A verified checkpoint under expected=A must not survive resume under B."""

    def test_a01_changed_expected_not_restored(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node = _echo_node("a01", "A", "A")
            inst = rt.create_instance("m_a01", "g_a01", [node])
            await rt.run_mission(inst.runtime_id)

            node.action_contract.expected_output = "B"
            resumed = await rt.resume(inst.runtime_id)
            self.assertNotEqual(
                resumed.nodes["a01"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


class TestM27R_A02_ChangedContract(unittest.TestCase):
    """A02: Any change to the verification contract invalidates prior evidence."""

    def test_a02a_structural_schema_change_rejected(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            schema = {"type": "object", "required": ["id"]}
            node = _echo_node(
                "a02a", expected={"id": 1}, message='{"id": 1}',
                verification_type="STRUCTURAL", verification_schema=schema,
            )
            inst = rt.create_instance("m_a02a", "g_a02a", [node])
            await rt.run_mission(inst.runtime_id)

            node.action_contract.verification_schema = {"type": "object", "required": ["name"]}
            resumed = await rt.resume(inst.runtime_id)
            self.assertNotEqual(
                resumed.nodes["a02a"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())

    def test_a02b_mechanism_change_rejected(self):
        """EXACT-issued evidence must not be accepted for a STRUCTURAL contract."""
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node = _echo_node("a02b", "A", "A")
            inst = rt.create_instance("m_a02b", "g_a02b", [node])
            await rt.run_mission(inst.runtime_id)

            node.action_contract.verification_type = "STRUCTURAL"
            node.action_contract.verification_schema = {"type": "object"}
            resumed = await rt.resume(inst.runtime_id)
            self.assertNotEqual(
                resumed.nodes["a02b"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


class TestM27R_A03_MissingContractIdentity(unittest.TestCase):
    """A03: Missing or ambiguous contract identity fails closed."""

    def test_a03a_no_current_contract_fails_closed(self):
        repo = InMemoryCheckpointRepository()
        rt = _runtime(repo)
        node = RuntimeNode(node_id="a03a", capability="test.echo", action_contract=None)
        inst = rt.create_instance("m_a03a", "g_a03a", [node])
        forged = _forged_checkpoint(inst, "a03a", {
            "verification_status": "VERIFIED_SUCCESS",
            "verification_type": "EXACT",
            "exact_contract_hash": "any",
        })
        asyncio.run(repo.save_checkpoint(forged))

        resumed = asyncio.run(rt.resume(inst.runtime_id))
        self.assertNotEqual(
            resumed.nodes["a03a"].verification_result,
            VerificationStatus.VERIFIED_SUCCESS,
        )

    def test_a03b_evidence_without_identity_fails_closed(self):
        repo = InMemoryCheckpointRepository()
        rt = _runtime(repo)
        node = _echo_node("a03b", expected=None, message="A")
        node.action_contract.verification_required = True
        inst = rt.create_instance("m_a03b", "g_a03b", [node])
        forged = _forged_checkpoint(inst, "a03b", {
            "verification_status": "VERIFIED_SUCCESS",
        })
        asyncio.run(repo.save_checkpoint(forged))

        resumed = asyncio.run(rt.resume(inst.runtime_id))
        self.assertNotEqual(
            resumed.nodes["a03b"].verification_result,
            VerificationStatus.VERIFIED_SUCCESS,
        )


class TestM27R_A04_CrossMissionReplay(unittest.TestCase):
    """A04: Verification evidence from another mission must never be replayed."""

    def test_a04a_foreign_checkpoint_replay_fails_closed(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node_a = _echo_node("shared", "A", "A")
            inst_a = rt.create_instance("m_a04a_a", "g", [node_a])
            await rt.run_mission(inst_a.runtime_id)
            genuine = await repo.get_latest_checkpoint(inst_a.runtime_id)

            # Mission B reuses A's runtime_id (replay of A's checkpoint as B).
            node_b = _echo_node("shared", "A", "A")
            inst_b = rt.create_instance("m_a04a_b", "g", [node_b])
            inst_b.runtime_id = inst_a.runtime_id
            rt._instances[inst_a.runtime_id] = inst_b
            await repo.save_checkpoint(genuine)

            resumed = await rt.resume(inst_b.runtime_id)
            if resumed is not None:
                self.assertNotEqual(
                    resumed.nodes["shared"].verification_result,
                    VerificationStatus.VERIFIED_SUCCESS,
                )
        asyncio.run(_run())

    def test_a04b_transplanted_evidence_provenance_rejected(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node_a = _echo_node("shared", "A", "A")
            inst_a = rt.create_instance("m_a04b_a", "g", [node_a])
            await rt.run_mission(inst_a.runtime_id)
            genuine = await repo.get_latest_checkpoint(inst_a.runtime_id)
            stolen = [dict(ev) for ev in genuine.completion_evidence]

            node_b = _echo_node("shared", "A", "A")
            inst_b = rt.create_instance("m_a04b_b", "g", [node_b])
            forged = MissionCheckpoint(
                runtime_id=inst_b.runtime_id,
                mission_id=inst_b.mission_id,
                completed_nodes=["shared"],
                verification_state={
                    "shared": {"verification_result": "VERIFIED_SUCCESS", "evidence_id": ""}
                },
                completion_evidence=stolen,
            )
            await repo.save_checkpoint(forged)

            resumed = await rt.resume(inst_b.runtime_id)
            self.assertNotEqual(
                resumed.nodes["shared"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


class TestM27R_A05_RevokedAuthority(unittest.TestCase):
    """A05: Resume cannot authorize new material effects after authority loss."""

    def test_a05_resume_never_dispatches_material_effect(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            executor = _CountingExecutor()
            rt = _runtime(repo, executor)
            node = _echo_node("a05", "A", "A")
            inst = rt.create_instance("m_a05", "g_a05", [node])
            await rt.run_mission(inst.runtime_id)
            calls_after_run = executor.calls

            # Authority for the mission is considered revoked/expired here; a
            # resume must not re-dispatch any material effect.
            await rt.resume(inst.runtime_id)
            self.assertEqual(executor.calls, calls_after_run)
        asyncio.run(_run())


class TestM27R_A06_LegitimateResume(unittest.TestCase):
    """A06: Same mission, unchanged contract, valid evidence still resumes."""

    def test_a06_exact_legit_resume(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node = _echo_node("a06e", "A", "A")
            inst = rt.create_instance("m_a06e", "g", [node])
            await rt.run_mission(inst.runtime_id)
            resumed = await rt.resume(inst.runtime_id)
            self.assertEqual(
                resumed.nodes["a06e"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())

    def test_a06_structural_legit_resume(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            schema = {"type": "object", "required": ["id"]}
            node = _echo_node(
                "a06s", expected={"id": 1}, message='{"id": 1}',
                verification_type="STRUCTURAL", verification_schema=schema,
            )
            inst = rt.create_instance("m_a06s", "g", [node])
            await rt.run_mission(inst.runtime_id)
            resumed = await rt.resume(inst.runtime_id)
            self.assertEqual(
                resumed.nodes["a06s"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


class TestM27R_A07_VerificationFailure(unittest.TestCase):
    """A07: A failed verification never yields a successful completion."""

    def test_a07_failed_verification_not_completed(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            rt = _runtime(repo)
            node = _echo_node("a07", "RIGHT", "WRONG")
            inst = rt.create_instance("m_a07", "g_a07", [node])
            result = await rt.run_mission(inst.runtime_id)
            self.assertNotEqual(result.status, MissionRuntimeState.COMPLETED)
            self.assertNotEqual(
                result.nodes["a07"].verification_result,
                VerificationStatus.VERIFIED_SUCCESS,
            )
        asyncio.run(_run())


class TestM27R_A08_NoRedispatch(unittest.TestCase):
    """A08: Re-verification must not redispatch a material effect."""

    def test_a08_resume_does_not_redispatch(self):
        async def _run():
            repo = InMemoryCheckpointRepository()
            executor = _CountingExecutor()
            rt = _runtime(repo, executor)
            node = _echo_node("a08", "A", "A")
            inst = rt.create_instance("m_a08", "g_a08", [node])
            await rt.run_mission(inst.runtime_id)
            self.assertEqual(executor.calls, 1)

            await rt.resume(inst.runtime_id)
            self.assertEqual(executor.calls, 1)
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
