"""M30.2 — Canonical Resource Generation (helper/schema only, no authority).

This module is a STRICT COMPATIBILITY / SCHEMA helper. It MUST NOT own
mutation or advancement authority.

Authority RESTRICTION:
  - Only RegistryResourceManager (the single canonical mutation authority)
    may advance `resource.generation`.
  - This module only defines:
      * the LEGACY_UNVERSIONED sentinel
      * the initial generation constant
      * validation / normalization / serialization helpers
  - Nothing here writes to a resource or advances a generation.

Semantics:
  - registration / a newly introduced canonical resource begins at generation 1.
  - a material mutation advances generation by exactly one.
  - a no-op mutation does NOT advance.
  - legacy / unversioned / malformed resources carry LEGACY_UNVERSIONED and
    fail closed as external evidence.
"""

from __future__ import annotations

from typing import Any

# Sentinel for resources without a canonical monotonic generation.
LEGACY_UNVERSIONED = 0

# Generation assigned to a newly-registered canonical resource.
GENERATION_INITIAL = 1

# Keys that are NOT part of a resource's canonical "material" state.
# Generation is the invariant under audit and must never self-compare.
# updated_at / created_at are observational metadata, never authority.
_MATERIAL_EXCLUDED_KEYS = ("generation", "updated_at", "created_at")


def is_valid_generation(value: Any) -> bool:
    """A valid canonical generation is a positive int (never bool)."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= GENERATION_INITIAL
    )


def is_versioned(value: Any) -> bool:
    """True if the value is a valid, canonical generation (>= 1)."""
    return is_valid_generation(value)


def generation_for_registration() -> int:
    """Canonical initial generation for a newly-introduced resource.

    Registration NEVER trusts caller-supplied generation. A new canonical
    resource always begins at GENERATION_INITIAL.
    """
    return GENERATION_INITIAL


def normalize_for_restore(value: Any) -> int:
    """Normalize a value read from a serialized payload for restore.

    Persistence restore is DISTINCT from registration:
      - a valid versioned value is preserved exactly.
      - a missing / None / malformed (bool, negative, non-int, zero) value is
        normalized to LEGACY_UNVERSIONED so it fails closed as external
        evidence rather than being silently trusted.
    """
    if is_valid_generation(value):
        return value
    return LEGACY_UNVERSIONED


def material_snapshot(obj: Any) -> dict:
    """Canonical material-state snapshot of a resource (serialization hook).

    Excludes generation (the invariant under audit), updated_at and created_at
    (observational metadata). Used by the single mutation authority to decide
    whether a mutation is material (and therefore whether generation advances).
    """
    if hasattr(obj, "to_dict"):
        raw = obj.to_dict()
    else:
        from dataclasses import asdict

        raw = asdict(obj)
    return {k: v for k, v in raw.items() if k not in _MATERIAL_EXCLUDED_KEYS}
