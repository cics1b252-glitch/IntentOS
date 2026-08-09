"""Test: First Run Experience + Cognitive Home."""

import pytest
from intent_kernel.onboarding import FirstRunExperience, OnboardingStep
from intent_kernel.home import CognitiveHome, HomeShortcut
from intent_kernel.kernel import Kernel


# ---------------------------------------------------------------------------
# First Run Experience
# ---------------------------------------------------------------------------

def test_onboarding_steps():
    fre = FirstRunExperience()
    assert len(fre.steps) == 6


def test_welcome_message():
    fre = FirstRunExperience()
    msg = fre.get_welcome_message()
    assert "Bem-vindo" in msg
    assert "Sistema Operacional Cognitivo" in msg


def test_constitution_explanation():
    fre = FirstRunExperience()
    msg = fre.get_constitution_explanation()
    assert "Soberania" in msg
    assert "Verdade" in msg
    assert "Continuidade" in msg
    assert "Evolução" in msg


def test_complete_step():
    fre = FirstRunExperience()
    result = fre.complete_step("welcome")
    assert result is not None
    assert result.completed is True


def test_progress():
    fre = FirstRunExperience()
    progress = fre.get_progress()
    assert progress["total"] == 6
    assert progress["completed"] == 0

    fre.complete_step("welcome")
    fre.complete_step("constitution")
    progress = fre.get_progress()
    assert progress["completed"] == 2
    assert progress["percentage"] == pytest.approx(33.3, abs=1)


def test_is_complete():
    fre = FirstRunExperience()
    assert fre.is_complete() is False
    for step in fre.steps:
        fre.complete_step(step.id)
    assert fre.is_complete() is True


# ---------------------------------------------------------------------------
# Cognitive Home
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_home_data():
    kernel = Kernel()
    home = CognitiveHome(kernel)
    data = await home.get_home_data()
    assert "greeting" in data
    assert "summary" in data
    assert "activities" in data
    assert "shortcuts" in data
    assert len(data["shortcuts"]) >= 5


@pytest.mark.asyncio
async def test_home_greeting():
    home = CognitiveHome()
    data = await home.get_home_data()
    assert data["greeting"] in ("Bom dia", "Boa tarde", "Boa noite")


def test_shortcuts():
    home = CognitiveHome()
    assert len(home.shortcuts) >= 5
    assert any(s.id == "chat" for s in home.shortcuts)
    assert any(s.id == "backup" for s in home.shortcuts)
