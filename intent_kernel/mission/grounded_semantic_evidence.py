"""FRONT-TP-09Q-R1: grounded evidence adapter for TrustedSemanticEvaluator.

    CALLER-AUTHORED EVIDENCE != GROUNDED OBSERVATION
    CONTENT SHA-256          != unique execution identity

Converts a :class:`GroundedObservation` (produced by the trusted
``GroundedFilesystemObserver``) into the evidence shape consumed by the inert
semantic contract — but ONLY after re-validating, fail-closed, that the
observation is genuinely bound to the expected mission, action, target,
content specification, durable gate proof and freshness window.

This adapter grants NO execution authority and is NOT wired into the
completion gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from intent_kernel.adapters.grounded_observation import (
    DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
    GroundedObservation,
    GroundingError,
    compute_grounded_digest,
    is_fresh,
)


def ground_semantic_evidence(
    observation: Any,
    *,
    mission_id: str,
    action_id: str,
    expected_target: str,
    expected_content_sha256: str,
    now: Optional[datetime] = None,
    max_age_seconds: float = DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
    require_gate_proof: bool = True,
    receipt: Any = None,
) -> Dict[str, Any]:
    """Validate a grounded observation and return evaluator evidence.

    Raises :class:`GroundingError` (explicit denial) on ANY anomaly. It never
    returns evidence that could yield SATISFIED from untrusted input.
    """
    now = now or datetime.now(timezone.utc)

    # 1. Reject caller-authored records outright.
    if not isinstance(observation, GroundedObservation):
        raise GroundingError("caller-authored-record")

    # 2. Reject a tampered/forged observation record.
    if compute_grounded_digest(observation) != observation.record_digest:
        raise GroundingError("forged-observation-record")

    # 3. Cross-mission / cross-action / wrong-target / wrong-spec reuse.
    if observation.mission_id != mission_id:
        raise GroundingError("cross-mission")
    if observation.action_id != action_id:
        raise GroundingError("cross-action")
    if observation.authorized_target != expected_target:
        raise GroundingError("wrong-target")
    if observation.expected_content_sha256 != expected_content_sha256:
        raise GroundingError("wrong-content-spec")

    # 4. Durable verification proof required.
    if require_gate_proof and not observation.gate_proof_digest:
        raise GroundingError("missing-gate-proof")

    # 5. Content integrity against the authorized effect specification.
    if not observation.exists:
        raise GroundingError("effect-absent")
    if not observation.content_matches \
            or observation.observed_sha256 != expected_content_sha256:
        raise GroundingError("content-mismatch")

    # 6. Freshness from the observer's own clock (never a caller marker).
    if not is_fresh(observation.observed_at, now, max_age_seconds):
        raise GroundingError("stale-observation")

    # 7. Conflicting executor receipt (self-report vs observed fact).
    if receipt is not None:
        reported = getattr(receipt, "reported_digest", None)
        if reported and reported != observation.observed_sha256:
            raise GroundingError("conflicting-receipt")

    return {
        "__result__": {
            "result": {
                "path": observation.authorized_target,
                "sha256": observation.observed_sha256,
                "mission_id": mission_id,
                "action_id": action_id,
            }
        },
        "gate_proof": {
            "digest": observation.gate_proof_digest,
            "mission_id": mission_id,
            "action_id": action_id,
            "observed_at": observation.observed_at,
        },
    }


__all__ = ["ground_semantic_evidence"]
