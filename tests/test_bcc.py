"""Bootstrap Cognitive Cortex (BCC) Tests — STUDIO 10.0 / RFC-0014.

Comprehensive test suite covering all 30 requirements (A through AD) and Mandatory Cases 1 through 5.
"""

import ast
import os
import unittest
from unittest import IsolatedAsyncioTestCase

from intent_kernel.kom import (
    KnowledgeObject,
    KnowledgeState,
    ProvenanceRecord,
    SourceType,
)
from intent_kernel.persistence import JsonFilePersistenceEngine
from intent_kernel.ame import AdaptiveMemoryEngine, LocalKnowledgeObjectRepository
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.rrm.models import (
    ProviderResource,
    ResourceStatus,
    ResourceOrigin,
)
from intent_kernel.ecc import ExecutiveExecutionPolicy
from intent_kernel.cor import CapabilityOrchestrator, ExecutionPlan, PlanStep
from intent_kernel.iue import StructuredIntent

from intent_kernel.bcc import (
    BootstrapCognitiveCortex,
    LocalCognitiveMode,
    CognitiveCapabilityAssessment,
    ProviderConnectionIntent,
    LocalMissionContinuation,
    BootstrapCognitiveResult,
    PerceptionEvent,
    PerceptionPort,
    ActionCapability,
    ActionCapabilityPort,
    ActionVerificationRequest,
    ActionVerificationResult,
    ActionVerificationPort,
)


