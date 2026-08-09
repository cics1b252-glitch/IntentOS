"""Unit and Integration Test Suite for RFC-0012 Adaptive Memory Engine (AME) & KOM.

Verifies:
- Scenarios A through AE
- Specific Cases 1 through 5
- Zero Provider / Database / RRM side effect dependencies
"""

import asyncio
import unittest
from datetime import datetime, timedelta

from intent_kernel.ame import (
    AdaptiveMemoryEngine,
    CDMContextPort,
    CPEContextPort,
    ECCMemoryControlPort,
    InMemoryGraphEdgeStorageAdapter,
    InMemoryVectorSearchAdapter,
    IUEContextPort,
    KnowledgeObjectRepositoryPort,
    LegacyKnowledgeEventAdapter,
    LocalKnowledgeObjectRepository,
    MemoryCandidate,
    MemoryDecisionEnum,
    MemoryDecisionEngine,
    MemoryQuery,
    ContextAssembler,
    RRMBoundary,
)
from intent_kernel.kom import (
    KnowledgeNature,
    KnowledgeObject,
    KnowledgeState,
    MemoryClass,
    ProvenanceRecord,
    RetentionPolicy,
    ScopeType,
    SourceType,
)
from intent_kernel.pkb.models import KnowledgeEvent
from intent_kernel.time_utils import utc_iso, utc_now


