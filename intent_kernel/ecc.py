"""Executive Cognitive Controller (ECC) — RFC-0011.

Primary executive supervisor that coordinates the cognitive pipeline:
User Input -> IUE -> CDM -> CPE -> COR -> Mission Runtime (Future).

Enforces quality gates, policy constraints, cost thresholds, and failure recovery
without invoking LLMs, external APIs, or executing real-world side-effects directly.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from intent_kernel.iue import IntentUnderstandingEngine, StructuredIntent
from intent_kernel.cdm import CognitiveDialogueManager, DialogueDecision, DialogueState
from intent_kernel.cpe import CognitivePlanningEngine, ExecutionPlan
from intent_kernel.cor import CapabilityOrchestrator, ExecutionGraph, RegistryCatalog
from intent_kernel.time_utils import utc_iso


class CognitiveState(str, Enum):
    """Pipeline execution states managed by ECC."""
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    WAITING_CONTEXT = "WAITING_CONTEXT"
    READY_FOR_DIALOGUE = "READY_FOR_DIALOGUE"
    READY_FOR_PLANNING = "READY_FOR_PLANNING"
    READY_FOR_ORCHESTRATION = "READY_FOR_ORCHESTRATION"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    EXECUTION_BLOCKED = "EXECUTION_BLOCKED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    FAILED = "FAILED"
    REPLANNING = "REPLANNING"
    REORCHESTRATING = "REORCHESTRATING"
    RECOVERING = "RECOVERING"


class ExecutiveAction(str, Enum):
    """Decision actions taken by the ECC Decision Engine."""
    CONTINUE = "CONTINUE"
    RETURN = "RETURN"
    RETRY = "RETRY"
    ASK_USER = "ASK_USER"
    BLOCK = "BLOCK"
    FAIL = "FAIL"
    REPLAN = "REPLAN"
    REORCHESTRATE = "REORCHESTRATE"
    ABORT = "ABORT"


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal transition between CognitiveStates is attempted."""
    pass


