"""Evolution Engine v3 — The personality of Intent OS.

Components:
- Opportunity Engine: detects growth opportunities
- Risk Engine: detects cognitive risks
- Goal Evolution: objectives mature over time
- Cognitive Coach: continuous evidence-based mentoring
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Opportunity:
    """A detected growth opportunity."""
    id: str = ""
    title: str = ""
    description: str = ""
    opportunity_type: str = ""  # abandoned_project, knowledge_connection, near_goal, review
    domain: str = ""
    confidence: float = 0.0
    actionable: bool = True


@dataclass
class Risk:
    """A detected cognitive risk."""
    id: str = ""
    title: str = ""
    description: str = ""
    risk_type: str = ""  # focus_excess, impulsive_decision, forgotten_project, unrevised_knowledge
    severity: str = ""   # low, medium, high
    suggestion: str = ""


@dataclass
class GoalSuggestion:
    """A suggestion for goal evolution."""
    goal_id: str = ""
    suggestion_type: str = ""  # split, merge, update_priority, close
    description: str = ""
    rationale: str = ""


@dataclass
class CoachMessage:
    """A message from the Cognitive Coach."""
    message: str = ""
    basis: str = ""     # evidence from KC
    confidence: float = 0.0
    category: str = ""  # progress, pattern, suggestion, encouragement


class OpportunityEngine:
    """Detects growth opportunities in the Knowledge Core."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def detect(self) -> list[Opportunity]:
        opportunities = []
        if not self.kernel:
            return opportunities

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            # Opportunity: near-completion goals
            goals = [e for e in events if e.type.value == "goal"]
            for goal in goals:
                if goal.confidence >= 0.8:
                    opportunities.append(Opportunity(
                        id=f"opp_{goal.id[:8]}",
                        title=f"Meta próxima de conclusão: {goal.title[:40]}",
                        description="Esta meta possui alta confiança. Considere finalizá-la.",
                        opportunity_type="near_goal",
                        domain=goal.domain.value,
                        confidence=goal.confidence,
                    ))

            # Opportunity: knowledge connections
            domains = {}
            for e in events:
                d = e.domain.value
                domains.setdefault(d, []).append(e)
            for domain, domain_events in domains.items():
                if len(domain_events) >= 3:
                    opportunities.append(Opportunity(
                        id=f"conn_{domain}",
                        title=f"Conhecimento maduro em '{domain}'",
                        description=f"{len(domain_events)} eventos podem ser conectados.",
                        opportunity_type="knowledge_connection",
                        domain=domain,
                        confidence=0.7,
                    ))

        except Exception:
            pass

        return opportunities


class RiskEngine:
    """Detects cognitive risks."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def detect(self) -> list[Risk]:
        risks = []
        if not self.kernel:
            return risks

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            # Risk: domain overconcentration
            domains = {}
            for e in events:
                d = e.domain.value
                domains[d] = domains.get(d, 0) + 1
            if domains:
                top = max(domains, key=domains.get)
                pct = domains[top] / len(events)
                if pct > 0.75:
                    risks.append(Risk(
                        id="risk_focus",
                        title=f"Excesso de foco em '{top}'",
                        description=f"{pct*100:.0f}% do conhecimento está em um único domínio.",
                        risk_type="focus_excess",
                        severity="medium",
                        suggestion="Explore outros domínios para diversificar o conhecimento.",
                    ))

            # Risk: low confidence decisions
            decisions = [e for e in events if e.type.value == "decision"]
            low_conf = [d for d in decisions if d.confidence < 0.5]
            if low_conf and len(low_conf) > len(decisions) * 0.4:
                risks.append(Risk(
                    id="risk_impulsive",
                    title="Muitas decisões com baixa confiança",
                    description=f"{len(low_conf)} de {len(decisions)} decisões abaixo de 0.5.",
                    risk_type="impulsive_decision",
                    severity="high",
                    suggestion="Considere revisar decisões antes de executá-las.",
                ))

        except Exception:
            pass

        return risks


class GoalEvolutionEngine:
    """Goals that mature over time."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def analyze(self) -> list[GoalSuggestion]:
        suggestions = []
        if not self.kernel:
            return suggestions

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            goals = [e for e in events if e.type.value == "goal"]
            for goal in goals:
                # High confidence = near completion
                if goal.confidence >= 0.9:
                    suggestions.append(GoalSuggestion(
                        goal_id=goal.id,
                        suggestion_type="close",
                        description=f"Meta '{goal.title[:30]}' parece concluída (confiança {goal.confidence}).",
                        rationale="Alta confiança indica conclusão.",
                    ))
                # Low confidence = may need update
                elif goal.confidence < 0.3:
                    suggestions.append(GoalSuggestion(
                        goal_id=goal.id,
                        suggestion_type="update_priority",
                        description=f"Meta '{goal.title[:30]}' com baixa confiança.",
                        rationale="Considere reavaliar esta meta.",
                    ))

        except Exception:
            pass

        return suggestions


class CognitiveCoach:
    """Continuous evidence-based mentoring."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    async def generate_messages(self) -> list[CoachMessage]:
        messages = []
        if not self.kernel:
            return messages

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=500))

            if not events:
                return messages

            # Progress message
            decisions = [e for e in events if e.type.value == "decision"]
            if len(decisions) >= 5:
                avg_conf = sum(d.confidence for d in decisions) / len(decisions)
                messages.append(CoachMessage(
                    message=f"Você já tomou {len(decisions)} decisões registradas. Confiança média: {avg_conf:.0%}.",
                    basis=f"{len(decisions)} eventos de decisão na KC",
                    confidence=0.9,
                    category="progress",
                ))

            # Pattern message
            domains = set(e.domain.value for e in events)
            if len(domains) >= 3:
                messages.append(CoachMessage(
                    message=f"Seu conhecimento abrange {len(domains)} domínios. Isso demonstra diversidade intelectual.",
                    basis=f"Domínios: {', '.join(domains)}",
                    confidence=0.85,
                    category="progress",
                ))

            # Encouragement
            if len(events) >= 10:
                messages.append(CoachMessage(
                    message="Sua Knowledge Core está crescendo. Cada evento registrado é um passo na sua evolução.",
                    basis=f"{len(events)} eventos totais",
                    confidence=0.95,
                    category="encouragement",
                ))

        except Exception:
            pass

        return messages


class EvolutionEngineV3:
    """Complete Evolution Engine v3."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.opportunities = OpportunityEngine(kernel)
        self.risks = RiskEngine(kernel)
        self.goals = GoalEvolutionEngine(kernel)
        self.coach = CognitiveCoach(kernel)

    @property
    def name(self) -> str:
        return "evolution_engine_v3"

    async def full_analysis(self) -> dict:
        """Complete evolutionary analysis."""
        return {
            "opportunities": [
                {"id": o.id, "title": o.title, "type": o.opportunity_type, "domain": o.domain}
                for o in await self.opportunities.detect()
            ],
            "risks": [
                {"id": r.id, "title": r.title, "type": r.risk_type, "severity": r.severity, "suggestion": r.suggestion}
                for r in await self.risks.detect()
            ],
            "goal_suggestions": [
                {"goal_id": g.goal_id, "type": g.suggestion_type, "description": g.description}
                for g in await self.goals.analyze()
            ],
            "coach_messages": [
                {"message": m.message, "category": m.category, "confidence": m.confidence}
                for m in await self.coach.generate_messages()
            ],
        }