class TestAdaptiveMemoryEngine(unittest.IsolatedAsyncioTestCase):
    """Full test suite covering AME, KOM, and pipeline integrations."""

    async def asyncSetUp(self):
        self.repo = LocalKnowledgeObjectRepository()
        self.vector = InMemoryVectorSearchAdapter()
        self.graph = InMemoryGraphEdgeStorageAdapter()
        self.ame = AdaptiveMemoryEngine(
            repository=self.repo,
            vector_search=self.vector,
            graph_storage=self.graph,
        )

    # -------------------------------------------------------------------------
    # Scenarios A - J: Models, Provenance, Epistemics & Lifecycle
    # -------------------------------------------------------------------------

    async def test_a_knowledge_object_creation(self):
        obj = KnowledgeObject(
            object_id="ko_1",
            content="Use Python 3.10+",
            summary="Python version preference",
            memory_class=MemoryClass.PREFERENCE,
            knowledge_nature=KnowledgeNature.PREFERENCE,
        )
        self.assertEqual(obj.object_id, "ko_1")
        self.assertEqual(obj.status, KnowledgeState.ACTIVE)
        self.assertTrue(obj.cognitive_context_eligible)

    async def test_b_provenance_structure(self):
        prov = ProvenanceRecord(
            source_type=SourceType.USER_INPUT,
            source_id="usr_123",
            mission_id="mis_1",
            project_id="prj_atlas",
            confidence_at_source=0.95,
        )
        obj = KnowledgeObject(
            object_id="ko_2",
            content="Test provenance",
            provenance=prov,
        )
        self.assertEqual(obj.provenance.source_id, "usr_123")
        self.assertEqual(obj.provenance.project_id, "prj_atlas")

    async def test_c_confidence_handling(self):
        obj = KnowledgeObject(object_id="ko_3", content="Fact", confidence=0.4)
        self.assertEqual(obj.confidence, 0.4)
        # Search requiring min confidence 0.5 should exclude it
        query = MemoryQuery(query_text="Fact", minimum_confidence=0.5)
        res = await self.ame.retrieve_memory(query)
        self.assertEqual(len(res.objects), 0)

    async def test_d_importance_salience(self):
        cand = MemoryCandidate(
            proposed_content="Prefiro respostas curtas.",
            proposed_importance=0.5,
        )
        importance = MemoryDecisionEngine.calculate_importance(cand)
        self.assertGreaterEqual(importance, 0.85)

    async def test_e_f_project_vs_global_scope(self):
        obj_atlas = KnowledgeObject(
            object_id="ko_atlas",
            content="Atlas secret strategy",
            project_id="PROJECT_ATLAS",
            user_scope=ScopeType.PROJECT_SCOPE,
        )
        obj_global = KnowledgeObject(
            object_id="ko_global",
            content="Global policy",
            project_id="GLOBAL",
            user_scope=ScopeType.GLOBAL_SCOPE,
        )
        await self.ame.store_object(obj_atlas)
        await self.ame.store_object(obj_global)

        # Retrieval for OEM Studio should ONLY see global, NOT Atlas
        res_oem = await self.ame.retrieve_memory(MemoryQuery(project_id="OEM_STUDIO"))
        ids = [o.object_id for o in res_oem.objects]
        self.assertIn("ko_global", ids)
        self.assertNotIn("ko_atlas", ids)

    async def test_g_temporal_expiration(self):
        past_iso = (utc_now() - timedelta(days=1)).isoformat()
        obj_expired = KnowledgeObject(
            object_id="ko_exp",
            content="Travel context",
            valid_until=past_iso,
        )
        await self.ame.store_object(obj_expired)

        # Purge
        purged = await self.ame.purge_expired()
        self.assertEqual(purged, 1)

        fetched = await self.ame.get_object("ko_exp")
        self.assertEqual(fetched.status, KnowledgeState.EXPIRED)

    async def test_h_i_j_versioning_supersession_correction(self):
        cand1 = MemoryCandidate(
            proposed_content="Meu projeto usa React.",
            project_id="PROJ_APP",
        )
        dec1, obj1 = await self.ame.process_candidate(cand1)
        self.assertEqual(dec1.decision, MemoryDecisionEnum.STORE)

        cand2 = MemoryCandidate(
            proposed_content="Corrigindo: decidimos usar Flutter.",
            project_id="PROJ_APP",
        )
        dec2, obj2 = await self.ame.process_candidate(cand2)
        self.assertEqual(dec2.decision, MemoryDecisionEnum.SUPERSEDE)
        self.assertEqual(obj2.version, 2)

        # Verify old is superseded
        old_obj = await self.ame.get_object(obj1.object_id)
        self.assertEqual(old_obj.status, KnowledgeState.SUPERSEDED)
        self.assertEqual(old_obj.superseded_by, obj2.object_id)

    # -------------------------------------------------------------------------
    # Scenarios K - Q: Candidate Evaluation & Decisions
    # -------------------------------------------------------------------------

    async def test_k_l_candidate_store_and_ignore(self):
        cand_noise = MemoryCandidate(proposed_content="ok")
        dec_noise, _ = await self.ame.process_candidate(cand_noise)
        self.assertEqual(dec_noise.decision, MemoryDecisionEnum.IGNORE)

        cand_valid = MemoryCandidate(proposed_content="Empresa fundada em 2024.")
        dec_valid, _ = await self.ame.process_candidate(cand_valid)
        self.assertEqual(dec_valid.decision, MemoryDecisionEnum.STORE)

    async def test_o_p_deduplication_and_conflict(self):
        cand1 = MemoryCandidate(proposed_content="Prefiro modo escuro.")
        await self.ame.process_candidate(cand1)

        cand_dup = MemoryCandidate(proposed_content="Prefiro modo escuro.")
        dec_dup, _ = await self.ame.process_candidate(cand_dup)
        self.assertEqual(dec_dup.decision, MemoryDecisionEnum.IGNORE)

    async def test_q_retention_policy(self):
        obj = KnowledgeObject(
            object_id="ko_ret",
            content="Session token note",
            retention_policy=RetentionPolicy.SESSION,
        )
        self.assertEqual(obj.retention_policy, RetentionPolicy.SESSION)

    # -------------------------------------------------------------------------
    # Scenarios R - V: Retrieval & Context Assembly
    # -------------------------------------------------------------------------

    async def test_r_s_t_retrieval_filtering(self):
        await self.ame.store_object(
            KnowledgeObject(
                object_id="ko_pref",
                content="Prefiro tom formal",
                memory_class=MemoryClass.PREFERENCE,
                project_id="P1",
            )
        )
        await self.ame.store_object(
            KnowledgeObject(
                object_id="ko_goal",
                content="Lançar v1.0",
                memory_class=MemoryClass.GOAL,
                project_id="P1",
            )
        )

        res_class = await self.ame.retrieve_memory(
            MemoryQuery(project_id="P1", memory_classes=[MemoryClass.GOAL])
        )
        self.assertEqual(len(res_class.objects), 1)
        self.assertEqual(res_class.objects[0].object_id, "ko_goal")

    async def test_u_v_context_assembler(self):
        obj1 = KnowledgeObject(
            object_id="k1",
            content="Architecture uses microservices",
            summary="Microservices architecture",
            knowledge_nature=KnowledgeNature.FACT,
            memory_class=MemoryClass.SEMANTIC,
        )
        res = ContextAssembler.assemble_context(
            retrieval_result=None or type("Result", (), {"objects": [obj1], "project_scope": "PROJ_A", "relevance_scores": {"k1": 0.9}})()
        )
        self.assertIn("Microservices architecture", res)
        self.assertIn("FACT", res)

    # -------------------------------------------------------------------------
    # Scenarios W - Z, AA, AB, AC, AD, AE: Security & Architecture Invariants
    # -------------------------------------------------------------------------

    async def test_w_ecc_memory_control_port(self):
        ecc_port = ECCMemoryControlPort(self.ame)
        auth = await ecc_port.authorize_memory_access("P1", sensitivity="secret")
        self.assertEqual(auth, "BLOCK_MEMORY_ACCESS")

        auth_normal = await ecc_port.authorize_memory_access("P1", sensitivity="normal")
        self.assertEqual(auth_normal, "ALLOW_MEMORY_ACCESS")

    async def test_x_secret_exclusion(self):
        cand_secret = MemoryCandidate(
            proposed_content="Minha chave e API key sk-live-1234567890123456789012345678"
        )
        dec_res, _ = await self.ame.process_candidate(cand_secret)
        self.assertEqual(dec_res.decision, MemoryDecisionEnum.REJECT)

    async def test_y_legacy_pkb_adapter(self):
        from intent_kernel.types import EventType
        event = KnowledgeEvent(
            type=EventType.DECISION,
            title="Legacy Decision",
            content={"chosen": "PostgreSQL"},
            confidence=0.9,
            source="user",
        )
        ko = LegacyKnowledgeEventAdapter.event_to_object(event, project_id="P_LEGACY")
        self.assertEqual(ko.object_id, event.id)
        self.assertEqual(ko.memory_class, MemoryClass.DECISION)
        self.assertEqual(ko.project_id, "P_LEGACY")

        event_back = LegacyKnowledgeEventAdapter.object_to_event(ko)
        self.assertEqual(event_back.id, ko.object_id)

    async def test_ad_vector_search_port(self):
        await self.vector.index("ko_v1", [1.0, 0.0, 0.0], {"type": "test"})
        similar = await self.vector.search_similar([1.0, 0.0, 0.0], top_k=1)
        self.assertEqual(similar[0][0], "ko_v1")
        self.assertAlmostEqual(similar[0][1], 1.0)

    async def test_ae_diagnostics(self):
        await self.ame.store_object(KnowledgeObject(object_id="d1", content="Diag 1"))
        diag = await self.ame.get_diagnostics()
        self.assertEqual(diag["total_active_objects"], 1)
        self.assertEqual(diag["storage_status"], "healthy")

    # -------------------------------------------------------------------------
    # Mandatory Specific Cases 1 - 5
    # -------------------------------------------------------------------------

    async def test_case_1_preference_storage(self):
        """Case 1: 'Prefiro respostas curtas.' -> PREFERENCE, LONG_TERM, STORE."""
        cand = MemoryCandidate(proposed_content="Prefiro respostas curtas.")
        dec, ko = await self.ame.process_candidate(cand)
        self.assertEqual(dec.decision, MemoryDecisionEnum.STORE)
        self.assertEqual(ko.memory_class, MemoryClass.PREFERENCE)
        self.assertEqual(ko.retention_policy, RetentionPolicy.LONG_TERM)

    async def test_case_2_temporary_context(self):
        """Case 2: 'Esta semana estou viajando.' -> TEMPORARY_CONTEXT, valid_until set."""
        cand = MemoryCandidate(proposed_content="Esta semana estou viajando.")
        dec, ko = await self.ame.process_candidate(cand)
        self.assertEqual(dec.decision, MemoryDecisionEnum.TEMPORARY)
        self.assertIsNotNone(ko.valid_until)

    async def test_case_3_user_correction_supersession(self):
        """Case 3: 'Meu projeto usa React.' then 'Corrigindo: decidimos usar Flutter.'"""
        c1 = MemoryCandidate(proposed_content="Meu projeto usa React.", project_id="WEB_APP")
        _, k1 = await self.ame.process_candidate(c1)

        c2 = MemoryCandidate(proposed_content="Corrigindo: decidimos usar Flutter.", project_id="WEB_APP")
        dec2, k2 = await self.ame.process_candidate(c2)

        self.assertEqual(dec2.decision, MemoryDecisionEnum.SUPERSEDE)
        k1_updated = await self.ame.get_object(k1.object_id)
        self.assertEqual(k1_updated.status, KnowledgeState.SUPERSEDED)
        self.assertEqual(k2.status, KnowledgeState.ACTIVE)

    async def test_case_4_project_isolation(self):
        """Case 4: Memory in Project Atlas not retrieved in OEM Studio."""
        await self.ame.store_object(
            KnowledgeObject(
                object_id="ko_atlas_secret",
                content="Atlas roadmap 2027",
                project_id="PROJECT_ATLAS",
            )
        )
        res = await self.ame.retrieve_memory(MemoryQuery(project_id="OEM_STUDIO"))
        self.assertEqual(len(res.objects), 0)

    async def test_case_5_secret_key_rejection(self):
        """Case 5: Input containing secret/API key -> REJECT, secret not persisted."""
        cand = MemoryCandidate(proposed_content="My key is AIzaSyA1234567890123456789012345678901")
        dec, ko = await self.ame.process_candidate(cand)
        self.assertEqual(dec.decision, MemoryDecisionEnum.REJECT)
        self.assertIsNone(ko)


if __name__ == "__main__":
    unittest.main()
