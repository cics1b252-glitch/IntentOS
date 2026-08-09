"""Capability Orchestrator (COR) — RFC-0010.

Transforms an ExecutionPlan into a distributed, capability-matched, dependency-aware ExecutionGraph.
Decides 'WHO' executes each step by scoring and ranking Agents, Providers, and Accounts dynamically
without executing side-effects or invoking LLMs/tools.
"""

from enum import Enum
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from intent_kernel.cpe import ExecutionPlan, PlanStep
from intent_kernel.time_utils import utc_iso


# --- Execution Environment Contracts ---

class ExecutionEnvironmentType(str, Enum):
    """Supported types of execution environments (RFC-0011.1)."""
    LOCAL_PROCESS = "local_process"
    DESKTOP = "desktop"
    BROWSER = "browser"
    MOBILE = "mobile"
    SERVER = "server"
    CLOUD = "cloud"
    EDGE = "edge"
    REMOTE = "remote"


@dataclass
class ExecutionEnvironment:
    """Execution Environment descriptor registered in the Catalog."""
    environment_id: str
    type: ExecutionEnvironmentType
    status: str = "active"  # "active", "degraded", "unavailable"
    capabilities: List[str] = field(default_factory=list)
    available_tools: List[str] = field(default_factory=list)
    network_access: bool = True
    privacy_level: str = "standard"  # "standard", "high", "airgapped"
    latency_class: str = "low"  # "ultra_low", "low", "medium", "high"
    cost_class: str = "free"  # "free", "low", "medium", "high"
    resource_limits: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["type"] = self.type.value if isinstance(self.type, Enum) else str(self.type)
        return res


# --- Registrations & Catalog Contracts ---

