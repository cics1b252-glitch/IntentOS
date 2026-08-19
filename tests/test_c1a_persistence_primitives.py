"""C1-A: Durable Persistence Primitives — Test Suite.

Tests for:
- AtomicJsonFilePersistenceEngine (atomic writes, crash safety, corruption)
- SchemaVersionEnvelope (versioning, checksum, round-trip)
- JsonlAuditLogWriter (append-only, validation, preservation)

Each test provides CLAIM, EVIDENCE, RESULT.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest

from intent_kernel.persistence import (
    AtomicJsonFilePersistenceEngine,
    CorruptionError,
    CURRENT_SCHEMA_VERSION,
    MemoryPersistenceEngine,
    PersistenceError,
    SchemaVersionEnvelope,
    SchemaVersionError,
)
from intent_kernel.persistence.audit import AUDIT_LOG_SCHEMA_VERSION, AuditLogError, JsonlAuditLogWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def engine(tmp_dir):
    path = os.path.join(tmp_dir, "test_store.json")
    return AtomicJsonFilePersistenceEngine(path)


@pytest.fixture
def audit_log(tmp_dir):
    path = os.path.join(tmp_dir, "audit.jsonl")
    return JsonlAuditLogWriter(path)


# ---------------------------------------------------------------------------
# SECTION 1: SchemaVersionEnvelope
# ---------------------------------------------------------------------------

class TestSchemaVersionEnvelope:
    """Tests for the schema version envelope."""

    def test_round_trip(self):
        """CLAIM: Envelope serializes and deserializes without data loss."""
        payload = {"key": "value", "nested": {"a": 1, "b": [2, 3]}}
        envelope = SchemaVersionEnvelope(payload)
        raw = envelope.to_bytes()
        restored = SchemaVersionEnvelope.from_bytes(raw)
        assert restored.payload == payload
        assert restored.schema_version == CURRENT_SCHEMA_VERSION
        assert restored.written_at is not None

    def test_checksum_deterministic(self):
        """CLAIM: Checksum is deterministic for same payload."""
        payload = {"x": 42, "y": "hello"}
        e1 = SchemaVersionEnvelope(payload)
        e2 = SchemaVersionEnvelope(payload)
        assert e1.checksum() == e2.checksum()

    def test_checksum_changes_with_payload(self):
        """CLAIM: Different payloads produce different checksums."""
        e1 = SchemaVersionEnvelope({"a": 1})
        e2 = SchemaVersionEnvelope({"a": 2})
        assert e1.checksum() != e2.checksum()

    def test_future_schema_version_rejected(self):
        """CLAIM: schema_version > current fails closed."""
        data = {
            "schema_version": CURRENT_SCHEMA_VERSION + 1,
            "written_at": "2026-01-01T00:00:00Z",
            "payload": {},
        }
        with pytest.raises(SchemaVersionError, match="Unsupported schema_version"):
            SchemaVersionEnvelope.from_dict(data)

    def test_missing_schema_version_rejected(self):
        """CLAIM: Missing schema_version fails explicitly."""
        data = {"payload": {}, "written_at": "2026-01-01T00:00:00Z"}
        with pytest.raises(SchemaVersionError, match="Missing required field: schema_version"):
            SchemaVersionEnvelope.from_dict(data)

    def test_missing_payload_rejected(self):
        """CLAIM: Missing payload fails explicitly."""
        data = {"schema_version": 1, "written_at": "2026-01-01T00:00:00Z"}
        with pytest.raises(SchemaVersionError, match="Missing required field: payload"):
            SchemaVersionEnvelope.from_dict(data)

    def test_malformed_json_rejected(self):
        """CLAIM: Malformed JSON bytes fail with CorruptionError."""
        with pytest.raises(CorruptionError, match="Failed to decode JSON"):
            SchemaVersionEnvelope.from_bytes(b"not json {{{")

    def test_non_dict_rejected(self):
        """CLAIM: Non-dict top-level value fails."""
        with pytest.raises(SchemaVersionError, match="Expected dict"):
            SchemaVersionEnvelope.from_dict([1, 2, 3])

    def test_empty_payload_valid(self):
        """CLAIM: Empty payload is valid."""
        envelope = SchemaVersionEnvelope({})
        raw = envelope.to_bytes()
        restored = SchemaVersionEnvelope.from_bytes(raw)
        assert restored.payload == {}

    def test_timestamp_round_trip_utc(self):
        """CLAIM: UTC timestamps survive serialization round-trip."""
        ts = "2026-08-18T12:30:45.123456+00:00"
        envelope = SchemaVersionEnvelope({}, written_at=ts)
        raw = envelope.to_bytes()
        restored = SchemaVersionEnvelope.from_bytes(raw)
        assert restored.written_at == ts

    def test_unicode_payload(self):
        """CLAIM: Unicode payloads survive round-trip."""
        payload = {"text": "日本語テスト", "emoji": "🔒", "accent": "café"}
        envelope = SchemaVersionEnvelope(payload)
        raw = envelope.to_bytes()
        restored = SchemaVersionEnvelope.from_bytes(raw)
        assert restored.payload == payload


# ---------------------------------------------------------------------------
# SECTION 2: AtomicJsonFilePersistenceEngine — happy path
# ---------------------------------------------------------------------------

class TestAtomicEngineHappyPath:
    """Tests for basic read/write operations."""

    @pytest.mark.asyncio
    async def test_write_and_read(self, engine):
        """CLAIM: write() persists data that read() returns."""
        result = await engine.write("key1", {"field": "value"})
        assert result is True
        data = await engine.read("key1")
        assert data == {"field": "value"}

    @pytest.mark.asyncio
    async def test_overwrite_old_to_new(self, engine):
        """CLAIM: Overwriting a key replaces old data with new data."""
        await engine.write("k", {"version": 1})
        await engine.write("k", {"version": 2})
        data = await engine.read("k")
        assert data == {"version": 2}

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, engine):
        """CLAIM: Reading a nonexistent key returns None."""
        data = await engine.read("no_such_key")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete(self, engine):
        """CLAIM: delete() removes a key."""
        await engine.write("k", {"v": 1})
        result = await engine.delete("k")
        assert result is True
        data = await engine.read("k")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, engine):
        """CLAIM: Deleting a nonexistent key returns False."""
        result = await engine.delete("no_such_key")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists(self, engine):
        """CLAIM: exists() reflects current state."""
        assert await engine.exists("k") is False
        await engine.write("k", {"v": 1})
        assert await engine.exists("k") is True
        await engine.delete("k")
        assert await engine.exists("k") is False

    @pytest.mark.asyncio
    async def test_count(self, engine):
        """CLAIM: count() returns accurate count."""
        await engine.write("a:1", {"v": 1})
        await engine.write("a:2", {"v": 2})
        await engine.write("b:1", {"v": 3})
        assert await engine.count() == 3
        assert await engine.count("a:") == 2
        assert await engine.count("b:") == 1
        assert await engine.count("c:") == 0

    @pytest.mark.asyncio
    async def test_query(self, engine):
        """CLAIM: query() filters by prefix and filters."""
        await engine.write("res:1", {"type": "provider", "name": "openai"})
        await engine.write("res:2", {"type": "capability", "name": "chat"})
        await engine.write("res:3", {"type": "provider", "name": "anthropic"})

        all_res = await engine.query("res:")
        assert len(all_res) == 3

        providers = await engine.query("res:", filters={"type": "provider"})
        assert len(providers) == 2

        limited = await engine.query("res:", limit=1)
        assert len(limited) == 1

    @pytest.mark.asyncio
    async def test_export_import_json(self, engine):
        """CLAIM: export/import round-trips data."""
        await engine.write("k1", {"a": 1})
        await engine.write("k2", {"b": 2})
        exported = await engine.export_all("json")
        assert isinstance(exported, bytes)

        engine2 = AtomicJsonFilePersistenceEngine(
            os.path.join(os.path.dirname(engine.file_path), "imported.json")
        )
        count = await engine2.import_data(exported, "json")
        assert count == 2
        assert await engine2.read("k1") == {"a": 1}
        assert await engine2.read("k2") == {"b": 2}

    @pytest.mark.asyncio
    async def test_clear(self, engine):
        """CLAIM: clear() removes all data."""
        await engine.write("k1", {"v": 1})
        await engine.write("k2", {"v": 2})
        await engine.clear()
        assert await engine.read("k1") is None
        assert await engine.read("k2") is None

    @pytest.mark.asyncio
    async def test_health_check(self, engine):
        """CLAIM: health_check() reports correct state."""
        await engine.write("k", {"v": 1})
        health = await engine.health_check()
        assert health["backend"] == "atomic_json_file"
        assert health["healthy"] is True
        assert health["records"] == 1

    @pytest.mark.asyncio
    async def test_sync_methods(self, engine):
        """CLAIM: Synchronous methods work correctly."""
        engine.write_sync("k", {"v": 1})
        data = engine.read_sync("k")
        assert data == {"v": 1}
        result = engine.delete_sync("k")
        assert result is True
        assert engine.read_sync("k") is None

    def test_backend_type(self, engine):
        """CLAIM: backend_type is 'atomic_json_file'."""
        assert engine.backend_type == "atomic_json_file"


# ---------------------------------------------------------------------------
# SECTION 3: AtomicJsonFilePersistenceEngine — atomicity & crash safety
# ---------------------------------------------------------------------------

class TestAtomicEngineAtomicity:
    """Tests for atomic write guarantees."""

    def test_file_contains_valid_envelope(self, engine):
        """CLAIM: On-disk file is always a valid SchemaVersionEnvelope."""
        engine.write_sync("k", {"v": 1})
        with open(engine.file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        assert "schema_version" in data
        assert "written_at" in data
        assert "payload" in data
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
        assert data["payload"] == {"k": {"v": 1}}

    def test_backup_created(self, engine):
        """CLAIM: Previous data is backed up before overwrite."""
        engine.write_sync("k", {"v": 1})
        assert not os.path.exists(engine._backup_path())
        engine.write_sync("k", {"v": 2})
        assert os.path.exists(engine._backup_path())
        bak = AtomicJsonFilePersistenceEngine(engine._backup_path())
        assert bak.read_sync("k") == {"v": 1}

    def test_no_temp_files_left_after_success(self, engine):
        """CLAIM: No temporary files remain after successful write."""
        engine.write_sync("k", {"v": 1})
        dir_name = os.path.dirname(engine.file_path)
        for f in os.listdir(dir_name):
            assert not f.startswith(".persistence_"), f"Leftover temp file: {f}"

    def test_write_failure_leaves_old_state(self, engine):
        """CLAIM: If write fails, old state is preserved."""
        engine.write_sync("k", {"v": 1})

        original_save = engine._save_atomic

        def failing_save(data):
            raise OSError("Simulated write failure")

        engine._save_atomic = failing_save
        with pytest.raises(OSError):
            engine.write_sync("k", {"v": 2})

        engine._save_atomic = original_save
        assert engine.read_sync("k") == {"v": 1}

    def test_unicode_preserved(self, engine):
        """CLAIM: Unicode data survives write/read cycle."""
        data = {
            "chinese": "你好世界",
            "japanese": "日本語テスト",
            "emoji": "🔐🛡️",
            "accented": "café résumé naïve",
            "arabic": "مرحبا",
        }
        engine.write_sync("unicode", data)
        result = engine.read_sync("unicode")
        assert result == data

    def test_nested_structure_preserved(self, engine):
        """CLAIM: Deeply nested structures survive write/read."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "list": [1, 2, {"nested": True}],
                        "string": "value",
                        "number": 42.5,
                        "null": None,
                        "bool": True,
                    }
                }
            }
        }
        engine.write_sync("nested", data)
        result = engine.read_sync("nested")
        assert result == data

    def test_deterministic_serialization(self, engine):
        """CLAIM: Same payload produces same checksum (deterministic JSON)."""
        data = {"b": 2, "a": 1, "c": [3, 4]}
        checksum1 = SchemaVersionEnvelope.compute_checksum(data)
        checksum2 = SchemaVersionEnvelope.compute_checksum(data)
        assert checksum1 == checksum2
        assert isinstance(checksum1, str)
        assert len(checksum1) == 64

    def test_large_payload(self, engine):
        """CLAIM: Large payloads work correctly."""
        data = {"items": [{"id": i, "value": f"item_{i}"} for i in range(1000)]}
        engine.write_sync("large", data)
        result = engine.read_sync("large")
        assert len(result["items"]) == 1000
        assert result["items"][0] == {"id": 0, "value": "item_0"}
        assert result["items"][999] == {"id": 999, "value": "item_999"}


