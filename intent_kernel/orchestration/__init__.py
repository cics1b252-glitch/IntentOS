"""Canonical agent and capability orchestration."""

from __future__ import annotations

from typing import Any

__all__ = [
    "CanonicalAgentOrchestrator",
    "CanonicalCapabilityRegistry",
    "CapabilityExecutionOutcome",
    "CapabilityExecutionService",
    "CapabilityRegistration",
    "ExecutorKind",
]

# Lazy import to avoid circular imports
_loaded = False
_agent_orchestrator = None
_capability_registry = None
_execution_outcome = None
_execution_service = None
_capability_registration = None
_executor_kind = None


def __getattr__(name: str) -> Any:
    global _loaded, _agent_orchestrator, _capability_registry, _execution_outcome
    global _execution_service, _capability_registration, _executor_kind

    if name == "CanonicalAgentOrchestrator":
        if _agent_orchestrator is None:
            from intent_kernel.orchestration.agents import CanonicalAgentOrchestrator
            _agent_orchestrator = CanonicalAgentOrchestrator
        return _agent_orchestrator

    if name == "CanonicalCapabilityRegistry":
        if _capability_registry is None:
            from intent_kernel.orchestration.registry import CanonicalCapabilityRegistry
            _capability_registry = CanonicalCapabilityRegistry
        return _capability_registry

    if name == "CapabilityExecutionOutcome":
        if _execution_outcome is None:
            from intent_kernel.orchestration.execution import CapabilityExecutionOutcome
            _execution_outcome = CapabilityExecutionOutcome
        return _execution_outcome

    if name == "CapabilityExecutionService":
        if _execution_service is None:
            from intent_kernel.orchestration.execution import CapabilityExecutionService
            _execution_service = CapabilityExecutionService
        return _execution_service

    if name == "CapabilityRegistration":
        if _capability_registration is None:
            from intent_kernel.orchestration.registry import CapabilityRegistration
            _capability_registration = CapabilityRegistration
        return _capability_registration

    if name == "ExecutorKind":
        if _executor_kind is None:
            from intent_kernel.orchestration.registry import ExecutorKind
            _executor_kind = ExecutorKind
        return _executor_kind

    raise AttributeError(f"module 'intent_kernel.orchestration' has no attribute '{name}'")