@dataclass
class CapabilityRegistration:
    """Capability descriptor registered in the Catalog."""
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    provided_by_agents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRegistration:
    """Agent descriptor registered in the Catalog."""
    agent_id: str
    name: str
    capabilities: List[str] = field(default_factory=list)
    specialization: List[str] = field(default_factory=list)
    availability: float = 1.0  # 0.0 to 1.0
    status: str = "active"  # "active", "degraded", "offline"
    version: str = "1.0.0"
    historical_confidence: float = 0.90  # 0.0 to 1.0
    cost_tier: float = 0.01  # Normalized cost metric
    latency_tier: float = 0.2  # Normalized latency in seconds
    supported_domains: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderRegistration:
    """AI Provider profile registered in the Catalog."""
    provider_id: str
    name: str
    reasoning_score: float = 0.85  # 0.0 to 1.0
    tool_use_support: bool = True
    context_window: int = 128000
    cost_per_1k_tokens: float = 0.002
    privacy_tier: str = "standard"  # "standard", "high"
    availability: float = 1.0
    multimodal: bool = False
    status: str = "active"  # "active", "degraded", "offline"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccountRegistration:
    """Service Account descriptor registered in the Catalog."""
    account_id: str
    provider_id: str
    name: str
    quota_remaining: float = 100000.0
    rate_limit_rpm: int = 1000
    priority: int = 5  # 1 (low) to 10 (high)
    cost_multiplier: float = 1.0
    status: str = "active"  # "active", "throttled", "exhausted"
    allowed_policies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RegistryCatalog:
    """Central dynamic registry of capabilities, agents, providers, accounts, and execution environments.

    All discovery occurs via query methods on this catalog.
    No hardcoded lists are assumed.
    """

    def __init__(self, populate_defaults: bool = True):
        self._capabilities: Dict[str, CapabilityRegistration] = {}
        self._agents: Dict[str, AgentRegistration] = {}
        self._providers: Dict[str, ProviderRegistration] = {}
        self._accounts: Dict[str, AccountRegistration] = {}
        self._environments: Dict[str, ExecutionEnvironment] = {}

        if populate_defaults:
            self.populate_default_catalog()

    def register_capability(self, cap: CapabilityRegistration) -> None:
        self._capabilities[cap.name] = cap

    def register_agent(self, agent: AgentRegistration) -> None:
        self._agents[agent.agent_id] = agent

    def register_provider(self, provider: ProviderRegistration) -> None:
        self._providers[provider.provider_id] = provider

    def register_account(self, account: AccountRegistration) -> None:
        self._accounts[account.account_id] = account

    def register_environment(self, env: ExecutionEnvironment) -> None:
        self._environments[env.environment_id] = env

    def get_capability(self, name: str) -> Optional[CapabilityRegistration]:
        return self._capabilities.get(name)

    def list_capabilities(self) -> List[CapabilityRegistration]:
        return list(self._capabilities.values())

    def find_agents_for_capabilities(self, capabilities: List[str]) -> List[AgentRegistration]:
        matching = []
        for agent in self._agents.values():
            if any(cap in agent.capabilities for cap in capabilities):
                matching.append(agent)
        return matching

    def list_agents(self) -> List[AgentRegistration]:
        return list(self._agents.values())

    def list_providers(self) -> List[ProviderRegistration]:
        return list(self._providers.values())

    def list_accounts_for_provider(self, provider_id: str) -> List[AccountRegistration]:
        return [acc for acc in self._accounts.values() if acc.provider_id == provider_id]

    def get_environment(self, env_id: str) -> Optional[ExecutionEnvironment]:
        return self._environments.get(env_id)

    def list_environments(self) -> List[ExecutionEnvironment]:
        return list(self._environments.values())

    def populate_default_catalog(self) -> None:
        """Populates dynamic default entries for Intent OS runtime."""
        # Capabilities
        default_caps = [
            ("retrieval.financial_context", "Resgate de histórico financeiro", ["finance", "retrieval"]),
            ("modeling.allocation_scenarios", "Modelagem de cenários de alocação", ["finance", "modeling"]),
            ("analysis.risk_evaluation", "Avaliação de riscos de mercado e liquidez", ["finance", "risk"]),
            ("synthesis.recommendation", "Sintetização de recomendações", ["synthesis", "advisory"]),
            ("validation.goal_alignment", "Validação de conformidade de metas", ["validation", "goal"]),
            ("code.architecture_design", "Design de arquitetura de software", ["coding", "architecture"]),
            ("code.scaffold_generation", "Geração de código base e estrutura", ["coding", "generation"]),
            ("code.ui_design", "Construção e layout de interfaces", ["coding", "ui"]),
            ("code.backend_logic", "Implementação de lógica backend e APIs", ["coding", "backend"]),
            ("code.testing", "Verificação e testes unitários", ["coding", "testing"]),
            ("code.documentation", "Geração de documentação técnica", ["coding", "docs"]),
            ("external.communication", "Comunicação e envio de mensagens externas", ["communication", "external"]),
            ("research.information_gathering", "Coleta e pesquisa de informações", ["research", "gathering"]),
            ("research.comparative_analysis", "Análise comparativa de dados", ["research", "comparison"]),
        ]
        for name, desc, tags in default_caps:
            self.register_capability(CapabilityRegistration(name=name, description=desc, tags=tags))

        # Agents
        self.register_agent(AgentRegistration(
            agent_id="agent_financial_atlas",
            name="Atlas Financial Engine",
            capabilities=["retrieval.financial_context", "modeling.allocation_scenarios", "analysis.risk_evaluation", "synthesis.recommendation"],
            specialization=["finance", "risk", "modeling"],
            historical_confidence=0.96,
            cost_tier=0.015,
            latency_tier=0.25,
            supported_domains=["finance"]
        ))
        self.register_agent(AgentRegistration(
            agent_id="agent_logos_synthesizer",
            name="Logos Synthesis Agent",
            capabilities=["synthesis.recommendation", "validation.goal_alignment", "external.communication", "research.comparative_analysis"],
            specialization=["synthesis", "validation", "communication"],
            historical_confidence=0.92,
            cost_tier=0.010,
            latency_tier=0.15,
            supported_domains=["finance", "communication", "general"]
        ))
        self.register_agent(AgentRegistration(
            agent_id="agent_code_architect",
            name="Code Architect & Builder Agent",
            capabilities=["code.architecture_design", "code.scaffold_generation", "code.ui_design", "code.backend_logic", "code.testing", "code.documentation"],
            specialization=["coding", "architecture", "scaffold"],
            historical_confidence=0.94,
            cost_tier=0.020,
            latency_tier=0.30,
            supported_domains=["coding"]
        ))
        self.register_agent(AgentRegistration(
            agent_id="agent_researcher_scout",
            name="Deep Research Scout",
            capabilities=["research.information_gathering", "research.comparative_analysis", "retrieval.financial_context"],
            specialization=["research", "comparative"],
            historical_confidence=0.91,
            cost_tier=0.008,
            latency_tier=0.20,
            supported_domains=["research", "general"]
        ))
        self.register_agent(AgentRegistration(
            agent_id="agent_core_orchestrator",
            name="Core General Agent",
            capabilities=["retrieval.financial_context", "synthesis.recommendation", "validation.goal_alignment", "research.information_gathering", "external.communication"],
            specialization=["general", "coordination"],
            historical_confidence=0.88,
            cost_tier=0.005,
            latency_tier=0.10,
            supported_domains=["general", "finance", "coding", "communication"]
        ))

        # Providers
        self.register_provider(ProviderRegistration(
            provider_id="provider_gemini_ultra",
            name="Gemini 1.5 Pro / Ultra Profile",
            reasoning_score=0.95,
            tool_use_support=True,
            context_window=1000000,
            cost_per_1k_tokens=0.002,
            privacy_tier="high",
            multimodal=True,
            availability=1.0
        ))
        self.register_provider(ProviderRegistration(
            provider_id="provider_anthropic_claude",
            name="Claude 3.5 Sonnet Profile",
            reasoning_score=0.96,
            tool_use_support=True,
            context_window=200000,
            cost_per_1k_tokens=0.003,
            privacy_tier="high",
            multimodal=True,
            availability=1.0
        ))
        self.register_provider(ProviderRegistration(
            provider_id="provider_openai_gpt4",
            name="GPT-4o Profile",
            reasoning_score=0.94,
            tool_use_support=True,
            context_window=128000,
            cost_per_1k_tokens=0.0025,
            privacy_tier="standard",
            multimodal=True,
            availability=1.0
        ))
        self.register_provider(ProviderRegistration(
            provider_id="provider_local_llama",
            name="Local Llama 3 Edge Profile",
            reasoning_score=0.75,
            tool_use_support=True,
            context_window=32000,
            cost_per_1k_tokens=0.0001,
            privacy_tier="high",
            multimodal=False,
            availability=1.0
        ))

        # Accounts
        self.register_account(AccountRegistration(
            account_id="acc_primary_gcp_01",
            provider_id="provider_gemini_ultra",
            name="Primary GCP Studio Enterprise Account",
            quota_remaining=500000.0,
            rate_limit_rpm=2000,
            priority=10,
            cost_multiplier=1.0,
            allowed_policies=["standard", "high_privacy", "enterprise"]
        ))
        self.register_account(AccountRegistration(
            account_id="acc_anthropic_prod_01",
            provider_id="provider_anthropic_claude",
            name="Production Anthropic Direct Account",
            quota_remaining=300000.0,
            rate_limit_rpm=1000,
            priority=9,
            cost_multiplier=1.0,
            allowed_policies=["standard", "high_privacy"]
        ))
        self.register_account(AccountRegistration(
            account_id="acc_openai_backup_01",
            provider_id="provider_openai_gpt4",
            name="OpenAI Reserve Enterprise Account",
            quota_remaining=200000.0,
            rate_limit_rpm=800,
            priority=7,
            cost_multiplier=1.1,
            allowed_policies=["standard"]
        ))
        self.register_account(AccountRegistration(
            account_id="acc_local_edge_01",
            provider_id="provider_local_llama",
            name="Local On-Prem Edge Account",
            quota_remaining=9999999.0,
            rate_limit_rpm=10000,
            priority=5,
            cost_multiplier=0.01,
            allowed_policies=["standard", "high_privacy", "offline_only"]
        ))

        # Execution Environments
        self.register_environment(ExecutionEnvironment(
            environment_id="env_local_process",
            type=ExecutionEnvironmentType.LOCAL_PROCESS,
            status="active",
            capabilities=["code_execution", "local_storage", "in_memory"],
            available_tools=["python_interpreter", "file_system"],
            network_access=True,
            privacy_level="high",
            latency_class="ultra_low",
            cost_class="free",
            resource_limits={"memory_mb": 4096, "cpu_cores": 4}
        ))
        self.register_environment(ExecutionEnvironment(
            environment_id="env_desktop_host",
            type=ExecutionEnvironmentType.DESKTOP,
            status="active",
            capabilities=["ui_rendering", "local_storage", "ipc_bridge"],
            available_tools=["desktop_native", "file_system"],
            network_access=True,
            privacy_level="high",
            latency_class="low",
            cost_class="free",
            resource_limits={"memory_mb": 8192, "cpu_cores": 8}
        ))
        self.register_environment(ExecutionEnvironment(
            environment_id="env_cloud_server",
            type=ExecutionEnvironmentType.CLOUD,
            status="active",
            capabilities=["scalable_compute", "cloud_storage", "remote_api"],
            available_tools=["cloud_runner", "external_http"],
            network_access=True,
            privacy_level="standard",
            latency_class="medium",
            cost_class="medium",
            resource_limits={"memory_mb": 16384, "cpu_cores": 16}
        ))
        self.register_environment(ExecutionEnvironment(
            environment_id="env_remote_edge",
            type=ExecutionEnvironmentType.EDGE,
            status="active",
            capabilities=["airgapped_compute", "edge_inference"],
            available_tools=["edge_runner"],
            network_access=False,
            privacy_level="airgapped",
            latency_class="low",
            cost_class="low",
            resource_limits={"memory_mb": 2048, "cpu_cores": 2}
        ))


