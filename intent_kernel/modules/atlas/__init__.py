"""Atlas — Core App #1: Gestão Patrimonial e Inteligência Financeira.

Responsibilities:
- Patrimônio (assets tracking)
- Carteira (portfolio management)
- Renda passiva (passive income)
- FIIs, Ações, ETFs, Renda fixa
- Fluxo de caixa (cash flow)
- Cenários (scenario simulation)
- Aposentadoria (retirement planning)
- Objetivos financeiros (financial goals)
- Dashboards
- Projeções (projections)
- Acompanhamento da estratégia (strategy tracking)

Uses Kernel services exclusively — no parallel memory logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from intent_kernel.types import Domain, new_id, utcnow


# ---------------------------------------------------------------------------
# Atlas Types
# ---------------------------------------------------------------------------

class AssetType(str, Enum):
    """Types of financial assets."""
    ACTION = "ação"
    FII = "fii"
    ETF = "etf"
    CDB = "cdb"
    LCI = "lci"
    LCA = "lca"
    TESOURO = "tesouro_direto"
    POUPANCA = "poupanca"
    FUNDO = "fundo"
    CRYPTO = "crypto"
    IMOVEL = "imovel"
    OUTRO = "outro"


class RiskProfile(str, Enum):
    """Investor risk profiles."""
    CONSERVADOR = "conservador"
    MODERADO = "moderado"
    AGRESSIVO = "agressivo"


class ScenarioType(str, Enum):
    """Financial scenario types."""
    CONSERVADOR = "conservador"
    BASE = "base"
    AGRESSIVO = "agressivo"


class GoalStatus(str, Enum):
    """Financial goal status."""
    ATIVA = "ativa"
    CONCLUIDA = "concluida"
    PAUSADA = "pausada"
    CANCELADA = "cancelada"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Asset:
    """A financial asset in the portfolio."""
    id: str = field(default_factory=new_id)
    name: str = ""
    ticker: str = ""
    asset_type: AssetType = AssetType.OUTRO
    quantity: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0
    sector: str = ""
    currency: str = "BRL"
    acquired_at: str = ""
    notes: str = ""

    @property
    def total_cost(self) -> float:
        return self.quantity * self.avg_cost

    @property
    def current_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def profit_loss(self) -> float:
        return self.current_value - self.total_cost

    @property
    def profit_loss_pct(self) -> float:
        if self.total_cost == 0:
            return 0.0
        return (self.profit_loss / self.total_cost) * 100


@dataclass
class Portfolio:
    """A financial portfolio containing assets."""
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    risk_profile: RiskProfile = RiskProfile.MODERADO
    assets: list[Asset] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: utcnow().isoformat())

    @property
    def total_value(self) -> float:
        return sum(a.current_value for a in self.assets)

    @property
    def total_cost(self) -> float:
        return sum(a.total_cost for a in self.assets)

    @property
    def total_profit_loss(self) -> float:
        return self.total_value - self.total_cost

    @property
    def total_profit_loss_pct(self) -> float:
        if self.total_cost == 0:
            return 0.0
        return (self.total_profit_loss / self.total_cost) * 100

    def allocation_by_type(self) -> dict[str, float]:
        """Asset allocation by type (percentage)."""
        if self.total_value == 0:
            return {}
        alloc = {}
        for asset in self.assets:
            t = asset.asset_type.value
            alloc[t] = alloc.get(t, 0) + asset.current_value
        return {k: round((v / self.total_value) * 100, 2) for k, v in alloc.items()}


@dataclass
class CashFlow:
    """A cash flow entry."""
    id: str = field(default_factory=new_id)
    description: str = ""
    amount: float = 0.0  # positive = income, negative = expense
    category: str = ""
    recurring: bool = False
    frequency: str = ""  # monthly, weekly, etc.
    date: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class FinancialGoal:
    """A financial goal with target and progress."""
    id: str = field(default_factory=new_id)
    name: str = ""
    target_amount: float = 0.0
    current_amount: float = 0.0
    deadline: str = ""
    status: GoalStatus = GoalStatus.ATIVA
    priority: int = 1  # 1 = highest
    notes: str = ""

    @property
    def progress_pct(self) -> float:
        if self.target_amount == 0:
            return 0.0
        return min(100.0, (self.current_amount / self.target_amount) * 100)

    @property
    def remaining(self) -> float:
        return max(0, self.target_amount - self.current_amount)


@dataclass
class Scenario:
    """A financial scenario simulation."""
    id: str = field(default_factory=new_id)
    name: str = ""
    scenario_type: ScenarioType = ScenarioType.BASE
    assumptions: dict = field(default_factory=dict)
    projections: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class RetirementPlan:
    """Retirement planning data."""
    id: str = field(default_factory=new_id)
    target_monthly_income: float = 0.0
    current_savings: float = 0.0
    monthly_contribution: float = 0.0
    expected_return_pct: float = 10.0  # annual
    retirement_age: int = 60
    current_age: int = 30
    years_to_retirement: int = 30

    @property
    def years_needed(self) -> float:
        """Years needed to reach target at current pace."""
        if self.monthly_contribution == 0:
            return float('inf')
        # Simple compound interest approximation
        monthly_rate = self.expected_return_pct / 100 / 12
        if monthly_rate == 0:
            return max(0, (self.target_monthly_income * 12 * 25 - self.current_savings) / (self.monthly_contribution * 12))
        # FV = PV(1+r)^n + PMT*((1+r)^n - 1)/r
        # Solve for n when FV = target
        target_corpus = self.target_monthly_income * 12 * 25  # 25x annual expenses
        # Approximation
        if self.current_savings >= target_corpus:
            return 0.0
        return max(0, self.years_to_retirement)  # simplified


# ---------------------------------------------------------------------------
# Atlas Core App
# ---------------------------------------------------------------------------

class Atlas:
    """Atlas — Gestão Patrimonial e Inteligência Financeira.

    Core App #1 for Intent OS.
    Uses Kernel services exclusively.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.portfolios: dict[str, Portfolio] = {}
        self.cash_flows: list[CashFlow] = []
        self.goals: dict[str, FinancialGoal] = {}
        self.scenarios: dict[str, Scenario] = {}
        self.retirement_plans: dict[str, RetirementPlan] = {}

    @property
    def name(self) -> str:
        return "atlas"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Gestão Patrimonial e Inteligência Financeira"

    # -------------------------------------------------------------------
    # Portfolio Management
    # -------------------------------------------------------------------

    def create_portfolio(
        self,
        name: str,
        risk_profile: RiskProfile = RiskProfile.MODERADO,
        description: str = "",
    ) -> Portfolio:
        """Create a new portfolio."""
        portfolio = Portfolio(
            name=name,
            risk_profile=risk_profile,
            description=description,
        )
        self.portfolios[portfolio.id] = portfolio
        return portfolio

    def add_asset(
        self,
        portfolio_id: str,
        name: str,
        ticker: str,
        asset_type: AssetType,
        quantity: float,
        avg_cost: float,
        current_price: float,
        sector: str = "",
    ) -> Asset | None:
        """Add an asset to a portfolio."""
        portfolio = self.portfolios.get(portfolio_id)
        if not portfolio:
            return None

        asset = Asset(
            name=name,
            ticker=ticker,
            asset_type=asset_type,
            quantity=quantity,
            avg_cost=avg_cost,
            current_price=current_price,
            sector=sector,
        )
        portfolio.assets.append(asset)
        portfolio.updated_at = utcnow().isoformat()
        return asset

    def get_portfolio_summary(self, portfolio_id: str) -> dict | None:
        """Get a complete portfolio summary."""
        portfolio = self.portfolios.get(portfolio_id)
        if not portfolio:
            return None

        return {
            "id": portfolio.id,
            "name": portfolio.name,
            "risk_profile": portfolio.risk_profile.value,
            "total_value": portfolio.total_value,
            "total_cost": portfolio.total_cost,
            "profit_loss": portfolio.total_profit_loss,
            "profit_loss_pct": portfolio.total_profit_loss_pct,
            "allocation": portfolio.allocation_by_type(),
            "asset_count": len(portfolio.assets),
            "assets": [
                {
                    "name": a.name,
                    "ticker": a.ticker,
                    "type": a.asset_type.value,
                    "quantity": a.quantity,
                    "current_value": a.current_value,
                    "profit_loss_pct": a.profit_loss_pct,
                }
                for a in portfolio.assets
            ],
        }

    # -------------------------------------------------------------------
    # Cash Flow
    # -------------------------------------------------------------------

    def add_cash_flow(
        self,
        description: str,
        amount: float,
        category: str = "",
        recurring: bool = False,
        frequency: str = "",
    ) -> CashFlow:
        """Add a cash flow entry."""
        cf = CashFlow(
            description=description,
            amount=amount,
            category=category,
            recurring=recurring,
            frequency=frequency,
        )
        self.cash_flows.append(cf)
        return cf

    def get_cash_flow_summary(self) -> dict:
        """Get cash flow summary."""
        income = sum(cf.amount for cf in self.cash_flows if cf.amount > 0)
        expenses = sum(cf.amount for cf in self.cash_flows if cf.amount < 0)
        return {
            "total_income": income,
            "total_expenses": abs(expenses),
            "net_flow": income + expenses,
            "entry_count": len(self.cash_flows),
        }

    # -------------------------------------------------------------------
    # Financial Goals
    # -------------------------------------------------------------------

    def create_goal(
        self,
        name: str,
        target_amount: float,
        deadline: str = "",
        priority: int = 1,
    ) -> FinancialGoal:
        """Create a financial goal."""
        goal = FinancialGoal(
            name=name,
            target_amount=target_amount,
            deadline=deadline,
            priority=priority,
        )
        self.goals[goal.id] = goal
        return goal

    def update_goal_progress(self, goal_id: str, amount: float) -> FinancialGoal | None:
        """Update goal progress."""
        goal = self.goals.get(goal_id)
        if not goal:
            return None
        goal.current_amount = amount
        if goal.current_amount >= goal.target_amount:
            goal.status = GoalStatus.CONCLUIDA
        return goal

    def get_goals_summary(self) -> list[dict]:
        """Get all goals with progress."""
        return [
            {
                "id": g.id,
                "name": g.name,
                "target": g.target_amount,
                "current": g.current_amount,
                "progress_pct": g.progress_pct,
                "remaining": g.remaining,
                "status": g.status.value,
                "deadline": g.deadline,
            }
            for g in sorted(self.goals.values(), key=lambda g: g.priority)
        ]

    # -------------------------------------------------------------------
    # Scenarios
    # -------------------------------------------------------------------

    def create_scenario(
        self,
        name: str,
        scenario_type: ScenarioType,
        assumptions: dict,
    ) -> Scenario:
        """Create a financial scenario."""
        scenario = Scenario(
            name=name,
            scenario_type=scenario_type,
            assumptions=assumptions,
        )
        self.scenarios[scenario.id] = scenario
        return scenario

    def simulate_scenario(self, scenario_id: str, years: int = 10) -> list[dict] | None:
        """Run a simple scenario simulation."""
        scenario = self.scenarios.get(scenario_id)
        if not scenario:
            return None

        # Simple projection based on assumptions
        monthly_contribution = scenario.assumptions.get("monthly_contribution", 0)
        annual_return = scenario.assumptions.get("annual_return_pct", 10) / 100
        initial = scenario.assumptions.get("initial_amount", 0)

        projections = []
        balance = initial
        monthly_rate = annual_return / 12

        for year in range(1, years + 1):
            for month in range(12):
                balance = balance * (1 + monthly_rate) + monthly_contribution
            projections.append({
                "year": year,
                "balance": round(balance, 2),
                "total_invested": round(initial + monthly_contribution * 12 * year, 2),
                "total_return": round(balance - initial - monthly_contribution * 12 * year, 2),
            })

        scenario.projections = projections
        return projections

    # -------------------------------------------------------------------
    # Retirement
    # -------------------------------------------------------------------

    def create_retirement_plan(
        self,
        target_monthly_income: float,
        current_savings: float,
        monthly_contribution: float,
        expected_return_pct: float = 10.0,
        current_age: int = 30,
        retirement_age: int = 60,
    ) -> RetirementPlan:
        """Create a retirement plan."""
        plan = RetirementPlan(
            target_monthly_income=target_monthly_income,
            current_savings=current_savings,
            monthly_contribution=monthly_contribution,
            expected_return_pct=expected_return_pct,
            current_age=current_age,
            retirement_age=retirement_age,
            years_to_retirement=retirement_age - current_age,
        )
        self.retirement_plans[plan.id] = plan
        return plan

    def get_retirement_summary(self, plan_id: str) -> dict | None:
        """Get retirement plan summary."""
        plan = self.retirement_plans.get(plan_id)
        if not plan:
            return None

        target_corpus = plan.target_monthly_income * 12 * 25
        return {
            "id": plan.id,
            "target_monthly_income": plan.target_monthly_income,
            "target_corpus": target_corpus,
            "current_savings": plan.current_savings,
            "monthly_contribution": plan.monthly_contribution,
            "expected_return_pct": plan.expected_return_pct,
            "years_to_retirement": plan.years_to_retirement,
            "progress_pct": round((plan.current_savings / target_corpus) * 100, 1) if target_corpus > 0 else 0,
            "on_track": plan.current_savings >= target_corpus * 0.5,  # simplified check
        }

    # -------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------

    def get_dashboard(self) -> dict:
        """Get a complete Atlas dashboard."""
        total_portfolio_value = sum(p.total_value for p in self.portfolios.values())
        total_portfolio_cost = sum(p.total_cost for p in self.portfolios.values())
        cash_flow = self.get_cash_flow_summary()
        goals = self.get_goals_summary()

        return {
            "total_portfolio_value": total_portfolio_value,
            "total_portfolio_cost": total_portfolio_cost,
            "total_profit_loss": total_portfolio_value - total_portfolio_cost,
            "portfolio_count": len(self.portfolios),
            "cash_flow": cash_flow,
            "goals": goals,
            "active_goals": sum(1 for g in self.goals.values() if g.status == GoalStatus.ATIVA),
            "scenarios": len(self.scenarios),
            "retirement_plans": len(self.retirement_plans),
        }

    # -------------------------------------------------------------------
    # Knowledge Integration (via Kernel)
    # -------------------------------------------------------------------

    async def record_financial_decision(
        self,
        question: str,
        chosen: str,
        alternatives: list[str],
        rationale: str,
        confidence: float = 0.8,
    ) -> dict:
        """Record a financial decision to the Knowledge Core via Kernel."""
        if not self.kernel:
            return {"error": "Kernel not connected"}

        from intent_kernel.pkb.models import KnowledgeEvent
        from intent_kernel.types import EventType

        event = KnowledgeEvent(
            type=EventType.DECISION,
            domain=Domain.FINANCE,
            title=f"Decisão financeira: {question[:60]}",
            content={
                "question": question,
                "chosen": chosen,
                "alternatives": alternatives,
                "rationale": rationale,
            },
            summary=f"Decisão: {chosen}",
            confidence=confidence,
            source="atlas",
            tags=["finance", "decision", "atlas"],
        )

        # Use Kernel's knowledge manager
        result = await self.kernel.knowledge.ingest([event])
        return {
            "recorded": True,
            "events_created": result.approved + result.candidate,
            "event_id": event.id,
        }
