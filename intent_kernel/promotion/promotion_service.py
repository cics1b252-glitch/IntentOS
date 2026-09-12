"""Movement 17 — Governed Resource Promotion Service.

Orchestrates the full governed promotion pipeline:

  DISCOVERY EVIDENCE
  → PROPOSAL
  → TYPED DECISION
  → TOCTOU REVALIDATION
  → CANONICAL REGISTRATION
  → RRM

No stage may impersonate another.
"""

from __future__ import annotations

from intent_kernel.discovery.service import CanonicalResourceDiscoveryService
from intent_kernel.promotion.decision_authority import ResourcePromotionDecisionAuthority
from intent_kernel.promotion.models import (
    ResourcePromotionDecisionType,
    ResourcePromotionResult,
)
from intent_kernel.promotion.proposal_service import (
    PromotionError,
    ResourcePromotionProposalService,
)
from intent_kernel.promotion.registration_boundary import (
    CanonicalPromotionRegistrationBoundary,
)


class BootstrapGovernanceError(Exception):
    """M31.3B-1B — raised when the canonical build's bootstrap first-governance
    gate fails (any declaration did not end governed and verified)."""


class CanonicalResourcePromotionService:
    """Orchestrates the governed promotion pipeline.

    ORCHESTRATION_ONLY — delegates to sub-services; contains no
    independent mutation logic.
    """

    def __init__(
        self,
        discovery_service: CanonicalResourceDiscoveryService,
        rrm: object,
    ) -> None:
        self._discovery = discovery_service
        self._rrm = rrm
        self._proposal_service = ResourcePromotionProposalService(discovery_service)
        self._decision_authority = ResourcePromotionDecisionAuthority(
            self._proposal_service,
        )
        self._registration_boundary = CanonicalPromotionRegistrationBoundary(
            self._proposal_service,
            self._decision_authority,
            rrm,
        )

    # ------------------------------------------------------------------
    # Sub-service accessors (read-only)
    # ------------------------------------------------------------------

    @property
    def proposals(self) -> ResourcePromotionProposalService:
        return self._proposal_service

    @property
    def decisions(self) -> ResourcePromotionDecisionAuthority:
        return self._decision_authority

    @property
    def registration(self) -> CanonicalPromotionRegistrationBoundary:
        return self._registration_boundary

    # ------------------------------------------------------------------
    # Convenience entry points
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        discovery_id: str,
        *,
        requested_scope: str = "global",
        reasoning: str = "",
        metadata: dict[str, object] | None = None,
    ):
        """Create a promotion proposal from discovery evidence."""
        return self._proposal_service.create_proposal(
            discovery_id,
            requested_scope=requested_scope,
            reasoning=reasoning,
            metadata=metadata,
        )

    def decide_proposal(
        self,
        proposal_id: str,
        decision_type: ResourcePromotionDecisionType,
        *,
        decided_by: str = "system",
        reasoning: str = "",
    ):
        """Make a typed decision on a proposal."""
        return self._decision_authority.decide(
            proposal_id,
            decision_type,
            decided_by=decided_by,
            reasoning=reasoning,
        )

    def promote(
        self,
        proposal_id: str,
        decision_id: str,
        *,
        fresh: bool = True,
    ) -> ResourcePromotionResult:
        """Full promotion: validate proposal + decision, register in RRM."""
        return self._registration_boundary.register(
            proposal_id,
            decision_id,
            fresh=fresh,
        )

    def bootstrap_govern(
        self,
        declarations: list[Any],
        *,
        decided_by: str = "bootstrap",
        reasoning: str = "",
    ) -> Any:
        """M31.3B-1B — govern every declared built-in pre-governed resource.

        Single pipeline per declaration (single source: the canonical
        capability registry):

            detached pre-governed snapshot (must exist, ungoverned lineage,
            valid pre-governed generation) → deterministic OBSERVED evidence
            → proposal → bootstrap approval (decide_bootstrap, caller-bound
            precondition) → boundary govern_existing (RRM atomic first
            governance) → verified entry.

        ``declarations`` carry NO generation: the observed pre-governed
        generation is derived from each detached RRM snapshot. The report's
        ``success`` is True ONLY when every entry governed AND the detached
        post-governance verification pass confirms each governed lineage and
        non-terminal lifecycle.
        """
        from uuid import uuid4

        from intent_kernel.discovery.models import (
            ResourceDiscoveryEvidence,
            ResourceDiscoveryStatus,
        )
        from intent_kernel.promotion.models import (
            BootstrapGovernanceEntry,
            BootstrapGovernanceReport,
        )
        from intent_kernel.rrm.models import ResourceStatus

        entries: list[BootstrapGovernanceEntry] = []
        overall = True

        def _failed(
            declaration: Any, reason: str
        ) -> BootstrapGovernanceEntry:
            return BootstrapGovernanceEntry(
                resource_kind=declaration.resource_kind,
                resource_id=declaration.resource_id,
                capability_name=declaration.capability_name,
                executor_kind=declaration.executor_kind,
                executor_id=declaration.executor_id,
                success=False,
                reason=reason,
            )

        for declaration in declarations:
            resource = self._snapshot(
                declaration.resource_kind,
                declaration.resource_id,
            )
            if resource is None:
                entries.append(_failed(declaration, "resource_not_found"))
                overall = False
                continue
            active_grid = (
                getattr(resource, "governed_registration_id", "") or ""
            )
            if active_grid:
                restart = self._recognize_restart_reconciliation(
                    declaration, resource, active_grid
                )
                if restart is not None:
                    # M32B-1 CASE B — valid durable restart reconciliation.
                    # The declaration is ALREADY SATISFIED BY DURABLE
                    # AUTHORITY: no mint, no govern_existing call, no
                    # generation advance, no durable commit, no new fact, no
                    # consumption, no replacement grid. Outcome reports
                    # reconciliation, never a new governance event.
                    entries.append(
                        BootstrapGovernanceEntry(
                            resource_kind=declaration.resource_kind,
                            resource_id=declaration.resource_id,
                            capability_name=declaration.capability_name,
                            executor_kind=declaration.executor_kind,
                            executor_id=declaration.executor_id,
                            success=True,
                            outcome="restart_reconciled",
                            governed_registration_id=(
                                restart.governed_registration_id
                            ),
                            resulting_generation=restart.generation,
                        )
                    )
                    continue
                entries.append(_failed(declaration, "already_governed"))
                overall = False
                continue
            gen = getattr(resource, "generation", 0)
            if not self._valid_generation(gen):
                entries.append(
                    _failed(declaration, "invalid_pre_governed_generation")
                )
                overall = False
                continue
            if getattr(resource, "status", None) in (
                ResourceStatus.ARCHIVED,
                ResourceStatus.UNINSTALLED,
            ):
                entries.append(_failed(declaration, "terminal_state"))
                overall = False
                continue

            discovery_id = f"boot-{uuid4().hex}"
            evidence = ResourceDiscoveryEvidence(
                discovery_id=discovery_id,
                resource_kind=declaration.discovery_kind,
                resource_id=declaration.resource_id,
                display_name=declaration.resource_id,
                source="bootstrap",
                source_type="canonical_build",
                observed_by="system",
                status=ResourceDiscoveryStatus.OBSERVED,
                confidence=1.0,
            )
            if not self._discovery.registry.add(evidence):
                entries.append(_failed(declaration, "evidence_duplicate"))
                overall = False
                continue

            proposal = self._proposal_service.create_proposal(
                discovery_id,
                reasoning=reasoning,
                metadata={"provenance": "bootstrap_first_governance"},
            )

            try:
                decision = self._decision_authority.decide_bootstrap(
                    declaration=declaration,
                    evidence=evidence,
                    proposal_id=proposal.proposal_id,
                    observed_pre_governed_generation=gen,
                    decided_by=decided_by,
                    reasoning=reasoning,
                )
                result = self._registration_boundary.govern_existing(
                    proposal.proposal_id,
                    decision.decision_id,
                    fresh=True,
                )
            except Exception as exc:  # noqa: BLE001 — fail closed per declaration
                entries.append(
                    _failed(declaration, f"error:{type(exc).__name__}")
                )
                overall = False
                continue

            if not result.success:
                entries.append(
                    _failed(declaration, result.reason or "first_governance_failed")
                )
                overall = False
                continue

            entries.append(
                BootstrapGovernanceEntry(
                    resource_kind=declaration.resource_kind,
                    resource_id=declaration.resource_id,
                    capability_name=declaration.capability_name,
                    executor_kind=declaration.executor_kind,
                    executor_id=declaration.executor_id,
                    success=True,
                    outcome=result.reason,
                    governed_registration_id=(
                        result.governed_registration_id or ""
                    ),
                    resulting_generation=result.observed_generation or 0,
                )
            )

        # Detached post-governance verification pass.
        verified = overall
        if verified:
            for entry in entries:
                res = self._snapshot(entry.resource_kind, entry.resource_id)
                ok = (
                    res is not None
                    and bool(
                        getattr(res, "governed_registration_id", "") or ""
                    )
                    and self._valid_generation(getattr(res, "generation", 0))
                    and getattr(res, "status", None)
                    not in (
                        ResourceStatus.ARCHIVED,
                        ResourceStatus.UNINSTALLED,
                    )
                )
                if not ok:
                    verified = False
                    break

        pass_ok = bool(overall and verified)
        return BootstrapGovernanceReport(
            success=pass_ok,
            entries=tuple(entries),
            verified=verified,
            reason=(
                ""
                if pass_ok
                else "bootstrap_governance_failed"
            ),
        )

    # ------------------------------------------------------------------
    # Private bootstrap helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _valid_generation(value: Any) -> bool:
        from intent_kernel.rrm.generation import is_valid_generation
        return is_valid_generation(value)

    def _snapshot(self, resource_kind: Any, resource_id: str) -> Any | None:
        from intent_kernel.rrm.models import ResourceType

        getters = {
            ResourceType.CAPABILITY: getattr(self._rrm, "get_capability", None),
            ResourceType.AGENT: getattr(self._rrm, "get_agent", None),
            ResourceType.PROVIDER: getattr(self._rrm, "get_provider", None),
        }
        getter = getters.get(resource_kind)
        if getter is None:
            return None
        return getter(resource_id)

    def _recognize_restart_reconciliation(
        self, declaration: Any, resource: Any, active_grid: str
    ) -> Any | None:
        """M32B-1 — recognize a valid durable restart reconciliation.

        Returns the RRM-issued FirstGovernanceRestartEvidence when the live
        governed identity is fully explained by durable M32A authority, else
        None (caller keeps existing fail-closed already_governed behavior).

        READ-ONLY: no discovery, no proposal, no decision, no boundary call,
        no mint, no commit. Declaration/executor binding compatibility mirrors
        the canonical binding check (executor_kind must match; executor_id
        must match when the snapshot carries one). Cross-process
        proposal/decision equality is never required.
        """
        query = getattr(
            self._rrm, "get_first_governance_restart_evidence", None
        )
        if query is None:
            return None
        try:
            evidence = query(
                declaration.resource_kind,
                declaration.resource_id,
                observed_governed_registration_id=active_grid,
                observed_generation=getattr(resource, "generation", 0),
                observed_status=getattr(resource, "status", ""),
            )
        except Exception:  # noqa: BLE001 — fail closed per declaration
            return None
        if evidence is None:
            return None
        metadata = getattr(resource, "metadata", None) or {}
        try:
            meta_kind = metadata.get("executor_kind")
            meta_executor = metadata.get("executor_id", None)
        except AttributeError:
            return None
        if meta_kind != declaration.executor_kind:
            return None
        if meta_executor is not None and meta_executor != declaration.executor_id:
            return None
        return evidence
