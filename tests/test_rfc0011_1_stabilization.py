"""Unit tests for RFC-0011.1 — Architecture Stabilization.

Validates ExecutiveQualityPolicy, ExecutiveExecutionPolicy, ExecutionEnvironment,
DecisionTable precedence, COR environment routing, and ECC integration.
"""

import unittest
from intent_kernel.ecc import (
    ExecutiveCognitiveController,
    ExecutiveQualityPolicy,
    ExecutiveExecutionPolicy,
    ExecutiveDecisionRule,
    ExecutiveDecisionTable,
    ExecutiveAction,
    CognitiveState,
    QualityGates,
    PolicyProvenance,
)
from intent_kernel.cor import (
    CapabilityOrchestrator,
    RegistryCatalog,
    ExecutionEnvironment,
    ExecutionEnvironmentType,
    NodeAssignment,
)
from intent_kernel.cpe import ExecutionPlan, PlanStep


class TestRFC0011_1Stabilization(unittest.TestCase):
    def test_executive_quality_policy_defaults_and_risk_profiles(self):
        pol_std = ExecutiveQualityPolicy.from_risk_profile("standard")
        self.assertEqual(pol_std.profile_id, "standard")
        self.assertEqual(pol_std.risk_profile, "standard")
        self.assertEqual(pol_std.min_iqi, 0.60)
        self.assertEqual(pol_std.min_pqi, 0.60)
        self.assertEqual(pol_std.max_planning_iterations, 2)
        self.assertEqual(pol_std.max_replans, 2)
        self.assertEqual(pol_std.provenance, PolicyProvenance.SYSTEM_DEFAULT)

        pol_high = ExecutiveQualityPolicy.from_risk_profile("high_risk")
        self.assertEqual(pol_high.profile_id, "high_risk")
        self.assertEqual(pol_high.min_iqi, 0.75)
        self.assertEqual(pol_high.min_pqi, 0.75)

        pol_crit = ExecutiveQualityPolicy.from_risk_profile("critical")
        self.assertEqual(pol_crit.profile_id, "critical")
        self.assertEqual(pol_crit.min_iqi, 0.85)

        pol_low = ExecutiveQualityPolicy.from_risk_profile("low_risk")
        self.assertEqual(pol_low.profile_id, "low_risk")
        self.assertEqual(pol_low.min_iqi, 0.40)

    def test_executive_execution_policy_defaults_and_presets(self):
        exec_def = ExecutiveExecutionPolicy.from_preset("default")
        self.assertEqual(exec_def.policy_id, "default_execution_policy")
        self.assertEqual(exec_def.max_cost, 1.0)
        self.assertEqual(exec_def.max_latency, 60.0)
        self.assertTrue(exec_def.internet_allowed)
        self.assertTrue(exec_def.cloud_execution_allowed)
        self.assertFalse(exec_def.offline_required)

        exec_off = ExecutiveExecutionPolicy.from_preset("offline_only")
        self.assertTrue(exec_off.offline_required)
        self.assertFalse(exec_off.internet_allowed)
        self.assertFalse(exec_off.cloud_execution_allowed)
        self.assertEqual(exec_off.provenance, PolicyProvenance.ENVIRONMENT_POLICY)

        exec_priv = ExecutiveExecutionPolicy.from_preset("high_privacy")
        self.assertEqual(exec_priv.privacy_requirements, "high")
        self.assertFalse(exec_priv.cloud_execution_allowed)

    def test_execution_environment_registration_and_catalog(self):
        catalog = RegistryCatalog(populate_defaults=True)
        envs = catalog.list_environments()
        self.assertGreaterEqual(len(envs), 4)

        env_ids = [e.environment_id for e in envs]
        self.assertIn("env_local_process", env_ids)
        self.assertIn("env_desktop_host", env_ids)
        self.assertIn("env_cloud_server", env_ids)
        self.assertIn("env_remote_edge", env_ids)

        custom_env = ExecutionEnvironment(
            environment_id="env_custom_sandbox",
            type=ExecutionEnvironmentType.LOCAL_PROCESS,
            network_access=False,
            capabilities=["synthesis.recommendation", "sandbox.isolated"],
        )
        catalog.register_environment(custom_env)
        retrieved = catalog.get_environment("env_custom_sandbox")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.environment_id, "env_custom_sandbox")

    def test_cor_environment_routing_and_ranking(self):
        cor = CapabilityOrchestrator()
        step = PlanStep(
            step_id="step_1",
            objective="Process data locally",
            action_type="transform",
            required_capabilities=["synthesis.recommendation"],
        )
        plan = ExecutionPlan(
            plan_id="plan_1",
            intent_id="intent_1",
            goal="Process data",
            steps=[step],
        )

        # Standard orchestration
        graph = cor.orchestrate(plan)
        self.assertEqual(graph.status, "ready")
        self.assertIn("step_1", graph.assignments)

        assignment = graph.assignments["step_1"]
        self.assertTrue(hasattr(assignment, "environment_id"))
        self.assertTrue(hasattr(assignment, "environment_type"))
        self.assertNotEqual(assignment.environment_id, "unassigned")
        self.assertGreater(len(assignment.environment_candidates), 0)

        # Restrictive orchestration (offline only)
        graph_offline = cor.orchestrate(
            plan,
            constraints={
                "offline_required": True,
                "cloud_execution_allowed": False,
            },
        )
        assignment_off = graph_offline.assignments["step_1"]
        self.assertIn(assignment_off.environment_type, ["local_process", "desktop", "edge"])

    def test_executive_decision_table_precedence(self):
        dt = ExecutiveDecisionTable()
        
        # Test Tier 1 (Constitution) priority over lower tiers
        ctx_const = {
            "constitution_denied": True,
            "constitution_reason": "Princípio ético violado",
            "iqi_failed": True,
            "current_state": CognitiveState.UNDERSTANDING,
        }
        dec_const = dt.evaluate(ctx_const)
        self.assertIsNotNone(dec_const)
        self.assertEqual(dec_const.action, ExecutiveAction.BLOCK)
        self.assertIn("Bloqueio Constitucional", dec_const.reason)

        # Test Tier 2 (ExecutionPolicy) over QualityPolicy
        ctx_exec = {
            "block_execution": True,
            "iqi_failed": True,
            "current_state": CognitiveState.RECEIVED,
        }
        dec_exec = dt.evaluate(ctx_exec)
        self.assertIsNotNone(dec_exec)
        self.assertEqual(dec_exec.action, ExecutiveAction.BLOCK)
        self.assertIn("Execução desabilitada", dec_exec.reason)

        # Test Tier 4 (QualityPolicy)
        ctx_qual = {
            "iqi_failed": True,
            "iqi_reason": "IQI baixo (0.35)",
            "current_state": CognitiveState.UNDERSTANDING,
        }
        dec_qual = dt.evaluate(ctx_qual)
        self.assertIsNotNone(dec_qual)
        self.assertEqual(dec_qual.action, ExecutiveAction.ASK_USER)
        self.assertIn("IQI baixo", dec_qual.reason)

    def test_quality_gates_with_quality_and_execution_policies(self):
        q_pol = ExecutiveQualityPolicy.from_risk_profile("standard")
        e_pol = ExecutiveExecutionPolicy.from_preset("default", max_cost=0.5)

        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test step", action_type="synthesize", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Goal", steps=[step])
        graph = cor.orchestrate(plan)

        # Normal cost
        ok, msg = QualityGates.evaluate_cor(graph, policy=q_pol, execution_policy=e_pol)
        self.assertTrue(ok)

        # Exceed cost
        e_pol_strict = ExecutiveExecutionPolicy.from_preset("default", max_cost=0.000001)
        ok_strict, msg_strict = QualityGates.evaluate_cor(graph, policy=q_pol, execution_policy=e_pol_strict)
        self.assertFalse(ok_strict)
        self.assertIn("excede o limite estipulado", msg_strict)

    def test_ecc_process_intent_end_to_end_with_rfc0011_1(self):
        ecc = ExecutiveCognitiveController()
        q_pol = ExecutiveQualityPolicy.from_risk_profile("standard")
        e_pol = ExecutiveExecutionPolicy.from_preset("default")

        result = ecc.process_intent(
            text="Analisar relatórios financeiros",
            quality_policy=q_pol,
            execution_policy=e_pol,
        )

        self.assertEqual(result.current_state, CognitiveState.READY_FOR_EXECUTION)
        self.assertEqual(result.final_action, ExecutiveAction.CONTINUE)
        self.assertIsNotNone(result.execution_graph)

        # Verify environment selection in assignments
        assignments = result.execution_graph.get("assignments", {})
        self.assertGreater(len(assignments), 0)
        first_assign = next(iter(assignments.values()))
        self.assertIn("environment_id", first_assign)
        self.assertIn("environment_type", first_assign)

    def test_empty_registry_environment_behavior(self):
        """A. Empty Registry -> 0 environments -> no fictitious environments -> assignment blocked."""
        empty_catalog = RegistryCatalog(populate_defaults=False)
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        graph = cor.orchestrate(plan, registry=empty_catalog)
        self.assertIn("step_1", graph.assignments)
        assignment = graph.assignments["step_1"]

        self.assertEqual(len(assignment.environment_candidates), 0)
        self.assertEqual(assignment.status, "blocked")
        self.assertEqual(assignment.reasoning, "no_execution_environment_available")
        self.assertEqual(assignment.environment_id, "unassigned")

    def test_explicit_local_environment(self):
        """B. Explicitly registered local environment can be considered."""
        catalog = RegistryCatalog(populate_defaults=False)
        catalog.register_environment(
            ExecutionEnvironment(
                environment_id="env_local_custom",
                type=ExecutionEnvironmentType.LOCAL_PROCESS,
                network_access=False,
                capabilities=["synthesis.recommendation"],
            )
        )
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        graph = cor.orchestrate(plan, registry=catalog)
        assignment = graph.assignments["step_1"]
        self.assertEqual(len(assignment.environment_candidates), 1)
        self.assertEqual(assignment.environment_id, "env_local_custom")

    def test_explicit_cloud_environment_per_policy(self):
        """C. Explicitly registered cloud environment considered per ExecutionPolicy."""
        catalog = RegistryCatalog(populate_defaults=False)
        catalog.register_environment(
            ExecutionEnvironment(
                environment_id="env_cloud_custom",
                type=ExecutionEnvironmentType.CLOUD,
                network_access=True,
                capabilities=["synthesis.recommendation"],
            )
        )
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        # Cloud allowed
        graph = cor.orchestrate(plan, registry=catalog, constraints={"cloud_execution_allowed": True})
        self.assertEqual(graph.assignments["step_1"].environment_id, "env_cloud_custom")

    def test_offline_required_with_no_offline_environment(self):
        """D. offline_required + no offline environment -> blocked."""
        catalog = RegistryCatalog(populate_defaults=False)
        catalog.register_environment(
            ExecutionEnvironment(
                environment_id="env_cloud_online",
                type=ExecutionEnvironmentType.CLOUD,
                network_access=True,
                capabilities=["synthesis.recommendation"],
            )
        )
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        graph = cor.orchestrate(plan, registry=catalog, constraints={"offline_required": True})
        assignment = graph.assignments["step_1"]
        self.assertEqual(assignment.status, "blocked")
        self.assertEqual(assignment.reasoning, "no_execution_environment_available")

    def test_cloud_forbidden_with_only_cloud_available(self):
        """E. cloud_execution_allowed=False + only cloud available -> blocked."""
        catalog = RegistryCatalog(populate_defaults=False)
        catalog.register_environment(
            ExecutionEnvironment(
                environment_id="env_cloud_only",
                type=ExecutionEnvironmentType.CLOUD,
                network_access=True,
                capabilities=["synthesis.recommendation"],
            )
        )
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        graph = cor.orchestrate(plan, registry=catalog, constraints={"cloud_execution_allowed": False})
        assignment = graph.assignments["step_1"]
        self.assertEqual(assignment.status, "blocked")
        self.assertEqual(assignment.reasoning, "no_execution_environment_available")

    def test_environment_status_unavailable_not_selected(self):
        """F. Environment with status != active -> not selected."""
        catalog = RegistryCatalog(populate_defaults=False)
        catalog.register_environment(
            ExecutionEnvironment(
                environment_id="env_disabled",
                type=ExecutionEnvironmentType.LOCAL_PROCESS,
                status="inactive",
                network_access=False,
                capabilities=["synthesis.recommendation"],
            )
        )
        cor = CapabilityOrchestrator()
        step = PlanStep(step_id="step_1", objective="Test", action_type="test", required_capabilities=["synthesis.recommendation"])
        plan = ExecutionPlan(plan_id="p1", intent_id="i1", goal="Test", steps=[step])

        graph = cor.orchestrate(plan, registry=catalog)
        assignment = graph.assignments["step_1"]
        self.assertEqual(assignment.status, "blocked")
        self.assertEqual(assignment.reasoning, "no_execution_environment_available")


if __name__ == "__main__":
    unittest.main()
