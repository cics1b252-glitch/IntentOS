"""Registry & Resource Manager (RRM) — Core Implementation (RFC-0013).

Provides thread-safe canonical storage, indexing, lookup, status tracking, and query capabilities
for Providers, Accounts, Execution Environments, Capabilities, Agents, and Projects.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from intent_kernel.rrm.models import (
    AccountResource,
    AgentInstallationState,
    AgentResource,
    AvailabilitySource,
    CapabilityResource,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentType,
    ProjectResource,
    ProviderResource,
    ResourceHealthReport,
    ResourceOrigin,
    ResourceQueryFilter,
    ResourceStatus,
    ResourceType,
    RRMRegistryMetrics,
)
from intent_kernel.rrm.ports import ProjectRegistryPort, ResourceQueryPort, RRMRegistryPort
from intent_kernel.time_utils import utc_iso


class RegistryResourceManager(RRMRegistryPort, ResourceQueryPort, ProjectRegistryPort):
    """Canonical Registry & Resource Manager (RRM) service implementation."""

    def __init__(self, populate_defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._providers: Dict[str, ProviderResource] = {}
        self._accounts: Dict[str, AccountResource] = {}
        self._environments: Dict[str, ExecutionEnvironmentResource] = {}
        self._capabilities: Dict[str, CapabilityResource] = {}  # keyed by name or capability_id
        self._agents: Dict[str, AgentResource] = {}
        self._projects: Dict[str, ProjectResource] = {}
        self._governed_ids: Set[str] = set()
        self._tombstones: Set[str] = set()  # H1.3: retired resource IDs

        if populate_defaults:
            self.populate_default_catalog()

    # --- Provider Operations ---

    def register_provider(self, provider: ProviderResource) -> ProviderResource:
        with self._lock:
            if self._is_tombstoned(provider.provider_id):
                return self._providers.get(provider.provider_id)  # H1.3: reject retired identity
            existing = self._providers.get(provider.provider_id)
            if existing is not None and self._is_governed_resource(provider.provider_id):
                return existing
            self._establish_generation_on_registration(provider, existing)
            provider.updated_at = utc_iso()
            self._providers[provider.provider_id] = provider
            return provider

    def get_provider(self, provider_id: str) -> Optional[ProviderResource]:
        with self._lock:
            return self._providers.get(provider_id)

    def list_providers(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProviderResource]:
        with self._lock:
            providers = list(self._providers.values())
            if only_eligible:
                providers = [p for p in providers if p.is_eligible]
            if status is not None:
                providers = [p for p in providers if p.status == status]
            return providers

    def unregister_provider(self, provider_id: str) -> bool:
        with self._lock:
            if self._is_governed_resource(provider_id):
                return False
            if provider_id in self._providers:
                del self._providers[provider_id]
                return True
            return False

    # --- Account Operations ---

    def register_account(self, account: AccountResource) -> AccountResource:
        with self._lock:
            if self._is_tombstoned(account.account_id):
                return self._accounts.get(account.account_id)  # H1.3: reject retired identity
            existing = self._accounts.get(account.account_id)
            if existing is not None and self._is_governed_resource(account.account_id):
                return existing
            self._establish_generation_on_registration(account, existing)
            account.updated_at = utc_iso()
            self._accounts[account.account_id] = account
            return account

    def get_account(self, account_id: str) -> Optional[AccountResource]:
        with self._lock:
            return self._accounts.get(account_id)

    def list_accounts(
        self,
        provider_id: Optional[str] = None,
        status: Optional[ResourceStatus] = None,
        only_eligible: bool = False,
    ) -> List[AccountResource]:
        with self._lock:
            accounts = list(self._accounts.values())
            if only_eligible:
                accounts = [a for a in accounts if a.is_eligible]
            if provider_id is not None:
                accounts = [a for a in accounts if a.provider_id == provider_id]
            if status is not None:
                accounts = [a for a in accounts if a.status == status]
            return accounts

    def unregister_account(self, account_id: str) -> bool:
        with self._lock:
            if self._is_governed_resource(account_id):
                return False
            if account_id in self._accounts:
                del self._accounts[account_id]
                return True
            return False

    # --- Execution Environment Operations ---

    def register_environment(self, environment: ExecutionEnvironmentResource) -> ExecutionEnvironmentResource:
        with self._lock:
            if self._is_tombstoned(environment.environment_id):
                return self._environments.get(environment.environment_id)  # H1.3: reject retired identity
            existing = self._environments.get(environment.environment_id)
            if existing is not None and self._is_governed_resource(environment.environment_id):
                return existing
            self._establish_generation_on_registration(environment, existing)
            environment.updated_at = utc_iso()
            self._environments[environment.environment_id] = environment
            return environment

    def get_environment(self, environment_id: str) -> Optional[ExecutionEnvironmentResource]:
        with self._lock:
            return self._environments.get(environment_id)

    def list_environments(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ExecutionEnvironmentResource]:
        with self._lock:
            envs = list(self._environments.values())
            if only_eligible:
                envs = [e for e in envs if e.is_eligible]
            if status is not None:
                envs = [e for e in envs if e.status == status]
            return envs

    def unregister_environment(self, environment_id: str) -> bool:
        with self._lock:
            if self._is_governed_resource(environment_id):
                return False
            if environment_id in self._environments:
                del self._environments[environment_id]
                return True
            return False

    # --- Capability Operations ---

    def register_capability(self, capability: CapabilityResource) -> CapabilityResource:
        with self._lock:
            if self._is_tombstoned(capability.capability_id):
                return self._capabilities.get(capability.capability_id)  # H1.3: reject retired identity
            existing = self._capabilities.get(capability.capability_id)
            if existing is not None and self._is_governed_resource(capability.capability_id):
                return existing
            self._establish_generation_on_registration(capability, existing)
            capability.updated_at = utc_iso()
            self._capabilities[capability.capability_id] = capability
            if capability.name and capability.name != capability.capability_id:
                self._capabilities[capability.name] = capability
            return capability

    def get_capability(self, capability_name_or_id: str) -> Optional[CapabilityResource]:
        with self._lock:
            return self._capabilities.get(capability_name_or_id)

    def list_capabilities(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[CapabilityResource]:
        with self._lock:
            unique = {id(c): c for c in self._capabilities.values()}
            caps = list(unique.values())
            if only_eligible:
                caps = [c for c in caps if c.is_eligible]
            if status is not None:
                caps = [c for c in caps if c.status == status]
            return caps

    def unregister_capability(self, capability_id: str) -> bool:
        with self._lock:
            if self._is_governed_resource(capability_id):
                return False
            cap = self._capabilities.get(capability_id)
            if cap:
                keys_to_del = [k for k, v in self._capabilities.items() if v is cap]
                for k in keys_to_del:
                    del self._capabilities[k]
                return True
            return False

    # --- Agent Operations ---

    def register_agent(self, agent: AgentResource) -> AgentResource:
        with self._lock:
            if self._is_tombstoned(agent.agent_id):
                return self._agents.get(agent.agent_id)  # H1.3: reject retired identity
            existing = self._agents.get(agent.agent_id)
            if existing is not None and self._is_governed_resource(agent.agent_id):
                return existing
            self._establish_generation_on_registration(agent, existing)
            agent.updated_at = utc_iso()
            self._agents[agent.agent_id] = agent
            return agent

    def get_agent(self, agent_id: str) -> Optional[AgentResource]:
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[AgentResource]:
        with self._lock:
            agents = list(self._agents.values())
            if only_eligible:
                agents = [a for a in agents if a.is_eligible]
            if status is not None:
                agents = [a for a in agents if a.status == status]
            return agents

    def unregister_agent(self, agent_id: str) -> bool:
        with self._lock:
            if self._is_governed_resource(agent_id):
                return False
            if agent_id in self._agents:
                del self._agents[agent_id]
                return True
            return False

    def find_agents_for_capabilities(self, capabilities: List[str], only_eligible: bool = True) -> List[AgentResource]:
        with self._lock:
            matching = []
            for agent in self._agents.values():
                if only_eligible and not agent.is_eligible:
                    continue
                if any(cap in agent.capabilities for cap in capabilities):
                    matching.append(agent)
            return matching

    # --- Project Operations ---

    def register_project(self, project: ProjectResource) -> ProjectResource:
        with self._lock:
            existing = self._projects.get(project.project_id)
            self._establish_generation_on_registration(project, existing)
            project.updated_at = utc_iso()
            self._projects[project.project_id] = project
            return project

    def get_project(self, project_id: str) -> Optional[ProjectResource]:
        with self._lock:
            return self._projects.get(project_id)

    def list_projects(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProjectResource]:
        with self._lock:
            projects = list(self._projects.values())
            if only_eligible:
                projects = [p for p in projects if p.is_eligible]
            if status is not None:
                projects = [p for p in projects if p.status == status]
            return projects

    def unregister_project(self, project_id: str) -> bool:
        with self._lock:
            if project_id in self._projects:
                del self._projects[project_id]
                return True
            return False

    # --- Governed Resource Provenance ---

    def _establish_generation_on_registration(self, incoming: Any, existing: Any) -> None:
        """Single canonical generation authority on registration.

        M30.2 — registration NEVER trusts caller-provided generation for a
        newly-introduced canonical resource:
          - new to RRM (existing is None): generation = GENERATION_INITIAL (1).
          - re-registration / repeated projection of an existing incarnation:
            preserve the stored generation so legitimate updates and repeated
            projections never reset or decrease lineage.
        """
        from intent_kernel.rrm.generation import (
            GENERATION_INITIAL,
            is_valid_generation,
        )

        if existing is None:
            incoming.generation = GENERATION_INITIAL
        elif is_valid_generation(getattr(existing, "generation", 0)):
            incoming.generation = existing.generation
        else:
            incoming.generation = GENERATION_INITIAL

    def _advance_generation(self, resource: Any) -> None:
        """Single canonical mutation authority: advance generation by exactly one.

        M30.2 — material mutation advances generation exactly once. A legacy
        resource's first material mutation establishes canonical generation 1.
        Called ONLY by RegistryResourceManager mutation methods, under the RRM
        lock, atomically with the state mutation it accompanies.
        """
        from intent_kernel.rrm.generation import (
            GENERATION_INITIAL,
            is_valid_generation,
        )

        gen = getattr(resource, "generation", 0)
        resource.generation = (
            (gen + 1) if is_valid_generation(gen) else GENERATION_INITIAL
        )

    def mark_governed(self, resource_id: str, registration_id: str = "") -> None:
        """Compatibility-only marker — does NOT create canonical governed identity.

        COMPATIBILITY_ONLY / TEST_ONLY — retained for backward compatibility
        and test infrastructure only.

        This method does NOT:
        - Populate the canonical governed identity store
        - Cause _is_governed_resource() to return True
        - Trigger protected overwrite guards
        - Influence activation trust, eligibility, binding, or execution

        Canonical governed identity is created exclusively by
        CanonicalPromotionRegistrationBoundary via governed_registration_id
        on the resource object.
        """
        pass

    def is_governed(self, resource_id: str) -> bool:
        """Check if a resource ID is governed.

        COMPATIBILITY_ONLY — checks canonical governed_registration_id
        on the resource object. Does NOT consult _governed_ids set.
        """
        existing = (
            self._providers.get(resource_id)
            or self._capabilities.get(resource_id)
            or self._agents.get(resource_id)
            or self._environments.get(resource_id)
            or self._accounts.get(resource_id)
            or self._projects.get(resource_id)
        )
        if existing is not None:
            return bool(getattr(existing, "governed_registration_id", ""))
        return False

    def _is_governed_resource(self, resource_id: str) -> bool:
        """Check if a resource has canonical governed provenance.

        A resource is considered governed ONLY if it has a non-empty
        governed_registration_id set by CanonicalPromotionRegistrationBoundary.

        NOT governed:
        - mark_governed() called (compatibility-only, no canonical identity)
        - resource_origin alone (caller-controlled)
        - caller-provided registration strings
        - _governed_ids set (compatibility-only, not consulted)

        Canonical governed identity is generated by M17 registration boundary
        and bound to resource_id + kind + proposal_id + decision_id.
        """
        existing = (
            self._providers.get(resource_id)
            or self._capabilities.get(resource_id)
            or self._agents.get(resource_id)
            or self._environments.get(resource_id)
            or self._accounts.get(resource_id)
            or self._projects.get(resource_id)
        )
        if existing is not None:
            return bool(getattr(existing, "governed_registration_id", ""))
        return False

    # --- H1.3 Retired Resource Tombstones ---

    def _record_tombstone(self, resource_id: str) -> None:
        """Record a retired resource ID to prevent re-registration."""
        with self._lock:
            self._tombstones.add(resource_id)

    def _is_tombstoned(self, resource_id: str) -> bool:
        """Check if a resource ID has been retired and tombstoned."""
        return resource_id in self._tombstones

    def _is_compatibility_source(self, resource_origin: ResourceOrigin) -> bool:
        """Check if a resource origin represents a compatibility/bootstrap source."""
        return resource_origin in (
            ResourceOrigin.MIGRATION,
            ResourceOrigin.CONFIGURATION,
            ResourceOrigin.HOST_DISCOVERY,
        )

    # --- Generic Query & Status Operations ---

    def query_resources(self, filter_criteria: ResourceQueryFilter) -> List[Any]:
        with self._lock:
            results: List[Any] = []

            # Providers
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.PROVIDER:
                for p in self._providers.values():
                    if filter_criteria.matches(ResourceType.PROVIDER, p):
                        results.append(p)

            # Accounts
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.ACCOUNT:
                for a in self._accounts.values():
                    if filter_criteria.matches(ResourceType.ACCOUNT, a):
                        results.append(a)

            # Execution Environments
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.EXECUTION_ENVIRONMENT:
                for e in self._environments.values():
                    if filter_criteria.matches(ResourceType.EXECUTION_ENVIRONMENT, e):
                        results.append(e)

            # Capabilities
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.CAPABILITY:
                unique_caps = {id(c): c for c in self._capabilities.values()}.values()
                for c in unique_caps:
                    if filter_criteria.matches(ResourceType.CAPABILITY, c):
                        results.append(c)

            # Agents
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.AGENT:
                for ag in self._agents.values():
                    if filter_criteria.matches(ResourceType.AGENT, ag):
                        results.append(ag)

            # Projects
            if not filter_criteria.resource_type or filter_criteria.resource_type == ResourceType.PROJECT:
                for pr in self._projects.values():
                    if filter_criteria.matches(ResourceType.PROJECT, pr):
                        results.append(pr)

            return results

    def update_resource_status(
        self,
        resource_type: ResourceType,
        resource_id: str,
        status: ResourceStatus,
    ) -> bool:
        """Update status of a non-governed resource.

        Governed resources cannot have their lifecycle mutated by
        generic status updates. Use the activation application boundary
        for governed resource lifecycle transitions.
        """
        with self._lock:
            if self._is_governed_resource(resource_id):
                return False

            now = utc_iso()
            if resource_type == ResourceType.PROVIDER:
                res = self._providers.get(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.ACCOUNT:
                res = self._accounts.get(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
                res = self._environments.get(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.CAPABILITY:
                res = self.get_capability(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.AGENT:
                res = self._agents.get(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            elif resource_type == ResourceType.PROJECT:
                res = self._projects.get(resource_id)
                if res:
                    before = res.status
                    res.status = status
                    if res.status != before:
                        self._advance_generation(res)
                        res.updated_at = now
                    return True

            return False

    # --- Health & Metrics ---

    def check_health(self) -> ResourceHealthReport:
        with self._lock:
            degraded: List[str] = []
            exhausted_accounts = 0

            active_providers = sum(1 for p in self._providers.values() if p.is_eligible)
            for p in self._providers.values():
                if not p.is_template and p.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"provider:{p.provider_id}")

            active_accounts = sum(1 for a in self._accounts.values() if a.is_eligible)
            for a in self._accounts.values():
                if not a.is_template and a.status in (ResourceStatus.EXHAUSTED, ResourceStatus.THROTTLED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"account:{a.account_id}")
                    if a.status == ResourceStatus.EXHAUSTED or a.quota_remaining <= 0:
                        exhausted_accounts += 1

            active_environments = sum(1 for e in self._environments.values() if e.is_eligible)
            for e in self._environments.values():
                if not e.is_template and e.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"environment:{e.environment_id}")

            unique_caps = list({id(c): c for c in self._capabilities.values()}.values())
            active_caps = sum(1 for c in unique_caps if c.is_eligible)

            active_agents = sum(1 for ag in self._agents.values() if ag.is_eligible)
            for ag in self._agents.values():
                if not ag.is_template and ag.status in (ResourceStatus.DEGRADED, ResourceStatus.UNAVAILABLE):
                    degraded.append(f"agent:{ag.agent_id}")

            active_projects = sum(1 for pr in self._projects.values() if pr.is_eligible)

            total = (
                len(self._providers)
                + len(self._accounts)
                + len(self._environments)
                + len(unique_caps)
                + len(self._agents)
                + len(self._projects)
            )

            is_healthy = len(degraded) == 0 and active_providers > 0 and active_accounts > 0
            overall_status = "healthy" if is_healthy else "degraded" if active_providers > 0 else "unconfigured"

            return ResourceHealthReport(
                is_healthy=is_healthy,
                status=overall_status,
                total_resources=total,
                active_providers=active_providers,
                active_accounts=active_accounts,
                active_environments=active_environments,
                active_capabilities=active_caps,
                active_agents=active_agents,
                active_projects=active_projects,
                exhausted_accounts=exhausted_accounts,
                degraded_resources=degraded,
            )

    def get_metrics(self) -> RRMRegistryMetrics:
        with self._lock:
            counts = {
                "providers": len(self._providers),
                "accounts": len(self._accounts),
                "environments": len(self._environments),
                "capabilities": len({id(c) for c in self._capabilities.values()}),
                "agents": len(self._agents),
                "projects": len(self._projects),
            }

            status_counts: Dict[str, int] = {}

            all_resources: List[Any] = (
                list(self._providers.values())
                + list(self._accounts.values())
                + list(self._environments.values())
                + list({id(c): c for c in self._capabilities.values()}.values())
                + list(self._agents.values())
                + list(self._projects.values())
            )

            for r in all_resources:
                st = getattr(r, "status", None)
                st_str = st.value if isinstance(st, Enum) else str(st)
                status_counts[st_str] = status_counts.get(st_str, 0) + 1

            return RRMRegistryMetrics(
                resource_counts=counts,
                status_counts=status_counts,
                providers_count=counts["providers"],
                accounts_count=counts["accounts"],
                environments_count=counts["environments"],
                capabilities_count=counts["capabilities"],
                agents_count=counts["agents"],
                projects_count=counts["projects"],
            )

    # --- Default Catalog Seeds ---

    def populate_default_catalog(self) -> None:
        """Seeds template entries for Intent OS runtime.
        
        CRITICAL ARCHITECTURAL RULE (Studio 8.1):
        Default catalog seeds are strictly TEMPLATES (is_template=True, status=UNCONFIGURED/DRAFT).
        TEMPLATE != AVAILABLE/ELIGIBLE.
        Default seeds do NOT automatically participate in execution selection until explicit
        configuration, discovery, or user registration occurs.
        """
        with self._lock:
            # 1. Default Capabilities (Templates)
            default_caps = [
                ("cap_retrieval_financial", "retrieval.financial_context", "Resgate de histórico financeiro", ["finance", "retrieval"], ["finance"], "read"),
                ("cap_modeling_allocation", "modeling.allocation_scenarios", "Modelagem de cenários de alocação", ["finance", "modeling"], ["finance"], "compute"),
                ("cap_analysis_risk", "analysis.risk_evaluation", "Avaliação de riscos de mercado e liquidez", ["finance", "risk"], ["finance"], "compute"),
                ("cap_synthesis_recommendation", "synthesis.recommendation", "Sintetização de recomendações", ["synthesis", "advisory"], ["finance", "general"], "generate"),
                ("cap_validation_goal", "validation.goal_alignment", "Validação de conformidade de metas", ["validation", "goal"], ["general"], "compute"),
                ("cap_code_architecture", "code.architecture_design", "Design de arquitetura de software", ["coding", "architecture"], ["coding"], "generate"),
                ("cap_code_scaffold", "code.scaffold_generation", "Geração de código base e estrutura", ["coding", "generation"], ["coding"], "generate"),
                ("cap_code_ui", "code.ui_design", "Construção e layout de interfaces", ["coding", "ui"], ["coding"], "generate"),
                ("cap_code_backend", "code.backend_logic", "Implementação de lógica backend e APIs", ["coding", "backend"], ["coding"], "generate"),
                ("cap_code_testing", "code.testing", "Verificação e testes unitários", ["coding", "testing"], ["coding"], "compute"),
                ("cap_code_docs", "code.documentation", "Geração de documentação técnica", ["coding", "docs"], ["coding"], "generate"),
                ("cap_ext_communication", "external.communication", "Comunicação e envio de mensagens externas", ["communication", "external"], ["communication"], "external_change"),
                ("cap_research_gathering", "research.information_gathering", "Coleta e pesquisa de informações", ["research", "gathering"], ["research"], "read"),
                ("cap_research_comparative", "research.comparative_analysis", "Análise comparativa de dados", ["research", "comparison"], ["research"], "compute"),
            ]
            for cid, name, desc, tags, domains, effect in default_caps:
                self.register_capability(
                    CapabilityResource(
                        capability_id=cid,
                        name=name,
                        description=desc,
                        tags=tags,
                        domains=domains,
                        effect=effect,
                        status=ResourceStatus.DRAFT,
                        resource_origin=ResourceOrigin.TEMPLATE,
                        availability_source=AvailabilitySource.UNKNOWN,
                        is_template=True,
                        is_executable=False,
                    )
                )

            # 2. Default Providers (Templates)
            self.register_provider(
                ProviderResource(
                    provider_id="provider_gemini_ultra",
                    name="Gemini 1.5 Pro / Ultra Profile",
                    reasoning_score=0.95,
                    tool_use_support=True,
                    context_window=1000000,
                    cost_per_1k_tokens=0.002,
                    privacy_tier="high",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_anthropic_claude",
                    name="Claude 3.5 Sonnet Profile",
                    reasoning_score=0.96,
                    tool_use_support=True,
                    context_window=200000,
                    cost_per_1k_tokens=0.003,
                    privacy_tier="high",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_openai_gpt4",
                    name="GPT-4o Profile",
                    reasoning_score=0.94,
                    tool_use_support=True,
                    context_window=128000,
                    cost_per_1k_tokens=0.0025,
                    privacy_tier="standard",
                    multimodal=True,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )
            self.register_provider(
                ProviderResource(
                    provider_id="provider_local_llama",
                    name="Local Llama 3 Edge Profile",
                    reasoning_score=0.75,
                    tool_use_support=True,
                    context_window=32000,
                    cost_per_1k_tokens=0.0001,
                    privacy_tier="high",
                    multimodal=False,
                    availability=0.0,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    has_active_account=False,
                )
            )

            # 3. Default Accounts (Templates)
            self.register_account(
                AccountResource(
                    account_id="acc_primary_gcp_01",
                    provider_id="provider_gemini_ultra",
                    name="Primary GCP Studio Enterprise Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=10,
                    cost_multiplier=1.0,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy", "enterprise"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_anthropic_prod_01",
                    provider_id="provider_anthropic_claude",
                    name="Production Anthropic Direct Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=9,
                    cost_multiplier=1.0,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_openai_backup_01",
                    provider_id="provider_openai_gpt4",
                    name="OpenAI Reserve Enterprise Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=7,
                    cost_multiplier=1.1,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard"],
                )
            )
            self.register_account(
                AccountResource(
                    account_id="acc_local_edge_01",
                    provider_id="provider_local_llama",
                    name="Local On-Prem Edge Account",
                    quota_remaining=0.0,
                    rate_limit_rpm=0,
                    priority=5,
                    cost_multiplier=0.01,
                    status=ResourceStatus.UNCONFIGURED,
                    secret_reference=None,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_configured=False,
                    allowed_policies=["standard", "high_privacy", "offline_only"],
                )
            )

            # 4. Default Execution Environments (Templates)
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_local_process",
                    type=ExecutionEnvironmentType.LOCAL_PROCESS,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["code_execution", "local_storage", "in_memory"],
                    available_tools=["python_interpreter", "file_system"],
                    network_access=True,
                    privacy_level="high",
                    latency_class="ultra_low",
                    cost_class="free",
                    resource_limits={"memory_mb": 4096, "cpu_cores": 4},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_desktop_host",
                    type=ExecutionEnvironmentType.DESKTOP,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["ui_rendering", "local_storage", "ipc_bridge"],
                    available_tools=["desktop_native", "file_system"],
                    network_access=True,
                    privacy_level="high",
                    latency_class="low",
                    cost_class="free",
                    resource_limits={"memory_mb": 8192, "cpu_cores": 8},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_cloud_server",
                    type=ExecutionEnvironmentType.CLOUD,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["scalable_compute", "cloud_storage", "remote_api"],
                    available_tools=["cloud_runner", "external_http"],
                    network_access=True,
                    privacy_level="standard",
                    latency_class="medium",
                    cost_class="medium",
                    resource_limits={"memory_mb": 16384, "cpu_cores": 16},
                )
            )
            self.register_environment(
                ExecutionEnvironmentResource(
                    environment_id="env_remote_edge",
                    type=ExecutionEnvironmentType.EDGE,
                    status=ResourceStatus.UNCONFIGURED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_discovered=False,
                    capabilities=["airgapped_compute", "edge_inference"],
                    available_tools=["edge_runner"],
                    network_access=False,
                    privacy_level="airgapped",
                    latency_class="low",
                    cost_class="low",
                    resource_limits={"memory_mb": 2048, "cpu_cores": 2},
                )
            )

            # 5. Default Agents (Templates)
            self.register_agent(
                AgentResource(
                    agent_id="agent_financial_atlas",
                    name="Atlas Financial Engine",
                    capabilities=[
                        "retrieval.financial_context",
                        "modeling.allocation_scenarios",
                        "analysis.risk_evaluation",
                        "synthesis.recommendation",
                    ],
                    specialization=["finance", "risk", "modeling"],
                    historical_confidence=0.96,
                    cost_tier=0.015,
                    latency_tier=0.25,
                    supported_domains=["finance"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_logos_synthesizer",
                    name="Logos Synthesis Agent",
                    capabilities=[
                        "synthesis.recommendation",
                        "validation.goal_alignment",
                        "external.communication",
                        "research.comparative_analysis",
                    ],
                    specialization=["synthesis", "validation", "communication"],
                    historical_confidence=0.92,
                    cost_tier=0.010,
                    latency_tier=0.15,
                    supported_domains=["finance", "communication", "general"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_code_architect",
                    name="Code Architect & Builder Agent",
                    capabilities=[
                        "code.architecture_design",
                        "code.scaffold_generation",
                        "code.ui_design",
                        "code.backend_logic",
                        "code.testing",
                        "code.documentation",
                    ],
                    specialization=["coding", "architecture", "scaffold"],
                    historical_confidence=0.94,
                    cost_tier=0.020,
                    latency_tier=0.30,
                    supported_domains=["coding"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_researcher_scout",
                    name="Deep Research Scout",
                    capabilities=[
                        "research.information_gathering",
                        "research.comparative_analysis",
                        "retrieval.financial_context",
                    ],
                    specialization=["research", "comparative"],
                    historical_confidence=0.91,
                    cost_tier=0.008,
                    latency_tier=0.20,
                    supported_domains=["research", "general"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )
            self.register_agent(
                AgentResource(
                    agent_id="agent_core_orchestrator",
                    name="Core General Agent",
                    capabilities=[
                        "retrieval.financial_context",
                        "synthesis.recommendation",
                        "validation.goal_alignment",
                        "research.information_gathering",
                        "external.communication",
                    ],
                    specialization=["general", "coordination"],
                    historical_confidence=0.88,
                    cost_tier=0.005,
                    latency_tier=0.10,
                    supported_domains=["general", "finance", "coding", "communication"],
                    status=ResourceStatus.UNCONFIGURED,
                    installation_state=AgentInstallationState.DEFINED,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_enabled=False,
                )
            )

            # 6. Default Projects (Templates / Demo Fixtures)
            self.register_project(
                ProjectResource(
                    project_id="proj_system_core",
                    name="Intent OS Core System Workspace",
                    domain="system",
                    description="Template workspace definition for Intent OS kernel processes and system agents.",
                    owner_id="system_governor",
                    status=ResourceStatus.DRAFT,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_demo=True,
                    retention_class="permanent",
                    access_scope="organization",
                    assigned_agents=[
                        "agent_core_orchestrator",
                        "agent_code_architect",
                    ],
                    assigned_environments=[
                        "env_local_process",
                        "env_desktop_host",
                    ],
                )
            )
            self.register_project(
                ProjectResource(
                    project_id="proj_product_alpha",
                    name="Product Alpha Workspace",
                    domain="finance",
                    description="Demo fixture workspace for Atlas financial modeling and advisory missions.",
                    owner_id="user_primary",
                    status=ResourceStatus.DRAFT,
                    resource_origin=ResourceOrigin.TEMPLATE,
                    availability_source=AvailabilitySource.UNKNOWN,
                    is_template=True,
                    is_demo=True,
                    retention_class="permanent",
                    access_scope="project",
                    assigned_agents=[
                        "agent_financial_atlas",
                        "agent_logos_synthesizer",
                        "agent_researcher_scout",
                    ],
                    assigned_environments=[
                        "env_local_process",
                        "env_cloud_server",
                    ],
                )
            )

