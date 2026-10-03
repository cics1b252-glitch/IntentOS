"""FRONT-F.M1 — Authority Provenance View, mission/action scope.

Read-only reconstruction answering, from durable canonical evidence alone:

    WHERE DID THE AUTHORITY FOR THIS EXACT EFFECT COME FROM?

Canonical principle: PROVENANCE_IS_NOT_AUTHORITY — POWER TO EXPLAIN !=
POWER TO ACT. This module is incapable by construction of mutating,
granting, or executing anything:

- it receives only narrow read callables (mission load/exists, detached
  RRM snapshot getters) plus pure recompute functions;
- it never imports or references stores, authorities, guards, executors,
  registries, gates, or services;
- every source it touches is evidence; every verdict is recomputed from
  already-loaded mappings, never trusted from a hint or cache.

Scope (M1): reconstruct_by_action(mission_id, action_id) only. No global
scan, no secondary index, no effect-first lookup (M2), no quantity
authority, no human-principal infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from intent_kernel.mission import delegation as _delegation
from intent_kernel.mission import execution_identity as _identity


class LinkStatus:
    """Evidence-based per-link / overall statuses (FRONT-F Phase 6)."""

    PROVEN = "PROVEN"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"


# Reasons that describe expected lifecycle invalidation (revoked/expired
# ancestor): historical provenance stays attributable while current
# authority is false. Every other re-proof failure is structural.
_HISTORICAL_VALID_REASONS = frozenset({"ancestor-not-active", "ancestor-expired"})


@dataclass(frozen=True)
class LinkResult:
    """One provenance link: status + human-readable detail + evidence refs."""

    status: str
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class ProvenanceView:
    """Structured M1 reconstruction result (FRONT-F Phase 5, minimum)."""

    query_identity: str
    mission_id: str
    action_id: str
    sovereign_origin: Dict[str, Any]
    human_principal: str
    intent: Dict[str, Any]
    plan_action: Dict[str, Any]
    delegation: Dict[str, Any]
    executor: Dict[str, Any]
    ceiling: Dict[str, Any]
    digests: Dict[str, Any]
    dispatch: Dict[str, Any]
    effect: Dict[str, Any]
    verification: Dict[str, Any]
    completion: Dict[str, Any]
    historical: Dict[str, Any]
    current: Dict[str, Any]
    evidence_refs: Dict[str, Any]
    overall_status: str
    missing_links: List[str] = field(default_factory=list)
    ambiguous_links: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_identity": self.query_identity,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "sovereign_origin": dict(self.sovereign_origin),
            "human_principal": self.human_principal,
            "intent": dict(self.intent),
            "plan_action": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.plan_action.items()},
            "delegation": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.delegation.items()},
            "executor": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.executor.items()},
            "ceiling": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.ceiling.items()},
            "digests": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.digests.items()},
            "dispatch": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.dispatch.items()},
            "effect": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.effect.items()},
            "verification": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.verification.items()},
            "completion": {k: (v.to_dict() if isinstance(v, LinkResult) else v) for k, v in self.completion.items()},
            "historical": dict(self.historical),
            "current": dict(self.current),
            "evidence_refs": dict(self.evidence_refs),
            "overall_status": self.overall_status,
            "missing_links": list(self.missing_links),
            "ambiguous_links": list(self.ambiguous_links),
        }


def _link(status: str, detail: str, **evidence: Any) -> LinkResult:
    return LinkResult(status=status, detail=detail, evidence=dict(evidence))


def _chain_expiry_state(chain: Any) -> str:
    """Expiry dependency of a walked delegation chain: tri-state.

    Returns "PRESENT" when any walked grant carries an expiry timestamp,
    "ABSENT" when the chain is structurally sound and expiry-free, and
    "UNKNOWN" when inspection itself fails (malformed chain/object).

    UNKNOWN != ABSENT: inspection uncertainty must never be read as proof
    of no expiry. Callers map PRESENT and UNKNOWN identically for current
    validity (unknown/unevaluated, never True) while keeping them
    distinct in diagnostics. Pure read; narrowly catches structural
    inspection errors only (broad failures propagate).
    """
    try:
        entries = list(chain or ())
    except (TypeError, ValueError, AttributeError):
        return "UNKNOWN"
    try:
        for entry in entries:
            _aid, _action, grant = entry
            if isinstance(grant, Mapping) and str(
                grant.get("delegation_expires_at", "") or ""
            ):
                return "PRESENT"
    except (TypeError, ValueError, AttributeError):
        return "UNKNOWN"
    return "ABSENT"
    return False


class AuthorityProvenanceView:
    """Mission/action-scoped provenance reconstruction (M1).

    Narrow read ports only (all optional except ``load_mission``):

    - ``load_mission(mission_id)``: returns the canonical mission mapping
      (as ``store.load`` does) or ``None`` when absent; raises on
      corrupt/invalid persisted data.
    - ``mission_exists(mission_id)``: optional boolean pre-check.
    - ``rrm_capability(name)`` / ``rrm_agent(id)`` / ``rrm_provider(id)``:
      optional detached snapshot mappings with keys
      ``governed_registration_id`` / ``generation`` / ``eligible``,
      or ``None`` when the resource is absent (retired/unknown).
    - ``installation_id``: expected sovereign installation identity ("" skips
      the continuity comparison).
    - ``now_iso``: caller-supplied clock reading for expiry checks; the
      view itself never reads a clock.
    """

    def __init__(
        self,
        *,
        load_mission: Callable[[str], Optional[Mapping[str, Any]]],
        mission_exists: Optional[Callable[[str], bool]] = None,
        rrm_capability: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
        rrm_agent: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
        rrm_provider: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
        installation_id: str = "",
        now_iso: str = "",
    ) -> None:
        self._load_mission = load_mission
        self._mission_exists = mission_exists
        self._rrm_capability = rrm_capability
        self._rrm_agent = rrm_agent
        self._rrm_provider = rrm_provider
        self._installation_id = installation_id or ""
        self._now_iso = now_iso or ""

    # -- internal helpers (pure) --------------------------------------

    def _snapshot_for(
        self, kind: str, capability: str, executor_id: str
    ) -> Optional[Mapping[str, Any]]:
        if kind == "core_app":
            getter = self._rrm_capability
            key = capability
        elif kind == "agent":
            getter = self._rrm_agent
            key = executor_id
        elif kind == "provider":
            getter = self._rrm_provider
            key = executor_id
        else:
            return None
        if getter is None:
            return None
        try:
            snap = getter(key)
        except Exception:
            return None
        return snap if isinstance(snap, Mapping) else None

    # -- public contract -----------------------------------------------

    def reconstruct_by_action(
        self, mission_id: str, action_id: str
    ) -> ProvenanceView:
        """Reconstruct provenance for one durable (mission_id, action_id)."""
        query_identity = f"{mission_id or ''}#{action_id or ''}"
        if not isinstance(mission_id, str) or not mission_id.strip():
            return self._not_found(query_identity, "", action_id or "",
                                   "mission_id must be a non-empty string")
        if not isinstance(action_id, str) or not action_id.strip():
            return self._not_found(query_identity, mission_id, "",
                                   "action_id must be a non-empty string")
        try:
            if self._mission_exists is not None and not self._mission_exists(mission_id):
                return self._not_found(query_identity, mission_id, action_id,
                                       "no durable MissionRecord for mission_id")
            data = self._load_mission(mission_id)
        except Exception as exc:
            return self._invalid(query_identity, mission_id, action_id,
                                 f"canonical load failed: {type(exc).__name__}")
        if data is None or not isinstance(data, Mapping):
            return self._not_found(query_identity, mission_id, action_id,
                                   "no durable MissionRecord for mission_id")
        states = data.get("action_states", {})
        action = states.get(action_id) if isinstance(states, Mapping) else None
        if not isinstance(action, dict):
            return self._not_found(query_identity, mission_id, action_id,
                                   "mission has no such action_id")
        plan_entry: Optional[Dict[str, Any]] = None
        plan = data.get("plan", ())
        if isinstance(plan, (list, tuple)):
            for entry in plan:
                if isinstance(entry, Mapping) and entry.get("action_id") == action_id:
                    plan_entry = dict(entry)
                    break
        if plan_entry is None:
            return self._invalid(query_identity, mission_id, action_id,
                                 "action present without plan entry (structural corruption)")
        return self._reconstruct(query_identity, mission_id, action_id,
                                 data, action, plan_entry)

    # -- terminal constructors ------------------------------------------

    def _not_found(self, query_identity: str, mission_id: str,
                   action_id: str, detail: str) -> ProvenanceView:
        empty = _link(LinkStatus.NOT_FOUND, detail)
        return ProvenanceView(
            query_identity=query_identity, mission_id=mission_id,
            action_id=action_id,
            sovereign_origin={}, human_principal="NOT_RECORDED",
            intent={}, plan_action={"link": empty}, delegation={"link": empty},
            executor={"link": empty}, ceiling={"link": empty},
            digests={"link": empty}, dispatch={"link": empty},
            effect={"link": empty}, verification={"link": empty},
            completion={"link": empty}, historical={}, current={},
            evidence_refs={}, overall_status=LinkStatus.NOT_FOUND,
            missing_links=["mission/action"], ambiguous_links=[],
        )

    def _invalid(self, query_identity: str, mission_id: str,
                 action_id: str, detail: str) -> ProvenanceView:
        bad = _link(LinkStatus.INVALID, detail)
        return ProvenanceView(
            query_identity=query_identity, mission_id=mission_id,
            action_id=action_id,
            sovereign_origin={}, human_principal="NOT_RECORDED",
            intent={}, plan_action={"link": bad}, delegation={"link": bad},
            executor={"link": bad}, ceiling={"link": bad},
            digests={"link": bad}, dispatch={"link": bad},
            effect={"link": bad}, verification={"link": bad},
            completion={"link": bad}, historical={}, current={},
            evidence_refs={}, overall_status=LinkStatus.INVALID,
            missing_links=[], ambiguous_links=[],
        )

    # -- core reconstruction (pure over loaded mappings) ------------------

    def _reconstruct(
        self, query_identity: str, mission_id: str, action_id: str,
        data: Mapping[str, Any], action: Dict[str, Any],
        plan_entry: Dict[str, Any],
    ) -> ProvenanceView:
        missing: List[str] = []
        invalid = False

        # Sovereign origin: durable installation identity; human never inferred.
        record_installation = str(data.get("installation_id", "") or "")
        continuity_ok: Optional[bool] = None
        if self._installation_id:
            continuity_ok = bool(record_installation) and record_installation == self._installation_id
        sovereign = {
            "installation_id": record_installation,
            "continuity_match": continuity_ok,
            "link": _link(
                LinkStatus.PROVEN if record_installation else LinkStatus.INCOMPLETE,
                "durable installation identity" if record_installation else "installation identity absent",
                installation_id=record_installation,
            ),
        }

        # Intent: definition digest reference (constrains, never grants).
        intent_digest = str(data.get("mission_definition_digest", "") or "")
        intent = {
            "mission_definition_digest": intent_digest,
            "link": _link(
                LinkStatus.PROVEN if intent_digest else LinkStatus.INCOMPLETE,
                "durable mission definition digest" if intent_digest else "definition digest absent",
            ),
        }

        # Plan/action reference.
        plan_digest = str(plan_entry.get("request_semantics_digest", "") or "")
        plan_link = _link(
            LinkStatus.PROVEN if plan_digest else LinkStatus.INCOMPLETE,
            "durable plan entry with request semantics digest" if plan_digest else "plan entry lacks request_semantics_digest",
            capability=str(plan_entry.get("capability", "") or ""),
            node_id=str(plan_entry.get("node_id", "") or ""),
        )
        plan_action = {"link": plan_link, "entry_capability": str(plan_entry.get("capability", "") or "")}

        # Executor / binding identity (durable record fact).
        kind = str(action.get("expected_executor_kind", "") or "")
        executor_id = str(action.get("expected_executor_logical_id", "") or "")
        grid = str(action.get("expected_governed_registration_id", "") or "")
        try:
            gen = int(action.get("expected_resource_generation", 0) or 0)
        except (TypeError, ValueError):
            gen = 0
        resource_id = str(action.get("expected_resource_id", "") or "")
        capability = str(plan_entry.get("capability", "") or "")
        binding_ok = bool(kind and plan_digest)
        executor = {
            "link": _link(
                LinkStatus.PROVEN if binding_ok else LinkStatus.INCOMPLETE,
                "durable expected executor/binding triple" if binding_ok else "executor/binding expectations absent",
            ),
            "executor_kind": kind,
            "executor_logical_id": executor_id,
            "governed_registration_id": grid,
            "generation": gen,
            "resource_id": resource_id,
        }

        # Digests: recompute local execution identity + effect digest.
        try:
            recomputed_identity = _identity.compute_local_execution_identity(
                mission_id, action_id, plan_digest, executor_id, grid, gen,
            )
        except Exception:
            recomputed_identity = ""
        stored_identity = str(action.get("local_execution_identity", "") or "")
        if stored_identity and recomputed_identity and stored_identity == recomputed_identity:
            identity_link = _link(LinkStatus.PROVEN, "stored identity matches recomputation from durable fields",
                                  local_execution_identity=stored_identity)
        elif not stored_identity:
            identity_link = _link(LinkStatus.INCOMPLETE, "identity not yet bound (pre-dispatch action)")
            missing.append("local_execution_identity")
        else:
            identity_link = _link(LinkStatus.INVALID, "stored identity differs from recomputation (tamper)",
                                  stored=stored_identity, recomputed=recomputed_identity)
            invalid = True
        token = str(action.get("provider_effect_id", "") or "")
        try:
            recomputed_effect = _identity.effect_identity_digest_for(token)
        except Exception:
            recomputed_effect = ""
        stored_effect = str(action.get("effect_identity_digest", "") or "")
        if token and stored_effect and stored_effect == recomputed_effect:
            effect_digest_link = _link(LinkStatus.PROVEN, "effect digest matches recomputation over presented token")
        elif not token:
            effect_digest_link = _link(LinkStatus.INCOMPLETE, "no provider effect token bound (external exactly-once unprovable)")
            missing.append("provider_effect_id")
        else:
            effect_digest_link = _link(LinkStatus.INVALID, "effect digest differs from recomputation (tamper)")
            invalid = True
        digests = {
            "link": identity_link,
            "request_semantics_digest": plan_digest,
            "local_execution_identity": stored_identity,
            "effect_identity_link": effect_digest_link,
        }

        # Delegation: historical grant copy + current re-proof (pure).
        grant = _delegation.grant_view(action)
        if grant is None:
            delegation_link = _link(LinkStatus.PROVEN, "not-delegated")
            delegation_current: Dict[str, Any] = {"applicable": False, "valid_now": True,
                                                  "detail": "no delegation on this action"}
            delegation_historical: Dict[str, Any] = {"present": False}
        else:
            gid = str(grant.get("delegation_id", "") or "")
            if not gid:
                delegation_link = _link(LinkStatus.INVALID, "malformed grant (delegation_id absent)")
                invalid = True
                delegation_historical = {"present": True, "malformed": True}
                delegation_current = {"applicable": True, "valid_now": False, "detail": "malformed grant"}
            else:
                delegation_historical = {
                    "present": True,
                    "delegation_id": gid,
                    "state": str(grant.get("delegation_state", "") or ""),
                    "parent_action_id": str(grant.get("delegation_parent_action_id", "") or ""),
                    "root_action_id": str(grant.get("delegation_root_action_id", "") or ""),
                    "delegate_agent_id": str(grant.get("delegation_delegate_agent_id", "") or ""),
                    "allowed_capabilities": list(grant.get("delegation_allowed_capabilities", ()) or ()),
                    "allowed_resources": list(grant.get("delegation_allowed_resources", ()) or ()),
                    "allowed_targets": list(grant.get("delegation_allowed_targets", ()) or ()),
                    "expires_at": str(grant.get("delegation_expires_at", "") or ""),
                    "revoked_at": str(grant.get("delegation_revoked_at", "") or ""),
                    "revoke_reason": str(grant.get("delegation_revoke_reason", "") or ""),
                }
                try:
                    _states = data.get("action_states", {})
                    _plan = data.get("plan", ())
                    ok, why, _chain = _delegation.verify_grant_dispatch(
                        {"action_states": dict(_states) if isinstance(_states, Mapping) else {},
                         "plan": list(_plan) if isinstance(_plan, (list, tuple)) else [],
                         "mission_id": mission_id},
                        action_id, now_iso=self._now_iso,
                    )
                except Exception as exc:
                    ok, why = False, f"reproof-error:{type(exc).__name__}"
                if ok:
                    expiry_state = _chain_expiry_state(_chain)
                    if not self._now_iso and expiry_state != "ABSENT":
                        # FRONT-F.M1.1/M1.2: expiry evaluation needs a current
                        # clock. With none supplied, a PRESENT expiry — and,
                        # fail-closed, an UNKNOWN expiry dependency — leaves
                        # CURRENT validity unknown, never True. UNKNOWN is
                        # not ABSENT: inspection failure must not become
                        # proof of no expiry. Historical attribution below
                        # is untouched.
                        if expiry_state == "PRESENT":
                            detail = ("chain structurally valid but expiry unevaluated: "
                                      "no current clock supplied (current validity unknown, never True)")
                            clock_evidence = "unavailable"
                        else:  # UNKNOWN
                            detail = ("chain expiry dependency indeterminate (inspection "
                                      "uncertainty): no current clock supplied (current validity "
                                      "unknown, never True)")
                            clock_evidence = "indeterminate"
                        delegation_link = _link(LinkStatus.INCOMPLETE, detail,
                                                delegation_id=gid)
                        delegation_current = {"applicable": True, "valid_now": False,
                                              "clock_evidence": clock_evidence,
                                              "detail": detail}
                        missing.append("current_clock")
                    else:
                        delegation_link = _link(LinkStatus.PROVEN, "chain re-proven from durable state (ACTIVE, unexpired, in-scope)",
                                                delegation_id=gid)
                        delegation_current = {"applicable": True, "valid_now": True, "detail": "chain valid at re-proof"}
                elif why in _HISTORICAL_VALID_REASONS:
                    delegation_link = _link(LinkStatus.PROVEN, f"historical grant attributable; current authority invalid ({why})",
                                            delegation_id=gid)
                    delegation_current = {"applicable": True, "valid_now": False,
                                          "detail": f"current authority invalid: {why} (historical provenance preserved)"}
                else:
                    delegation_link = _link(LinkStatus.INVALID, f"chain re-proof failed structurally: {why}",
                                            delegation_id=gid)
                    invalid = True
                    delegation_current = {"applicable": True, "valid_now": False, "detail": f"structural failure: {why}"}
        delegation = {"link": delegation_link, "historical": delegation_historical,
                      "current": delegation_current}

        # Ceiling: conjunctive lattice values from durable evidence (no new object).
        grant_map = _delegation.grant_view(action) or {}
        ceiling_values = {
            "delegation_scope": {
                "allowed_capabilities": list(grant_map.get("delegation_allowed_capabilities", ()) or ()),
                "allowed_resources": list(grant_map.get("delegation_allowed_resources", ()) or ()),
                "allowed_targets": list(grant_map.get("delegation_allowed_targets", ()) or ()),
            } if grant_map else None,
            "capability": capability,
            "operation": plan_digest,
            "target": resource_id,
            "executor": {"kind": kind, "logical_id": executor_id},
            "binding": {"grid": grid, "generation": gen},
            "risk_level": str(grant_map.get("delegation_max_risk_level", "") or "") if grant_map else "",
            "timeout_seconds": grant_map.get("delegation_max_timeout_seconds", 0) if grant_map else 0,
            "require_verification": grant_map.get("delegation_require_verification", None) if grant_map else None,
            "max_side_effect": str(grant_map.get("delegation_max_side_effect", "") or "") if grant_map else "",
            "confirmation_required": bool(action.get("confirmation_required", False)),
            "confirmation_basis_digest": str(action.get("confirmation_basis_digest", "") or ""),
            "quantity": "absent/deferred (no quantity authority in V1)",
        }
        ceiling = {
            "link": _link(LinkStatus.PROVEN, "lattice components read from durable evidence (no new ceiling object)"),
            "components": ceiling_values,
        }

        # Dispatch / action state + effect observation.
        state = action.get("state", "")
        state_name = str(getattr(state, "value", state) or "")
        dispatch = {
            "link": _link(LinkStatus.PROVEN, "durable action state read from canonical record",
                          state=state_name),
            "action_state": state_name,
            "attempt_count": action.get("attempt_count", 0),
            "error_message": str(action.get("error_message", "") or ""),
        }
        effect = {
            "link": _link(
                LinkStatus.PROVEN if token and effect_digest_link.status == LinkStatus.PROVEN
                else LinkStatus.INCOMPLETE,
                "effect attributed to external token" if token and effect_digest_link.status == LinkStatus.PROVEN
                else "effect unattributed to external token (attempt identity still proves dispatch unit)",
            ),
            "provider_effect_id": token,
            "effect_identity_digest": stored_effect,
            "result_present": action.get("result", None) is not None,
        }
        if effect["link"].status == LinkStatus.INCOMPLETE:
            missing.append("effect_attribution")

        # Verification: record-canonical (proof object itself is never stored).
        vstatus = str(action.get("verification_status", "") or "")
        vdigest = str(action.get("verification_proof_digest", "") or "")
        # Mirror the authority's own gate: only VERIFIED_SUCCESS with a
        # bound proof digest counts (cf. runtime/verification authority_complete).
        if vstatus == "VERIFIED_SUCCESS" and vdigest:
            verification_link = _link(LinkStatus.PROVEN, "record-canonical VERIFIED with proof digest (proof object not durably stored; recomputation unavailable)",
                                      verification_status=vstatus, proof_digest=vdigest)
        else:
            verification_link = _link(LinkStatus.INCOMPLETE, "no VERIFIED proof digest recorded",
                                      verification_status=vstatus)
            missing.append("verification_proof")
        verification = {"link": verification_link, "status": vstatus, "proof_digest": vdigest}

        # Completion: action completion (state) vs mission completion (no writer).
        completion_state = data.get("completion_state", {})
        completion = {
            "link": _link(
                LinkStatus.PROVEN if state_name.upper() == "COMPLETED" else LinkStatus.INCOMPLETE,
                "action COMPLETED in durable state" if state_name.upper() == "COMPLETED"
                else "action not COMPLETED in durable state",
                action_state=state_name,
            ),
            "mission_completion_state": dict(completion_state) if isinstance(completion_state, Mapping) else {},
        }
        if completion["link"].status == LinkStatus.INCOMPLETE:
            missing.append("completion")

        # CURRENT RRM re-read (observation only; never historical rewrite).
        snap = self._snapshot_for(kind, capability, executor_id)
        if snap is None and (self._rrm_capability or self._rrm_agent or self._rrm_provider) is not None:
            # Ports wired but resource absent (retired/unknown) or kind unsupported.
            binding_current: Dict[str, Any] = {"observable": True, "executable_now": False,
                                               "detail": "resource absent from RRM read port (retired or unknown)"}
        elif snap is None:
            binding_current = {"observable": False, "executable_now": None,
                               "detail": "no RRM read port wired; current binding not re-readable"}
        else:
            try:
                sgen = int(snap.get("generation", 0) or 0)
            except (TypeError, ValueError):
                sgen = 0
            sgrid = str(snap.get("governed_registration_id", "") or "")
            selig = snap.get("eligible", None)
            # NOTE: eligible unknown (None) does not fail closed here: the view
            # reports observation, and exact equality of grid+generation governs.
            ok_now = (sgrid == grid and bool(grid) and sgen == gen and selig is not False)
            binding_current = {"observable": True, "executable_now": bool(ok_now),
                               "detail": "grid+generation exact match with eligibility not-false"
                               if ok_now else "current grid/generation/eligibility differs from durable expectation",
                               "observed_grid": sgrid, "observed_generation": sgen,
                               "observed_eligible": selig}

        historical = {
            "mission_revision": data.get("revision", 0),
            "action_state": state_name,
            "binding": {"grid": grid, "generation": gen, "executor_kind": kind,
                        "executor_logical_id": executor_id, "resource_id": resource_id},
            "digests": {"request_semantics_digest": plan_digest,
                        "local_execution_identity": stored_identity,
                        "effect_identity_digest": stored_effect},
            "delegation": delegation_historical,
            "verification": {"status": vstatus, "proof_digest": vdigest},
        }
        current = {
            "binding": binding_current,
            "delegation": delegation_current,
            "action_state_now": state_name,
            "note": "re-verification of evidence only; never an authorization decision",
        }

        evidence_refs = {
            "mission_record": {"mission_id": mission_id,
                               "revision": data.get("revision", 0)},
            "plan_digest": plan_digest,
        }

        # Overall composition (fail-closed ordering).
        if invalid:
            overall = LinkStatus.INVALID
        else:
            links = [sovereign["link"], intent["link"], plan_link, identity_link,
                     delegation_link, executor["link"], ceiling["link"],
                     dispatch["link"], effect["link"], verification_link,
                     completion["link"]]
            statuses = {lk.status for lk in links}
            if statuses == {LinkStatus.PROVEN}:
                overall = LinkStatus.PROVEN
            else:
                overall = LinkStatus.PARTIAL
        if overall == LinkStatus.PARTIAL and not missing:
            missing = [name for name, sec in (
                ("sovereign_origin", sovereign["link"]), ("intent", intent["link"]),
                ("plan", plan_link), ("identity", identity_link),
                ("delegation", delegation_link), ("executor", executor["link"]),
                ("ceiling", ceiling["link"]), ("dispatch", dispatch["link"]),
                ("effect", effect["link"]), ("verification", verification_link),
                ("completion", completion["link"]),
            ) if sec.status == LinkStatus.INCOMPLETE]

        return ProvenanceView(
            query_identity=query_identity, mission_id=mission_id,
            action_id=action_id,
            sovereign_origin={"installation_id": record_installation,
                              "continuity_match": continuity_ok,
                              "link": sovereign["link"]},
            human_principal="NOT_RECORDED",
            intent={"mission_definition_digest": intent_digest, "link": intent["link"]},
            plan_action=plan_action, delegation=delegation, executor=executor,
            ceiling=ceiling, digests=digests, dispatch=dispatch, effect=effect,
            verification=verification, completion=completion,
            historical=historical, current=current,
            evidence_refs=evidence_refs, overall_status=overall,
            missing_links=missing, ambiguous_links=[],
        )
