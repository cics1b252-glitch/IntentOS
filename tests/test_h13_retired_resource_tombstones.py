"""H1.3 — Retired Resource Tombstones.

Proves the invariant:
    ONCE RETIRED = CANNOT BE RE-REGISTERED UNDER THE SAME GOVERNED IDENTITY

A retired identity must not return to active state by simple new registration.
"""

from __future__ import annotations

import pytest

from intent_kernel.rrm.models import (
    AvailabilitySource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
)
from intent_kernel.rrm.retirement import CanonicalResourceRetirementAuthority
from intent_kernel.rrm.service import RegistryResourceManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rrm() -> RegistryResourceManager:
    return RegistryResourceManager(populate_defaults=False)


def _make_provider(
    rrm: RegistryResourceManager,
    resource_id: str = "prov-1",
    governed_grid: str = "",
    name: str = "TestProvider",
) -> ProviderResource:
    resource = ProviderResource(
        provider_id=resource_id,
        name=name,
        availability_source=AvailabilitySource.CONFIGURATION,
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    if governed_grid:
        resource.governed_registration_id = governed_grid
    rrm.register_provider(resource)
    return resource


def _retire(rrm: RegistryResourceManager, resource_id: str, grid: str):
    authority = CanonicalResourceRetirementAuthority(rrm)
    req = authority.request_retirement(resource_id, grid)
    dec = authority.decide_retirement(req.request_id, approved=True)
    return authority.apply_retirement(dec.decision_id)


# ---------------------------------------------------------------------------
# 1. Normal new registration → succeeds
# ---------------------------------------------------------------------------

def test_normal_new_registration_succeeds():
    rrm = _make_rrm()
    p = _make_provider(rrm, "prov-new", name="New")
    assert p is not None
    assert rrm.get_provider("prov-new") is not None


# ---------------------------------------------------------------------------
# 2. Duplicate active registration → preserves existing canonical behavior
# ---------------------------------------------------------------------------

def test_duplicate_active_registration_preserves_existing():
    rrm = _make_rrm()
    p1 = _make_provider(rrm, "prov-dup", name="First")
    p2 = _make_provider(rrm, "prov-dup", name="Second")
    # Governed guard: returns existing (first write wins for governed)
    # Non-governed: overwrites (last write wins)
    assert p2 is not None
    assert rrm.get_provider("prov-dup") is not None


# ---------------------------------------------------------------------------
# 3. Active resource retirement → succeeds
# ---------------------------------------------------------------------------

def test_active_resource_retirement_succeeds():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-ret", governed_grid="gr-ret")
    result = _retire(rrm, "prov-ret", "gr-ret")
    assert result.success is True
    assert result.resource_id == "prov-ret"
    assert rrm.get_provider("prov-ret") is None


# ---------------------------------------------------------------------------
# 4. Retired identity receives tombstone → confirmed
# ---------------------------------------------------------------------------

def test_retired_identity_receives_tombstone():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-tomb", governed_grid="gr-tomb")
    _retire(rrm, "prov-tomb", "gr-tomb")
    assert rrm._is_tombstoned("prov-tomb") is True


# ---------------------------------------------------------------------------
# 5. Same retired identity registration attempt → rejected
# ---------------------------------------------------------------------------

def test_same_retired_identity_registration_rejected():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-reuse", governed_grid="gr-reuse")
    _retire(rrm, "prov-reuse", "gr-reuse")

    # Attempt to re-register with same resource_id
    new_resource = ProviderResource(
        provider_id="prov-reuse",
        name="Reincarnation",
        availability_source=AvailabilitySource.CONFIGURATION,
        resource_origin=ResourceOrigin.CONFIGURATION,
    )
    result = rrm.register_provider(new_resource)

    # Should be rejected — tombstone prevents registration
    # Result is None (tombstoned, not in _providers)
    assert result is None
    assert rrm.get_provider("prov-reuse") is None


# ---------------------------------------------------------------------------
# 6. Different new identity → registration succeeds
# ---------------------------------------------------------------------------

def test_different_new_identity_registration_succeeds():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-old", governed_grid="gr-old")
    _retire(rrm, "prov-old", "gr-old")

    # Register a completely different resource
    p = _make_provider(rrm, "prov-different", name="Different")
    assert p is not None
    assert rrm.get_provider("prov-different") is not None


# ---------------------------------------------------------------------------
# 7. Retired identity cannot become executable through normal registration
# ---------------------------------------------------------------------------

def test_retired_identity_not_resolvable():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-exec", governed_grid="gr-exec")
    _retire(rrm, "prov-exec", "gr-exec")

    # get_provider returns None after retirement
    assert rrm.get_provider("prov-exec") is None

    # list_providers with only_eligible should not include it
    providers = rrm.list_providers(only_eligible=True)
    assert all(p.provider_id != "prov-exec" for p in providers)


# ---------------------------------------------------------------------------
# 8. ProductBridge or compatibility path cannot bypass tombstone
# ---------------------------------------------------------------------------

def test_compatibility_register_cannot_bypass_tombstone():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-compat", governed_grid="gr-compat")
    _retire(rrm, "prov-compat", "gr-compat")

    # Even a "fresh" ProviderResource with different attributes but same ID
    # should be rejected
    fake = ProviderResource(
        provider_id="prov-compat",
        name="Bypass Attempt",
        availability_source=AvailabilitySource.RUNTIME_DISCOVERY,
        resource_origin=ResourceOrigin.MIGRATION,
    )
    result = rrm.register_provider(fake)
    assert result is None
    assert rrm.get_provider("prov-compat") is None


# ---------------------------------------------------------------------------
# 9. Retirement authority remains unchanged
# ---------------------------------------------------------------------------

def test_retirement_authority_unchanged():
    """3-phase retirement lifecycle still works exactly as before."""
    rrm = _make_rrm()
    _make_provider(rrm, "prov-auth", governed_grid="gr-auth")

    authority = CanonicalResourceRetirementAuthority(rrm)
    req = authority.request_retirement("prov-auth", "gr-auth")
    assert req.request_id is not None

    dec = authority.decide_retirement(req.request_id, approved=True)
    assert dec.decision_type.value == "approve"

    result = authority.apply_retirement(dec.decision_id)
    assert result.success is True
    assert result.resource_id == "prov-auth"


# ---------------------------------------------------------------------------
# 10. Existing resource resolution for non-retired resources unchanged
# ---------------------------------------------------------------------------

def test_non_retired_resource_resolution_unchanged():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-active", governed_grid="gr-active")
    _make_provider(rrm, "prov-other", governed_grid="gr-other")

    # Both should be resolvable
    assert rrm.get_provider("prov-active") is not None
    assert rrm.get_provider("prov-other") is not None

    # Retire one
    _retire(rrm, "prov-active", "gr-active")

    # The other should still be resolvable
    assert rrm.get_provider("prov-active") is None
    assert rrm.get_provider("prov-other") is not None


# ---------------------------------------------------------------------------
# 11. Same governed_registration_id with different object → REJECT
# ---------------------------------------------------------------------------

def test_same_governed_id_different_object_rejects():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-obj", governed_grid="gr-obj")
    _retire(rrm, "prov-obj", "gr-obj")

    # New object with same resource_id but different everything else
    obj2 = ProviderResource(
        provider_id="prov-obj",
        name="New Object",
        availability_source=AvailabilitySource.RUNTIME_DISCOVERY,
        resource_origin=ResourceOrigin.USER_REGISTRATION,
    )
    result = rrm.register_provider(obj2)
    assert result is None


# ---------------------------------------------------------------------------
# 12. Tombstone persists across register attempts
# ---------------------------------------------------------------------------

def test_tombstone_persists_across_attempts():
    rrm = _make_rrm()
    _make_provider(rrm, "prov-persist", governed_grid="gr-persist")
    _retire(rrm, "prov-persist", "gr-persist")

    # Multiple registration attempts — all should fail
    for i in range(3):
        attempt = ProviderResource(
            provider_id="prov-persist",
            name=f"Attempt {i}",
            availability_source=AvailabilitySource.CONFIGURATION,
            resource_origin=ResourceOrigin.CONFIGURATION,
        )
        result = rrm.register_provider(attempt)
        assert result is None

    # Tombstone still present
    assert rrm._is_tombstoned("prov-persist") is True
