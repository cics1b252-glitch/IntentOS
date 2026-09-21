"""Mission Record — M32B Durable Mission Authority.

Canonical durable mission record for cross-process mission resume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from intent_kernel.time_utils import utc_iso


def detach_json_value(value: Any) -> Any:
    """Canonical serialization detachment at authority boundaries.

    Round-trips through canonical JSON so no caller-owned nested mutable
    object can alias canonical record state. Fails closed (ValueError) on
    non-JSON-serializable input such as Python object identities, bytes,
    sets, or NaN/Infinity — none of which may enter durable authority.
    """
    import json
    try:
        return json.loads(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"mission authority value is not JSON-detachable: {exc}"
        ) from exc


class MissionStatus(str, Enum):
    """Durable mission lifecycle states."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED_FINAL = "FAILED_FINAL"


class ActionState(str, Enum):
    """Durable action execution states."""
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DISPATCH_INTENT_RECORDED = "DISPATCH_INTENT_RECORDED"
    DISPATCHING = "DISPATCHING"
    RESULT_RECORDED = "RESULT_RECORDED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    RECONFIRMATION_REQUIRED = "RECONFIRMATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class ActionPlanEntry:
    """Immutable action plan entry for deterministic ordering."""
    action_id: str
    capability: str
    node_id: str
    dependencies: tuple[str, ...] = ()
    request_semantics_digest: str = ""
    expected_resource_id: str = ""
    expected_governed_registration_id: str = ""
    expected_resource_generation: int = 0
    expected_executor_kind: str = ""
    expected_executor_logical_id: str = ""

    def __post_init__(self) -> None:
        for label in ("action_id", "capability", "node_id",
                      "request_semantics_digest", "expected_resource_id",
                      "expected_governed_registration_id",
                      "expected_executor_kind", "expected_executor_logical_id"):
            if not isinstance(getattr(self, label), str):
                raise ValueError(f"{label} must be a string")
        if not isinstance(self.expected_resource_generation, int) or isinstance(
            self.expected_resource_generation, bool
        ):
            raise ValueError("expected_resource_generation must be an int")
        for dep in self.dependencies:
            if not isinstance(dep, str):
                raise ValueError("dependencies items must be strings")
        object.__setattr__(self, "dependencies", tuple(self.dependencies))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionPlanEntry":
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DurableActionState:
    """Durable action execution state with expected preconditions.

    provider_effect_id carries the opaque provider-supplied effect token
    (idempotency key / effect ID / transaction ID) when one exists, stored
    distinctly from the local execution identity. effect_identity_digest is
    the deterministic digest over that token ("" when absent). Neither field
    manufactures provider certainty: absent provider identity means external
    exactly-once remains unprovable. local_execution_identity persists the
    frozen MODEL E2 dispatch identity once bound ("" until first binding;
    immutable and recomputation-checked afterwards). verification_proof_digest
    pins the canonical gate proof that authorized VERIFIED, so only that
    proof's basis can later authorize action COMPLETED.

    confirmation_required identifies that a durable confirmation
    *requirement* exists for this action. confirmation_basis_digest
    identifies the requirement (not an approval token): it binds the
    requirement to the request semantics and must be re-validated after
    restart. Raw confirmation tokens, session IDs, or approval
    capability are never persisted here — they remain in-memory only.
    """
    action_id: str
    node_id: str
    state: ActionState = ActionState.PENDING
    expected_resource_id: str = ""
    expected_governed_registration_id: str = ""
    expected_resource_generation: int = 0
    expected_executor_kind: str = ""
    expected_executor_logical_id: str = ""
    result: Any = None
    verification_status: str = ""
    verification_evidence: Optional[dict[str, Any]] = None
    attempt_count: int = 0
    error_message: Optional[str] = None
    provider_effect_id: str = ""
    effect_identity_digest: str = ""
    local_execution_identity: str = ""
    verification_proof_digest: str = ""
    confirmation_required: bool = False
    confirmation_basis_digest: str = ""
    # M33.2B governed delegation: flat grant fields. Empty delegation_id
    # means "no delegation on this action" and every other delegation
    # field must then be at its default (partial grants fail closed).
    # A non-empty delegation_id carries a complete grant validated at
    # creation by MissionActionAuthority; ordinary commit() rejects any
    # delegation field change (see store _require_immutable_identity).
    delegation_id: str = ""
    delegation_parent_mission_id: str = ""
    delegation_parent_action_id: str = ""
    delegation_parent_delegation_id: str = ""
    delegation_root_mission_id: str = ""
    delegation_root_action_id: str = ""
    delegation_root_governed_registration_id: str = ""
    delegation_root_generation: int = 0
    delegation_delegator_grid: str = ""
    delegation_delegator_agent_id: str = ""
    delegation_delegate_agent_id: str = ""
    delegation_delegate_grid: str = ""
    delegation_allowed_capabilities: tuple = ()
    delegation_allowed_resources: tuple = ()
    delegation_allowed_targets: tuple = ()
    delegation_max_risk_level: str = ""
    delegation_max_timeout_seconds: float = 0.0
    delegation_require_verification: Optional[bool] = None
    delegation_max_side_effect: str = ""
    delegation_created_at: str = ""
    delegation_expires_at: str = ""
    delegation_state: str = "NONE"
    delegation_revoked_at: str = ""
    delegation_revoke_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string")
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        if not isinstance(self.state, ActionState):
            raise ValueError("state must be an ActionState")
        self._validate_delegation_fields()
        for label in ("expected_resource_id",
                      "expected_governed_registration_id",
                      "expected_executor_kind", "expected_executor_logical_id",
                      "verification_status", "provider_effect_id",
                      "effect_identity_digest", "local_execution_identity",
                      "verification_proof_digest"):
            if not isinstance(getattr(self, label), str):
                raise ValueError(f"{label} must be a string")
        if not isinstance(self.confirmation_basis_digest, str):
            raise ValueError("confirmation_basis_digest must be a string")
        if not isinstance(self.confirmation_required, bool):
            raise ValueError("confirmation_required must be a bool")
        # M32B-3 hardening: fail-closed when confirmation is
        # required but basis digest is empty or missing.
        if self.confirmation_required and (
            not self.confirmation_basis_digest
        ):
            raise ValueError(
                "confirmation_required=True requires a non-empty "
                "confirmation_basis_digest"
            )
        if not isinstance(self.expected_resource_generation, int) or isinstance(
            self.expected_resource_generation, bool
        ):
            raise ValueError("expected_resource_generation must be an int")
        if not isinstance(self.attempt_count, int) or isinstance(
            self.attempt_count, bool
        ):
            raise ValueError("attempt_count must be an int")
        if self.error_message is not None and not isinstance(
            self.error_message, str
        ):
            raise ValueError("error_message must be a string or None")
        # Detach result/evidence: non-serializable Python objects
        # (executors, services, locks, object identities) fail closed here.
        object.__setattr__(self, "result", detach_json_value(self.result))
        if self.verification_evidence is not None:
            if not isinstance(self.verification_evidence, dict):
                raise ValueError("verification_evidence must be a dict or None")
            object.__setattr__(
                self, "verification_evidence",
                detach_json_value(self.verification_evidence),
            )
        self._validate_delegation_fields()

    def _validate_delegation_fields(self) -> None:
        """M33.2B: delegation grant shape + all-or-nothing rule.

        Empty delegation_id means "no delegation": every grant field must
        then be at its default, so partial/forged grants fail closed at
        construction. A set delegation_id requires a complete grant:
        valid state, non-empty parent/delegate/capability identity, and
        well-typed scope/ceiling/lifetime fields. Subset semantics
        (child ⊆ parent) are proven by MissionActionAuthority at grant
        creation and re-proven at handoff — not here.
        """
        gid = self.delegation_id
        if not isinstance(gid, str):
            raise ValueError("delegation_id must be a string")
        str_fields = (
            "delegation_parent_mission_id",
            "delegation_parent_action_id",
            "delegation_parent_delegation_id",
            "delegation_root_mission_id",
            "delegation_root_action_id",
            "delegation_root_governed_registration_id",
            "delegation_delegator_grid",
            "delegation_delegator_agent_id",
            "delegation_delegate_agent_id",
            "delegation_delegate_grid",
            "delegation_max_risk_level",
            "delegation_max_side_effect",
            "delegation_created_at",
            "delegation_expires_at",
            "delegation_state",
            "delegation_revoked_at",
            "delegation_revoke_reason",
        )
        for label in str_fields:
            if not isinstance(getattr(self, label), str):
                raise ValueError(f"{label} must be a string")
        if not isinstance(self.delegation_root_generation, int) or isinstance(
            self.delegation_root_generation, bool
        ):
            raise ValueError("delegation_root_generation must be an int")
        if not isinstance(self.delegation_max_timeout_seconds, (int, float)) or isinstance(
            self.delegation_max_timeout_seconds, bool
        ):
            raise ValueError("delegation_max_timeout_seconds must be numeric")
        if self.delegation_require_verification is not None and not isinstance(
            self.delegation_require_verification, bool
        ):
            raise ValueError("delegation_require_verification must be a bool or None")
        # Normalize sequence fields (JSON round-trips tuples to lists).
        caps = self.delegation_allowed_capabilities or ()
        if not isinstance(caps, (tuple, list)) or not all(
            isinstance(c, str) for c in caps
        ):
            raise ValueError("delegation_allowed_capabilities must be strings")
        object.__setattr__(self, "delegation_allowed_capabilities", tuple(caps))
        targets = self.delegation_allowed_targets or ()
        if not isinstance(targets, (tuple, list)) or not all(
            isinstance(t, str) for t in targets
        ):
            raise ValueError("delegation_allowed_targets must be strings")
        object.__setattr__(self, "delegation_allowed_targets", tuple(targets))
        resources = self.delegation_allowed_resources or ()
        if not isinstance(resources, (tuple, list)):
            raise ValueError("delegation_allowed_resources must be a sequence")
        normalized = []
        for item in resources:
            if not isinstance(item, dict):
                raise ValueError(
                    "delegation_allowed_resources items must be mappings"
                )
            for key in ("resource_id", "governed_registration_id", "generation"):
                if key not in item:
                    raise ValueError(
                        "delegation_allowed_resources items must carry "
                        "resource_id, governed_registration_id, generation"
                    )
            if not isinstance(item["resource_id"], str) or not item["resource_id"].strip():
                raise ValueError("delegated resource_id must be non-empty")
            if not isinstance(item["governed_registration_id"], str):
                raise ValueError("delegated governed_registration_id must be a string")
            if not isinstance(item["generation"], int) or isinstance(item["generation"], bool):
                raise ValueError("delegated generation must be an int")
            normalized.append({
                "resource_id": item["resource_id"],
                "governed_registration_id": item["governed_registration_id"],
                "generation": item["generation"],
            })
        object.__setattr__(self, "delegation_allowed_resources", tuple(normalized))
        if self.delegation_state not in ("NONE", "ACTIVE", "REVOKED"):
            raise ValueError(
                f"delegation_state must be NONE, ACTIVE, or REVOKED, "
                f"got {self.delegation_state!r}"
            )
        if gid == "":
            # No delegation: every grant field must be at its default.
            if (
                self.delegation_parent_mission_id
                or self.delegation_parent_action_id
                or self.delegation_parent_delegation_id
                or self.delegation_root_mission_id
                or self.delegation_root_action_id
                or self.delegation_root_governed_registration_id
                or self.delegation_root_generation != 0
                or self.delegation_delegator_grid
                or self.delegation_delegator_agent_id
                or self.delegation_delegate_agent_id
                or self.delegation_delegate_grid
                or self.delegation_allowed_capabilities
                or self.delegation_allowed_resources
                or self.delegation_allowed_targets
                or self.delegation_max_risk_level
                or self.delegation_max_timeout_seconds not in (0, 0.0)
                or self.delegation_require_verification is not None
                or self.delegation_max_side_effect
                or self.delegation_created_at
                or self.delegation_expires_at
                or self.delegation_state != "NONE"
                or self.delegation_revoked_at
                or self.delegation_revoke_reason
            ):
                raise ValueError(
                    "delegation fields set without delegation_id "
                    "(partial grants fail closed)"
                )
        else:
            # Complete grant required.
            for label in (
                "delegation_parent_mission_id",
                "delegation_parent_action_id",
                "delegation_root_mission_id",
                "delegation_root_action_id",
                "delegation_delegator_grid",
                "delegation_delegate_agent_id",
            ):
                if not getattr(self, label).strip():
                    raise ValueError(
                        f"{label} must be non-empty when delegation_id is set"
                    )
            if not self.delegation_allowed_capabilities:
                raise ValueError(
                    "delegation_allowed_capabilities must be non-empty "
                    "when delegation_id is set"
                )
            if self.delegation_state not in ("ACTIVE", "REVOKED"):
                raise ValueError(
                    "delegation_state must be ACTIVE or REVOKED "
                    "when delegation_id is set"
                )
            if self.delegation_state == "REVOKED" and not self.delegation_revoked_at:
                raise ValueError(
                    "delegation_revoked_at must be set when state is REVOKED"
                )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DurableActionState":
        d = dict(data)
        d["state"] = ActionState(d["state"])
        return cls(**d)


