"""Default Constitution — v1.0.0."""

from intent_kernel.constitution.models import Constitution, Constraint, Pillar
from intent_kernel.types import Severity


def create_default_constitution() -> Constitution:
    """Create the default Constitution with all four pillars."""
    return Constitution(
        version="1.0.0",
        supreme_principle=(
            "O Intent OS existe para ampliar a capacidade cognitiva "
            "do usuário, nunca para substituí-la."
        ),
        pillars=[
            Pillar(
                id="soberania",
                name="Soberania",
                description="O usuário é dono dos seus dados",
                constraints=[
                    Constraint(
                        id="data_sovereignty",
                        rule="Dados do usuário nunca saem sem consentimento",
                        enforced_by="provider_manager",
                        severity=Severity.BLOCK,
                    ),
                    Constraint(
                        id="user_delete_real",
                        rule="Delete é remoção real, não mark-as-deleted",
                        enforced_by="knowledge_store",
                        severity=Severity.BLOCK,
                    ),
                ],
            ),
            Pillar(
                id="verdade",
                name="Verdade",
                description="O sistema nunca inventa",
                constraints=[
                    Constraint(
                        id="no_fake_facts",
                        rule="Nunca apresentar estimativa como fato",
                        enforced_by="output_validator",
                        severity=Severity.BLOCK,
                    ),
                    Constraint(
                        id="confidence_required",
                        rule="Todo output inclui confidence score",
                        enforced_by="output_validator",
                        severity=Severity.BLOCK,
                    ),
                ],
            ),
            Pillar(
                id="continuidade",
                name="Continuidade",
                description="Nenhum conhecimento importante morre em conversa",
                constraints=[
                    Constraint(
                        id="knowledge_survives",
                        rule="Conhecimento approved persiste entre sessões",
                        enforced_by="knowledge_manager",
                        severity=Severity.BLOCK,
                    ),
                ],
            ),
            Pillar(
                id="evolucao",
                name="Evolução",
                description="O sistema nunca está pronto",
                constraints=[
                    Constraint(
                        id="kernel_independence",
                        rule="Kernel não depende de services externos",
                        enforced_by="import_validator",
                        severity=Severity.BLOCK,
                    ),
                    Constraint(
                        id="module_isolation",
                        rule="Módulos não acessam estado de outros módulos",
                        enforced_by="module_router",
                        severity=Severity.BLOCK,
                    ),
                ],
            ),
        ],
    )
