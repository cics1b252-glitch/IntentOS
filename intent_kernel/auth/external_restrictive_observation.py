"""M33.2E-Movement1 — Canonical External Restrictive Observation.

Protocol-independent representation of the RESULT of external
verification. Adapter/trust-boundary verification (HMAC, JWKS,
mutual TLS, etc.) is OUTSIDE this model — this model carries only
the provenance of that verification (integrity_reference, source
binding) so local policy can independently decide to consume it.

The observation NEVER mutates authority by itself. Consumption is:

  verified observation
  → local mapping validation (does the mapped local subject exist?)
  → local policy/authority decision (is restrictive action allowed?)
  → existing canonical revocation API
    (conditional_retire_resource / revoke_delegation / revoke_permission)
  → existing durable local authority state

No raw external token/secret is stored. No new parallel revocation
store. No CAEP/SSF/OCSF/MCP SDK.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from intent_kernel.time_utils import utc_iso


def _mint_observation_id() -> str:
    return f"extobs_{uuid4().hex[:16]}"


@dataclass(frozen=True, slots=True)
class ExternalRestrictiveObservation:
    """Verified external restrictive signal as consumed by local policy.

    The adapter that produced this observation is responsible for:
    - authenticating the external source (HMAC/JWKS/mTLS — outside kernel)
    - mapping the external subject to a local governed identity
    - producing an integrity_reference that is a non-reversible digest
      (e.g., sha256 of the raw signal), never the raw token/secret

    This object is the RESULT — local code trusts it only if
    ``verified`` is True and ``integrity_reference`` is present.
    """

    observation_id: str = field(default_factory=_mint_observation_id)
    external_signal_id: str = ""
    external_signal_type: str = ""  # e.g., "RESTRICT", "REVOKE", "SUSPEND"
    source_identity: str = ""  # e.g., "okta", "azure_ad", "custom_adapter"
    source_binding: str = ""  # adapter instance / provenance
    received_at: str = field(default_factory=utc_iso)
    effective_at: str = field(default_factory=utc_iso)
    # Mapped local subject — at least one must be set (resource OR delegation)
    mapped_kind: str = ""  # "RESOURCE" | "DELEGATION" | "PERMISSION"
    mapped_resource_kind: str = ""  # ResourceType value string, e.g., "CAPABILITY"
    mapped_resource_id: str = ""
    mapped_governed_registration_id: str = ""
    mapped_generation: int = 0
    mapped_mission_id: str = ""
    mapped_action_id: str = ""
    mapped_delegation_id: str = ""
    integrity_reference: str = ""  # sha256 hex digest, not raw token
    verified: bool = False

    def __post_init__(self) -> None:
        for label in (
            "external_signal_id",
            "external_signal_type",
            "source_identity",
            "source_binding",
        ):
            v = getattr(self, label)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"{label} must be non-empty")
        for label in ("received_at", "effective_at"):
            v = getattr(self, label)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"{label} must be non-empty ISO timestamp")
        if not isinstance(self.verified, bool):
            raise ValueError("verified must be a bool")
        if not isinstance(self.integrity_reference, str):
            raise ValueError("integrity_reference must be a string")
        if self.verified and not self.integrity_reference.strip():
            raise ValueError(
                "verified observation must carry integrity_reference"
            )
        # At least one mapped subject must be present
        has_resource = bool(self.mapped_resource_id.strip())
        has_delegation = bool(self.mapped_delegation_id.strip())
        if not has_resource and not has_delegation:
            raise ValueError(
                "observation must map to at least one local subject "
                "(resource or delegation)"
            )
        if has_resource:
            if not self.mapped_resource_kind.strip():
                raise ValueError(
                    "mapped_resource_kind required when mapped_resource_id is set"
                )
        # No raw secret fields exist — structural guarantee by absence
        if not isinstance(self.mapped_generation, int) or isinstance(
            self.mapped_generation, bool
        ):
            raise ValueError("mapped_generation must be an int")

    def is_verified_and_mapped(self) -> bool:
        """Whether this observation is eligible for local consumption."""
        return bool(self.verified and self.integrity_reference.strip())


def integrity_reference_for(raw_signal: str) -> str:
    """Non-reversible digest for provenance — never store raw.

    Adapter calls this on the raw external signal bytes before
    constructing the observation. The raw value never leaves the
    adapter boundary.
    """
    return hashlib.sha256(raw_signal.encode("utf-8")).hexdigest()[:32]
