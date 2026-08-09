"""Knowledge Curator — RFC-0003 Section 7.

Full pipeline: Constitution gate → Score → Threshold → Conflict → Action → Audit.

This replaces the simple confidence-based curator with the proper
score-based pipeline from the canonical implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from intent_kernel.constitution.checker import ConstitutionChecker, ConstitutionVerdict
from intent_kernel.pkb.score import KnowledgeScoreCalculator, KnowledgeScoreBreakdown, SCORE_THRESHOLDS
from intent_kernel.types import new_id, utcnow


# ---------------------------------------------------------------------------
# Audit Entry — RFC-0003 Section 11
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """Record of a Curator operation."""
    ke_id: str
    action: str           # APPROVE | REJECT | MERGE | ESCALATE | EXPIRE | DELETE | SCORE_RECALC
    reason: str
    score_at_action: float
    timestamp: str
    session_id: str
    module: str


# ---------------------------------------------------------------------------
# Curator Decision
# ---------------------------------------------------------------------------

@dataclass
class CuratorDecision:
    """Result of Curator processing."""
    action: str           # APPROVE | REJECT | MERGE | ESCALATE
    ke: dict              # the knowledge event (possibly modified)
    merged_with: str | None = None
    audit_entry: AuditEntry | None = None


# ---------------------------------------------------------------------------
# Knowledge Curator — Full Pipeline
# ---------------------------------------------------------------------------

class LegacyV2KnowledgeCuratorAdapter:
    """Processes Knowledge Events through the full RFC-0003 pipeline.

    Pipeline (Section 7.1):
        Event → Constitution Gate → Score → Threshold → Conflict → Action → Audit

    Actions:
        APPROVE  — event enters KC at appropriate level
        REJECT   — event discarded
        MERGE    — event combined with existing KC entry
        ESCALATE — event flagged for human review
    """

    def __init__(
        self,
        constitution: ConstitutionChecker | None = None,
        score_calculator: KnowledgeScoreCalculator | None = None,
        module_name: str = "intent-os-kernel",
    ):
        self.constitution = constitution or ConstitutionChecker()
        self.score_calc = score_calculator or KnowledgeScoreCalculator()
        self.module_name = module_name

        # In-memory stores (Sprint 0)
        self._kc: dict[str, dict] = {}          # knowledge core
        self._candidates: dict[str, dict] = {}  # candidate queue
        self._audit_log: list[AuditEntry] = []

    # -------------------------------------------------------------------
    # Main entry point — RFC-0003 Section 7.1
    # -------------------------------------------------------------------

    async def process(self, event: dict[str, Any], session_id: str = "") -> CuratorDecision:
        """Process a Knowledge Event through the full pipeline.

        Steps:
        1. Constitution gate (blocked/flagged/allowed)
        2. Score calculation (if not already scored)
        3. Threshold check (DISCARD/CANDIDATE/APPROVED/CONSTITUTIONAL)
        4. Conflict detection
        5. Action (APPROVE/REJECT/MERGE/ESCALATE)
        6. Audit log
        """
        event_id = event.get("id", new_id())

        # Step 1: Constitution gate
        verdict = self.constitution.evaluate(event)
        if verdict.decision == "blocked":
            return self._reject(event, f"Constitution blocked: {verdict.reason}", session_id)
        if verdict.decision == "flagged":
            return self._escalate(event, f"Constitution flagged: {verdict.reason}", session_id)

        # Step 2: Score calculation
        score_value = self._ensure_score(event)
        if score_value is None:
            return self._reject(event, "No score provided and could not calculate.", session_id)

        # Step 3: Threshold check
        target_level = self.score_calc.get_target_level(score_value)
        if target_level == "DISCARD":
            return self._reject(event, f"Score {score_value} below DISCARD threshold", session_id)

        # Step 4: Conflict detection
        conflict = self._detect_conflict(event)
        if conflict:
            event_type = event.get("type", "")
            conflict_type = conflict.get("type", "")
            if event_type == "CORRECTION" or conflict_type == "CORRECTION":
                return self._merge(event, conflict, session_id)
            return self._escalate(
                event,
                f"Conflicts with existing entry {conflict.get('id', 'unknown')}",
                session_id,
            )

        # Step 5: Action based on level
        if target_level == "CONSTITUTIONAL":
            return self._approve(event, "CONSTITUTIONAL", session_id)
        if target_level == "APPROVED":
            return self._approve(event, "APPROVED", session_id)

        # CANDIDATE → add to queue
        return self._add_to_candidates(event, session_id)

    # -------------------------------------------------------------------
    # Score recalculation — RFC-0003 Section 6.5
    # -------------------------------------------------------------------

    async def recalculate(
        self,
        ke_id: str,
        new_breakdown: KnowledgeScoreBreakdown,
        session_id: str = "",
    ) -> CuratorDecision | None:
        """Recalculate score for a CANDIDATE event."""
        candidate = self._candidates.get(ke_id)
        if not candidate:
            return None

        last_calc = candidate.get("score", {}).get("calculatedAt", "")
        event_type = candidate.get("type", "")
        if not self.score_calc.can_recalculate(last_calc, event_type):
            return None

        new_value = self.score_calc.calculate(new_breakdown)
        candidate["score"] = {
            "value": new_value,
            "breakdown": {
                "relevance": new_breakdown.relevance,
                "persistence": new_breakdown.persistence,
                "reuse": new_breakdown.reuse,
                "impact": new_breakdown.impact,
                "goalAlignment": new_breakdown.goalAlignment,
            },
            "calculatedAt": utcnow().isoformat(),
            "recalculations": candidate.get("score", {}).get("recalculations", []) + [{
                "at": utcnow().isoformat(),
                "value": new_value,
                "reason": "Score recalculated",
            }],
        }

        self._add_audit(AuditEntry(
            ke_id=ke_id,
            action="SCORE_RECALC",
            reason=f"Score recalculated: {new_value}",
            score_at_action=new_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        ))

        target_level = self.score_calc.get_target_level(new_value)
        if target_level in ("APPROVED", "CONSTITUTIONAL"):
            self._candidates.pop(ke_id, None)
            return self._approve(candidate, target_level, session_id)

        return None

    # -------------------------------------------------------------------
    # Auto-promote — RFC-0003 Section 10
    # -------------------------------------------------------------------

    async def auto_promote(self, session_id: str = "") -> list[CuratorDecision]:
        """Auto-promote CANDIDATEs with 3+ recalculations."""
        promoted = []
        for ke_id, candidate in list(self._candidates.items()):
            recalcs = candidate.get("score", {}).get("recalculations", [])
            if len(recalcs) < 3:
                continue

            # Boost reuse by 20 (simulating repeated consultation)
            breakdown = candidate.get("score", {}).get("breakdown", {})
            boosted = KnowledgeScoreBreakdown(
                relevance=breakdown.get("relevance", 50),
                persistence=breakdown.get("persistence", 50),
                reuse=min(100, breakdown.get("reuse", 50) + 20),
                impact=breakdown.get("impact", 50),
                goalAlignment=breakdown.get("goalAlignment", 50),
            )
            result = await self.recalculate(ke_id, boosted, session_id)
            if result:
                promoted.append(result)

        return promoted

    # -------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------

    def _approve(self, event: dict, level: str, session_id: str) -> CuratorDecision:
        """Approve event into KC."""
        event["level"] = level
        event.setdefault("lifecycle", {})
        event["lifecycle"]["currentLevel"] = level
        transitions = event["lifecycle"].get("transitions", [])
        transitions.append({
            "from": event.get("level", "TRANSIENT"),
            "to": level,
            "at": utcnow().isoformat(),
            "reason": f"Score {event.get('score', {}).get('value', 0)} meets {level} threshold",
        })
        event["lifecycle"]["transitions"] = transitions

        self._kc[event["id"]] = {
            "ke": event,
            "storedAt": utcnow().isoformat(),
            "lastAccessedAt": utcnow().isoformat(),
            "accessCount": 0,
        }

        score_value = event.get("score", {}).get("value", 0)
        audit = AuditEntry(
            ke_id=event["id"],
            action="APPROVE",
            reason=f"{level}: score {score_value}",
            score_at_action=score_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        )
        self._audit_log.append(audit)

        return CuratorDecision(action="APPROVE", ke=event, audit_entry=audit)

    def _reject(self, event: dict, reason: str, session_id: str) -> CuratorDecision:
        """Reject event."""
        score_value = event.get("score", {}).get("value", 0)
        audit = AuditEntry(
            ke_id=event.get("id", "unknown"),
            action="REJECT",
            reason=reason,
            score_at_action=score_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        )
        self._audit_log.append(audit)
        return CuratorDecision(action="REJECT", ke=event, audit_entry=audit)

    def _escalate(self, event: dict, reason: str, session_id: str) -> CuratorDecision:
        """Escalate event for human review."""
        score_value = event.get("score", {}).get("value", 0)
        audit = AuditEntry(
            ke_id=event.get("id", "unknown"),
            action="ESCALATE",
            reason=reason,
            score_at_action=score_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        )
        self._audit_log.append(audit)
        return CuratorDecision(action="ESCALATE", ke=event, audit_entry=audit)

    def _merge(self, new_event: dict, existing: dict, session_id: str) -> CuratorDecision:
        """Merge new event into existing KC entry."""
        existing_score = existing.get("score", {}).get("value", 0)
        new_score = new_event.get("score", {}).get("value", 0)

        merged_value = self.score_calc.calculate_merged(existing_score, new_score, 2)

        # Update existing
        existing["content"] = new_event.get("content", existing.get("content", {}))
        existing["score"]["value"] = merged_value
        existing["score"]["calculatedAt"] = utcnow().isoformat()

        audit = AuditEntry(
            ke_id=new_event.get("id", "unknown"),
            action="MERGE",
            reason=f"Merged into {existing.get('id')}. Combined score: {merged_value}",
            score_at_action=merged_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        )
        self._audit_log.append(audit)

        return CuratorDecision(
            action="MERGE",
            ke=existing,
            merged_with=new_event.get("id"),
            audit_entry=audit,
        )

    def _add_to_candidates(self, event: dict, session_id: str) -> CuratorDecision:
        """Add event to candidate queue."""
        event["level"] = "CANDIDATE"
        event.setdefault("lifecycle", {})
        event["lifecycle"]["currentLevel"] = "CANDIDATE"
        transitions = event["lifecycle"].get("transitions", [])
        score_value = event.get("score", {}).get("value", 0)
        transitions.append({
            "from": "TRANSIENT",
            "to": "CANDIDATE",
            "at": utcnow().isoformat(),
            "reason": f"Score {score_value} is CANDIDATE (30-69)",
        })
        event["lifecycle"]["transitions"] = transitions

        self._candidates[event["id"]] = event

        audit = AuditEntry(
            ke_id=event["id"],
            action="APPROVE",
            reason=f"CANDIDATE: score {score_value}, added to queue",
            score_at_action=score_value,
            timestamp=utcnow().isoformat(),
            session_id=session_id,
            module=self.module_name,
        )
        self._audit_log.append(audit)

        return CuratorDecision(action="APPROVE", ke=event, audit_entry=audit)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _ensure_score(self, event: dict) -> float | None:
        """Get or calculate score for event."""
        score = event.get("score", {})
        if isinstance(score, dict) and "value" in score:
            return score["value"]
        return None

    def _detect_conflict(self, event: dict) -> dict | None:
        """Check if event conflicts with existing KC entries."""
        event_type = event.get("type", "")
        event_content = self._normalize_content(event)

        for entry in self._kc.values():
            existing = entry.get("ke", {})
            if existing.get("id") == event.get("id"):
                continue
            if existing.get("type") != event_type:
                continue

            existing_content = self._normalize_content(existing)
            if existing_content == event_content:
                return existing

            # FACT vs FACT with same domain but different content → conflict
            if (event_type == "FACT" and existing.get("type") == "FACT"
                    and self._domains_overlap(event, existing)
                    and existing_content != event_content):
                return existing

        return None

    def _normalize_content(self, event: dict) -> str:
        content = event.get("content", {})
        if isinstance(content, dict):
            return content.get("normalized", content.get("raw", "")).lower().strip()
        return str(content).lower().strip()

    def _domains_overlap(self, event_a: dict, event_b: dict) -> bool:
        domains_a = event_a.get("domain", [])
        domains_b = event_b.get("domain", [])
        if isinstance(domains_a, str):
            domains_a = [domains_a]
        if isinstance(domains_b, str):
            domains_b = [domains_b]
        return bool(set(domains_a) & set(domains_b))

    def _add_audit(self, entry: AuditEntry) -> None:
        self._audit_log.append(entry)

    # -------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------

    def get_audit_log(self, days: int = 30) -> list[AuditEntry]:
        """Get audit log entries from the last N days."""
        cutoff = utcnow().timestamp() - days * 86400
        return [
            e for e in self._audit_log
            if datetime.fromisoformat(e.timestamp).timestamp() > cutoff
        ]

    def get_kc(self) -> list[dict]:
        """Get all KC entries."""
        return list(self._kc.values())

    def get_candidates(self) -> list[dict]:
        """Get all candidate events."""
        return list(self._candidates.values())

    def get_kc_size(self) -> int:
        return len(self._kc)

    def get_candidate_count(self) -> int:
        return len(self._candidates)


# Public legacy name retained for source compatibility. The canonical typed
# flow lives in canonical_curator.py and knowledge_pipeline.py.
KnowledgeCurator = LegacyV2KnowledgeCuratorAdapter
