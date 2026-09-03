"""M31.2B-2A — Immutable Tombstone Identity Contract (MODEL_D1).

Originally a contract-only movement. ``ResourceTombstone`` defines the
canonical immutable structured tombstone identity. M31.2B-2B activated it as
the single authoritative runtime tombstone source:

- ``RegistryResourceManager._tombstones`` is now the canonical
  ``Dict[Tuple[ResourceType, str, str], ResourceTombstone]`` store (M31.2B-2B
  replaced the legacy ``Set[str]``).
- M31.2B-1 tombstone rejection behavior is unchanged for same-family IDs.
- No API installs a caller-supplied canonical tombstone.
- ``ResourceTombstone`` confers no authority (no retirement, no
  re-registration, no promotion authorization).

Canonical lineage primary identity:
    (resource_kind, resource_id, governed_registration_id)

``observed_generation`` is freshness/version evidence bound to that lineage;
it is NOT part of the lineage primary key.

Allowed claim ONLY:
  "Canonical immutable tombstone identity contract is the single authoritative
  structured tombstone source (TS1)."
"""

from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError, fields

from intent_kernel.rrm.generation import (
    GENERATION_INITIAL,
    LEGACY_UNVERSIONED,
    is_valid_generation,
)
from intent_kernel.rrm.models import (
    ConditionalCreateOutcome,
    ConditionalRegistrationRequest,
    ProviderResource,
    ResourceTombstone,
    ResourceType,
)
from intent_kernel.rrm.service import RegistryResourceManager


def _valid_tombstone(
    resource_kind: ResourceType = ResourceType.PROVIDER,
    resource_id: str = "p1",
    governed_registration_id: str = "R1",
    observed_generation: int = GENERATION_INITIAL,
) -> ResourceTombstone:
    return ResourceTombstone(
        resource_kind=resource_kind,
        resource_id=resource_id,
        governed_registration_id=governed_registration_id,
        observed_generation=observed_generation,
    )


ALL_SIX_RESOURCE_TYPES = [
    ResourceType.PROVIDER,
    ResourceType.ACCOUNT,
    ResourceType.EXECUTION_ENVIRONMENT,
    ResourceType.CAPABILITY,
    ResourceType.AGENT,
    ResourceType.PROJECT,
]


