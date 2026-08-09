"""Cognitive Home — The definitive home screen of Intent OS.

Shows:
- Last project
- Recent activities
- Cognitive health
- Timeline
- Goals
- Quick shortcuts
- System suggestions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HomeActivity:
    """A recent activity on the home screen."""
    id: str
    title: str
    activity_type: str  # project, decision, knowledge, backup
    timestamp: str
    icon: str = ""


@dataclass
class HomeShortcut:
    """A quick shortcut on the home screen."""
    id: str
    label: str
    icon: str
    action: str


class CognitiveHome:
    """The home screen of Intent OS."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.shortcuts = self._init_shortcuts()

    def _init_shortcuts(self) -> list[HomeShortcut]:
        return [
            HomeShortcut("new_project", "Novo Projeto", "📁", "create_project"),
            HomeShortcut("chat", "Conversar", "💬", "open_chat"),
            HomeShortcut("map", "Mapa Cognitivo", "🗺️", "open_map"),
            HomeShortcut("timeline", "Timeline", "📅", "open_timeline"),
            HomeShortcut("backup", "Backup", "💾", "create_backup"),
            HomeShortcut("search", "Buscar", "🔍", "universal_search"),
        ]

    async def get_home_data(self) -> dict:
        """Get all data for the home screen."""
        return {
            "greeting": self._get_greeting(),
            "summary": await self._get_system_summary(),
            "activities": await self._get_recent_activities(),
            "health": await self._get_health(),
            "shortcuts": [
                {"id": s.id, "label": s.label, "icon": s.icon}
                for s in self.shortcuts
            ],
        }

    def _get_greeting(self) -> str:
        from datetime import datetime
        hour = datetime.now().hour
        if hour < 12:
            return "Bom dia"
        elif hour < 18:
            return "Boa tarde"
        return "Boa noite"

    async def _get_system_summary(self) -> dict:
        if not self.kernel:
            return {"status": "offline"}
        try:
            status = self.kernel.status()
            return {
                "status": "online",
                "version": status.get("version", "?"),
                "providers": len(status.get("providers", [])),
                "modules": len(status.get("modules", [])),
            }
        except Exception:
            return {"status": "error"}

    async def _get_recent_activities(self) -> list[dict]:
        return [
            {"title": "Sistema inicializado", "type": "system", "icon": "🟢"},
        ]

    async def _get_health(self) -> dict:
        return {"grade": "N/A", "events": 0}
