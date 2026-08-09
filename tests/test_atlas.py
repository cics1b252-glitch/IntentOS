"""Test: Atlas — Core App #1: Gestão Patrimonial e Inteligência Financeira."""

import pytest
from intent_kernel.modules.atlas import (
    Atlas,
    Asset,
    Portfolio,
    CashFlow,
    FinancialGoal,
    Scenario,
    RetirementPlan,
    AssetType,
    RiskProfile,
    ScenarioType,
    GoalStatus,
)


@pytest.fixture
def atlas():
    return Atlas()


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def test_create_portfolio(atlas):
    p = atlas.create_portfolio("Minha Carteira", RiskProfile.CONSERVADOR)
    assert p.name == "Minha Carteira"
    assert p.risk_profile == RiskProfile.CONSERVADOR
    assert p.id in atlas.portfolios


def test_add_asset(atlas):
    p = atlas.create_portfolio("Carteira")
    a = atlas.add_asset(
        p.id, "PETR4", "PETR4", AssetType.ACTION,
        quantity=100, avg_cost=25.0, current_price=28.0,
    )
    assert a is not None
    assert a.ticker == "PETR4"
    assert a.profit_loss == 300.0  # (28-25)*100
    assert a.profit_loss_pct == 12.0


def test_add_asset_invalid_portfolio(atlas):
    result = atlas.add_asset("invalid", "X", "X", AssetType.ACTION, 1, 1, 1)
    assert result is None


def test_portfolio_summary(atlas):
    p = atlas.create_portfolio("Carteira")
    atlas.add_asset(p.id, "PETR4", "PETR4", AssetType.ACTION, 100, 25.0, 28.0)
    atlas.add_asset(p.id, "ITUB4", "ITUB4", AssetType.ACTION, 50, 30.0, 32.0)

    summary = atlas.get_portfolio_summary(p.id)
    assert summary is not None
    assert summary["asset_count"] == 2
    assert summary["total_value"] == 100*28 + 50*32  # 2800+1600=4400
    assert summary["profit_loss"] == 100*3 + 50*2  # 300+100=400


def test_allocation_by_type(atlas):
    p = atlas.create_portfolio("Carteira")
    atlas.add_asset(p.id, "PETR4", "PETR4", AssetType.ACTION, 100, 25.0, 28.0)
    atlas.add_asset(p.id, "TESOURO", "Tesouro", AssetType.TESOURO, 1, 5000, 5200)

    alloc = p.allocation_by_type()
    assert "ação" in alloc
    assert "tesouro_direto" in alloc
    assert abs(alloc["ação"] + alloc["tesouro_direto"] - 100) < 0.1


# ---------------------------------------------------------------------------
# Cash Flow
# ---------------------------------------------------------------------------

def test_add_cash_flow(atlas):
    cf = atlas.add_cash_flow("Salário", 8000, "income", recurring=True, frequency="monthly")
    assert cf.amount == 8000
    assert cf.recurring is True


def test_cash_flow_summary(atlas):
    atlas.add_cash_flow("Salário", 8000, "income")
    atlas.add_cash_flow("Aluguel", -2000, "expense")
    atlas.add_cash_flow("Comida", -1500, "expense")

    summary = atlas.get_cash_flow_summary()
    assert summary["total_income"] == 8000
    assert summary["total_expenses"] == 3500
    assert summary["net_flow"] == 4500


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

def test_create_goal(atlas):
    g = atlas.create_goal("Reserva de Emergência", 30000, "2026-12-31")
    assert g.name == "Reserva de Emergência"
    assert g.target_amount == 30000


def test_update_goal_progress(atlas):
    g = atlas.create_goal("Viagem", 10000)
    atlas.update_goal_progress(g.id, 5000)
    assert g.progress_pct == 50.0
    assert g.remaining == 5000


def test_goal_completion(atlas):
    g = atlas.create_goal("Viagem", 10000)
    atlas.update_goal_progress(g.id, 10000)
    assert g.status == GoalStatus.CONCLUIDA
    assert g.progress_pct == 100.0


def test_goals_summary(atlas):
    atlas.create_goal("Meta 1", 10000, priority=2)
    atlas.create_goal("Meta 2", 5000, priority=1)
    goals = atlas.get_goals_summary()
    assert len(goals) == 2
    assert goals[0]["name"] == "Meta 2"  # priority 1 first


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_create_scenario(atlas):
    s = atlas.create_scenario("Aposentadoria", ScenarioType.BASE, {
        "monthly_contribution": 2000,
        "annual_return_pct": 10,
        "initial_amount": 50000,
    })
    assert s.name == "Aposentadoria"


def test_simulate_scenario(atlas):
    s = atlas.create_scenario("Teste", ScenarioType.BASE, {
        "monthly_contribution": 1000,
        "annual_return_pct": 12,
        "initial_amount": 10000,
    })
    projections = atlas.simulate_scenario(s.id, years=5)
    assert projections is not None
    assert len(projections) == 5
    assert projections[4]["balance"] > 10000  # should grow


def test_simulate_nonexistent(atlas):
    result = atlas.simulate_scenario("invalid")
    assert result is None


# ---------------------------------------------------------------------------
# Retirement
# ---------------------------------------------------------------------------

def test_create_retirement_plan(atlas):
    plan = atlas.create_retirement_plan(
        target_monthly_income=10000,
        current_savings=100000,
        monthly_contribution=3000,
        current_age=30,
        retirement_age=60,
    )
    assert plan.years_to_retirement == 30


def test_retirement_summary(atlas):
    plan = atlas.create_retirement_plan(
        target_monthly_income=10000,
        current_savings=100000,
        monthly_contribution=3000,
    )
    summary = atlas.get_retirement_summary(plan.id)
    assert summary is not None
    assert summary["target_corpus"] == 10000 * 12 * 25  # 3M
    assert summary["progress_pct"] > 0


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard(atlas):
    p = atlas.create_portfolio("Carteira")
    atlas.add_asset(p.id, "PETR4", "PETR4", AssetType.ACTION, 100, 25.0, 28.0)
    atlas.add_cash_flow("Salário", 8000, "income")
    atlas.create_goal("Emergência", 30000)

    dashboard = atlas.get_dashboard()
    assert dashboard["portfolio_count"] == 1
    assert dashboard["total_portfolio_value"] == 2800
    assert dashboard["cash_flow"]["total_income"] == 8000
    assert dashboard["active_goals"] == 1


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

def test_atlas_name(atlas):
    assert atlas.name == "atlas"


def test_atlas_version(atlas):
    assert atlas.version == "0.1.0"


# ---------------------------------------------------------------------------
# Asset calculations
# ---------------------------------------------------------------------------

def test_asset_profit_loss():
    a = Asset(quantity=100, avg_cost=25.0, current_price=30.0)
    assert a.total_cost == 2500
    assert a.current_value == 3000
    assert a.profit_loss == 500
    assert a.profit_loss_pct == 20.0


def test_asset_zero_cost():
    a = Asset(quantity=0, avg_cost=0, current_price=0)
    assert a.profit_loss_pct == 0.0
