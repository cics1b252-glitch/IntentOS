"""M33.2C — Technical caller identity (request-bound, not authority)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    """Who presented the ingress credential for *this* request.

    A shared API key proves possession of an ingress credential, not
    a human/user identity. This object is provenance only — it never
    carries mission/action/capability/resource/grid/generation/
    delegation authority and is never consulted by ActionGate, the
    RRM, or ProductiveDispatchGuard.
    """

    caller_id: str
    credential_class: str
    validation_result: str
    credential_reference: str
    authenticated_at: str
