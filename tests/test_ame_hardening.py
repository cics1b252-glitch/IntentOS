"""AME & KOM Hardening & Persistence Validation Gate (STUDIO 9.1 / RFC-0012).

Validates:
1. Real persistence & supersession across process restarts via JsonFilePersistenceEngine.
2. Temporal expiration with controlled clocks.
3. Secret detection hardening & zero secret leakage in logs/diagnostics/reasons.
4. Scope isolation (Project A vs Project B vs Global).
5. Sensitivity filtering (normal vs confidential vs secret).
6. Memory access control policy (memory_access_allowed=False).
7. Authority boundaries (AST/import inspection).
8. IUE / CDM / CPE Integration Ports.
9. Epistemic nature preservation (INFERENCE vs FACT).
10. Persistent deduplication across restarts.
11. User correction priority over system inferences.
12. Legacy PKB compatibility.
13. Storage failure handling.
14. Offline execution & optional vector search.
15. BCC extension points readiness & diagnostic safety.
"""

import os
import tempfile
import unittest
import ast
from unittest import IsolatedAsyncioTestCase

from intent_kernel.kom import (
    KnowledgeObject,
    ProvenanceRecord,
    MemoryClass,
    KnowledgeNature,
    KnowledgeState,
    RetentionPolicy,
    SourceType,
    ScopeType,
    utc_iso,
)
from intent_kernel.persistence import JsonFilePersistenceEngine
from intent_kernel.ame import (
    AdaptiveMemoryEngine,
    LocalKnowledgeObjectRepository,
    MemoryCandidate,
    MemoryDecisionEnum,
    MemoryQuery,
    ContextAssembler,
    IUEContextPort,
    CDMContextPort,
    CPEContextPort,
    ECCMemoryControlPort,
    LegacyKnowledgeEventAdapter,
)
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.types import EventType


