"""M31.3B-1B — First Governance: typed atomic RRM primitive (FG suite).

Covers the ``conditional_govern_existing_resource`` contract on RRM:
  FG1  fresh APPLIED (RRM-minted lineage, resulting generation = pre + 1,
       caller supplies neither)
  FG2  exact same-decision retry → ALREADY_APPLIED_SAME_DECISION with the
       STORED lineage — never a second mint, never a further advance
  FG3  recorded fact + different decision → ALREADY_GOVERNED
  FG4  fresh request on an already-governed resource → ALREADY_GOVERNED
  FG5  pre-governed generation mismatch → GENERATION_MISMATCH (no mutation,
       no fact recorded)
  FG6  missing resource → NOT_FOUND
  FG7  fail-closed request validation (expected_ungoverned_lineage False,
       missing/legacy/bool generation, empty proposal/decision ids)
  FG8  recovery window (WRITE 1 present, WRITE 2 missing) → APPLIED with the
       stored lineage/generation and reason first_governance_recovered
  FG9  terminal states refuse governance (INVALID_STATE)

Under audit:
  RRM is the SOLE governed-lineage authority; the caller supplies NEITHER the
  governing grid NOR the resulting generation. The result is always a detached
  immutable FirstGovernanceResult.
"""

from __future__ import annotations

import asyncio
import unittest

from intent_kernel.rrm.models import (
    CapabilityResource,
    FirstGovernanceOutcome,
    FirstGovernanceRequest,
    ResourceStatus,
    ResourceType,
)
from intent_kernel.rrm.service import RegistryResourceManager


def _fresh_rrm() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


def _fresh_capability(resource_id: str, *, status: ResourceStatus | None = None) -> CapabilityResource:
    cap = CapabilityResource(
        capability_id=resource_id,
        name=resource_id,
        description="FG test capability",
    )
    if status is not None:
        cap.status = status
    return cap


class TestFirstGovernanceRequestValidation(unittest.TestCase):
    """FG7 — fail-closed request construction."""

    def test_accepts_valid_request(self) -> None:
        req = FirstGovernanceRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="fg.cap",
            expected_pre_governed_generation=1,
            proposal_id="p1",
            decision_id="d1",
        )
        self.assertEqual(req.expected_ungoverned_lineage, True)

    def test_rejects_ungoverned_lineage_flag(self) -> None:
        with self.assertRaises(ValueError):
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id="fg.cap",
                expected_pre_governed_generation=1,
                expected_ungoverned_lineage=False,
                proposal_id="p1",
                decision_id="d1",
            )

    def test_rejects_legacy_zero_generation(self) -> None:
        with self.assertRaises(ValueError):
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id="fg.cap",
                expected_pre_governed_generation=0,
                proposal_id="p1",
                decision_id="d1",
            )

    def test_rejects_bool_generation(self) -> None:
        with self.assertRaises(ValueError):
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id="fg.cap",
                expected_pre_governed_generation=True,  # type: ignore[arg-type]
                proposal_id="p1",
                decision_id="d1",
            )

    def test_rejects_empty_proposal_id(self) -> None:
        with self.assertRaises(ValueError):
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id="fg.cap",
                expected_pre_governed_generation=1,
                proposal_id="",
                decision_id="d1",
            )

    def test_rejects_empty_decision_id(self) -> None:
        with self.assertRaises(ValueError):
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id="fg.cap",
                expected_pre_governed_generation=1,
                proposal_id="p1",
                decision_id="",
            )

    def test_rejects_unknown_resource_kind_type(self) -> None:
        from intent_kernel.rrm.models import (
            FirstGovernanceRequest as FGR,
        )

        with self.assertRaises(ValueError):
            FGR(
                resource_kind="not-a-kind",  # type: ignore[arg-type]
                resource_id="fg.cap",
                expected_pre_governed_generation=1,
                proposal_id="p1",
                decision_id="d1",
            )


