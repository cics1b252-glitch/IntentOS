"""FRONT-F.M1 — read-only Authority Provenance View package.

Query-only reconstruction over existing canonical evidence. This package
is incapable by construction of authority-bearing operations: it receives
only narrow read callables plus detached snapshots and pure recompute
functions. See view.AuthorityProvenanceView.
"""

from intent_kernel.provenance.view import (
    AuthorityProvenanceView,
    LinkResult,
    LinkStatus,
    ProvenanceView,
)

__all__ = [
    "AuthorityProvenanceView",
    "LinkResult",
    "LinkStatus",
    "ProvenanceView",
]
