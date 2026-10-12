"""FRONT-TP-09Q-R1: grounded filesystem observation adapter.

    OBSERVED_AT (observer clock)   != caller-asserted timestamp
    CONTENT SHA-256                != unique execution identity
    OLD SUCCESSFUL OBSERVATION     != current effect existence

Additive to the observation adapter contract ONLY. This module does not modify
``LocalFilesystemObserver``, ``ExternalObservationResult``, any authority type,
the completion gate, or frozen verification policy. It WRAPS the existing
trusted observer and augments its facts with:

  * an observation timestamp captured by the observer's OWN clock,
  * trusted runtime-established mission/action/effect binding,
  * a link to the durable ``ActionVerificationProof`` digest.

The host-content integrity check and authorized-target check are the existing
``LocalFilesystemObserver`` / ``CreateTestFileAuthority`` behaviour, unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from intent_kernel.adapters.local_filesystem import (
    CreateTestFileAuthority,
    ExecutionReceipt,
    LocalFilesystemObserver,
)
from intent_kernel.time_utils import utc_iso

DEFAULT_MAX_OBSERVATION_AGE_SECONDS = 300.0


class GroundingError(RuntimeError):
    """Observation provenance is unverifiable. Never yields SATISFIED."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GroundedObservation:
    """A trusted host observation bound to mission/action/effect + proof."""

    mission_id: str
    action_id: str
    authorized_target: str
    expected_content_sha256: str
    observed_sha256: str
    content_matches: bool
    exists: bool
    observed_at: str
    observer_id: str
    observer_version: str
    gate_proof_digest: str
    record_digest: str = ""

    def __post_init__(self) -> None:
        expected = compute_grounded_digest(self)
        if self.record_digest and self.record_digest != expected:
            raise GroundingError("forged-observation-record")
        object.__setattr__(self, "record_digest", expected)


def compute_grounded_digest(observation: "GroundedObservation") -> str:
    payload = {
        "mission_id": observation.mission_id,
        "action_id": observation.action_id,
        "authorized_target": observation.authorized_target,
        "expected_content_sha256": observation.expected_content_sha256,
        "observed_sha256": observation.observed_sha256,
        "content_matches": observation.content_matches,
        "exists": observation.exists,
        "observed_at": observation.observed_at,
        "observer_id": observation.observer_id,
        "observer_version": observation.observer_version,
        "gate_proof_digest": observation.gate_proof_digest,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_fresh(observed_at: str, now: datetime,
             max_age_seconds: float = DEFAULT_MAX_OBSERVATION_AGE_SECONDS) -> bool:
    """Bounded-elapsed-age freshness with clock-rollback fail-closed.

    A timestamp in the future (clock rollback / skew) is NOT fresh, because
    elapsed age cannot be trusted. Uncertain -> False.
    """
    try:
        observed = datetime.fromisoformat(str(observed_at))
    except (ValueError, TypeError):
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if observed > now:
        return False
    return (now - observed).total_seconds() <= max_age_seconds


class GroundedFilesystemObserver:
    """Trusted observer: wraps LocalFilesystemObserver + binds provenance.

    Constructed ONLY from a trusted runtime-established binding. It is never
    reachable from a request, a plan, or an executor response.
    """

    OBSERVER_ID = "GroundedFilesystemObserver"
    OBSERVER_VERSION = "1"

    def __init__(
        self,
        grant: CreateTestFileAuthority,
        mission_id: str,
        action_id: str,
        gate_proof_digest: str,
        now_provider: Optional[Any] = None,
    ) -> None:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise GroundingError("mission-id-required")
        if not isinstance(action_id, str) or not action_id.strip():
            raise GroundingError("action-id-required")
        if not isinstance(gate_proof_digest, str) or not gate_proof_digest.strip():
            raise GroundingError("missing-gate-proof")
        self._grant = grant
        self._mission_id = mission_id
        self._action_id = action_id
        self._gate_proof_digest = gate_proof_digest
        self._now_provider = now_provider

    def _now(self) -> datetime:
        if self._now_provider is not None:
            return self._now_provider()
        return datetime.now(timezone.utc)

    def observe(self) -> GroundedObservation:
        host = LocalFilesystemObserver(self._grant).observe()
        return GroundedObservation(
            mission_id=self._mission_id,
            action_id=self._action_id,
            authorized_target=str(self._grant.authorized_target),
            expected_content_sha256=self._grant.expected_content_sha256,
            observed_sha256=host.observed_sha256,
            content_matches=bool(host.matches_authorized),
            exists=bool(host.exists),
            observed_at=utc_iso(self._now()),
            observer_id=self.OBSERVER_ID,
            observer_version=self.OBSERVER_VERSION,
            gate_proof_digest=self._gate_proof_digest,
        )


__all__ = [
    "DEFAULT_MAX_OBSERVATION_AGE_SECONDS",
    "GroundingError",
    "GroundedObservation",
    "GroundedFilesystemObserver",
    "compute_grounded_digest",
    "is_fresh",
]
