"""Controlled Cognitive Execution Runtime Package — RFC-0015 (STUDIO 10.2).

Exports canonical Mission Runtime models, Action Gate, Executor Port, Verification Gate, Checkpoints, and Engine.
"""

from intent_kernel.runtime.action_gate import ActionGate
from intent_kernel.runtime.checkpoints import (
    InMemoryCheckpointRepository,
    MissionCheckpointRepositoryPort,
)
from intent_kernel.runtime.executor_port import (
    ActionExecutorPort,
    InMemoryActionExecutor,
    RealActionExecutionProhibitedError,
)
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    ActionGateDecision,
    ExecutionConfirmationRequest,
    FailureCategory,
    FailureReport,
    MissionCheckpoint,
    MissionRuntimeInstance,
    MissionRuntimeState,
    RuntimeNode,
    RuntimeNodeState,
    RuntimeTraceRecord,
    SideEffectLevel,
    VerificationStatus,
)
from intent_kernel.runtime.verification import (
    ActionVerificationPort,
    DeterministicStructuralVerifier,
    InMemoryActionVerificationAdapter,
    MissionCompletionDecision,
    MissionCompletionGate,
    VerificationGate,
    exact_contract_hash,
)
from intent_kernel.runtime.semantic_verifier import (
    DeterministicRuleVerifier,
    rule_set_hash,
)

__all__ = [
    "MissionRuntimeState",
    "RuntimeNodeState",
    "SideEffectLevel",
    "ActionGateDecision",
    "FailureCategory",
    "VerificationStatus",
    "ActionContract",
    "ExecutionConfirmationRequest",
    "RuntimeNode",
    "MissionCheckpoint",
    "RuntimeTraceRecord",
    "FailureReport",
    "MissionRuntimeInstance",
    "ActionGate",
    "ActionExecutorPort",
    "InMemoryActionExecutor",
    "RealActionExecutionProhibitedError",
    "ActionVerificationPort",
    "DeterministicStructuralVerifier",
    "InMemoryActionVerificationAdapter",
    "VerificationGate",
    "MissionCompletionDecision",
    "MissionCompletionGate",
    "MissionCheckpointRepositoryPort",
    "InMemoryCheckpointRepository",
    "DeterministicRuleVerifier",
    "rule_set_hash",
    "MissionRuntime",
]