class VerificationState(str, Enum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"
    REQUIRES_USER_VERIFICATION = "REQUIRES_USER_VERIFICATION"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class VerificationStateRecord:
    verification_status: VerificationState = VerificationState.VERIFICATION_REQUIRED
    evidence: Optional[dict[str, Any]] = None
    contract_hash: str = ""
    exact_contract_hash: str = ""
    rule_set_hash: str = ""
    external_evidence_hash: str = ""
    last_verified_at: str = ""
    freshness_fact: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.verification_status, VerificationState):
            raise ValueError("verification_status must be a VerificationState")
        for label in ("contract_hash", "exact_contract_hash", "rule_set_hash",
                      "external_evidence_hash", "last_verified_at"):
            if not isinstance(getattr(self, label), str):
                raise ValueError(f"{label} must be a string")
        if self.evidence is not None:
            if not isinstance(self.evidence, dict):
                raise ValueError("evidence must be a dict or None")
            object.__setattr__(
                self, "evidence", detach_json_value(self.evidence))
        if self.freshness_fact is not None:
            if not isinstance(self.freshness_fact, dict):
                raise ValueError("freshness_fact must be a dict or None")
            object.__setattr__(
                self, "freshness_fact",
                detach_json_value(self.freshness_fact))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verification_status"] = self.verification_status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerificationStateRecord":
        d = dict(data)
        d["verification_status"] = VerificationState(d["verification_status"])
        return cls(**d)


