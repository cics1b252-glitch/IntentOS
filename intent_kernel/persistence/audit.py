"""JSONL append-only audit log writer (C1-A).

This module provides a durable, append-only audit log for recording
canonical lifecycle events. It is pure evidence/history recording.

INVARIANT:
    AUDIT HISTORY != CURRENT CANONICAL STATE

The audit log is never consulted for authority decisions.
It is append-only: previous entries are never rewritten.
Each line is independently parseable JSON (JSONL format).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

AUDIT_LOG_SCHEMA_VERSION = 1


class AuditLogError(Exception):
    """Raised when audit log operations fail."""


class JsonlAuditLogWriter:
    """Append-only JSONL audit log writer.

    Guarantees:
        - APPEND-ONLY: never rewrites previous entries
        - THREAD-SAFE: threading.Lock protects concurrent writes
        - ONE EVENT PER LINE: each line is independently parseable JSON
        - SCHEMA VERSION: every entry includes schema_version
        - EVENT ID: every entry gets a unique UUID
        - TIMESTAMP: every entry gets ISO 8601 UTC timestamp
        - VALIDATION: malformed events rejected before append

    Does NOT:
        - Decide what events are canonical
        - Grant authority
        - Become runtime state after restart
        - Support replay as authority
    """

    def __init__(self, log_path: str):
        self.log_path = log_path
        self._lock = threading.Lock()
        self._write_count = 0

    def _ensure_directory(self) -> None:
        dir_name = os.path.dirname(self.log_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def _validate_event(self, event: dict) -> None:
        """Validate event structure before append."""
        if not isinstance(event, dict):
            raise AuditLogError(f"Event must be dict, got {type(event).__name__}")
        if "event_type" not in event:
            raise AuditLogError("Event missing required field: event_type")
        if not isinstance(event["event_type"], str):
            raise AuditLogError("event_type must be a string")
        if not event["event_type"].strip():
            raise AuditLogError("event_type must not be empty")

    def _format_entry(self, event: dict) -> str:
        """Format an event as a JSONL entry with metadata."""
        entry = {
            "schema_version": AUDIT_LOG_SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "event_type": event["event_type"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {k: v for k, v in event.items() if k != "event_type"},
        }
        return json.dumps(entry, ensure_ascii=False, sort_keys=False)

    def append(self, event: dict) -> str:
        """Append an event to the audit log.

        Returns the event_id of the appended entry.

        Raises AuditLogError if the event is malformed.
        Raises AuditLogError if the write fails.
        """
        self._validate_event(event)
        entry_line = self._format_entry(event)
        event_id = json.loads(entry_line)["event_id"]

        with self._lock:
            self._ensure_directory()
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(entry_line + "\n")
                    f.flush()
                self._write_count += 1
            except (OSError, IOError) as e:
                raise AuditLogError(
                    f"Failed to write audit event to {self.log_path}: {e}",
                ) from e

        return event_id

    def read_all(self) -> list[dict]:
        """Read all entries from the audit log.

        Returns a list of parsed JSON entries.
        Malformed lines are skipped (not silently treated as empty).
        """
        if not os.path.exists(self.log_path):
            return []

        entries = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except (OSError, IOError) as e:
            raise AuditLogError(
                f"Failed to read audit log {self.log_path}: {e}",
            ) from e

        return entries

    def read_by_type(self, event_type: str) -> list[dict]:
        """Read entries filtered by event_type."""
        return [
            entry for entry in self.read_all()
            if entry.get("event_type") == event_type
        ]

    def count(self) -> int:
        """Count total entries in the audit log."""
        if not os.path.exists(self.log_path):
            return 0
        count = 0
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
        except (OSError, IOError):
            return 0
        return count

    def clear(self) -> bool:
        """Clear the audit log. Use with caution."""
        with self._lock:
            if os.path.exists(self.log_path):
                os.remove(self.log_path)
            self._write_count = 0
            return True

    @property
    def write_count(self) -> int:
        return self._write_count
