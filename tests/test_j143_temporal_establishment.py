"""J1.4.3 — Temporal Establishment Fail-Closed Tests.

Direct tests for establish_intent_authority() and grant-chain establishment
through IntentAuthorityGrant.
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.intent_authority import (
    IntentAuthorityError,
    establish_intent_authority,
    prove_plan_actions_against_authority,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    propose_intent_authority,
    establish_intent_authority_from_grant,
)
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_ceiling(**over):
    defaults = {
        "allow_capabilities": ("c.rt", "c.read"),
        "allowed_operations": ("retrieve", "analyze"),
        "target_scope": ("r1", "r2"),
        "max_risk_level": "medium",
        "max_side_effect": "EXTERNAL_REVERSIBLE",
        "require_verification": True,
        "valid_from": "",
        "valid_until": "",
    }
    defaults.update(over)
    return IntentCeiling(**defaults)


def _now_iso() -> str:
    return "2026-06-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# T1: temporal ceiling + valid current time → ESTABLISH
# ---------------------------------------------------------------------------

def test_t1_temporal_ceiling_valid_time_establishes():
    """T1: Ceiling with valid_from/valid_until and current time within window → ESTABLISH."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    record = establish_intent_authority(
        ceiling=ceiling,
        source_type="user_explicit",
        source_identity="test",
        established_at=_now_iso(),
        now_iso=_now_iso(),
    )
    assert isinstance(record, IntentAuthorityError) is False
    assert record.ceiling.valid_from == "2025-01-01T00:00:00+00:00"
    assert record.ceiling.valid_until == "2027-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# T2: expired ceiling + valid current clock → DENY ceiling-expired
# ---------------------------------------------------------------------------

def test_t2_expired_ceiling_denied_at_establishment():
    """T2: Ceiling expired before current time → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2020-01-01T00:00:00+00:00",
        valid_until="2020-12-31T23:59:59+00:00",
    )
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority(
            ceiling=ceiling,
            source_type="user_explicit",
            source_identity="test",
            established_at=_now_iso(),
            now_iso=_now_iso(),
        )
    assert "ceiling-expired" in str(exc.value)


# ---------------------------------------------------------------------------
# T3: not-yet-valid ceiling + valid current clock → DENY ceiling-not-yet-valid
# ---------------------------------------------------------------------------

def test_t3_not_yet_valid_ceiling_denied_at_establishment():
    """T3: Ceiling not yet valid at current time → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2027-01-01T00:00:00+00:00",
        valid_until="2028-01-01T00:00:00+00:00",
    )
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority(
            ceiling=ceiling,
            source_type="user_explicit",
            source_identity="test",
            established_at=_now_iso(),
            now_iso=_now_iso(),
        )
    assert "ceiling-not-yet-valid" in str(exc.value)


# ---------------------------------------------------------------------------
# T4: temporal ceiling + missing clock → DENY
# ---------------------------------------------------------------------------

def test_t4_temporal_ceiling_missing_clock_denied():
    """T4: Temporal ceiling without now_iso → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority(
            ceiling=ceiling,
            source_type="user_explicit",
            source_identity="test",
            established_at=_now_iso(),
            now_iso="",  # Missing clock
        )
    assert "ceiling-temporal-unknown" in str(exc.value)


# ---------------------------------------------------------------------------
# T5: temporal ceiling + malformed/invalid clock → DENY
# ---------------------------------------------------------------------------

def test_t5_temporal_ceiling_malformed_clock_denied():
    """T5: Temporal ceiling with malformed now_iso → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority(
            ceiling=ceiling,
            source_type="user_explicit",
            source_identity="test",
            established_at=_now_iso(),
            now_iso="not-a-valid-iso-timestamp",
        )
    assert "ceiling-temporal-invalid" in str(exc.value)


# ---------------------------------------------------------------------------
# T6: non-temporal ceiling → establishment unaffected
# ---------------------------------------------------------------------------

def test_t6_non_temporal_ceiling_establishes_without_clock():
    """T6: Ceiling without temporal constraints establishes even without now_iso."""
    ceiling = _base_ceiling(valid_from="", valid_until="")
    record = establish_intent_authority(
        ceiling=ceiling,
        source_type="user_explicit",
        source_identity="test",
        established_at=_now_iso(),
        now_iso="",  # No clock needed for non-temporal
    )
    assert isinstance(record, IntentAuthorityError) is False
    assert record.ceiling.valid_from == ""
    assert record.ceiling.valid_until == ""


# ---------------------------------------------------------------------------
# Grant Chain Tests
# ---------------------------------------------------------------------------

