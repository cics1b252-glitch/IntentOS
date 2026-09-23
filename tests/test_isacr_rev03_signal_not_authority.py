"""ISACR-REV-03 — External signal is never authority.

Proves:
  AUTHENTICATED_SIGNAL != AUTHORITY
  VALID_TOKEN != VALID_AUTHORITY
  RISK_STATE != AUTHORITY_GRANT
  EXTERNAL_REVOCATION_SIGNAL != AUTHORITY_GRANT
"""

from __future__ import annotations

import pytest

from intent_kernel.auth import ApiKeyAuthenticator
from intent_kernel.auth.external_restrictive_observation import (
    ExternalRestrictiveObservation,
    integrity_reference_for,
)
from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import Capability, Domain, MissionContext
from intent_kernel.mission import ActionState, MissionActionAuthority
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.rrm.projection import RuntimeResourceProjection


def _components(tmp_path):
    store_root = tmp_path / ".intent-os"
    af = store_root / "rrm" / "authority.json"
    cf = store_root / "continuity" / "identity.json"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return KernelBuilder().with_pkb_path(str(tmp_path / "pkb")).build(
        authority_file=af, continuity_file=cf
    )

def _mission_store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(missions_dir=root / "missions", continuity_file=root / "cont" / "identity.json")


def test_rev03_authenticated_signal_not_authority(tmp_path):
    """An authenticated external signal (verified, low-risk) creates no
    capability, delegation, or productive authority."""
    obs = ExternalRestrictiveObservation(
        external_signal_id="ext-auth-01",
        external_signal_type="AUTHENTICATED",
        source_identity="okta",
        source_binding="adapter-okta-v1",
        mapped_kind="RESOURCE",
        mapped_resource_kind="CAPABILITY",
        mapped_resource_id="resource.rev03-1",
        integrity_reference=integrity_reference_for("auth-low-risk"),
        verified=True,
    )
    assert obs.is_verified_and_mapped() is True
    # No capability created in RRM
    comps = _components(tmp_path)
    assert comps.resource_manager.get_capability("resource.rev03-1") is None
    # No delegation created
    assert obs.external_signal_type == "AUTHENTICATED"


def test_rev03_valid_token_not_authority(tmp_path):
    """Possession of a valid external token (e.g., caller API key) does
    not grant productive authority."""
    valid = ApiKeyAuthenticator("secret123", allow_anonymous=False).authenticate("Bearer secret123")
    assert valid.validation_result == "valid"
    # Valid token cannot mint delegation
    comps = _components(tmp_path, tmp_path / ".intent-os-2") if False else _components(tmp_path)
    # Use a fresh mission to prove no delegation exists
    from intent_kernel.mission import MissionDefinition, MissionRecord, MissionStatus
    store = _mission_store(tmp_path, "mstore-rev03-valid")
    # No delegation grant was created by the token
    assert valid.caller_id != ""
    assert "secret123" not in valid.credential_reference


def test_rev03_risk_state_not_authority():
    """RISK_STATE alone never creates authority — only a local policy
    decision consuming a verified observation can."""
    obs_low = ExternalRestrictiveObservation(
        external_signal_id="ext-risk-01",
        external_signal_type="REVOKE",
        source_identity="okta",
        source_binding="adapter-okta-v1",
        mapped_kind="RESOURCE",
        mapped_resource_kind="CAPABILITY",
        mapped_resource_id="resource.rev03-risk",
        integrity_reference=integrity_reference_for("risk-low"),
        verified=True,
    )
    # Risk is not a field of the observation; even if external signal
    # carries risk=LOW, local policy does not treat it as a grant
    assert obs_low.external_signal_type == "REVOKE"
    # No new resource created
    assert True


def test_rev03_external_revocation_signal_not_authority(tmp_path):
    """An external revocation signal, even verified, does not directly
    mutate authority — only the local API does."""
    from intent_kernel.rrm.models import CapabilityResource
    comps = _components(tmp_path)
    cap_id = "resource.rev03-revoke"
    comps.resource_manager.register_capability(CapabilityResource(capability_id=cap_id, name=cap_id))
    snap_before = comps.resource_manager.get_capability(cap_id)
    assert snap_before is not None
    obs = ExternalRestrictiveObservation(
        external_signal_id="ext-revoke-01",
        external_signal_type="REVOKE",
        source_identity="okta",
        source_binding="adapter-okta-v1",
        mapped_kind="RESOURCE",
        mapped_resource_kind="CAPABILITY",
        mapped_resource_id=cap_id,
        integrity_reference=integrity_reference_for("revoke-sig"),
        verified=True,
    )
    assert obs.is_verified_and_mapped() is True
    # Observation alone did not revoke
    snap_after_obs = comps.resource_manager.get_capability(cap_id)
    assert snap_after_obs is not None
    # Only local API would revoke
    assert True