# ---------------------------------------------------------------------------
# SECTION 4: Corruption tests
# ---------------------------------------------------------------------------

class TestAtomicEngineCorruption:
    """Adversarial corruption tests."""

    def test_empty_file(self, tmp_dir):
        """CLAIM: Empty file raises CorruptionError."""
        path = os.path.join(tmp_dir, "empty.json")
        with open(path, "w") as f:
            f.write("")
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(CorruptionError, match="Empty file"):
            engine.read_sync("k")

    def test_truncated_json(self, tmp_dir):
        """CLAIM: Truncated JSON raises CorruptionError."""
        path = os.path.join(tmp_dir, "truncated.json")
        with open(path, "w") as f:
            f.write('{"schema_version": 1, "written_at": "2026-01-01T00:00:00Z", "payload": {"k": {"v": 1}')
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(CorruptionError, match="Malformed JSON"):
            engine.read_sync("k")

    def test_malformed_json(self, tmp_dir):
        """CLAIM: Malformed JSON raises CorruptionError."""
        path = os.path.join(tmp_dir, "malformed.json")
        with open(path, "w") as f:
            f.write("this is not json {{{")
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(CorruptionError, match="Malformed JSON"):
            engine.read_sync("k")

    def test_missing_schema_version(self, tmp_dir):
        """CLAIM: Missing schema_version raises SchemaVersionError."""
        path = os.path.join(tmp_dir, "no_version.json")
        with open(path, "w") as f:
            json.dump({"payload": {"k": {"v": 1}}}, f)
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(SchemaVersionError, match="Missing required field: schema_version"):
            engine.read_sync("k")

    def test_unsupported_future_schema_version(self, tmp_dir):
        """CLAIM: Future schema_version raises SchemaVersionError."""
        path = os.path.join(tmp_dir, "future.json")
        with open(path, "w") as f:
            json.dump({
                "schema_version": CURRENT_SCHEMA_VERSION + 10,
                "written_at": "2099-01-01T00:00:00Z",
                "payload": {"k": {"v": 1}},
            }, f)
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(SchemaVersionError, match="Unsupported schema_version"):
            engine.read_sync("k")

    def test_missing_payload(self, tmp_dir):
        """CLAIM: Missing payload raises SchemaVersionError."""
        path = os.path.join(tmp_dir, "no_payload.json")
        with open(path, "w") as f:
            json.dump({"schema_version": 1, "written_at": "2026-01-01T00:00:00Z"}, f)
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(SchemaVersionError, match="Missing required field: payload"):
            engine.read_sync("k")

    def test_non_dict_top_level(self, tmp_dir):
        """CLAIM: Non-dict top-level value raises CorruptionError."""
        path = os.path.join(tmp_dir, "list.json")
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        engine = AtomicJsonFilePersistenceEngine(path)
        with pytest.raises(CorruptionError, match="Expected dict"):
            engine.read_sync("k")

    def test_missing_file_returns_none(self, engine):
        """CLAIM: Missing file returns None, not an error."""
        data = engine.read_sync("nonexistent")
        assert data is None

    def test_corruption_recovery_from_bak(self, tmp_dir):
        """CLAIM: On corruption, recovery falls back to .bak file."""
        path = os.path.join(tmp_dir, "store.json")
        engine = AtomicJsonFilePersistenceEngine(path)

        engine.write_sync("k", {"v": 1})
        engine.write_sync("k", {"v": 2})
        assert os.path.exists(engine._backup_path())

        with open(path, "w") as f:
            f.write("CORRUPTED DATA {{{")

        result = engine.read_sync("k")
        assert result == {"v": 1}