class CompletionState(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CompletionStateRecord:
    completion_state: CompletionState = CompletionState.PENDING
    completion_authority: str = ""
    completion_evidence: tuple[dict[str, Any], ...] = ()
    freshness_facts: tuple[dict[str, Any], ...] = ()
    completed_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.completion_state, CompletionState):
            raise ValueError("completion_state must be a CompletionState")
        if not isinstance(self.completion_authority, str):
            raise ValueError("completion_authority must be a string")
        if not isinstance(self.completed_at, str):
            raise ValueError("completed_at must be a string")
        for label in ("completion_evidence", "freshness_facts"):
            items = getattr(self, label)
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"{label} items must be dicts")
            object.__setattr__(
                self, label, tuple(detach_json_value(i) for i in items))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["completion_state"] = self.completion_state.value
        d["completion_evidence"] = list(self.completion_evidence)
        d["freshness_facts"] = list(self.freshness_facts)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompletionStateRecord":
        d = dict(data)
        d["completion_state"] = CompletionState(d["completion_state"])
        d["completion_evidence"] = tuple(d.get("completion_evidence", []))
        d["freshness_facts"] = tuple(d.get("freshness_facts", []))
        return cls(**d)


@dataclass(frozen=True, slots=True)
class MissionDefinition:
    """Immutable mission definition for deterministic digest."""
    objective: str
    context: dict[str, Any] = field(default_factory=dict)
    success_criteria: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("objective must be a non-empty string")
        if not isinstance(self.context, dict):
            raise ValueError("context must be a dict")
        object.__setattr__(self, "context", detach_json_value(self.context))
        for label in ("success_criteria", "scope"):
            for item in getattr(self, label):
                if not isinstance(item, str):
                    raise ValueError(f"{label} items must be strings")
            object.__setattr__(self, label, tuple(getattr(self, label)))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["context"] = dict(self.context)
        d["success_criteria"] = list(self.success_criteria)
        d["scope"] = list(self.scope)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionDefinition":
        d = dict(data)
        d["context"] = dict(d.get("context", {}))
        d["success_criteria"] = tuple(d.get("success_criteria", []))
        d["scope"] = tuple(d.get("scope", []))
        return cls(**d)


