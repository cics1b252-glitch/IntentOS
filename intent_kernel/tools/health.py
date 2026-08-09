"""Tool Health Port & Adapter — RFC-0016 (STUDIO 10.3).

Provides deterministic health check mechanisms for registered tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

from intent_kernel.tools.models import ToolHealthStatus


class ToolHealthPort(ABC):
    """Abstract port for querying tool health."""

    @abstractmethod
    async def check_health(self, tool_id: str) -> ToolHealthStatus:
        """Query deterministic health status for a tool."""
        pass


class InMemoryToolHealthAdapter(ToolHealthPort):
    """Deterministic in-memory tool health adapter for unit testing."""

    def __init__(self) -> None:
        self._health_map: Dict[str, ToolHealthStatus] = {}

    def set_tool_health(self, tool_id: str, status: ToolHealthStatus) -> None:
        self._health_map[tool_id] = status

    async def check_health(self, tool_id: str) -> ToolHealthStatus:
        return self._health_map.get(tool_id, ToolHealthStatus.HEALTHY)
