"""Tool Registry & Capability Mapping — RFC-0016 (STUDIO 10.3).

Defines ToolRegistryPort and InMemoryToolRegistry for tool registration, lifecycle tracking,
and mapping abstract capabilities to candidate tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from intent_kernel.tools.models import (
    CapabilityToolMapping,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)


class ToolRegistryPort(ABC):
    """Abstract port interface for the Tool Registry."""

    @abstractmethod
    async def register_tool(self, tool: ToolResource) -> bool:
        """Register a new tool resource in the catalog."""
        pass

    @abstractmethod
    async def unregister_tool(self, tool_id: str) -> bool:
        """Remove a tool resource from the catalog."""
        pass

    @abstractmethod
    async def get_tool(self, tool_id: str) -> Optional[ToolResource]:
        """Retrieve a tool resource by ID."""
        pass

    @abstractmethod
    async def list_tools(self) -> List[ToolResource]:
        """List all tools registered in the catalog."""
        pass

    @abstractmethod
    async def update_tool_status(self, tool_id: str, status: ToolStatus) -> bool:
        """Update lifecycle status of a tool."""
        pass

    @abstractmethod
    async def get_tools_for_capability(self, capability: str) -> List[ToolResource]:
        """Query tools capable of handling the specified capability."""
        pass


class InMemoryToolRegistry(ToolRegistryPort):
    """In-memory implementation of the Tool Registry with explicit capability mapping."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolResource] = {}
        self._capability_mappings: Dict[str, CapabilityToolMapping] = {}

    async def register_tool(self, tool: ToolResource) -> bool:
        self._tools[tool.tool_id] = tool

        # Update capability mappings
        for cap in tool.capabilities:
            if cap not in self._capability_mappings:
                self._capability_mappings[cap] = CapabilityToolMapping(capability=cap, tool_ids=[])
            mapping = self._capability_mappings[cap]
            if tool.tool_id not in mapping.tool_ids:
                mapping.tool_ids.append(tool.tool_id)
                if not mapping.default_tool_id:
                    mapping.default_tool_id = tool.tool_id

        return True

    async def unregister_tool(self, tool_id: str) -> bool:
        if tool_id in self._tools:
            tool = self._tools[tool_id]
            for cap in tool.capabilities:
                if cap in self._capability_mappings:
                    mapping = self._capability_mappings[cap]
                    if tool_id in mapping.tool_ids:
                        mapping.tool_ids.remove(tool_id)
                    if mapping.default_tool_id == tool_id:
                        mapping.default_tool_id = mapping.tool_ids[0] if mapping.tool_ids else None
            del self._tools[tool_id]
            return True
        return False

    async def get_tool(self, tool_id: str) -> Optional[ToolResource]:
        return self._tools.get(tool_id)

    async def list_tools(self) -> List[ToolResource]:
        return list(self._tools.values())

    async def update_tool_status(self, tool_id: str, status: ToolStatus) -> bool:
        if tool_id in self._tools:
            self._tools[tool_id].status = status
            return True
        return False

    async def get_tools_for_capability(self, capability: str) -> List[ToolResource]:
        mapping = self._capability_mappings.get(capability)
        if not mapping:
            # Fallback scan tools directly
            return [t for t in self._tools.values() if capability in t.capabilities]

        res: List[ToolResource] = []
        for tid in mapping.tool_ids:
            t = self._tools.get(tid)
            if t:
                res.append(t)
        return res
