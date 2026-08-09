"""Canonical UTC timestamp parsing for persisted product data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_iso(value: Any = None, *, fallback_now: bool = True) -> str | None:
    """Normalize supported timestamp forms to ISO 8601 UTC."""
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if abs(seconds) >= 100_000_000_000:
            seconds /= 1000
        try:
            parsed = datetime.fromtimestamp(seconds, timezone.utc)
        except (OverflowError, OSError, ValueError):
            parsed = None
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            numeric = float(raw)
        except ValueError:
            numeric = None
        if numeric is not None:
            return utc_iso(numeric, fallback_now=fallback_now)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        parsed = datetime.now(timezone.utc) if fallback_now else None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Generate a new UUID v4 string."""
    import uuid
    return str(uuid.uuid4())
