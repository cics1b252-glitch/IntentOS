"""FRONT-F.M1/M2 — read-only Authority Provenance View package.

Query-only reconstruction over existing canonical evidence. This package
is incapable by construction of authority-bearing operations: it receives
only narrow read callables plus detached snapshots and pure recompute
functions. See view.AuthorityProvenanceView and lookup.EffectProvenanceLookup.
"""

from intent_kernel.provenance.view import (
    AuthorityProvenanceView,
    LinkResult,
    LinkStatus,
    ProvenanceView,
)
from intent_kernel.provenance.lookup import (
    EffectCandidate,
    EffectLookup,
    EffectLookupResult,
    EffectProvenanceLookup,
)

__all__ = [
    "AuthorityProvenanceView",
    "LinkResult",
    "LinkStatus",
    "ProvenanceView",
    "EffectCandidate",
    "EffectLookup",
    "EffectLookupResult",
    "EffectProvenanceLookup",
]
