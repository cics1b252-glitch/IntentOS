"""Symbiotic Layer — Phase 2: Host Environment Awareness.

Strictly non-invasive. Observes the host system without modifying it.
All information feeds into the Knowledge Core automatically.

Detects:
- Operating system and version
- Hardware (CPU, GPU, RAM, disks)
- Python environments
- Docker containers
- Virtual machines
- Installed programs
- System services
- Relevant environment variables
- Directory structure
- External disks
- Printers
"""

from __future__ import annotations

import os
import sys
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path


@dataclass
class SystemInfo:
    """Host system information."""
    os_name: str = ""
    os_version: str = ""
    os_arch: str = ""
    hostname: str = ""
    python_version: str = ""
    python_path: str = ""
    cpu_count: int = 0
    cpu_model: str = ""
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    gpu_info: str = ""
    hostname_resolved: str = ""


@dataclass
class EnvironmentSnapshot:
    """Complete snapshot of the host environment."""
    system: SystemInfo
    python_environments: list[dict] = field(default_factory=list)
    docker_containers: list[dict] = field(default_factory=list)
    installed_programs: list[str] = field(default_factory=list)
    system_services: list[str] = field(default_factory=list)
    environment_vars: dict[str, str] = field(default_factory=dict)
    external_disks: list[dict] = field(default_factory=list)
    printers: list[str] = field(default_factory=list)
    key_directories: list[dict] = field(default_factory=list)
    timestamp: str = ""


