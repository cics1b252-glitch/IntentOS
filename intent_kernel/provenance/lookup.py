"""FRONT-F.M2 — Effect-first Authority Provenance Lookup.

Read-only discovery of candidate (mission_id, action_id) provenance from
durable effect-identity evidence, followed by canonical M1 reconstruction.

Canonical principle: PROVENANCE_IS_NOT_AUTHORITY — POWER TO EXPLAIN !=
POWER TO ACT. This module discovers candidates; it never authorizes,
mutates, repairs, certifies, transitions, verifies, or completes anything.

Resolution contract:
    effect identity
    → enumerate candidate missions/actions
    → load candidate
    → match identity
    → 0 matches = NOT_FOUND
    → >1 matches = AMBIGUOUS
    → exactly 1 match → FRESH RELOAD → M1 reconstruction → REVERIFY identity
    → return reconstruction

NEVER first-match-wins. Historical effect matching is independent from
current authority validity. A historical match can coexist with
CURRENT_VALIDITY = FALSE or UNKNOWN.

Bounded/truncated enumeration returns INCOMPLETE, never NOT_FOUND.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from intent_kernel.provenance.view import (
    AuthorityProvenanceView,
    LinkStatus,
    ProvenanceView,
)


# ---------------------------------------------------------------------------
# Effect lookup query
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectLookup:
    """Typed effect-first lookup query.

    At least one identity field must be nonempty. Empty fields are not
    match criteria. Context fields filter candidates (all supplied must
    match); they never broaden the search.
    """

    provider_effect_id: str = ""
    effect_identity_digest: str = ""
    local_execution_identity: str = ""
    capability: str = ""
    executor_kind: str = ""
    executor_logical_id: str = ""

    def __post_init__(self) -> None:
        identities = [
            self.provider_effect_id,
            self.effect_identity_digest,
            self.local_execution_identity,
        ]
        if not any(isinstance(v, str) and v.strip() for v in identities):
            raise ValueError(
                "EffectLookup requires at least one nonempty effect identity"
            )

    @property
    def identity_fields(self) -> Dict[str, str]:
        """Nonempty identity fields as match criteria."""
        result: Dict[str, str] = {}
        if self.provider_effect_id and self.provider_effect_id.strip():
            result["provider_effect_id"] = self.provider_effect_id
        if self.effect_identity_digest and self.effect_identity_digest.strip():
            result["effect_identity_digest"] = self.effect_identity_digest
        if self.local_execution_identity and self.local_execution_identity.strip():
            result["local_execution_identity"] = self.local_execution_identity
        return result


# ---------------------------------------------------------------------------
# Effect candidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectCandidate:
    """One discovered (mission_id, action_id) candidate."""

    mission_id: str
    action_id: str
    matched_on: str


# ---------------------------------------------------------------------------
# Effect lookup result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectLookupResult:
    """Structured M2 lookup result."""

    status: str
    query: EffectLookup
    candidates: Tuple[EffectCandidate, ...] = ()
    provenance: Optional[ProvenanceView] = None
    detail: str = ""
    search_complete: bool = True
    scanned_missions: int = 0
    skipped_corrupt: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "query": {
                "provider_effect_id": self.query.provider_effect_id,
                "effect_identity_digest": self.query.effect_identity_digest,
                "local_execution_identity": self.query.local_execution_identity,
                "capability": self.query.capability,
                "executor_kind": self.query.executor_kind,
                "executor_logical_id": self.query.executor_logical_id,
            },
            "candidates": [
                {
                    "mission_id": c.mission_id,
                    "action_id": c.action_id,
                    "matched_on": c.matched_on,
                }
                for c in self.candidates
            ],
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "detail": self.detail,
            "search_complete": self.search_complete,
            "scanned_missions": self.scanned_missions,
            "skipped_corrupt": self.skipped_corrupt,
        }


# ---------------------------------------------------------------------------
# Effect provenance lookup
# ---------------------------------------------------------------------------


class EffectProvenanceLookup:
    """Effect-first provenance discovery over durable mission records.

    Holds an M1 AuthorityProvenanceView (for canonical reconstruction) and
    an enumeration callable (for discovering candidate missions). The
    enumeration callable returns a list of mission_id strings to scan;
    it must NOT construct stores, mint identity, or mutate durable state.
    """

    def __init__(
        self,
        view: AuthorityProvenanceView,
        enumerate_mission_ids: Callable[[], List[str]],
        *,
        max_missions: Optional[int] = None,
    ) -> None:
        self._view = view
        self._enumerate = enumerate_mission_ids
        self._max_missions = max_missions

    def lookup(self, query: EffectLookup) -> EffectLookupResult:
        """Resolve an effect-first lookup query.

        Algorithm:
        1. Enumerate mission IDs.
        2. For each: load, scan action_states for identity matches.
        3. Collect ALL candidates (never first-match).
        4. 0 → NOT_FOUND; >1 → AMBIGUOUS; 1 → fresh reload + M1 + reverify.
        5. Bounded/truncated → INCOMPLETE (never NOT_FOUND).
        """
        identity_fields = query.identity_fields
        if not identity_fields:
            return EffectLookupResult(
                status=LinkStatus.INVALID,
                query=query,
                detail="empty effect identity: at least one field required",
                search_complete=False,
            )

        # -- enumerate -------------------------------------------------------
        try:
            all_ids = list(self._enumerate() or [])
        except Exception as exc:
            return EffectLookupResult(
                status=LinkStatus.INCOMPLETE,
                query=query,
                detail=f"enumeration failed: {type(exc).__name__}",
                search_complete=False,
            )

        # -- bounded scan ----------------------------------------------------
        truncated = False
        if self._max_missions is not None and len(all_ids) > self._max_missions:
            all_ids = all_ids[: self._max_missions]
            truncated = True

        # -- scan candidates -------------------------------------------------
        candidates: List[EffectCandidate] = []
        scanned = 0
        skipped = 0
        for mid in all_ids:
            try:
                data = self._view._load_mission(mid)
            except Exception:
                skipped += 1
                continue
            if data is None or not isinstance(data, Mapping):
                continue
            scanned += 1
            states = data.get("action_states", {})
            if not isinstance(states, Mapping):
                continue
            for aid, action in states.items():
                if not isinstance(action, dict):
                    continue
                for field_name, query_value in identity_fields.items():
                    record_value = str(action.get(field_name, "") or "")
                    if record_value and record_value == query_value:
                        # Context filter: all supplied must match
                        if query.capability:
                            plan = data.get("plan", ())
                            cap = ""
                            if isinstance(plan, (list, tuple)):
                                for entry in plan:
                                    if isinstance(entry, Mapping) and entry.get("action_id") == aid:
                                        cap = str(entry.get("capability", "") or "")
                                        break
                            if cap != query.capability:
                                continue
                        if query.executor_kind:
                            if str(action.get("expected_executor_kind", "") or "") != query.executor_kind:
                                continue
                        if query.executor_logical_id:
                            if str(action.get("expected_executor_logical_id", "") or "") != query.executor_logical_id:
                                continue
                        candidates.append(
                            EffectCandidate(
                                mission_id=mid,
                                action_id=aid,
                                matched_on=field_name,
                            )
                        )

        # -- bounded result --------------------------------------------------
        if truncated:
            return EffectLookupResult(
                status=LinkStatus.INCOMPLETE,
                query=query,
                candidates=tuple(candidates),
                detail=f"scan truncated at {self._max_missions} missions; completeness not established",
                search_complete=False,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )

        # -- resolution ------------------------------------------------------
        if not candidates:
            return EffectLookupResult(
                status=LinkStatus.NOT_FOUND,
                query=query,
                detail="no durable action matches the effect identity (complete scan)",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )
        if len(candidates) > 1:
            return EffectLookupResult(
                status=LinkStatus.AMBIGUOUS,
                query=query,
                candidates=tuple(candidates),
                detail=f"{len(candidates)} candidates match the effect identity; ambiguity unresolved",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )

        # -- exactly one: fresh reload + M1 + reverify -----------------------
        candidate = candidates[0]
        try:
            fresh_data = self._view._load_mission(candidate.mission_id)
        except Exception as exc:
            return EffectLookupResult(
                status=LinkStatus.INVALID,
                query=query,
                candidates=tuple(candidates),
                detail=f"fresh reload failed: {type(exc).__name__}",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )
        if fresh_data is None or not isinstance(fresh_data, Mapping):
            return EffectLookupResult(
                status=LinkStatus.NOT_FOUND,
                query=query,
                candidates=tuple(candidates),
                detail="candidate mission disappeared between discovery and reload",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )

        # Reverify identity against fresh data
        fresh_states = fresh_data.get("action_states", {})
        fresh_action = fresh_states.get(candidate.action_id) if isinstance(fresh_states, Mapping) else None
        if not isinstance(fresh_action, dict):
            return EffectLookupResult(
                status=LinkStatus.NOT_FOUND,
                query=query,
                candidates=tuple(candidates),
                detail="candidate action disappeared between discovery and reload",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )
        reverified = False
        for field_name, query_value in identity_fields.items():
            fresh_value = str(fresh_action.get(field_name, "") or "")
            if fresh_value and fresh_value == query_value:
                reverified = True
                break
        if not reverified:
            return EffectLookupResult(
                status=LinkStatus.NOT_FOUND,
                query=query,
                candidates=tuple(candidates),
                detail="effect identity changed between discovery and fresh reload",
                search_complete=True,
                scanned_missions=scanned,
                skipped_corrupt=skipped,
            )

        # M1 canonical reconstruction
        provenance = self._view.reconstruct_by_action(
            candidate.mission_id, candidate.action_id
        )
        return EffectLookupResult(
            status=provenance.overall_status,
            query=query,
            candidates=tuple(candidates),
            provenance=provenance,
            detail="unique match resolved via fresh reload + M1 reconstruction + identity reverify",
            search_complete=True,
            scanned_missions=scanned,
            skipped_corrupt=skipped,
        )
