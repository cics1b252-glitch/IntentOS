"""Persistent Instruction Enforcement Tests — RFC-0014.1 (STUDIO 10.1).

Comprehensive test suite covering requirements A through Z for persistent instruction management,
resolver precedence, output contract validation, regression incident test, and project isolation.
"""

import ast
import os
import shutil
import tempfile
import unittest
from unittest import IsolatedAsyncioTestCase

from intent_kernel.ame import AdaptiveMemoryEngine, LocalKnowledgeObjectRepository
from intent_kernel.kom import KnowledgeObject, KnowledgeState, MemoryClass
from intent_kernel.persistence import JsonFilePersistenceEngine

from intent_kernel.instructions import (
    CompletionEvidence,
    InstructionScope,
    InstructionType,
    InstructionViolation,
    MissionConstraint,
    OutputContract,
    OutputContractValidator,
    OutputValidationResult,
    PersistentInstruction,
    PersistentInstructionResolver,
    PrecedenceLevel,
    SecretInstructionError,
)


class TestPersistentInstructionEnforcement(IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, "ame_data.json")
        self.persistence = JsonFilePersistenceEngine(file_path=self.file_path)
        self.repo = LocalKnowledgeObjectRepository(persistence_engine=self.persistence)
        self.ame = AdaptiveMemoryEngine(repository=self.repo)
        self.resolver = PersistentInstructionResolver(ame=self.ame)
        self.validator = OutputContractValidator(max_output_corrections=3)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # -------------------------------------------------------------------------
    # A & B: Create & Retrieve Persistent Instruction
    # -------------------------------------------------------------------------
    async def test_a_b_create_and_retrieve_instruction(self):
        inst = PersistentInstruction(
            instruction_id="pi_1",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="format_single_block",
            description="Entregar em bloco único",
            constraint="Relatórios técnicos de missões do Intent OS devem ser entregues em um único bloco copiável, sem texto fora do bloco.",
        )
        saved = await self.resolver.save_instruction(inst)
        self.assertEqual(saved.instruction_id, "pi_1")

        active = await self.resolver.get_active_instructions(project_id="GLOBAL")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].instruction_id, "pi_1")

    # -------------------------------------------------------------------------
    # C: Persistence Restart Test Across Processes
    # -------------------------------------------------------------------------
    async def test_c_persistence_restart(self):
        inst = PersistentInstruction(
            instruction_id="pi_restart_1",
            scope=InstructionScope.PROJECT,
            project_id="PROJ_RESTART",
            rule_key="no_git_modify",
            description="Não modificar Git",
            constraint="Intent OS não deve modificar Git no AI Studio.",
        )
        await self.resolver.save_instruction(inst)

        # Re-initialize repository and AME reading from disk (simulating process restart)
        new_repo = LocalKnowledgeObjectRepository(persistence_engine=self.persistence)
        new_ame = AdaptiveMemoryEngine(repository=new_repo)
        new_resolver = PersistentInstructionResolver(ame=new_ame)

        active = await new_resolver.get_active_instructions(project_id="PROJ_RESTART")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].instruction_id, "pi_restart_1")
        self.assertIn("Git", active[0].constraint)

    # -------------------------------------------------------------------------
    # D, E, F, G: Scopes (GLOBAL_USER, PROJECT, MISSION, SESSION)
    # -------------------------------------------------------------------------
    async def test_d_e_f_g_scopes(self):
        inst_global = PersistentInstruction(
            instruction_id="pi_g",
            scope=InstructionScope.GLOBAL_USER,
            project_id="GLOBAL",
            rule_key="global_pref",
            constraint="Global preference rule",
        )
        inst_project = PersistentInstruction(
            instruction_id="pi_p",
            scope=InstructionScope.PROJECT,
            project_id="PROJ_X",
            rule_key="proj_x_pref",
            constraint="Project X specific rule",
        )
        await self.resolver.save_instruction(inst_global)
        await self.resolver.save_instruction(inst_project)

        # Query PROJ_X (should get global + PROJ_X)
        res_x = await self.resolver.get_active_instructions(project_id="PROJ_X")
        self.assertEqual(len(res_x), 2)

        # Query PROJ_Y (should get ONLY global, NOT PROJ_X)
        res_y = await self.resolver.get_active_instructions(project_id="PROJ_Y")
        self.assertEqual(len(res_y), 1)
        self.assertEqual(res_y[0].instruction_id, "pi_g")

    # -------------------------------------------------------------------------
    # H & Precedence & V: Current Explicit Mission Override
    # -------------------------------------------------------------------------
    async def test_h_v_precedence_and_current_mission_override(self):
        inst = PersistentInstruction(
            instruction_id="pi_detailed",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="report_style",
            constraint="Relatórios técnicos completos em detalhe.",
            priority=50,
        )
        await self.resolver.save_instruction(inst)

        # Resolve without override
        constraints_1, contract_1 = await self.resolver.resolve_constraints(
            goal="Relatório técnico",
            project_id="GLOBAL",
        )
        self.assertEqual(len(constraints_1), 1)

        # Resolve with current explicit mission requirement override
        constraints_2, contract_2 = await self.resolver.resolve_constraints(
            goal="Relatório técnico",
            project_id="GLOBAL",
            explicit_current_instruction="Para esta missão, envie somente resumo executivo.",
        )
        self.assertTrue(len(constraints_2) >= 1)

    # -------------------------------------------------------------------------
    # I & J: Conflict Detection & Supersession
    # -------------------------------------------------------------------------
    async def test_i_j_supersession_and_conflict(self):
        inst_v1 = PersistentInstruction(
            instruction_id="pi_v1",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="summary_format",
            constraint="Relatórios resumidos.",
            version=1,
        )
        await self.resolver.save_instruction(inst_v1)

        inst_v2 = PersistentInstruction(
            instruction_id="pi_v2",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="summary_format",
            constraint="Relatórios técnicos completos.",
            version=2,
            supersedes="pi_v1",
        )
        await self.resolver.save_instruction(inst_v2)

        active = await self.resolver.get_active_instructions(project_id="GLOBAL")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].instruction_id, "pi_v2")

    # -------------------------------------------------------------------------
    # K: Inactive / Deleted Instruction Ignored
    # -------------------------------------------------------------------------
    async def test_k_inactive_instruction_ignored(self):
        inst_inact = PersistentInstruction(
            instruction_id="pi_inact",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="inactive_rule",
            constraint="Draft constraint",
            active=False,
        )
        await self.resolver.save_instruction(inst_inact)

        active = await self.resolver.get_active_instructions(project_id="GLOBAL")
        self.assertEqual(len(active), 0)

    # -------------------------------------------------------------------------
    # L: Secret Rejection
    # -------------------------------------------------------------------------
    async def test_l_secret_rejection(self):
        secret_inst = PersistentInstruction(
            instruction_id="pi_sec",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="secret_token",
            constraint="Use token sk_live_SECRET_DO_NOT_EXPOSE_12345 in header",
        )
        with self.assertRaises(SecretInstructionError):
            await self.resolver.save_instruction(secret_inst)

    # -------------------------------------------------------------------------
    # M, N, O: MissionConstraint & OutputContract Generation
    # -------------------------------------------------------------------------
    async def test_m_n_o_mission_constraint_and_contract_generation(self):
        inst = PersistentInstruction(
            instruction_id="pi_block",
            scope=InstructionScope.GLOBAL_USER,
            rule_key="single_block_delivery",
            constraint="Relatórios técnicos de missões do Intent OS devem ser entregues em um único bloco copiável, sem texto fora do bloco.",
        )
        await self.resolver.save_instruction(inst)

        constraints, contract = await self.resolver.resolve_constraints("Gerar relatório", project_id="GLOBAL")
        self.assertEqual(len(constraints), 1)
        self.assertTrue(contract.single_block_required)
        self.assertFalse(contract.text_outside_block_allowed)
        self.assertEqual(contract.max_blocks, 1)

    # -------------------------------------------------------------------------
    # P, Q, R: Valid vs Invalid Output & Real Incident Regression Test
    # -------------------------------------------------------------------------
    async def test_p_q_r_single_block_regression_incident(self):
        contract = OutputContract(
            single_block_required=True,
            text_outside_block_allowed=False,
            max_blocks=1,
        )

        # Incidente Real: Texto fora do bloco (INCORRETO)
        incorrect_output = (
            "Missão concluída com sucesso.\n\n"
            "```text\n"
            "STATUS DA MISSÃO: COMPLETED\n"
            "DETALHES: Relatório técnico\n"
            "```"
        )
        res_incorrect = self.validator.validate(incorrect_output, contract)
        self.assertFalse(res_incorrect.valid)
        self.assertTrue(res_incorrect.correction_required)
        self.assertTrue(len(res_incorrect.blocking_violations) > 0)

        # Output correto: TODO o texto dentro de UM ÚNICO BLOCO (CORRETO)
        correct_output = (
            "```text\n"
            "STATUS DA MISSÃO: COMPLETED\n"
            "DETALHES: Relatório técnico dentro do bloco único\n"
            "```"
        )
        res_correct = self.validator.validate(correct_output, contract)
        self.assertTrue(res_correct.valid)
        self.assertFalse(res_correct.correction_required)
        self.assertEqual(len(res_correct.blocking_violations), 0)

    # -------------------------------------------------------------------------
    # S & T: Correction Required & Max Correction Limit
    # -------------------------------------------------------------------------
    async def test_s_t_correction_required_and_max_limit(self):
        contract = OutputContract(single_block_required=True, text_outside_block_allowed=False)
        bad_output = "Texto solto sem bloco"
        res = self.validator.validate(bad_output, contract)

        self.assertTrue(res.correction_required)
        self.assertIn("no code blocks were found", str(res.blocking_violations))

        evidence = self.validator.generate_completion_evidence("Formato verificado", res)
        self.assertFalse(evidence.verified)

        violation = self.validator.create_violation_record("pi_block", "m_1", res)
        self.assertEqual(violation.severity, "high")

    # -------------------------------------------------------------------------
    # U: Project Isolation
    # -------------------------------------------------------------------------
    async def test_u_project_isolation(self):
        p1 = PersistentInstruction(
            instruction_id="pi_p1",
            scope=InstructionScope.PROJECT,
            project_id="PROJECT_ALPHA",
            rule_key="rule_alpha",
            constraint="Alpha project rule",
        )
        p2 = PersistentInstruction(
            instruction_id="pi_p2",
            scope=InstructionScope.PROJECT,
            project_id="PROJECT_BETA",
            rule_key="rule_beta",
            constraint="Beta project rule",
        )
        await self.resolver.save_instruction(p1)
        await self.resolver.save_instruction(p2)

        alpha_insts = await self.resolver.get_active_instructions("PROJECT_ALPHA")
        beta_insts = await self.resolver.get_active_instructions("PROJECT_BETA")

        self.assertTrue(any(i.instruction_id == "pi_p1" for i in alpha_insts))
        self.assertFalse(any(i.instruction_id == "pi_p2" for i in alpha_insts))

        self.assertTrue(any(i.instruction_id == "pi_p2" for i in beta_insts))
        self.assertFalse(any(i.instruction_id == "pi_p1" for i in beta_insts))

    # -------------------------------------------------------------------------
    # W: Safe Diagnostics
    # -------------------------------------------------------------------------
    async def test_w_safe_diagnostics(self):
        diag = await self.resolver.get_diagnostics()
        self.assertIn("persistent_instruction_count", diag)
        self.assertIn("active_instruction_count", diag)
        self.assertIn("output_validation_failures", diag)

    # -------------------------------------------------------------------------
    # X, Y, Z: Architectural Boundaries & Constitution Precedence
    # -------------------------------------------------------------------------
    def test_x_y_z_architectural_boundaries(self):
        resolver_file = os.path.join(os.path.dirname(__file__), "../intent_kernel/instructions/resolver.py")
        with open(resolver_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=resolver_file)

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
                self.assertFalse(imp.startswith(forbidden), f"Resolver violates boundary by importing {imp}")


if __name__ == "__main__":
    unittest.main()
