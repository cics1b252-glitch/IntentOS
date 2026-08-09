"""Intent OS Local Root — persistent local memory via expandable text files.

The Intent OS installs itself as a layer above the OS.
All intelligence is stored locally in simple text files.
No cloud accounts needed — everything is self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import hashlib


@dataclass
class MemoryEntry:
    """A single memory entry in the text-based memory."""
    id: str = ""
    timestamp: str = ""
    category: str = ""  # decision, preference, context, learning, pattern
    content: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)


class LocalRoot:
    """Intent OS local root — ~/.intent-os/

    Structure:
    ~/.intent-os/
    ├── identity.json          # KC Identity
    ├── memory.md              # Persistent memory (expandable text)
    ├── decisions.md           # Decisions log
    ├── patterns.md            # Detected patterns
    ├── preferences.md         # User preferences
    ├── context.md             # Current context
    ├── projects/              # Project files
    ├── knowledge/             # Knowledge entries
    ├── backups/               # Backup files
    ├── cache/                 # Temporary cache
    └── config.json            # Configuration
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or Path.home() / ".intent-os")
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Create directory structure if not exists."""
        (self.root / "projects").mkdir(exist_ok=True)
        (self.root / "knowledge").mkdir(exist_ok=True)
        (self.root / "backups").mkdir(exist_ok=True)
        (self.root / "cache").mkdir(exist_ok=True)

        # Create memory files if not exist
        for filename in ["memory.md", "decisions.md", "patterns.md", "preferences.md", "context.md"]:
            filepath = self.root / filename
            if not filepath.exists():
                filepath.write_text(f"# Intent OS — {filename.replace('.md', '').title()}\n\n")

    # -------------------------------------------------------------------
    # Memory (expandable text file)
    # -------------------------------------------------------------------

    def read_memory(self) -> str:
        """Read the full memory file."""
        return (self.root / "memory.md").read_text()

    def append_memory(self, entry: MemoryEntry) -> None:
        """Append a memory entry to the text file."""
        timestamp = entry.timestamp or datetime.now(timezone.utc).isoformat()
        tags = ", ".join(entry.tags) if entry.tags else ""
        line = f"- [{timestamp}] [{entry.category}] {entry.content}"
        if entry.source:
            line += f" (fonte: {entry.source})"
        if tags:
            line += f" [{tags}]"
        line += "\n"

        with open(self.root / "memory.md", "a") as f:
            f.write(line)

    def search_memory(self, query: str) -> list[str]:
        """Search memory file for matching lines."""
        query_lower = query.lower()
        results = []
        for line in self.read_memory().split("\n"):
            if query_lower in line.lower():
                results.append(line.strip())
        return results

    def get_memory_stats(self) -> dict:
        """Get memory statistics."""
        content = self.read_memory()
        lines = [l for l in content.split("\n") if l.strip().startswith("- [")]
        return {
            "total_entries": len(lines),
            "file_size_bytes": len(content.encode()),
            "file_path": str(self.root / "memory.md"),
        }

    # -------------------------------------------------------------------
    # Decisions
    # -------------------------------------------------------------------

    def record_decision(self, question: str, chosen: str, alternatives: list[str], rationale: str) -> None:
        line = f"- [{datetime.now(timezone.utc).isoformat()}] {question}\n"
        line += f"  Escolha: {chosen}\n"
        if alternatives:
            line += f"  Alternativas: {', '.join(alternatives)}\n"
        line += f"  Raciocínio: {rationale}\n\n"

        with open(self.root / "decisions.md", "a") as f:
            f.write(line)

    def read_decisions(self) -> str:
        return (self.root / "decisions.md").read_text()

    # -------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------

    def save_preference(self, key: str, value: str) -> None:
        line = f"- {key}: {value}\n"
        with open(self.root / "preferences.md", "a") as f:
            f.write(line)

    def read_preferences(self) -> str:
        return (self.root / "preferences.md").read_text()

    def get_preference(self, key: str) -> str | None:
        for line in self.read_preferences().split("\n"):
            if line.strip().startswith(f"- {key}:"):
                return line.split(":", 1)[1].strip()
        return None

    # -------------------------------------------------------------------
    # Patterns
    # -------------------------------------------------------------------

    def record_pattern(self, pattern: str, confidence: float = 0.8) -> None:
        line = f"- [{datetime.now(timezone.utc).isoformat()}] {pattern} (confiança: {confidence:.0%})\n"
        with open(self.root / "patterns.md", "a") as f:
            f.write(line)

    def read_patterns(self) -> str:
        return (self.root / "patterns.md").read_text()

    # -------------------------------------------------------------------
    # Context
    # -------------------------------------------------------------------

    def save_context(self, key: str, value: str) -> None:
        """Save current context (overwrites if exists)."""
        lines = []
        found = False
        if (self.root / "context.md").exists():
            for line in (self.root / "context.md").read_text().split("\n"):
                if line.strip().startswith(f"- {key}:"):
                    lines.append(f"- {key}: {value}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"- {key}: {value}")

        (self.root / "context.md").write_text("\n".join(lines) + "\n")

    def read_context(self) -> str:
        return (self.root / "context.md").read_text()

    # -------------------------------------------------------------------
    # Knowledge entries
    # -------------------------------------------------------------------

    def save_knowledge(self, key: str, content: str, category: str = "general") -> None:
        filepath = self.root / "knowledge" / f"{key}.md"
        header = f"# {key}\n\nCategoria: {category}\nCriado: {datetime.now(timezone.utc).isoformat()}\n\n"
        filepath.write_text(header + content)

    def read_knowledge(self, key: str) -> str | None:
        filepath = self.root / "knowledge" / f"{key}.md"
        if filepath.exists():
            return filepath.read_text()
        return None

    def list_knowledge(self) -> list[str]:
        return [f.stem for f in (self.root / "knowledge").glob("*.md")]

    # -------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------

    def save_config(self, config: dict) -> None:
        (self.root / "config.json").write_text(json.dumps(config, indent=2))

    def load_config(self) -> dict:
        config_path = self.root / "config.json"
        if config_path.exists():
            return json.loads(config_path.read_text())
        return {}

    # -------------------------------------------------------------------
    # Identity
    # -------------------------------------------------------------------

    def get_identity(self) -> dict:
        identity_path = self.root / "identity.json"
        if identity_path.exists():
            return json.loads(identity_path.read_text())
        return {}

    def save_identity(self, identity: dict) -> None:
        (self.root / "identity.json").write_text(json.dumps(identity, indent=2))

    # -------------------------------------------------------------------
    # System status
    # -------------------------------------------------------------------

    def status(self) -> dict:
        """Get local root status."""
        total_files = len(list(self.root.rglob("*")))
        total_size = sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
        return {
            "root": str(self.root),
            "total_files": total_files,
            "total_size_bytes": total_size,
            "memory": self.get_memory_stats(),
            "knowledge_count": len(self.list_knowledge()),
        }
