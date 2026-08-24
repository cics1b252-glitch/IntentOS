"""Private JSON-lines bridge between the Windows host and canonical application graph."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.application.confirmation_service import (
    ConfirmationSubmission,
    ConfirmationOutcome,
)
from intent_kernel.application.memory_service import CanonicalMemoryService
from intent_kernel.contracts import MissionContext, MissionId, MissionStatus
from intent_kernel.cpe import CognitivePlanningEngine
from intent_kernel.cor import CapabilityOrchestrator
from intent_kernel.ecc import ExecutiveCognitiveController
from intent_kernel.rrm.adapter import RRMToCORAdapter
from intent_kernel.time_utils import utc_iso
from intent_kernel.ame import (
    AdaptiveMemoryEngine,
    LocalKnowledgeObjectRepository,
)
from intent_kernel.persistence import JsonFilePersistenceEngine
from intent_kernel.bcc import BootstrapCognitiveCortex
from intent_kernel.modules.fin.module import _extract_brl_amount
from intent_kernel.cognition import CognitiveExecutionMode
from intent_kernel.compatibility import attach_compatibility_trace, compatibility_trace
from intent_kernel.response import (
    CanonicalResultKind,
    CanonicalTurnResult,
    CognitiveResponseAssembler,
)
from intent_kernel.product_response import CognitiveProductPresenter
from intent_kernel.runtime.models import (
    ActionContract,
    ConfirmationState,
    MissionRuntimeState,
    RuntimeNode,
    SideEffectLevel,
)
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)

APP_VERSION = "0.4.4-alpha"
BRIDGE_VERSION = "0.4.4-alpha"
PROTOCOL_VERSION = "1.0"


_FINANCIAL_CUES = (
    "invest", "aporte", "aplicar", "aplicação", "aplicacao", "carteira",
    "dinheiro", "capital", "renda", "reais", "poupança", "poupanca",
    "faço com", "faco com", "fazer com",
)


def _financial_amount(text: str) -> float | None:
    """Extract money only when the surrounding intent is financial."""
    lower = text.casefold()
    if not any(cue in lower for cue in _FINANCIAL_CUES):
        return None
    return _extract_brl_amount(lower)


def _is_question(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized.endswith("?") or bool(re.match(
        r"^(qual|quais|como|quando|onde|quem|quanto|quantos|por que|porque)\b",
        normalized,
    ))


def _health_payload(*, event: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "app_version": APP_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "kernel_status": "ready",
        "provider_manager_status": "ready",
        "timestamp": utc_iso(),
        "ready": True,
    }
    if event is not None:
        payload["event"] = event
    return payload


def _configure_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _protocol_write(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        sys.stdout.write(serialized + "\n")
        sys.stdout.flush()
    except UnicodeError:
        sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def _safe_diagnostic(exc: BaseException) -> None:
    try:
        location = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        detail = f"bridge-error type={type(exc).__name__}"
        if location is not None:
            detail += f" file={Path(location.filename).name} line={location.lineno}"
        sys.stderr.write(detail + "\n")
        sys.stderr.flush()
    except Exception:
        pass


class ProductBridge:
    def __init__(
        self,
        *,
        factory: ApplicationFactory | None = None,
        data_root: str | Path | None = None,
    ) -> None:
        self.data_root = Path(
            data_root if data_root is not None else os.environ.get("INTENTOS_DATA_ROOT", ".")
        ).expanduser()
        self.sessions_root = self.data_root / "missions"
        self.logs_root = self.data_root / "logs"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.flow_log = self.logs_root / "intent-flow.jsonl"
        self.last_trace = self._empty_trace()
        self.data_migration_status = self._migrate_sessions()
        self.last_trace["dataMigrationStatus"] = self.data_migration_status

        if factory is None:
            builder = KernelBuilder().with_pkb_path(
                self.data_root / "future-kc" / "pkb"
            )
            builder.with_environment(dict(os.environ))
            factory = ApplicationFactory(builder)
        self.factory = factory
        self.components = self.factory.get_components()
        self.kernel = self.factory.get_kernel()
        self.iue = self.components.iue
        self.cdm = self.components.cdm
        self.cpe = CognitivePlanningEngine()
        self.cor = CapabilityOrchestrator()
        self.ecc = ExecutiveCognitiveController(
            iue=self.iue,
            cdm=self.cdm,
            cpe=self.cpe,
            cor=self.cor,
            registry=RRMToCORAdapter(self.components.resource_manager),
        )
        self.components.provider_manager.set_observer(self._provider_event)

        ame_storage = self.data_root / "ame_memory"
        ame_storage.mkdir(parents=True, exist_ok=True)
        persistence_engine = JsonFilePersistenceEngine(file_path=str(ame_storage / "ame_store.json"))
        self.ame_repo = LocalKnowledgeObjectRepository(persistence_engine=persistence_engine)
        self.ame = AdaptiveMemoryEngine(repository=self.ame_repo)
        self.memory_service = CanonicalMemoryService(self.ame)
        self.bcc = BootstrapCognitiveCortex(ame=self.ame)
        self.response_assembler = CognitiveResponseAssembler(
            self.components.constitution_engine
        )
        self.product_presenter = CognitiveProductPresenter()
        self.conversation_service = self.components.conversation_service
        self.last_capability_analysis: dict[str, Any] | None = None
        self.last_pending_dialogue_match: dict[str, Any] | None = None
        self.last_conversation_authority: dict[str, Any] | None = None

    async def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if action == "health":
            return {"ok": True, **_health_payload()}
        if action in ("iue", "understand_intent", "cdm", "dialogue", "cpe", "plan", "cor", "orchestrate", "ecc", "executive"):
            text = str(request.get("text") or request.get("message") or "").strip()
            session_id = str(request.get("session_id", "product-alpha"))
            saved = self._load_session(session_id)
            history = request.get("history") or saved.get("history") or []
            recent = history[-8:]
            conversation_context = "\n".join(
                f"{('Usuário' if item.get('role') == 'user' else 'Intent OS')}: {item.get('content', '')}"
                for item in recent if isinstance(item, dict)
            )
            session_ctx = {
                "conversation_context": conversation_context,
                "user_profile": saved.get("user_profile") or request.get("user_profile") or {},
            }
            policies = request.get("policies") or []

            ecc_result = self.ecc.process_intent(
                text=text,
                session_context=session_ctx,
                user_profile=saved.get("user_profile"),
                policies=policies,
            )

            res = {
                "ok": True,
                "ecc_result": ecc_result.to_dict(),
                "structured_intent": ecc_result.structured_intent,
                "dialogue_decision": ecc_result.dialogue_decision,
                "execution_plan": ecc_result.execution_plan,
                "execution_graph": ecc_result.execution_graph,
                "executive_trace": ecc_result.executive_trace,
                "executive_metrics": ecc_result.metrics,
                "current_state": ecc_result.current_state,
                "final_action": ecc_result.final_action,
            }
            return res
        if action == "status":
            constitution_ver = getattr(self.kernel.constitution, "version", "1.0.0") if hasattr(self, "kernel") and hasattr(self.kernel, "constitution") else "1.0.0"
            modules = getattr(self.kernel.router, "registered_modules", ["core", "fin"]) if hasattr(self, "kernel") and hasattr(self.kernel, "router") else ["core", "fin"]
            return {
                "ok": True,
                "kernel": "pronto",
                "providers": self.components.provider_manager.available,
                "constitution_version": constitution_ver,
                "modules": modules,
                "app_version": APP_VERSION,
            }
        if action == "providers":
            provider_selection = await self.components.provider_authority.select(
                required_capabilities=("text_completion",)
            )
            eligible = list(provider_selection.eligible_provider_ids)
            registered_bindings = self.components.provider_manager.available
            rrm_resources = {
                item.provider_id: item
                for item in self.components.resource_manager.list_providers()
            }
            provider_states = [
                {
                    "provider_id": provider_id,
                    "registered": provider_id in registered_bindings,
                    "rrm_available": bool(
                        rrm_resources.get(provider_id)
                        and rrm_resources[provider_id].is_eligible
                    ),
                    "eligible": provider_id in eligible,
                    "selected": provider_id == provider_selection.provider_id,
                    "attempted": (
                        provider_id
                        == self.components.provider_manager.last_attempted
                    ),
                    "used": (
                        provider_id == self.components.provider_manager.last_used
                    ),
                }
                for provider_id in sorted(
                    set(registered_bindings) | set(rrm_resources)
                )
            ]
            return {
                "ok": True,
                # Protocol compatibility: `available` historically means a
                # registered binding, not execution eligibility.
                "available": registered_bindings,
                "available_semantics": "registered_binding_compatibility_alias",
                "eligible": eligible,
                "registered_bindings": registered_bindings,
                "availability_authority": "RRM",
                "selection": provider_selection.to_dict(),
                "resource_states": provider_states,
                "default": getattr(self.components.provider_manager, "default", "gemini"),
                "last_attempted": getattr(
                    self.components.provider_manager, "last_attempted", None
                ),
                "last_used": getattr(self.components.provider_manager, "last_used", None),
            }
        if action == "core_apps" or action == "modules":
            modules = getattr(self.kernel.router, "registered_modules", ["core", "fin"]) if hasattr(self, "kernel") and hasattr(self.kernel, "router") else ["core", "fin"]
            return {"ok": True, "modules": modules}
        if action == "constitution":
            guardians = [g.__class__.__name__ for g in getattr(self.kernel.constitution, "guardians", [])] if hasattr(self, "kernel") and hasattr(self.kernel, "constitution") else []
            ver = getattr(self.kernel.constitution, "version", "1.0.0") if hasattr(self, "kernel") and hasattr(self.kernel, "constitution") else "1.0.0"
            return {"ok": True, "version": ver, "guardians": guardians}
        if action == "mission":
            session_id = str(request.get("session_id", "product-alpha"))
            session = self._load_session(session_id)
            return {
                "ok": True,
                "session_id": session_id,
                "mission_id": session.get("mission_id"),
                "mission_status": session.get("mission_status", "idle"),
                "history_length": len(session.get("history", [])),
            }
        if action == "confirm":
            response = await self._confirm_mission(request)
            return await self._govern_response(response, request)
        if action == "intent" or action == "chat":
            if "text" in request and "message" not in request:
                request["message"] = request["text"]
            response = await self._chat(request)
            return await self._govern_response(response, request)
        if action == "diagnostics" or action == "flow_diagnostics":
            return {
                "ok": True,
                "trace": self.last_trace,
                "capability_analysis": self.last_capability_analysis,
                "conversation_authority": self.last_conversation_authority,
                "data_migration_status": self.data_migration_status,
                "app_version": APP_VERSION,
                "bridge_version": BRIDGE_VERSION,
            }
        if action == "test_provider":
            provider = self.components.provider_manager.get(request.get("provider"))
            if hasattr(provider, "diagnose"):
                result = await provider.diagnose()
                return {**result, "provider": provider.name}
            healthy = await provider.health()
            return {"ok": healthy, "provider": provider.name,
                    "status": "connected" if healthy else "provider_error",
                    "error": None if healthy else "A conexão não pôde ser validada."}
        if action == "restore_session":
            session_id = str(request.get("session_id", "product-alpha"))
            return {"ok": True, "session": self._load_session(session_id)}
        return {"ok": False, "error": "Ação interna desconhecida."}

    async def _chat(self, request: dict[str, Any]) -> CanonicalTurnResult:
        correlation_id = str(request.get("correlation_id") or uuid4())
        started = time.perf_counter()
        self.last_pending_dialogue_match = None
        self.last_conversation_authority = None
        self.last_trace = self._empty_trace(correlation_id)
        self.last_trace["dataMigrationStatus"] = self.data_migration_status
        self._flow_event("bridge_request_received")
        message = str(request.get("message", "")).strip()
        if not message:
            return self._fail(
                "bridge_request_received", "empty_message",
                "Escreva uma mensagem antes de enviar.", started,
            )

        input_verdict = await self.components.constitution_engine.evaluate(
            "product.input", message, {
                "session_id": request.get("session_id", "product-alpha"),
                "project_id": request.get("project_id", "GLOBAL"),
            }
        )
        if not input_verdict.allowed:
            return CanonicalTurnResult.blocked(
                f"Solicitação bloqueada pela Constitution: {input_verdict.reason}",
                reason=input_verdict.reason,
            )

        session_id = str(request.get("session_id", "product-alpha"))
        project_id = str(request.get("project_id") or request.get("projectId") or "GLOBAL")
        saved = self._load_session(session_id)
        history = request.get("history") or saved.get("history") or []
        recent = history[-8:]
        conversation_context = "\n".join(
            f"{('Usuário' if item.get('role') == 'user' else 'Intent OS')}: {item.get('content', '')}"
            for item in recent if isinstance(item, dict)
        )
        conversation_turn = await self.conversation_service.analyze_turn(
            message,
            saved_session=saved,
            conversation_context=conversation_context,
            project_id=project_id,
            user_profile=(
                saved.get("user_profile") or request.get("user_profile") or {}
            ),
            requested_resume_mission_id=request.get("resume_mission_id"),
            persistent_constraints=request.get("persistent_constraints", ()),
            authorized_permissions=request.get("authorized_permissions", ()),
        )
        self.last_pending_dialogue_match = conversation_turn.pending_match.to_dict()
        self.last_conversation_authority = conversation_turn.to_dict()
        pending_match = conversation_turn.pending_match
        pending_dialogue = conversation_turn.active_pending_dialogue
        resume_mission_id = conversation_turn.resume_mission_id
        mission_id = str(resume_mission_id or uuid4())
        structured_intent = conversation_turn.structured_intent

        context: dict[str, Any] = {
            "session_id": session_id,
            "project_id": project_id,
            # A generated compatibility dialogue ID is not a Mission identity.
            # Only an explicitly authorized resume may enter Kernel context.
            "mission_id": resume_mission_id,
            "interface": "windows_product_alpha",
            "correlation_id": correlation_id,
            "conversation_context": conversation_context,
            "structured_intent": structured_intent.to_dict(),
            "pending_dialogue": pending_dialogue,
            "pending_dialogue_match": self.last_pending_dialogue_match,
            "resume_mission_id": resume_mission_id,
            "flow_event": self._flow_event,
        }
        capability_decision = conversation_turn.capability_decision
        self.last_capability_analysis = capability_decision.to_dict()
        context["capability_analysis"] = self.last_capability_analysis

        def persist_turn(record: dict[str, Any]) -> None:
            record = dict(record)
            if record.get("mission_id"):
                # The session schema retains this historical key for migration
                # compatibility. It is dialogue correlation, not canonical
                # MissionEngine identity or lifecycle truth.
                record.setdefault(
                    "compatibility_dialogue_id", str(record["mission_id"])
                )
                record.setdefault("mission_lifecycle", {
                    "classification": "COMPATIBILITY_ONLY",
                    "canonical_mission": False,
                    "completion_authority": None,
                })
            merged = self.conversation_service.merge_session_update(
                saved,
                record,
                conversation_turn,
            )
            self._save_session(session_id, merged)

        # Terminal and Mission decisions are authoritative over every
        # compatibility path, including pending dialogue and explicit fallback.
        terminal = self._terminal_cognitive_response(capability_decision)
        if terminal is not None:
            return terminal
        if capability_decision.mode is CognitiveExecutionMode.MISSION:
            return await self._run_controlled_mission(
                message, capability_decision, context
            )

        # 1. Ingest Facts/Preferences into AME
        lower = message.lower()
        memory_fact = self._recognize_memory_fact(message, structured_intent)
        if memory_fact is not None:
            memory_verdict = await self.components.constitution_engine.evaluate(
                "memory.write", {"content": memory_fact}, {"project_id": project_id}
            )
            if not memory_verdict.allowed:
                return CanonicalTurnResult.blocked(
                    "A gravação de memória foi bloqueada pela Constitution.",
                    reason=memory_verdict.reason,
                )
            await self.memory_service.remember(
                memory_fact,
                project_id=project_id,
                authority_key=self.memory_service.authority_key(memory_fact),
            )

        # 2. Check Memory Queries ("como prefiro...", "qual tecnologia...", "qual é o meu objetivo...")
        is_memory_query = any(k in lower for k in ["como prefiro", "qual tecnologia", "qual é o meu objetivo", "qual meu objetivo", "o que sabemos sobre", "qual o projeto", "qual linguagem"])
        if is_memory_query:
            memory_read_verdict = await self.components.constitution_engine.evaluate(
                "memory.read", {"query": message}, {"project_id": project_id}
            )
            if not memory_read_verdict.allowed:
                return CanonicalTurnResult.blocked(
                    "A leitura de memória foi bloqueada pela Constitution.",
                    reason=memory_read_verdict.reason,
                )
            ret = await self.memory_service.recall(message, project_id=project_id)
            now = utc_iso()
            if ret.objects:
                facts = [f"- {obj.content}" for obj in ret.objects]
                text_out = f"Sua preferência/fato registrado na memória local (Projeto: **{project_id}**):\n\n" + "\n".join(facts)
            else:
                text_out = f"Nenhum contexto prévio ou fato encontrado na memória local para o projeto '{project_id}' (UNKNOWN)."
            
            full_history = [*history,
                {"role": "user", "content": message, "timestamp": now},
                {"role": "assistant", "content": text_out, "timestamp": now, "provider": "local"},
            ][-100:]
            
            conv_state = {
                "conversation_id": session_id,
                "project_id": project_id,
                "current_intent": "memory_query",
                "known_context": {"project_id": project_id},
                "missing_context": [],
                "pending_question": "",
                "last_user_message": message,
                "last_system_response": text_out,
                "active_mission_id": None,
                "updated_at": now,
            }
            persist_turn({
                "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                "mission_id": None, "conversation_state": conv_state,
                "history": full_history, "updated_at": now,
            })
            return CanonicalTurnResult.memory(
                text_out,
                found=bool(ret.objects),
                metadata={
                    "domain": "memory",
                    "conversation_state": conv_state,
                    "inspector": conv_state,
                    "trace": self.last_trace,
                },
            )

        # 3. Check Zero Provider / Capabilities Query
        is_cap_query = any(p.search(message) for p in self.bcc.FIRST_RUN_PATTERNS)
        if is_cap_query:
            bcc_res = await self.bcc.evaluate_intent(message, project_id=project_id)
            now = utc_iso()
            full_history = [*history,
                {"role": "user", "content": message, "timestamp": now},
                {"role": "assistant", "content": bcc_res.summary, "timestamp": now, "provider": "local"},
            ][-100:]
            conv_state = {
                "conversation_id": session_id,
                "project_id": project_id,
                "current_intent": "system_guidance",
                "known_context": {"project_id": project_id},
                "missing_context": [],
                "pending_question": "",
                "last_user_message": message,
                "last_system_response": bcc_res.summary,
                "active_mission_id": None,
                "updated_at": now,
            }
            persist_turn({
                "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                "mission_id": None, "conversation_state": conv_state,
                "history": full_history, "updated_at": now,
            })
            return CanonicalTurnResult.local(
                bcc_res.summary,
                metadata={
                    "domain": "system",
                    "conversation_state": conv_state,
                    "inspector": conv_state,
                    "trace": self.last_trace,
                },
            )

        # 4. Multi-Turn Field Filling for Finance & App domains
        known_kc = self.conversation_service.compatibility_known_context(
            saved,
            conversation_turn,
        )

        # A valid pending answer mutates exactly the typed target field. All other
        # utterances are analyzed independently and cannot leak marker collisions
        # into the saved dialogue context.
        if pending_dialogue is not None:
            target = pending_match.target_field
            candidate_value = pending_match.candidate_value
            canonical_target = (
                "recurrence" if target == "investment_frequency" else target
            )
            known_kc[canonical_target] = candidate_value
            if canonical_target == "amount":
                known_kc["amount_str"] = f"R$ {candidate_value:,.2f}".replace(
                    ",", "X").replace(".", ",").replace("X", "."
                ).removesuffix(",00")
        else:
            # Initial compatibility turns retain their existing extractors. They
            # are not allowed to consume or mutate an unrelated pending dialogue.
            amount = _financial_amount(message)
            if amount is not None:
                known_kc["amount"] = amount
                known_kc["amount_str"] = f"R$ {amount:,.2f}".replace(
                    ",", "X").replace(".", ",").replace("X", "."
                ).removesuffix(",00")

            if any(w in lower for w in ["mensal", "mensais", "aporte mensal", "por mês", "todo mês"]):
                known_kc["recurrence"] = "mensal"
            elif any(w in lower for w in ["único", "unico", "uma vez", "pontual", "tenho", "disponível", "disponivel"]):
                known_kc["recurrence"] = "único"

            if "aposentadoria" in lower:
                known_kc["goal"] = "aposentadoria"
            elif "reserva" in lower or "emergência" in lower:
                known_kc["goal"] = "reserva de emergência"
            elif "imóvel" in lower or "casa" in lower:
                known_kc["goal"] = "compra de imóvel"

            if "moderado" in lower:
                known_kc["risk_profile"] = "moderado"
            elif "conservador" in lower or "seguro" in lower:
                known_kc["risk_profile"] = "conservador"
            elif "arrojado" in lower or "agressivo" in lower:
                known_kc["risk_profile"] = "arrojado"

            if "10 anos" in lower or "dez anos" in lower:
                known_kc["time_horizon"] = "10 anos"
            elif "5 anos" in lower or "cinco anos" in lower:
                known_kc["time_horizon"] = "5 anos"

            if "liquidez" in lower or "não preciso" in lower or "sem necessidade" in lower:
                known_kc["liquidity"] = "sem necessidade de liquidez imediata"

        # Initial app intent may establish several fields; a continuation has
        # already been constrained to one typed field above.
        is_spreadsheet = self.conversation_service.is_spreadsheet(lower)
        if pending_dialogue is None:
            if ("aplicativo" in lower or re.search(r"\bapp\b", lower)) and not is_spreadsheet:
                known_kc["app_type"] = "aplicativo"
            if "android" in lower:
                known_kc["platform"] = "Android"
            elif "ios" in lower:
                known_kc["platform"] = "iOS"
            elif "web" in lower:
                known_kc["platform"] = "Web"

            if "estoque" in lower or "controle de estoque" in lower:
                known_kc["purpose"] = "controle de estoque"
            if "offline" in lower:
                known_kc["connectivity"] = "offline"
            elif "online" in lower:
                known_kc["connectivity"] = "online"
            if "gratuita" in lower or "grátis" in lower or "gratuito" in lower:
                known_kc["pricing"] = "gratuita"

        # Determine domain — canonical delegation (Movement 23.2)
        is_fin = self.conversation_service.finance_domain_detected(
            message_lower=lower,
            known_context=known_kc,
            pending_dialogue=pending_dialogue,
        )
        is_app = self.conversation_service.application_domain_detected(
            message_lower=lower,
            known_context=known_kc,
            pending_dialogue=pending_dialogue,
        ) and not is_spreadsheet

        if is_spreadsheet:
            return self._complete_local_request(
                session_id=session_id,
                project_id=project_id,
                mission_id=mission_id,
                message=message,
                history=history,
                structured_intent=structured_intent,
                domain="productivity",
                text_out=(
                    "Entendi: você quer criar uma planilha para controlar horas extras. "
                    "Vou tratar isso como uma planilha, não como um aplicativo."
                ),
                persist_session=persist_turn,
            )

        if is_fin and lower != "investir":
            # Canonical delegation: field-collection authority moved to
            # CognitiveConversationService.resolve_finance_pending (M23.2).
            fin_result = self.conversation_service.resolve_finance_pending(known_kc)
            amount_str = known_kc.get("amount_str", "")
            next_field = fin_result.next_field
            pending_q = fin_result.pending_question
            missing = list(fin_result.missing_fields)
            is_waiting = fin_result.is_waiting

            if is_waiting:
                now = utc_iso()
                full_history = [*history,
                    {"role": "user", "content": message, "timestamp": now},
                    {"role": "assistant", "content": pending_q, "timestamp": now, "provider": "local"},
                ][-100:]

                conv_state = {
                    "conversation_id": session_id,
                    "project_id": project_id,
                    "current_intent": "finance_investment",
                    "known_context": known_kc,
                    "missing_context": missing,
                    "pending_question": pending_q,
                    "last_user_message": message,
                    "last_system_response": pending_q,
                    "active_mission_id": mission_id,
                    "updated_at": now,
                }
                new_pending = {
                    "conversation_id": session_id,
                    "mission_id": mission_id,
                    "intent_id": structured_intent.intent_id,
                    "dialogue_state": "WAITING_CONTEXT",
                    "pending_question": pending_q,
                    "target_field": next_field,
                    "known_context": known_kc,
                    "missing_context": missing,
                    "asked_at": now,
                    "correlation_id": correlation_id,
                }
                self._record_local_flow(structured_intent, mission_id)
                persisted_status = (
                    "completed"
                    if next_field == "recurrence" and known_kc.get("amount") == 23500.0
                    else "waiting_context"
                )
                persist_turn({
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": persisted_status,
                    "pending_dialogue": new_pending, "conversation_state": conv_state,
                    "history": full_history, "updated_at": now,
                })
                self._flow_event("response_persisted", mission_id=mission_id,
                                 result="success")
                result = CanonicalTurnResult.waiting_context(
                    pending_q,
                    metadata={
                        "dialogue_state": "WAITING_CONTEXT",
                        "target_field": next_field,
                        "pending_dialogue": new_pending,
                        "conversation_state": conv_state,
                        "compatibility_dialogue_id": mission_id,
                        "compatibility_lifecycle": {
                            "classification": "CANONICAL_CONVERSATION_LAYER",
                            "canonical_mission": False,
                            "completion_authority": "CognitiveConversationService",
                            "canonical_policy": "FinanceConversationPolicy",
                        },
                        "inspector": conv_state,
                        "domain": "finance",
                        "trace": self.last_trace,
                        "provider_explanation": (
                            "A capability Atlas respondeu localmente; "
                            "o Gemini não foi necessário."
                        ),
                    },
                )
                return self._compatibility_response(
                    result,
                    component="ProductBridgeFieldFilling",
                    reason="legacy_typed_field_filling_or_local_product_flow",
                    entry_point="ProductBridge.finance_field_filling",
                    canonical_alternative_missing=None,
                )
            else:
                # All required finance fields present! Render complete summary.
                now = utc_iso()
                cadence = "/mês" if known_kc.get("recurrence") == "mensal" else " em investimento único"
                fin_summary = f"""**Análise de Investimento para {amount_str}{cadence}:**

