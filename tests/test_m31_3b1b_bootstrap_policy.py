"""M31.3B-1B — Bootstrap First-Governance Policy + Production Chain (BB/BAS suite).

Covers:
  BB1  decide_bootstrap binds the EXACT declaration/evidence/pre-governed
       generation into a FirstGovernancePrecondition on an APPROVE decision
  BB2  decide_bootstrap fails closed on stale/revoked evidence
  BB3  decide_bootstrap fails closed on kind/resource mismatch and on
       missing/legacy/bool pre-governed generations
  BB4  end-to-end governed pipeline: evidence → proposal → bootstrap approval
       → govern_existing (decision consumed, proposal CONSUMED, lineage + gen)
  BB5  bootstrap_govern aggregate report fails closed on any missing resource
  BB6  govern_existing on an already-governed resource → failed result
  BB7  production chain governs a runtime-added core app and makes it resolvable
  BB8  productive-set regression: build gate governs EXACTLY 8 capabilities +
       3 agents + 1 provider (ame placeholders excluded) and finance.intent
       resolves eligible with a governed EXISTING_RESOURCE precondition while
       the mock provider stays ineligible
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import Capability
from intent_kernel.discovery.models import (
    ResourceDiscoveryEvidence,
    ResourceDiscoveryKind,
    ResourceDiscoveryStatus,
)
from intent_kernel.discovery.service import CanonicalResourceDiscoveryService
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import (
    BootstrapResourceDeclaration,
    FirstGovernancePrecondition,
    ResourcePromotionStatus,
)
from intent_kernel.promotion.promotion_service import CanonicalResourcePromotionService
from intent_kernel.rrm.models import (
    CapabilityResource,
    FirstGovernanceOutcome,
    ResourceType,
)
from intent_kernel.rrm.service import RegistryResourceManager


def _fresh() -> tuple[RegistryResourceManager, CanonicalResourcePromotionService]:
    rrm = RegistryResourceManager(populate_defaults=False)
    discovery = CanonicalResourceDiscoveryService(rrm=rrm)
    svc = CanonicalResourcePromotionService(
        discovery_service=discovery,
        rrm=rrm,
    )
    return rrm, svc


def _observed_evidence(discovery_id: str, resource_id: str) -> ResourceDiscoveryEvidence:
    return ResourceDiscoveryEvidence(
        discovery_id=discovery_id,
        resource_kind=ResourceDiscoveryKind.CAPABILITY,
        resource_id=resource_id,
        display_name=resource_id,
        source="bootstrap",
        status=ResourceDiscoveryStatus.OBSERVED,
        confidence=1.0,
    )


def _capability_declaration(resource_id: str, executor_id: str = "bpapp") -> BootstrapResourceDeclaration:
    return BootstrapResourceDeclaration(
        resource_kind=ResourceType.CAPABILITY,
        capability_name=resource_id,
        executor_kind="core_app",
        executor_id=executor_id,
    )


class TestDecideBootstrap(unittest.TestCase):
    """BB1-BB3 — MODEL_AP_B bootstrap approval authority."""

    def setUp(self) -> None:
        self.rrm, self.svc = _fresh()

    def _proposal(self, evidence: ResourceDiscoveryEvidence) -> object:
        self.rrm.register_capability(CapabilityResource(
            capability_id="bb.cap",
            name="bb.cap",
        ))
        self.svc._discovery.registry.add(evidence)  # noqa: SLF001
        return self.svc.create_proposal(evidence.discovery_id)

    def test_bb1_binds_exact_precondition_and_approves(self) -> None:
        evidence = _observed_evidence("boot-bb1", "bb.cap")
        proposal = self._proposal(evidence)
        decision = self.svc.decisions.decide_bootstrap(
            declaration=_capability_declaration("bb.cap"),
            evidence=evidence,
            proposal_id=proposal.proposal_id,
            observed_pre_governed_generation=1,
            decided_by="bootstrap_audit",
            reasoning="first governance",
        )

        self.assertEqual(decision.decision_id, decision.decision_id)
        self.assertIsInstance(
            decision.first_governance_precondition,
            FirstGovernancePrecondition,
        )
        precondition = decision.first_governance_precondition
        self.assertEqual(precondition.resource_kind, ResourceType.CAPABILITY)
        self.assertEqual(precondition.resource_id, "bb.cap")
        self.assertEqual(precondition.expected_pre_governed_generation, 1)
        self.assertEqual(precondition.expected_ungoverned_lineage, True)
        self.assertEqual(decision.decided_by, "bootstrap_audit")
        stored = self.svc.proposals.get_proposal(proposal.proposal_id)
        self.assertIs(stored.status, ResourcePromotionStatus.APPROVED)

    def test_bb2_rejects_non_observed_evidence(self) -> None:
        evidence = _observed_evidence("boot-bb2", "bb.cap")
        proposal = self._proposal(evidence)
        self.svc._discovery.revoke(evidence.discovery_id)  # noqa: SLF001

        with self.assertRaises(Exception):
            self.svc.decisions.decide_bootstrap(
                declaration=_capability_declaration("bb.cap"),
                evidence=self.svc._discovery.get(evidence.discovery_id),  # noqa: SLF001
                proposal_id=proposal.proposal_id,
                observed_pre_governed_generation=1,
            )

    def test_bb3a_rejects_kind_mismatch(self) -> None:
        evidence = _observed_evidence("boot-bb3a", "other.cap")
        self.svc._discovery.registry.add(evidence)  # noqa: SLF001
        proposal = self.svc.create_proposal(evidence.discovery_id)

        with self.assertRaises(Exception):
            self.svc.decisions.decide_bootstrap(
                declaration=_capability_declaration("bb.cap"),
                evidence=evidence,
                proposal_id=proposal.proposal_id,
                observed_pre_governed_generation=1,
            )

    def test_bb3b_rejects_missing_generation(self) -> None:
        evidence = _observed_evidence("boot-bb3b", "bb.cap")
        proposal = self._proposal(evidence)

        for bad in (0, True, "1"):
            with self.assertRaises(Exception, msg=f"generation={bad!r}"):
                self.svc.decisions.decide_bootstrap(
                    declaration=_capability_declaration("bb.cap"),
                    evidence=evidence,
                    proposal_id=proposal.proposal_id,
                    observed_pre_governed_generation=bad,  # type: ignore[arg-type]
                )

    def test_bb3c_rejects_proposal_mismatch(self) -> None:
        evidence = _observed_evidence("boot-bb3c", "bb.cap")
        self.svc._discovery.registry.add(evidence)  # noqa: SLF001
        other = ResourceDiscoveryEvidence(
            discovery_id="boot-bb3c-other",
            resource_kind=ResourceDiscoveryKind.CAPABILITY,
            resource_id="other.cap",
            display_name="other",
            source="bootstrap",
            status=ResourceDiscoveryStatus.OBSERVED,
            confidence=1.0,
        )
        self.svc._discovery.registry.add(other)  # noqa: SLF001
        proposal = self.svc.create_proposal("boot-bb3c-other")

        with self.assertRaises(Exception):
            self.svc.decisions.decide_bootstrap(
                declaration=_capability_declaration("bb.cap"),
                evidence=evidence,
                proposal_id=proposal.proposal_id,
                observed_pre_governed_generation=1,
            )


class TestBootstrapGovernPipeline(unittest.TestCase):
    """BB4-BB6 — boundary + aggregate orchestration."""

    def setUp(self) -> None:
        self.rrm, self.svc = _fresh()

    def test_bb4_end_to_end_pipeline(self) -> None:
        self.rrm.register_capability(CapabilityResource(
            capability_id="bb.cap",
            name="bb.cap",
        ))
        declaration = _capability_declaration("bb.cap")
        gen_before = self.rrm.get_capability("bb.cap").generation

        report = self.svc.bootstrap_govern(
            [declaration],
            decided_by="bootstrap",
            reasoning="bb4 audit",
        )

        self.assertTrue(report.success, [(e.resource_id, e.reason) for e in report.entries])
        self.assertTrue(report.verified)
        self.assertEqual(report.governed_count, 1)
        entry = report.entries[0]
        self.assertTrue(entry.success)
        self.assertTrue(entry.governed_registration_id)
        self.assertEqual(entry.resulting_generation, gen_before + 1)

        after = self.rrm.get_capability("bb.cap")
        self.assertEqual(after.generation, gen_before + 1)
        self.assertTrue(after.governed_registration_id)

        # The proposal/decision chain was consumed.
        self.assertTrue(self.svc.proposals.list_proposals(ResourcePromotionStatus.CONSUMED))
        proposal = self.svc.proposals.list_proposals(ResourcePromotionStatus.CONSUMED)[0]
        decision_id = None
        for decision in self.svc.decisions._decisions.values():  # noqa: SLF001
            if decision.proposal_id == proposal.proposal_id:
                decision_id = decision.decision_id
        self.assertIsNotNone(decision_id)
        self.assertTrue(self.svc.decisions.is_consumed(decision_id))

    def test_bb5_aggregate_report_fails_closed_on_missing_resource(self) -> None:
        self.rrm.register_capability(CapabilityResource(
            capability_id="bb.ok",
            name="bb.ok",
        ))
        declarations = [
            _capability_declaration("bb.ok"),
            _capability_declaration("bb.missing"),
        ]

        report = self.svc.bootstrap_govern(declarations)

        self.assertFalse(report.success)
        self.assertFalse(report.verified)
        reasons = {e.resource_id: e.reason for e in report.entries}
        self.assertEqual(reasons["bb.missing"], "resource_not_found")
        ok_entry = next(e for e in report.entries if e.resource_id == "bb.ok")
        self.assertTrue(ok_entry.success)
        self.assertTrue(ok_entry.governed_registration_id)

    def test_bb6_govern_existing_on_governed_resource_is_flat_failure(self) -> None:
        self.rrm.register_capability(CapabilityResource(
            capability_id="bb.cap",
            name="bb.cap",
        ))
        declaration = _capability_declaration("bb.cap")

        evidence = _observed_evidence("boot-bb6", "bb.cap")
        self.svc._discovery.registry.add(evidence)  # noqa: SLF001
        proposal = self.svc.create_proposal(evidence.discovery_id)
        decision = self.svc.decisions.decide_bootstrap(
            declaration=declaration,
            evidence=evidence,
            proposal_id=proposal.proposal_id,
            observed_pre_governed_generation=1,
        )
        first = self.svc.registration.govern_existing(
            proposal.proposal_id,
            decision.decision_id,
            fresh=True,
        )
        self.assertTrue(first.success)
        self.assertEqual(first.registration_type, "capability/first_governance")
        self.assertEqual(first.observed_generation, 2)

        # Second pipeline against the same (now governed) resource. Uses a
        # distinct discovery source so the dedup key does not collide with the
        # first evidence.
        evidence2 = _observed_evidence("boot-bb6b", "bb.cap")
        evidence2 = ResourceDiscoveryEvidence(
            discovery_id=evidence2.discovery_id,
            resource_kind=evidence2.resource_kind,
            resource_id=evidence2.resource_id,
            display_name=evidence2.display_name,
            source="bootstrap.second",
            status=evidence2.status,
            confidence=evidence2.confidence,
        )
        self.svc._discovery.registry.add(evidence2)  # noqa: SLF001
        proposal2 = self.svc.create_proposal(evidence2.discovery_id)
        decision2 = self.svc.decisions.decide_bootstrap(
            declaration=declaration,
            evidence=evidence2,
            proposal_id=proposal2.proposal_id,
            observed_pre_governed_generation=99,
        )
        second = self.svc.registration.govern_existing(
            proposal2.proposal_id,
            decision2.decision_id,
            fresh=True,
        )

        self.assertFalse(second.success)
        self.assertIn(second.reason, {"already_governed", "pre_governed_generation_mismatch"})
        self.assertEqual(self.rrm.get_capability("bb.cap").generation, 2)

    def test_bb4_govern_existing_outcome_is_typed_and_detached(self) -> None:
        self.rrm.register_capability(CapabilityResource(
            capability_id="bb.cap",
            name="bb.cap",
        ))
        evidence = _observed_evidence("boot-bb4b", "bb.cap")
        self.svc._discovery.registry.add(evidence)  # noqa: SLF001
        proposal = self.svc.create_proposal(evidence.discovery_id)
        decision = self.svc.decisions.decide_bootstrap(
            declaration=_capability_declaration("bb.cap"),
            evidence=evidence,
            proposal_id=proposal.proposal_id,
            observed_pre_governed_generation=1,
        )
        result = self.svc.registration.govern_existing(
            proposal.proposal_id,
            decision.decision_id,
            fresh=True,
        )
        self.assertTrue(result.success)
        self.assertTrue(result.governed_registration_id)
        self.assertEqual(result.observed_generation, 2)


@pytest.mark.usefixtures("m32a_isolated_store_root")
class TestProductionChainAndBuildRegression(unittest.TestCase):
    """BB7-BB8 — canonical production chain + productive-set build gate."""

    @pytest.fixture(autouse=True)
    def _setup_paths(self, m32a_isolated_store_root: Path) -> None:
        self._authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
        self._continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"

    def test_bb7_runtime_added_core_app_is_governed_and_resolvable(self) -> None:
        components = KernelBuilder().build(authority_file=self._authority_file, continuity_file=self._continuity_file)

    def test_bb7_runtime_added_core_app_is_governed_and_resolvable(self) -> None:
        components = KernelBuilder().build(authority_file=self._authority_file, continuity_file=self._continuity_file)
        app = _SwitchableApp()

        components.capability_router.register(app)
        components.capability_registry.register_core_app(app)
        from intent_kernel.rrm.projection import RuntimeResourceProjection

        RuntimeResourceProjection(components.resource_manager).project_core_app(app)

        registrations = components.capability_registry.discover(
            "resource.switchable",
            executor_kind=ExecutorKind.CORE_APP,
        )
        declaration = BootstrapResourceDeclaration.from_registration(registrations[0])
        report = components.resource_promotion_service.bootstrap_govern([declaration])
        self.assertTrue(report.success, [(e.resource_id, e.reason) for e in report.entries])

        resource = components.resource_manager.get_capability("resource.switchable")
        self.assertTrue(resource.governed_registration_id)
        self.assertEqual(resource.generation, 2)

        decision = _run(
            components.capability_execution_service.resource_authority.resolve(
                "resource.switchable"
            )
        )
        self.assertTrue(decision.available)
        self.assertTrue(decision.rrm_eligible)
        self.assertEqual(decision.selected_binding, "core_app:switchable")
        self.assertEqual(len(decision.execution_preconditions), 1)
        precondition = decision.execution_preconditions[0]
        self.assertEqual(precondition.kind.value, "existing_resource")
        self.assertTrue(precondition.governed_registration_id)
        self.assertEqual(precondition.expected_generation, 2)

    def test_bb8_productive_set_gate_and_resolution(self) -> None:
        components = KernelBuilder().build(authority_file=self._authority_file, continuity_file=self._continuity_file)
        rrm = components.resource_manager

        governed_caps = {
            c.capability_id
            for c in rrm.list_capabilities()
            if c.governed_registration_id
        }
        governed_agents = {
            a.agent_id
            for a in rrm.list_agents()
            if a.governed_registration_id
        }
        governed_providers = {
            p.provider_id
            for p in rrm.list_providers()
            if p.governed_registration_id
        }
        ungoverned_caps = {
            c.capability_id
            for c in rrm.list_capabilities()
            if not c.governed_registration_id
        }

        self.assertEqual(
            governed_caps,
            {
                "finance.intent",
                "knowledge.intent",
                "knowledge.project.create",
                "knowledge.project.list",
                "knowledge.search",
                "engineering.intent",
                "engineering.project.create",
                "engineering.project.list",
            },
        )
        self.assertEqual(governed_agents, {"finance", "knowledge", "engineering"})
        self.assertEqual(governed_providers, {"mock"})
        self.assertEqual(
            ungoverned_caps,
            {"memory.retrieve", "memory.write", "productivity.spreadsheet"},
        )

        for cap_id in governed_caps:
            self.assertEqual(rrm.get_capability(cap_id).generation, 2)

        decision = _run(
            components.capability_execution_service.resource_authority.resolve(
                "finance.intent"
            )
        )
        self.assertTrue(decision.available)
        self.assertEqual(decision.reason, "eligible_binding")
        self.assertEqual(decision.selected_binding, "core_app:atlas")
        precondition = decision.execution_preconditions[0]
        self.assertEqual(precondition.kind.value, "existing_resource")
        self.assertEqual(precondition.resource_id, "finance.intent")
        self.assertEqual(precondition.expected_generation, 2)

        mock = rrm.get_provider("mock")
        self.assertTrue(mock.governed_registration_id)
        self.assertEqual(mock.is_configured, False)
        provider_decision = _run(
            components.capability_execution_service.resource_authority.resolve(
                "provider.text_completion"
            )
        )
        self.assertFalse(provider_decision.available)
        self.assertEqual(provider_decision.reason, "rrm_rejected_bindings")


class _SwitchableApp:
    app_id = "switchable"
    capabilities = (Capability(name="resource.switchable"),)

    def __init__(self) -> None:
        self.healthy = True
        self.calls = 0

    async def health(self) -> bool:
        return self.healthy

    async def execute(self, request) -> object:
        self.calls += 1
        from intent_kernel.contracts import CapabilityResult

        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="executed",
        )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)