# --- Assignment & Execution Graph Data Contracts ---

@dataclass
class NodeAssignment:
    """Assignment detail binding a PlanStep to specific Agent, Provider, Account, and ExecutionEnvironment."""
    step_id: str
    capability: str
    agent_id: str
    agent_name: str
    agent_score: float
    provider_id: str
    provider_name: str
    provider_score: float
    account_id: str
    account_name: str
    account_score: float
    match_score: float
    reasoning: str
    environment_id: str = "env_local_process"
    environment_type: str = "local_process"
    environment_score: float = 1.0
    agent_candidates: List[Dict[str, Any]] = field(default_factory=list)
    provider_candidates: List[Dict[str, Any]] = field(default_factory=list)
    account_candidates: List[Dict[str, Any]] = field(default_factory=list)
    environment_candidates: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "assigned"  # "assigned", "fallback_assigned", "unassigned"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionNode:
    """Graph node representing a PlanStep augmented with assignment metadata."""
    step_id: str
    objective: str
    action_type: str
    inputs: Dict[str, Any]
    expected_output: str
    dependencies: List[str]
    required_capabilities: List[str]
    risk_level: str
    reversibility: str
    requires_confirmation: bool
    assignment: Optional[NodeAssignment] = None
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        if self.assignment and hasattr(self.assignment, "to_dict"):
            res["assignment"] = self.assignment.to_dict()
        return res