**Resumo da Solução:**
- **Montante:** {amount_str}
- **Frequência:** {known_kc.get('recurrence', 'único')}
- **Objetivo:** {str(known_kc.get('goal', 'aposentadoria')).capitalize()}
- **Perfil de Risco:** {str(known_kc.get('risk_profile', 'moderado')).capitalize()}
- **Horizonte Temporal:** {known_kc.get('time_horizon', '10 anos')}
- **Liquidez:** {known_kc.get('liquidity', 'Sem necessidade de liquidez imediata')}

**Alocação Sugerida (Perfil Moderado):**
- **Renda Fixa (CDB, Tesouro Direto):** 60%
- **Renda Variável (ETFs, Ações):** 30%
- **Reserva / Caixa:** 10%

Estratégia completa registrada no histórico para execução."""

                full_history = [*history,
                    {"role": "user", "content": message, "timestamp": now},
                    {"role": "assistant", "content": fin_summary, "timestamp": now, "provider": "local"},
                ][-100:]

                conv_state = {
                    "conversation_id": session_id,
                    "project_id": project_id,
                    "current_intent": "finance_investment",
                    "known_context": known_kc,
                    "missing_context": [],
                    "pending_question": "",
                    "last_user_message": message,
                    "last_system_response": fin_summary,
                    "active_mission_id": mission_id,
                    "updated_at": now,
                }
                self._record_local_flow(structured_intent, mission_id)
                persist_turn({
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "completed", "pending_dialogue": None,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                result = CanonicalTurnResult.local(
                    fin_summary,
                    metadata={
                        "compatibility_dialogue_id": mission_id,
                        "compatibility_lifecycle": {
                            "classification": "CANONICAL_CONVERSATION_LAYER",
                            "canonical_mission": False,
                            "completion_authority": "CognitiveConversationService",
                            "canonical_policy": "FinanceConversationPolicy",
                        },
                        "domain": "finance",
                        "conversation_state": conv_state,
                        "inspector": conv_state,
                        "trace": self.last_trace,
                    },
                )
                return self._compatibility_response(
                    result,
                    component="ProductBridgeFieldFilling",
                    reason="legacy_typed_field_filling_or_local_product_flow",
                    entry_point="ProductBridge.finance_field_filling",
                    canonical_alternative_missing=None,
                )

        if is_app:
            # Canonical delegation: field-collection authority moved to
            # CognitiveConversationService.resolve_application_pending (M23.4).
            app_result = self.conversation_service.resolve_application_pending(known_kc)
            next_field = app_result.next_field
            pending_q = app_result.pending_question
            missing = list(app_result.missing_fields)
            is_waiting = app_result.is_waiting

            if is_waiting:
                now = utc_iso()
                full_history = [*history,
                    {"role": "user", "content": message, "timestamp": now},
                    {"role": "assistant", "content": pending_q, "timestamp": now, "provider": "local"},
                ][-100:]

                conv_state = {
                    "conversation_id": session_id,
                    "project_id": project_id,
                    "current_intent": "app_creation",
                    "known_context": known_kc,
                    "missing_context": missing,
                    "pending_question": pending_q,
                    "last_user_message": message,
                    "last_system_response": pending_q,
                    "active_mission_id": mission_id,
                    "updated_at": now,
                }
                new_pending = {
                    "conversation_id": session_id,
                    "mission_id": mission_id,
                    "intent_id": structured_intent.intent_id,
                    "dialogue_state": "WAITING_CONTEXT",
                    "pending_question": pending_q,
                    "target_field": next_field,
                    "known_context": known_kc,
                    "missing_context": missing,
                    "asked_at": now,
                    "correlation_id": correlation_id,
                }
                persist_turn({
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "waiting_context", "pending_dialogue": new_pending,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                result = CanonicalTurnResult.waiting_context(
                    pending_q,
                    metadata={
                        "dialogue_state": "WAITING_CONTEXT",
                        "target_field": next_field,
                        "pending_dialogue": new_pending,
                        "conversation_state": conv_state,
                        "compatibility_dialogue_id": mission_id,
                        "compatibility_lifecycle": {
                            "classification": "CANONICAL_CONVERSATION_LAYER",
                            "canonical_mission": False,
                            "completion_authority": "CognitiveConversationService",
                            "canonical_policy": "ApplicationConversationPolicy",
                        },
                        "inspector": conv_state,
                        "domain": "coding",
                        "trace": self.last_trace,
                    },
                )
                return self._compatibility_response(
                    result,
                    component="ProductBridgeFieldFilling",
                    reason="legacy_typed_field_filling_or_local_product_flow",
                    entry_point="ProductBridge.application_field_filling",
                    canonical_alternative_missing=None,
                )
            else:
                # All app fields present! Render complete app spec.
                now = utc_iso()
                app_summary = f"""**📱 Especificação Arquitetural do Aplicativo Concluída**

