"""First Run Experience — Onboarding for new Intent OS users.

When the user opens Intent OS for the first time:
1. Welcome presentation
2. Constitution explanation
3. Knowledge Core creation
4. Cognitive identity creation
5. Workspace tour
6. First example project

The user must understand the system in minutes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OnboardingStep:
    """A step in the onboarding flow."""
    id: str
    title: str
    description: str
    icon: str
    action: str  # "info", "action", "done"
    completed: bool = False


class FirstRunExperience:
    """First run experience for Intent OS."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel
        self.steps = self._init_steps()

    def _init_steps(self) -> list[OnboardingStep]:
        return [
            OnboardingStep("welcome", "Bem-vindo ao Intent OS", "Seu Sistema Operacional Cognitivo pessoal", "🧠", "info"),
            OnboardingStep("constitution", "A Constitution", "Os princípios que governam o sistema", "📜", "info"),
            OnboardingStep("knowledge_core", "Knowledge Core", "Sua base de conhecimento pessoal", "💾", "action"),
            OnboardingStep("identity", "Identidade Cognitiva", "Seu ID único no sistema", "🪪", "action"),
            OnboardingStep("tour", "Tour Rápido", "Conheça o Workspace", "🗺️", "info"),
            OnboardingStep("first_project", "Primeiro Projeto", "Vamos criar seu primeiro projeto", "🚀", "action"),
        ]

    def get_welcome_message(self) -> str:
        return (
            "Bem-vindo ao Intent OS!\n\n"
            "Este é um Sistema Operacional Cognitivo — diferente de qualquer "
            "assistente ou ferramenta que você já usou.\n\n"
            "O Intent OS não apenas responde perguntas. Ele:\n"
            "• Aprende com você\n"
            "• Preserva seu conhecimento\n"
            "• Conecta suas ideias\n"
            "• Evolui ao longo do tempo\n\n"
            "Vamos começar!"
        )

    def get_constitution_explanation(self) -> str:
        return (
            "📜 A Constitution\n\n"
            "A Constitution é o conjunto de princípios que governam o Intent OS.\n\n"
            "Ela não é apenas um documento — é um componente ativo do sistema.\n\n"
            "4 Princípios Fundamentais:\n"
            "1. Soberania — Seus dados pertencem a você\n"
            "2. Verdade — O sistema nunca inventa\n"
            "3. Continuidade — Conhecimento preservado entre sessões\n"
            "4. Evolução — O sistema aprende e melhora continuamente\n\n"
            "7 Guardians protegem esses princípios em tempo real."
        )

    def complete_step(self, step_id: str) -> OnboardingStep | None:
        for step in self.steps:
            if step.id == step_id:
                step.completed = True
                return step
        return None

    def get_progress(self) -> dict:
        completed = sum(1 for s in self.steps if s.completed)
        return {
            "total": len(self.steps),
            "completed": completed,
            "percentage": (completed / len(self.steps)) * 100,
            "steps": [
                {"id": s.id, "title": s.title, "completed": s.completed}
                for s in self.steps
            ],
        }

    def is_complete(self) -> bool:
        return all(s.completed for s in self.steps)
