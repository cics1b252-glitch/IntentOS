"""M32B Durable Mission Authority — Package Exports."""

from __future__ import annotations

from intent_kernel.mission.mission_record import (
    MissionRecord,
    MissionDefinition,
    MissionStatus,
    ActionState,
    ActionPlanEntry,
    DurableActionState,
    DurableActionStateBuilder,
    VerificationState,
    VerificationStateRecord,
    CompletionState,
    CompletionStateRecord,
    detach_json_value,
)

from intent_kernel.mission.store import (
    MissionRecordStorePort,
    DurableCommitResult,
    MissionRecordCommitError,
    MissionRecordConflictError,
    MissionRecordNotFoundError,
    MissionRecordValidationError,
)

from intent_kernel.mission.store_impl import (
    JsonFileMissionRecordStore,
    create_json_file_mission_record_store,
)

from intent_kernel.mission.transitions import (
    ACTION_TRANSITIONS,
    RESTART_POSTURES,
    IllegalActionTransitionError,
    RestartPosture,
    is_legal_action_transition,
    require_legal_action_transition,
    restart_posture_for,
)

from intent_kernel.mission.execution_identity import (
    canonical_identity_bytes,
    compute_local_execution_identity,
    effect_identity_digest_for,
)

from intent_kernel.mission.action_authority import (
    FRESH_DETERMINISTIC,
    NOT_VERIFIED,
    REQUIRES_REVALIDATION,
    ActionTransitionError,
    ActionTransitionEvidence,
    MissionActionAuthority,
    ReplayDecision,
    RestartPostureView,
    TransitionResult,
)

from intent_kernel.mission.dispatch_guard import (
    DispatchAttemptSpec,
    DispatchGuardError,
    DispatchOwnership,
    ProductiveDispatchGuard,
    spec_for_legacy_dispatch,
    spec_for_runtime_node,
)

from intent_kernel.mission.delegation import (
    MAX_DELEGATION_DEPTH,
    DelegatedResource,
    DelegationError,
    DelegationGrant,
    DelegationState,
    capability_subset,
    confirmation_basis_for_grant,
    contract_within_grant,
    is_expired,
    lifetime_subset,
    mint_delegation_id,
    prove_edge,
    resolve_effective_ceilings,
    resolve_parent_view,
    resource_subset,
    risk_allows,
    side_effect_allows,
    target_subset,
    timeout_allows,
    verification_allows,
    verify_grant_dispatch,
    walk_chain,
)

__all__ = [
    # Models
    "MissionRecord",
    "MissionDefinition",
    "MissionStatus",
    "ActionState",
    "ActionPlanEntry",
    "DurableActionState",
    "DurableActionStateBuilder",
    "VerificationState",
    "VerificationStateRecord",
    "CompletionState",
    "CompletionStateRecord",
    "detach_json_value",
    # Store
    "MissionRecordStorePort",
    "DurableCommitResult",
    "MissionRecordCommitError",
    "MissionRecordConflictError",
    "MissionRecordNotFoundError",
    "MissionRecordValidationError",
    "JsonFileMissionRecordStore",
    "create_json_file_mission_record_store",
    # Action state machine (M32B-2)
    "ACTION_TRANSITIONS",
    "RESTART_POSTURES",
    "IllegalActionTransitionError",
    "RestartPosture",
    "is_legal_action_transition",
    "require_legal_action_transition",
    "restart_posture_for",
    "canonical_identity_bytes",
    "compute_local_execution_identity",
    "effect_identity_digest_for",
    "ActionTransitionError",
    "ActionTransitionEvidence",
    "FRESH_DETERMINISTIC",
    "NOT_VERIFIED",
    "REQUIRES_REVALIDATION",
    "DispatchAttemptSpec",
    "DispatchGuardError",
    "DispatchOwnership",
    "ProductiveDispatchGuard",
    "spec_for_legacy_dispatch",
    "spec_for_runtime_node",
    "MissionActionAuthority",
    "ReplayDecision",
    "RestartPostureView",
    "TransitionResult",
    # Governed delegation (M33.2B)
    "MAX_DELEGATION_DEPTH",
    "DelegatedResource",
    "DelegationError",
    "DelegationGrant",
    "DelegationState",
    "capability_subset",
    "confirmation_basis_for_grant",
    "contract_within_grant",
    "is_expired",
    "lifetime_subset",
    "mint_delegation_id",
    "prove_edge",
    "resolve_effective_ceilings",
    "resolve_parent_view",
    "resource_subset",
    "risk_allows",
    "side_effect_allows",
    "target_subset",
    "timeout_allows",
    "verification_allows",
    "verify_grant_dispatch",
    "walk_chain",
]