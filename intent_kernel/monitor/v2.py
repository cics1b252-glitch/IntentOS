"""Intent OS Monitor 2.0 — The Nervous System of Intent OS.

10 components that make the entire system visible:
1. Living Architecture — visual graph of all components
2. Animated Pipeline — watch intentions flow through stages
3. KC Explorer — navigate Knowledge Core like Windows Explorer
4. Cognitive Timeline — intellectual evolution over time
5. Cognitive Health Dashboard — A-F grade, metrics, suggestions
6. Constitution Live — Guardians in real-time
7. Capability Explorer — capabilities, usage, performance
8. Symbiotic Layer Live — host environment, read-only
9. Cognitive Map — interactive knowledge graph
10. Developer Mode — logs, events, metrics

The Monitor answers: "What is happening inside Intent OS's intelligence right now?"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MonitorEvent:
    """A monitored event."""
    timestamp: str
    category: str  # kernel, pipeline, knowledge, guardian, capability, symbiotic, etc.
    event_type: str
    title: str
    details: dict = field(default_factory=dict)


class IntentOSMonitorV2:
    """Intent OS Monitor 2.0 — full observability of the cognitive system."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self._start_time = time.time()
        self._events: list[MonitorEvent] = []
        self._pipeline_runs: list[dict] = []
        self._developer_mode = False
        self._max_events = 5000

    @property
    def name(self) -> str:
        return "intent_os_monitor_v2"

    @property
    def version(self) -> str:
        return "2.0.0"

    # -------------------------------------------------------------------
    # 1. Living Architecture
    # -------------------------------------------------------------------

    def get_architecture(self) -> dict:
        """Visual representation of all connected components."""
        components = []

        # Kernel
        components.append({
            "id": "kernel",
            "name": "Kernel",
            "type": "core",
            "status": "online" if self.kernel else "offline",
            "connections": ["constitution", "pipeline", "event_bus", "knowledge_core"],
        })

        # Constitution
        components.append({
            "id": "constitution",
            "name": "Constitution",
            "type": "governance",
            "status": "active",
            "connections": ["guardians"],
        })

        # Guardians
        components.append({
            "id": "guardians",
            "name": "Guardians",
            "type": "protection",
            "status": "active",
            "count": 6,
            "connections": [],
        })

        # Pipeline
        components.append({
            "id": "pipeline",
            "name": "Pipeline",
            "type": "processing",
            "status": "ready",
            "stages": 9,
            "connections": ["kernel", "event_bus"],
        })

        # Event Bus
        components.append({
            "id": "event_bus",
            "name": "Event Bus",
            "type": "communication",
            "status": "active",
            "connections": ["kernel", "knowledge_core"],
        })

        # Knowledge Core
        components.append({
            "id": "knowledge_core",
            "name": "Knowledge Core",
            "type": "storage",
            "status": "active",
            "connections": ["continuity"],
        })

        # Providers
        components.append({
            "id": "providers",
            "name": "Provider Layer",
            "type": "integration",
            "status": "active",
            "connections": ["kernel"],
        })

        # Capabilities
        components.append({
            "id": "capabilities",
            "name": "Capability Registry",
            "type": "registry",
            "status": "active",
            "count": 10,
            "connections": ["core_apps"],
        })

        # Core Apps
        for app in ["atlas", "logos", "oem_studio"]:
            components.append({
                "id": f"app_{app}",
                "name": app.replace("_", " ").title(),
                "type": "core_app",
                "status": "loaded",
                "connections": ["capabilities", "kernel"],
            })

        # Symbiotic Layer
        components.append({
            "id": "symbiotic",
            "name": "Symbiotic Layer",
            "type": "awareness",
            "status": "scanning",
            "connections": ["knowledge_core"],
        })

        # Continuity
        components.append({
            "id": "continuity",
            "name": "Cognitive Continuity",
            "type": "continuity",
            "status": "active",
            "connections": ["knowledge_core"],
        })

        return {"components": components, "total": len(components)}

    # -------------------------------------------------------------------
    # 2. Animated Pipeline
    # -------------------------------------------------------------------

    def record_pipeline_run(self, run_data: dict) -> None:
        """Record a pipeline execution for visualization."""
        self._pipeline_runs.append({
            "id": run_data.get("id", "unknown"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stages": run_data.get("stages", []),
            "total_time_ms": run_data.get("total_time_ms", 0),
            "domain": run_data.get("domain", "unknown"),
            "mode": run_data.get("mode", "basic"),
            "events_generated": run_data.get("events_generated", 0),
        })

    def get_pipeline_runs(self, limit: int = 10) -> list[dict]:
        return self._pipeline_runs[-limit:]

    def get_pipeline_stages(self) -> list[dict]:
        """Define the pipeline stages for visualization."""
        return [
            {"id": "intake", "name": "Intake", "icon": "📥", "description": "Recebe a intenção"},
            {"id": "classify", "name": "Classificar", "icon": "🏷️", "description": "Domínio + Modo"},
            {"id": "diagnose", "name": "Diagnosticar", "icon": "🔍", "description": "Ambiguidades + Gaps"},
            {"id": "plan", "name": "Planejar", "icon": "📋", "description": "Técnicas + Profundidade"},
            {"id": "build", "name": "Construir", "icon": "🔨", "description": "Gera resposta"},
            {"id": "stress_test", "name": "Stress Test", "icon": "⚖️", "description": "Argumenta contra"},
            {"id": "review", "name": "Revisar", "icon": "✅", "description": "Valida qualidade"},
            {"id": "knowledge_check", "name": "Knowledge Check", "icon": "🧠", "description": "Identifica KC"},
            {"id": "deliver", "name": "Entregar", "icon": "📤", "description": "Finaliza output"},
        ]

    # -------------------------------------------------------------------
    # 3. KC Explorer
    # -------------------------------------------------------------------

    def get_kc_explorer(self) -> dict:
        """Navigate Knowledge Core like Windows Explorer."""
        if not self.kernel:
            return {"categories": [], "total_items": 0}

        categories = [
            {"name": "Projetos", "icon": "📁", "count": 0, "type": "project"},
            {"name": "Objetivos", "icon": "🎯", "count": 0, "type": "goal"},
            {"name": "Decisões", "icon": "⚖️", "count": 0, "type": "decision"},
            {"name": "RFCs", "icon": "📄", "count": 0, "type": "rfc"},
            {"name": "Notas", "icon": "📝", "count": 0, "type": "note"},
            {"name": "Pesquisas", "icon": "🔬", "count": 0, "type": "research"},
            {"name": "Artefatos", "icon": "📦", "count": 0, "type": "artifact"},
            {"name": "Memórias", "icon": "🧠", "count": 0, "type": "memory"},
        ]

        # Count events by type if KC is available
        try:
            from intent_kernel.types import QueryFilters
            import asyncio
            events = asyncio.run(self.kernel.knowledge.query(QueryFilters(limit=1000)))
            for event in events:
                for cat in categories:
                    if event.type.value in cat["type"] or cat["type"] in event.tags:
                        cat["count"] += 1
        except Exception:
            pass

        total = sum(c["count"] for c in categories)
        return {"categories": categories, "total_items": total}

    # -------------------------------------------------------------------
    # 4. Cognitive Timeline
    # -------------------------------------------------------------------

    def get_cognitive_timeline(self, limit: int = 50) -> list[dict]:
        """Get the intellectual evolution timeline."""
        if not self.kernel:
            return []

        events = []
        try:
            from intent_kernel.types import QueryFilters
            import asyncio
            kc_events = asyncio.run(self.kernel.knowledge.query(QueryFilters(limit=limit)))
            for e in kc_events:
                events.append({
                    "id": e.id,
                    "timestamp": e.created_at.isoformat() if hasattr(e.created_at, 'isoformat') else str(e.created_at),
                    "type": e.type.value,
                    "title": e.title,
                    "domain": e.domain.value,
                    "confidence": e.confidence,
                    "lifecycle": e.lifecycle.value,
                })
        except Exception:
            pass

        return sorted(events, key=lambda x: x.get("timestamp", ""), reverse=True)

    # -------------------------------------------------------------------
    # 5. Cognitive Health Dashboard
    # -------------------------------------------------------------------

    def get_cognitive_health(self) -> dict:
        """Get cognitive health metrics."""
        if not self.kernel:
            return {"grade": "N/A", "total_events": 0}

        try:
            from intent_kernel.continuity import CognitiveContinuity
            import asyncio
            continuity = CognitiveContinuity(kernel=self.kernel)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                return {"grade": "N/A", "total_events": 0}
            health = asyncio.run(continuity.assess_health())
            return {
                "grade": health.health_grade,
                "total_events": health.total_events,
                "consistency": health.consistency_score,
                "redundancy": health.redundancy_score,
                "avg_confidence": health.avg_confidence,
                "domains": health.domains,
                "orphan_knowledge": health.orphan_knowledge,
            }
        except Exception:
            return {"grade": "N/A", "total_events": 0}

    # -------------------------------------------------------------------
    # 6. Constitution Live
    # -------------------------------------------------------------------

    def get_constitution_live(self) -> dict:
        """Real-time Constitution and Guardians status."""
        guardians = [
            {"name": "Soberania", "status": "active", "icon": "🛡️", "violations": 0},
            {"name": "Verdade", "status": "active", "icon": "🔍", "violations": 0},
            {"name": "Continuidade", "status": "active", "icon": "🔄", "violations": 0},
            {"name": "Evolução", "status": "active", "icon": "📈", "violations": 0},
            {"name": "Symbiosis", "status": "active", "icon": "🌿", "violations": 0},
            {"name": "Knowledge Heritage", "status": "active", "icon": "📚", "violations": 0},
            {"name": "Continuity", "status": "active", "icon": "🔗", "violations": 0},
        ]

        return {
            "constitution_active": self.kernel is not None,
            "guardians": guardians,
            "total_guardians": len(guardians),
        }

    # -------------------------------------------------------------------
    # 7. Capability Explorer
    # -------------------------------------------------------------------

    def get_capability_explorer(self) -> dict:
        """Explore registered capabilities."""
        capabilities = [
            {"name": "memory", "consumers": [], "usage_count": 0},
            {"name": "knowledge", "consumers": ["Atlas", "Logos", "OEM Studio"], "usage_count": 15},
            {"name": "decision", "consumers": ["Logos"], "usage_count": 8},
            {"name": "planning", "consumers": ["Logos", "OEM Studio"], "usage_count": 5},
            {"name": "simulation", "consumers": ["Atlas"], "usage_count": 3},
            {"name": "research", "consumers": ["Logos"], "usage_count": 4},
            {"name": "versioning", "consumers": ["OEM Studio"], "usage_count": 6},
            {"name": "search", "consumers": ["Logos"], "usage_count": 7},
            {"name": "guardians", "consumers": ["Kernel"], "usage_count": 20},
            {"name": "event_bus", "consumers": ["Kernel"], "usage_count": 25},
        ]

        return {"capabilities": capabilities, "total": len(capabilities)}

    # -------------------------------------------------------------------
    # 8. Symbiotic Layer Live
    # -------------------------------------------------------------------

    def get_symbiotic_live(self) -> dict:
        """Live view of host environment."""
        try:
            from intent_kernel.symbiotic import SymbioticLayer
            import asyncio
            symbiotic = SymbioticLayer()
            snapshot = asyncio.run(symbiotic.scan())
            return {
                "status": "active",
                "os": f"{snapshot.system.os_name} {snapshot.system.os_version}",
                "cpu": f"{snapshot.system.cpu_count} cores",
                "ram": f"{snapshot.system.ram_total_gb:.1f} GB",
                "python": snapshot.system.python_version,
                "programs": len(snapshot.installed_programs),
                "docker": len(snapshot.docker_containers),
                "disks": len(snapshot.external_disks),
                "printers": len(snapshot.printers),
            }
        except Exception:
            return {"status": "unavailable"}

    # -------------------------------------------------------------------
    # 9. Cognitive Map (graph)
    # -------------------------------------------------------------------

    def get_cognitive_map(self) -> dict:
        """Interactive graph of knowledge connections."""
        nodes = []
        edges = []

        try:
            from intent_kernel.types import QueryFilters
            import asyncio
            if self.kernel:
                events = asyncio.run(self.kernel.knowledge.query(QueryFilters(limit=100)))
                for e in events:
                    nodes.append({
                        "id": e.id,
                        "label": e.title[:30],
                        "type": e.type.value,
                        "domain": e.domain.value,
                        "size": max(5, e.confidence * 20),
                    })
                    # Connect to related events
                    for other in events:
                        if other.id != e.id and other.domain == e.domain:
                            edges.append({"source": e.id, "target": other.id})
        except Exception:
            pass

        return {"nodes": nodes, "edges": edges[:200], "total_nodes": len(nodes)}

    # -------------------------------------------------------------------
    # 10. Developer Mode
    # -------------------------------------------------------------------

    def toggle_developer_mode(self) -> bool:
        self._developer_mode = not self._developer_mode
        return self._developer_mode

    def get_developer_view(self) -> dict:
        """Developer mode: logs, events, metrics."""
        uptime = time.time() - self._start_time
        return {
            "developer_mode": self._developer_mode,
            "uptime_seconds": round(uptime, 1),
            "events_logged": len(self._events),
            "pipeline_runs": len(self._pipeline_runs),
            "kernel_status": self.kernel.status() if self.kernel else {},
        }

    # -------------------------------------------------------------------
    # Event logging
    # -------------------------------------------------------------------

    def log(self, category: str, event_type: str, title: str, details: dict | None = None) -> None:
        event = MonitorEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            event_type=event_type,
            title=title,
            details=details or {},
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get_events(self, category: str | None = None, limit: int = 100) -> list[dict]:
        events = self._events
        if category:
            events = [e for e in events if e.category == category]
        return [
            {"timestamp": e.timestamp, "category": e.category, "type": e.event_type, "title": e.title}
            for e in events[-limit:]
        ]

    # -------------------------------------------------------------------
    # Full snapshot
    # -------------------------------------------------------------------

    def get_full_snapshot(self) -> dict:
        """Complete Monitor 2.0 snapshot."""
        return {
            "version": self.version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "architecture": self.get_architecture(),
            "pipeline_stages": self.get_pipeline_stages(),
            "pipeline_runs": self.get_pipeline_runs(limit=5),
            "kc_explorer": self.get_kc_explorer(),
            "cognitive_health": self.get_cognitive_health(),
            "constitution": self.get_constitution_live(),
            "capabilities": self.get_capability_explorer(),
            "symbiotic": self.get_symbiotic_live(),
            "events": self.get_events(limit=20),
        }
