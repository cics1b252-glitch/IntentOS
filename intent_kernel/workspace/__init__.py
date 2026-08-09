"""Cognitive Workspace — The definitive main screen of Intent OS.

Unified surface that combines:
- Chat
- Projects
- Cognitive Map
- Timeline
- Dashboard
- Core Apps (Atlas, Logos, OEM Studio)
- Cognitive Health
- Universal Search
- Command Palette
- Context Engine

One environment. Not separate apps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkspacePanel:
    """A panel in the Cognitive Workspace."""
    id: str
    name: str
    icon: str
    visible: bool = True
    active: bool = False
    data: dict = field(default_factory=dict)


@dataclass
class CommandItem:
    """A command in the Command Palette."""
    id: str
    label: str
    description: str
    category: str
    action: str  # action type
    keywords: list[str] = field(default_factory=list)


class ContextEngine:
    """Determines what the user is trying to do right now."""

    def __init__(self):
        self._context_stack: list[dict] = []

    def analyze(self, intent_text: str) -> dict:
        """Analyze user intent to determine context."""
        text = intent_text.lower()

        # Domain detection
        domain = "general"
        if any(w in text for w in ["investir", "financeiro", "carteira", "ações", "etf"]):
            domain = "finance"
        elif any(w in text for w in ["código", "programar", "api", "sistema", "deploy"]):
            domain = "engineering"
        elif any(w in text for w in ["projeto", "rfc", "decisão", "document", "nota"]):
            domain = "knowledge"
        elif any(w in text for w in ["estudar", "aprender", "curso", "tutorial"]):
            domain = "education"

        # Action detection
        action = "query"
        if any(w in text for w in ["criar", "novo", "adicionar", "registrar"]):
            action = "create"
        elif any(w in text for w in ["buscar", "procurar", "encontrar", "onde"]):
            action = "search"
        elif any(w in text for w in ["simular", "projetar", "calcular"]):
            action = "simulate"
        elif any(w in text for w in ["backup", "exportar", "salvar"]):
            action = "backup"

        context = {"domain": domain, "action": action, "text": intent_text}
        self._context_stack.append(context)
        return context

    def get_current(self) -> dict:
        return self._context_stack[-1] if self._context_stack else {"domain": "general", "action": "query"}

    def get_recommended_panels(self) -> list[str]:
        """Get panels recommended for current context."""
        ctx = self.get_current()
        domain = ctx.get("domain", "general")

        base = ["chat", "timeline", "health"]
        if domain == "finance":
            return ["chat", "atlas", "timeline", "health", "map"]
        elif domain == "engineering":
            return ["chat", "oem_studio", "timeline", "health"]
        elif domain == "knowledge":
            return ["chat", "logos", "timeline", "health", "map"]
        else:
            return base + ["map"]


class CognitiveWorkspace:
    """The unified workspace of Intent OS.

    Combines all functionality into one coherent environment.
    Adapts to context. Never fragments.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.context_engine = ContextEngine()
        self.panels = self._init_panels()
        self.commands = self._init_commands()
        self.search_index: list[dict] = []

    @property
    def name(self) -> str:
        return "cognitive_workspace"

    def _init_panels(self) -> list[WorkspacePanel]:
        return [
            WorkspacePanel("chat", "Chat", "💬", active=True),
            WorkspacePanel("projects", "Projetos", "📁"),
            WorkspacePanel("map", "Mapa Cognitivo", "🗺️"),
            WorkspacePanel("timeline", "Timeline", "📅"),
            WorkspacePanel("health", "Saúde Cognitiva", "❤️"),
            WorkspacePanel("atlas", "Atlas", "💰"),
            WorkspacePanel("logos", "Logos", "📚"),
            WorkspacePanel("oem_studio", "OEM Studio", "🔧"),
            WorkspacePanel("symbiotic", "Ambiente", "🌿"),
            WorkspacePanel("settings", "Configurações", "⚙️"),
        ]

    def _init_commands(self) -> list[CommandItem]:
        return [
            CommandItem("create_project", "Criar Projeto", "Inicia um novo projeto", "project", "create", ["criar", "novo", "projeto"]),
            CommandItem("simulate_wallet", "Simular Carteira", "Simula investimento", "finance", "simulate", ["simular", "investir", "carteira"]),
            CommandItem("open_timeline", "Abrir Timeline", "Mostra evolução cognitiva", "view", "view", ["timeline", "evolução", "histórico"]),
            CommandItem("search_rfc", "Buscar RFC", "Pesquisa RFCs", "search", "search", ["buscar", "rfc"]),
            CommandItem("create_backup", "Gerar Backup", "Backup da Knowledge Core", "system", "backup", ["backup", "salvar", "exportar"]),
            CommandItem("restore_kc", "Restaurar KC", "Restaura KC de backup", "system", "restore", ["restaurar", "importar"]),
            CommandItem("open_map", "Abrir Mapa", "Mapa Cognitivo", "view", "view", ["mapa", "conexões", "grafo"]),
            CommandItem("view_health", "Ver Saúde", "Métricas cognitivas", "view", "view", ["saúde", "métricas", "qualidade"]),
            CommandItem("search_all", "Busca Universal", "Pesquisa em tudo", "search", "search", ["buscar", "procurar"]),
            CommandItem("env_scan", "Escanear Ambiente", "Detecta ambiente host", "system", "scan", ["ambiente", "sistema", "scan"]),
        ]

    # -------------------------------------------------------------------
    # Universal Search
    # -------------------------------------------------------------------

    async def universal_search(self, query: str) -> dict:
        """Search everything: projects, documents, decisions, knowledge, timeline."""
        results = {
            "query": query,
            "projects": [],
            "documents": [],
            "decisions": [],
            "knowledge": [],
            "commands": [],
        }

        # Search commands
        q = query.lower()
        results["commands"] = [
            {"id": c.id, "label": c.label, "description": c.description}
            for c in self.commands
            if any(kw in q for kw in c.keywords) or q in c.label.lower()
        ]

        # Search knowledge
        if self.kernel:
            try:
                from intent_kernel.types import QueryFilters
                events = await self.kernel.knowledge.query(
                    QueryFilters(search_text=query, limit=20)
                )
                results["knowledge"] = [
                    {"id": e.id, "title": e.title, "type": e.type.value, "domain": e.domain.value}
                    for e in events
                ]
            except Exception:
                pass

        results["total"] = sum(len(v) for v in results.values() if isinstance(v, list))
        return results

    # -------------------------------------------------------------------
    # Command Palette
    # -------------------------------------------------------------------

    def get_commands(self, filter_text: str = "") -> list[dict]:
        """Get commands filtered by text."""
        commands = self.commands
        if filter_text:
            q = filter_text.lower()
            commands = [
                c for c in commands
                if q in c.label.lower() or any(kw in q for kw in c.keywords)
            ]
        return [
            {"id": c.id, "label": c.label, "description": c.description, "category": c.category}
            for c in commands
        ]

    def execute_command(self, command_id: str) -> dict:
        """Execute a command."""
        for cmd in self.commands:
            if cmd.id == command_id:
                return {
                    "executed": True,
                    "command": cmd.label,
                    "action": cmd.action,
                    "message": f"Comando '{cmd.label}' executado.",
                }
        return {"executed": False, "error": "Command not found"}

    # -------------------------------------------------------------------
    # Workspace Context
    # -------------------------------------------------------------------

    def process_input(self, text: str) -> dict:
        """Process user input and return workspace state."""
        context = self.context_engine.analyze(text)
        recommended = self.context_engine.get_recommended_panels()

        # Update panel visibility
        for panel in self.panels:
            panel.visible = panel.id in recommended or panel.id in ["chat", "settings"]

        return {
            "context": context,
            "recommended_panels": recommended,
            "active_panels": [p.id for p in self.panels if p.visible],
        }

    def get_workspace_state(self) -> dict:
        """Get current workspace state."""
        return {
            "panels": [
                {"id": p.id, "name": p.name, "icon": p.icon, "visible": p.visible, "active": p.active}
                for p in self.panels
            ],
            "context": self.context_engine.get_current(),
            "commands_count": len(self.commands),
        }

    # -------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------

    async def get_dashboard(self) -> dict:
        """Get complete workspace dashboard."""
        state = self.get_workspace_state()
        health = {}
        if self.kernel:
            try:
                from intent_kernel.monitor.v2 import IntentOSMonitorV2
                monitor = IntentOSMonitorV2(self.kernel)
                health = monitor.get_cognitive_health()
            except Exception:
                pass

        return {
            "workspace": state,
            "health": health,
            "searchable_items": len(self.search_index),
        }
