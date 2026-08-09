"""Bootstrap Cognitive Cortex (BCC) — RFC-0014 (STUDIO 10.0).

Local cognitive bootstrap layer of Intent OS that maintains system utility
and self-aware deterministic guidance even when no external AI Provider is configured.

Key Principles:
- Not an LLM; does not pretend or simulate external LLMs/providers.
- Operates deterministically, knowledge-bound, self-aware of its own limits.
- Accesses memory exclusively via AME ports.
- Registers explicitly in RRM as a built-in active local resource.
- Provider-neutral: specifies abstract requirements (reasoning, multimodal, etc.), never brand names.
- Zero dark patterns: no pressure, false urgency, or misleading limitations.
- Preserves project and mission continuity.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple, Union
from uuid import uuid4

from intent_kernel.time_utils import utc_iso
from intent_kernel.kom import KnowledgeState
from intent_kernel.ame import AdaptiveMemoryEngine, MemoryQuery, ContextAssembler, MemoryRetrievalResult


# ============================================================================
# 1. LOCAL COGNITIVE MODES
# ============================================================================

class LocalCognitiveMode(str, Enum):
    """Conceptual cognitive operational states for BCC (RFC-0014)."""
    LOCAL_CAPABLE = "LOCAL_CAPABLE"
    LOCAL_PARTIAL = "LOCAL_PARTIAL"
    EXTERNAL_PROVIDER_RECOMMENDED = "EXTERNAL_PROVIDER_RECOMMENDED"
    EXTERNAL_PROVIDER_REQUIRED = "EXTERNAL_PROVIDER_REQUIRED"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    OFFLINE_ONLY = "OFFLINE_ONLY"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"


# ============================================================================
# 2. CAPABILITY SELF-AWARENESS & CONTRACTS
# ============================================================================

@dataclass
class CognitiveCapabilityAssessment:
    """Self-aware capability assessment for a requested feature or goal."""
    requested_capability: str
    available_locally: bool
    available_via_agent: bool = False
    external_provider_required: bool = False
    missing_requirements: List[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""
    possible_next_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderConnectionIntent:
    """Declarative request specifying abstract provider requirements for setup/RRM."""
    intent_id: str = field(default_factory=lambda: f"pci_{uuid4().hex[:8]}")
    required_capabilities: List[str] = field(default_factory=list)
    preferred_privacy: str = "standard"  # "standard", "high", "airgapped"
    cost_preference: str = "balanced"   # "low_cost", "balanced", "unconstrained"
    local_or_cloud_preference: str = "any"  # "local_only", "cloud_allowed", "any"
    account_requirement: bool = True
    timestamp: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LocalMissionContinuation:
    """State descriptor for local mission continuation and state tracking."""
    mission_id: str
    project_id: str = "GLOBAL"
    current_state: str = "INITIAL"
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    required_capability: Optional[str] = None
    provider_required: bool = False
    resumable: bool = True
    last_updated: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BootstrapCognitiveResult:
    """Canonical result output produced by Bootstrap Cognitive Cortex."""
    result_id: str = field(default_factory=lambda: f"bcr_{uuid4().hex[:8]}")
    intent_id: str = ""
    state: LocalCognitiveMode = LocalCognitiveMode.LOCAL_CAPABLE
    summary: str = ""
    known_context: List[str] = field(default_factory=list)
    missing_context: List[str] = field(default_factory=list)
    available_local_capabilities: List[str] = field(default_factory=list)
    unavailable_capabilities: List[str] = field(default_factory=list)
    recommended_next_action: str = ""
    provider_requirement: str = "none"  # "none", "recommended", "required"
    provider_profile_requirement: Optional[str] = None
    local_plan: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    confidence: float = 1.0
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["state"] = self.state.value if isinstance(self.state, Enum) else str(self.state)
        return res


# ============================================================================
# 3. EXTENSION POINT CONTRACTS (PERCEPTION, ACTION, VERIFICATION)
# ============================================================================

@dataclass
class PerceptionEvent:
    """Event descriptor for Perception Extension Point (RFC-0014)."""
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex[:8]}")
    event_type: str = "external_event"  # file_changed, message_received, calendar_changed, project_updated, device_state_changed, sensor_event, external_event
    source: str = "system"
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_iso)


class PerceptionPort(Protocol):
    """Extension Point boundary for future system perception events."""
    async def receive_event(self, event: PerceptionEvent) -> None:
        ...

    async def get_recent_events(self, limit: int = 10) -> List[PerceptionEvent]:
        ...


@dataclass
class ActionCapability:
    """Capability descriptor for Action Extension Point (RFC-0014)."""
    capability_id: str  # file.create, message.send, calendar.create, document.update, application.control
    description: str
    params_schema: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = True


class ActionCapabilityPort(Protocol):
    """Extension Point boundary for future action capability execution."""
    def list_supported_actions(self) -> List[ActionCapability]:
        ...

    async def register_action_handler(self, capability_id: str, handler: Any) -> bool:
        ...


@dataclass
class ActionVerificationRequest:
    """Request contract for Action Verification Extension Point (RFC-0014)."""
    action_id: str
    action_type: str
    expected_outcome: str
    execution_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionVerificationResult:
    """Verification result contract enforcing ACTION SENT != ACTION SUCCEEDED."""
    action_id: str
    succeeded: bool
    observed_outcome: str
    verification_timestamp: str = field(default_factory=utc_iso)
    details: Dict[str, Any] = field(default_factory=dict)


class ActionVerificationPort(Protocol):
    """Extension Point boundary for verifying action execution outcomes."""
    async def verify_action(self, request: ActionVerificationRequest) -> ActionVerificationResult:
        ...


# ============================================================================
# 4. BOOTSTRAP COGNITIVE CORTEX CORE
# ============================================================================

class BootstrapCognitiveCortex:
    """Bootstrap Cognitive Cortex (BCC) core service.
    
    Provides deterministic, knowledge-bound local cognition, capability self-awareness,
    zero-provider guidance, and mission continuity.
    """

    SUPPORTED_LOCAL_CAPABILITIES: List[str] = [
        "local.intent_summary",
        "local.context_retrieval",
        "local.plan_explanation",
        "local.system_guidance",
        "local.project_management",
        "local.memory_storage",
        "local.mission_continuation",
    ]

    GENERATIVE_KEYWORDS: List[str] = [
        "campanha", "publicitária", "poema", "redigir", "escreva um artigo",
        "gerar texto", "artigo completo", "deep reasoning", "análise aberta",
        "creative writing", "generate image", "traduzir poema", "compor música",
    ]

    FIRST_RUN_PATTERNS: List[re.Pattern] = [
        re.compile(r"o que você consegue fazer", re.IGNORECASE),
        re.compile(r"quais (são )?suas capacidades", re.IGNORECASE),
        re.compile(r"como funciona", re.IGNORECASE),
        re.compile(r"primeira vez", re.IGNORECASE),
        re.compile(r"help|ajuda|manual|bem vindo", re.IGNORECASE),
    ]

    CONTINUATION_PATTERNS: List[re.Pattern] = [
        re.compile(r"onde paramos", re.IGNORECASE),
        re.compile(r"qual o status", re.IGNORECASE),
        re.compile(r"resumo da missão", re.IGNORECASE),
        re.compile(r"continuar projeto", re.IGNORECASE),
    ]

    def __init__(
        self,
        ame: Optional[Any] = None,
        rrm: Optional[Any] = None,
        policy: Optional[Any] = None,
    ) -> None:
        self._ame = ame
        self._rrm = rrm
        self._policy = policy
        self._missions: Dict[str, LocalMissionContinuation] = {}

        if self._rrm:
            self.register_in_rrm(self._rrm)

    def get_provider_count(self) -> int:
        """Query eligible external AI provider count via RRM query port or registry."""
        if not self._rrm:
            return 0
        try:
            if hasattr(self._rrm, "list_providers"):
                providers = self._rrm.list_providers(only_eligible=True)
                return len(providers)
            if hasattr(self._rrm, "query_resources"):
                from intent_kernel.rrm.models import ResourceQueryFilter, ResourceType
                filt = ResourceQueryFilter(resource_type=ResourceType.PROVIDER)
                res = self._rrm.query_resources(filt)
                return len([p for p in res if getattr(p, "is_eligible", False)])
        except Exception:
            return 0
        return 0

    def get_mode(
        self,
        intent_goal: str = "",
        requested_capability: Optional[str] = None,
    ) -> LocalCognitiveMode:
        """Determine conceptual LocalCognitiveMode deterministically."""
        if self._policy and getattr(self._policy, "offline_required", False):
            return LocalCognitiveMode.OFFLINE_ONLY

        p_count = self.get_provider_count()
        goal_lower = intent_goal.lower()

        is_generative = any(kw in goal_lower for kw in self.GENERATIVE_KEYWORDS)

        if p_count == 0:
            if is_generative:
                return LocalCognitiveMode.EXTERNAL_PROVIDER_REQUIRED
            return LocalCognitiveMode.LOCAL_CAPABLE

        if is_generative:
            return LocalCognitiveMode.EXTERNAL_PROVIDER_RECOMMENDED

        return LocalCognitiveMode.LOCAL_CAPABLE

    def assess_capability(self, requested_capability: str) -> CognitiveCapabilityAssessment:
        """Evaluate capability self-awareness for a requested capability."""
        req_lower = requested_capability.lower().strip()

        # Is it in BCC local capabilities?
        if req_lower in self.SUPPORTED_LOCAL_CAPABILITIES or any(req_lower == cap for cap in self.SUPPORTED_LOCAL_CAPABILITIES):
            return CognitiveCapabilityAssessment(
                requested_capability=requested_capability,
                available_locally=True,
                available_via_agent=False,
                external_provider_required=False,
                confidence=1.0,
                reason="Eu sei fazer. Capability suportada deterministicamente pela camada local do Intent OS.",
                possible_next_steps=["Executar via Bootstrap Cognitive Cortex local."],
            )

        # Can we organize/structure it locally, but not execute?
        if any(kw in req_lower for kw in ["plan", "organize", "structure", "plano", "estruturar", "organizar"]):
            return CognitiveCapabilityAssessment(
                requested_capability=requested_capability,
                available_locally=False,
                available_via_agent=True,
                external_provider_required=False,
                missing_requirements=["Execution Agent / Tool"],
                confidence=0.85,
                reason="Eu sei organizar e estruturar o plano localmente, mas a execução direta de side-effects depende de um componente/agente externo.",
                possible_next_steps=["Gerar plano de execução determinístico", "Aguardar confirmação ou agente de execução."],
            )

        # Does it require a generative provider?
        if any(kw in req_lower for kw in ["generative", "llm", "campanha", "poema", "reasoning", "artigo", "criatividade"]):
            return CognitiveCapabilityAssessment(
                requested_capability=requested_capability,
                available_locally=False,
                available_via_agent=False,
                external_provider_required=True,
                missing_requirements=["External AI Provider (reasoning / generative)"],
                confidence=0.95,
                reason="Preciso de um Provider. Esta funcionalidade requer capacidade gerativa ou raciocínio aberto fornecido por um Provider de IA externo.",
                possible_next_steps=[
                    "Conectar um Provider de IA compatível",
                    "Aproveitar o plano estruturado local enquanto o Provider não está conectado.",
                ],
            )

        # Otherwise unavailable
        return CognitiveCapabilityAssessment(
            requested_capability=requested_capability,
            available_locally=False,
            available_via_agent=False,
            external_provider_required=False,
            missing_requirements=[f"Capability '{requested_capability}' não cadastrada"],
            confidence=0.90,
            reason="Não há recurso disponível. Capability ou ferramenta não encontrada no RRM.",
            possible_next_steps=["Verificar RRM para cadastro da capability."],
        )

    async def evaluate_intent(
        self,
        intent: Union[Any, Dict[str, Any], str],
        project_id: str = "GLOBAL",
    ) -> BootstrapCognitiveResult:
        """Process structured intent deterministically without invoking external LLMs or APIs."""

        # 1. Normalize input intent
        intent_id = ""
        raw_input = ""
        goal = ""
        domain = "general"

        if isinstance(intent, str):
            raw_input = intent
            goal = intent
            intent_id = f"intent_{uuid4().hex[:8]}"
        elif isinstance(intent, dict):
            raw_input = intent.get("raw_input", intent.get("goal", ""))
            goal = intent.get("goal", raw_input)
            intent_id = intent.get("intent_id", f"intent_{uuid4().hex[:8]}")
            domain = intent.get("domain", "general")
        elif hasattr(intent, "goal"):
            goal = getattr(intent, "goal", "")
            raw_input = getattr(intent, "raw_input", goal)
            intent_id = getattr(intent, "intent_id", f"intent_{uuid4().hex[:8]}")
            domain = getattr(intent, "domain", "general")

        # 2. Retrieve authorized context exclusively via AME ports
        known_ctx: List[str] = []
        missing_ctx: List[str] = []
        ame_summary = ""

        if self._ame:
            try:
                # Use AME ports
                if hasattr(self._ame, "get_bcc_memory_summary"):
                    ame_summary = await self._ame.get_bcc_memory_summary(project_id=project_id)
                elif hasattr(self._ame, "query_for_bcc"):
                    ret_res = await self._ame.query_for_bcc(prompt=goal, project_id=project_id)
                    ame_summary = ContextAssembler.assemble_context(ret_res)

                if ame_summary and "nenhum objeto" not in ame_summary.lower():
                    known_ctx.append(ame_summary)
            except Exception:
                missing_ctx.append("AME memory retrieval encountered an error or was unavailable.")

        # 3. Check First-Run / Capabilities query
        is_first_run = any(p.search(goal) for p in self.FIRST_RUN_PATTERNS)
        if is_first_run:
            guidance = self.generate_first_run_guidance()
            guidance.intent_id = intent_id
            if known_ctx:
                guidance.known_context.extend(known_ctx)
            return guidance

        # 4. Check Continuation query ("Onde paramos?")
        is_continuation = any(p.search(goal) for p in self.CONTINUATION_PATTERNS)
        if is_continuation:
            mission = await self.query_mission_continuation(project_id=project_id)
            if mission or known_ctx:
                summary_parts = ["=== CONTINUIDADE DO PROJETO ==="]
                summary_parts.append(f"Projeto Ativo: {project_id}")
                if mission:
                    summary_parts.append(f"Missão ID: {mission.mission_id}")
                    summary_parts.append(f"Estado Atual: {mission.current_state}")
                    if mission.completed_steps:
                        summary_parts.append("Passos Concluídos:\n" + "\n".join(f" - {s}" for s in mission.completed_steps))
                    if mission.pending_steps:
                        summary_parts.append("Passos Pendentes:\n" + "\n".join(f" - {s}" for s in mission.pending_steps))
                if known_ctx:
                    summary_parts.append("\nContexto Conhecido Recuperado:\n" + "\n".join(known_ctx))

                return BootstrapCognitiveResult(
                    intent_id=intent_id,
                    state=LocalCognitiveMode.LOCAL_CAPABLE,
                    summary="\n".join(summary_parts),
                    known_context=known_ctx if known_ctx else [f"Missão {mission.mission_id if mission else 'local'} ativa."],
                    available_local_capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
                    recommended_next_action="Continuar passos pendentes do projeto.",
                    provider_requirement="none",
                    local_plan=mission.pending_steps if mission else ["Continuar execução conforme contexto registrado."],
                    confidence=1.0,
                )
            else:
                # Strictly knowledge-bound: UNKNOWN stays UNKNOWN
                return BootstrapCognitiveResult(
                    intent_id=intent_id,
                    state=LocalCognitiveMode.LOCAL_CAPABLE,
                    summary=f"Nenhum contexto prévio ou missão ativa encontrada para o projeto '{project_id}' na memória local (UNKNOWN).",
                    missing_context=[f"Sem histórico registrado no AME para o projeto '{project_id}'."],
                    available_local_capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
                    recommended_next_action="Registrar novo objetivo ou iniciar nova missão local.",
                    provider_requirement="none",
                    confidence=1.0,
                )

        # 5. Check Generative / External Provider Requirement
        is_generative = any(kw in goal.lower() for kw in self.GENERATIVE_KEYWORDS)
        mode = self.get_mode(intent_goal=goal)

        if is_generative or mode in (LocalCognitiveMode.EXTERNAL_PROVIDER_REQUIRED, LocalCognitiveMode.EXTERNAL_PROVIDER_RECOMMENDED):
            local_plan = [
                f"1. [Local] Estruturar o objetivo principal: '{goal}'",
                "2. [Local] Organizar pré-requisitos e contexto local no AME",
                "3. [Local] Mapear etapas e restrições da tarefa",
                "4. [Pendente External AI] Gerar síntese e conteúdo gerativo com Provider de IA",
            ]
            summary = (
                f"Consigo organizar esta tarefa e preparar o plano localmente.\n"
                f"Objetivo: '{goal}'\n"
                f"Para gerar o conteúdo gerativo completo ou análises abertas mais profundas, "
                f"é recomendado conectar um Provider de IA compatível (requer capacidade 'reasoning' e 'long_context')."
            )
            return BootstrapCognitiveResult(
                intent_id=intent_id,
                state=LocalCognitiveMode.EXTERNAL_PROVIDER_REQUIRED if self.get_provider_count() == 0 else LocalCognitiveMode.EXTERNAL_PROVIDER_RECOMMENDED,
                summary=summary,
                known_context=known_ctx,
                missing_context=["Capacidade gerativa externa de LLM para geração de texto aberto."],
                available_local_capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
                unavailable_capabilities=["generative.text_synthesis", "llm.open_reasoning"],
                recommended_next_action="Revisar o plano local estruturado ou conectar um Provider de IA no RRM.",
                provider_requirement="required" if self.get_provider_count() == 0 else "recommended",
                provider_profile_requirement="Requires reasoning, open-text generation and long_context.",
                local_plan=local_plan,
                limitations=[
                    "O Bootstrap Cognitive Cortex opera de forma determinística sem LLM.",
                    "Não inventa fatos nem gera texto poético/criativo sem Provider.",
                ],
                confidence=0.95,
            )

        # 6. Standard Local Capable Response
        local_plan = [
            f"1. [Local] Processar objetivo: '{goal}'",
            "2. [Local] Consultar e aplicar contexto autorizado do AME",
            "3. [Local] Disponibilizar diretrizes determinísticas e próximos passos",
        ]
        summary = (
            f"Processamento cognitivo local concluído com sucesso.\n"
            f"Objetivo: '{goal}'\n"
            f"O Intent OS organizou a solicitação deterministicamente utilizando as capacidades locais disponíveis."
        )

        return BootstrapCognitiveResult(
            intent_id=intent_id,
            state=LocalCognitiveMode.LOCAL_CAPABLE,
            summary=summary,
            known_context=known_ctx,
            available_local_capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
            recommended_next_action="Prosseguir com o plano local ou salvar no AME.",
            provider_requirement="none",
            local_plan=local_plan,
            limitations=["Execução de side-effects reais no mundo físico requer agentes/ferramentas cadastrados no RRM."],
            confidence=1.0,
        )

    def generate_first_run_guidance(self) -> BootstrapCognitiveResult:
        """Generate structured zero-provider / first-run orientation message."""
        summary = (
            "=== INTENT OS — PRIMEIRA EXECUÇÃO / MODO COGNITIVO LOCAL ===\n\n"
            "Bem-vindo ao Intent OS! O sistema está operacional com o Bootstrap Cognitive Cortex (BCC).\n\n"
            "O QUE FUNCIONA OFFLINE E LOCALMENTE:\n"
            " - Criação e gestão de Projetos\n"
            " - Registro de Objetivos e Decisões\n"
            " - Armazenamento e recuperação de memória no Adaptive Memory Engine (AME)\n"
            " - Estruturação determinística de Planos de Ação (CPE) e Orquestração (COR)\n"
            " - Verificação de Segurança e Governança pela Constituição\n\n"
            "O QUE DEPENDE DE UM PROVIDER DE IA EXTERNO:\n"
            " - Geração de texto criativo aberto, artigos e campanhas publicitárias\n"
            " - Raciocínio aberto não determinístico (llm.open_reasoning)\n"
            " - Análise multimodal avançada de imagens/áudio\n\n"
            "COMO CONECTAR UM PROVIDER:\n"
            " - Conectar um Provider de IA (OpenAI, Gemini, Claude, Ollama local, etc.) é totalmente OPCIONAL.\n"
            " - O Intent OS permanece totalmente útil e funcional para organização local sem qualquer conta externa."
        )

        return BootstrapCognitiveResult(
            intent_id="first_run_guidance",
            state=LocalCognitiveMode.LOCAL_CAPABLE,
            summary=summary,
            available_local_capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
            recommended_next_action="Criar um projeto ou registrar seu primeiro objetivo localmente.",
            provider_requirement="none",
            local_plan=[
                "1. Criar ou selecionar um projeto ativo no RRM",
                "2. Registrar objetivos e preferências no AME",
                "3. Opcional: Conectar um Provider de IA caso necessite de capacidades gerativas",
            ],
            limitations=["BCC opera deterministicamente sem modelos de linguagem gerativos."],
            confidence=1.0,
        )

    def generate_provider_connection_intent(
        self,
        required_capabilities: List[str],
        preferred_privacy: str = "standard",
        cost_preference: str = "balanced",
        local_or_cloud_preference: str = "any",
    ) -> ProviderConnectionIntent:
        """Generate abstract provider setup intent without handling credentials directly."""
        return ProviderConnectionIntent(
            required_capabilities=required_capabilities,
            preferred_privacy=preferred_privacy,
            cost_preference=cost_preference,
            local_or_cloud_preference=local_or_cloud_preference,
            account_requirement=True,
        )

    async def save_mission_continuation(self, continuation: LocalMissionContinuation) -> None:
        """Store or update mission continuation state."""
        self._missions[continuation.project_id] = continuation

    async def query_mission_continuation(
        self,
        project_id: str = "GLOBAL",
        mission_id: Optional[str] = None,
    ) -> Optional[LocalMissionContinuation]:
        """Query pending mission continuation for a project."""
        return self._missions.get(project_id)

    def get_diagnostics(self) -> Dict[str, Any]:
        """Produce safe diagnostic metrics without exposing sensitive content."""
        p_count = self.get_provider_count()
        return {
            "cortex_status": "healthy",
            "local_cognitive_mode": self.get_mode().value,
            "local_capabilities": self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
            "memory_available": self._ame is not None,
            "project_context_available": True,
            "external_provider_count": p_count,
            "offline_mode": self._policy and getattr(self._policy, "offline_required", False),
            "registered_missions_count": len(self._missions),
            "last_error": None,
            "limitations": [
                "BCC is a deterministic Cortex and does not replace LLM reasoning.",
                "External AI Providers amplify intelligence, but do not define Intent OS identity.",
            ],
        }

    def register_in_rrm(self, rrm_service: Any) -> bool:
        """Explicitly register BCC into RRM as a built-in active agent resource."""
        if not rrm_service:
            return False
        try:
            from intent_kernel.rrm.models import (
                AgentResource,
                AgentInstallationState,
                CapabilityResource,
                ResourceOrigin,
                ResourceStatus,
                ResourceType,
            )

            # 1. Register Capabilities
            for cap_name in self.SUPPORTED_LOCAL_CAPABILITIES:
                cap_res = CapabilityResource(
                    capability_id=cap_name,
                    name=cap_name,
                    description=f"Local deterministic capability {cap_name} provided by BCC.",
                    tags=["builtin", "local", "bcc"],
                    status=ResourceStatus.ACTIVE,
                    resource_origin=ResourceOrigin.CONFIGURATION,
                )
                if hasattr(rrm_service, "register_capability"):
                    rrm_service.register_capability(cap_res)

            # 2. Register BCC Agent
            agent_res = AgentResource(
                agent_id="agent_bcc_local_cortex",
                name="Bootstrap Cognitive Cortex",
                capabilities=self.SUPPORTED_LOCAL_CAPABILITIES.copy(),
                status=ResourceStatus.ACTIVE,
                installation_state=AgentInstallationState.AVAILABLE,
                resource_origin=ResourceOrigin.CONFIGURATION,
            )

            if hasattr(rrm_service, "register_agent"):
                rrm_service.register_agent(agent_res)
                return True
        except Exception:
            return False
        return False
