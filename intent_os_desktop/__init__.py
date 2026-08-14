"""Intent OS Desktop — First executable product.

Packages the Kernel + Monitor + Core Apps as a Windows application.
Uses FastAPI backend + web frontend + PyInstaller for .exe.

Usage:
    python -m intent_os_desktop    # Development mode
    Intent OS.exe                  # Production (after PyInstaller build)
"""

from __future__ import annotations

import os
import sys
import json
import webbrowser
import threading
from pathlib import Path
from typing import Any

# Add parent to path for Kernel imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class IntentOSDesktop:
    """Desktop application wrapper for Intent OS."""

    def __init__(self, factory=None):
        self.kernel = None
        self.monitor = None
        self.bridge = None
        self._factory = factory
        self.config_path = Path.home() / ".intent-os" / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load user configuration."""
        defaults = {
            "theme": "dark",
            "language": "pt-BR",
            "auto_start_monitor": True,
            "window_width": 1200,
            "window_height": 800,
        }
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    saved = json.load(f)
                defaults.update(saved)
            except Exception:
                pass
        return defaults

    def save_config(self) -> None:
        """Save configuration."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def initialize(self) -> dict:
        """Initialize the Intent OS system."""
        from intent_kernel.application import ApplicationFactory
        from intent_kernel.monitor import IntentOSMonitor

        self._factory = self._factory or ApplicationFactory()
        self.kernel = self._factory.get_kernel()
        self.monitor = IntentOSMonitor(
            self.kernel,
            components=self._factory.get_components(),
        )
        from product_bridge import ProductBridge

        self.bridge = ProductBridge(
            factory=self._factory,
            data_root=Path.home() / ".intent-os",
        )

        return {
            "status": "initialized",
            "kernel_version": self.kernel.version,
            "constitution_version": self.kernel.constitution.version,
            "providers": self.kernel.providers.available,
            "modules": self.kernel.router.registered_modules,
        }

    def process_intent(self, text: str, context: dict | None = None) -> dict:
        """Process a user intent."""
        import asyncio

        if not self.kernel:
            self.initialize()

        # Context carries transport/session metadata only. It cannot redirect
        # this product entry point or replace the explicit user utterance.
        request = {**dict(context or {}), "action": "intent", "message": text}
        result = asyncio.run(self.bridge.dispatch(request))

        # Log to monitor
        self.monitor.log_event("intent", "Canonical product response", {
            "status": result["status"],
            "execution_mode": result["execution_mode"],
            "response_origin": result["response_origin"],
        })
        return result

    def get_status(self) -> dict:
        """Get complete system status."""
        if not self.kernel:
            return {"status": "offline"}

        return {
            "status": "online",
            "kernel": self.kernel.status(),
            "monitor": {
                "version": self.monitor.version if self.monitor else "unknown",
            },
        }

    def get_dashboard(self) -> dict:
        """Get combined dashboard from all Core Apps."""
        if not self.kernel:
            return {}

        dashboard = {
            "kernel": self.kernel.status(),
            "monitor_summary": self.monitor.get_user_summary() if self.monitor else "",
        }

        # Try to get Core App dashboards
        for module_name in self.kernel.router.registered_modules:
            module = self.kernel.router.get_module(module_name)
            if module and hasattr(module, "get_dashboard"):
                try:
                    dashboard[module_name] = module.get_dashboard()
                except Exception:
                    dashboard[module_name] = {"error": "Could not load dashboard"}

        return dashboard

    def get_knowledge_events(self, limit: int = 20) -> list[dict]:
        """Get recent knowledge events."""
        if not self.kernel:
            return []

        import asyncio
        events = asyncio.run(self.kernel.query(""))
        return [
            {
                "id": e.id,
                "type": e.type.value,
                "title": e.title,
                "domain": e.domain.value,
                "confidence": e.confidence,
                "lifecycle": e.lifecycle.value,
            }
            for e in events[:limit]
        ]


def create_app(factory=None) -> IntentOSDesktop:
    """Create and initialize the desktop application."""
    app = IntentOSDesktop(factory=factory)
    app.initialize()
    return app


# ---------------------------------------------------------------------------
# CLI entry point (development mode)
# ---------------------------------------------------------------------------

def main():
    """Run Intent OS Desktop in development mode."""
    print("🧠 Intent OS Desktop v0.1.0")
    print("=" * 40)

    app = create_app()

    status = app.get_status()
    print(f"Kernel: v{status['kernel']['version']}")
    print(f"Constitution: v{status['kernel']['constitution_version']}")
    print(f"Providers: {status['kernel']['providers']}")
    print(f"Modules: {status['kernel']['modules']}")
    print()

    # Start local server
    try:
        from intent_kernel.server.app import app as fastapi_app
        from intent_kernel.server.app import configure_factory
        import uvicorn

        configure_factory(app._factory)

        print("🌐 Starting web interface...")
        print("   Open http://localhost:8000 in your browser")
        print("   Press Ctrl+C to stop")
        print()

        # Open browser in background
        threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()

        uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)
    except ImportError:
        print("⚠️  FastAPI not installed. Running in terminal mode.")
        print("   Install with: pip install fastapi uvicorn")
        print()

        # Fallback: terminal mode
        while True:
            try:
                text = input("🔹 Sua intenção: ").strip()
                if not text:
                    continue
                if text.lower() in ("/quit", "/exit", "/sair"):
                    print("👋 Até logo!")
                    break

                result = app.process_intent(text)
                print()
                print(result["text"])
                print()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Até logo!")
                break


if __name__ == "__main__":
    main()
