"""In-process migration telemetry without user payloads."""

from __future__ import annotations

from collections import Counter
from threading import Lock


class MigrationTelemetry:
    """Counts canonical and compatibility routes by domain."""

    def __init__(
        self,
        *,
        dependency_counts: dict[str, int] | None = None,
    ):
        self._canonical: Counter[str] = Counter()
        self._fallback: Counter[str] = Counter()
        self._legacy_calls: Counter[str] = Counter()
        self._dependency_counts = dict(dependency_counts or {})
        self._lock = Lock()

    def record_canonical(self, domain: str) -> None:
        with self._lock:
            self._canonical[domain] += 1

    def record_fallback(self, domain: str) -> None:
        with self._lock:
            self._fallback[domain] += 1

    def record_legacy(self, component: str) -> None:
        with self._lock:
            self._legacy_calls[component] += 1

    def snapshot(self) -> dict:
        with self._lock:
            canonical = dict(self._canonical)
            fallback = dict(self._fallback)
            legacy = dict(self._legacy_calls)
        canonical_total = sum(canonical.values())
        fallback_total = sum(fallback.values())
        total = canonical_total + fallback_total
        return {
            "canonical_executions": canonical_total,
            "fallback_executions": fallback_total,
            "canonical_percent": (
                round(canonical_total * 100 / total, 2)
                if total else 0.0
            ),
            "legacy_percent": (
                round(fallback_total * 100 / total, 2)
                if total else 0.0
            ),
            "canonical_by_domain": canonical,
            "fallback_by_domain": fallback,
            "legacy_component_calls": legacy,
            "direct_dependencies": dict(self._dependency_counts),
        }