def _make_grant(ceiling: IntentCeiling, now_iso: str = "") -> IntentAuthorityGrant:
    """Create an IntentAuthorityGrant for the given ceiling."""
    proposal = propose_intent_authority(
        allow_capabilities=ceiling.allow_capabilities,
        allowed_operations=ceiling.allowed_operations,
        target_scope=ceiling.target_scope,
        max_risk_level=ceiling.max_risk_level,
        max_side_effect=ceiling.max_side_effect,
        require_verification=ceiling.require_verification,
        valid_from=ceiling.valid_from,
        valid_until=ceiling.valid_until,
        rationale="temporal establishment test",
    )
    return approve_intent_authority(
        proposal,
        authority_source_type="user_explicit",
        authority_source_identity="test",
        approved_at=now_iso or _now_iso(),
    )


# ---------------------------------------------------------------------------
# G1: valid temporal grant → ESTABLISH
# ---------------------------------------------------------------------------

def test_g1_valid_temporal_grant_establishes():
    """G1: Valid temporal grant with current time in window → ESTABLISH."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    grant = _make_grant(ceiling, now_iso=_now_iso())
    record = establish_intent_authority_from_grant(grant, now_iso=_now_iso())
    assert isinstance(record, IntentAuthorityError) is False
    assert record.ceiling.valid_from == "2025-01-01T00:00:00+00:00"
    assert record.ceiling.valid_until == "2027-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# G2: expired grant → DENY at establishment
# ---------------------------------------------------------------------------

def test_g2_expired_grant_denied_at_establishment():
    """G2: Expired grant → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2020-01-01T00:00:00+00:00",
        valid_until="2020-12-31T23:59:59+00:00",
    )
    grant = _make_grant(ceiling, now_iso=_now_iso())
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority_from_grant(grant, now_iso=_now_iso())
    assert "ceiling-expired" in str(exc.value)


# ---------------------------------------------------------------------------
# G3: not-yet-valid grant → DENY at establishment
# ---------------------------------------------------------------------------

def test_g3_not_yet_valid_grant_denied_at_establishment():
    """G3: Not-yet-valid grant → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2027-01-01T00:00:00+00:00",
        valid_until="2028-01-01T00:00:00+00:00",
    )
    grant = _make_grant(ceiling, now_iso=_now_iso())
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority_from_grant(grant, now_iso=_now_iso())
    assert "ceiling-not-yet-valid" in str(exc.value)


# ---------------------------------------------------------------------------
# G4: missing/invalid required clock → DENY
# ---------------------------------------------------------------------------

def test_g4_grant_missing_clock_denied():
    """G4: Temporal grant without now_iso → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    grant = _make_grant(ceiling, now_iso=_now_iso())
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority_from_grant(grant, now_iso="")
    assert "ceiling-temporal-unknown" in str(exc.value)


def test_g4b_grant_malformed_clock_denied():
    """G4b: Temporal grant with malformed now_iso → DENY at establishment."""
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2027-01-01T00:00:00+00:00",
    )
    grant = _make_grant(ceiling, now_iso=_now_iso())
    with pytest.raises(IntentAuthorityError) as exc:
        establish_intent_authority_from_grant(grant, now_iso="not-a-valid-iso-timestamp")
    assert "ceiling-temporal-invalid" in str(exc.value)


# ---------------------------------------------------------------------------
# TOCTOU / Time-Advance Test
# ---------------------------------------------------------------------------

def test_toctou_time_advance_after_establishment_denied_at_productive_use():
    """Authority valid at T1 establishment → expires → attempted use at T2 → DENY.

    This proves defense-in-depth: establishment validity check +
    plan <= current valid intent check at productive use.
    """
    # T1: Authority established when valid
    t1 = "2026-06-01T00:00:00+00:00"
    ceiling = _base_ceiling(
        valid_from="2025-01-01T00:00:00+00:00",
        valid_until="2026-06-01T12:00:00+00:00",  # Expires at noon T1
    )
    record = establish_intent_authority(
        ceiling=ceiling,
        source_type="user_explicit",
        source_identity="test",
        established_at=t1,
        now_iso=t1,
    )
    assert isinstance(record, IntentAuthorityError) is False

    # T2: Time advances past expiry, attempt productive use
    t2 = "2026-06-02T00:00:00+00:00"
    with pytest.raises(IntentAuthorityError) as exc:
        prove_plan_actions_against_authority(
            record,
            [{
                "action_id": "act_1",
                "capability": "c.rt",
                "operation": "retrieve",
                "target": "r1",
                "risk_level": "low",
                "side_effect": "NONE",
                "verification_required": True,
            }],
            now_iso=t2,
        )
    assert "ceiling-expired" in str(exc.value)