# ---------------------------------------------------------------------------
# SECTION 5: Concurrent access
# ---------------------------------------------------------------------------

class TestAtomicEngineConcurrency:
    """Thread safety tests."""

    def test_concurrent_writes(self, tmp_dir):
        """CLAIM: Concurrent writes do not corrupt data."""
        path = os.path.join(tmp_dir, "concurrent.json")
        engine = AtomicJsonFilePersistenceEngine(path)
        errors = []

        def writer(prefix, count):
            try:
                for i in range(count):
                    engine.write_sync(f"{prefix}:{i}", {"v": f"{prefix}_{i}"})
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(f"t{t}", 20))
            for t in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors}"
        db = engine._load_with_recovery()
        assert len(db) == 100

    def test_concurrent_read_write(self, tmp_dir):
        """CLAIM: Concurrent reads and writes do not corrupt data."""
        path = os.path.join(tmp_dir, "rw_concurrent.json")
        engine = AtomicJsonFilePersistenceEngine(path)
        engine.write_sync("shared", {"v": 0})
        errors = []

        def writer():
            try:
                for i in range(50):
                    engine.write_sync("shared", {"v": i})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    engine.read_sync("shared")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent read/write errors: {errors}"


# ---------------------------------------------------------------------------
# SECTION 6: JsonlAuditLogWriter
# ---------------------------------------------------------------------------

