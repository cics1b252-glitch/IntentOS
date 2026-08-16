"""Discovery adapter protocol — Movement 16.

Adapters are the only mechanism through which new observation sources enter
the discovery subsystem.  Each adapter is a read-only probe that returns
evidence; it must never mutate RRM, registry, or execution state.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from intent_kernel.discovery.models import ResourceDiscoveryEvidence


@runtime_checkable
class ResourceDiscoveryAdapter(Protocol):
    """Narrow contract for pluggable discovery observation sources."""

    @property
    def adapter_id(self) -> str: ...

    @property
    def adapter_type(self) -> str: ...

    def discover(self) -> list[ResourceDiscoveryEvidence]: ...
