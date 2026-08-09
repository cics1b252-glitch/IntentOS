"""Evolution Engine — The brain that makes Intent OS evolve.

Analyzes usage, identifies patterns, suggests improvements.
Never modifies anything automatically — only recommends.

Components:
- Evolution Engine: pattern detection + recommendations
- Meta Knowledge: knowledge about how the user learns
- Cognitive Insights: proactive suggestions
- Reflection Cycle: periodic self-analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Insight:
    """A cognitive insight — proactive suggestion."""
    id: str
    title: str
    description: str
    insight_type: str  # pattern, gap, opportunity, warning, suggestion
    severity: str      # low, medium, high
    domain: str = ""
    related_events: list[str] = field(default_factory=list)
    actionable: bool = True


@dataclass
class ReflectionResult:
    """Result of a reflection cycle."""
    timestamp: str
    redundancies_found: int
    gaps_found: int
    connections_improved: int
    insights_generated: int
    suggestions: list[str] = field(default_factory=list)


class EvolutionEngine:
    """Analyzes the Knowledge Core and suggests improvements.

    Never modifies anything automatically.
    Only recommends. The user decides.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self._insights: list[Insight] = []
        self._reflection_history: list[ReflectionResult] = []

    @property
    def name(self) -> str:
        return "evolution_engine"

    # -------------------------------------------------------------------
    # Pattern Detection
    # -------------------------------------------------------------------

    async def detect_patterns(self) -> list[dict]:
        """Detect patterns in the Knowledge Core."""
        patterns = []
        if not self.kernel:
            return patterns

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=1000))

            # Pattern 1: Repeated decisions
            decisions = [e for e in events if e.type.value == "decision"]
            decision_titles = {}
            for d in decisions:
                title_key = d.title[:30].lower()
                decision_titles[title_key] = decision_titles.get(title_key, 0) + 1
            for title, count in decision_titles.items():
                if count >= 2:
                    patterns.append({
                        "type": "repeated_decision",
                        "description": f"Decisão semelhante tomada {count} vezes",
                        "title": title,
                        "count": count,
                    })

            # Pattern 2: Domain concentration
            domains = {}
            for e in events:
                d = e.domain.value
                domains[d] = domains.get(d, 0) + 1
            for domain, count in domains.items():
                if count > len(events) * 0.6:
                    patterns.append({
                        "type": "domain_concentration",
                        "description": f"{count}% do conhecimento está em '{domain}'",
                        "domain": domain,
                        "percentage": round(count / len(events) * 100, 1),
                    })

            # Pattern 3: High confidence decisions
            high_conf = [e for e in decisions if e.confidence >= 0.9]
            if high_conf:
                patterns.append({
                    "type": "high_confidence_decisions",
                    "description": f"{len(high_conf)} decisões com alta confiança",
                    "count": len(high_conf),
                })

        except Exception:
            pass

        return patterns

    # -------------------------------------------------------------------
    # Cognitive Insights
    # -------------------------------------------------------------------

    async def generate_insights(self) -> list[Insight]:
        """Generate proactive cognitive insights."""
        insights = []
        if not self.kernel:
            return insights

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            # Insight: repeated problem solving
            decisions = [e for e in events if e.type.value == "decision"]
            if len(decisions) >= 4:
                insights.append(Insight(
                    id="repeated_solving",
                    title="Padrão de resolução detectado",
                    description=f"Você resolveu {len(decisions)} problemas. Considere documentar um processo reutilizável.",
                    insight_type="pattern",
                    severity="medium",
                ))

            # Insight: knowledge gaps
            domains = set(e.domain.value for e in events)
            all_domains = {"finance", "engineering", "knowledge", "education", "other"}
            gaps = all_domains - domains
            if gaps:
                insights.append(Insight(
                    id="domain_gaps",
                    title="Domínios inexplorados",
                    description=f"Você ainda não explorou: {', '.join(gaps)}",
                    insight_type="gap",
                    severity="low",
                ))

            # Insight: stale goals
            goals = [e for e in events if e.type.value == "goal"]
            for goal in goals:
                insights.append(Insight(
                    id=f"goal_{goal.id[:8]}",
                    title=f"Objetivo: {goal.title[:40]}",
                    description="Verifique se este objetivo ainda está ativo.",
                    insight_type="suggestion",
                    severity="low",
                ))

        except Exception:
            pass

        self._insights = insights
        return insights

    def get_insights(self, limit: int = 20) -> list[dict]:
        return [
            {
                "id": i.id,
                "title": i.title,
                "description": i.description,
                "type": i.insight_type,
                "severity": i.severity,
                "actionable": i.actionable,
            }
            for i in self._insights[:limit]
        ]

    # -------------------------------------------------------------------
    # Reflection Cycle
    # -------------------------------------------------------------------

    async def run_reflection(self) -> ReflectionResult:
        """Run a reflection cycle — analyze the Knowledge Core."""
        from intent_kernel.types import utcnow

        result = ReflectionResult(
            timestamp=utcnow().isoformat(),
            redundancies_found=0,
            gaps_found=0,
            connections_improved=0,
            insights_generated=0,
        )

        if not self.kernel:
            return result

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=1000))

            # Check redundancies
            titles = [e.title.lower()[:30] for e in events]
            unique = set(titles)
            result.redundancies_found = len(titles) - len(unique)

            # Check gaps
            domains = set(e.domain.value for e in events)
            all_domains = {"finance", "engineering", "knowledge", "education", "other"}
            result.gaps_found = len(all_domains - domains)

            # Generate insights during reflection
            insights = await self.generate_insights()
            result.insights_generated = len(insights)

            result.suggestions = [
                f"Encontradas {result.redundancies_found} possíveis redundâncias",
                f"Domínios não explorados: {result.gaps_found}",
                f"{result.insights_generated} insights gerados",
            ]

        except Exception:
            pass

        self._reflection_history.append(result)
        return result

    def get_reflection_history(self, limit: int = 10) -> list[dict]:
        return [
            {
                "timestamp": r.timestamp,
                "redundancies": r.redundancies_found,
                "gaps": r.gaps_found,
                "insights": r.insights_generated,
                "suggestions": r.suggestions,
            }
            for r in self._reflection_history[-limit:]
        ]

    # -------------------------------------------------------------------
    # Meta Knowledge
    # -------------------------------------------------------------------

    async def get_meta_knowledge(self) -> dict:
        """Knowledge about how the user uses the Knowledge Core."""
        if not self.kernel:
            return {}

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=1000))

            # Analyze usage patterns
            domains = {}
            types = {}
            confidences = []
            for e in events:
                domains[e.domain.value] = domains.get(e.domain.value, 0) + 1
                types[e.type.value] = types.get(e.type.value, 0) + 1
                confidences.append(e.confidence)

            return {
                "total_events": len(events),
                "domains": domains,
                "types": types,
                "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
                "most_used_domain": max(domains, key=domains.get) if domains else "none",
                "most_common_type": max(types, key=types.get) if types else "none",
            }
        except Exception:
            return {}

    # -------------------------------------------------------------------
    # Evolution Recommendations
    # -------------------------------------------------------------------

    async def get_recommendations(self) -> list[dict]:
        """Get evolution recommendations."""
        recommendations = []

        patterns = await self.detect_patterns()
        for p in patterns:
            if p["type"] == "repeated_decision":
                recommendations.append({
                    "title": "Criar processo reutilizável",
                    "description": f"Decisão '{p['title']}' tomada {p['count']} vezes. Considere criar um template.",
                    "priority": "medium",
                })
            elif p["type"] == "domain_concentration":
                recommendations.append({
                    "title": "Diversificar conhecimento",
                    "description": f"Concentração em '{p['domain']}'. Explore outros domínios.",
                    "priority": "low",
                })

        return recommendations