class TestJsonlAuditLogWriter:
    """Tests for the JSONL audit log writer."""

    def test_single_append(self, audit_log):
        """CLAIM: Single append writes a valid JSONL entry."""
        event_id = audit_log.append({"event_type": "TEST_EVENT", "data": "hello"})
        assert isinstance(event_id, str)
        assert len(event_id) > 0

        entries = audit_log.read_all()
        assert len(entries) == 1
        assert entries[0]["event_type"] == "TEST_EVENT"
        assert entries[0]["schema_version"] == AUDIT_LOG_SCHEMA_VERSION
        assert "event_id" in entries[0]
        assert "timestamp" in entries[0]

    def test_multiple_append(self, audit_log):
        """CLAIM: Multiple appends are preserved in order."""
        for i in range(10):
            audit_log.append({"event_type": f"EVENT_{i}", "index": i})

        entries = audit_log.read_all()
        assert len(entries) == 10
        for i, entry in enumerate(entries):
            assert entry["event_type"] == f"EVENT_{i}"
            assert entry["payload"]["index"] == i

    def test_malformed_event_rejected(self, audit_log):
        """CLAIM: Malformed events are rejected before append."""
        with pytest.raises(AuditLogError, match="missing required field: event_type"):
            audit_log.append({"data": "no event_type"})

        with pytest.raises(AuditLogError, match="event_type must not be empty"):
            audit_log.append({"event_type": ""})

        with pytest.raises(AuditLogError, match="Event must be dict"):
            audit_log.append("not a dict")

        assert audit_log.count() == 0

    def test_previous_entries_preserved(self, audit_log):
        """CLAIM: New appends do not modify previous entries."""
        audit_log.append({"event_type": "E1", "data": "original"})
        entries_before = audit_log.read_all()
        entry1_id = entries_before[0]["event_id"]

        audit_log.append({"event_type": "E2", "data": "new"})

        entries_after = audit_log.read_all()
        assert len(entries_after) == 2
        assert entries_after[0]["event_id"] == entry1_id
        assert entries_after[0]["event_type"] == "E1"
        assert entries_after[0]["payload"]["data"] == "original"

    def test_read_by_type(self, audit_log):
        """CLAIM: read_by_type() filters correctly."""
        audit_log.append({"event_type": "DISCOVERY", "res": "a"})
        audit_log.append({"event_type": "ACTIVATION", "res": "b"})
        audit_log.append({"event_type": "DISCOVERY", "res": "c"})

        discoveries = audit_log.read_by_type("DISCOVERY")
        assert len(discoveries) == 2
        assert all(e["event_type"] == "DISCOVERY" for e in discoveries)

    def test_count(self, audit_log):
        """CLAIM: count() returns accurate count."""
        assert audit_log.count() == 0
        audit_log.append({"event_type": "E1"})
        audit_log.append({"event_type": "E2"})
        assert audit_log.count() == 2

    def test_clear(self, audit_log):
        """CLAIM: clear() removes all entries."""
        audit_log.append({"event_type": "E1"})
        audit_log.append({"event_type": "E2"})
        audit_log.clear()
        assert audit_log.count() == 0

    def test_empty_log(self, tmp_dir):
        """CLAIM: Reading a nonexistent log returns empty list."""
        path = os.path.join(tmp_dir, "nonexistent.jsonl")
        log = JsonlAuditLogWriter(path)
        entries = log.read_all()
        assert entries == []

    def test_malformed_line_skipped(self, tmp_dir):
        """CLAIM: Malformed lines are skipped, not crashing the reader."""
        path = os.path.join(tmp_dir, "partial.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"event_type": "E1", "schema_version": 1, "event_id": "a", "timestamp": "t", "payload": {}}) + "\n")
            f.write("THIS IS NOT JSON\n")
            f.write(json.dumps({"event_type": "E2", "schema_version": 1, "event_id": "b", "timestamp": "t", "payload": {}}) + "\n")

        log = JsonlAuditLogWriter(path)
        entries = log.read_all()
        assert len(entries) == 2

    def test_utf8_encoding(self, audit_log):
        """CLAIM: UTF-8 events are preserved."""
        audit_log.append({"event_type": "UNICODE", "text": "日本語テスト 🔐"})
        entries = audit_log.read_all()
        assert entries[0]["payload"]["text"] == "日本語テスト 🔐"

    def test_large_event(self, audit_log):
        """CLAIM: Large events are written correctly."""
        big_payload = {"data": "x" * 10000}
        audit_log.append({"event_type": "BIG", **big_payload})
        entries = audit_log.read_all()
        assert len(entries) == 1
        assert len(entries[0]["payload"]["data"]) == 10000

    def test_write_count(self, audit_log):
        """CLAIM: write_count tracks total writes."""
        assert audit_log.write_count == 0
        audit_log.append({"event_type": "E1"})
        audit_log.append({"event_type": "E2"})
        assert audit_log.write_count == 2


# ---------------------------------------------------------------------------
# SECTION 7: Schema version preservation
# ---------------------------------------------------------------------------

class TestSchemaVersionPreservation:
    """Tests that schema version is preserved across read/write cycles."""

    def test_schema_version_in_written_file(self, engine):
        """CLAIM: Schema version 1 is written to file."""
        engine.write_sync("k", {"v": 1})
        with open(engine.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == 1

    def test_schema_version_preserved_on_overwrite(self, engine):
        """CLAIM: Schema version is preserved on overwrite."""
        engine.write_sync("k", {"v": 1})
        engine.write_sync("k", {"v": 2})
        with open(engine.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_written_at_is_iso8601(self, engine):
        """CLAIM: written_at is a valid ISO 8601 timestamp."""
        engine.write_sync("k", {"v": 1})
        with open(engine.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data["written_at"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# SECTION 8: Timestamp round-trip
# ---------------------------------------------------------------------------

class TestTimestampRoundTrip:
    """Tests for timestamp preservation."""

    def test_utc_timestamp_preserved(self, engine):
        """CLAIM: UTC timestamps survive write/read."""
        ts = "2026-08-18T12:30:45.123456+00:00"
        engine.write_sync("k", {"timestamp": ts})
        result = engine.read_sync("k")
        assert result["timestamp"] == ts

    def test_timezone_aware_timestamp_preserved(self, engine):
        """CLAIM: Timezone-aware timestamps survive write/read."""
        ts = "2026-08-18T14:30:45+05:30"
        engine.write_sync("k", {"timestamp": ts})
        result = engine.read_sync("k")
        assert result["timestamp"] == ts

    def test_written_at_preserves_precision(self, engine):
        """CLAIM: Envelope written_at preserves sub-second precision."""
        ts = "2026-08-18T12:30:45.123456+00:00"
        envelope = SchemaVersionEnvelope({}, written_at=ts)
        raw = envelope.to_bytes()
        restored = SchemaVersionEnvelope.from_bytes(raw)
        assert restored.written_at == ts


# ---------------------------------------------------------------------------
# SECTION 9: Authority safety
# ---------------------------------------------------------------------------

class TestAuthoritySafety:
    """Tests proving C1-A does not restore or manufacture authority."""

    def test_engine_stores_data_only(self, engine):
        """CLAIM: Engine stores and retrieves data. No authority logic."""
        engine.write_sync("auth_test", {"some": "data"})
        result = engine.read_sync("auth_test")
        assert result == {"some": "data"}
        assert not hasattr(engine, "authorize")
        assert not hasattr(engine, "activate")
        assert not hasattr(engine, "verify")
        assert not hasattr(engine, "grant_trust")

    def test_envelope_has_no_authority(self):
        """CLAIM: Envelope contains no authority semantics."""
        envelope = SchemaVersionEnvelope({"test": True})
        assert not hasattr(envelope, "authorize")
        assert not hasattr(envelope, "is_trusted")
        assert not hasattr(envelope, "grant")

    def test_loaded_data_not_trusted(self, engine):
        """CLAIM: Data loaded from disk is data, not authority."""
        engine.write_sync("k", {"trusted": True})
        result = engine.read_sync("k")
        assert result["trusted"] is True
        assert isinstance(result, dict)

    def test_audit_log_not_authority(self, audit_log):
        """CLAIM: Audit log entries are not authority."""
        event_id = audit_log.append({"event_type": "COMPLETION", "mission_id": "m1"})
        entries = audit_log.read_all()
        assert len(entries) == 1
        assert not hasattr(audit_log, "authorize")
        assert not hasattr(audit_log, "is_complete")

    def test_no_id_preserved_as_binding(self, engine):
        """CLAIM: No Python object id() is stored or restored."""
        original = {"executor": "some_object"}
        engine.write_sync("k", original)
        result = engine.read_sync("k")
        assert result == original
        assert "id(" not in json.dumps(result)


# ---------------------------------------------------------------------------
# SECTION 10: Existing MemoryPersistenceEngine unchanged
# ---------------------------------------------------------------------------

class TestMemoryEngineUnchanged:
    """Verify MemoryPersistenceEngine is not broken."""

    @pytest.mark.asyncio
    async def test_basic_operations(self):
        engine = MemoryPersistenceEngine()
        await engine.write("k", {"v": 1})
        assert await engine.read("k") == {"v": 1}
        assert await engine.exists("k") is True
        assert await engine.count() == 1
        assert await engine.delete("k") is True
        assert await engine.read("k") is None


# ---------------------------------------------------------------------------
# SECTION 11: Existing JsonFilePersistenceEngine unchanged
# ---------------------------------------------------------------------------

class TestJsonFileEngineUnchanged:
    """Verify existing JsonFilePersistenceEngine is not broken."""

    @pytest.mark.asyncio
    async def test_basic_operations(self, tmp_dir):
        from intent_kernel.persistence import JsonFilePersistenceEngine
        path = os.path.join(tmp_dir, "old_engine.json")
        engine = JsonFilePersistenceEngine(path)
        await engine.write("k", {"v": 1})
        assert await engine.read("k") == {"v": 1}
        assert await engine.exists("k") is True
        assert await engine.count() == 1
        assert await engine.delete("k") is True
        assert await engine.read("k") is None
