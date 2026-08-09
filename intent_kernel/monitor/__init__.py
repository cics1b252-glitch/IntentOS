"""Intent OS Monitor — First official UI of the Intent OS.

Observes the entire ecosystem in real-time:
- Kernel state, version, uptime, health
- Constitution, Guardians, validations
- Pipeline stage, timing, events
- Capability Registry: capabilities, dependencies, usage
- Providers: active, availability, health
- Knowledge Core: projects, documents, events, stats
- Core Apps: state, capabilities used, events
- Logs: all important events

Uses only public Kernel APIs — never accesses internal structures.
Comprehensible by non-programmers.
"""

from __future__ import annotations

import time
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MonitorSnapshot:
    """A point-in-time snapshot of the entire Intent OS ecosystem."""
    timestamp: str
    kernel: dict
    constitution: dict
    guardians: dict
    pipeline: dict
    capabilities: dict
    providers: dict
    knowledge_core: dict
    core_apps: dict
    logs: list[dict]
    metrics: dict
    composition: dict = field(default_factory=dict)
    migration: dict = field(default_factory=dict)


class IntentOSMonitor:
    """Intent OS Monitor — observes the system without touching internals.

    Every piece of information is obtained through public Kernel APIs.
    The Monitor is a consumer of the architecture, never a shortcut.
    """

    def __init__(self, kernel: Any = None, *, components: Any = None):
        self.kernel = kernel
        self.components = components
        self._start_time = time.time()
        self._event_log: list[dict] = []
        self._max_log_size = 1000

    @property
    def name(self) -> str:
        return "intent_os_monitor"

    @property
    def version(self) -> str:
        return "0.1.0"

    # -------------------------------------------------------------------
    # Main snapshot
    # -------------------------------------------------------------------

    def get_snapshot(self) -> MonitorSnapshot:
        """Get a complete snapshot of the Intent OS ecosystem."""
        return MonitorSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            kernel=self._observe_kernel(),
            constitution=self._observe_constitution(),
            guardians=self._observe_guardians(),
            pipeline=self._observe_pipeline(),
            capabilities=self._observe_capabilities(),
            providers=self._observe_providers(),
            knowledge_core=self._observe_knowledge_core(),
            core_apps=self._observe_core_apps(),
            logs=self._get_recent_logs(),
            metrics=self._compute_metrics(),
            composition=self._observe_composition(),
            migration=self._observe_migration(),
        )

    # -------------------------------------------------------------------
    # Observation methods — each accesses only public APIs
    # -------------------------------------------------------------------

    def _observe_kernel(self) -> dict:
        """Observe Kernel state through public API."""
        if not self.kernel:
            return {"status": "offline", "version": "unknown"}

        uptime = time.time() - self._start_time
        status = self.kernel.status()

        return {
            "status": "online",
            "version": status.get("version", "unknown"),
            "uptime_seconds": round(uptime, 1),
            "uptime_human": self._format_uptime(uptime),
            "constitution_version": status.get("constitution_version", "unknown"),
            "providers": status.get("providers", []),
            "modules": status.get("modules", []),
            "pkb_path": status.get("pkb_path", ""),
        }

    def _observe_constitution(self) -> dict:
        """Observe Constitution state."""
        if not self.kernel:
            return {"status": "offline"}

        constitution = self.kernel.constitution
        return {
            "status": "active",
            "version": getattr(constitution, "version", "unknown"),
            "supreme_principle": getattr(constitution, "supreme_principle", "")[:80],
            "pillars": len(getattr(constitution, "pillars", [])),
            "constraints": len(getattr(constitution, "all_constraints", [])),
        }

    def _observe_guardians(self) -> dict:
        """Observe Guardians state."""
        if not self.kernel:
            return {"status": "offline", "guardians": []}

        # Try to get guardian status from the kernel
        guardians = []
        if hasattr(self.kernel, "guardian_registry"):
            registry = self.kernel.guardian_registry
            if hasattr(registry, "status"):
                status = registry.status()
                guardians = status.get("guardians", [])

        return {
            "status": "active",
            "count": len(guardians),
            "guardians": guardians,
        }

    def _observe_pipeline(self) -> dict:
        """Observe Pipeline state."""
        return {
            "status": "ready",
            "modes": ["QUICK", "BASIC", "DETAIL", "EXPERT", "ARCHITECT"],
            "nodes": ["intake", "classify", "diagnose", "plan", "build", "review", "deliver"],
        }

    def _observe_capabilities(self) -> dict:
        """Observe Capability Registry."""
        if self.components is not None:
            capabilities = [
                item.name
                for item in self.components.capability_registry.capabilities
            ]
            return {
                "status": "active",
                "total": len(capabilities),
                "capabilities": capabilities,
                "source": "canonical",
            }
        return {
            "status": "active",
            "total": 10,
            "capabilities": [
                "memory", "knowledge", "decision", "planning",
                "simulation", "research", "versioning", "search",
                "guardians", "event_bus",
            ],
        }

    def _observe_providers(self) -> dict:
        """Observe Provider Layer."""
        providers = []
        if self.kernel and hasattr(self.kernel, "providers"):
            pm = self.kernel.providers
            if hasattr(pm, "available"):
                for name in pm.available:
                    providers.append({"name": name, "status": "active"})

        return {
            "status": "active",
            "total": len(providers),
            "providers": providers,
        }

    def _observe_knowledge_core(self) -> dict:
        """Observe Knowledge Core."""
        if not self.kernel:
            return {"status": "offline", "events": 0}

        event_count = 0
        if hasattr(self.kernel, "knowledge"):
            km = self.kernel.knowledge
            if (
                hasattr(km, "count")
                and not inspect.iscoroutinefunction(km.count)
            ):
                result = km.count()
                event_count = result

        return {
            "status": "active",
            "events": event_count,
        }

    def _observe_core_apps(self) -> dict:
        """Observe Core Apps."""
        if self.components is not None:
            apps = {
                app.app_id: {
                    "status": "loaded",
                    "capabilities": [
                        capability.name
                        for capability in app.capabilities
                    ],
                }
                for app in self.components.core_apps
            }
            return {
                "status": "active",
                "total": len(apps),
                "apps": apps,
                "source": "canonical",
            }
        apps = {}
        if self.kernel and hasattr(self.kernel, "modules"):
            router = self.kernel.modules if hasattr(self.kernel, "modules") else None
            if router and hasattr(router, "registered_modules"):
                for name in router.registered_modules:
                    apps[name] = {
                        "status": "loaded",
                        "capabilities_used": [],
                        "events_published": 0,
                        "events_consumed": 0,
                    }

        return {
            "status": "active",
            "total": len(apps),
            "apps": apps,
        }

    def _observe_composition(self) -> dict:
        """Describe the public canonical graph without inspecting internals."""
        if not self.kernel:
            return {"status": "offline"}
        description = getattr(self.kernel, "runtime_description", {})
        return {
            "status": "active",
            **description,
        }

    def _observe_migration(self) -> dict:
        """Expose aggregate routing telemetry without user content."""
        if self.components is None:
            return {
                "status": "unavailable",
                "reason": "compatibility bootstrap",
            }
        snapshot = self.components.migration_telemetry.snapshot()
        owned = {
            item.name
            for item in self.components.capability_registry.capabilities
        }
        loaded_adapters = list(self.components.legacy_adapters)
        observed_legacy = set(snapshot["legacy_component_calls"])
        return {
            "status": "active",
            **snapshot,
            "canonical_capabilities": len(owned),
            "capabilities_without_owner": [],
            "loaded_adapters": loaded_adapters,
            "active_adapters": [
                name for name in loaded_adapters
                if name in observed_legacy
            ],
            "unused_adapters": [
                name for name in loaded_adapters
                if name not in observed_legacy
            ],
            "deprecated_loaded": [
                "ModuleRouter",
                "CoreModule",
                "FinanceModule",
            ],
        }

    # -------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------

    def log_event(self, event_type: str, message: str, details: dict | None = None) -> None:
        """Log an event for observation."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "message": message,
            "details": details or {},
        }
        self._event_log.append(entry)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

    def _get_recent_logs(self, limit: int = 50) -> list[dict]:
        """Get recent log entries."""
        return self._event_log[-limit:]

    # -------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------

    def _compute_metrics(self) -> dict:
        """Compute system metrics."""
        uptime = time.time() - self._start_time
        return {
            "uptime_seconds": round(uptime, 1),
            "events_logged": len(self._event_log),
            "monitor_version": self.version,
        }

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime in human-readable form."""
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

    # -------------------------------------------------------------------
    # Summary for non-technical users
    # -------------------------------------------------------------------

    def get_user_summary(self) -> str:
        """Get a human-readable summary of the system status."""
        snapshot = self.get_snapshot()

        lines = []
        lines.append("🧠 Intent OS — Status do Sistema")
        lines.append("=" * 40)

        # Kernel
        k = snapshot.kernel
        if k.get("status") == "online":
            lines.append(f"🟢 Kernel Online (v{k.get('version', '?')})")
            lines.append(f"   Uptime: {k.get('uptime_human', '?')}")
        else:
            lines.append("🔴 Kernel Offline")

        # Constitution
        c = snapshot.constitution
        if c.get("status") == "active":
            lines.append(f"🟢 Constitution Ativa (v{c.get('version', '?')})")
            lines.append(f"   Princípios: {c.get('pillars', 0)} | Restrições: {c.get('constraints', 0)}")
        else:
            lines.append("🔴 Constitution Inativa")

        # Guardians
        g = snapshot.guardians
        lines.append(f"🟢 {g.get('count', 0)} Guardians Ativos")

        # Providers
        p = snapshot.providers
        lines.append(f"🟢 {p.get('total', 0)} Providers Conectados")

        # Knowledge Core
        kc = snapshot.knowledge_core
        lines.append(f"🟢 Knowledge Core: {kc.get('events', 0)} eventos")

        # Core Apps
        apps = snapshot.core_apps
        lines.append(f"🟢 {apps.get('total', 0)} Core Apps Carregados")

        lines.append("")
        lines.append(f"📊 Uptime: {snapshot.metrics.get('uptime_seconds', 0)}s")
        lines.append(f"📋 Eventos monitorados: {snapshot.metrics.get('events_logged', 0)}")

        return "\n".join(lines)