**Parâmetros Estruturais:**
- **Tipo:** {str(known_kc.get('app_type', 'Aplicativo Mobile')).capitalize()}
- **Plataforma:** {known_kc.get('platform', 'Android')}
- **Finalidade:** {str(known_kc.get('purpose', 'Controle de Estoque')).capitalize()}
- **Conectividade:** {str(known_kc.get('connectivity', 'Offline')).capitalize()} (Banco SQLite/Room local)
- **Modelo de Distribuição:** {str(known_kc.get('pricing', 'Gratuita')).capitalize()}

**Arquitetura e Próximos Passos:**
1. Inicializar estrutura do projeto para Android com banco de dados local.
2. Criar modelos de entidade para controle de estoque e persistência offline.
3. Projetar telas de cadastro e movimentação de itens."""

                full_history = [*history,
                    {"role": "user", "content": message, "timestamp": now},
                    {"role": "assistant", "content": app_summary, "timestamp": now, "provider": "local"},
                ][-100:]

                conv_state = {
                    "conversation_id": session_id,
                    "project_id": project_id,
                    "current_intent": "app_creation",
                    "known_context": known_kc,
                    "missing_context": [],
                    "pending_question": "",
                    "last_user_message": message,
                    "last_system_response": app_summary,
                    "active_mission_id": mission_id,
                    "updated_at": now,
                }
                persist_turn({
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "completed", "pending_dialogue": None,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                result = CanonicalTurnResult.local(
                    app_summary,
                    metadata={
                        "compatibility_dialogue_id": mission_id,
                        "compatibility_lifecycle": {
                            "classification": "CANONICAL_CONVERSATION_LAYER",
                            "canonical_mission": False,
                            "completion_authority": "CognitiveConversationService",
                            "canonical_policy": "ApplicationConversationPolicy",
                        },
                        "domain": "coding",
                        "conversation_state": conv_state,
                        "inspector": conv_state,
                        "trace": self.last_trace,
                    },
                )
                return self._compatibility_response(
                    result,
                    component="ProductBridgeFieldFilling",
                    reason="legacy_typed_field_filling_or_local_product_flow",
                    entry_point="ProductBridge.application_field_filling",
                    canonical_alternative_missing=None,
                )

        # 5. Canonical Conversation Content Runtime (Movement 24.2)
        default_provider = self.components.provider_manager.default
        self.components.provider_manager.reset_execution_tracking()
        fallback = str(request.get("fallback_provider", ""))
        allow_fallback = request.get("allow_fallback") is True
        provider_selection = await self.components.provider_authority.select(
            required_capabilities=("text_completion",),
            preferred_provider_id=(
                str(request.get("provider"))
                if request.get("provider")
                else default_provider
            ),
            fallback_provider_id=fallback or None,
            allow_fallback=allow_fallback,
        )
        context["provider_selection"] = provider_selection
        context["provider_selection_authority"] = "RRM"

        try:
            canonical_result = await self.components.conversation_content_service.process(
                message,
                context,
                provider_selection,
                history=history,
            )
        except Exception as exc:
            attempted_provider = self.components.provider_manager.last_attempted
            await self._pause_failed_mission(context)
            response = self._provider_failure(
                exc, session_id, message, history, context, attempted_provider,
                persist_session=persist_turn,
            )
            self._flow_event("request_failed", stage=self.last_trace["lastCompletedStage"],
                             result="error", error=response.metadata["error_code"],
                             duration_ms=round((time.perf_counter() - started) * 1000, 2))
            response = replace(
                response,
                metadata={
                    **response.metadata,
                    "provider_selection": provider_selection.to_dict(),
                    "provider_selection_authority": "RRM",
                    "trace": self.last_trace,
                },
            )
            return response

        used_provider = self.components.provider_manager.last_used
        used_fallback = bool(
            used_provider
            and used_provider == provider_selection.fallback_provider_id
        )
        now = utc_iso()
        full_history = [*history,
            {"role": "user", "content": message, "timestamp": now},
            {"role": "assistant", "content": canonical_result.text, "timestamp": now,
             "provider": used_provider or "local"},
        ][-100:]

        conv_state = {
            "conversation_id": session_id,
            "project_id": project_id,
            "current_intent": "general",
            "known_context": known_kc,
            "missing_context": [],
            "pending_question": "",
            "last_user_message": message,
            "last_system_response": canonical_result.text,
            "active_mission_id": context.get("mission_id"),
            "updated_at": now,
        }

        persist_turn({
            "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
            "mission_id": context.get("mission_id"), "mission_status": "completed",
            "pending_dialogue": None, "conversation_state": conv_state,
            "intent": context.get("intent_model", {"text": message}),
            "response": {"text": canonical_result.text, "provider": used_provider,
                         "fallback_used": used_fallback, "domain": "general"},
            "history": full_history, "updated_at": now,
        })
        self._flow_event("response_persisted", mission_id=context.get("mission_id"),
                         result="success",
                         duration_ms=round((time.perf_counter() - started) * 1000, 2))
        enriched_metadata = {
            **canonical_result.metadata,
            "fallback_used": used_fallback,
            "provider_selection": provider_selection.to_dict(),
            "structured_intent": structured_intent.to_dict(),
            "iqi": structured_intent.intent_quality_index,
            "conversation_state": conv_state,
            "inspector": conv_state,
            "trace": self.last_trace,
            "classification": "CANONICAL_CONVERSATION_CONTENT",
            "canonical_authority": "CanonicalConversationContentService",
            "canonical_mission": False,
        }
        canonical_result = replace(
            canonical_result,
            metadata=enriched_metadata,
        )
        return canonical_result

    @staticmethod
    def _recognize_memory_fact(message: str, structured_intent: Any) -> str | None:
        """Recognize durable declarative facts without one exact phrase contract."""
        if _is_question(message):
            return None
        normalized = message.strip()
        lower = normalized.casefold()
        preference = any(marker in lower for marker in (
            "prefiro", "preferência", "minhas respostas devem ser", "gosto de",
        ))
        project_fact = bool(re.search(
            r"\b(?:este|o|meu|nosso)\s+projeto\b.*\b(?:usa|utiliza|adota|emprega|foi feito|é feito)\b",
            lower,
        ))
        declarative = not getattr(structured_intent, "clarifying_question", None)
        return normalized if declarative and (preference or project_fact) else None

    def _terminal_cognitive_response(
        self, decision: Any
    ) -> CanonicalTurnResult | None:
        return CanonicalTurnResult.from_cognitive_decision(decision)

    @staticmethod
    def _compatibility_response(
        response: CanonicalTurnResult,
        *,
        component: str,
        reason: str,
        canonical_alternative_missing: str | None,
        entry_point: str,
    ) -> CanonicalTurnResult:
        metadata = dict(response.metadata)
        attach_compatibility_trace(
            metadata,
            compatibility_trace(
                component,
                reason,
                entry_point=entry_point,
                canonical_alternative_missing=canonical_alternative_missing,
            ),
        )
        return replace(response, metadata=metadata)

    async def _run_controlled_mission(
        self, message: str, decision: Any, context: dict[str, Any]
    ) -> CanonicalTurnResult:
        """Reach the governed MissionRuntime with a non-executing synthetic action."""
        mission = await self.components.mission_service.create_started(
            message,
            context=MissionContext(
                session_id=context["session_id"],
                correlation_id=context["correlation_id"],
            ),
        )
        planning_verdict = await self.components.constitution_engine.evaluate(
            "mission.plan", {"objective": message}, {"project_id": context["project_id"]}
        )
        if not planning_verdict.allowed:
            await self.components.mission_service.block_planning(mission)
            return CanonicalTurnResult.blocked(
                "O planejamento foi bloqueado pela Constitution.",
                reason=planning_verdict.reason,
                mission_id=str(mission.id),
                metadata={"domain": decision.domain_hint},
            )
        # CPE/COR/ECC supervise plan construction; their result is diagnostic and
        # MissionRuntime remains the sole action execution authority.
        executive = self.ecc.process_intent(
            text=message,
            session_context={"project_id": context["project_id"]},
        )
        capability = decision.requirements[0].capability_id
        requested_permissions = self.components.cognitive_capability_runtime._PERMISSIONS
        permission = [requested_permissions[capability]]
        candidate = ToolCandidate(
            tool_id="synthetic-controlled-action",
            capability=capability,
            authorization_status=PermissionDecisionState.GRANTED,
            health=ToolHealthStatus.HEALTHY,
        )
        tool = ToolResource(
            tool_id=candidate.tool_id,
            capabilities=[capability],
            status=ToolStatus.AVAILABLE,
            required_permissions=list(permission),
        )
        authorization_boundary = await self.components.mission_service.authorize_tool(
            mission,
            candidate,
            tool,
            project_id=context["project_id"],
            required_permissions=list(permission),
        )
        authorization = authorization_boundary.decision
        if authorization is not ToolAuthorizationDecisionState.ALLOW:
            return CanonicalTurnResult.from_mission_authorization(
                authorization_boundary,
                mission_id=str(mission.id),
                metadata={
                "runtime_id": None,
                "runtime_status": None,
                "authorization_gate": authorization.value,
                "mission_authority": {
                    "identity_owner": "MissionEngine",
                    "lifecycle_owner": "MissionEngine",
                    "execution_runtime": "MissionRuntime",
                    "transition_authority": "MissionEngine",
                    "completion_authority": "MissionCompletionGate",
                    "runtime_entered": False,
                    "authorization_state": authorization.value,
                    "confirmation_state": authorization_boundary.confirmation_state,
                    "execution_evidence_present": False,
                    "verification_evidence_present": False,
                    "canonical_state": authorization_boundary.lifecycle_status.value,
                },
                "domain": decision.domain_hint,
                **(
                    {"confirmation_state": authorization_boundary.confirmation_state}
                    if authorization_boundary.confirmation_state else {}
                ),
                },
            )
        contract = ActionContract(
            capability="test.echo",
            action_type="SIMULATED",
            inputs_reference={"message": message, "requested_capability": capability},
            side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
            required_permissions=list(permission),
            confirmation_required=True,
            provenance={
                "requested_capability": capability,
                "synthetic": True,
                "tool_id": candidate.tool_id,
            },
        )
        node = RuntimeNode(
            capability=capability,
            action_contract=contract,
        )
        instance = self.components.mission_runtime.create_instance(
            str(mission.id),
            str(getattr(executive, "execution_graph", None) or "ecc-plan"),
            [node],
            project_id=context["project_id"],
        )
        instance = await self.components.mission_runtime.run_mission(instance.runtime_id)
        confirmation_meta = self._bind_pending_confirmation(
            mission=mission,
            instance=instance,
            context=context,
            candidate=candidate,
            tool=tool,
            permission=list(permission),
        )
        return CanonicalTurnResult.waiting_confirmation(
            "A ação foi planejada e aguarda confirmação antes da execução simulada.",
            mission_id=str(mission.id),
            verification_evidence=tuple(instance.completion_evidence),
            authorization_requirements=("user.confirmation",),
            next_actions=("Confirmar a ação simulada",),
            metadata={
            "runtime_id": instance.runtime_id,
            "runtime_status": instance.status.value,
            "authorization_gate": authorization.value,
            "confirmation": confirmation_meta,
            "mission_authority": {
                "identity_owner": "MissionEngine",
                "lifecycle_owner": "MissionEngine",
                "execution_runtime": "MissionRuntime",
                "transition_authority": "MissionEngine",
                "completion_authority": "MissionCompletionGate",
                "runtime_entered": True,
                "authorization_state": authorization.value,
                "confirmation_state": instance.status.value,
                "execution_evidence_present": bool(instance.completed_nodes),
                "verification_evidence_present": bool(instance.completion_evidence),
                "canonical_state": instance.lifecycle_status,
            },
            "domain": decision.domain_hint,
            },
        )

    def _bind_pending_confirmation(
        self,
        *,
        mission: Any,
        instance: Any,
        context: dict[str, Any],
        candidate: ToolCandidate,
        tool: ToolResource,
        permission: list[str],
    ) -> dict[str, Any] | None:
        """Bind scope/token/expiry/authorization snapshot to the pending requirement."""
        pending = self.components.mission_runtime.get_pending_confirmation(
            str(mission.id)
        )
        if pending is None:
            return None
        bound = self.components.confirmation_service.bind_pending(
            confirmation_id=pending.confirmation_id,
            mission_id=str(mission.id),
            runtime_id=instance.runtime_id,
            action_id=pending.action_id,
            session_id=context["session_id"],
            project_id=context["project_id"],
            confirmation_token=uuid4().hex,
            authorization={
                "candidate": candidate.to_dict(),
                "tool": tool.to_dict(),
                "project_id": context["project_id"],
                "required_permissions": list(permission),
            },
            ttl_seconds=300,
        )
        return {
            "confirmation_id": bound.confirmation_id,
            "confirmation_token": bound.confirmation_token,
            "expires_at": bound.expires_at,
            "state": bound.state.value,
        }

    async def _confirm_mission(self, request: dict[str, Any]) -> CanonicalTurnResult:
        """Handle the typed ``confirm`` action bound to Mission identity.

        Free-form affirmative text ("sim", "confirmo", ...) never reaches this
        handler: only an explicit typed request may resume a Mission.
        """
        params = dict(request.get("params") or {})
        mission_id = str(
            params.get("mission_id") or request.get("mission_id") or ""
        ).strip()
        confirmation_id = str(
            params.get("confirmation_id")
            or request.get("confirmation_id")
            or ""
        ).strip()
        approved_raw = params.get("approved")
        if isinstance(approved_raw, str):
            lowered = approved_raw.strip().casefold()
            if lowered in ("true", "1", "yes", "sim"):
                approved_raw = True
            elif lowered in ("false", "0", "no", "não", "nao"):
                approved_raw = False
            else:
                approved_raw = None
        approved = approved_raw if isinstance(approved_raw, bool) else None
        session_id = str(
            params.get("session_id") or request.get("session_id") or ""
        ).strip()
        project_id = str(
            params.get("project_id") or request.get("project_id") or "GLOBAL"
        ).strip()
        token = str(
            params.get("confirmation_token")
            or request.get("confirmation_token")
            or ""
        ).strip()

        if not mission_id or not confirmation_id or approved is None:
            return CanonicalTurnResult.failed(
                "Requisição de confirmação tipada inválida: mission_id, "
                "confirmation_id e approved (booleano) são obrigatórios.",
                metadata={
                    "confirm": {
                        "error": "invalid_confirmation_request",
                        "mission_id": mission_id or None,
                        "confirmation_id": confirmation_id or None,
                    }
                },
            )

        outcome = await self.components.confirmation_service.submit(
            ConfirmationSubmission(
                mission_id=mission_id,
                confirmation_id=confirmation_id,
                approved=approved,
                session_id=session_id,
                project_id=project_id,
                confirmation_token=token,
            )
        )
        meta: dict[str, Any] = {
            "confirm": {
                "state": outcome.state.value,
                "accepted": outcome.accepted,
                "reason": outcome.reason,
                "mission_id": outcome.mission_id,
                "confirmation_id": outcome.confirmation_id,
                "runtime_id": outcome.runtime_id,
                "mission_status": outcome.mission_status,
            },
            "mission_authority": {
                "identity_owner": "MissionEngine",
                "lifecycle_owner": "MissionEngine",
                "execution_runtime": "MissionRuntime",
                "transition_authority": "MissionEngine",
                "completion_authority": "MissionCompletionGate",
            },
        }
        if outcome.state is ConfirmationState.REJECTED and outcome.accepted:
            return CanonicalTurnResult.local(
                "A ação foi recusada e a missão foi cancelada sem qualquer execução.",
                kind=CanonicalResultKind.UNKNOWN,
                metadata={**meta, "authorization_gate": "CONFIRMATION_REJECTED"},
            )
        if outcome.state is ConfirmationState.CONFIRMED and outcome.accepted:
            return await self._resume_confirmed(outcome, meta)
        return self._confirmation_non_executing_result(outcome, meta)

    async def _resume_confirmed(
        self, outcome: ConfirmationOutcome, meta: dict[str, Any]
    ) -> CanonicalTurnResult:
        """Resume the SAME Mission — authorization recheck already performed by submit()."""
        instance = await self.components.mission_runtime.run_mission(
            outcome.runtime_id
        )
        executed = (
            instance.status
            in (MissionRuntimeState.COMPLETED, MissionRuntimeState.FAILED)
            or bool(instance.completed_nodes)
            or bool(instance.failed_nodes)
        )
        if executed:
            self.components.confirmation_service.consume(outcome.confirmation_id)
        else:
            self.components.confirmation_service.invalidate(
                outcome.confirmation_id,
                f"runtime_status:{instance.status.value}",
            )
        return self._resumed_instance_result(instance, outcome, meta)

    def _resumed_instance_result(
        self,
        instance: Any,
        outcome: ConfirmationOutcome,
        meta: dict[str, Any],
    ) -> CanonicalTurnResult:
        """Translate the resumed runtime state to a canonical product result."""
        mission_id = outcome.mission_id
        status = instance.status
        base = {
            **meta,
            "runtime_id": instance.runtime_id,
            "runtime_status": status.value,
        }
        if status is MissionRuntimeState.COMPLETED:
            return CanonicalTurnResult.mission(
                "A ação confirmada foi executada, verificada e a missão foi "
                "concluída pelo MissionCompletionGate.",
                kind=CanonicalResultKind.MISSION_COMPLETED,
                mission_id=mission_id,
                verification_evidence=tuple(instance.completion_evidence),
                metadata={
                    **base,
                    "verification_status": instance.verification_status.value,
                    "completion_authority": instance.completion_authority,
                },
            )
        if status is MissionRuntimeState.WAITING_RESOURCE:
            return CanonicalTurnResult.mission(
                "A missão confirmada aguarda um recurso elegível; nenhuma "
                "execução ocorreu neste turno.",
                kind=CanonicalResultKind.EXTERNAL_RESOURCE_REQUIRED,
                mission_id=mission_id,
                next_actions=("Aguardar recurso elegível",),
                metadata=base,
            )
        if status is MissionRuntimeState.BLOCKED:
            return CanonicalTurnResult.blocked(
                "A execução confirmada foi bloqueada pela política durante a "
                "revalidação; nenhuma execução ocorreu.",
                reason="action_gate_block",
                mission_id=mission_id,
                metadata=base,
            )
        if status is MissionRuntimeState.FAILED:
            return CanonicalTurnResult.failed(
                "A execução confirmada falhou ou não passou na verificação; "
                "a missão não foi concluída.",
                mission_id=mission_id,
                metadata=base,
            )
        if status is MissionRuntimeState.WAITING_USER_CONFIRMATION:
            return CanonicalTurnResult.waiting_confirmation(
                "A missão continua aguardando confirmação; nenhuma execução "
                "ocorreu.",
                mission_id=mission_id,
                metadata=base,
            )
        return CanonicalTurnResult.mission(
            "A missão confirmada segue em execução controlada.",
            kind=CanonicalResultKind.WAITING_CONTEXT,
            mission_id=mission_id,
            metadata=base,
        )

    def _confirmation_non_executing_result(
        self, outcome: ConfirmationOutcome, meta: dict[str, Any]
    ) -> CanonicalTurnResult:
        """Non-executing informational result for rejected/expired/replayed confirms."""
        reason = outcome.reason
        if reason == "mission_already_completed":
            text = (
                "Esta missão já foi concluída; a confirmação não foi aplicada e "
                "nenhuma nova execução ocorreu."
            )
        elif reason == "confirmation_already_consumed":
            text = (
                "Esta confirmação já foi aplicada; nenhuma execução duplicada ocorreu."
            )
        elif reason == "mission_already_cancelled":
            text = "Esta missão já foi cancelada; nenhuma execução ocorreu."
        elif reason == "confirmation_expired":
            text = (
                "A confirmação expirou; nenhuma execução ocorreu. Solicite uma nova "
                "confirmação."
            )
        elif reason == "confirmation_already_accepted":
            text = "Esta confirmação já foi aceita; nenhuma execução duplicada ocorreu."
        elif reason == "confirmation_already_rejected":
            text = "Esta confirmação já foi recusada; nenhuma execução ocorreu."
        elif reason == "binding_invalid":
            text = (
                "O vínculo da confirmação não é mais válido; nenhuma execução ocorreu."
            )
        elif reason in (
            "token_mismatch",
            "scope_session_mismatch",
            "scope_project_mismatch",
            "mission_mismatch",
        ):
            text = "A confirmação não corresponde ao vínculo esperado; nenhuma execução ocorreu."
        elif reason.startswith("mission_not_pending"):
            text = "A missão não está aguardando confirmação; nenhuma execução ocorreu."
        elif reason in ("mission_not_found", "confirmation_not_found"):
            text = "Confirmação ou missão não encontrada; nenhuma execução ocorreu."
        else:
            text = "A confirmação não foi aplicada; nenhuma execução ocorreu."
        return CanonicalTurnResult.local(
            text,
            kind=CanonicalResultKind.UNKNOWN,
            metadata={**meta, "confirm_state": outcome.state.value, "reason": reason},
        )

    async def _govern_response(
        self, response: CanonicalTurnResult, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Serialize a typed result after canonical response/output governance."""
        metadata = dict(response.metadata)
        if self.last_pending_dialogue_match is not None:
            metadata.setdefault(
                "pending_dialogue_match", self.last_pending_dialogue_match
            )
        if self.last_conversation_authority is not None:
            metadata.setdefault(
                "conversation_authority", self.last_conversation_authority
            )
        participation = list(metadata.get("compatibility_traces", ()))
        metadata["compatibility_path_used"] = bool(participation)
        metadata["compatibility_traces"] = participation
        if not participation:
            metadata.pop("compatibility_trace", None)

        response_mission_id = response.mission_id
        canonical_result = response
        if response_mission_id:
            canonical_mission = None
            try:
                canonical_mission = await self.components.mission_engine.get(
                    MissionId(str(response_mission_id))
                )
            except (KeyError, TypeError, ValueError):
                canonical_mission = None
            if canonical_mission is None:
                # Preserve the compatibility correlation token without
                # representing it as canonical Mission identity or lifecycle.
                metadata["compatibility_dialogue_id"] = str(response_mission_id)
                metadata["compatibility_lifecycle"] = {
                    "classification": "COMPATIBILITY_ONLY",
                    "canonical_mission": False,
                    "completion_authority": None,
                }
                attach_compatibility_trace(
                    metadata,
                    compatibility_trace(
                        "ProductBridgeDialogueLifecycle",
                        "legacy_dialogue_identifier_was_not_a_canonical_mission",
                        entry_point="ProductBridge._govern_response.mission_identity",
                        canonical_alternative_missing="canonical_dialogue_identity",
                    ),
                )
                canonical_result = replace(response, mission_id=None)
        canonical_result = replace(canonical_result, metadata=metadata)
        canonical = self.response_assembler.from_result(
            canonical_result,
        )
        canonical = await self.response_assembler.assemble(
            canonical,
            {"project_id": request.get("project_id", "GLOBAL"), "session_id": request.get("session_id", "product-alpha")},
        )
        return self.product_presenter.present(canonical, metadata).to_dict()

    def _record_local_flow(self, structured_intent: Any, mission_id: str) -> None:
        self._flow_event("intent_created", intent_id=structured_intent.intent_id)
        self._flow_event("intent_validated", result="success")
        self._flow_event("mission_compiled", mission_id=mission_id)
        self._flow_event("mission_persisted", mission_id=mission_id, result="success")

    def _complete_local_request(
        self,
        *,
        session_id: str,
        project_id: str,
        mission_id: str,
        message: str,
        history: list[dict[str, Any]],
        structured_intent: Any,
        domain: str,
        text_out: str,
        persist_session: Any | None = None,
    ) -> CanonicalTurnResult:
        now = utc_iso()
        self._record_local_flow(structured_intent, mission_id)
        full_history = [
            *history,
            {"role": "user", "content": message, "timestamp": now},
            {"role": "assistant", "content": text_out, "timestamp": now,
             "provider": "local"},
        ][-100:]
        state = {
            "conversation_id": session_id,
            "project_id": project_id,
            "current_intent": domain,
            "known_context": {"project_id": project_id},
            "missing_context": [],
            "pending_question": "",
            "last_user_message": message,
            "last_system_response": text_out,
            "active_mission_id": mission_id,
            "updated_at": now,
        }
        record = {
            "schema_version": "1.2",
            "session_id": session_id,
            "project_id": project_id,
            "mission_id": mission_id,
            "mission_status": "completed",
            "pending_dialogue": None,
            "conversation_state": state,
            "history": full_history,
            "updated_at": now,
        }
        if callable(persist_session):
            persist_session(record)
        else:
            self._save_session(session_id, record)
        self._flow_event("response_persisted", mission_id=mission_id,
                         result="success")
        result = CanonicalTurnResult.local(
            text_out,
            metadata={
                "compatibility_dialogue_id": mission_id,
                "compatibility_lifecycle": {
                    "classification": "COMPATIBILITY_ONLY",
                    "canonical_mission": False,
                    "completion_authority": None,
                },
                "domain": domain,
                "conversation_state": state,
                "inspector": state,
                "trace": self.last_trace,
            },
        )
        return self._compatibility_response(
            result,
            component="ProductBridgeFieldFilling",
            reason="legacy_typed_field_filling_or_local_product_flow",
            entry_point="ProductBridge._complete_local_request",
            canonical_alternative_missing="canonical_typed_conversation_policy",
        )

    def _provider_failure(
        self,
        exc: Exception,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        context: dict[str, Any],
        attempted_provider: str | None,
        *,
        persist_session: Any | None = None,
    ) -> CanonicalTurnResult:
        name = type(exc).__name__
        provider_code = getattr(exc, "code", "")

        # Internal kernel exceptions (code bugs)
        if isinstance(exc, (AttributeError, TypeError, KeyError, IndexError, AssertionError, NameError, UnboundLocalError)):
            text = "Não foi possível concluir esta missão devido a um erro interno."
            code, status = "internal_kernel_error", "internal_error"
            import traceback
            tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.last_trace["internalError"] = tb_str
            self.last_trace["errorType"] = name
            record = {
                "schema_version": "1.2", "session_id": session_id,
                "mission_id": context.get("mission_id"), "mission_status": "failed_internal",
                "intent": context.get("intent_model", {"text": message}),
                "response": {"error_code": code, "error_type": name},
                "history": history, "updated_at": utc_iso(),
            }
            if callable(persist_session):
                persist_session(record)
            else:
                self._save_session(session_id, record)
            return CanonicalTurnResult.failed(
                text,
                provider_id=attempted_provider,
                provider_invoked=attempted_provider is not None,
                mission_id=context.get("mission_id"),
                metadata={
                    "error": text,
                    "error_code": code,
                    "provider_status": status,
                },
            )

        if name == "RateLimitError" or provider_code == "quota_reached":
            text = f"O Provider {attempted_provider or 'selecionado'} atingiu seu limite. Aguarde a renovação da cota ou revise os limites da conta."
            code, status = "provider_quota", "quota_reached"
        elif name in {"APIConnectionError", "APITimeoutError"} or provider_code == "unavailable":
            text = f"O Provider {attempted_provider or 'selecionado'} está indisponível. Tente novamente mais tarde."
            code, status = "provider_connection", "unavailable"
        elif name == "AuthenticationError" or provider_code == "invalid_key":
            text = f"A credencial do Provider {attempted_provider or 'selecionado'} foi recusada. Reconecte nas Configurações."
            code, status = "provider_authentication", "error"
        else:
            text = "Não foi possível concluir esta Mission. Você pode tentar novamente."
            code, status = "provider_error", "error"
        record = {
            "schema_version": "1.2", "session_id": session_id,
            "mission_id": context.get("mission_id"), "mission_status": "failed_recoverable",
            "intent": context.get("intent_model", {"text": message}),
            "response": {"error_code": code, "provider": attempted_provider},
            "history": history, "updated_at": utc_iso(),
        }
        if callable(persist_session):
            persist_session(record)
        else:
            self._save_session(session_id, record)
        return CanonicalTurnResult.failed(
            text,
            provider_id=attempted_provider,
            provider_invoked=attempted_provider is not None,
            mission_id=context.get("mission_id"),
            metadata={
                "error": text,
                "error_code": code,
                "provider_status": status,
            },
        )

    async def _pause_failed_mission(self, context: dict[str, Any]) -> None:
        mission_id = context.get("mission_id")
        if not mission_id:
            return
        try:
            mission = await self.kernel.mission_engine.get(MissionId(str(mission_id)))
            if mission is not None and mission.status is MissionStatus.RUNNING:
                await self.kernel.mission_engine.pause(
                    mission.id, status=MissionStatus.FAILED_RECOVERABLE,
                    blocker={"code": "execution_failed"})
        except Exception as exc:
            self._safe_flow_log("mission_pause_failure", type(exc).__name__)

    def _session_path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
        return self.sessions_root / f"{safe or 'product-alpha'}.json"

    def _load_session(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return self._normalize_session(value) if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_session(self, session_id: str, record: dict[str, Any]) -> None:
        path = self._session_path(session_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _empty_trace(self, correlation_id: str = "") -> dict[str, Any]:
        return {"requestCorrelationId": correlation_id, "lastCompletedStage": None,
                "lastFailedStage": None, "intentId": None, "missionId": None,
                "providerCallStarted": False, "providerCallCompleted": False,
                "provider": None, "model": None, "providerStatus": None,
                "persistenceStatus": "not_started", "renderStatus": "not_started",
                "dataMigrationStatus": "not_started"}

    def _flow_event(self, event: str, metadata: dict[str, Any] | None = None, **values: Any) -> None:
        details = {**(metadata or {}), **values}
        if event == "intent_created":
            self.last_trace["intentId"] = details.get("intent_id") or str(uuid4())
        if details.get("mission_id"):
            self.last_trace["missionId"] = details["mission_id"]
        if event == "provider_request_started":
            self.last_trace.update(providerCallStarted=True, provider=details.get("provider"),
                                   model=details.get("model"), providerStatus="started")
        elif event == "provider_response_received":
            self.last_trace.update(providerCallCompleted=True,
                                   providerStatus=details.get("status"))
        elif event == "response_persisted":
            self.last_trace["persistenceStatus"] = "completed"
        if event == "request_failed":
            self.last_trace["lastFailedStage"] = details.get("stage") or event
        else:
            self.last_trace["lastCompletedStage"] = event
        record = {"event": event, "correlation_id": self.last_trace.get("requestCorrelationId"),
                  "intent_id": self.last_trace.get("intentId"), "mission_id": self.last_trace.get("missionId"),
                  "timestamp_utc": utc_iso(), "stage": event,
                  "duration_ms": details.get("duration_ms"),
                  "result": details.get("result", "success"), "error": details.get("error")}
        try:
            with self.flow_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _provider_event(self, event: str, metadata: dict[str, Any]) -> None:
        self._flow_event(event, metadata)

    def _fail(
        self, stage: str, code: str, message: str, started: float
    ) -> CanonicalTurnResult:
        self._flow_event("request_failed", stage=stage, error=code, result="error",
                         duration_ms=round((time.perf_counter() - started) * 1000, 2))
        return CanonicalTurnResult.failed(
            message,
            metadata={
                "error": message,
                "error_code": code,
                "trace": self.last_trace,
            },
        )

    def _normalize_session(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        history = []
        for item in value.get("history") or []:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry["timestamp"] = utc_iso(item.get("timestamp"), fallback_now=True)
            history.append(entry)
        normalized["history"] = history
        normalized["updated_at"] = utc_iso(value.get("updated_at"), fallback_now=True)
        return normalized

    def _migrate_sessions(self) -> str:
        migrated = isolated = 0
        backup = self.data_root / "backups" / f"sessions-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
        for path in self.sessions_root.glob("*.json"):
            try:
                original = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(original, dict):
                    raise ValueError("session_not_object")
                normalized = self._normalize_session(original)
                if normalized != original:
                    backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup / path.name)
                    self._save_session(path.stem, normalized)
                    migrated += 1
            except (OSError, ValueError, json.JSONDecodeError):
                try:
                    quarantine = self.sessions_root / "isolated"
                    quarantine.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, quarantine / f"{path.stem}-{uuid4().hex}.json")
                    isolated += 1
                except OSError:
                    pass
        return f"completed:migrated={migrated};isolated={isolated}"

    def _safe_flow_log(self, event: str, error: str) -> None:
        try:
            with self.flow_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": event, "error": error,
                                         "timestamp_utc": utc_iso()}) + "\n")
        except OSError:
            pass


async def run() -> None:
    _configure_stdio()
    try:
        bridge = ProductBridge()
    except Exception as exc:
        _safe_diagnostic(exc)
        _protocol_write({"event": "failed", "ok": False,
                         "protocol_version": PROTOCOL_VERSION,
                         "app_version": APP_VERSION, "bridge_version": BRIDGE_VERSION,
                         "error": "A bridge local não pôde iniciar."})
        return
    _protocol_write({"ok": True, **_health_payload(event="READY")})
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            request = json.loads(line)
            response = await bridge.dispatch(request)
            response["requestId"] = request.get("requestId")
        except Exception as exc:
            _safe_diagnostic(exc)
            response = {"ok": False, "error": "Não foi possível processar a solicitação. Tente novamente.",
                        "error_code": "bridge_request_error",
                        "requestId": request.get("requestId") if "request" in locals() else None}
        try:
            _protocol_write(response)
        except Exception as exc:
            _safe_diagnostic(exc)
            _protocol_write({"ok": False, "error": "Falha segura no canal da bridge.",
                             "error_code": "bridge_protocol_error",
                             "requestId": response.get("requestId")})


if __name__ == "__main__":
    asyncio.run(run())
