"""EventBus — internal pub/sub for Kernel components."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Awaitable


class EventBus:
    """Internal event bus for decoupled communication between Kernel components.

    Components subscribe to events and react when they're published.
    No external dependencies — pure in-memory pub/sub.
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._history: list[dict] = []
        self._failures: list[dict[str, Any]] = []

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe a handler to an event type."""
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Remove a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    async def publish(self, event_type: str, data: Any = None) -> None:
        """Publish an event to all subscribed handlers."""
        self._history.append({
            "type": event_type,
            "data": data,
        })

        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            if hasattr(handler, "__call__"):
                try:
                    result = handler(data)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    self._failures.append({
                        "event_type": event_type,
                        "handler": getattr(handler, "__name__", type(handler).__name__),
                        "error_type": type(exc).__name__,
                    })

    def get_history(self, event_type: str | None = None) -> list[dict]:
        """Get event history, optionally filtered by type."""
        if event_type:
            return [e for e in self._history if e["type"] == event_type]
        return list(self._history)

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()

    def get_failures(self, event_type: str | None = None) -> list[dict[str, Any]]:
        """Return redacted handler failures without interrupting other handlers."""
        if event_type is None:
            return list(self._failures)
        return [item for item in self._failures if item["event_type"] == event_type]

    @property
    def subscriber_count(self) -> int:
        """Total number of subscriptions."""
        return sum(len(handlers) for handlers in self._handlers.values())
