"""PersistenceEngine — abstraction layer for storage backends.

Based on the Architectural Directive v1.1:
- Kernel must work without any specific database
- PersistenceEngine is an interface, not an implementation
- Implementations: JsonFile, PostgreSQL, SQLite, Cloud (future)

This is the third official interface alongside KnowledgeStore and ProviderManager.

C1-A additions:
- AtomicJsonFilePersistenceEngine: crash-safe atomic writes with schema envelope
- SchemaVersionEnvelope: versioned payload wrapper with checksum
- PersistenceError: typed error for corruption/failure detection
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import tempfile
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# C1-A: Typed persistence errors
# ---------------------------------------------------------------------------

class PersistenceError(Exception):
    """Raised when persistence operations encounter unrecoverable errors."""

    def __init__(self, message: str, *, path: str | None = None, cause: Exception | None = None):
        self.path = path
        self.cause = cause
        super().__init__(message)


class CorruptionError(PersistenceError):
    """Raised when persisted data is corrupted and cannot be recovered."""


class SchemaVersionError(PersistenceError):
    """Raised when schema version is unsupported or missing."""


# ---------------------------------------------------------------------------
# C1-A: Schema version envelope
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 1


class SchemaVersionEnvelope:
    """Versioned payload wrapper for durable persistence.

    Envelope format:
        {
            "schema_version": int,
            "written_at": str (ISO 8601 UTC),
            "payload": <actual data>
        }

    This class handles serialization, deserialization, and validation.
    It does NOT decide authorization, activation, or any canonical semantics.
    """

    __slots__ = ("schema_version", "written_at", "payload")

    def __init__(self, payload: dict, *, schema_version: int = CURRENT_SCHEMA_VERSION,
                 written_at: str | None = None):
        self.schema_version = schema_version
        self.written_at = written_at or datetime.now(timezone.utc).isoformat()
        self.payload = payload

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "written_at": self.written_at,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaVersionEnvelope":
        if not isinstance(data, dict):
            raise SchemaVersionError(f"Expected dict, got {type(data).__name__}")
        if "schema_version" not in data:
            raise SchemaVersionError("Missing required field: schema_version")
        version = data["schema_version"]
        if not isinstance(version, int):
            raise SchemaVersionError(f"schema_version must be int, got {type(version).__name__}")
        if version > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Unsupported schema_version {version} > current {CURRENT_SCHEMA_VERSION}. "
                "Cannot read future schema."
            )
        if "payload" not in data:
            raise SchemaVersionError("Missing required field: payload")
        return cls(
            payload=data["payload"],
            schema_version=version,
            written_at=data.get("written_at"),
        )

    def checksum(self) -> str:
        """SHA-256 checksum of the serialized payload."""
        payload_bytes = json.dumps(self.payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def to_bytes(self) -> bytes:
        """Serialize the full envelope to UTF-8 JSON bytes."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "SchemaVersionEnvelope":
        """Deserialize from UTF-8 JSON bytes."""
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CorruptionError(f"Failed to decode JSON: {e}", cause=e) from e
        return cls.from_dict(parsed)

    @classmethod
    def compute_checksum(cls, payload: dict) -> str:
        """Compute checksum for a payload without creating an envelope."""
        payload_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()


# ---------------------------------------------------------------------------
# C1-A: AtomicJsonFilePersistenceEngine
# ---------------------------------------------------------------------------

