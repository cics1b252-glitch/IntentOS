"""Movement 23.6 — Canonical conversation metadata/provenance tests.

Validates that the 8 corrected metadata occurrences in ProductBridge
finance/application field-filling paths now emit truthful canonical
provenance, while legitimate compatibility paths remain unchanged.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "product_bridge.py"
_BRIDGE_SRC: str = _BRIDGE.read_text(encoding="utf-8")


def _lines_around(pattern: str, src: str, before: int = 5, after: int = 5) -> list[str]:
    """Return numbered lines surrounding each match of *pattern* in *src*."""
    results: list[str] = []
    for m in re.finditer(pattern, src):
        start = max(0, m.start())
        line_num = src[:start].count("\n") + 1
        results.append(f"  L{line_num}: ...{src[max(0,start-80):min(len(src),m.end()+80)]}...")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  FINANCE PROVENANCE — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinanceProvenance:
    def test_finance_waiting_canonical_classification(self):
        """Finance WAITING_CONTEXT metadata must say CANONICAL, not COMPATIBILITY_ONLY."""
        # Find the finance field-filling waiting block (domain=finance, WAITING path)
        # Pattern: compatibility_lifecycle block near domain=finance and waiting_context
        match = re.search(
            r'"classification":\s*"CANONICAL_CONVERSATION_LAYER".*?'
            r'"canonical_policy":\s*"FinanceConversationPolicy".*?'
            r'"domain":\s*"finance"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert match, (
            "Finance WAITING_CONTEXT missing CANONICAL_CONVERSATION_LAYER "
            "with FinanceConversationPolicy"
        )

    def test_finance_completed_canonical_classification(self):
        """Finance COMPLETED metadata must say CANONICAL, not COMPATIBILITY_ONLY."""
        match = re.search(
            r'"classification":\s*"CANONICAL_CONVERSATION_LAYER".*?'
            r'"canonical_policy":\s*"FinanceConversationPolicy".*?'
            r'"domain":\s*"finance".*?'
            r'"conversation_state"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert match, (
            "Finance COMPLETED missing CANONICAL_CONVERSATION_LAYER "
            "with FinanceConversationPolicy"
        )

    def test_finance_no_stale_alternative_missing(self):
        """Finance paths must not claim canonical_alternative_missing."""
        # Find all _compatibility_response calls in finance_field_filling paths
        finance_blocks = re.findall(
            r'entry_point="ProductBridge\.finance_field_filling".*?\)',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        for block in finance_blocks:
            assert "canonical_typed_conversation_policy" not in block, (
                f"Finance path still has stale canonical_alternative_missing: {block[:120]}"
            )

    def test_finance_canonical_mission_false(self):
        """Finance metadata must have canonical_mission=False (conversation, not mission)."""
        matches = re.findall(
            r'"canonical_mission":\s*False.*?"canonical_policy":\s*"FinanceConversationPolicy"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert len(matches) >= 2, (
            f"Expected at least 2 Finance canonical_mission=False, found {len(matches)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  APPLICATION PROVENANCE — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestApplicationProvenance:
    def test_app_waiting_canonical_classification(self):
        """Application WAITING_CONTEXT metadata must say CANONICAL."""
        match = re.search(
            r'"classification":\s*"CANONICAL_CONVERSATION_LAYER".*?'
            r'"canonical_policy":\s*"ApplicationConversationPolicy".*?'
            r'"domain":\s*"coding"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert match, (
            "Application WAITING_CONTEXT missing CANONICAL_CONVERSATION_LAYER "
            "with ApplicationConversationPolicy"
        )

    def test_app_completed_canonical_classification(self):
        """Application COMPLETED metadata must say CANONICAL."""
        match = re.search(
            r'"classification":\s*"CANONICAL_CONVERSATION_LAYER".*?'
            r'"canonical_policy":\s*"ApplicationConversationPolicy".*?'
            r'"domain":\s*"coding".*?'
            r'"conversation_state"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert match, (
            "Application COMPLETED missing CANONICAL_CONVERSATION_LAYER "
            "with ApplicationConversationPolicy"
        )

    def test_app_no_stale_alternative_missing(self):
        """Application paths must not claim canonical_alternative_missing."""
        app_blocks = re.findall(
            r'entry_point="ProductBridge\.application_field_filling".*?\)',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        for block in app_blocks:
            assert "canonical_typed_conversation_policy" not in block, (
                f"Application path still has stale canonical_alternative_missing: {block[:120]}"
            )

    def test_app_canonical_mission_false(self):
        """Application metadata must have canonical_mission=False (conversation, not mission)."""
        matches = re.findall(
            r'"canonical_mission":\s*False.*?"canonical_policy":\s*"ApplicationConversationPolicy"',
            _BRIDGE_SRC,
            re.DOTALL,
        )
        assert len(matches) >= 2, (
            f"Expected at least 2 Application canonical_mission=False, found {len(matches)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  LEGITIMATE COMPATIBILITY PRESERVED — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegitimateCompatibilityPreserved:
    def test_kernel_fallback_remains_compatibility(self):
        """Kernel fallback path must still say COMPATIBILITY_ONLY."""
        assert '"classification": "COMPATIBILITY_ONLY"' in _BRIDGE_SRC, (
            "No COMPATIBILITY_ONLY found in product_bridge.py — "
            "legitimate compatibility paths may have been accidentally removed"
        )

    def test_provider_failure_remains_compatibility(self):
        """Kernel fallback compatibility_lifecycle retains COMPATIBILITY_ONLY."""
        # Session default + _complete_local_request paths retain COMPATIBILITY_ONLY.
        # The kernel_fallback path is now canonical (M24.2) — no longer COMPATIBILITY_ONLY.
        count = _BRIDGE_SRC.count('"classification": "COMPATIBILITY_ONLY"')
        assert count == 3, (
            f"Expected 3 COMPATIBILITY_ONLY (session default + "
            f"_complete_local_request paths), found {count}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  STATIC AUDIT — stale metadata in finance/application paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaticAudit:
    def test_no_stale_finance_field_filling_metadata(self):
        """No COMPATIBILITY_ONLY or stale canonical_alternative_missing in
        finance field-filling path."""
        # Extract the finance field-filling section
        finance_start = _BRIDGE_SRC.index("is_fin = self.conversation_service.finance_domain_detected")
        finance_section_end = _BRIDGE_SRC.index("# 5. Canonical Conversation Content Runtime")
        finance_section = _BRIDGE_SRC[finance_start:finance_section_end]

        assert "COMPATIBILITY_ONLY" not in finance_section, (
            "Finance field-filling section still contains COMPATIBILITY_ONLY"
        )
        assert "canonical_typed_conversation_policy" not in finance_section, (
            "Finance field-filling section still contains stale canonical_alternative_missing"
        )

    def test_no_stale_app_field_filling_metadata(self):
        """No COMPATIBILITY_ONLY or stale canonical_alternative_missing in
        application field-filling path."""
        app_start = _BRIDGE_SRC.index("is_app = self.conversation_service.application_domain_detected")
        app_section_end = _BRIDGE_SRC.index("# 5. Canonical Conversation Content Runtime")
        app_section = _BRIDGE_SRC[app_start:app_section_end]

        assert "COMPATIBILITY_ONLY" not in app_section, (
            "Application field-filling section still contains COMPATIBILITY_ONLY"
        )
        assert "canonical_typed_conversation_policy" not in app_section, (
            "Application field-filling section still contains stale canonical_alternative_missing"
        )

    def test_canonical_conversation_layer_count(self):
        """Exactly 4 occurrences of CANONICAL_CONVERSATION_LAYER in product_bridge.py
        (finance waiting, finance completed, app waiting, app completed)."""
        count = _BRIDGE_SRC.count("CANONICAL_CONVERSATION_LAYER")
        assert count == 4, (
            f"Expected 4 CANONICAL_CONVERSATION_LAYER occurrences, found {count}"
        )