class SymbioticLayer:
    """Symbiotic Layer — observes the host system.

    Phase 2: Deep environment awareness.
    Strictly non-invasive — reads but never modifies.
    All data feeds into the Knowledge Core.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    @property
    def name(self) -> str:
        return "symbiotic_layer"

    async def scan(self) -> EnvironmentSnapshot:
        """Perform a complete environment scan."""
        from intent_kernel.types import utcnow

        system = self._scan_system()
        snapshot = EnvironmentSnapshot(
            system=system,
            python_environments=self._scan_python_envs(),
            docker_containers=self._scan_docker(),
            installed_programs=self._scan_programs(),
            system_services=self._scan_services(),
            environment_vars=self._scan_env_vars(),
            external_disks=self._scan_disks(),
            printers=self._scan_printers(),
            key_directories=self._scan_directories(),
            timestamp=utcnow().isoformat(),
        )

        return snapshot

    async def sync_to_knowledge_core(self, snapshot: EnvironmentSnapshot) -> dict:
        """Send environment snapshot to Knowledge Core via Kernel."""
        if not self.kernel:
            return {"error": "Kernel not connected"}

        from intent_kernel.pkb.models import KnowledgeEvent
        from intent_kernel.types import EventType, Domain

        events = []

        # System info as a FACT
        sys_event = KnowledgeEvent(
            type=EventType.FACT,
            domain=Domain.OTHER,
            title=f"Sistema: {snapshot.system.os_name} {snapshot.system.os_version}",
            content={
                "os": snapshot.system.os_name,
                "os_version": snapshot.system.os_version,
                "arch": snapshot.system.os_arch,
                "cpu_count": snapshot.system.cpu_count,
                "ram_gb": snapshot.system.ram_total_gb,
                "python": snapshot.system.python_version,
            },
            summary=f"{snapshot.system.os_name} {snapshot.system.os_version} | {snapshot.system.cpu_count} CPUs | {snapshot.system.ram_total_gb}GB RAM",
            confidence=1.0,
            source="symbiotic_layer",
            tags=["symbiotic", "system", "environment"],
        )
        events.append(sys_event)

        # Docker containers as CONTEXT
        if snapshot.docker_containers:
            docker_event = KnowledgeEvent(
                type=EventType.CONTEXT if hasattr(EventType, 'CONTEXT') else EventType.FACT,
                domain=Domain.ENGINEERING,
                title=f"Docker: {len(snapshot.docker_containers)} containers",
                content={"containers": snapshot.docker_containers},
                summary=f"{len(snapshot.docker_containers)} containers Docker ativos",
                confidence=0.9,
                source="symbiotic_layer",
                tags=["symbiotic", "docker", "containers"],
            )
            events.append(docker_event)

        # Python environments as FACT
        if snapshot.python_environments:
            py_event = KnowledgeEvent(
                type=EventType.FACT,
                domain=Domain.ENGINEERING,
                title=f"Python: {len(snapshot.python_environments)} ambientes",
                content={"environments": snapshot.python_environments},
                summary=f"{len(snapshot.python_environments)} ambientes Python detectados",
                confidence=1.0,
                source="symbiotic_layer",
                tags=["symbiotic", "python", "environments"],
            )
            events.append(py_event)

        # Installed programs as FACT
        if snapshot.installed_programs:
            prog_event = KnowledgeEvent(
                type=EventType.FACT,
                domain=Domain.OTHER,
                title=f"Programas: {len(snapshot.installed_programs)} instalados",
                content={"programs": snapshot.installed_programs[:50]},  # limit
                summary=f"{len(snapshot.installed_programs)} programas detectados no sistema",
                confidence=0.8,
                source="symbiotic_layer",
                tags=["symbiotic", "programs", "installed"],
            )
            events.append(prog_event)

        if events:
            result = await self.kernel.knowledge.ingest(events)
            return {"synced": True, "events_created": result.approved + result.candidate}

        return {"synced": True, "events_created": 0}

    # -------------------------------------------------------------------
    # Scanning methods — all read-only, non-invasive
    # -------------------------------------------------------------------

    def _scan_system(self) -> SystemInfo:
        """Scan basic system information."""
        info = SystemInfo(
            os_name=platform.system(),
            os_version=platform.version(),
            os_arch=platform.machine(),
            hostname=platform.node(),
            python_version=sys.version.split()[0],
            python_path=sys.executable,
            cpu_count=os.cpu_count() or 0,
        )

        # CPU model (platform-specific)
        try:
            if platform.system() == "Linux":
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if "model name" in line:
                            info.cpu_model = line.split(":")[1].strip()
                            break
            elif platform.system() == "Darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=5
                )
                info.cpu_model = result.stdout.strip()
        except Exception:
            info.cpu_model = "Unknown"

        # RAM
        try:
            if platform.system() == "Linux":
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemTotal" in line:
                            info.ram_total_gb = int(line.split()[1]) / 1048576
                        elif "MemAvailable" in line:
                            info.ram_available_gb = int(line.split()[1]) / 1048576
            elif platform.system() == "Darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5
                )
                info.ram_total_gb = int(result.stdout.strip()) / (1024**3)
        except Exception:
            pass

        return info

    def _scan_python_envs(self) -> list[dict]:
        """Detect Python virtual environments."""
        envs = []
        # Check common locations
        check_paths = [
            Path.home() / ".venvs",
            Path.home() / "venvs",
            Path.home() / ".local/share/virtualenvs",
            Path.cwd() / ".venv",
            Path.cwd() / "venv",
        ]

        for path in check_paths:
            if path.exists():
                for item in path.iterdir():
                    if item.is_dir() and (item / "pyvenv.cfg").exists():
                        envs.append({
                            "name": item.name,
                            "path": str(item),
                            "type": "venv",
                        })

        # Check conda
        try:
            result = subprocess.run(
                ["conda", "env", "list", "--json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                for env in data.get("envs", []):
                    envs.append({
                        "name": Path(env).name,
                        "path": env,
                        "type": "conda",
                    })
        except Exception:
            pass

        return envs

    def _scan_docker(self) -> list[dict]:
        """Detect Docker containers."""
        containers = []
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 3:
                            containers.append({
                                "name": parts[0],
                                "image": parts[1],
                                "status": parts[2],
                            })
        except Exception:
            pass
        return containers

    def _scan_programs(self) -> list[str]:
        """Detect commonly installed programs."""
        programs = []
        check_commands = [
            "git", "docker", "node", "npm", "python3", "python",
            "code", "cursor", "nvim", "vim", "ffmpeg", "curl", "wget",
            "java", "gradle", "mvn", "rustc", "cargo", "go",
            "blender", "freecad", "openscad",
        ]
        for cmd in check_commands:
            try:
                result = subprocess.run(
                    ["which", cmd], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    programs.append(cmd)
            except Exception:
                pass
        return programs

    def _scan_services(self) -> list[str]:
        """Detect running system services (Linux only)."""
        services = []
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[:20]:  # limit
                    parts = line.split()
                    if parts:
                        services.append(parts[0].replace(".service", ""))
        except Exception:
            pass
        return services

    def _scan_env_vars(self) -> dict[str, str]:
        """Capture relevant environment variables."""
        relevant = [
            "PATH", "HOME", "SHELL", "EDITOR", "LANG", "LC_ALL",
            "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
            "DOCKER_HOST", "KUBECONFIG",
            "HTTP_PROXY", "HTTPS_PROXY",
        ]
        return {k: v for k, v in os.environ.items() if k in relevant}

    def _scan_disks(self) -> list[dict]:
        """Detect mounted disks."""
        disks = []
        try:
            result = subprocess.run(
                ["df", "-h", "--output=source,size,used,avail,target"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 5 and not parts[0].startswith("tmpfs"):
                        disks.append({
                            "device": parts[0],
                            "size": parts[1],
                            "used": parts[2],
                            "available": parts[3],
                            "mount": parts[4],
                        })
        except Exception:
            pass
        return disks

    def _scan_printers(self) -> list[str]:
        """Detect printers."""
        printers = []
        try:
            result = subprocess.run(
                ["lpstat", "-p"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.startswith("printer"):
                        parts = line.split()
                        if len(parts) >= 2:
                            printers.append(parts[1])
        except Exception:
            pass
        return printers

    def _scan_directories(self) -> list[dict]:
        """Scan key directories."""
        dirs = []
        home = Path.home()
        check_dirs = [
            ("Documents", home / "Documents"),
            ("Desktop", home / "Desktop"),
            ("Downloads", home / "Downloads"),
            ("Projects", home / "Projects"),
            ("Docker", home / "Docker"),
        ]
        for name, path in check_dirs:
            if path.exists():
                try:
                    items = list(path.iterdir())[:10]
                    dirs.append({
                        "name": name,
                        "path": str(path),
                        "exists": True,
                        "items_count": len(list(path.iterdir())),
                        "sample": [i.name for i in items[:5]],
                    })
                except PermissionError:
                    dirs.append({"name": name, "path": str(path), "exists": True, "items_count": -1})
        return dirs
