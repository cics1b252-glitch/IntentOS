"""Registry & Resource Manager (RRM) — COR Adapter (RFC-0013).

Provides an interface adapter translating RRM canonical resources to COR's expected
RegistryCatalog contracts, maintaining loose coupling between RRM and COR.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from intent_kernel.cor import (
    AccountRegistration,
    AgentRegistration,
    CapabilityRegistration,
    ExecutionEnvironment,
    ExecutionEnvironmentType as CORExecutionEnvironmentType,
    ProviderRegistration,
)
from intent_kernel.rrm.models import (
    AccountResource,
    AgentInstallationState,
    AgentResource,
    CapabilityResource,
    ExecutionEnvironmentResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
)
from intent_kernel.rrm.service import RegistryResourceManager


class RRMToCORAdapter:
    """Adapter bridging RRM (RegistryResourceManager) to COR's RegistryCatalog interface."""

    def __init__(self, rrm_service: Optional[RegistryResourceManager] = None) -> None:
        self._rrm = rrm_service or RegistryResourceManager(populate_defaults=True)

    @property
    def rrm_service(self) -> RegistryResourceManager:
        return self._rrm

    def register_capability(self, cap: CapabilityRegistration) -> None:
        resource = CapabilityResource(
            capability_id=f"cap_{cap.name}",
            name=cap.name,
            description=cap.description,
            tags=list(cap.tags),
            provided_by_agents=list(cap.provided_by_agents),
            status=ResourceStatus.ACTIVE,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_executable=True,
        )
        self._rrm.register_capability(resource)

    def register_agent(self, agent: AgentRegistration) -> None:
        st = ResourceStatus(agent.status) if agent.status in [s.value for s in ResourceStatus] else ResourceStatus.ACTIVE
        resource = AgentResource(
            agent_id=agent.agent_id,
            name=agent.name,
            capabilities=list(agent.capabilities),
            specialization=list(agent.specialization),
            availability=agent.availability,
            status=st,
            installation_state=AgentInstallationState.INSTALLED if st == ResourceStatus.ACTIVE else AgentInstallationState.DEFINED,
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            is_template=False,
            is_enabled=st == ResourceStatus.ACTIVE,
            version=agent.version,
            historical_confidence=agent.historical_confidence,
            cost_tier=agent.cost_tier,
            latency_tier=agent.latency_tier,
            supported_domains=list(agent.supported_domains),
        )
        self._rrm.register_agent(resource)

    def register_provider(self, provider: ProviderRegistration) -> None:
        st = ResourceStatus(provider.status) if provider.status in [s.value for s in ResourceStatus] else ResourceStatus.ACTIVE
        resource = ProviderResource(
            provider_id=provider.provider_id,
            name=provider.name,
            reasoning_score=provider.reasoning_score,
            tool_use_support=provider.tool_use_support,
            context_window=provider.context_window,
            cost_per_1k_tokens=provider.cost_per_1k_tokens,
            privacy_tier=provider.privacy_tier,
            availability=provider.availability,
            multimodal=provider.multimodal,
            status=st,
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        self._rrm.register_provider(resource)

    def register_account(self, account: AccountRegistration) -> None:
        st = ResourceStatus(account.status) if account.status in [s.value for s in ResourceStatus] else ResourceStatus.ACTIVE
        resource = AccountResource(
            account_id=account.account_id,
            provider_id=account.provider_id,
            name=account.name,
            quota_remaining=account.quota_remaining,
            rate_limit_rpm=account.rate_limit_rpm,
            priority=account.priority,
            cost_multiplier=account.cost_multiplier,
            status=st,
            secret_reference=f"sec_ref_{account.account_id}",
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            is_configured=True,
            allowed_policies=list(account.allowed_policies),
        )
        self._rrm.register_account(resource)

    def register_environment(self, env: ExecutionEnvironment) -> None:
        st = ResourceStatus(env.status) if env.status in [s.value for s in ResourceStatus] else ResourceStatus.ACTIVE
        resource = ExecutionEnvironmentResource(
            environment_id=env.environment_id,
            type=env.type.value if hasattr(env.type, "value") else str(env.type),
            status=st,
            resource_origin=ResourceOrigin.HOST_DISCOVERY,
            is_template=False,
            is_discovered=True,
            capabilities=list(env.capabilities),
            available_tools=list(env.available_tools),
            network_access=env.network_access,
            privacy_level=env.privacy_level,
            latency_class=env.latency_class,
            cost_class=env.cost_class,
            resource_limits=dict(env.resource_limits),
        )
        self._rrm.register_environment(resource)

    def get_capability(self, name: str) -> Optional[CapabilityRegistration]:
        cap = self._rrm.get_capability(name)
        if not cap or not cap.is_eligible:
            return None
        return CapabilityRegistration(
            name=cap.name,
            description=cap.description,
            tags=list(cap.tags),
            provided_by_agents=list(cap.provided_by_agents),
        )

    def list_capabilities(self) -> List[CapabilityRegistration]:
        caps = self._rrm.list_capabilities(only_eligible=True)
        return [
            CapabilityRegistration(
                name=c.name,
                description=c.description,
                tags=list(c.tags),
                provided_by_agents=list(c.provided_by_agents),
            )
            for c in caps
        ]

    def find_agents_for_capabilities(self, capabilities: List[str]) -> List[AgentRegistration]:
        agents = self._rrm.find_agents_for_capabilities(capabilities, only_eligible=True)
        return [self._to_cor_agent(a) for a in agents]

    def list_agents(self) -> List[AgentRegistration]:
        agents = self._rrm.list_agents(only_eligible=True)
        return [self._to_cor_agent(a) for a in agents]

    def list_providers(self) -> List[ProviderRegistration]:
        providers = self._rrm.list_providers(only_eligible=True)
        return [self._to_cor_provider(p) for p in providers]

    def list_accounts_for_provider(self, provider_id: str) -> List[AccountRegistration]:
        accounts = self._rrm.list_accounts(provider_id=provider_id, only_eligible=True)
        return [self._to_cor_account(a) for a in accounts]

    def get_environment(self, env_id: str) -> Optional[ExecutionEnvironment]:
        env = self._rrm.get_environment(env_id)
        if not env or not env.is_eligible:
            return None
        return self._to_cor_environment(env)

    def list_environments(self) -> List[ExecutionEnvironment]:
        envs = self._rrm.list_environments(only_eligible=True)
        return [self._to_cor_environment(e) for e in envs]

    def populate_default_catalog(self) -> None:
        self._rrm.populate_default_catalog()

    # --- Private Converters ---

    def _to_cor_agent(self, a: AgentResource) -> AgentRegistration:
        return AgentRegistration(
            agent_id=a.agent_id,
            name=a.name,
            capabilities=list(a.capabilities),
            specialization=list(a.specialization),
            availability=a.availability,
            status=a.status.value if isinstance(a.status, ResourceStatus) else str(a.status),
            version=a.version,
            historical_confidence=a.historical_confidence,
            cost_tier=a.cost_tier,
            latency_tier=a.latency_tier,
            supported_domains=list(a.supported_domains),
        )

    def _to_cor_provider(self, p: ProviderResource) -> ProviderRegistration:
        return ProviderRegistration(
            provider_id=p.provider_id,
            name=p.name,
            reasoning_score=p.reasoning_score,
            tool_use_support=p.tool_use_support,
            context_window=p.context_window,
            cost_per_1k_tokens=p.cost_per_1k_tokens,
            privacy_tier=p.privacy_tier,
            availability=p.availability,
            multimodal=p.multimodal,
            status=p.status.value if isinstance(p.status, ResourceStatus) else str(p.status),
        )

    def _to_cor_account(self, a: AccountResource) -> AccountRegistration:
        return AccountRegistration(
            account_id=a.account_id,
            provider_id=a.provider_id,
            name=a.name,
            quota_remaining=a.quota_remaining,
            rate_limit_rpm=a.rate_limit_rpm,
            priority=a.priority,
            cost_multiplier=a.cost_multiplier,
            status=a.status.value if isinstance(a.status, ResourceStatus) else str(a.status),
            allowed_policies=list(a.allowed_policies),
        )

    def _to_cor_environment(self, e: ExecutionEnvironmentResource) -> ExecutionEnvironment:
        try:
            env_type = CORExecutionEnvironmentType(e.type.value if hasattr(e.type, "value") else str(e.type))
        except ValueError:
            env_type = CORExecutionEnvironmentType.LOCAL_PROCESS

        return ExecutionEnvironment(
            environment_id=e.environment_id,
            type=env_type,
            status=e.status.value if isinstance(e.status, ResourceStatus) else str(e.status),
            capabilities=list(e.capabilities),
            available_tools=list(e.available_tools),
            network_access=e.network_access,
            privacy_level=e.privacy_level,
            latency_class=e.latency_class,
            cost_class=e.cost_class,
            resource_limits=dict(e.resource_limits),
        )