class ResourceTombstoneIdentityContractTest(unittest.TestCase):
    """Invariants 01-11: the immutable identity contract itself."""

    def test_01_tombstone_is_immutable(self):
        t = _valid_tombstone()
        with self.assertRaises(FrozenInstanceError):
            t.resource_id = "other"

    def test_02_resource_kind_uses_canonical_resource_type(self):
        t = _valid_tombstone()
        self.assertIsInstance(t.resource_kind, ResourceType)

    def test_03_all_six_resource_types_are_accepted(self):
        for kind in ALL_SIX_RESOURCE_TYPES:
            t = _valid_tombstone(resource_kind=kind, resource_id="res")
            self.assertIs(t.resource_kind, kind)

    def test_04_invalid_resource_kind_fails_closed(self):
        for bad in (None, "provider", 3, object()):
            with self.assertRaises(ValueError):
                ResourceTombstone(
                    resource_kind=bad,
                    resource_id="p1",
                    governed_registration_id="R1",
                    observed_generation=1,
                )

    def test_05_empty_resource_id_fails_closed(self):
        for bad in ("", "   ", None, 0):
            with self.assertRaises(ValueError):
                ResourceTombstone(
                    resource_kind=ResourceType.PROVIDER,
                    resource_id=bad,
                    governed_registration_id="R1",
                    observed_generation=1,
                )

    def test_06_empty_governed_registration_id_fails_closed(self):
        for bad in ("", "   ", None, 0):
            with self.assertRaises(ValueError):
                ResourceTombstone(
                    resource_kind=ResourceType.PROVIDER,
                    resource_id="p1",
                    governed_registration_id=bad,
                    observed_generation=1,
                )

    def test_07_missing_or_invalid_observed_generation_fails_closed(self):
        for bad in (None, LEGACY_UNVERSIONED, -1, True, 1.5, "1"):
            with self.assertRaises(ValueError):
                ResourceTombstone(
                    resource_kind=ResourceType.PROVIDER,
                    resource_id="p1",
                    governed_registration_id="R1",
                    observed_generation=bad,
                )

    def test_08_legacy_unversioned_generation_not_silently_promoted_to_one(self):
        # GENERATION_INITIAL is 1; LEGACY_UNVERSIONED is 0. Passing 0 (or any
        # unversioned value) must fail closed and must NOT silently become
        # generation 1. is_valid_generation() guards this.
        self.assertEqual(LEGACY_UNVERSIONED, 0)
        self.assertEqual(GENERATION_INITIAL, 1)
        self.assertFalse(is_valid_generation(LEGACY_UNVERSIONED))
        with self.assertRaises(ValueError):
            ResourceTombstone(
                resource_kind=ResourceType.PROVIDER,
                resource_id="p1",
                governed_registration_id="R1",
                observed_generation=LEGACY_UNVERSIONED,
            )

    def test_09_lineage_identity_distinguishes_different_resource_type(self):
        # Same resource_id + different ResourceType => different lineage.
        a = _valid_tombstone(resource_kind=ResourceType.PROVIDER, resource_id="x")
        b = _valid_tombstone(resource_kind=ResourceType.ACCOUNT, resource_id="x")
        self.assertNotEqual(a.lineage_identity, b.lineage_identity)

    def test_10_lineage_identity_distinguishes_different_registration_lineage(self):
        # Same kind + same resource_id + different governed_registration_id
        # => different lineage.
        a = _valid_tombstone(resource_id="x", governed_registration_id="R1")
        b = _valid_tombstone(resource_id="x", governed_registration_id="R2")
        self.assertNotEqual(a.lineage_identity, b.lineage_identity)

    def test_11_observed_generation_does_not_redefine_registration_lineage(self):
        # Different observed_generation => same lineage primary identity.
        # TOMBSTONE_GENERATION_PART_OF_PRIMARY_KEY=NO.
        a = _valid_tombstone(resource_id="x", governed_registration_id="R1", observed_generation=1)
        b = _valid_tombstone(resource_id="x", governed_registration_id="R1", observed_generation=7)
        self.assertEqual(a.lineage_identity, b.lineage_identity)


class ResourceTombstoneDataIsolationTest(unittest.TestCase):
    """Invariants 12-14: data-only, no escaping mutability, no caller mutation."""

    def test_12_no_mutable_nested_state_escaping_immutability(self):
        t = _valid_tombstone()
        for f in fields(t):
            value = getattr(t, f.name)
            if isinstance(value, ResourceType):
                self.assertFalse(hasattr(value, "__setitem__"))
            else:
                self.assertIsInstance(value, (str, int))
        # slots=True: no instance __dict__ exists to hold escaping state.
        self.assertFalse(hasattr(t, "__dict__"))
        # str Enum members are immutable singletons.
        self.assertFalse(hasattr(ResourceType.PROVIDER, "__setitem__"))

    def test_13_no_executable_or_callback_object_accepted_as_identity_data(self):
        # Every identity field is a plain str/int/Enum. A callable is not a
        # valid identity string and fails closed at construction.
        def _callback(*args, **kwargs):
            return "p1"

        with self.assertRaises(ValueError):
            ResourceTombstone(
                resource_kind=ResourceType.PROVIDER,
                resource_id=_callback,
                governed_registration_id="R1",
                observed_generation=1,
            )

    def test_14_constructing_tombstone_does_not_mutate_caller_inputs(self):
        kind = ResourceType.PROVIDER
        rid = "p1"
        grid = "R1"
        gen = 1
        t = ResourceTombstone(
            resource_kind=kind,
            resource_id=rid,
            governed_registration_id=grid,
            observed_generation=gen,
        )
        self.assertEqual(
            (t.resource_kind, t.resource_id, t.governed_registration_id, t.observed_generation),
            (kind, rid, grid, gen),
        )
        # Caller variables are untouched.
        self.assertEqual((kind, rid, grid, gen), (ResourceType.PROVIDER, "p1", "R1", 1))


