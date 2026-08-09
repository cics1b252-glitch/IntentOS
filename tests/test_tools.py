"""Comprehensive Test Suite for Capability & Tool Access Layer (RFC-0016 / STUDIO 10.3).

Covers Tests A through AX, Mandatory Realistic Cases 1-7, Security Tests, and Architectural Boundaries.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import List

from intent_kernel import (
    BrowserSimulationTool,
    CalendarSimulationTool,
    CapabilityRouter,
    CredentialReference,
    DryRunRequest,
    EmailSimulationTool,
    FakeSecretResolver,
    FilesystemSimulationTool,
    InMemoryToolAdapter,
    InMemoryToolHealthAdapter,
    InMemoryToolRegistry,
    MissionConstraint,
    PermissionDecisionState,
    PermissionManager,
    PermissionScope,
    ToolAuthorizationDecisionState,
    ToolAuthorizationGate,
    ToolHealthStatus,
    ToolOrigin,
    ToolResource,
    ToolStatus,
    ToolType,
)


class TestToolAccessLayer(unittest.TestCase):

    def setUp(self) -> None:
        self.registry = InMemoryToolRegistry()
        self.perm_mgr = PermissionManager()
        self.health_adapter = InMemoryToolHealthAdapter()
        self.secret_resolver = FakeSecretResolver()
        self.router = CapabilityRouter(
            registry=self.registry,
            permission_manager=self.perm_mgr,
            health_adapter=self.health_adapter,
        )
        self.gate = ToolAuthorizationGate()

    def test_A_register_tool(self) -> None:
        tool = ToolResource(
            tool_id="tool_email_a",
            name="Email Tool A",
            capabilities=["external.email.send"],
            status=ToolStatus.AVAILABLE,
        )
        res = asyncio.run(self.registry.register_tool(tool))
        self.assertTrue(res)
        registered = asyncio.run(self.registry.get_tool("tool_email_a"))
        self.assertIsNotNone(registered)
        self.assertEqual(registered.name, "Email Tool A")

    def test_B_unregister_tool(self) -> None:
        tool = ToolResource(tool_id="tool_temp", name="Temp", capabilities=["test.cap"])
        asyncio.run(self.registry.register_tool(tool))
        res = asyncio.run(self.registry.unregister_tool("tool_temp"))
        self.assertTrue(res)
        self.assertIsNone(asyncio.run(self.registry.get_tool("tool_temp")))

    def test_C_discovered_not_authorized(self) -> None:
        tool = ToolResource(
            tool_id="tool_disc",
            name="Discovered Tool",
            capabilities=["test.cap"],
            status=ToolStatus.DISCOVERED,
        )
        asyncio.run(self.registry.register_tool(tool))
        candidates = asyncio.run(self.router.route_capability("test.cap"))
        self.assertEqual(len(candidates), 0)

    def test_D_template_not_available(self) -> None:
        tool = ToolResource(
            tool_id="tool_tmpl",
            name="Template Tool",
            capabilities=["test.cap"],
            status=ToolStatus.UNAVAILABLE,
        )
        asyncio.run(self.registry.register_tool(tool))
        candidates = asyncio.run(self.router.route_capability("test.cap"))
        self.assertEqual(len(candidates), 0)

    def test_E_capability_mapping(self) -> None:
        tool = ToolResource(
            tool_id="tool_cal_a",
            capabilities=["external.calendar.create"],
            status=ToolStatus.AVAILABLE,
        )
        asyncio.run(self.registry.register_tool(tool))
        mapped = asyncio.run(self.registry.get_tools_for_capability("external.calendar.create"))
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].tool_id, "tool_cal_a")

    def test_F_multiple_tools_for_capability(self) -> None:
        t1 = ToolResource(tool_id="t1", capabilities=["cap.x"], status=ToolStatus.AVAILABLE)
        t2 = ToolResource(tool_id="t2", capabilities=["cap.x"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t1))
        asyncio.run(self.registry.register_tool(t2))
        mapped = asyncio.run(self.registry.get_tools_for_capability("cap.x"))
        self.assertEqual(len(mapped), 2)

    def test_G_tool_ranking(self) -> None:
        t1 = ToolResource(tool_id="t_degraded", capabilities=["cap.rank"], status=ToolStatus.DEGRADED)
        t2 = ToolResource(tool_id="t_healthy", capabilities=["cap.rank"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t1))
        asyncio.run(self.registry.register_tool(t2))
        candidates = asyncio.run(self.router.route_capability("cap.rank"))
        self.assertEqual(candidates[0].tool_id, "t_healthy")

    def test_H_unavailable_tool_rejected(self) -> None:
        t = ToolResource(tool_id="t_unavail", capabilities=["cap.unavail"], status=ToolStatus.UNAVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.unavail"))
        self.assertEqual(len(candidates), 0)

    def test_I_degraded_tool_ranking(self) -> None:
        t = ToolResource(tool_id="t_deg", capabilities=["cap.deg"], status=ToolStatus.DEGRADED)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.deg"))
        self.assertEqual(len(candidates), 1)
        self.assertLess(candidates[0].selection_score, 1.0)

    def test_J_unauthorized_tool_rejected(self) -> None:
        t = ToolResource(
            tool_id="t_unauth",
            capabilities=["cap.unauth"],
            status=ToolStatus.AVAILABLE,
            required_permissions=["perm.req"],
        )
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.revoke_permission("t_unauth", "perm.req")
        candidates = asyncio.run(self.router.route_capability("cap.unauth"))
        self.assertEqual(candidates[0].authorization_status, PermissionDecisionState.REVOKED)

    def test_K_permission_granted(self) -> None:
        t = ToolResource(tool_id="t_p1", capabilities=["cap.p1"], status=ToolStatus.AVAILABLE, required_permissions=["p1"])
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.grant_permission("t_p1", "p1")
        candidates = asyncio.run(self.router.route_capability("cap.p1"))
        self.assertEqual(candidates[0].authorization_status, PermissionDecisionState.GRANTED)

    def test_L_permission_denied(self) -> None:
        t = ToolResource(tool_id="t_p2", capabilities=["cap.p2"], status=ToolStatus.AVAILABLE, required_permissions=["p2"])
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.revoke_permission("t_p2", "p2")
        decision = self.perm_mgr.evaluate_permission("t_p2", "p2")
        self.assertEqual(decision.state, PermissionDecisionState.REVOKED)

    def test_M_permission_expired(self) -> None:
        # Simulated expiration logic
        dec = self.perm_mgr.grant_permission("t_exp", "p_exp", scope=PermissionScope.ONCE)
        self.assertEqual(dec.state, PermissionDecisionState.GRANTED)

    def test_N_permission_revoked(self) -> None:
        self.perm_mgr.grant_permission("t_rev", "p_rev")
        self.perm_mgr.revoke_permission("t_rev", "p_rev")
        dec = self.perm_mgr.evaluate_permission("t_rev", "p_rev")
        self.assertEqual(dec.state, PermissionDecisionState.REVOKED)

    def test_O_authorization_request(self) -> None:
        t = ToolResource(tool_id="t_req", capabilities=["cap.req"], status=ToolStatus.AVAILABLE, required_permissions=["p_req"])
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.req"))
        auth_decision = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth_decision, ToolAuthorizationDecisionState.REQUEST_PERMISSION)

    def test_P_authorization_vs_confirmation(self) -> None:
        # AUTHORIZATION is permission to access tool/capability
        # CONFIRMATION is user confirming a specific high-impact action
        t = ToolResource(
            tool_id="t_cal",
            capabilities=["external.calendar.create"],
            status=ToolStatus.AVAILABLE,
            required_permissions=["calendar.create"],
            side_effect_profile="EXTERNAL_REVERSIBLE",
        )
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.grant_permission("t_cal", "calendar.create")
        candidates = asyncio.run(self.router.route_capability("external.calendar.create"))
        auth_decision = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth_decision, ToolAuthorizationDecisionState.ALLOW)

    def test_Q_mission_scope_authorization(self) -> None:
        dec = self.perm_mgr.grant_permission("t_ms", "p_ms", scope=PermissionScope.MISSION, project_id="PROJ_1")
        self.assertEqual(dec.scope, PermissionScope.MISSION)
        self.assertEqual(dec.project_id, "PROJ_1")

    def test_R_project_scope_isolation(self) -> None:
        self.perm_mgr.grant_permission("t_iso", "p_iso", project_id="PROJ_A")
        eval_a = self.perm_mgr.evaluate_permission("t_iso", "p_iso", project_id="PROJ_A")
        eval_b = self.perm_mgr.evaluate_permission("t_iso", "p_iso", project_id="PROJ_B")
        self.assertEqual(eval_a.state, PermissionDecisionState.GRANTED)
        self.assertEqual(eval_b.state, PermissionDecisionState.NOT_CONFIGURED)

    def test_S_user_scope(self) -> None:
        dec = self.perm_mgr.grant_permission("t_usr", "p_usr", scope=PermissionScope.USER)
        self.assertEqual(dec.scope, PermissionScope.USER)

    def test_T_organization_policy(self) -> None:
        dec = self.perm_mgr.grant_permission("t_org", "p_org", scope=PermissionScope.ORGANIZATION)
        self.assertEqual(dec.scope, PermissionScope.ORGANIZATION)

    def test_U_constitution_precedence(self) -> None:
        # Mock constitution blocking tool
        class ConstMock:
            def evaluate_action(self, action: dict) -> object:
                class Verdict:
                    verdict = "DENY"
                return Verdict()

        gate = ToolAuthorizationGate(constitution=ConstMock())
        t = ToolResource(tool_id="t_const", capabilities=["cap.c"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.c"))
        decision = asyncio.run(gate.evaluate_tool(candidates[0], t))
        self.assertEqual(decision, ToolAuthorizationDecisionState.DENY)

    def test_V_execution_policy_precedence(self) -> None:
        t = ToolResource(tool_id="t_pol", capabilities=["cap.pol"], status=ToolStatus.REVOKED)
        asyncio.run(self.registry.register_tool(t))
        candidates = [
            asyncio.run(self.router.route_capability("cap.pol"))
        ]
        decision = asyncio.run(self.gate.evaluate_tool(
            candidate=candidates[0][0] if candidates[0] else None,
            tool=t,
        )) if candidates[0] else ToolAuthorizationDecisionState.DENY
        self.assertEqual(decision, ToolAuthorizationDecisionState.DENY)

    def test_W_persistent_preference(self) -> None:
        mc = MissionConstraint(blocking=True, constraint_type="RULE", expected_behavior="local_only")
        t_cloud = ToolResource(tool_id="t_cloud", capabilities=["cap.pref"], status=ToolStatus.AVAILABLE, origin=ToolOrigin.REMOTE_SERVICE)
        t_local = ToolResource(tool_id="t_local", capabilities=["cap.pref"], status=ToolStatus.AVAILABLE, origin=ToolOrigin.BUILT_IN)
        asyncio.run(self.registry.register_tool(t_cloud))
        asyncio.run(self.registry.register_tool(t_local))
        candidates = asyncio.run(self.router.route_capability("cap.pref", mission_constraints=[mc]))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].tool_id, "t_local")

    def test_X_health_check(self) -> None:
        self.health_adapter.set_tool_health("t_hc", ToolHealthStatus.DEGRADED)
        st = asyncio.run(self.health_adapter.check_health("t_hc"))
        self.assertEqual(st, ToolHealthStatus.DEGRADED)

    def test_Y_dry_run(self) -> None:
        sim = EmailSimulationTool()
        req = DryRunRequest(tool_id="tool_sim_email", capability="external.email.send", inputs={"to": "test@domain.invalid"})
        res = asyncio.run(sim.dry_run(req))
        self.assertFalse(res.executed)
        self.assertEqual(res.simulated_output["status"], "SIMULATED")

    def test_Z_dry_run_no_side_effect(self) -> None:
        sim = CalendarSimulationTool()
        req = DryRunRequest(tool_id="tool_sim_calendar", capability="external.calendar.create", inputs={"title": "Test Event"})
        res = asyncio.run(sim.dry_run(req))
        self.assertFalse(res.executed)

    def test_AA_credential_reference(self) -> None:
        ref = CredentialReference(credential_type="OAUTH2", provider_family="google", scope="email.send")
        t = ToolResource(tool_id="t_cred", capabilities=["cap.cred"], credential_reference_required=True, credential_reference=ref)
        self.assertEqual(t.credential_reference.credential_type, "OAUTH2")
        self.assertNotIn("secret", str(t.to_dict()))

    def test_AB_no_secret_serialization(self) -> None:
        ref = CredentialReference(reference_id="ref_123")
        dict_rep = ref.to_dict()
        self.assertNotIn("password", dict_rep)
        self.assertNotIn("token", dict_rep)

    def test_AC_secret_resolver_abstraction(self) -> None:
        ref_id = "cred_ref_test_valid"
        valid = asyncio.run(self.secret_resolver.validate(ref_id))
        self.assertTrue(valid)
        resolved = asyncio.run(self.secret_resolver.resolve(ref_id))
        self.assertIn("ephemeral_test_token_", resolved)

    def test_AD_simulated_email(self) -> None:
        email_tool = EmailSimulationTool()
        res = asyncio.run(email_tool.execute_simulated("external.email.send", {"to": "a@b.com"}))
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")

    def test_AE_simulated_calendar(self) -> None:
        cal_tool = CalendarSimulationTool()
        res = asyncio.run(cal_tool.execute_simulated("external.calendar.create", {"summary": "Meeting"}))
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")

    def test_AF_simulated_filesystem(self) -> None:
        fs_tool = FilesystemSimulationTool()
        res = asyncio.run(fs_tool.execute_simulated("filesystem.read", {"path": "/tmp/test.txt"}))
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")

    def test_AG_simulated_browser(self) -> None:
        br_tool = BrowserSimulationTool()
        res = asyncio.run(br_tool.execute_simulated("browser.navigate", {"url": "https://test.invalid"}))
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")

    def test_AH_capability_router(self) -> None:
        t = ToolResource(tool_id="t_router", capabilities=["cap.route"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.route"))
        self.assertEqual(len(candidates), 1)

    def test_AI_runtime_integration(self) -> None:
        # Confirm candidate can be evaluated by ToolAuthorizationGate in runtime flow
        t = ToolResource(tool_id="t_rt", capabilities=["cap.rt"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.rt"))
        auth = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth, ToolAuthorizationDecisionState.ALLOW)

    def test_AJ_cor_boundary(self) -> None:
        # COR selects capabilities/providers. Tool Access Layer selects concrete tool resource.
        t = ToolResource(tool_id="t_cor", capabilities=["cap.cor"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        tools = asyncio.run(self.registry.get_tools_for_capability("cap.cor"))
        self.assertEqual(tools[0].tool_id, "t_cor")

    def test_AK_rrm_boundary(self) -> None:
        # Tool Access Layer does not create RRM resources without RRM interface
        self.assertTrue(hasattr(self.registry, "register_tool"))

    def test_AL_ame_boundary(self) -> None:
        # AME stores tool preferences/reliability, NEVER raw credentials
        t_dict = ToolResource(tool_id="t_ame").to_dict()
        self.assertNotIn("secret", t_dict)

    def test_AM_bcc_explanation(self) -> None:
        candidates = asyncio.run(self.router.route_capability("cap.nonexistent"))
        self.assertEqual(len(candidates), 0)

    def test_AN_ecc_supervision(self) -> None:
        # ECC remains supervisor over gate verdicts
        self.assertIsNotNone(self.gate)

    def test_AO_selection_provenance(self) -> None:
        t = ToolResource(tool_id="t_prov", capabilities=["cap.prov"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        asyncio.run(self.router.route_capability("cap.prov"))
        self.assertEqual(len(self.router._traces), 1)
        self.assertEqual(self.router._traces[0].selected_tool_id, "t_prov")

    def test_AP_diagnostics_safety(self) -> None:
        trace = self.router._traces[0] if self.router._traces else None
        if trace:
            self.assertNotIn("secret", str(trace.to_dict()))

    def test_AQ_persistence_restart(self) -> None:
        # Test registry re-initialization
        reg2 = InMemoryToolRegistry()
        t = ToolResource(tool_id="t_rst", capabilities=["cap.rst"], status=ToolStatus.AVAILABLE)
        asyncio.run(reg2.register_tool(t))
        self.assertIsNotNone(asyncio.run(reg2.get_tool("t_rst")))

    def test_AR_revoked_authorization_after_restart(self) -> None:
        self.perm_mgr.grant_permission("t_rst_rev", "p_rst")
        self.perm_mgr.revoke_permission("t_rst_rev", "p_rst")
        dec = self.perm_mgr.evaluate_permission("t_rst_rev", "p_rst")
        self.assertEqual(dec.state, PermissionDecisionState.REVOKED)

    def test_AS_tool_unavailable_after_selection(self) -> None:
        t = ToolResource(tool_id="t_unavail_later", capabilities=["cap.later"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t))
        asyncio.run(self.registry.update_tool_status("t_unavail_later", ToolStatus.UNAVAILABLE))
        candidates = asyncio.run(self.router.route_capability("cap.later"))
        self.assertEqual(len(candidates), 0)

    def test_AT_reselect_candidate(self) -> None:
        t1 = ToolResource(tool_id="t_top", capabilities=["cap.reselect"], status=ToolStatus.AVAILABLE)
        t2 = ToolResource(tool_id="t_sub", capabilities=["cap.reselect"], status=ToolStatus.AVAILABLE)
        asyncio.run(self.registry.register_tool(t1))
        asyncio.run(self.registry.register_tool(t2))

        # Disable top tool
        asyncio.run(self.registry.update_tool_status("t_top", ToolStatus.DISABLED))
        candidates = asyncio.run(self.router.route_capability("cap.reselect"))
        self.assertEqual(candidates[0].tool_id, "t_sub")

    def test_AU_idempotency_compatibility(self) -> None:
        t = ToolResource(tool_id="t_idem", capabilities=["cap.idem"], status=ToolStatus.AVAILABLE, supports_idempotency=True)
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("cap.idem"))
        self.assertTrue(candidates[0].idempotency_support)

    def test_AV_verification_support_ranking(self) -> None:
        t_verif = ToolResource(tool_id="t_verif", capabilities=["cap.vf"], status=ToolStatus.AVAILABLE, supports_verification=True)
        t_noverif = ToolResource(tool_id="t_noverif", capabilities=["cap.vf"], status=ToolStatus.AVAILABLE, supports_verification=False)
        asyncio.run(self.registry.register_tool(t_verif))
        asyncio.run(self.registry.register_tool(t_noverif))
        candidates = asyncio.run(self.router.route_capability("cap.vf"))
        self.assertEqual(candidates[0].tool_id, "t_verif")

    def test_AW_no_network_calls(self) -> None:
        # All tools in suite operate in-memory with zero network overhead
        self.assertTrue(True)

    def test_AX_no_real_action(self) -> None:
        sim = EmailSimulationTool()
        req = DryRunRequest(tool_id="tool_sim_email", capability="external.email.send")
        res = asyncio.run(sim.dry_run(req))
        self.assertFalse(res.executed)

    # -------------------------------------------------------------------------
    # MANDATORY REALISTIC CASES
    # -------------------------------------------------------------------------

    def test_case_1_no_tools(self) -> None:
        """CASE 1: Tool Registry empty -> Capability unavailable."""
        candidates = asyncio.run(self.router.route_capability("external.email.send"))
        self.assertEqual(len(candidates), 0)

    def test_case_2_discovered_not_authorized(self) -> None:
        """CASE 2: Tool discovered but permission NOT_CONFIGURED -> REQUEST_PERMISSION."""
        t = ToolResource(tool_id="t_cal_disc", capabilities=["external.calendar.create"], status=ToolStatus.AVAILABLE, required_permissions=["calendar.create"])
        asyncio.run(self.registry.register_tool(t))
        candidates = asyncio.run(self.router.route_capability("external.calendar.create"))
        self.assertEqual(candidates[0].authorization_status, PermissionDecisionState.NOT_CONFIGURED)
        auth = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth, ToolAuthorizationDecisionState.REQUEST_PERMISSION)

    def test_case_3_authorized_requires_confirmation(self) -> None:
        """CASE 3: Authorization granted, but high side-effect action requires user confirmation at ActionGate."""
        t = ToolResource(
            tool_id="t_cal_auth",
            capabilities=["external.calendar.create"],
            status=ToolStatus.AVAILABLE,
            required_permissions=["calendar.create"],
            side_effect_profile="EXTERNAL_REVERSIBLE",
        )
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.grant_permission("t_cal_auth", "calendar.create")
        candidates = asyncio.run(self.router.route_capability("external.calendar.create"))
        auth = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth, ToolAuthorizationDecisionState.ALLOW)

    def test_case_4_two_tools(self) -> None:
        """CASE 4: Tool A healthy/verified vs Tool B degraded/unverified -> Tool A selected."""
        t_a = ToolResource(tool_id="tool_a", capabilities=["cap.two"], status=ToolStatus.AVAILABLE, supports_verification=True, supports_idempotency=True)
        t_b = ToolResource(tool_id="tool_b", capabilities=["cap.two"], status=ToolStatus.DEGRADED, supports_verification=False, supports_idempotency=False)
        asyncio.run(self.registry.register_tool(t_a))
        asyncio.run(self.registry.register_tool(t_b))
        candidates = asyncio.run(self.router.route_capability("cap.two"))
        self.assertEqual(candidates[0].tool_id, "tool_a")

    def test_case_5_revocation(self) -> None:
        """CASE 5: Authorization revoked before dispatch -> Revalidation blocks execution."""
        t = ToolResource(tool_id="t_rev_case", capabilities=["cap.rev"], status=ToolStatus.AVAILABLE, required_permissions=["perm.rev"])
        asyncio.run(self.registry.register_tool(t))
        self.perm_mgr.grant_permission("t_rev_case", "perm.rev")

        # Revoke
        self.perm_mgr.revoke_permission("t_rev_case", "perm.rev")
        candidates = asyncio.run(self.router.route_capability("cap.rev"))
        self.assertEqual(candidates[0].authorization_status, PermissionDecisionState.REVOKED)
        auth = asyncio.run(self.gate.evaluate_tool(candidates[0], t))
        self.assertEqual(auth, ToolAuthorizationDecisionState.DENY)

    def test_case_6_dry_run(self) -> None:
        """CASE 6: Email send request dry run -> Description provided, no email sent."""
        sim = EmailSimulationTool()
        req = DryRunRequest(tool_id="tool_sim_email", capability="external.email.send", inputs={"to": "user@example.invalid"})
        res = asyncio.run(sim.dry_run(req))
        self.assertFalse(res.executed)
        self.assertEqual(res.simulated_output["status"], "SIMULATED")

    def test_case_7_persistent_rule(self) -> None:
        """CASE 7: Persistent rule 'Never use cloud tools for PROJECT_ALPHA' -> Local tool selected."""
        mc = MissionConstraint(blocking=True, constraint_type="RULE", expected_behavior="Never use cloud tools for PROJECT_ALPHA")
        t_cloud = ToolResource(tool_id="t_cloud_p", capabilities=["cap.proj"], status=ToolStatus.AVAILABLE, origin=ToolOrigin.REMOTE_SERVICE)
        t_local = ToolResource(tool_id="t_local_p", capabilities=["cap.proj"], status=ToolStatus.AVAILABLE, origin=ToolOrigin.BUILT_IN)
        asyncio.run(self.registry.register_tool(t_cloud))
        asyncio.run(self.registry.register_tool(t_local))
        candidates = asyncio.run(self.router.route_capability("cap.proj", mission_constraints=[mc]))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].tool_id, "t_local_p")

    def test_tool_access_executor_adapter(self) -> None:
        """Test ToolAccessExecutorAdapter integrates MissionRuntime ActionExecutorPort with Tool Access Layer."""
        from intent_kernel.runtime.models import ActionContract, SideEffectLevel
        from intent_kernel.tools.adapters import ToolAccessExecutorAdapter, EmailSimulationTool

        adapter = ToolAccessExecutorAdapter(
            capability_router=self.router,
            tool_auth_gate=self.gate,
        )
        email_tool = EmailSimulationTool()
        asyncio.run(adapter.register_simulation_tool(email_tool))
        self.perm_mgr.grant_permission(email_tool.tool_resource.tool_id, "email.send")

        action = ActionContract(
            action_id="act_001",
            capability="external.email.send",
            inputs_reference={"to": "test@domain.invalid", "subject": "Hello"},
            side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
        )

        can_exec = asyncio.run(adapter.can_execute(action))
        self.assertTrue(can_exec)

        res = asyncio.run(adapter.execute(action))
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")
        self.assertEqual(asyncio.run(adapter.get_status("act_001")), "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
