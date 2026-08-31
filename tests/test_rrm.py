"""Unit tests for Registry & Resource Manager (RRM) — RFC-0013."""

import threading
import unittest
from typing import List

from intent_kernel.cor import CapabilityOrchestrator
from intent_kernel.cpe import ExecutionPlan, PlanStep
from intent_kernel.rrm import (
    AccountResource,
    AgentInstallationState,
    AgentResource,
    CapabilityResource,
    ExecutionEnvironmentResource,
    ExecutionEnvironmentType,
    ProjectResource,
    ProviderResource,
    RegistryResourceManager,
    ResourceHealthReport,
    ResourceOrigin,
    ResourceQueryFilter,
    ResourceStatus,
    ResourceType,
    RRMRegistryMetrics,
    RRMToCORAdapter,
)


class TestRRMProviderOperations(unittest.TestCase):
    """Tests for Provider management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_get_provider(self):
        provider = ProviderResource(
            provider_id="prov_test_01",
            name="Test Provider Profile",
            reasoning_score=0.92,
            context_window=64000,
        )
        registered = self.rrm.register_provider(provider)
        self.assertEqual(registered.provider_id, "prov_test_01")

        fetched = self.rrm.get_provider("prov_test_01")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test Provider Profile")
        self.assertEqual(fetched.reasoning_score, 0.92)

    def test_list_providers_and_filter_by_status(self):
        p1 = ProviderResource(provider_id="prov_active", name="Active Provider", status=ResourceStatus.ACTIVE)
        p2 = ProviderResource(provider_id="prov_degraded", name="Degraded Provider", status=ResourceStatus.DEGRADED)
        self.rrm.register_provider(p1)
        self.rrm.register_provider(p2)

        all_providers = self.rrm.list_providers()
        self.assertEqual(len(all_providers), 2)

        active_providers = self.rrm.list_providers(status=ResourceStatus.ACTIVE)
        self.assertEqual(len(active_providers), 1)
        self.assertEqual(active_providers[0].provider_id, "prov_active")

    def test_unregister_provider(self):
        p1 = ProviderResource(provider_id="prov_del", name="To Delete")
        self.rrm.register_provider(p1)
        self.assertTrue(self.rrm.unregister_provider("prov_del"))
        self.assertIsNone(self.rrm.get_provider("prov_del"))
        self.assertFalse(self.rrm.unregister_provider("non_existent"))


class TestRRMAccountOperations(unittest.TestCase):
    """Tests for Service Account management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_get_account(self):
        acc = AccountResource(
            account_id="acc_test_01",
            provider_id="prov_gemini",
            name="Test Account",
            quota_remaining=50000.0,
            priority=8,
        )
        self.rrm.register_account(acc)

        fetched = self.rrm.get_account("acc_test_01")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.provider_id, "prov_gemini")
        self.assertEqual(fetched.quota_remaining, 50000.0)

    def test_list_accounts_for_provider(self):
        a1 = AccountResource(account_id="a1", provider_id="p1", name="Acc 1")
        a2 = AccountResource(account_id="a2", provider_id="p1", name="Acc 2")
        a3 = AccountResource(account_id="a3", provider_id="p2", name="Acc 3")
        self.rrm.register_account(a1)
        self.rrm.register_account(a2)
        self.rrm.register_account(a3)

        p1_accounts = self.rrm.list_accounts(provider_id="p1")
        self.assertEqual(len(p1_accounts), 2)
        p2_accounts = self.rrm.list_accounts(provider_id="p2")
        self.assertEqual(len(p2_accounts), 1)