class ResourceTombstoneRuntimeNonActivationTest(unittest.TestCase):
    """Invariants 15-20: single TS1 store, M31.2B-1 preserved, no authority."""

    def test_15_single_authoritative_structured_tombstone_store(self):
        # M31.2B-2B activates the canonical structured tombstone store, replacing
        # the legacy Set[str] mechanism with ONE authoritative container.
        rrm = RegistryResourceManager(populate_defaults=False)
        self.assertIsInstance(rrm._tombstones, dict)
        # The RRM holds no additional structured container / history / index.
        rrm_attrs = vars(rrm).keys()
        for forbidden in ("_tombstone_objects", "_tombstone_history", "_tombstone_index", "_tombstones_set"):
            self.assertNotIn(forbidden, rrm_attrs)

    def test_16_m31_2b1_tombstone_rejection_remains_unchanged(self):
        rrm = RegistryResourceManager(populate_defaults=False)
        rrm.register_provider(
            ProviderResource(
                provider_id="p1", name="p1", governed_registration_id="R1", generation=1
            )
        )
        rrm._record_tombstone(ResourceType.PROVIDER, "p1", "R1", 1)
        res = rrm.conditional_create_resource(
            ConditionalRegistrationRequest(
                resource_type=ResourceType.PROVIDER,
                resource_data=ProviderResource(provider_id="p1", name="p2"),
                expected_absence=True,
            )
        )
        self.assertIs(res.outcome, ConditionalCreateOutcome.REJECTED_TOMBSTONED)

    def test_17_no_resource_tombstone_api_confers_reregistration_authority(self):
        authority_like_members = [
            name
            for name, _ in inspect.getmembers(ResourceTombstone)
            if any(part in name.lower() for part in ("authority", "authorize", "approve", "grant"))
        ]
        self.assertEqual(authority_like_members, [])

    def test_18_no_caller_supplied_canonical_tombstone_installation_api_exists(self):
        rrm_public = {n for n in dir(RegistryResourceManager) if not n.startswith("_")}
        for forbidden in ("install_tombstone", "register_tombstone", "set_tombstone"):
            self.assertNotIn(forbidden, rrm_public)
        # No generic MUTATION interface accepting/installing tombstone objects.
        # (B2C permits only read-only observation surfaces: has_tombstoned_resource
        # and the exact-lineage get_resource_tombstone query — both are non-mutating.)
        for method_like in rrm_public:
            if method_like in ("get_resource_tombstone", "has_tombstoned_resource"):
                self.assertTrue(callable(getattr(RegistryResourceManager, method_like)))
                continue
            self.assertFalse(method_like.endswith("tombstone"))
        # the read-only exact-lineage query must not expose a mutation surface
        self.assertTrue(
            not any(
                m.endswith(("install_tombstone", "write_tombstone", "set_tombstone",
                            "add_tombstone", "mutate_tombstone", "overwrite_tombstone"))
                for m in rrm_public
            )
        )

    def test_19_authority_ownership_remains_unchanged(self):
        # ResourceTombstone exposes NO callable helper surface; all authority
        # decisions remain in the existing authority classes.
        method_names = [
            name
            for name in dir(ResourceTombstone)
            if not name.startswith("_") and callable(getattr(ResourceTombstone, name))
        ]
        self.assertEqual(method_names, [])

    def test_20_project_support_in_contract_does_not_modify_retirement_authority(self):
        # ResourceTombstone accepts ResourceType.PROJECT (contract representability
        # only). This MUST NOT change CanonicalResourceRetirementAuthority.
        from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority

        t = _valid_tombstone(resource_kind=ResourceType.PROJECT, resource_id="proj1")
        self.assertIs(t.resource_kind, ResourceType.PROJECT)
        # The retirement authority class is a distinct, unchanged authority; the
        # contract itself carries no retirement request/decision surface.
        self.assertIsNot(CanonicalResourceRetirementAuthority, ResourceTombstone)
        self.assertFalse(hasattr(ResourceTombstone, "request_retirement"))
        self.assertFalse(hasattr(ResourceTombstone, "decide_retirement"))
        self.assertFalse(hasattr(ResourceTombstone, "apply_retirement"))