class AtomicJsonFilePersistenceEngine:
    """Crash-safe file-backed persistence engine using atomic writes.

    Guarantees:
        - ATOMIC WRITE: writes to temp file, then os.replace() to target
        - CRASH SAFETY: failed write leaves old valid state or new valid state
        - SCHEMA VERSION: every write wrapped in SchemaVersionEnvelope
        - CHECKSUM: SHA-256 of payload for corruption detection
        - LOCKING: threading.Lock for in-process thread safety
        - CORRUPTION RECOVERY: attempts .bak file fallback on corruption
        - NO SILENT DATA LOSS: corrupted state raises CorruptionError

    Does NOT guarantee:
        - Cross-process safety (uses threading.Lock, not file locks)
        - fsync to disk (OS may buffer)
        - Authority semantics (stores data only, no authorization logic)

    This engine stores/retrieves data. It MUST NOT decide:
        authorization, activation, registration, retirement, binding,
        verification, completion, or trust.
    """

    def __init__(self, file_path: str, *, auto_migrate: bool = True):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._ops_count = 0
        self._auto_migrate = auto_migrate
        self._in_memory_cache: dict[str, dict] | None = None

    @property
    def backend_type(self) -> str:
        return "atomic_json_file"

    def _ensure_directory(self) -> None:
        dir_name = os.path.dirname(self.file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def _atomic_replace(self, temp_path: str) -> None:
        """Atomically replace target file with temp file.

        On Windows, os.replace() is atomic when source and target are on
        the same volume. On POSIX, it is always atomic.
        """
        os.replace(temp_path, self.file_path)

    def _backup_path(self) -> str:
        return self.file_path + ".bak"

    def _load_raw(self) -> dict:
        """Load the raw envelope from disk. Raises on corruption."""
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except (OSError, IOError) as e:
            raise PersistenceError(
                f"Failed to read {self.file_path}: {e}",
                path=self.file_path, cause=e,
            ) from e

        if not raw.strip():
            raise CorruptionError(
                f"Empty file: {self.file_path}",
                path=self.file_path,
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CorruptionError(
                f"Malformed JSON in {self.file_path}: {e}",
                path=self.file_path, cause=e,
            ) from e

        if not isinstance(data, dict):
            raise CorruptionError(
                f"Expected dict at top level in {self.file_path}, got {type(data).__name__}",
                path=self.file_path,
            )

        envelope = SchemaVersionEnvelope.from_dict(data)
        return envelope.payload

    def _load_with_recovery(self) -> dict:
        """Load with corruption recovery: try main file, then .bak."""
        try:
            return self._load_raw()
        except (CorruptionError, SchemaVersionError):
            bak_path = self._backup_path()
            if os.path.exists(bak_path):
                try:
                    with open(bak_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                    data = json.loads(raw)
                    envelope = SchemaVersionEnvelope.from_dict(data)
                    return envelope.payload
                except Exception:
                    pass
            raise

    def _save_atomic(self, data: dict) -> None:
        """Atomically save data with envelope wrapping."""
        envelope = SchemaVersionEnvelope(data)
        envelope_bytes = envelope.to_bytes()

        self._ensure_directory()

        dir_name = os.path.dirname(self.file_path) or "."
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".persistence_",
                dir=dir_name,
            )
            try:
                os.write(fd, envelope_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)

            if os.path.exists(self.file_path):
                bak_path = self._backup_path()
                try:
                    if os.path.exists(bak_path):
                        os.remove(bak_path)
                    os.replace(self.file_path, bak_path)
                except OSError:
                    pass

            self._atomic_replace(temp_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise

    def _load(self) -> dict[str, dict]:
        """Load the database (backwards-compatible with old callers)."""
        return self._load_with_recovery()

    def _save(self, data: dict[str, dict]) -> None:
        """Save the database (backwards-compatible with old callers)."""
        self._save_atomic(data)

    async def read(self, key: str) -> dict | None:
        with self._lock:
            self._ops_count += 1
            data = self._load_with_recovery()
            return data.get(key)

    async def write(self, key: str, data: dict) -> bool:
        with self._lock:
            self._ops_count += 1
            db = self._load_with_recovery()
            db[key] = data
            self._save_atomic(db)
            return True

    async def delete(self, key: str) -> bool:
        with self._lock:
            self._ops_count += 1
            db = self._load_with_recovery()
            if key in db:
                del db[key]
                self._save_atomic(db)
                return True
            return False

    async def exists(self, key: str) -> bool:
        with self._lock:
            db = self._load_with_recovery()
            return key in db

    async def query(
        self,
        prefix: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            db = self._load_with_recovery()
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
        with self._lock:
            db = self._load_with_recovery()
            if not prefix:
                return len(db)
            return sum(1 for k in db if k.startswith(prefix))

    async def export_all(self, format: str = "json") -> bytes:
        with self._lock:
            db = self._load_with_recovery()
            if format == "json":
                return json.dumps(db, indent=2, ensure_ascii=False).encode("utf-8")
            elif format == "jsonl":
                lines = [json.dumps(v, ensure_ascii=False) for v in db.values()]
                return "\n".join(lines).encode("utf-8")
            raise ValueError(f"Unsupported format: {format}")

    async def import_data(self, data: bytes, format: str = "json") -> int:
        with self._lock:
            db = self._load_with_recovery()
            if format == "json":
                imported = json.loads(data)
                count = 0
                for key, value in imported.items():
                    db[key] = value
                    count += 1
                self._save_atomic(db)
                return count
            elif format == "jsonl":
                count = 0
                for line in data.decode().strip().split("\n"):
                    if line:
                        record = json.loads(line)
                        key = record.get("id", f"imported-{count}")
                        db[key] = record
                        count += 1
                self._save_atomic(db)
                return count
            raise ValueError(f"Unsupported format: {format}")

    async def clear(self) -> bool:
        with self._lock:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
            bak_path = self._backup_path()
            if os.path.exists(bak_path):
                os.remove(bak_path)
            return True

    async def health_check(self) -> dict[str, Any]:
        with self._lock:
            try:
                db = self._load_with_recovery()
                healthy = True
            except Exception:
                db = {}
                healthy = False
            return {
                "backend": self.backend_type,
                "healthy": healthy,
                "records": len(db),
                "operations_count": self._ops_count,
            }

    def read_sync(self, key: str) -> dict | None:
        """Synchronous read for use outside async contexts."""
        with self._lock:
            self._ops_count += 1
            data = self._load_with_recovery()
            return data.get(key)

    def write_sync(self, key: str, data: dict) -> bool:
        """Synchronous write for use outside async contexts."""
        with self._lock:
            self._ops_count += 1
            db = self._load_with_recovery()
            db[key] = data
            self._save_atomic(db)
            return True

    def delete_sync(self, key: str) -> bool:
        """Synchronous delete for use outside async contexts."""
        with self._lock:
            self._ops_count += 1
            db = self._load_with_recovery()
            if key in db:
                del db[key]
                self._save_atomic(db)
                return True
            return False