class CognitiveStateMachine:
    """Enforces legal state transition matrix in the ECC cognitive pipeline."""

    LEGAL_TRANSITIONS: Dict[CognitiveState, List[CognitiveState]] = {
        CognitiveState.RECEIVED: [
            CognitiveState.UNDERSTANDING,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.UNDERSTANDING: [
            CognitiveState.WAITING_CONTEXT,
            CognitiveState.READY_FOR_DIALOGUE,
            CognitiveState.READY_FOR_PLANNING,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.READY_FOR_DIALOGUE: [
            CognitiveState.WAITING_CONTEXT,
            CognitiveState.READY_FOR_PLANNING,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.WAITING_CONTEXT: [
            CognitiveState.UNDERSTANDING,
            CognitiveState.READY_FOR_DIALOGUE,
            CognitiveState.READY_FOR_PLANNING,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.READY_FOR_PLANNING: [
            CognitiveState.REPLANNING,
            CognitiveState.READY_FOR_ORCHESTRATION,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.REPLANNING: [
            CognitiveState.READY_FOR_PLANNING,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.READY_FOR_ORCHESTRATION: [
            CognitiveState.REORCHESTRATING,
            CognitiveState.RECOVERING,
            CognitiveState.READY_FOR_EXECUTION,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.REORCHESTRATING: [
            CognitiveState.READY_FOR_ORCHESTRATION,
            CognitiveState.READY_FOR_EXECUTION,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.RECOVERING: [
            CognitiveState.READY_FOR_ORCHESTRATION,
            CognitiveState.READY_FOR_EXECUTION,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.READY_FOR_EXECUTION: [
            CognitiveState.EXECUTION_COMPLETED,
            CognitiveState.EXECUTION_BLOCKED,
            CognitiveState.FAILED,
        ],
        CognitiveState.EXECUTION_BLOCKED: [],
        CognitiveState.EXECUTION_COMPLETED: [],
        CognitiveState.FAILED: [],
    }

    @classmethod
    def is_transition_valid(cls, from_state: CognitiveState, to_state: CognitiveState) -> bool:
        if from_state == to_state:
            return True
        allowed = cls.LEGAL_TRANSITIONS.get(from_state, [])
        return to_state in allowed

    @classmethod
    def validate_transition(cls, from_state: CognitiveState, to_state: CognitiveState) -> None:
        if not cls.is_transition_valid(from_state, to_state):
            raise InvalidStateTransitionError(
                f"Transição de estado inválida no ECC: {from_state.value} -> {to_state.value}"
            )


class PolicyProvenance(str, Enum):
    """Provenance origin for executive policies (RFC-0011.1)."""
    CONSTITUTION = "constitution"
    SYSTEM_DEFAULT = "system_default"
    USER_PREFERENCE = "user_preference"
    ORGANIZATION_POLICY = "organization_policy"
    MISSION_POLICY = "mission_policy"
    ENVIRONMENT_POLICY = "environment_policy"


@dataclass
class ExecutiveQualityPolicy:
    """Consolidated cognitive quality thresholds for ECC supervision (RFC-0011.1)."""
    profile_id: str = "standard"  # low_risk, standard, high_risk, critical
    min_iqi: float = 0.60
    min_pqi: float = 0.60
    min_orchestration_confidence: float = 0.60
    max_dialogue_iterations: int = 3
    max_planning_iterations: int = 2
    max_orchestration_iterations: int = 2
    max_recovery_attempts: int = 2
    confidence_floor: float = 0.40
    validation_requirements: List[str] = field(default_factory=list)
    provenance: PolicyProvenance = PolicyProvenance.SYSTEM_DEFAULT

    @property
    def risk_profile(self) -> str:
        return self.profile_id

    @risk_profile.setter
    def risk_profile(self, val: str) -> None:
        self.profile_id = val

    @property
    def max_replans(self) -> int:
        return self.max_planning_iterations

    @property
    def max_reorchestrations(self) -> int:
        return self.max_orchestration_iterations

    @classmethod
    def from_risk_profile(cls, profile: str = "standard", **overrides: Any) -> "ExecutiveQualityPolicy":
        prof = (profile or "standard").lower().strip()
        if prof in ("low_risk", "low"):
            defaults = {
                "profile_id": "low_risk",
                "min_iqi": 0.40,
                "min_pqi": 0.50,
                "min_orchestration_confidence": 0.50,
                "max_dialogue_iterations": 2,
                "max_planning_iterations": 1,
                "max_orchestration_iterations": 1,
                "max_recovery_attempts": 1,
                "confidence_floor": 0.30,
            }
        elif prof in ("high_risk", "high"):
            defaults = {
                "profile_id": "high_risk",
                "min_iqi": 0.75,
                "min_pqi": 0.75,
                "min_orchestration_confidence": 0.75,
                "max_dialogue_iterations": 3,
                "max_planning_iterations": 2,
                "max_orchestration_iterations": 2,
                "max_recovery_attempts": 3,
                "confidence_floor": 0.60,
            }
        elif prof in ("critical", "crit"):
            defaults = {
                "profile_id": "critical",
                "min_iqi": 0.85,
                "min_pqi": 0.85,
                "min_orchestration_confidence": 0.85,
                "max_dialogue_iterations": 3,
                "max_planning_iterations": 3,
                "max_orchestration_iterations": 3,
                "max_recovery_attempts": 3,
                "confidence_floor": 0.75,
            }
        else:  # "standard"
            defaults = {
                "profile_id": "standard",
                "min_iqi": 0.60,
                "min_pqi": 0.60,
                "min_orchestration_confidence": 0.60,
                "max_dialogue_iterations": 3,
                "max_planning_iterations": 2,
                "max_orchestration_iterations": 2,
                "max_recovery_attempts": 2,
                "confidence_floor": 0.40,
            }
        defaults.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**defaults)


@dataclass
class ExecutiveExecutionPolicy:
    """Execution constraints for ECC pipeline supervision (RFC-0011.1)."""
    policy_id: str = "default_execution_policy"
    max_cost: float = 1.0  # Normalized cost threshold
    max_latency: float = 60.0  # Maximum latency in seconds
    internet_allowed: bool = True
    external_tools_allowed: bool = True
    local_execution_allowed: bool = True
    cloud_execution_allowed: bool = True
    remote_execution_allowed: bool = True
    memory_access_allowed: bool = True
    external_side_effects_allowed: bool = False
    confirmation_required_for_external_effects: bool = True
    provider_constraints: List[str] = field(default_factory=list)
    account_constraints: List[str] = field(default_factory=list)
    privacy_requirements: str = "standard"  # standard, high, strict
    data_residency: Optional[str] = None
    offline_required: bool = False
    preferred_execution_environment: Optional[str] = None
    forbidden_execution_environments: List[str] = field(default_factory=list)
    provenance: PolicyProvenance = PolicyProvenance.SYSTEM_DEFAULT

    @classmethod
    def from_preset(cls, preset_id: str = "default", **overrides: Any) -> "ExecutiveExecutionPolicy":
        pid = (preset_id or "default").lower().strip()
        if pid in ("offline_only", "airgapped", "offline"):
            defaults = {
                "policy_id": "offline_execution_policy",
                "offline_required": True,
                "internet_allowed": False,
                "cloud_execution_allowed": False,
                "external_side_effects_allowed": False,
                "provenance": PolicyProvenance.ENVIRONMENT_POLICY,
            }
        elif pid in ("high_privacy", "strict_privacy"):
            defaults = {
                "policy_id": "high_privacy_policy",
                "privacy_requirements": "high",
                "cloud_execution_allowed": False,
                "external_side_effects_allowed": False,
                "provenance": PolicyProvenance.ORGANIZATION_POLICY,
            }
        elif pid in ("restricted", "sandboxed"):
            defaults = {
                "policy_id": "restricted_policy",
                "external_tools_allowed": False,
                "external_side_effects_allowed": False,
                "max_cost": 0.5,
                "max_latency": 30.0,
                "provenance": PolicyProvenance.USER_PREFERENCE,
            }
        else:  # "default"
            defaults = {
                "policy_id": "default_execution_policy",
                "max_cost": 1.0,
                "max_latency": 60.0,
                "internet_allowed": True,
                "external_tools_allowed": True,
                "local_execution_allowed": True,
                "cloud_execution_allowed": True,
                "remote_execution_allowed": True,
                "provenance": PolicyProvenance.SYSTEM_DEFAULT,
            }
        defaults.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**defaults)


@dataclass
class ExecutiveDecisionRule:
    """Declarative decision rule for ECC state machine evaluation (RFC-0011.1)."""
    rule_id: str
    priority: int  # Priority number (lower number = higher precedence)
    precedence_tier: str  # 1_CONSTITUTION, 2_EXECUTION_POLICY, 3_INVALID_STATE, 4_QUALITY_POLICY, 5_RECOVERY_LIMITS, 6_COST_LATENCY, 7_NORMAL_CONTINUATION
    condition: Any  # Callable[[Dict[str, Any]], bool]
    source: str  # Module source e.g. "Constitution", "ExecutionPolicy", "QualityPolicy", "StateMachine"
    action: ExecutiveAction
    next_state: CognitiveState
    policy_reference: str
    reason_template: str
    enabled: bool = True

    def evaluate(self, ctx: Dict[str, Any]) -> Optional["ExecutiveDecision"]:
        if not self.enabled:
            return None
        try:
            matched = self.condition(ctx) if callable(self.condition) else bool(self.condition)
            if matched:
                reason = self.reason_template.format(**ctx) if "{" in self.reason_template else self.reason_template
                return ExecutiveDecision(
                    decision_id=f"dec_rule_{self.rule_id}",
                    action=self.action,
                    reason=reason,
                    source_module=self.source,
                    current_state=ctx.get("current_state", CognitiveState.RECEIVED),
                    next_state=self.next_state,
                    policy_reference=self.policy_reference,
                    confidence=1.0,
                )
        except Exception:
            return None
        return None


class ExecutiveDecisionTable:
    """Declarative decision engine establishing strict decision precedence for ECC (RFC-0011.1).
    
    Precedence Order:
    1. Constitution / Safety
    2. ExecutionPolicy hard blocks
    3. Invalid State
    4. QualityPolicy (IQI, PQI, CDM questions)
    5. Recovery limits (max dialogue, max replans, max reorchestrations)
    6. Cost / Latency constraints
    7. Normal continuation
    """

    def __init__(self, rules: Optional[List[ExecutiveDecisionRule]] = None):
        self.rules: List[ExecutiveDecisionRule] = rules if rules is not None else self._build_default_rules()

    def add_rule(self, rule: ExecutiveDecisionRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional["ExecutiveDecision"]:
        for rule in sorted(self.rules, key=lambda r: r.priority):
            dec = rule.evaluate(ctx)
            if dec is not None:
                return dec
        return None

    def _build_default_rules(self) -> List[ExecutiveDecisionRule]:
        return [
            # Tier 1: Constitution / Safety
            ExecutiveDecisionRule(
                rule_id="tier1_constitution_violation",
                priority=10,
                precedence_tier="1_CONSTITUTION",
                condition=lambda c: c.get("constitution_denied", False),
                source="Constitution",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="constitution",
                reason_template="Bloqueio Constitucional: {constitution_reason}",
            ),
            ExecutiveDecisionRule(
                rule_id="tier1_safety_pattern_violation",
                priority=11,
                precedence_tier="1_CONSTITUTION",
                condition=lambda c: any(bad in str(c.get("raw_input", "")).lower() for bad in ["bypass_security", "exfiltrate_keys", "rm -rf /"]),
                source="Constitution",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="constitution",
                reason_template="Bloqueio de Política de Segurança: Comando violou a Constituição do Kernel.",
            ),

            # Tier 2: ExecutionPolicy hard blocks
            ExecutiveDecisionRule(
                rule_id="tier2_execution_blocked_flag",
                priority=20,
                precedence_tier="2_EXECUTION_POLICY",
                condition=lambda c: c.get("block_execution", False) or "block_execution" in c.get("policies", []),
                source="ExecutionPolicy",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="execution_policy",
                reason_template="Bloqueio de Política: Execução desabilitada por configuração de política de segurança.",
            ),
            ExecutiveDecisionRule(
                rule_id="tier2_offline_required_violation",
                priority=21,
                precedence_tier="2_EXECUTION_POLICY",
                condition=lambda c: c.get("offline_required", False) and c.get("environment_network_access", False),
                source="ExecutionPolicy",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="execution_policy",
                reason_template="Bloqueio de Execução: Requisitado ambiente offline, mas o ambiente selecionado possui acesso à rede.",
            ),

            # Tier 4: QualityPolicy
            ExecutiveDecisionRule(
                rule_id="tier4_iqi_insufficient",
                priority=40,
                precedence_tier="4_QUALITY_POLICY",
                condition=lambda c: c.get("iqi_failed", False),
                source="QualityPolicy",
                action=ExecutiveAction.ASK_USER,
                next_state=CognitiveState.WAITING_CONTEXT,
                policy_reference="quality_policy",
                reason_template="{iqi_reason}",
            ),
            ExecutiveDecisionRule(
                rule_id="tier4_cdm_question_required",
                priority=41,
                precedence_tier="4_QUALITY_POLICY",
                condition=lambda c: c.get("cdm_failed", False),
                source="QualityPolicy",
                action=ExecutiveAction.ASK_USER,
                next_state=CognitiveState.WAITING_CONTEXT,
                policy_reference="quality_policy",
                reason_template="{cdm_reason}",
            ),
            ExecutiveDecisionRule(
                rule_id="tier4_pqi_insufficient",
                priority=42,
                precedence_tier="4_QUALITY_POLICY",
                condition=lambda c: c.get("pqi_failed", False) and c.get("replans", 0) < c.get("max_replans", 2),
                source="QualityPolicy",
                action=ExecutiveAction.REPLAN,
                next_state=CognitiveState.REPLANNING,
                policy_reference="quality_policy",
                reason_template="{pqi_reason}",
            ),

            # Tier 5: Recovery Limits
            ExecutiveDecisionRule(
                rule_id="tier5_dialogue_limit_exceeded",
                priority=50,
                precedence_tier="5_RECOVERY_LIMITS",
                condition=lambda c: c.get("dialogue_iterations", 0) > c.get("max_dialogue_iterations", 3),
                source="RecoveryLimits",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="quality_policy",
                reason_template="Limite de iterações de diálogo excedido ({dialogue_iterations} > max {max_dialogue_iterations}).",
            ),
            ExecutiveDecisionRule(
                rule_id="tier5_replan_limit_exceeded",
                priority=51,
                precedence_tier="5_RECOVERY_LIMITS",
                condition=lambda c: c.get("pqi_failed", False) and c.get("replans", 0) >= c.get("max_replans", 2),
                source="RecoveryLimits",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="quality_policy",
                reason_template="Limite de replanejamentos excedido ({replans} >= max {max_replans}).",
            ),
            ExecutiveDecisionRule(
                rule_id="tier5_reorch_limit_exceeded",
                priority=52,
                precedence_tier="5_RECOVERY_LIMITS",
                condition=lambda c: c.get("cor_failed", False) and c.get("reorchestrations", 0) >= c.get("max_reorchestrations", 2),
                source="RecoveryLimits",
                action=ExecutiveAction.FAIL,
                next_state=CognitiveState.FAILED,
                policy_reference="quality_policy",
                reason_template="Limite de reorquestrações excedido ({reorchestrations} >= max {max_reorchestrations}).",
            ),

            # Tier 6: Cost / Latency Constraints
            ExecutiveDecisionRule(
                rule_id="tier6_cost_limit_exceeded",
                priority=60,
                precedence_tier="6_COST_LATENCY",
                condition=lambda c: c.get("estimated_cost", 0.0) > c.get("max_cost", 1.0),
                source="ExecutionPolicy",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="execution_policy",
                reason_template="Custo estimado (${estimated_cost:.4f}) excede o limite estipulado (${max_cost}).",
            ),
            ExecutiveDecisionRule(
                rule_id="tier6_latency_limit_exceeded",
                priority=61,
                precedence_tier="6_COST_LATENCY",
                condition=lambda c: c.get("estimated_latency", 0.0) > c.get("max_latency", 60.0),
                source="ExecutionPolicy",
                action=ExecutiveAction.BLOCK,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                policy_reference="execution_policy",
                reason_template="Latência estimada ({estimated_latency:.1f}s) excede o limite estipulado ({max_latency}s).",
            ),
        ]


@dataclass
class ExecutiveDecision:
    """Explicit decision object generated by the ECC decision engine."""
    decision_id: str
    action: ExecutiveAction
    reason: str
    source_module: str
    current_state: CognitiveState
    next_state: CognitiveState
    timestamp: str = field(default_factory=utc_iso)
    policy_reference: Optional[str] = "standard_policy"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError("ExecutiveDecision requer uma justificativa (reason) válida e não vazia.")

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["action"] = self.action.value if isinstance(self.action, Enum) else self.action
        res["current_state"] = self.current_state.value if isinstance(self.current_state, Enum) else self.current_state
        res["next_state"] = self.next_state.value if isinstance(self.next_state, Enum) else self.next_state
        return res


def sanitize_trace_text(text: Optional[str], max_len: int = 120) -> str:
    """Redacts API keys, tokens, and trims raw text to prevent sensitive leaks in audit logs."""
    if not text:
        return ""
    cleaned = str(text)
    cleaned = re.sub(r'(sk-[A-Za-z0-9_-]{10,})', '[REDACTED_API_KEY]', cleaned)
    cleaned = re.sub(r'(AIza[0-9A-Za-z-_]{10,})', '[REDACTED_API_KEY]', cleaned)
    cleaned = re.sub(r'(bearer\s+[A-Za-z0-9._-]+)', '[REDACTED_TOKEN]', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'("?(?:api_key|token|password|secret)"?\s*:\s*)"[^"]+"', r'\1"[REDACTED]"', cleaned, flags=re.IGNORECASE)
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned


@dataclass
class ExecutiveStepRecord:
    """Audit record for a single cognitive step in the trace."""
    step_id: str
    module: str
    input_summary: str
    output_summary: str
    action: ExecutiveAction
    state_after: CognitiveState
    reason: str
    timestamp: str = field(default_factory=utc_iso)
    duration_ms: float = 0.0
    decision: Optional[ExecutiveDecision] = None

    def __post_init__(self) -> None:
        self.input_summary = sanitize_trace_text(self.input_summary)
        self.output_summary = sanitize_trace_text(self.output_summary)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["action"] = self.action.value if isinstance(self.action, Enum) else self.action
        res["state_after"] = self.state_after.value if isinstance(self.state_after, Enum) else self.state_after
        if self.decision:
            res["decision"] = self.decision.to_dict()
        return res


@dataclass
class ExecutiveTrace:
    """Full executive audit trail for a cognitive run (privacy-safe)."""
    trace_id: str
    correlation_id: Optional[str] = None
    intent_id: Optional[str] = None
    mission_candidate_id: Optional[str] = None
    steps: List[ExecutiveStepRecord] = field(default_factory=list)

    def record_step(
        self,
        module: str,
        input_summary: str,
        output_summary: str,
        action: ExecutiveAction,
        state_after: CognitiveState,
        reason: str,
        duration_ms: float = 0.0,
        decision: Optional[ExecutiveDecision] = None,
    ) -> ExecutiveStepRecord:
        record = ExecutiveStepRecord(
            step_id=f"step_{len(self.steps) + 1}",
            module=module,
            input_summary=input_summary,
            output_summary=output_summary,
            action=action,
            state_after=state_after,
            reason=reason,
            duration_ms=duration_ms,
            decision=decision,
        )
        self.steps.append(record)
        return record

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "intent_id": self.intent_id,
            "mission_candidate_id": self.mission_candidate_id,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class ExecutiveMetrics:
    """Performance and quality metrics calculated across the executive run."""
    pipeline_completion: float = 0.0  # 0.0 to 1.0
    planning_iterations: int = 0
    dialogue_iterations: int = 0
    replans: int = 0
    reorchestrations: int = 0
    recovery_count: int = 0
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    confidence_evolution: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutivePipelineResult:
    """Final output object returned by ECC processing."""
    run_id: str
    current_state: CognitiveState
    final_action: ExecutiveAction
    structured_intent: Optional[Dict[str, Any]] = None
    dialogue_decision: Optional[Dict[str, Any]] = None
    execution_plan: Optional[Dict[str, Any]] = None
    execution_graph: Optional[Dict[str, Any]] = None
    executive_trace: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    validation_messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["current_state"] = self.current_state.value if isinstance(self.current_state, Enum) else self.current_state
        res["final_action"] = self.final_action.value if isinstance(self.final_action, Enum) else self.final_action
        return res


class QualityGates:
    """Threshold rules enforced by ECC before transitioning states using ExecutiveQualityPolicy."""

    # Default fallback thresholds
    min_iqi: float = 0.60
    min_pqi: float = 0.60
    max_estimated_cost: float = 1.0
    max_estimated_latency: float = 60.0

    @classmethod
    def evaluate_iue(cls, intent: StructuredIntent, policy: Optional[ExecutiveQualityPolicy] = None) -> Tuple[bool, str]:
        pol = policy or ExecutiveQualityPolicy.from_risk_profile("standard")
        iqi_dict = getattr(intent, "intent_quality_index", {}) or {}
        if isinstance(iqi_dict, dict):
            score = iqi_dict.get("overall_score", 0.0)
        else:
            score = getattr(iqi_dict, "overall_score", 0.0)

        if getattr(intent, "clarifying_question", None) and getattr(intent, "requires_confirmation", False):
            return False, f"IQI insuficiente ({score:.2f}). {intent.clarifying_question}"

        if score < pol.min_iqi:
            return False, f"IQI insuficiente ({score:.2f} < min {pol.min_iqi}). Requer maiores esclarecimentos."
        return True, f"IQI aprovado ({score:.2f} >= min {pol.min_iqi})."

    @classmethod
    def evaluate_cdm(cls, decision: DialogueDecision, policy: Optional[ExecutiveQualityPolicy] = None) -> Tuple[bool, str]:
        if decision.requires_question and not decision.can_proceed:
            q_text = decision.selected_question.question if decision.selected_question else "Pergunta necessária"
            return False, f"Diálogo necessário: {q_text}"
        if not decision.can_proceed:
            return False, f"Decisão do CDM impede progressão. Estado: {decision.state.value}"
        return True, "Decisão do CDM autoriza prosseguimento."

    @classmethod
    def evaluate_cpe(cls, plan: ExecutionPlan, policy: Optional[ExecutiveQualityPolicy] = None) -> Tuple[bool, str]:
        pol = policy or ExecutiveQualityPolicy.from_risk_profile("standard")
        if plan.status == "blocked":
            return False, "ExecutionPlan está bloqueado pela camada de planejamento."
        pqi_obj = getattr(plan, "plan_quality_index", None)
        if isinstance(pqi_obj, dict):
            pqi_score = pqi_obj.get("overall_score", 0.0)
        else:
            pqi_score = getattr(pqi_obj, "overall_score", 0.0) if pqi_obj else 0.0

        if pqi_score < pol.min_pqi:
            return False, f"PQI insuficiente ({pqi_score:.2f} < min {pol.min_pqi}). Replanejamento necessário."
        return True, f"PQI aprovado ({pqi_score:.2f} >= min {pol.min_pqi})."

    @classmethod
    def evaluate_cor(
        cls,
        graph: ExecutionGraph,
        policy: Optional[ExecutiveQualityPolicy] = None,
        execution_policy: Optional[ExecutiveExecutionPolicy] = None,
    ) -> Tuple[bool, str]:
        pol = policy or ExecutiveQualityPolicy.from_risk_profile("standard")
        exec_pol = execution_policy or ExecutiveExecutionPolicy.from_preset("default")
        if graph.status == "blocked":
            return False, "ExecutionGraph está bloqueado."
        if graph.status == "partially_assigned":
            return False, "Atribuição de capacidade incompleta no ExecutionGraph."
        if graph.estimated_cost > exec_pol.max_cost:
            return False, f"Custo estimado (${graph.estimated_cost:.4f}) excede o limite estipulado (${exec_pol.max_cost})."
        if graph.estimated_latency > exec_pol.max_latency:
            return False, f"Latência estimada ({graph.estimated_latency:.1f}s) excede o limite estipulado ({exec_pol.max_latency}s)."
        return True, f"ExecutionGraph consistente e validado (Status: {graph.status})."


class ExecutivePolicyEngine:
    """Evaluates security, privacy, and constitutional constraints for executive decisions."""

    @staticmethod
    def check_policies(
        intent: Optional[StructuredIntent],
        session_ctx: Optional[Dict[str, Any]],
        active_policies: Optional[List[str]],
        constitution: Optional[Any] = None,
        execution_policy: Optional[ExecutiveExecutionPolicy] = None,
    ) -> Tuple[bool, str]:
        ctx = session_ctx or {}
        p_list = active_policies or []
        exec_pol = execution_policy or ExecutiveExecutionPolicy.from_preset("default")

        # 1. Constitution delegation check if available
        if constitution is not None:
            if hasattr(constitution, "evaluate_intent"):
                try:
                    verdict = constitution.evaluate_intent(intent)
                    if hasattr(verdict, "is_allowed") and not verdict.is_allowed:
                        return False, f"Bloqueio Constitucional: {getattr(verdict, 'reason', 'Violação de princípios')}"
                except Exception as exc:
                    pass

        # 2. Safety pattern check
        raw = getattr(intent, "raw_input", "") or ""
        if any(bad in raw.lower() for bad in ["bypass_security", "exfiltrate_keys", "rm -rf /"]):
            return False, "Bloqueio de Política de Segurança: Comando violou a Constituição do Kernel."

        if "block_execution" in p_list or ctx.get("safety_block") is True:
            return False, "Bloqueio de Política: Execução desabilitada por configuração de política de segurança."

        if exec_pol.offline_required and ctx.get("environment_network_access", True) is True and ctx.get("network_required", False):
            return False, "Bloqueio de Execução: Política offline_required ativa, mas acesso à rede foi detectado."

        return True, "Políticas de segurança e privacidade aprovadas."


class ExecutiveCognitiveController:
    """Executive Cognitive Controller (ECC) — RFC-0011.

    Supervisor that coordinates IUE -> CDM -> CPE -> COR.
    Evaluates quality gates, handles failure recovery, and maintains full executive trace.
    Does NOT execute tasks or interact directly with LLMs/tools.
    """

    def __init__(
        self,
        iue: Optional[IntentUnderstandingEngine] = None,
        cdm: Optional[CognitiveDialogueManager] = None,
        cpe: Optional[CognitivePlanningEngine] = None,
        cor: Optional[CapabilityOrchestrator] = None,
        registry: Optional[RegistryCatalog] = None,
        constitution: Optional[Any] = None,
        bcc: Optional[Any] = None,
        instruction_resolver: Optional[Any] = None,
    ):
        self.iue = iue or IntentUnderstandingEngine()
        self.cdm = cdm or CognitiveDialogueManager()
        self.cpe = cpe or CognitivePlanningEngine()
        self.cor = cor or CapabilityOrchestrator()
        self.registry = registry or RegistryCatalog(populate_defaults=True)
        self.constitution = constitution
        self.bcc = bcc
        self.instruction_resolver = instruction_resolver

    def _transition(
        self,
        current_state: CognitiveState,
        next_state: CognitiveState,
        action: ExecutiveAction,
        module: str,
        reason: str,
        trace: ExecutiveTrace,
        duration_ms: float = 0.0,
        policy_ref: str = "standard_policy",
        confidence: float = 1.0,
        input_sum: str = "",
        output_sum: str = "",
    ) -> Tuple[CognitiveState, ExecutiveDecision]:
        CognitiveStateMachine.validate_transition(current_state, next_state)
        dec = ExecutiveDecision(
            decision_id=f"dec_{uuid4().hex[:6]}",
            action=action,
            reason=reason,
            source_module=module,
            current_state=current_state,
            next_state=next_state,
            policy_reference=policy_ref,
            confidence=confidence,
        )
        trace.record_step(
            module=module,
            input_summary=input_sum or module,
            output_summary=output_sum or f"Action: {action.value}",
            action=action,
            state_after=next_state,
            reason=reason,
            duration_ms=duration_ms,
            decision=dec,
        )
        return next_state, dec

    def process_intent(
        self,
        text: str,
        session_context: Optional[Dict[str, Any]] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        policies: Optional[List[str]] = None,
        policy: Optional[ExecutiveQualityPolicy] = None,
        quality_policy: Optional[ExecutiveQualityPolicy] = None,
        execution_policy: Optional[ExecutiveExecutionPolicy] = None,
        risk_profile: Optional[str] = None,
    ) -> ExecutivePipelineResult:
        """Executes the cognitive pipeline under strict executive supervision."""
        run_id = f"ecc_run_{uuid4().hex[:8]}"
        trace = ExecutiveTrace(
            trace_id=f"trace_{run_id}",
            correlation_id=str((session_context or {}).get("correlation_id", uuid4())),
        )
        metrics = ExecutiveMetrics()
        validation: List[str] = []
        ctx = session_context or {}
        p_list = policies or []

        # Resolve quality and execution policies
        exec_policy = quality_policy or policy or ExecutiveQualityPolicy.from_risk_profile(risk_profile or ctx.get("risk_profile") or "standard")
        exec_constraints_policy = execution_policy or ExecutiveExecutionPolicy.from_preset(ctx.get("execution_preset", "default"))

        state = CognitiveState.RECEIVED
        action = ExecutiveAction.CONTINUE

        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.RECEIVED,
            action=action,
            module="ECC",
            reason="Intenção do usuário recebida. Iniciando controle executivo.",
            trace=trace,
            policy_ref=exec_policy.risk_profile,
            input_sum=f"Input: '{text[:60]}...'",
            output_sum="Inicialização do pipeline executivo",
        )

        # 0. Policy Pre-check
        pol_ok, pol_msg = ExecutivePolicyEngine.check_policies(
            None, ctx, p_list, constitution=self.constitution, execution_policy=exec_constraints_policy
        )
        if not pol_ok:
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                action=ExecutiveAction.BLOCK,
                module="PolicyEngine",
                reason=pol_msg,
                trace=trace,
                policy_ref=exec_policy.risk_profile,
                input_sum="Verificação de Políticas",
                output_sum=pol_msg,
            )
            return ExecutivePipelineResult(
                run_id=run_id,
                current_state=CognitiveState.EXECUTION_BLOCKED,
                final_action=ExecutiveAction.BLOCK,
                executive_trace=trace.to_dict(),
                metrics=metrics.to_dict(),
                validation_messages=[pol_msg],
            )

        # 1. IUE Stage
        t0 = time.perf_counter()
        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.UNDERSTANDING,
            action=ExecutiveAction.CONTINUE,
            module="ECC",
            reason="Avançando para análise de compreensão de intenção (IUE).",
            trace=trace,
            policy_ref=exec_policy.risk_profile,
            input_sum="Início IUE",
            output_sum="Estado: UNDERSTANDING",
        )

        if user_profile and "user_profile" not in ctx:
            ctx["user_profile"] = user_profile
        structured = self.iue.analyze(text, session_context=ctx)
        dur_iue = (time.perf_counter() - t0) * 1000.0

        trace.intent_id = structured.intent_id
        iqi_score = structured.intent_quality_index.get("overall_score", 0.0) if hasattr(structured, "intent_quality_index") else 0.0
        metrics.confidence_evolution.append(iqi_score)

        # Quality Gate 1: IUE
        iue_ok, iue_msg = QualityGates.evaluate_iue(structured, policy=exec_policy)
        validation.append(iue_msg)

        if not iue_ok:
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.WAITING_CONTEXT,
                action=ExecutiveAction.ASK_USER,
                module="IUE",
                reason=iue_msg,
                trace=trace,
                duration_ms=dur_iue,
                policy_ref=exec_policy.risk_profile,
                confidence=iqi_score,
                input_sum=text,
                output_sum=f"IQI: {iqi_score:.2f}",
            )
            metrics.pipeline_completion = 0.25
            return ExecutivePipelineResult(
                run_id=run_id,
                current_state=CognitiveState.WAITING_CONTEXT,
                final_action=ExecutiveAction.ASK_USER,
                structured_intent=structured.to_dict(),
                executive_trace=trace.to_dict(),
                metrics=metrics.to_dict(),
                validation_messages=validation,
            )

        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.READY_FOR_DIALOGUE,
            action=ExecutiveAction.CONTINUE,
            module="IUE",
            reason=iue_msg,
            trace=trace,
            duration_ms=dur_iue,
            policy_ref=exec_policy.risk_profile,
            confidence=iqi_score,
            input_sum=text,
            output_sum=f"Domain: {structured.domain}, Goal: {structured.goal}",
        )

        # 2. CDM Stage
        t0 = time.perf_counter()
        dialogue_decision = self.cdm.evaluate(structured, session_context=ctx)
        dur_cdm = (time.perf_counter() - t0) * 1000.0
        metrics.dialogue_iterations += 1

        # Loop Guard for Dialogue
        if metrics.dialogue_iterations > exec_policy.max_dialogue_iterations:
            reason_lim = f"Limite de iterações de diálogo excedido ({metrics.dialogue_iterations} > max {exec_policy.max_dialogue_iterations})."
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.EXECUTION_BLOCKED,
                action=ExecutiveAction.BLOCK,
                module="CDM",
                reason=reason_lim,
                trace=trace,
                duration_ms=dur_cdm,
                policy_ref=exec_policy.risk_profile,
            )
            return ExecutivePipelineResult(
                run_id=run_id,
                current_state=CognitiveState.EXECUTION_BLOCKED,
                final_action=ExecutiveAction.BLOCK,
                structured_intent=structured.to_dict(),
                dialogue_decision=dialogue_decision.to_dict(),
                executive_trace=trace.to_dict(),
                metrics=metrics.to_dict(),
                validation_messages=[reason_lim],
            )

        # Quality Gate 2: CDM
        cdm_ok, cdm_msg = QualityGates.evaluate_cdm(dialogue_decision, policy=exec_policy)
        validation.append(cdm_msg)

        if not cdm_ok or dialogue_decision.requires_question:
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.WAITING_CONTEXT,
                action=ExecutiveAction.ASK_USER,
                module="CDM",
                reason=cdm_msg,
                trace=trace,
                duration_ms=dur_cdm,
                policy_ref=exec_policy.risk_profile,
                input_sum=f"Intent: {structured.intent_id}",
                output_sum=f"State: {dialogue_decision.state.value}",
            )
            metrics.pipeline_completion = 0.40
            return ExecutivePipelineResult(
                run_id=run_id,
                current_state=CognitiveState.WAITING_CONTEXT,
                final_action=ExecutiveAction.ASK_USER,
                structured_intent=structured.to_dict(),
                dialogue_decision=dialogue_decision.to_dict(),
                executive_trace=trace.to_dict(),
                metrics=metrics.to_dict(),
                validation_messages=validation,
            )

        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.READY_FOR_PLANNING,
            action=ExecutiveAction.CONTINUE,
            module="CDM",
            reason=cdm_msg,
            trace=trace,
            duration_ms=dur_cdm,
            policy_ref=exec_policy.risk_profile,
            input_sum=f"Intent: {structured.intent_id}",
            output_sum="Dialogue state: READY_TO_EXECUTE",
        )

        # 3. CPE Stage
        t0 = time.perf_counter()
        metrics.planning_iterations += 1

        execution_plan = self.cpe.create_plan(
            structured, session_context=ctx, dialogue_decision=dialogue_decision
        )
        dur_cpe = (time.perf_counter() - t0) * 1000.0

        pqi_obj = getattr(execution_plan, "plan_quality_index", None)
        if isinstance(pqi_obj, dict):
            pqi_val = pqi_obj.get("overall_score", 0.0)
        else:
            pqi_val = getattr(pqi_obj, "overall_score", 0.0) if pqi_obj else 0.0
        metrics.confidence_evolution.append(pqi_val)

        # Quality Gate 3: CPE
        cpe_ok, cpe_msg = QualityGates.evaluate_cpe(execution_plan, policy=exec_policy)
        validation.append(cpe_msg)

        if not cpe_ok:
            # Replan Loop Guard
            if metrics.replans >= exec_policy.max_replans:
                reason_replans = f"Limite de replanejamentos excedido ({metrics.replans} >= max {exec_policy.max_replans})."
                state, _ = self._transition(
                    current_state=state,
                    next_state=CognitiveState.EXECUTION_BLOCKED,
                    action=ExecutiveAction.BLOCK,
                    module="CPE",
                    reason=reason_replans,
                    trace=trace,
                    duration_ms=dur_cpe,
                    policy_ref=exec_policy.risk_profile,
                )
                metrics.pipeline_completion = 0.60
                return ExecutivePipelineResult(
                    run_id=run_id,
                    current_state=CognitiveState.EXECUTION_BLOCKED,
                    final_action=ExecutiveAction.BLOCK,
                    structured_intent=structured.to_dict(),
                    dialogue_decision=dialogue_decision.to_dict(),
                    execution_plan=execution_plan.to_dict(),
                    executive_trace=trace.to_dict(),
                    metrics=metrics.to_dict(),
                    validation_messages=validation + [reason_replans],
                )

            # Failure Recovery: Replan attempt
            metrics.replans += 1
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.REPLANNING,
                action=ExecutiveAction.REPLAN,
                module="CPE",
                reason=cpe_msg,
                trace=trace,
                duration_ms=dur_cpe,
                policy_ref=exec_policy.risk_profile,
                input_sum=f"StructuredIntent: {structured.intent_id}",
                output_sum=f"Plan status: {execution_plan.status}, PQI: {pqi_val:.2f}",
            )

            # Retry creation with complete flag
            ctx_retry = dict(ctx)
            ctx_retry["force_complete"] = True
            execution_plan = self.cpe.create_plan(structured, session_context=ctx_retry, dialogue_decision=dialogue_decision)
            cpe_ok, cpe_msg = QualityGates.evaluate_cpe(execution_plan, policy=exec_policy)

            if not cpe_ok:
                state, _ = self._transition(
                    current_state=state,
                    next_state=CognitiveState.EXECUTION_BLOCKED,
                    action=ExecutiveAction.BLOCK,
                    module="CPE",
                    reason="Plano de execução rejeitado pelo Quality Gate CPE após replanejamento.",
                    trace=trace,
                    policy_ref=exec_policy.risk_profile,
                    input_sum="Tentativa de Replanejamento",
                    output_sum="Plano continua insuficiente",
                )
                metrics.pipeline_completion = 0.60
                return ExecutivePipelineResult(
                    run_id=run_id,
                    current_state=CognitiveState.EXECUTION_BLOCKED,
                    final_action=ExecutiveAction.BLOCK,
                    structured_intent=structured.to_dict(),
                    dialogue_decision=dialogue_decision.to_dict(),
                    execution_plan=execution_plan.to_dict(),
                    executive_trace=trace.to_dict(),
                    metrics=metrics.to_dict(),
                    validation_messages=validation,
                )

            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.READY_FOR_PLANNING,
                action=ExecutiveAction.CONTINUE,
                module="CPE",
                reason="Replanejamento bem-sucedido.",
                trace=trace,
                policy_ref=exec_policy.risk_profile,
            )

        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.READY_FOR_ORCHESTRATION,
            action=ExecutiveAction.CONTINUE,
            module="CPE",
            reason=cpe_msg,
            trace=trace,
            duration_ms=dur_cpe,
            policy_ref=exec_policy.risk_profile,
            input_sum=f"StructuredIntent: {structured.intent_id}",
            output_sum=f"Etapas geradas: {len(execution_plan.steps)}, PQI: {pqi_val:.2f}",
        )

        # 4. COR Stage
        t0 = time.perf_counter()
        execution_graph = self.cor.orchestrate(
            plan=execution_plan,
            registry=self.registry,
            policies=p_list,
        )
        dur_cor = (time.perf_counter() - t0) * 1000.0

        metrics.estimated_cost = execution_graph.estimated_cost
        metrics.estimated_latency = execution_graph.estimated_latency

        # Quality Gate 4: COR
        cor_ok, cor_msg = QualityGates.evaluate_cor(execution_graph, policy=exec_policy, execution_policy=exec_constraints_policy)
        validation.append(cor_msg)

        if not cor_ok:
            if metrics.reorchestrations >= exec_policy.max_reorchestrations:
                reason_reorch = f"Limite de reorquestrações excedido ({metrics.reorchestrations} >= max {exec_policy.max_reorchestrations})."
                state, _ = self._transition(
                    current_state=state,
                    next_state=CognitiveState.FAILED,
                    action=ExecutiveAction.FAIL,
                    module="COR",
                    reason=reason_reorch,
                    trace=trace,
                    duration_ms=dur_cor,
                    policy_ref=exec_policy.risk_profile,
                )
                metrics.pipeline_completion = 0.80
                return ExecutivePipelineResult(
                    run_id=run_id,
                    current_state=CognitiveState.FAILED,
                    final_action=ExecutiveAction.FAIL,
                    structured_intent=structured.to_dict(),
                    dialogue_decision=dialogue_decision.to_dict(),
                    execution_plan=execution_plan.to_dict(),
                    execution_graph=execution_graph.to_dict(),
                    executive_trace=trace.to_dict(),
                    metrics=metrics.to_dict(),
                    validation_messages=validation + [reason_reorch],
                )

            metrics.reorchestrations += 1
            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.RECOVERING,
                action=ExecutiveAction.REORCHESTRATE,
                module="COR",
                reason=cor_msg,
                trace=trace,
                duration_ms=dur_cor,
                policy_ref=exec_policy.risk_profile,
                input_sum=f"ExecutionPlan: {execution_plan.plan_id}",
                output_sum=f"Graph status: {execution_graph.status}",
            )

            # Re-orchestration fallback attempt
            execution_graph = self.cor.orchestrate(plan=execution_plan, registry=self.registry)
            cor_ok, cor_msg = QualityGates.evaluate_cor(execution_graph, policy=exec_policy, execution_policy=exec_constraints_policy)

            if not cor_ok:
                state, _ = self._transition(
                    current_state=state,
                    next_state=CognitiveState.FAILED,
                    action=ExecutiveAction.FAIL,
                    module="COR",
                    reason="Orquestração de capacidades falhou e não foi possível rotear.",
                    trace=trace,
                    policy_ref=exec_policy.risk_profile,
                    input_sum="Tentativa de Re-orquestração",
                    output_sum=f"Graph status: {execution_graph.status}",
                )
                metrics.pipeline_completion = 0.80
                return ExecutivePipelineResult(
                    run_id=run_id,
                    current_state=CognitiveState.FAILED,
                    final_action=ExecutiveAction.FAIL,
                    structured_intent=structured.to_dict(),
                    dialogue_decision=dialogue_decision.to_dict(),
                    execution_plan=execution_plan.to_dict(),
                    execution_graph=execution_graph.to_dict(),
                    executive_trace=trace.to_dict(),
                    metrics=metrics.to_dict(),
                    validation_messages=validation,
                )

            state, _ = self._transition(
                current_state=state,
                next_state=CognitiveState.READY_FOR_ORCHESTRATION,
                action=ExecutiveAction.CONTINUE,
                module="COR",
                reason="Reorquestração bem-sucedida.",
                trace=trace,
                policy_ref=exec_policy.risk_profile,
            )

        state, _ = self._transition(
            current_state=state,
            next_state=CognitiveState.READY_FOR_EXECUTION,
            action=ExecutiveAction.CONTINUE,
            module="COR",
            reason=cor_msg,
            trace=trace,
            duration_ms=dur_cor,
            policy_ref=exec_policy.risk_profile,
            input_sum=f"ExecutionPlan: {execution_plan.plan_id}",
            output_sum=f"Grafo de Execução pronto. Atribuições: {len(execution_graph.assignments)}",
        )

        metrics.pipeline_completion = 1.0

        # Final Success State: READY_FOR_EXECUTION
        return ExecutivePipelineResult(
            run_id=run_id,
            current_state=CognitiveState.READY_FOR_EXECUTION,
            final_action=ExecutiveAction.CONTINUE,
            structured_intent=structured.to_dict(),
            dialogue_decision=dialogue_decision.to_dict(),
            execution_plan=execution_plan.to_dict(),
            execution_graph=execution_graph.to_dict(),
            executive_trace=trace.to_dict(),
            metrics=metrics.to_dict(),
            validation_messages=validation,
        )
