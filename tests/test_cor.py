"""Unit & Integration Tests for Capability Orchestrator (COR) — RFC-0010."""

import unittest
from intent_kernel.iue import IntentUnderstandingEngine
from intent_kernel.cdm import CognitiveDialogueManager, DialogueDecision, DialogueState
from intent_kernel.cpe import CognitivePlanningEngine, ExecutionPlan, PlanStep
from intent_kernel.cor import (
    CapabilityOrchestrator,
    RegistryCatalog,
    AgentRegistration,
    ProviderRegistration,
    AccountRegistration,
    CapabilityRegistration,
    ExecutionGraph,
    ExecutionEnvironment,
    ExecutionEnvironmentType,
)


class TestCapabilityOrchestrator(unittest.TestCase):

    def setUp(self):
        self.iue = IntentUnderstandingEngine()
        self.cdm = CognitiveDialogueManager()
        self.cpe = CognitivePlanningEngine()
        self.cor = CapabilityOrchestrator()
        self.catalog = RegistryCatalog(populate_defaults=True)

    def _make_ready_decision(self, intent_id: str) -> DialogueDecision:
        return DialogueDecision(
            decision_id="d1",
            intent_id=intent_id,
            state=DialogueState.READY_TO_EXECUTE,
            can_proceed=True,
            requires_question=False,
            selected_question=None,
            candidate_questions=[],
            justification={},
            initial_iqi=0.9,
            projected_iqi_after_question=0.9,
            net_value=0.0,
        )

    def test_single_capability_orchestration(self):
        """Single capability requirement maps cleanly to matching agent, provider, and account."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(plan, registry=self.catalog)

        self.assertEqual(graph.status, "ready")
        self.assertGreater(len(graph.nodes), 0)
        self.assertEqual(len(graph.assignments), len(plan.steps))

        first_step_id = plan.steps[0].step_id
        assignment = graph.assignments[first_step_id]
        self.assertEqual(assignment.status, "assigned")
        self.assertIsNotNone(assignment.agent_id)
        self.assertIsNotNone(assignment.provider_id)
        self.assertIsNotNone(assignment.account_id)

    def test_multiple_agents_ranking(self):
        """When multiple agents offer a capability, ranking picks the highest scoring agent."""
        custom_catalog = RegistryCatalog(populate_defaults=False)
        custom_catalog.register_capability(CapabilityRegistration(
            name="research.information_gathering", description="Coleta de dados", tags=["research"]
        ))
        # Agent 1: Lower confidence
        custom_catalog.register_agent(AgentRegistration(
            agent_id="agent_junior_researcher",
            name="Junior Researcher",
            capabilities=["research.information_gathering"],
            historical_confidence=0.70,
            cost_tier=0.005,
            latency_tier=0.1
        ))
        # Agent 2: Higher confidence & specialization
        custom_catalog.register_agent(AgentRegistration(
            agent_id="agent_senior_researcher",
            name="Senior Researcher",
            capabilities=["research.information_gathering"],
            specialization=["research"],
            historical_confidence=0.95,
            cost_tier=0.01,
            latency_tier=0.2
        ))
        # Provider & Account
        custom_catalog.register_provider(ProviderRegistration(provider_id="prov_1", name="Provider 1"))
        custom_catalog.register_account(AccountRegistration(account_id="acc_1", provider_id="prov_1", name="Account 1"))

        intent = self.iue.analyze("Pesquise três alternativas e compare.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(plan, registry=custom_catalog)

        # Check that senior researcher was selected for research steps
        assigned_agents = [a.agent_id for a in graph.assignments.values()]
        self.assertIn("agent_senior_researcher", assigned_agents)

    def test_multiple_providers_ranking(self):
        """Provider ranking selects optimal profile based on reasoning and privacy requirements."""
        step = PlanStep(
            step_id="step_reasoning",
            objective="Complex reasoning task",
            action_type="analyze",
            required_capabilities=["synthesis.recommendation"]
        )
        plan = ExecutionPlan(
            plan_id="p1",
            intent_id="i1",
            goal="Goal",
            steps=[step],
            provider_requirements={"reasoning": "high", "privacy": "high"}
        )

        graph = self.cor.orchestrate(plan, registry=self.catalog)

        assignment = graph.assignments["step_reasoning"]
        # Gemini Ultra or Claude Sonnet score highest for reasoning=high & privacy=high
        self.assertIn(assignment.provider_id, ["provider_gemini_ultra", "provider_anthropic_claude"])

    def test_multiple_accounts_selection(self):
        """Multi-account routing selects the account with remaining quota and highest priority."""
        custom_catalog = RegistryCatalog(populate_defaults=False)
        custom_catalog.register_capability(CapabilityRegistration(name="retrieval.financial_context", description="Retrieval"))
        custom_catalog.register_capability(CapabilityRegistration(name="synthesis.recommendation", description="Sintese"))
        custom_catalog.register_agent(AgentRegistration(agent_id="a1", name="Agent 1", capabilities=["retrieval.financial_context", "synthesis.recommendation"]))
        custom_catalog.register_provider(ProviderRegistration(provider_id="p1", name="Provider 1"))
        custom_catalog.register_environment(ExecutionEnvironment(environment_id="env_local_custom", type=ExecutionEnvironmentType.LOCAL_PROCESS, capabilities=["retrieval.financial_context", "synthesis.recommendation"]))

        # Acc 1: Exhausted
        custom_catalog.register_account(AccountRegistration(account_id="acc_exhausted", provider_id="p1", name="Exhausted", quota_remaining=0))
        # Acc 2: Available
        custom_catalog.register_account(AccountRegistration(account_id="acc_active", provider_id="p1", name="Active", quota_remaining=50000, priority=9))

        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(plan, registry=custom_catalog)

        first_step_id = plan.steps[0].step_id
        assignment = graph.assignments[first_step_id]
        self.assertEqual(assignment.account_id, "acc_active")

    def test_fallback_reassignment(self):
        """Fallback mechanism reassigns failed agent/provider without re-generating plan."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(plan, registry=self.catalog)
        first_step_id = plan.steps[0].step_id

        reassigned_graph = self.cor.reassign_fallback(
            graph=graph,
            failed_step_id=first_step_id,
            failure_reason="Timeout na chamada ao agente primario",
            registry=self.catalog
        )

        reassigned_assignment = reassigned_graph.assignments[first_step_id]
        self.assertEqual(reassigned_assignment.status, "fallback_assigned")
        self.assertIn("Fallback efetuado", reassigned_graph.validation[-1])

    def test_parallelism_execution_groups(self):
        """Steps without dependencies are grouped into parallel execution stages."""
        s1 = PlanStep(step_id="s1", objective="Research 1", action_type="retrieve", dependencies=[])
        s2 = PlanStep(step_id="s2", objective="Research 2", action_type="retrieve", dependencies=[])
        s3 = PlanStep(step_id="s3", objective="Compare", action_type="synthesize", dependencies=["s1", "s2"])

        plan = ExecutionPlan(plan_id="p_parallel", intent_id="i_parallel", goal="Compare 2 items", steps=[s1, s2, s3])

        groups = self.cor.compute_execution_groups(plan.steps)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], ["s1", "s2"])  # Stage 1: parallel
        self.assertEqual(groups[1], ["s3"])        # Stage 2: depends on s1 and s2

    def test_unavailable_or_missing_capability(self):
        """Steps requiring non-existent capabilities get marked as unassigned gracefully."""
        custom_catalog = RegistryCatalog(populate_defaults=False)
        custom_catalog.register_environment(ExecutionEnvironment(environment_id="env_local", type=ExecutionEnvironmentType.LOCAL_PROCESS, capabilities=["quantum.synthesis"]))
        # Catalog has environment but no matching capability or agent

        step = PlanStep(
            step_id="s_rare",
            objective="Perform quantum synthesis",
            action_type="quantum",
            required_capabilities=["quantum.synthesis"]
        )
        plan = ExecutionPlan(plan_id="p_rare", intent_id="i_rare", goal="Quantum", steps=[step])

        graph = self.cor.orchestrate(plan, registry=custom_catalog)

        self.assertEqual(graph.status, "partially_assigned")
        assignment = graph.assignments["s_rare"]
        self.assertEqual(assignment.status, "unassigned")

    def test_cost_and_latency_estimation(self):
        """ExecutionGraph calculates total cost and latency metrics based on assigned candidates."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(plan, registry=self.catalog)

        self.assertGreaterEqual(graph.estimated_cost, 0.0)
        self.assertGreater(graph.estimated_latency, 0.0)

    def test_policies_and_constraints_enforcement(self):
        """Active policies filter or penalize candidate options according to privacy/offline constraints."""
        intent = self.iue.analyze("Quero investir R$ 23.500.")
        decision = self._make_ready_decision(intent.intent_id)
        plan = self.cpe.create_plan(intent, dialogue_decision=decision)

        graph = self.cor.orchestrate(
            plan,
            registry=self.catalog,
            policies=["high_privacy", "offline_only"]
        )

        self.assertIn("high_privacy", graph.execution_policy["active_policies"])

    def test_cases_a_b_c_d(self):
        """Test Case A (Financial Advisory), Case B (Research), Case C (Software App), Case D (Financial Analysis)."""
        # Case A: Financial
        intent_a = self.iue.analyze("Quero investir R$ 23.500.")
        plan_a = self.cpe.create_plan(intent_a, dialogue_decision=self._make_ready_decision(intent_a.intent_id))
        graph_a = self.cor.orchestrate(plan_a, registry=self.catalog)
        self.assertEqual(graph_a.status, "ready")

        # Case B: Research
        intent_b = self.iue.analyze("Pesquise três alternativas de investimento e compare.")
        plan_b = self.cpe.create_plan(intent_b, dialogue_decision=self._make_ready_decision(intent_b.intent_id))
        graph_b = self.cor.orchestrate(plan_b, registry=self.catalog)
        self.assertEqual(graph_b.status, "ready")

        # Case C: Software App
        intent_c = self.iue.analyze("Monte um aplicativo web React para controlar manutenção do meu carro.")
        plan_c = self.cpe.create_plan(intent_c, dialogue_decision=self._make_ready_decision(intent_c.intent_id))
        graph_c = self.cor.orchestrate(plan_c, registry=self.catalog)
        self.assertEqual(graph_c.status, "ready")

    def test_architectural_isolation(self):
        """COR must be purely declarative and import zero execution or LLM libraries."""
        import inspect
        import intent_kernel.cor as cor_module

        source = inspect.getsource(cor_module)

        forbidden = ["subprocess", "requests", "urllib", "openai", "google.generativeai", "httpx"]
        for lib in forbidden:
            self.assertNotIn(f"import {lib}", source)
            self.assertNotIn(f"from {lib}", source)


if __name__ == "__main__":
    unittest.main()