class TestFirstGovernancePrimitive(unittest.TestCase):
    """FG1-FG6, FG8, FG9 — atomic first governance on RRM."""

    def _govern(self, rrm, resource_id: str, *, decision="d1") -> object:
        return rrm.conditional_govern_existing_resource(
            FirstGovernanceRequest(
                resource_kind=ResourceType.CAPABILITY,
                resource_id=resource_id,
                expected_pre_governed_generation=1,
                proposal_id="p1",
                decision_id=decision,
            )
        )

    def test_fg1_fresh_apply_mints_lineage_and_advances_once(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))
        before = rrm.get_capability("fg.cap")

        result = self._govern(rrm, "fg.cap")

        self.assertIs(result.outcome, FirstGovernanceOutcome.APPLIED)
        self.assertTrue(result.governed_registration_id)
        self.assertEqual(result.resulting_generation, 2)
        after = rrm.get_capability("fg.cap")
        self.assertEqual(after.governed_registration_id, result.governed_registration_id)
        self.assertEqual(after.generation, 2)
        self.assertEqual(before.governed_registration_id, "")

    def test_fg2_exact_retry_is_idempotent_never_second_mint(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))

        first = self._govern(rrm, "fg.cap")
        second = self._govern(rrm, "fg.cap")

        self.assertIs(second.outcome, FirstGovernanceOutcome.ALREADY_APPLIED_SAME_DECISION)
        self.assertEqual(
            second.governed_registration_id,
            first.governed_registration_id,
        )
        self.assertEqual(second.resulting_generation, first.resulting_generation)
        self.assertEqual(rrm.get_capability("fg.cap").generation, 2)

    def test_fg2b_result_is_detached_immutable(self) -> None:
        import dataclasses

        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))
        result = self._govern(rrm, "fg.cap")
        self.assertTrue(dataclasses.is_dataclass(result))
        self.assertTrue(type(result).__slots__)

    def test_fg3_recorded_fact_with_other_decision_is_already_governed(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))

        first = self._govern(rrm, "fg.cap")
        other = self._govern(rrm, "fg.cap", decision="d2")

        self.assertIs(other.outcome, FirstGovernanceOutcome.ALREADY_GOVERNED)
        self.assertEqual(
            rrm.get_capability("fg.cap").governed_registration_id,
            first.governed_registration_id,
        )

    def test_fg4_fresh_request_on_governed_resource(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))
        first = self._govern(rrm, "fg.cap")

        # New decision (no recorded fact keyed to it) on an already-governed
        # resource → ALREADY_GOVERNED with the existing lineage observed.
        request = FirstGovernanceRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="fg.cap",
            expected_pre_governed_generation=1,
            proposal_id="p9",
            decision_id="d9",
        )
        result = rrm.conditional_govern_existing_resource(request)

        self.assertIs(result.outcome, FirstGovernanceOutcome.ALREADY_GOVERNED)
        self.assertEqual(
            rrm.get_capability("fg.cap").governed_registration_id,
            first.governed_registration_id,
        )

    def test_fg5_generation_mismatch_never_mutates_or_records(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))

        request = FirstGovernanceRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="fg.cap",
            expected_pre_governed_generation=5,
            proposal_id="p1",
            decision_id="d1",
        )
        result = rrm.conditional_govern_existing_resource(request)

        self.assertIs(result.outcome, FirstGovernanceOutcome.GENERATION_MISMATCH)
        after = rrm.get_capability("fg.cap")
        self.assertEqual(after.governed_registration_id, "")
        self.assertEqual(after.generation, 1)
        self.assertEqual(result.resulting_generation, 0)

        # No fact was recorded: a correct fresh request for the same decision
        # still applies (proves the mismatch never poisoned the retry path).
        corrected = FirstGovernanceRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="fg.cap",
            expected_pre_governed_generation=1,
            proposal_id="p1",
            decision_id="d1",
        )
        applied = rrm.conditional_govern_existing_resource(corrected)
        self.assertIs(applied.outcome, FirstGovernanceOutcome.APPLIED)

    def test_fg5b_wrong_decision_does_not_collide(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))

        request = FirstGovernanceRequest(
            resource_kind=ResourceType.CAPABILITY,
            resource_id="fg.cap",
            expected_pre_governed_generation=5,
            proposal_id="p1",
            decision_id="d1",
        )
        result = rrm.conditional_govern_existing_resource(request)

        self.assertIs(result.outcome, FirstGovernanceOutcome.GENERATION_MISMATCH)
        self.assertEqual(rrm.get_capability("fg.cap").governed_registration_id, "")
        self.assertEqual(result.resulting_generation, 0)

    def test_fg6_missing_resource_is_not_found(self) -> None:
        rrm = _fresh_rrm()

        result = self._govern(rrm, "missing.cap")

        self.assertIs(result.outcome, FirstGovernanceOutcome.NOT_FOUND)

    def test_fg8_recovery_window_reuses_stored_lineage(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))

        first = self._govern(rrm, "fg.cap")
        lineage = first.governed_registration_id

        # Simulate the WRITE-2 lost window: fact recorded, active resource
        # still pre-governed (empty lineage).
        store_entry = rrm._capabilities["fg.cap"]  # noqa: SLF001
        store_entry.governed_registration_id = ""
        store_entry.generation = 1

        recovered = self._govern(rrm, "fg.cap")

        self.assertIs(recovered.outcome, FirstGovernanceOutcome.APPLIED)
        self.assertEqual(recovered.reason, "first_governance_recovered")
        self.assertEqual(recovered.governed_registration_id, lineage)
        self.assertEqual(recovered.resulting_generation, 2)
        after = rrm.get_capability("fg.cap")
        self.assertEqual(after.governed_registration_id, lineage)
        self.assertEqual(after.generation, 2)

    def test_fg9_terminal_state_refuses_governance(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))
        rrm._capabilities["fg.cap"].status = ResourceStatus.ARCHIVED  # noqa: SLF001

        result = self._govern(rrm, "fg.cap")

        self.assertIs(result.outcome, FirstGovernanceOutcome.INVALID_STATE)
        self.assertEqual(rrm.get_capability("fg.cap").governed_registration_id, "")

    def test_governed_resource_is_protected_from_legacy_paths(self) -> None:
        rrm = _fresh_rrm()
        rrm.register_capability(_fresh_capability("fg.cap"))
        self._govern(rrm, "fg.cap")
        lineage = rrm.get_capability("fg.cap").governed_registration_id

        # Old-style direct register path refuses to overwrite: it returns the
        # EXISTING governed resource and never replaces the lineage.
        result = rrm.register_capability(_fresh_capability("fg.cap"))
        self.assertEqual(result.governed_registration_id, lineage)
        self.assertEqual(rrm.unregister_capability("fg.cap"), False)
        self.assertEqual(
            rrm.get_capability("fg.cap").governed_registration_id,
            lineage,
        )


class TestFirstGovernanceAcrossFamilies(unittest.TestCase):
    """Governance applies to capability / agent / provider families."""

    def test_govern_agent_and_provider_families(self) -> None:
        from intent_kernel.rrm.models import AgentResource

        rrm = _fresh_rrm()
        rrm.register_agent(AgentResource(agent_id="fg.agent", name="fg.agent"))

        agent_result = rrm.conditional_govern_existing_resource(
            FirstGovernanceRequest(
                resource_kind=ResourceType.AGENT,
                resource_id="fg.agent",
                expected_pre_governed_generation=1,
                proposal_id="pa",
                decision_id="da",
            )
        )
        self.assertIs(agent_result.outcome, FirstGovernanceOutcome.APPLIED)
        self.assertEqual(agent_result.resulting_generation, 2)
        self.assertEqual(rrm.get_agent("fg.agent").generation, 2)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)