@dataclass(frozen=True, slots=True)
class MissionRecord:
    """Durable MissionRecord — canonical authority for mission state."""
    schema_version: int = 1
    installation_id: str = ""
    revision: int = 1
    mission_id: str = ""
    runtime_id: str = ""
    mission_definition_digest: str = ""
    mission_definition: Optional[MissionDefinition] = None
    mission_status: MissionStatus = MissionStatus.CREATED
    plan: tuple[dict[str, Any], ...] = ()
    action_states: dict[str, DurableActionState] = field(default_factory=dict)
    completed_nodes: tuple[str, ...] = ()
    failed_nodes: tuple[str, ...] = ()
    verification_state: dict[str, VerificationStateRecord] = field(default_factory=dict)
    completion_state: CompletionStateRecord = field(default_factory=CompletionStateRecord)
    created_at: str = field(default_factory=utc_iso)
    updated_at: str = field(default_factory=utc_iso)

    def __post_init__(self) -> None:
        if not self.mission_id:
            raise ValueError("mission_id must not be empty")
        if not self.installation_id:
            raise ValueError("installation_id must not be empty")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        if not isinstance(self.mission_status, MissionStatus):
            raise ValueError("mission_status must be a MissionStatus")
        if not isinstance(self.mission_definition_digest, str):
            raise ValueError("mission_definition_digest must be a string")
        for label in ("runtime_id", "created_at", "updated_at"):
            if not isinstance(getattr(self, label), str):
                raise ValueError(f"{label} must be a string")
        # Deep-detach every mutable container so retained caller-owned nested
        # objects can never mutate canonical record authority after validation.
        for entry in self.plan:
            if not isinstance(entry, dict):
                raise ValueError("plan entries must be dicts")
        object.__setattr__(
            self, "plan",
            tuple(detach_json_value(e) for e in self.plan),
        )
        detached_states = {}
        for key, state in self.action_states.items():
            if not isinstance(state, DurableActionState):
                raise ValueError("action_states values must be DurableActionState")
            detached_states[key] = DurableActionState.from_dict(
                detach_json_value(state.to_dict())
            )
        object.__setattr__(self, "action_states", detached_states)
        for label in ("completed_nodes", "failed_nodes"):
            nodes = getattr(self, label)
            for node in nodes:
                if not isinstance(node, str):
                    raise ValueError(f"{label} items must be strings")
            object.__setattr__(self, label, tuple(nodes))
        detached_verification = {}
        for key, record in self.verification_state.items():
            if not isinstance(record, VerificationStateRecord):
                raise ValueError(
                    "verification_state values must be VerificationStateRecord"
                )
            detached_verification[key] = VerificationStateRecord.from_dict(
                detach_json_value(record.to_dict())
            )
        object.__setattr__(self, "verification_state", detached_verification)
        if not isinstance(self.completion_state, CompletionStateRecord):
            raise ValueError("completion_state must be a CompletionStateRecord")
        object.__setattr__(
            self, "completion_state",
            CompletionStateRecord.from_dict(
                detach_json_value(self.completion_state.to_dict())
            ),
        )
        if self.mission_definition is not None:
            if not isinstance(self.mission_definition, MissionDefinition):
                raise ValueError(
                    "mission_definition must be a MissionDefinition or None"
                )
            object.__setattr__(
                self, "mission_definition",
                MissionDefinition.from_dict(
                    detach_json_value(self.mission_definition.to_dict())
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        d = {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "revision": self.revision,
            "mission_id": self.mission_id,
            "runtime_id": self.runtime_id,
            "mission_definition_digest": self.mission_definition_digest,
            "mission_status": self.mission_status.value,
            "plan": list(self.plan),
            "action_states": {k: v.to_dict() for k, v in self.action_states.items()},
            "completed_nodes": list(self.completed_nodes),
            "failed_nodes": list(self.failed_nodes),
            "verification_state": {k: v.to_dict() for k, v in self.verification_state.items()},
            "completion_state": self.completion_state.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.mission_definition:
            d["mission_definition"] = self.mission_definition.to_dict()
        # Detach nested leaves: mutating serialized output must never reach
        # the canonical record.
        return detach_json_value(d)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionRecord":
        d = dict(data)
        d["mission_status"] = MissionStatus(d["mission_status"])
        d["plan"] = tuple(d.get("plan", []))
        d["action_states"] = {k: DurableActionState.from_dict(v) for k, v in d.get("action_states", {}).items()}
        d["completed_nodes"] = tuple(d.get("completed_nodes", []))
        d["failed_nodes"] = tuple(d.get("failed_nodes", []))
        d["verification_state"] = {k: VerificationStateRecord.from_dict(v) for k, v in d.get("verification_state", {}).items()}
        d["completion_state"] = CompletionStateRecord.from_dict(d.get("completion_state", {}))
        if "mission_definition" in d and d["mission_definition"]:
            d["mission_definition"] = MissionDefinition.from_dict(d["mission_definition"])
        return cls(**d)

    def compute_definition_digest(self) -> str:
        """Compute deterministic SHA-256 digest of mission definition."""
        import hashlib
        import json
        if self.mission_definition:
            canonical = json.dumps(
                self.mission_definition.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ""


# --- M32B Action State Machine Types ---

class DurableActionStateBuilder:
    """Helper to build DurableActionState with expected preconditions."""

    @staticmethod
    def create_pending(action_id: str, node_id: str) -> "DurableActionState":
        return DurableActionState(action_id=action_id, node_id=node_id, state=ActionState.PENDING)

    @staticmethod
    def create_authorized(action_id: str, node_id: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.AUTHORIZED,
            **preconditions
        )

    @staticmethod
    def create_dispatch_intent_recorded(action_id: str, node_id: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.DISPATCH_INTENT_RECORDED,
            **preconditions
        )

    @staticmethod
    def create_dispatching(action_id: str, node_id: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.DISPATCHING,
            **preconditions
        )

    @staticmethod
    def create_result_recorded(action_id: str, node_id: str, result: Any, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.RESULT_RECORDED,
            result=result,
            **preconditions
        )

    @staticmethod
    def create_verification_required(action_id: str, node_id: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.VERIFICATION_REQUIRED,
            **preconditions
        )

    @staticmethod
    def create_verified(action_id: str, node_id: str, result: Any, verification_status: str, evidence: Optional[dict] = None, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.VERIFIED,
            result=result,
            verification_status=verification_status,
            verification_evidence=evidence,
            **preconditions
        )

    @staticmethod
    def create_completed(action_id: str, node_id: str, result: Any, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.COMPLETED,
            result=result,
            **preconditions
        )

    @staticmethod
    def create_failed(action_id: str, node_id: str, error: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.FAILED,
            error_message=error,
            **preconditions
        )

    @staticmethod
    def create_ambiguous_effect(action_id: str, node_id: str, result: Any, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.AMBIGUOUS_EFFECT,
            result=result,
            **preconditions
        )

    @staticmethod
    def create_reconfirmation_required(action_id: str, node_id: str, **preconditions) -> "DurableActionState":
        return DurableActionState(
            action_id=action_id,
            node_id=node_id,
            state=ActionState.RECONFIRMATION_REQUIRED,
            **preconditions
        )