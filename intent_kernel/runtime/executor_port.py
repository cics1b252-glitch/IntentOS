"""Action Executor Port & Safe Test Executor — RFC-0015 (STUDIO 10.2).

Defines the abstract ActionExecutorPort interface and the safe, deterministic
InMemoryActionExecutor for unit testing and local simulation without external side effects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from intent_kernel.runtime.models import ActionContract


class RealActionExecutionProhibitedError(RuntimeError):
    """Raised when an executor attempts to execute real external actions in test runtime."""
    pass


class ActionExecutorPort(ABC):
    """Abstract port interface for action execution."""

    @abstractmethod
    async def can_execute(self, action: ActionContract) -> bool:
        """Query if the executor can handle the specified action contract."""
        pass

    @abstractmethod
    async def execute(self, action: ActionContract) -> Any:
        """Execute the specified action contract and return the raw result."""
        pass

    @abstractmethod
    async def cancel(self, action_id: str) -> bool:
        """Cancel an in-flight action execution."""
        pass

    @abstractmethod
    async def get_status(self, action_id: str) -> str:
        """Get execution status of an action."""
        pass


class InMemoryActionExecutor(ActionExecutorPort):
    """Safe, deterministic in-memory executor for unit testing without external side effects."""

    SUPPORTED_CAPABILITIES = {
        "test.echo",
        "test.calculate",
        "test.transform",
        "test.store_temporary",
    }

    FORBIDDEN_KEYWORDS = [
        "email", "calendar", "browser", "network", "os_control", "http", "api_call"
    ]

    def __init__(self) -> None:
        self._execution_history: Dict[str, Any] = {}
        self._temporary_store: Dict[str, Any] = {}

    async def can_execute(self, action: ActionContract) -> bool:
        if action.capability in self.SUPPORTED_CAPABILITIES:
            return True
        return False

    async def execute(self, action: ActionContract) -> Any:
        # Enforce Real Action Execution Prohibition
        cap_lower = action.capability.lower()
        for kw in self.FORBIDDEN_KEYWORDS:
            if kw in cap_lower:
                raise RealActionExecutionProhibitedError(
                    f"Real external action capability '{action.capability}' is prohibited in safe test runtime."
                )

        inputs = action.inputs_reference or {}

        if action.capability == "test.echo":
            msg = inputs.get("message", "echo")
            self._execution_history[action.action_id] = msg
            return msg

        elif action.capability == "test.calculate":
            a = inputs.get("a", 0)
            b = inputs.get("b", 0)
            op = inputs.get("op", "add")
            if op == "add":
                res = a + b
            elif op == "multiply":
                res = a * b
            else:
                res = a + b
            self._execution_history[action.action_id] = res
            return res

        elif action.capability == "test.transform":
            text = str(inputs.get("text", ""))
            mode = inputs.get("mode", "upper")
            if mode == "upper":
                res = text.upper()
            elif mode == "lower":
                res = text.lower()
            else:
                res = text
            self._execution_history[action.action_id] = res
            return res

        elif action.capability == "test.store_temporary":
            key = inputs.get("key", f"k_{action.action_id}")
            val = inputs.get("value", None)
            self._temporary_store[key] = val
            self._execution_history[action.action_id] = val
            return {"stored": key, "value": val}

        else:
            raise ValueError(f"Unsupported capability: {action.capability}")

    async def cancel(self, action_id: str) -> bool:
        if action_id in self._execution_history:
            del self._execution_history[action_id]
            return True
        return False

    async def get_status(self, action_id: str) -> str:
        if action_id in self._execution_history:
            return "SUCCEEDED"
        return "UNKNOWN"