@dataclass
class ExecutionGraph:
    """Distributed Execution Graph generated by Capability Orchestrator (COR)."""
    graph_id: str
    plan_id: str
    status: str = "ready"  # "ready", "partially_assigned", "unassignable", "blocked"
    nodes: Dict[str, Any] = field(default_factory=dict)
    edges: List[Dict[str, str]] = field(default_factory=list)  # [{"from": "step_1", "to": "step_2"}]
    assignments: Dict[str, Any] = field(default_factory=dict)  # step_id -> NodeAssignment dict
    execution_groups: List[List[str]] = field(default_factory=list)  # Parallel stages
    dependencies: List[Dict[str, str]] = field(default_factory=list)
    provider_requirements: Dict[str, Any] = field(default_factory=dict)
    agent_requirements: Dict[str, Any] = field(default_factory=dict)
    account_selection: Dict[str, Any] = field(default_factory=dict)
    estimated_parallelism: float = 1.0
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    execution_policy: Dict[str, Any] = field(default_factory=dict)
    validation: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["nodes"] = {
            k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in self.nodes.items()
        }
        res["assignments"] = {
            k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in self.assignments.items()
        }
        return res


class CapabilityOrchestrator:
    """Capability Orchestrator (COR) — RFC-0010.

    Responsible for mapping execution steps to capability-matched agents, provider profiles,
    and account routing, without executing side effects or LLM calls.
    """

    def orchestrate(
        self,
        plan: ExecutionPlan,
        registry: Optional[RegistryCatalog] = None,
        system_state: Optional[Dict[str, Any]] = None,
        policies: Optional[List[str]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> ExecutionGraph:
        """Generates a distributed ExecutionGraph from an ExecutionPlan."""
        catalog = registry or RegistryCatalog(populate_defaults=True)
        graph_id = f"graph_{uuid4().hex[:8]}"
        system_state = system_state or {"load": "normal", "health": 1.0}
        active_policies = list(set((policies or []) + plan.constraints))
        user_constraints = constraints or {}

        # 1. Handle blocked / unready plans
        if plan.status == "blocked" or not plan.steps:
            return ExecutionGraph(
                graph_id=graph_id,
                plan_id=plan.plan_id,
                status="blocked",
                nodes={},
                edges=[],
                assignments={},
                execution_groups=[],
                dependencies=[],
                provider_requirements=plan.provider_requirements,
                agent_requirements={},
                account_selection={},
                estimated_parallelism=1.0,
                estimated_cost=0.0,
                estimated_latency=0.0,
                execution_policy={"policies": active_policies},
                validation=["Plano bloqueado na etapa anterior (CPE/CDM). Nenhuma atribuição gerada."],
            )

        nodes: Dict[str, ExecutionNode] = {}
        assignments: Dict[str, NodeAssignment] = {}
        edges: List[Dict[str, str]] = []
        validation: List[str] = [
            "Atribuição de capacidades e agentes efetuada com sucesso.",
            "Grafo de dependência validado como DAG acíclico.",
            "Roteamento de contas configurado de forma isolada.",
        ]

        total_cost = 0.0
        total_latency = 0.0

        # 2. Process each step in plan
        for step in plan.steps:
            # Edges
            for dep in step.dependencies:
                edges.append({"from": dep, "to": step.step_id})

            # Capability matching & agent ranking
            step_caps = step.required_capabilities or ["synthesis.recommendation"]
            primary_cap = step_caps[0]

            agent_candidates = self._rank_agents(
                step=step,
                capabilities=step_caps,
                catalog=catalog,
                policies=active_policies,
                constraints=user_constraints,
            )

            # Provider ranking
            provider_candidates = self._rank_providers(
                step=step,
                plan_provider_reqs=plan.provider_requirements,
                catalog=catalog,
                policies=active_policies,
                constraints=user_constraints,
            )

            # Execution Environment ranking
            environment_candidates = self._rank_environments(
                step=step,
                catalog=catalog,
                policies=active_policies,
                constraints=user_constraints,
            )

            # Select top Agent, Provider, and Environment
            selected_agent = agent_candidates[0] if agent_candidates else None
            selected_provider = provider_candidates[0] if provider_candidates else None
            selected_env = environment_candidates[0] if environment_candidates else None

            # Account selection
            account_candidates = []
            selected_account = None
            if selected_provider:
                account_candidates = self._select_accounts(
                    provider_id=selected_provider["provider_id"],
                    catalog=catalog,
                    policies=active_policies,
                )
                if account_candidates:
                    selected_account = account_candidates[0]

            # Construct NodeAssignment
            if selected_agent and selected_provider and selected_account and selected_env:
                combined_score = round(
                    (selected_agent["score"] * 0.40)
                    + (selected_provider["score"] * 0.30)
                    + (selected_account["score"] * 0.15)
                    + (selected_env["score"] * 0.15),
                    2,
                )
                reasoning = (
                    f"Atribuído Agente '{selected_agent['name']}' (score: {selected_agent['score']}) "
                    f"via Provider '{selected_provider['name']}' (score: {selected_provider['score']}) "
                    f"na Conta '{selected_account['name']}' (score: {selected_account['score']}) "
                    f"no Ambiente '{selected_env['environment_id']}' ({selected_env['environment_type']}) (score: {selected_env['score']}) "
                    f"para suprir capacidade '{primary_cap}'."
                )

                assignment = NodeAssignment(
                    step_id=step.step_id,
                    capability=primary_cap,
                    agent_id=selected_agent["agent_id"],
                    agent_name=selected_agent["name"],
                    agent_score=selected_agent["score"],
                    provider_id=selected_provider["provider_id"],
                    provider_name=selected_provider["name"],
                    provider_score=selected_provider["score"],
                    account_id=selected_account["account_id"],
                    account_name=selected_account["name"],
                    account_score=selected_account["score"],
                    match_score=combined_score,
                    reasoning=reasoning,
                    environment_id=selected_env["environment_id"],
                    environment_type=selected_env["environment_type"],
                    environment_score=selected_env["score"],
                    agent_candidates=agent_candidates,
                    provider_candidates=provider_candidates,
                    account_candidates=account_candidates,
                    environment_candidates=environment_candidates,
                    status="assigned",
                )
                assignments[step.step_id] = assignment

                # Add cost / latency estimates
                total_cost += selected_provider["cost"] * selected_account["cost_multiplier"]
                total_latency += selected_agent["latency"]
            else:
                # Unassigned node / missing capability or environment constraint violation
                if not selected_env:
                    reasoning = "no_execution_environment_available"
                    status_code = "blocked"
                else:
                    reasoning = f"Capacidade '{primary_cap}' sem fornecedor/agente/conta totalmente elegível."
                    status_code = "unassigned"

                validation.append(f"ALERTA: Não foi possível atribuir agente/provider/conta/ambiente completo para a etapa {step.step_id}: {reasoning}")
                assignment = NodeAssignment(
                    step_id=step.step_id,
                    capability=primary_cap,
                    agent_id=selected_agent["agent_id"] if selected_agent else "unassigned",
                    agent_name=selected_agent["name"] if selected_agent else "Nenhum Agente Compatível",
                    agent_score=selected_agent["score"] if selected_agent else 0.0,
                    provider_id=selected_provider["provider_id"] if selected_provider else "unassigned",
                    provider_name=selected_provider["name"] if selected_provider else "Nenhum Provider",
                    provider_score=selected_provider["score"] if selected_provider else 0.0,
                    account_id="unassigned",
                    account_name="Nenhuma Conta",
                    account_score=0.0,
                    match_score=0.0,
                    reasoning=reasoning,
                    environment_id=selected_env["environment_id"] if selected_env else "unassigned",
                    environment_type=selected_env["environment_type"] if selected_env else "none",
                    environment_score=selected_env["score"] if selected_env else 0.0,
                    agent_candidates=agent_candidates,
                    provider_candidates=provider_candidates,
                    account_candidates=account_candidates,
                    environment_candidates=environment_candidates,
                    status=status_code,
                )
                assignments[step.step_id] = assignment

            nodes[step.step_id] = ExecutionNode(
                step_id=step.step_id,
                objective=step.objective,
                action_type=step.action_type,
                inputs=step.inputs,
                expected_output=step.expected_output,
                dependencies=step.dependencies,
                required_capabilities=step.required_capabilities,
                risk_level=step.risk_level,
                reversibility=step.reversibility,
                requires_confirmation=step.requires_confirmation,
                assignment=assignment,
                status="pending",
            )

        # 3. Compute parallel execution groups (Topological DAG staging)
        execution_groups = self.compute_execution_groups(plan.steps)
        estimated_parallelism = max([len(group) for group in execution_groups], default=1.0)

        # Overall Graph Status
        has_blocked = any(a.status == "blocked" for a in assignments.values())
        has_unassigned = any(a.status in ["unassigned", "blocked"] for a in assignments.values())
        if has_blocked:
            graph_status = "blocked"
        elif has_unassigned:
            graph_status = "partially_assigned"
        else:
            graph_status = "ready"

        return ExecutionGraph(
            graph_id=graph_id,
            plan_id=plan.plan_id,
            status=graph_status,
            nodes=nodes,
            edges=edges,
            assignments=assignments,
            execution_groups=execution_groups,
            dependencies=edges,
            provider_requirements=plan.provider_requirements,
            agent_requirements={"policy_filter_applied": len(active_policies) > 0},
            account_selection={"routed_accounts_count": len(set(a.account_id for a in assignments.values() if a.account_id != "unassigned"))},
            estimated_parallelism=float(estimated_parallelism),
            estimated_cost=round(total_cost, 4),
            estimated_latency=round(total_latency / max(1, len(execution_groups)), 2),
            execution_policy={"active_policies": active_policies, "system_load": system_state.get("load")},
            validation=validation,
        )

    def compute_execution_groups(self, steps: List[PlanStep]) -> List[List[str]]:
        """Groups steps into parallel execution levels using topological ordering."""
        step_dict = {s.step_id: s for s in steps}
        in_degree = {s.step_id: len(s.dependencies) for s in steps}

        # Dependencies graph
        dependents: Dict[str, List[str]] = {s.step_id: [] for s in steps}
        for s in steps:
            for dep in s.dependencies:
                if dep in dependents:
                    dependents[dep].append(s.step_id)

        groups: List[List[str]] = []
        current_level = [sid for sid, deg in in_degree.items() if deg == 0]

        visited_count = 0
        while current_level:
            groups.append(sorted(current_level))
            visited_count += len(current_level)
            next_level = []

            for sid in current_level:
                for child in dependents.get(sid, []):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_level.append(child)

            current_level = next_level

        # Fallback if remaining steps due to disconnected or cyclic definitions
        if visited_count < len(steps):
            unvisited = [s.step_id for s in steps if s.step_id not in [item for sub in groups for item in sub]]
            if unvisited:
                groups.append(sorted(unvisited))

        return groups

    def _rank_agents(
        self,
        step: PlanStep,
        capabilities: List[str],
        catalog: RegistryCatalog,
        policies: List[str],
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Ranks candidate agents based on capability coverage, specialization, confidence, cost, and policies."""
        all_agents = catalog.list_agents()
        ranked = []

        max_cost = constraints.get("max_cost_tier", 1.0)
        prefer_offline = "offline_only" in policies or constraints.get("offline_only", False)

        for agent in all_agents:
            if agent.status == "offline" or agent.availability <= 0.0:
                continue

            # 1. Capability Coverage Score (0.0 to 1.0)
            covered = sum(1 for cap in capabilities if cap in agent.capabilities)
            coverage_score = covered / max(1, len(capabilities))

            if coverage_score == 0.0 and not any(spec in step.action_type for spec in agent.specialization):
                continue  # Incompatible agent

            # 2. Specialization Score
            domain_bonus = 0.20 if any(spec in step.action_type or spec in step.required_capabilities for spec in agent.specialization) else 0.0

            # 3. Confidence & Availability
            confidence_score = agent.historical_confidence * agent.availability

            # 4. Cost Efficiency Score
            cost_score = max(0.0, 1.0 - (agent.cost_tier / max(0.001, max_cost)))

            # Policy Penalties / Multipliers
            policy_multiplier = 1.0
            if prefer_offline and "local" not in agent.agent_id:
                policy_multiplier *= 0.5

            total_score = round(
                ((coverage_score * 0.40) + (confidence_score * 0.30) + (domain_bonus * 0.20) + (cost_score * 0.10)) * policy_multiplier,
                2,
            )

            ranked.append({
                "agent_id": agent.agent_id,
                "name": agent.name,
                "score": total_score,
                "coverage": coverage_score,
                "confidence": agent.historical_confidence,
                "latency": agent.latency_tier,
                "reasoning": f"Agente '{agent.name}' atende {covered}/{len(capabilities)} capacidades com confiança {agent.historical_confidence}.",
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def _rank_providers(
        self,
        step: PlanStep,
        plan_provider_reqs: Dict[str, Any],
        catalog: RegistryCatalog,
        policies: List[str],
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Ranks candidate AI providers based on reasoning, context window, cost, privacy, and availability."""
        providers = catalog.list_providers()
        ranked = []

        req_reasoning = plan_provider_reqs.get("reasoning", "medium")
        req_privacy = plan_provider_reqs.get("privacy", "standard")
        if "high_privacy" in policies:
            req_privacy = "high"

        target_reasoning = 0.95 if req_reasoning == "high" else 0.85 if req_reasoning == "medium" else 0.70

        for prov in providers:
            if prov.status == "offline" or prov.availability <= 0.0:
                continue

            # Reasoning match
            reasoning_match = max(0.0, 1.0 - abs(prov.reasoning_score - target_reasoning))

            # Privacy match
            privacy_score = 1.0 if prov.privacy_tier == req_privacy or prov.privacy_tier == "high" else 0.5

            # Context window match
            context_score = 1.0 if prov.context_window >= 100000 else 0.7

            # Cost score
            cost_score = max(0.0, 1.0 - (prov.cost_per_1k_tokens * 100))

            total_score = round(
                (reasoning_match * 0.35) + (privacy_score * 0.25) + (context_score * 0.20) + (prov.availability * 0.10) + (cost_score * 0.10),
                2,
            )

            ranked.append({
                "provider_id": prov.provider_id,
                "name": prov.name,
                "score": total_score,
                "cost": prov.cost_per_1k_tokens,
                "reasoning_score": prov.reasoning_score,
                "privacy_tier": prov.privacy_tier,
                "reasoning": f"Provider '{prov.name}' possui score de raciocínio {prov.reasoning_score} e privacidade {prov.privacy_tier}.",
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def _select_accounts(
        self,
        provider_id: str,
        catalog: RegistryCatalog,
        policies: List[str],
    ) -> List[Dict[str, Any]]:
        """Selects and ranks service accounts for a provider independently of vendor credentials."""
        accounts = catalog.list_accounts_for_provider(provider_id)
        ranked = []

        for acc in accounts:
            if acc.status == "exhausted" or acc.quota_remaining <= 0:
                continue

            # Quota score
            quota_score = min(1.0, acc.quota_remaining / 100000.0)

            # Priority score
            priority_score = acc.priority / 10.0

            # Rate limit
            rate_score = min(1.0, acc.rate_limit_rpm / 1000.0)

            total_score = round((quota_score * 0.40) + (priority_score * 0.40) + (rate_score * 0.20), 2)

            ranked.append({
                "account_id": acc.account_id,
                "name": acc.name,
                "score": total_score,
                "quota_remaining": acc.quota_remaining,
                "cost_multiplier": acc.cost_multiplier,
                "reasoning": f"Conta '{acc.name}' com quota disponível ({acc.quota_remaining}) e prioridade {acc.priority}.",
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def _rank_environments(
        self,
        step: PlanStep,
        catalog: RegistryCatalog,
        policies: List[str],
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Ranks candidate execution environments based on step requirements, security, and policies."""
        environments = catalog.list_environments()
        ranked = []

        offline_required = "offline_only" in policies or constraints.get("offline_required", False) or constraints.get("offline_only", False)
        internet_allowed = constraints.get("internet_allowed", True)
        cloud_allowed = constraints.get("cloud_execution_allowed", True)
        local_allowed = constraints.get("local_execution_allowed", True)
        remote_allowed = constraints.get("remote_execution_allowed", True)
        forbidden_envs = constraints.get("forbidden_execution_environments", [])
        preferred_env = constraints.get("preferred_execution_environment")

        for env in environments:
            if env.status != "active":
                continue

            env_type_str = env.type.value if hasattr(env.type, "value") else str(env.type)

            # Check forbidden environments
            if env.environment_id in forbidden_envs or env_type_str in forbidden_envs:
                continue

            # Check execution permissions
            if not cloud_allowed and env_type_str in ["cloud", "server"]:
                continue
            if not local_allowed and env_type_str in ["local_process", "desktop"]:
                continue
            if not remote_allowed and env_type_str in ["remote", "edge"]:
                continue

            # Check offline / network requirement
            if (offline_required or not internet_allowed) and env.network_access and env_type_str not in ["local_process", "desktop", "edge"]:
                continue

            # Base score calculation
            cap_match = 1.0 if not step.required_capabilities else (
                sum(1 for cap in step.required_capabilities if cap in env.capabilities or cap.split(".")[0] in env.capabilities) / max(1, len(step.required_capabilities))
            )

            latency_score = 1.0 if env.latency_class == "ultra_low" else 0.8 if env.latency_class == "low" else 0.6 if env.latency_class == "medium" else 0.4
            cost_score = 1.0 if env.cost_class == "free" else 0.8 if env.cost_class == "low" else 0.5
            privacy_score = 1.0 if env.privacy_level in ["high", "airgapped"] else 0.7

            bonus = 0.3 if preferred_env and (env.environment_id == preferred_env or env_type_str == preferred_env) else 0.0

            total_score = round((cap_match * 0.40) + (latency_score * 0.25) + (privacy_score * 0.20) + (cost_score * 0.15) + bonus, 2)

            ranked.append({
                "environment_id": env.environment_id,
                "environment_type": env_type_str,
                "score": total_score,
                "network_access": env.network_access,
                "privacy_level": env.privacy_level,
                "reasoning": f"Ambiente '{env.environment_id}' ({env_type_str}) com score {total_score}.",
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def reassign_fallback(
        self,
        graph: ExecutionGraph,
        failed_step_id: str,
        failure_reason: str,
        registry: Optional[RegistryCatalog] = None,
    ) -> ExecutionGraph:
        """Reassigns fallback candidates for a failed node without rebuilding the entire ExecutionPlan."""
        catalog = registry or RegistryCatalog(populate_defaults=True)

        if failed_step_id not in graph.nodes or failed_step_id not in graph.assignments:
            return graph

        current_node = graph.nodes[failed_step_id]
        current_assignment = graph.assignments[failed_step_id]

        # Filter out failed candidate agent / provider
        failed_agent_id = current_assignment.agent_id
        failed_provider_id = current_assignment.provider_id

        remaining_agents = [a for a in current_assignment.agent_candidates if a["agent_id"] != failed_agent_id]
        remaining_providers = [p for p in current_assignment.provider_candidates if p["provider_id"] != failed_provider_id]

        new_agent = remaining_agents[0] if remaining_agents else current_assignment.agent_candidates[0]
        new_provider = remaining_providers[0] if remaining_providers else current_assignment.provider_candidates[0]

        accounts = self._select_accounts(new_provider["provider_id"], catalog, [])
        new_account = accounts[0] if accounts else {"account_id": "acc_fallback_01", "name": "Fallback Account", "score": 0.8, "cost_multiplier": 1.0}

        fallback_assignment = NodeAssignment(
            step_id=failed_step_id,
            capability=current_assignment.capability,
            agent_id=new_agent["agent_id"],
            agent_name=new_agent["name"],
            agent_score=new_agent["score"],
            provider_id=new_provider["provider_id"],
            provider_name=new_provider["name"],
            provider_score=new_provider["score"],
            account_id=new_account["account_id"],
            account_name=new_account["name"],
            account_score=new_account["score"],
            match_score=round((new_agent["score"] * 0.5) + (new_provider["score"] * 0.5), 2),
            reasoning=f"Fallback ativado após falha em {failed_agent_id} ({failure_reason}). Re-atribuído para Agente '{new_agent['name']}' via Provider '{new_provider['name']}'.",
            agent_candidates=remaining_agents,
            provider_candidates=remaining_providers,
            account_candidates=accounts,
            status="fallback_assigned",
        )

        # Update Graph state
        updated_assignments = dict(graph.assignments)
        updated_assignments[failed_step_id] = fallback_assignment

        updated_nodes = dict(graph.nodes)
        updated_node = current_node
        updated_node.assignment = fallback_assignment
        updated_node.status = "reassigned"
        updated_nodes[failed_step_id] = updated_node

        updated_validation = list(graph.validation) + [
            f"Fallback efetuado com sucesso na etapa {failed_step_id}: Re-atribuído para {new_agent['name']} ({new_provider['name']})."
        ]

        return ExecutionGraph(
            graph_id=graph.graph_id,
            plan_id=graph.plan_id,
            status="ready",
            nodes=updated_nodes,
            edges=graph.edges,
            assignments=updated_assignments,
            execution_groups=graph.execution_groups,
            dependencies=graph.dependencies,
            provider_requirements=graph.provider_requirements,
            agent_requirements=graph.agent_requirements,
            account_selection=graph.account_selection,
            estimated_parallelism=graph.estimated_parallelism,
            estimated_cost=graph.estimated_cost,
            estimated_latency=graph.estimated_latency,
            execution_policy=graph.execution_policy,
            validation=updated_validation,
            created_at=utc_iso(),
        )