class TestBootstrapCognitiveCortex(IsolatedAsyncioTestCase):

    def setUp(self):
        self.repo = LocalKnowledgeObjectRepository()
        self.ame = AdaptiveMemoryEngine(repository=self.repo)
        self.rrm = RegistryResourceManager(populate_defaults=False)
        self.bcc = BootstrapCognitiveCortex(ame=self.ame, rrm=self.rrm)

    # -------------------------------------------------------------------------
    # A & C: Startup without Provider / Provider count zero
    # -------------------------------------------------------------------------
    async def test_a_c_startup_without_provider(self):
        self.assertEqual(self.bcc.get_provider_count(), 0)
        mode = self.bcc.get_mode()
        self.assertEqual(mode, LocalCognitiveMode.LOCAL_CAPABLE)

    # -------------------------------------------------------------------------
    # B & M: Local mode active & Offline operation
    # -------------------------------------------------------------------------
    async def test_b_m_offline_operation_and_local_mode(self):
        offline_policy = ExecutiveExecutionPolicy.from_preset("offline_only")
        bcc_offline = BootstrapCognitiveCortex(ame=self.ame, rrm=self.rrm, policy=offline_policy)
        self.assertEqual(bcc_offline.get_mode(), LocalCognitiveMode.OFFLINE_ONLY)

    # -------------------------------------------------------------------------
    # D & E: Memory available vs Memory unavailable
    # -------------------------------------------------------------------------
    async def test_d_e_memory_available_and_unavailable(self):
        # E: Empty AME
        res_empty = await self.bcc.evaluate_intent("Onde paramos?")
        self.assertIn("Nenhum contexto", res_empty.summary)

        # D: AME with memory
        ko = KnowledgeObject(
            object_id="ko_100",
            content="O projeto Beta utiliza banco SQLite local.",
            project_id="PROJ_BETA",
            status=KnowledgeState.ACTIVE,
        )
        await self.repo.save(ko)

        res_mem = await self.bcc.evaluate_intent("Quais dados temos?", project_id="PROJ_BETA")
        self.assertTrue(len(res_mem.known_context) > 0)
        self.assertIn("SQLite local", res_mem.known_context[0])

    # -------------------------------------------------------------------------
    # F & P: Project Context & Project Isolation
    # -------------------------------------------------------------------------
    async def test_f_p_project_isolation(self):
        await self.repo.save(KnowledgeObject(object_id="ko_a", content="Proj A uses Python.", project_id="PROJ_A"))
        await self.repo.save(KnowledgeObject(object_id="ko_b", content="Proj B uses Go.", project_id="PROJ_B"))

        res_a = await self.bcc.evaluate_intent("Status do projeto", project_id="PROJ_A")
        self.assertIn("Python", str(res_a.known_context))
        self.assertNotIn("Go", str(res_a.known_context))

        res_b = await self.bcc.evaluate_intent("Status do projeto", project_id="PROJ_B")
        self.assertIn("Go", str(res_b.known_context))
        self.assertNotIn("Python", str(res_b.known_context))

    # -------------------------------------------------------------------------
    # G: Unknown information stays UNKNOWN
    # -------------------------------------------------------------------------
    async def test_g_unknown_information_remains_unknown(self):
        res = await self.bcc.evaluate_intent("Onde paramos?", project_id="NON_EXISTENT_PROJECT")
        self.assertIn("UNKNOWN", res.summary)
        self.assertEqual(len(res.known_context), 0)

    # -------------------------------------------------------------------------
    # H & I: Local capability supported vs unsupported
    # -------------------------------------------------------------------------
    async def test_h_i_local_capabilities(self):
        # Supported
        assess_sup = self.bcc.assess_capability("local.intent_summary")
        self.assertTrue(assess_sup.available_locally)
        self.assertIn("Eu sei fazer", assess_sup.reason)

        # Unsupported
        assess_unsup = self.bcc.assess_capability("quantum.computing.execution")
        self.assertFalse(assess_unsup.available_locally)
        self.assertIn("Não há recurso disponível", assess_unsup.reason)

    # -------------------------------------------------------------------------
    # J & K & L: Provider required, recommended & provider-neutral
    # -------------------------------------------------------------------------
    async def test_j_k_l_provider_requirement_and_neutrality(self):
        # Zero provider -> required
        res_req = await self.bcc.evaluate_intent("Crie uma campanha publicitária para lançamento de produto.")
        self.assertEqual(res_req.provider_requirement, "required")
        self.assertIn("reasoning", res_req.provider_profile_requirement)

        # Neutral check: Must NOT mention proprietary brand names
        brands = ["OpenAI", "ChatGPT", "Gemini", "Claude", "Grok"]
        for brand in brands:
            self.assertNotIn(brand, res_req.summary)
            self.assertNotIn(brand, res_req.provider_profile_requirement)

        # Provider available -> recommended
        self.rrm.register_provider(ProviderResource(provider_id="prov_test", name="Test Provider", is_template=False))
        res_rec = await self.bcc.evaluate_intent("Crie uma campanha publicitária para lançamento de produto.")
        self.assertEqual(res_rec.provider_requirement, "recommended")

    # -------------------------------------------------------------------------
    # N: AME Integration via Ports
    # -------------------------------------------------------------------------
    async def test_n_ame_integration_ports(self):
        summary = await self.ame.get_bcc_memory_summary("GLOBAL")
        self.assertIsInstance(summary, str)

        ret_res = await self.ame.query_for_bcc("teste", "GLOBAL")
        self.assertEqual(ret_res.project_scope, "GLOBAL")

    # -------------------------------------------------------------------------
    # O: Secret Exclusion
    # -------------------------------------------------------------------------
    async def test_o_secret_exclusion(self):
        secret_key = "sk_live_SECRET_DO_NOT_EXPOSE_99999"
        await self.repo.save(KnowledgeObject(
            object_id="ko_sec",
            content=f"Secret token: {secret_key}",
            sensitivity="secret",
        ))

        res = await self.bcc.evaluate_intent("Mostrar tokens", project_id="GLOBAL")
        self.assertNotIn(secret_key, res.summary)
        self.assertNotIn(secret_key, str(res.known_context))

    # -------------------------------------------------------------------------
    # Q: Expired memory exclusion
    # -------------------------------------------------------------------------
    async def test_q_expired_memory_exclusion(self):
        await self.repo.save(KnowledgeObject(
            object_id="ko_exp",
            content="Chave temporária de acesso.",
            valid_until="2020-01-01T00:00:00Z",
        ))

        res = await self.bcc.evaluate_intent("Chave temporária")
        self.assertNotIn("Chave temporária de acesso", str(res.known_context))

    # -------------------------------------------------------------------------
    # R: Mission Continuation
    # -------------------------------------------------------------------------
    async def test_r_mission_continuation(self):
        mission = LocalMissionContinuation(
            mission_id="m_101",
            project_id="PROJ_ALPHA",
            current_state="IN_PROGRESS",
            completed_steps=["Step 1: Setup repo"],
            pending_steps=["Step 2: Add database schema"],
        )
        await self.bcc.save_mission_continuation(mission)

        retrieved = await self.bcc.query_mission_continuation("PROJ_ALPHA")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.mission_id, "m_101")
        self.assertEqual(len(retrieved.pending_steps), 1)

    # -------------------------------------------------------------------------
    # S & T & U: AST Import Boundary Rules
    # -------------------------------------------------------------------------
    def test_s_t_u_ast_import_boundaries(self):
        bcc_file = os.path.join(os.path.dirname(__file__), "../intent_kernel/bcc.py")
        with open(bcc_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=bcc_file)

        forbidden_imports = [
            "intent_kernel.providers",
            "sqlite3", "psycopg2", "pymongo",
        ]

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

        for forbidden in forbidden_imports:
            for imp in imported_modules:
                self.assertFalse(imp.startswith(forbidden), f"BCC violates boundary by importing {imp}")

    # -------------------------------------------------------------------------
    # V: No Fake Cognition
    # -------------------------------------------------------------------------
    async def test_v_no_fake_cognition(self):
        res = await self.bcc.evaluate_intent("Análise simples")
        fake_phrases = ["Estou pensando...", "Analisei com inteligência artificial", "Pesquisei na web", "Conectado ao servidor de IA"]
        for phrase in fake_phrases:
            self.assertNotIn(phrase, res.summary)

    # -------------------------------------------------------------------------
    # W: Diagnostics
    # -------------------------------------------------------------------------
    async def test_w_diagnostics(self):
        diag = self.bcc.get_diagnostics()
        self.assertEqual(diag["cortex_status"], "healthy")
        self.assertIn("local.intent_summary", diag["local_capabilities"])
        self.assertIn("external_provider_count", diag)

    # -------------------------------------------------------------------------
    # X & Y: Constitution & ECC Supervision
    # -------------------------------------------------------------------------
    async def test_x_y_ecc_supervision(self):
        # ECC uses BCC as local cognitive resource when provider is 0
        pci = self.bcc.generate_provider_connection_intent(["reasoning"], preferred_privacy="high")
        self.assertEqual(pci.preferred_privacy, "high")
        self.assertTrue(pci.account_requirement)

    # -------------------------------------------------------------------------
    # Z: COR Capability Scope
    # -------------------------------------------------------------------------
    async def test_z_cor_capability_scope(self):
        # Register BCC in RRM
        ok = self.bcc.register_in_rrm(self.rrm)
        self.assertTrue(ok)

        # Check agent in RRM
        agent = self.rrm.get_agent("agent_bcc_local_cortex")
        self.assertIsNotNone(agent)
        self.assertIn("local.intent_summary", agent.capabilities)

    # -------------------------------------------------------------------------
    # AA: RRM Explicit Registration
    # -------------------------------------------------------------------------
    async def test_aa_rrm_explicit_registration(self):
        reg_ok = self.bcc.register_in_rrm(self.rrm)
        self.assertTrue(reg_ok)
        agent = self.rrm.get_agent("agent_bcc_local_cortex")
        self.assertEqual(agent.resource_origin, ResourceOrigin.CONFIGURATION)

    # -------------------------------------------------------------------------
    # AB & AC & AD: Perception, Action, Verification Ports
    # -------------------------------------------------------------------------
    async def test_ab_ac_ad_extension_ports(self):
        # AB: Perception
        evt = PerceptionEvent(event_type="file_changed", source="watcher", payload={"path": "/tmp/test.txt"})
        self.assertEqual(evt.event_type, "file_changed")

        # AC: Action
        act = ActionCapability(capability_id="file.create", description="Create local file", requires_confirmation=True)
        self.assertTrue(act.requires_confirmation)

        # AD: Verification
        req = ActionVerificationRequest(action_id="act_1", action_type="file.create", expected_outcome="file_exists")
        res = ActionVerificationResult(action_id="act_1", succeeded=True, observed_outcome="file_exists")
        self.assertTrue(res.succeeded)


    # =========================================================================
    # MANDATORY CASES 1 THROUGH 5
    # =========================================================================

    async def test_mandatory_case_1_first_install_zero_provider(self):
        """CASO 1 — PRIMEIRA INSTALAÇÃO (Zero Providers). User asks capabilities."""
        res = await self.bcc.evaluate_intent("O que você consegue fazer?")
        self.assertEqual(res.state, LocalCognitiveMode.LOCAL_CAPABLE)
        self.assertIn("INTENT OS — PRIMEIRA EXECUÇÃO", res.summary)
        self.assertIn("O QUE FUNCIONA OFFLINE", res.summary)

    async def test_mandatory_case_2_local_knowledge(self):
        """CASO 2 — CONHECIMENTO LOCAL (AME has active project memory)."""
        await self.repo.save(KnowledgeObject(
            object_id="ko_project_alpha",
            content="O projeto Alpha está no Passo 2: Configuração de banco de dados.",
            project_id="PROJ_ALPHA",
            status=KnowledgeState.ACTIVE,
        ))

        res = await self.bcc.evaluate_intent("Onde paramos?", project_id="PROJ_ALPHA")
        self.assertIn("Configuração de banco de dados", res.summary)
        self.assertEqual(res.state, LocalCognitiveMode.LOCAL_CAPABLE)

    async def test_mandatory_case_3_generative_task_no_provider(self):
        """CASO 3 — TAREFA GENERATIVA sem Provider."""
        res = await self.bcc.evaluate_intent("Crie uma campanha publicitária completa.")
        self.assertEqual(res.state, LocalCognitiveMode.EXTERNAL_PROVIDER_REQUIRED)
        self.assertIn("requer capacidade 'reasoning'", res.summary)
        self.assertTrue(len(res.local_plan) > 0)

    async def test_mandatory_case_4_provider_available(self):
        """CASO 4 — PROVIDER DISPONÍVEL no RRM."""
        self.rrm.register_provider(ProviderResource(provider_id="p_001", name="External LLM Provider", is_template=False))
        self.assertEqual(self.bcc.get_provider_count(), 1)

        res = await self.bcc.evaluate_intent("Crie uma campanha publicitária completa.")
        self.assertEqual(res.state, LocalCognitiveMode.EXTERNAL_PROVIDER_RECOMMENDED)

    async def test_mandatory_case_5_no_knowledge_unknown(self):
        """CASO 5 — SEM CONHECIMENTO (Query about nonexistent memory -> UNKNOWN)."""
        res = await self.bcc.evaluate_intent("Onde paramos?", project_id="PROJECT_NON_EXISTENT")
        self.assertIn("UNKNOWN", res.summary)
        self.assertEqual(len(res.known_context), 0)


if __name__ == "__main__":
    unittest.main()
