"""M31.2B-2B RA-09 — External Evidence Tombstone Compatibility (EXTERNAL_EVIDENCE).

Canonical post-retirement external evidence semantics:

    RETIRED GOVERNED PROVIDER -> resource_tombstoned
    NEVER merely            -> resource_not_found  (when a canonical tombstone exists)

RRMEvidenceAdapter must NOT directly inspect RRM private tombstone storage
(no ``._tombstones`` / ``"_tombstones"`` / ``getattr(self._rrm, "_tombstones")``).
It must call the typed read-only kind-aware RRM query ``has_tombstoned_resource``.

Canonical TS1 source remains the structured ResourceTombstone dict
(no Set / derived index / parallel mapping reintroduced).

Map (per RA-09 requirement):
  61 = retired Provider external evidence returns resource_tombstoned
  62 = never-registered Provider returns resource_not_found
  63 = Agent tombstone + same logical ID does NOT make Provider evidence tombstoned
  64 = RRMEvidenceAdapter does not directly inspect _tombstones
  65 = typed query returns bool and exposes no mutable canonical object
  66 = M30.2 post-retirement evidence remains invalid
  67 = M30.3 completion/freshness semantics unchanged
  68 = M28.2.1 mutable-evidence resume semantics unchanged
  69 = tombstone provenance classification remains resource_tombstoned
  70 = typed query grants no retirement / re-registration authority
"""

from __future__ import annotations

import inspect
import unittest

from intent_kernel.rrm.models import (
    AgentResource,
    ConditionalResourceStatusRequest,
    ProviderResource,
    ResourceStatus,
    ResourceType,
)
from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.runtime.external_evidence import (
    ExternalEvidenceRequirement,
    RRMEvidenceAdapter,
)


def _req(resource_id="p1") -> ExternalEvidenceRequirement:
    return ExternalEvidenceRequirement(
        evidence_type="PROVIDER_RESOURCE_STATE",
        resource_id=resource_id,
        expected_state={"status": "active", "is_eligible": True},
    )


def _fresh() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


def _governed_provider(rrm, rid="p1", grid="R1"):
    rrm.register_provider(
        ProviderResource(provider_id=rid, name="P", governed_registration_id=grid)
    )
    return rid, grid


def _retire(rrm, rid, grid):
    ret = CanonicalResourceRetirementAuthority(rrm)
    reqq = ret.request_retirement(rid, grid)
    dec = ret.decide_retirement(reqq.request_id, approved=True)
    res = ret.apply_retirement(dec.decision_id)
    assert res.success
    return rrm


class RetiredProviderEvidenceTest(unittest.TestCase):
    """Invariant 61: retired governed Provider -> resource_tombstoned."""

    def test_61_retired_provider_evidence_is_tombstoned(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "resource_tombstoned")


class NeverRegisteredProviderTest(unittest.TestCase):
    """Invariant 62: never-registered Provider -> resource_not_found."""

    def test_62_never_registered_provider_is_not_found(self):
        rrm = _fresh()
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="nope"))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "resource_not_found")


class CrossFamilyProviderEvidenceTest(unittest.TestCase):
    """Invariant 63: Agent tombstone must NOT cause Provider tombstoned."""

    def test_63_agent_tombstone_does_not_tombstone_provider(self):
        rrm = _fresh()
        shared = "pp-shared"
        rrm.register_agent(
            AgentResource(agent_id=shared, name="A", governed_registration_id="R-A")
        )
        _retire(rrm, shared, "R-A")
        self.assertTrue(rrm.has_tombstoned_resource(ResourceType.AGENT, shared))
        self.assertFalse(rrm.has_tombstoned_resource(ResourceType.PROVIDER, shared))
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=shared))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "resource_not_found")


class PrivateAccessProhibitedTest(unittest.TestCase):
    """Invariant 64: RRMEvidenceAdapter must not directly inspect _tombstones."""

    def test_64_adapter_source_has_no_private_tombstone_access(self):
        import intent_kernel.runtime.external_evidence as module

        src = inspect.getsource(module)
        self.assertNotIn("_tombstones", src)
        self.assertNotIn('"_tombstones"', src)
        self.assertNotIn("getattr(self._rrm, \"_tombstones\"", src)

    def test_64b_adapter_uses_typed_query_surface(self):
        src = inspect.getsource(RRMEvidenceAdapter.observe)
        self.assertIn("has_tombstoned_resource", src)


