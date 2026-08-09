"""PersistenceEngine — abstraction layer for storage backends.

Based on the Architectural Directive v1.1:
- Kernel must work without any specific database
- PersistenceEngine is an interface, not an implementation
- Implementations: JsonFile, PostgreSQL, SQLite, Cloud (future)

This is the third official interface alongside KnowledgeStore and ProviderManager.
"""

from __future__ import annotations

from typing import Protocol, Any


class PersistenceEngine(Protocol):
    """Abstract interface for persistence backends.

    Every KnowledgeStore implementation should be backed by a PersistenceEngine.
    The PersistenceEngine handles raw read/write; the KnowledgeStore handles
    Knowledge Event semantics (versioning, lifecycle, etc).

    Why this exists (Directive question 1):
        Decouples the Kernel from any specific storage technology.

    Which principle it protects (Directive question 2):
        Continuity — knowledge survives technological changes.
        Knowledge Heritage — data is exportable and portable.

    How it's observed by the Monitor (Directive question 3):
        Each engine reports: backend_type, health, storage_used, operations_count.
    """

    @property
    def backend_type(self) -> str:
        """Type of backend: 'json_file', 'postgresql', 'sqlite', 'memory'."""
        ...

    async def read(self, key: str) -> dict | None:
        """Read a record by key."""
        ...

    async def write(self, key: str, data: dict) -> bool:
        """Write a record. Returns success."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete a record. Returns success."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if a record exists."""
        ...

    async def query(
        self,
        prefix: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query records with optional prefix and filters."""
        ...

    async def count(self, prefix: str = "") -> int:
        """Count records with optional prefix."""
        ...

    async def export_all(self, format: str = "json") -> bytes:
        """Export all data in the specified format.

        Must support at minimum: 'json', 'jsonl'.
        Knowledge Heritage Guardian validates this.
        """
        ...

    async def import_data(self, data: bytes, format: str = "json") -> int:
        """Import data. Returns number of records imported."""
        ...

    async def clear(self) -> bool:
        """Clear all data. Returns success.

        Soberania Guardian: this is a real delete, not mark-as-delete.
        """
        ...

    async def health_check(self) -> dict[str, Any]:
        """Check engine health. Returns status dict for Monitor."""
        ...


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------

class MemoryPersistenceEngine:
    """In-memory persistence engine (for testing)."""

    def __init__(self):
        self._data: dict[str, dict] = {}
        self._ops_count = 0

    @property
    def backend_type(self) -> str:
        return "memory"

    async def read(self, key: str) -> dict | None:
        self._ops_count += 1
        return self._data.get(key)

    async def write(self, key: str, data: dict) -> bool:
        self._ops_count += 1
        self._data[key] = data
        return True

    async def delete(self, key: str) -> bool:
        self._ops_count += 1
        if key in self._data:
            del self._data[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        return key in self._data

    async def query(
        self,
        prefix: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results = []
        for key, data in self._data.items():
            if prefix and not key.startswith(prefix):
                continue
            if filters:
                match = all(data.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            results.append(data)
            if len(results) >= limit:
                break
        return results

    async def count(self, prefix: str = "") -> int:
        if not prefix:
            return len(self._data)
        return sum(1 for k in self._data if k.startswith(prefix))

    async def export_all(self, format: str = "json") -> bytes:
        import json
        if format == "json":
            return json.dumps(self._data, indent=2).encode()
        elif format == "jsonl":
            lines = [json.dumps(v) for v in self._data.values()]
            return "\n".join(lines).encode()
        raise ValueError(f"Unsupported format: {format}")

    async def import_data(self, data: bytes, format: str = "json") -> int:
        import json
        if format == "json":
            imported = json.loads(data)
            count = 0
            for key, value in imported.items():
                self._data[key] = value
                count += 1
            return count
        elif format == "jsonl":
            count = 0
            for line in data.decode().strip().split("\n"):
                if line:
                    record = json.loads(line)
                    key = record.get("id", f"imported-{count}")
                    self._data[key] = record
                    count += 1
            return count
        raise ValueError(f"Unsupported format: {format}")

    async def clear(self) -> bool:
        self._data.clear()
        return True

    async def health_check(self) -> dict[str, Any]:
        return {
            "backend": self.backend_type,
            "healthy": True,
            "records": len(self._data),
            "operations_count": self._ops_count,
        }


class JsonFilePersistenceEngine:
    """File-backed persistence engine using JSON storage on disk."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._ops_count = 0

    @property
    def backend_type(self) -> str:
        return "json_file"

    def _load(self) -> dict[str, dict]:
        import os
        import json
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data: dict[str, dict]):
        import os
        import json
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    async def read(self, key: str) -> dict | None:
        self._ops_count += 1
        data = self._load()
        return data.get(key)

    async def write(self, key: str, data: dict) -> bool:
        self._ops_count += 1
        db = self._load()
        db[key] = data
        self._save(db)
        return True

    async def delete(self, key: str) -> bool:
        self._ops_count += 1
        db = self._load()
        if key in db:
            del db[key]
            self._save(db)
            return True
        return False

    async def exists(self, key: str) -> bool:
        db = self._load()
        return key in db

    async def query(
        self,
        prefix: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        db = self._load()
        results = []
        for key, record in db.items():
            if prefix and not key.startswith(prefix):
                continue
            if filters:
                match = all(record.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    async def count(self, prefix: str = "") -> int:
        db = self._load()
        if not prefix:
            return len(db)
        return sum(1 for k in db if k.startswith(prefix))

    async def export_all(self, format: str = "json") -> bytes:
        import json
        db = self._load()
        if format == "json":
            return json.dumps(db, indent=2).encode()
        elif format == "jsonl":
            lines = [json.dumps(v) for v in db.values()]
            return "\n".join(lines).encode()
        raise ValueError(f"Unsupported format: {format}")

    async def import_data(self, data: bytes, format: str = "json") -> int:
        import json
        db = self._load()
        if format == "json":
            imported = json.loads(data)
            count = 0
            for key, value in imported.items():
                db[key] = value
                count += 1
            self._save(db)
            return count
        elif format == "jsonl":
            count = 0
            for line in data.decode().strip().split("\n"):
                if line:
                    record = json.loads(line)
                    key = record.get("id", f"imported-{count}")
                    db[key] = record
                    count += 1
            self._save(db)
            return count
        raise ValueError(f"Unsupported format: {format}")

    async def clear(self) -> bool:
        import os
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
        return True

    async def health_check(self) -> dict[str, Any]:
        db = self._load()
        return {
            "backend": self.backend_type,
            "healthy": True,
            "records": len(db),
            "operations_count": self._ops_count,
        }