class TestRRMExecutionEnvironmentOperations(unittest.TestCase):
    """Tests for Execution Environment management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_get_environment(self):
        env = ExecutionEnvironmentResource(
            environment_id="env_local_01",
            type=ExecutionEnvironmentType.LOCAL_PROCESS,
            capabilities=["python_execution", "file_access"],
            privacy_level="high",
        )
        self.rrm.register_environment(env)

        fetched = self.rrm.get_environment("env_local_01")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.type, ExecutionEnvironmentType.LOCAL_PROCESS)
        self.assertIn("python_execution", fetched.capabilities)


class TestRRMCapabilityOperations(unittest.TestCase):
    """Tests for Capability management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_get_capability_by_id_or_name(self):
        cap = CapabilityResource(
            capability_id="cap_fin_retrieval",
            name="retrieval.financial_context",
            description="Fetch financial metrics",
            domains=["finance"],
        )
        self.rrm.register_capability(cap)

        fetched_by_id = self.rrm.get_capability("cap_fin_retrieval")
        self.assertIsNotNone(fetched_by_id)

        fetched_by_name = self.rrm.get_capability("retrieval.financial_context")
        self.assertIsNotNone(fetched_by_name)
        self.assertEqual(fetched_by_id, fetched_by_name)


class TestRRMAgentOperations(unittest.TestCase):
    """Tests for Agent management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_find_agents_for_capabilities(self):
        ag = AgentResource(
            agent_id="ag_atlas",
            name="Atlas Engine",
            capabilities=["retrieval.financial_context", "modeling.allocation_scenarios"],
            supported_domains=["finance"],
            historical_confidence=0.95,
        )
        self.rrm.register_agent(ag)

        fetched = self.rrm.get_agent("ag_atlas")
        self.assertIsNotNone(fetched)

        matching = self.rrm.find_agents_for_capabilities(["retrieval.financial_context"])
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].agent_id, "ag_atlas")


class TestRRMProjectOperations(unittest.TestCase):
    """Tests for Project workspace management in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=False)

    def test_register_and_get_project(self):
        proj = ProjectResource(
            project_id="proj_alpha",
            name="Product Alpha",
            domain="finance",
            owner_id="user_owner_01",
            budget_limit=500.0,
        )
        self.rrm.register_project(proj)

        fetched = self.rrm.get_project("proj_alpha")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Product Alpha")
        self.assertEqual(fetched.budget_limit, 500.0)

        projects = self.rrm.list_projects()
        self.assertEqual(len(projects), 1)


class TestRRMResourceQueryFilter(unittest.TestCase):
    """Tests for multi-criteria querying in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=True)

    def test_query_resources_by_type_and_domain(self):
        query = ResourceQueryFilter(
            resource_type=ResourceType.AGENT,
            domain="finance",
        )
        results = self.rrm.query_resources(query)
        self.assertTrue(len(results) > 0)
        for res in results:
            self.assertIn("finance", getattr(res, "supported_domains", []))

    def test_query_resources_by_min_confidence(self):
        query = ResourceQueryFilter(
            resource_type=ResourceType.PROVIDER,
            min_confidence=0.95,
        )
        results = self.rrm.query_resources(query)
        self.assertTrue(len(results) > 0)
        for res in results:
            self.assertGreaterEqual(res.reasoning_score, 0.95)

    def test_query_resources_text_search(self):
        query = ResourceQueryFilter(
            text_search="Atlas",
        )
        results = self.rrm.query_resources(query)
        self.assertTrue(len(results) > 0)
        found_names = [getattr(r, "name", "") for r in results]
        self.assertTrue(any("Atlas" in name for name in found_names))


class TestRRMHealthAndMetrics(unittest.TestCase):
    """Tests for health reporting and metric calculations in RRM."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=True)

    def test_health_report_unconfigured_default_catalog(self):
        report = self.rrm.check_health()
        # Default catalog contains templates, which are unconfigured/not eligible
        self.assertFalse(report.is_healthy)
        self.assertEqual(report.status, "unconfigured")
        self.assertGreater(report.total_resources, 10)
        self.assertEqual(report.active_providers, 0)

    def test_health_report_when_configured(self):
        # Explicitly register active provider + account
        self.rrm.register_provider(ProviderResource(provider_id="prov_active", name="Active Provider", status=ResourceStatus.ACTIVE))
        self.rrm.register_account(AccountResource(account_id="acc_active", provider_id="prov_active", name="Active Acc", status=ResourceStatus.ACTIVE, secret_reference="sec_123"))
        report = self.rrm.check_health()
        self.assertTrue(report.is_healthy)
        self.assertEqual(report.status, "healthy")
        self.assertGreater(report.active_providers, 0)

    def test_metrics_summary(self):
        metrics = self.rrm.get_metrics()
        self.assertGreater(metrics.providers_count, 0)
        self.assertGreater(metrics.accounts_count, 0)
        self.assertGreater(metrics.agents_count, 0)
        self.assertGreater(metrics.projects_count, 0)

    def test_status_update_reflects_in_health(self):
        # Register explicit active provider and then set it degraded
        p = ProviderResource(provider_id="prov_deg_test", name="Degraded Test", status=ResourceStatus.ACTIVE)
        self.rrm.register_provider(p)
        self.rrm.update_resource_status(
            resource_type=ResourceType.PROVIDER,
            resource_id="prov_deg_test",
            status=ResourceStatus.DEGRADED,
        )

        fetched = self.rrm.get_provider("prov_deg_test")
        self.assertEqual(fetched.status, ResourceStatus.DEGRADED)

        report = self.rrm.check_health()
        self.assertFalse(report.is_healthy)
        self.assertIn("provider:prov_deg_test", report.degraded_resources)


