"""M32B-2 — Local execution identity: deterministic canonical digest (MODEL E2).

Local execution identity binds one dispatchable unit of work from stable
PRE-DISPATCH fields only:

    1. mission_id
    2. action_id
    3. request_semantics_digest
    4. executor_logical_id (the expected executor logical identity)
    5. expected governed_registration_id
    6. expected generation (int; type-distinct from strings)

Canonical form: JSON array of exactly these six values in this order
(order is positional), compact separators, UTF-8, allow_nan=False;
SHA-256 hex digest of those bytes.

The identity is frozen before the dispatch boundary and NEVER redefined
afterwards. In particular provider_effect_id / effect_identity_digest —
which become known only after dispatch — are POST-DISPATCH effect
provenance, NOT components of the local identity:

    LOCAL_EXECUTION_IDENTITY_BEFORE_DISPATCH
    ==
    LOCAL_EXECUTION_IDENTITY_AFTER_PROVIDER_EFFECT_BINDING

for the same execution attempt. Changing any of the six semantic
components changes the identity. No timestamps, no Python repr/object
addresses, no random process-local values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_identity_bytes(*components: Any) -> bytes:
    """Canonical bytes for an ordered identity component tuple."""
    return json.dumps(
        list(components),
        sort_keys=False,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_local_execution_identity(
    mission_id: str,
    action_id: str,
    request_semantics_digest: str,
    executor_logical_id: str,
    expected_governed_registration_id: str,
    expected_generation: int,
) -> str:
    """Deterministic SHA-256 local execution identity (hex, 64 chars).

    MODEL E2: pre-dispatch fields only. Post-dispatch effect provenance
    never enters this digest.
    """
    for label, value in (
        ("mission_id", mission_id),
        ("action_id", action_id),
        ("request_semantics_digest", request_semantics_digest),
        ("executor_logical_id", executor_logical_id),
        ("expected_governed_registration_id", expected_governed_registration_id),
    ):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string")
    if not isinstance(expected_generation, int) or isinstance(
        expected_generation, bool
    ):
        raise ValueError("expected_generation must be an int")
    return hashlib.sha256(
        canonical_identity_bytes(
            mission_id,
            action_id,
            request_semantics_digest,
            executor_logical_id,
            expected_governed_registration_id,
            expected_generation,
        )
    ).hexdigest()


def effect_identity_digest_for(provider_effect_id: str) -> str:
    """Digest over an opaque provider-supplied effect token.

    Returns "" when no provider effect identity exists. An absent token
    means external exactly-once remains unprovable — this function never
    fills that gap, it only canonically fingerprints a token the provider
    actually supplied.
    """
    if not isinstance(provider_effect_id, str):
        raise ValueError("provider_effect_id must be a string")
    if not provider_effect_id:
        return ""
    return hashlib.sha256(
        canonical_identity_bytes(provider_effect_id)
    ).hexdigest()