class TypedQuerySurfaceTest(unittest.TestCase):
    """Invariant 65: typed query returns bool, no mutable canonical escape."""

    def test_65_query_returns_bool(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        result = rrm.has_tombstoned_resource(ResourceType.PROVIDER, rid)
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_65b_query_no_mutable_canonical_object_escape(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        public = {
            name
            for name in dir(RegistryResourceManager)
            if not name.startswith("_")
        }
        self.assertNotIn("tombstones", public)
        self.assertNotIn("get_tombstone", public)
        self.assertNotIn("list_tombstones", public)
        self.assertTrue(rrm.has_tombstoned_resource(ResourceType.PROVIDER, rid))

    def test_65c_query_kind_aware_and_cross_family(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        self.assertTrue(rrm.has_tombstoned_resource(ResourceType.PROVIDER, rid))
        self.assertFalse(rrm.has_tombstoned_resource(ResourceType.AGENT, rid))


class M30Point2EvidenceInvalidationTest(unittest.TestCase):
    """Invariant 66: M30.2 post-retirement evidence remains invalid."""

    def test_66_post_retirement_evidence_invalid(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        self.assertFalse(o.matched)
        self.assertEqual(o.reason_code, "resource_tombstoned")
        self.assertEqual(o.resource_generation, None)


class M30Point3FreshnessUnchangedTest(unittest.TestCase):
    """Invariant 67: M30.3 completion/freshness semantics unchanged."""

    def test_67_generation_still_advances_on_material_mutation(self):
        rrm = _fresh()
        rrm.register_provider(
            ProviderResource(provider_id="p1", name="P", governed_registration_id="R1")
        )
        before = rrm.get_provider("p1").generation
        rrm.conditional_update_status(
            ConditionalResourceStatusRequest(
                resource_type=ResourceType.PROVIDER,
                resource_id="p1",
                expected_governed_registration_id="R1",
                expected_generation=before,
                desired_status=ResourceStatus.DEGRADED,
            )
        )
        after = rrm.get_provider("p1").generation
        self.assertEqual(after, before + 1)

    def test_67b_retired_provider_still_fail_closed(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        self.assertFalse(o.matched)


class M28Point2Point1ResumeUnchangedTest(unittest.TestCase):
    """Invariant 68: M28.2.1 mutable-evidence resume semantics unchanged."""

    def test_68_resume_distinguishes_tombstoned_from_absent(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        retired = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        absent = RRMEvidenceAdapter(rrm).observe(_req(resource_id="never"))
        self.assertEqual(retired.reason_code, "resource_tombstoned")
        self.assertEqual(absent.reason_code, "resource_not_found")
        self.assertNotEqual(retired.reason_code, absent.reason_code)


class TombstoneProvenanceClassificationTest(unittest.TestCase):
    """Invariant 69: provenance classification remains resource_tombstoned."""

    def test_69_canonical_retired_identity_classified_tombstoned(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        self.assertEqual(o.reason_code, "resource_tombstoned")

    def test_69b_no_parallel_legacy_set_authority(self):
        rrm = _fresh()
        rrm_attrs = vars(rrm).keys()
        self.assertNotIn("_tombstones_set", rrm_attrs)
        self.assertNotIn("_tombstone_index", rrm_attrs)


class NoAuthorityGrantTest(unittest.TestCase):
    """Invariant 70: typed query grants no retirement / re-registration authority."""

    def test_70_query_does_not_mutate_or_authorize(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        before = dict(rrm._tombstones)
        rrm.has_tombstoned_resource(ResourceType.PROVIDER, rid)
        after = dict(rrm._tombstones)
        self.assertEqual(before, after)
        self.assertIsNone(rrm.get_provider(rid))


class DirectSemanticReproductionTest(unittest.TestCase):
    """RA-09 section 19: explicit CASE A/B/C reproduction."""

    def test_case_a_retired_provider_tombstoned(self):
        rrm = _fresh()
        rid, grid = _governed_provider(rrm)
        _retire(rrm, rid, grid)
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=rid))
        self.assertEqual(o.reason_code, "resource_tombstoned")

    def test_case_b_never_registered_not_found(self):
        rrm = _fresh()
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id="never-provider"))
        self.assertEqual(o.reason_code, "resource_not_found")

    def test_case_c_cross_family_not_found(self):
        rrm = _fresh()
        shared = "shared-id"
        rrm.register_agent(
            AgentResource(agent_id=shared, name="A", governed_registration_id="R-A")
        )
        _retire(rrm, shared, "R-A")
        o = RRMEvidenceAdapter(rrm).observe(_req(resource_id=shared))
        self.assertEqual(o.reason_code, "resource_not_found")


if __name__ == "__main__":
    unittest.main()