class TestRRMToCORAdapter(unittest.TestCase):
    """Tests for RRMToCORAdapter integration with COR (CapabilityOrchestrator)."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=True)
        self.adapter = RRMToCORAdapter(self.rrm)
        self.orchestrator = CapabilityOrchestrator()

    def test_adapter_filters_out_unconfigured_templates(self):
        # On default unconfigured catalog, adapter returns 0 eligible providers to COR
        providers = self.adapter.list_providers()
        self.assertEqual(len(providers), 0)

        agents = self.adapter.list_agents()
        self.assertEqual(len(agents), 0)

        envs = self.adapter.list_environments()
        self.assertEqual(len(envs), 0)

    def test_cor_orchestration_with_explicitly_registered_resources(self):
        # Register capabilities, agents, providers, accounts, and environment to adapter
        from intent_kernel.cor import AgentRegistration, CapabilityRegistration, ProviderRegistration, AccountRegistration, ExecutionEnvironment, ExecutionEnvironmentType as CORExecutionEnvironmentType
        self.adapter.register_capability(CapabilityRegistration(name="retrieval.financial_context", description="Fetch context"))
        self.adapter.register_capability(CapabilityRegistration(name="synthesis.recommendation", description="Synthesize"))
        self.adapter.register_provider(ProviderRegistration(provider_id="prov_gemini", name="Gemini Provider", reasoning_score=0.95))
        self.adapter.register_account(AccountRegistration(account_id="acc_gemini", provider_id="prov_gemini", name="Gemini Account"))
        self.adapter.register_agent(AgentRegistration(agent_id="ag_atlas", name="Atlas Agent", capabilities=["retrieval.financial_context", "synthesis.recommendation"]))
        self.adapter.register_environment(ExecutionEnvironment(environment_id="env_local", type=CORExecutionEnvironmentType.LOCAL_PROCESS))

        providers = self.adapter.list_providers()
        self.assertEqual(len(providers), 1)

        agents = self.adapter.list_agents()
        self.assertEqual(len(agents), 1)

        plan = ExecutionPlan(
            plan_id="plan_test_rrm_01",
            intent_id="intent_test_rrm_01",
            goal="Analyze financial portfolio and generate scenario recommendation",
            steps=[
                PlanStep(
                    step_id="step_1",
                    objective="Fetch financial portfolio metrics",
                    action_type="retrieval",
                    required_capabilities=["retrieval.financial_context"],
                ),
                PlanStep(
                    step_id="step_2",
                    objective="Generate portfolio allocation recommendations",
                    action_type="synthesis",
                    dependencies=["step_1"],
                    required_capabilities=["synthesis.recommendation"],
                ),
            ],
            status="ready",
        )

        graph = self.orchestrator.orchestrate(plan, registry=self.adapter)

        self.assertEqual(graph.status, "ready")
        self.assertEqual(len(graph.nodes), 2)
        self.assertIn("step_1", graph.assignments)
        self.assertIn("step_2", graph.assignments)

        assign1 = graph.assignments["step_1"]
        self.assertEqual(assign1.capability, "retrieval.financial_context")
        self.assertIsNotNone(assign1.agent_id)
        self.assertIsNotNone(assign1.provider_id)


class TestRRMHardeningAndProvenance(unittest.TestCase):
    """Mandatory STUDIO 8.1 Hardening & Resource Provenance Verification Tests (A-J)."""

    def setUp(self):
        self.rrm = RegistryResourceManager(populate_defaults=True)

    def test_a_empty_catalog_has_no_fictitious_eligible_resources(self):
        """Rule A: Seed catalog contains NO active/eligible execution candidates."""
        report = self.rrm.check_health()
        self.assertEqual(report.active_providers, 0)
        self.assertEqual(report.active_accounts, 0)
        self.assertEqual(report.active_environments, 0)
        self.assertEqual(report.active_agents, 0)

        eligible_providers = self.rrm.list_providers(only_eligible=True)
        self.assertEqual(len(eligible_providers), 0)

    def test_b_provider_template_without_account_is_not_eligible(self):
        """Rule B: Provider template without account/config is ineligible."""
        provider = ProviderResource(
            provider_id="prov_template_only",
            name="Template Provider",
            is_template=True,
            resource_origin=ResourceOrigin.TEMPLATE,
            is_configured=False,
            has_active_account=False,
            status=ResourceStatus.UNCONFIGURED,
        )
        self.rrm.register_provider(provider)
        self.assertFalse(provider.is_eligible)
        self.assertNotIn(provider, self.rrm.list_providers(only_eligible=True))

    def test_c_unconfigured_account_without_secret_is_not_eligible(self):
        """Rule C: Service account without secret reference/config is ineligible."""
        acc = AccountResource(
            account_id="acc_unconfigured",
            provider_id="prov_gemini",
            name="Unconfigured Account",
            secret_reference=None,
            is_configured=False,
            status=ResourceStatus.UNCONFIGURED,
        )
        self.rrm.register_account(acc)
        self.assertFalse(acc.is_eligible)
        self.assertNotIn(acc, self.rrm.list_accounts(only_eligible=True))

    def test_d_undiscovered_environment_template_is_not_eligible(self):
        """Rule D: Environment template that is not discovered is ineligible."""
        env = ExecutionEnvironmentResource(
            environment_id="env_template",
            type=ExecutionEnvironmentType.LOCAL_PROCESS,
            is_template=True,
            is_discovered=False,
            status=ResourceStatus.UNCONFIGURED,
        )
        self.rrm.register_environment(env)
        self.assertFalse(env.is_eligible)
        self.assertNotIn(env, self.rrm.list_environments(only_eligible=True))

    def test_e_disabled_or_uninstalled_agent_is_not_eligible(self):
        """Rule E: Agent defined but disabled or uninstalled is ineligible."""
        ag_disabled = AgentResource(
            agent_id="ag_dis",
            name="Disabled Agent",
            is_enabled=False,
            installation_state=AgentInstallationState.INSTALLED,
            status=ResourceStatus.ACTIVE,
        )
        ag_defined_only = AgentResource(
            agent_id="ag_def",
            name="Defined Only Agent",
            is_enabled=True,
            installation_state=AgentInstallationState.DEFINED,
            status=ResourceStatus.ACTIVE,
        )
        self.rrm.register_agent(ag_disabled)
        self.rrm.register_agent(ag_defined_only)

        self.assertFalse(ag_disabled.is_eligible)
        self.assertFalse(ag_defined_only.is_eligible)
        eligible_agents = self.rrm.list_agents(only_eligible=True)
        self.assertNotIn(ag_disabled, eligible_agents)
        self.assertNotIn(ag_defined_only, eligible_agents)

    def test_f_non_executable_capability_is_not_eligible(self):
        """Rule F: Capability without executable handler is ineligible."""
        cap = CapabilityResource(
            capability_id="cap_non_exec",
            name="capability.non_executable",
            is_executable=False,
            status=ResourceStatus.ACTIVE,
        )
        self.rrm.register_capability(cap)
        self.assertFalse(cap.is_eligible)
        self.assertNotIn(cap, self.rrm.list_capabilities(only_eligible=True))

    def test_g_explicitly_registered_active_resource_is_eligible(self):
        """Rule G: Resource explicitly registered with valid configuration is eligible."""
        p = ProviderResource(
            provider_id="prov_real",
            name="Real Provider",
            status=ResourceStatus.ACTIVE,
            resource_origin=ResourceOrigin.CONFIGURATION,
            is_template=False,
            is_configured=True,
            has_active_account=True,
        )
        self.rrm.register_provider(p)
        self.assertTrue(p.is_eligible)
        # list_providers now returns ProviderSnapshot objects; verify the snapshot exists
        snapshots = self.rrm.list_providers(only_eligible=True)
        self.assertTrue(any(s.provider_id == p.provider_id for s in snapshots))

    def test_h_adapter_does_not_deliver_templates_to_cor(self):
        """Rule H: Adapter translates only eligible resources to COR."""
        adapter = RRMToCORAdapter(self.rrm)
        # Seed catalog contains templates -> COR sees 0 providers/agents/environments
        self.assertEqual(len(adapter.list_providers()), 0)
        self.assertEqual(len(adapter.list_agents()), 0)
        self.assertEqual(len(adapter.list_environments()), 0)

    def test_i_no_credentials_in_serialization(self):
        """Rule I: Serialization contains secret references, never plain text credentials."""
        acc = AccountResource(
            account_id="acc_secure",
            provider_id="prov_gemini",
            name="Secure Account",
            secret_reference="vault_ref_0182",
            status=ResourceStatus.ACTIVE,
        )
        d = acc.to_dict()
        self.assertEqual(d["secret_reference"], "vault_ref_0182")
        self.assertNotIn("password", d)
        self.assertNotIn("api_key", d)
        self.assertNotIn("token", d)

    def test_j_templates_remain_available_for_configuration(self):
        """Rule J: Templates can be retrieved by ID for future configuration without being active."""
        p_template = self.rrm.get_provider("provider_gemini_ultra")
        self.assertIsNotNone(p_template)
        self.assertTrue(p_template.is_template)
        self.assertFalse(p_template.is_eligible)


class TestRRMConcurrencyAndThreadSafety(unittest.TestCase):
    """Tests for thread safety under concurrent operations in RRM."""

    def test_concurrent_registrations_and_queries(self):
        rrm = RegistryResourceManager(populate_defaults=False)
        threads = []
        errors = []

        def worker(idx: int):
            try:
                p = ProviderResource(provider_id=f"prov_{idx}", name=f"Provider {idx}")
                rrm.register_provider(p)

                a = AgentResource(agent_id=f"agent_{idx}", name=f"Agent {idx}")
                rrm.register_agent(a)

                # Query
                rrm.list_providers()
                rrm.list_agents()
                rrm.check_health()
            except Exception as e:
                errors.append(e)

        for i in range(20):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(rrm.list_providers()), 20)
        self.assertEqual(len(rrm.list_agents()), 20)


if __name__ == "__main__":
    unittest.main()