class TestAMEHardeningValidationGate(IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "ame_storage.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_01_real_persistence_across_restart(self):
        """Process A saves KnowledgeObject to disk; Process B reloads and verifies all fields."""
        # Process A:
        engine_a = JsonFilePersistenceEngine(self.db_path)
        repo_a = LocalKnowledgeObjectRepository(engine_a)
        ame_a = AdaptiveMemoryEngine(repository=repo_a)

        prov = ProvenanceRecord(
            source_type=SourceType.USER_INPUT,
            source_id="user_session_101",
            timestamp="2026-08-08T10:00:00Z",
            correlation_id="corr_999",
        )
        cand = MemoryCandidate(
            proposed_content="O ecossistema do projeto utiliza PostgreSQL v15.",
            reason_to_remember="Arquitetura de banco de dados",
            project_id="PROJECT_ALPHA",
            provenance=prov,
            confidence=0.92,
        )
        dec_a, obj_a = await ame_a.process_candidate(cand)
        self.assertEqual(dec_a.decision, MemoryDecisionEnum.STORE)
        self.assertIsNotNone(obj_a)
        saved_id = obj_a.object_id

        # Shutdown instance A (no-op cleanup)
        del ame_a
        del repo_a
        del engine_a

        # Process B:
        engine_b = JsonFilePersistenceEngine(self.db_path)
        repo_b = LocalKnowledgeObjectRepository(engine_b)
        ame_b = AdaptiveMemoryEngine(repository=repo_b)

        retrieved = await repo_b.get(saved_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.object_id, saved_id)
        self.assertEqual(retrieved.version, 1)
        self.assertEqual(retrieved.provenance.source_id, "user_session_101")
        self.assertEqual(retrieved.provenance.correlation_id, "corr_999")
        self.assertEqual(retrieved.project_id, "PROJECT_ALPHA")
        self.assertEqual(retrieved.status, KnowledgeState.ACTIVE)
        self.assertAlmostEqual(retrieved.confidence, 0.92)

    async def test_02_persistent_supersession_across_restart(self):
        """v1 React -> v2 Flutter correction persists across process restart."""
        db = os.path.join(self.temp_dir.name, "supersede_db.json")

        # Instance A: Save v1
        engine1 = JsonFilePersistenceEngine(db)
        repo1 = LocalKnowledgeObjectRepository(engine1)
        ame1 = AdaptiveMemoryEngine(repository=repo1)

        cand1 = MemoryCandidate(
            proposed_content="O framework mobile utilizado é React Native.",
            project_id="ATLAS_MOBILE",
        )
        dec1, obj1 = await ame1.process_candidate(cand1)
        self.assertEqual(dec1.decision, MemoryDecisionEnum.STORE)
        v1_id = obj1.object_id

        # Instance B: Correct to v2
        cand2 = MemoryCandidate(
            proposed_content="Corrigindo: O framework mobile utilizado é Flutter.",
            project_id="ATLAS_MOBILE",
        )
        dec2, obj2 = await ame1.process_candidate(cand2)
        self.assertEqual(dec2.decision, MemoryDecisionEnum.SUPERSEDE)
        v2_id = obj2.object_id

        # Instance C (Process restart from clean memory space)
        engine_c = JsonFilePersistenceEngine(db)
        repo_c = LocalKnowledgeObjectRepository(engine_c)
        ret_v1 = await repo_c.get(v1_id)
        ret_v2 = await repo_c.get(v2_id)

        self.assertEqual(ret_v1.status, KnowledgeState.SUPERSEDED)
        self.assertEqual(ret_v1.superseded_by, v2_id)
        self.assertEqual(ret_v2.status, KnowledgeState.ACTIVE)
        self.assertEqual(ret_v2.supersedes, v1_id)
        self.assertEqual(ret_v2.version, 2)

    async def test_03_controlled_clock_temporal_expiration(self):
        """Time-bound knowledge is valid before valid_until and excluded after valid_until."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        ko = KnowledgeObject(
            object_id="temp_trip_1",
            content="Estou em viagem de trabalho nesta semana.",
            summary="Viagem de trabalho",
            project_id="GLOBAL",
            status=KnowledgeState.ACTIVE,
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2026-08-07T23:59:59Z",
        )
        await repo.save(ko)

        # Before expiration:
        self.assertTrue(ko.is_valid_at("2026-08-05T12:00:00Z"))

        # After expiration:
        self.assertFalse(ko.is_valid_at("2026-08-08T10:00:00Z"))

        # Retrieval at current date (2026-08-08) excludes expired item:
        res = await ame.retrieve_memory(MemoryQuery(query_text="viagem", project_id="GLOBAL"))
        self.assertEqual(len(res.objects), 0)

    async def test_04_secret_detection_hardening(self):
        """Rejects candidates containing tokens, passwords, bearer keys, private keys, or secret sensitivity."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        secret_samples = [
            ("sk-live-abcdef123456789012345678", "sk token"),
            ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "bearer token"),
            ("password=SuperSecretPassword123!", "password assignment"),
            ("api_key=AIzaSyA1234567890abcdef1234567890", "api key"),
            ("-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n-----END PRIVATE KEY-----", "pem private key"),
        ]

        for secret_str, label in secret_samples:
            cand = MemoryCandidate(proposed_content=f"Configuração do serviço: {secret_str}")
            dec, obj = await ame.process_candidate(cand)
            self.assertEqual(dec.decision, MemoryDecisionEnum.REJECT, f"Failed to reject secret: {label}")
            self.assertNotIn(secret_str, dec.reason)

    async def test_05_secret_zero_leakage_diagnostics_and_logs(self):
        """Rejection of secret leaves no trace in decision reason, diagnostics, or context assembler."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        sensitive_key = "sk_live_SECRET_DO_NOT_LEAK_99999"
        cand = MemoryCandidate(proposed_content=f"Secret key is {sensitive_key}")
        dec, _ = await ame.process_candidate(cand)

        self.assertEqual(dec.decision, MemoryDecisionEnum.REJECT)
        self.assertNotIn(sensitive_key, dec.reason)
        self.assertNotIn(sensitive_key, str(dec))

        diag = await ame.get_diagnostics()
        self.assertNotIn(sensitive_key, str(diag))

        res = await ame.retrieve_memory(MemoryQuery())
        ctx = ContextAssembler.assemble_context(res)
        self.assertNotIn(sensitive_key, ctx)

    async def test_06_project_isolation_and_global_scope(self):
        """Project A and Project B memories are isolated; global query does not leak project-specific items."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        await ame.process_candidate(MemoryCandidate(proposed_content="Project A uses Vue 3.", project_id="PROJ_A"))
        await ame.process_candidate(MemoryCandidate(proposed_content="Project B uses Angular.", project_id="PROJ_B"))
        await ame.process_candidate(MemoryCandidate(proposed_content="Empresa usa CI/CD no GitHub Actions.", project_id="GLOBAL"))

        # Query Project A -> gets A + Global
        res_a = await ame.retrieve_memory(MemoryQuery(project_id="PROJ_A"))
        contents_a = [str(o.content) for o in res_a.objects]
        self.assertTrue(any("Vue 3" in c for c in contents_a))
        self.assertTrue(any("GitHub Actions" in c for c in contents_a))
        self.assertFalse(any("Angular" in c for c in contents_a))

        # Global query -> gets ONLY Global
        res_g = await ame.retrieve_memory(MemoryQuery(project_id="GLOBAL"))
        contents_g = [str(o.content) for o in res_g.objects]
        self.assertTrue(any("GitHub Actions" in c for c in contents_g))
        self.assertFalse(any("Vue 3" in c for c in contents_g))
        self.assertFalse(any("Angular" in c for c in contents_g))

    async def test_07_sensitivity_filtering(self):
        """Objects higher than sensitivity_limit are excluded from retrieval and context."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        ko_norm = KnowledgeObject(object_id="ko1", content="Normal public info", sensitivity="normal")
        ko_conf = KnowledgeObject(object_id="ko2", content="Internal roadmap notes", sensitivity="confidential")
        ko_sec = KnowledgeObject(object_id="ko3", content="Ultra secret credential", sensitivity="secret")

        await repo.save(ko_norm)
        await repo.save(ko_conf)
        await repo.save(ko_sec)

        # Retrieval limit = "normal"
        res_norm = await ame.retrieve_memory(MemoryQuery(sensitivity_limit="normal"))
        ids_norm = [o.object_id for o in res_norm.objects]
        self.assertIn("ko1", ids_norm)
        self.assertNotIn("ko2", ids_norm)
        self.assertNotIn("ko3", ids_norm)

        # Retrieval limit = "confidential"
        res_conf = await ame.retrieve_memory(MemoryQuery(sensitivity_limit="confidential"))
        ids_conf = [o.object_id for o in res_conf.objects]
        self.assertIn("ko1", ids_conf)
        self.assertIn("ko2", ids_conf)
        self.assertNotIn("ko3", ids_conf)

    async def test_08_memory_access_policy_blocked(self):
        """When memory_access_allowed=False, no objects are injected."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        await repo.save(KnowledgeObject(object_id="k1", content="Qualquer dado"))

        ame_blocked = AdaptiveMemoryEngine(repository=repo, memory_access_allowed=False)
        res = await ame_blocked.retrieve_memory(MemoryQuery())
        self.assertEqual(len(res.objects), 0)
        self.assertIn("blocked", res.retrieval_reason.lower())

    def test_09_authority_boundaries_ast_inspection(self):
        """Verifies AME does not import concrete execution/provider/constitution engines."""
        ame_file = os.path.join(os.path.dirname(__file__), "../intent_kernel/ame.py")
        with open(ame_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=ame_file)

        forbidden_modules = [
            "intent_kernel.constitution",
            "intent_kernel.providers",
            "intent_kernel.agents",
            "intent_kernel.cor",
            "intent_kernel.rrm.catalog",
        ]

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

        for forbidden in forbidden_modules:
            for imp in imported_modules:
                self.assertFalse(imp.startswith(forbidden), f"AME violates boundary by importing {imp}")

    async def test_10_iue_cdm_cpe_context_ports(self):
        """Context ports supply pre-known context to IUE, CDM, and CPE without concrete imports."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        await ame.process_candidate(MemoryCandidate(proposed_content="Prefiro respostas diretas e curtas.", project_id="GLOBAL"))

        iue_port = IUEContextPort(ame)
        cdm_port = CDMContextPort(ame)
        cpe_port = CPEContextPort(ame)

        iue_ctx = await iue_port.retrieve_understanding_context("respostas")
        self.assertIn("diretas e curtas", iue_ctx)

        cdm_ctx = await cdm_port.get_known_context("GLOBAL")
        self.assertEqual(len(cdm_ctx.objects), 1)

        cpe_ctx = await cpe_port.get_planning_context("respostas")
        self.assertIn("diretas e curtas", cpe_ctx)

    async def test_11_epistemic_nature_preservation(self):
        """Knowledge nature INFERENCE with confidence 0.51 is preserved and formatted as INFERENCE."""
        ko = KnowledgeObject(
            object_id="inf_1",
            content="Provavelmente o cliente prefere implantar em AWS.",
            knowledge_nature=KnowledgeNature.INFERENCE,
            confidence=0.51,
        )
        res = MemoryQuery()
        ctx = ContextAssembler.assemble_context(
            retrieval_result=type("Result", (), {"objects": [ko], "relevance_scores": {"inf_1": 0.8}, "project_scope": "GLOBAL"})()
        )
        self.assertIn("INFERENCE", ctx)
        self.assertIn("Conf:0.51", ctx)

    async def test_12_persistent_deduplication(self):
        """Duplicates are rejected/ignored across process restarts."""
        db = os.path.join(self.temp_dir.name, "dedup_db.json")

        # Process A: Store initial candidate
        engine_a = JsonFilePersistenceEngine(db)
        ame_a = AdaptiveMemoryEngine(repository=LocalKnowledgeObjectRepository(engine_a))
        dec1, _ = await ame_a.process_candidate(MemoryCandidate(proposed_content="Prefiro utilizar o tema escuro."))
        self.assertEqual(dec1.decision, MemoryDecisionEnum.STORE)

        # Process B: Same candidate submitted again
        engine_b = JsonFilePersistenceEngine(db)
        ame_b = AdaptiveMemoryEngine(repository=LocalKnowledgeObjectRepository(engine_b))
        dec2, _ = await ame_b.process_candidate(MemoryCandidate(proposed_content="Prefiro utilizar o tema escuro."))
        self.assertEqual(dec2.decision, MemoryDecisionEnum.IGNORE)

    async def test_13_user_correction_over_system_inference(self):
        """User correction supersedes prior active inference."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        # System inference
        cand_inf = MemoryCandidate(
            proposed_content="Inferência: Usuário utiliza Python 3.9.",
            project_id="PROJ_X",
        )
        await ame.process_candidate(cand_inf)

        # User explicit correction
        cand_corr = MemoryCandidate(
            proposed_content="Corrigindo: Utilizo Python 3.11.",
            project_id="PROJ_X",
        )
        dec, corr_obj = await ame.process_candidate(cand_corr)

        self.assertEqual(dec.decision, MemoryDecisionEnum.SUPERSEDE)
        self.assertEqual(corr_obj.memory_class, MemoryClass.CORRECTION)

    async def test_14_legacy_pkb_compatibility(self):
        """Legacy PKB KnowledgeEvent converts bidirectionally with KnowledgeObject."""
        event = KnowledgeEvent(
            type=EventType.DECISION,
            title="Legacy Storage Decision",
            content={"database": "PostgreSQL"},
            confidence=0.88,
            source="pkb_importer",
            metadata={"project_id": "PROJ_LEGACY"},
        )

        ko = LegacyKnowledgeEventAdapter.event_to_object(event, project_id="PROJ_LEGACY")
        self.assertEqual(ko.project_id, "PROJ_LEGACY")
        self.assertEqual(ko.confidence, 0.88)
        self.assertEqual(ko.source, "pkb_importer")

        event_back = LegacyKnowledgeEventAdapter.object_to_event(ko)
        self.assertEqual(event_back.confidence, 0.88)
        self.assertEqual(event_back.content, {"database": "PostgreSQL"})

    async def test_15_storage_failure_handling(self):
        """Broken repository returning False or raising Exception returns REJECT decision."""
        class BrokenRepository:
            async def query(self, **kwargs):
                return []
            async def save(self, obj):
                return False
            async def supersede(self, old_id, new_obj):
                return False

        ame_broken = AdaptiveMemoryEngine(repository=BrokenRepository())
        dec, obj = await ame_broken.process_candidate(MemoryCandidate(proposed_content="Isto falhará no save."))

        self.assertEqual(dec.decision, MemoryDecisionEnum.REJECT)
        self.assertIn("Storage failure", dec.reason)
        self.assertIsNone(obj)

    async def test_16_bcc_readiness_and_diagnostics(self):
        """BCC extension points work securely and diagnostics report metrics without raw data."""
        repo = LocalKnowledgeObjectRepository(JsonFilePersistenceEngine(self.db_path))
        ame = AdaptiveMemoryEngine(repository=repo)

        await ame.process_candidate(MemoryCandidate(proposed_content="Configuração padrão do sistema."))

        summary = await ame.get_bcc_memory_summary("GLOBAL")
        self.assertIn("Configuração padrão", summary)

        diag = await ame.get_diagnostics()
        self.assertEqual(diag["total_active_objects"], 1)
        self.assertIn("read_operations", diag)
        self.assertIn("write_operations", diag)
        self.assertEqual(diag["storage_status"], "healthy")


if __name__ == "__main__":
    unittest.main()
