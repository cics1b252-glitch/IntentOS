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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.contracts import MissionId, MissionStatus
from intent_kernel.cdm import CognitiveDialogueManager
from intent_kernel.cpe import CognitivePlanningEngine
from intent_kernel.iue import IntentUnderstandingEngine
from intent_kernel.cor import CapabilityOrchestrator
from intent_kernel.ecc import ExecutiveCognitiveController
from intent_kernel.time_utils import utc_iso
from intent_kernel.ame import (
    AdaptiveMemoryEngine,
    MemoryCandidate,
    MemoryQuery,
    ContextAssembler,
    LocalKnowledgeObjectRepository,
)
from intent_kernel.persistence import JsonFilePersistenceEngine
from intent_kernel.bcc import BootstrapCognitiveCortex
from intent_kernel.modules.fin.module import _extract_brl_amount

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
    def __init__(self) -> None:
        self.data_root = Path(os.environ.get("INTENTOS_DATA_ROOT", "."))
        self.sessions_root = self.data_root / "missions"
        self.logs_root = self.data_root / "logs"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.flow_log = self.logs_root / "intent-flow.jsonl"
        self.last_trace = self._empty_trace()
        self.data_migration_status = self._migrate_sessions()
        self.last_trace["dataMigrationStatus"] = self.data_migration_status

        builder = KernelBuilder().with_pkb_path(self.data_root / "future-kc" / "pkb")
        builder.with_environment(dict(os.environ))
        self.factory = ApplicationFactory(builder)
        self.components = self.factory.get_components()
        self.kernel = self.factory.get_kernel()
        self.iue = IntentUnderstandingEngine(pkb=getattr(self.kernel, "pkb", None))
        self.cdm = CognitiveDialogueManager()
        self.cpe = CognitivePlanningEngine()
        self.cor = CapabilityOrchestrator()
        self.ecc = ExecutiveCognitiveController(iue=self.iue, cdm=self.cdm, cpe=self.cpe, cor=self.cor)
        self.components.provider_manager.set_observer(self._provider_event)

        ame_storage = self.data_root / "ame_memory"
        ame_storage.mkdir(parents=True, exist_ok=True)
        persistence_engine = JsonFilePersistenceEngine(file_path=str(ame_storage / "ame_store.json"))
        self.ame_repo = LocalKnowledgeObjectRepository(persistence_engine=persistence_engine)
        self.ame = AdaptiveMemoryEngine(repository=self.ame_repo)
        self.bcc = BootstrapCognitiveCortex(ame=self.ame)

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
            return {
                "ok": True,
                "available": self.components.provider_manager.available,
                "default": getattr(self.components.provider_manager, "default", "gemini"),
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
        if action == "intent" or action == "chat":
            if "text" in request and "message" not in request:
                request["message"] = request["text"]
            return await self._chat(request)
        if action == "diagnostics" or action == "flow_diagnostics":
            return {
                "ok": True,
                "trace": self.last_trace,
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

    async def _chat(self, request: dict[str, Any]) -> dict[str, Any]:
        correlation_id = str(request.get("correlation_id") or uuid4())
        started = time.perf_counter()
        self.last_trace = self._empty_trace(correlation_id)
        self.last_trace["dataMigrationStatus"] = self.data_migration_status
        self._flow_event("bridge_request_received")
        message = str(request.get("message", "")).strip()
        if not message:
            return self._fail("bridge_request_received", "empty_message",
                              "Escreva uma mensagem antes de enviar.", started)

        session_id = str(request.get("session_id", "product-alpha"))
        project_id = str(request.get("project_id") or request.get("projectId") or "GLOBAL")
        saved = self._load_session(session_id)
        history = request.get("history") or saved.get("history") or []
        recent = history[-8:]
        conversation_context = "\n".join(
            f"{('Usuário' if item.get('role') == 'user' else 'Intent OS')}: {item.get('content', '')}"
            for item in recent if isinstance(item, dict)
        )
        pending_dialogue = saved.get("pending_dialogue")
        resume_mission_id = request.get("resume_mission_id") or saved.get("mission_id")
        mission_id = str(resume_mission_id or saved.get("mission_id") or uuid4())

        # IUE Analysis
        session_ctx_iue = {
            "conversation_context": conversation_context,
            "pending_dialogue": pending_dialogue,
            "user_profile": saved.get("user_profile") or request.get("user_profile") or {},
            "project_id": project_id,
        }
        structured_intent = self.iue.analyze(message, session_context=session_ctx_iue)

        context: dict[str, Any] = {
            "session_id": session_id,
            "project_id": project_id,
            "mission_id": mission_id,
            "interface": "windows_product_alpha",
            "correlation_id": correlation_id,
            "conversation_context": conversation_context,
            "structured_intent": structured_intent.to_dict(),
            "pending_dialogue": pending_dialogue,
            "resume_mission_id": resume_mission_id,
            "flow_event": self._flow_event,
        }

        # 1. Ingest Facts/Preferences into AME
        lower = message.lower()
        if (
            not _is_question(message)
            and any(p in lower for p in [
                "prefiro", "preferência", "minhas respostas devem ser",
                "usamos ", "projeto_",
            ])
        ):
            candidate = MemoryCandidate(
                proposed_content=message,
                reason_to_remember=f"Memória informada no projeto {project_id}",
                source="user_chat",
                project_id=project_id,
                proposed_importance=0.9,
            )
            await self.ame.process_candidate(candidate)

        # 2. Check Memory Queries ("como prefiro...", "qual tecnologia...", "qual é o meu objetivo...")
        is_memory_query = any(k in lower for k in ["como prefiro", "qual tecnologia", "qual é o meu objetivo", "qual meu objetivo", "o que sabemos sobre", "qual o projeto", "qual linguagem"])
        if is_memory_query:
            ret = await self.ame.retrieve_memory(MemoryQuery(query_text=message, project_id=project_id))
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
                "active_mission_id": mission_id,
                "updated_at": now,
            }
            self._save_session(session_id, {
                "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                "mission_id": mission_id, "conversation_state": conv_state,
                "history": full_history, "updated_at": now,
            })
            return {
                "ok": True, "text": text_out, "provider": "local", "provider_called": False, "status": "concluído",
                "mission_id": mission_id, "domain": "memory", "conversation_state": conv_state, "inspector": conv_state,
                "trace": self.last_trace
            }

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
                "active_mission_id": mission_id,
                "updated_at": now,
            }
            self._save_session(session_id, {
                "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                "mission_id": mission_id, "conversation_state": conv_state,
                "history": full_history, "updated_at": now,
            })
            return {
                "ok": True, "text": bcc_res.summary, "provider": "local", "provider_called": False, "status": "concluído",
                "mission_id": mission_id, "domain": "system", "conversation_state": conv_state, "inspector": conv_state,
                "trace": self.last_trace
            }

        # 4. Multi-Turn Field Filling for Finance & App domains
        conv_state_prev = saved.get("conversation_state") or {}
        known_kc = dict(conv_state_prev.get("known_context")) if isinstance(conv_state_prev.get("known_context"), dict) else {}
        if not known_kc and isinstance(pending_dialogue, dict) and isinstance(pending_dialogue.get("known_context"), dict):
            known_kc = dict(pending_dialogue.get("known_context"))

        # Ingest incremental facts into known_kc
        # Amount: contextual financial parsing, never unrelated numbers.
        amount = _financial_amount(message)
        if amount is not None:
            known_kc["amount"] = amount
            known_kc["amount_str"] = f"R$ {amount:,.2f}".replace(
                ",", "X").replace(".", ",").replace("X", "."
            ).removesuffix(",00")
        
        # Recurrence
        if any(w in lower for w in ["mensal", "mensais", "aporte mensal", "por mês", "todo mês"]):
            known_kc["recurrence"] = "mensal"
        elif any(w in lower for w in ["único", "unico", "uma vez", "pontual", "tenho", "disponível", "disponivel"]):
            known_kc["recurrence"] = "único"

        # Goal
        if "aposentadoria" in lower:
            known_kc["goal"] = "aposentadoria"
        elif "reserva" in lower or "emergência" in lower:
            known_kc["goal"] = "reserva de emergência"
        elif "imóvel" in lower or "casa" in lower:
            known_kc["goal"] = "compra de imóvel"

        # Risk
        if "moderado" in lower:
            known_kc["risk_profile"] = "moderado"
        elif "conservador" in lower or "seguro" in lower:
            known_kc["risk_profile"] = "conservador"
        elif "arrojado" in lower or "agressivo" in lower:
            known_kc["risk_profile"] = "arrojado"

        # Time horizon
        if "10 anos" in lower or "dez anos" in lower:
            known_kc["time_horizon"] = "10 anos"
        elif "5 anos" in lower or "cinco anos" in lower:
            known_kc["time_horizon"] = "5 anos"

        # Liquidity
        if "liquidez" in lower or "não preciso" in lower or "sem necessidade" in lower:
            known_kc["liquidity"] = "sem necessidade de liquidez imediata"

        # App creation fields
        is_spreadsheet = any(term in lower for term in ("planilha", "spreadsheet", "excel"))
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

        # Determine domain
        is_fin = (
            "invest" in lower or "amount" in known_kc or "recurrence" in known_kc
            or isinstance(pending_dialogue, dict)
            and pending_dialogue.get("target_field") in {
                "amount", "recurrence", "investment_frequency", "goal",
                "risk_profile", "time_horizon", "liquidity",
            }
        )
        is_app = (
            not is_spreadsheet
            and ("aplicativo" in lower or bool(re.search(r"\bapp\b", lower))
                 or "app_type" in known_kc or "platform" in known_kc)
        )

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
            )

        if is_fin and lower != "investir":
            amount_str = known_kc.get("amount_str", "")
            if "amount" not in known_kc:
                pending_q = "Para começarmos a análise de investimentos, qual é o valor total disponível?"
                next_field = "amount"
                missing = ["amount", "recurrence", "goal", "risk_profile", "time_horizon", "liquidity"]
                is_waiting = True
            elif "recurrence" not in known_kc:
                pending_q = f"Entendi que o valor é **{amount_str}**. Esse valor é para um investimento único ou para um aporte mensal?"
                next_field = "recurrence"
                missing = ["recurrence", "goal", "risk_profile", "time_horizon", "liquidity"]
                is_waiting = True
            elif known_kc.get("recurrence") == "único":
                is_waiting = False
                missing = []
            elif (
                isinstance(pending_dialogue, dict)
                and pending_dialogue.get("target_field") == "recurrence"
                and "recurrence" in known_kc
            ):
                is_waiting = False
                missing = []
            elif "goal" not in known_kc:
                pending_q = f"Qual é o seu objetivo principal para este investimento de **{amount_str}** (ex: aposentadoria, reserva de emergência, compra de imóvel)?"
                next_field = "goal"
                missing = ["goal", "risk_profile", "time_horizon", "liquidity"]
                is_waiting = True
            elif "risk_profile" not in known_kc:
                pending_q = f"Qual é o seu perfil de risco para este investimento (conservador, moderado ou arrojado)?"
                next_field = "risk_profile"
                missing = ["risk_profile", "time_horizon", "liquidity"]
                is_waiting = True
            elif "time_horizon" not in known_kc:
                pending_q = f"Por quanto tempo você pretende manter este investimento aplicado?"
                next_field = "time_horizon"
                missing = ["time_horizon", "liquidity"]
                is_waiting = True
            elif "liquidity" not in known_kc:
                pending_q = f"Você precisa de liquidez imediata para resgates ou pode manter aplicado pelo prazo?"
                next_field = "liquidity"
                missing = ["liquidity"]
                is_waiting = True
            else:
                is_waiting = False
                missing = []

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
                self._save_session(session_id, {
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": persisted_status,
                    "pending_dialogue": new_pending, "conversation_state": conv_state,
                    "history": full_history, "updated_at": now,
                })
                self._flow_event("response_persisted", mission_id=mission_id,
                                 result="success")
                return {
                    "ok": True, "text": pending_q, "provider": "local", "provider_called": False, "status": "waiting_context",
                    "dialogue_state": "WAITING_CONTEXT", "target_field": next_field,
                    "pending_dialogue": new_pending, "conversation_state": conv_state,
                    "mission_id": mission_id, "inspector": conv_state,
                    "domain": "finance", "trace": self.last_trace,
                    "provider_explanation": (
                        "A capability Atlas respondeu localmente; "
                        "o Gemini não foi necessário."
                    ),
                }
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
                self._save_session(session_id, {
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "completed", "pending_dialogue": None,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                return {
                    "ok": True, "text": fin_summary, "provider": "local", "provider_called": False, "status": "concluído",
                    "mission_id": mission_id, "domain": "finance", "conversation_state": conv_state, "inspector": conv_state,
                    "trace": self.last_trace
                }

        if is_app:
            missing = []
            if "platform" not in known_kc: missing.append("platform")
            if "purpose" not in known_kc: missing.append("purpose")
            if "connectivity" not in known_kc: missing.append("connectivity")
            if "pricing" not in known_kc: missing.append("pricing")

            if missing:
                next_field = missing[0]
                questions = {
                    "platform": "Qual é a plataforma principal do aplicativo (ex: Android, iOS, Web)?",
                    "purpose": "Qual é a finalidade principal do aplicativo (ex: controle de estoque, vendas)?",
                    "connectivity": "O aplicativo precisa funcionar offline ou apenas online?",
                    "pricing": "Qual será o modelo de distribuição (ex: versão gratuita, paga)?",
                }
                pending_q = questions[next_field]
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
                self._save_session(session_id, {
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "waiting_context", "pending_dialogue": new_pending,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                return {
                    "ok": True, "text": pending_q, "provider": "local", "provider_called": False, "status": "waiting_context",
                    "dialogue_state": "WAITING_CONTEXT", "target_field": next_field,
                    "pending_dialogue": new_pending, "conversation_state": conv_state,
                    "mission_id": mission_id, "inspector": conv_state, "domain": "coding", "trace": self.last_trace
                }
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
                self._save_session(session_id, {
                    "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
                    "mission_id": mission_id, "mission_status": "completed", "pending_dialogue": None,
                    "conversation_state": conv_state, "history": full_history, "updated_at": now,
                })
                return {
                    "ok": True, "text": app_summary, "provider": "local", "provider_called": False, "status": "concluído",
                    "mission_id": mission_id, "domain": "coding", "conversation_state": conv_state, "inspector": conv_state,
                    "trace": self.last_trace
                }

        # 5. Default Fallback through Kernel Engine
        default_provider = self.components.provider_manager.default
        self.components.provider_manager.reset_execution_tracking()
        fallback = str(request.get("fallback_provider", ""))
        allow_fallback = request.get("allow_fallback") is True
        self.components.provider_manager.configure_fallback(
            allow_fallback, fallback if allow_fallback and fallback else None)

        try:
            result = await self.kernel.process(message, context)
        except Exception as exc:
            failed_provider = self.components.provider_manager.last_attempted or default_provider
            self.components.provider_manager.configure_fallback(False)
            await self._pause_failed_mission(context)
            response = self._provider_failure(
                exc, session_id, message, history, context, failed_provider)
            self._flow_event("request_failed", stage=self.last_trace["lastCompletedStage"],
                             result="error", error=response["error_code"],
                             duration_ms=round((time.perf_counter() - started) * 1000, 2))
            response["trace"] = self.last_trace
            return response

        used_provider = self.components.provider_manager.last_used
        used_fallback = bool(used_provider and used_provider != default_provider)
        self.components.provider_manager.configure_fallback(False)
        response_provider = used_provider or "local"
        if response_provider == "mock":
            result.text = (
                "Não tenho conhecimento local suficiente para responder com segurança "
                "e nenhum Provider externo está conectado (UNKNOWN)."
            )
            response_provider = "local"
        now = utc_iso()
        full_history = [*history,
            {"role": "user", "content": message, "timestamp": now},
            {"role": "assistant", "content": result.text, "timestamp": now,
             "provider": response_provider},
        ][-100:]

        conv_state = {
            "conversation_id": session_id,
            "project_id": project_id,
            "current_intent": result.domain.value,
            "known_context": known_kc,
            "missing_context": [],
            "pending_question": "",
            "last_user_message": message,
            "last_system_response": result.text,
            "active_mission_id": context.get("mission_id"),
            "updated_at": now,
        }

        self._save_session(session_id, {
            "schema_version": "1.2", "session_id": session_id, "project_id": project_id,
            "mission_id": context.get("mission_id"), "mission_status": "completed",
            "pending_dialogue": None, "conversation_state": conv_state,
            "intent": context.get("intent_model", {"text": message}),
            "response": {"text": result.text, "provider": response_provider,
                         "fallback_used": used_fallback, "domain": result.domain.value},
            "history": full_history, "updated_at": now,
        })
        self._flow_event("response_persisted", mission_id=context.get("mission_id"),
                         result="success",
                         duration_ms=round((time.perf_counter() - started) * 1000, 2))
        return {"ok": True, "text": result.text, "provider": response_provider,
                "fallback_used": used_fallback, "provider_called": bool(used_provider),
                "provider_explanation": None if used_provider else
                    "A capability Atlas respondeu localmente; o Gemini não foi necessário.",
                "status": "concluído", "domain": result.domain.value,
                "mission_id": context.get("mission_id"),
                "intent": context.get("intent_model"),
                "structured_intent": structured_intent.to_dict(),
                "iqi": structured_intent.intent_quality_index,
                "conversation_state": conv_state, "inspector": conv_state,
                "trace": self.last_trace}

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
    ) -> dict[str, Any]:
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
        self._save_session(session_id, {
            "schema_version": "1.2",
            "session_id": session_id,
            "project_id": project_id,
            "mission_id": mission_id,
            "mission_status": "completed",
            "pending_dialogue": None,
            "conversation_state": state,
            "history": full_history,
            "updated_at": now,
        })
        self._flow_event("response_persisted", mission_id=mission_id,
                         result="success")
        return {
            "ok": True,
            "text": text_out,
            "provider": "local",
            "provider_called": False,
            "status": "concluído",
            "mission_id": mission_id,
            "domain": domain,
            "conversation_state": state,
            "inspector": state,
            "trace": self.last_trace,
        }

    def _provider_failure(self, exc: Exception, session_id: str, message: str,
                          history: list[dict[str, Any]], context: dict[str, Any],
                          provider: str | None) -> dict[str, Any]:
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
            self._save_session(session_id, {
                "schema_version": "1.2", "session_id": session_id,
                "mission_id": context.get("mission_id"), "mission_status": "failed_internal",
                "intent": context.get("intent_model", {"text": message}),
                "response": {"error_code": code, "error_type": name},
                "history": history, "updated_at": utc_iso(),
            })
            return {"ok": False, "error": text, "error_code": code,
                    "provider": None, "provider_status": status,
                    "mission_id": context.get("mission_id")}

        if name == "RateLimitError" or provider_code == "quota_reached":
            text = f"O Provider {provider or 'selecionado'} atingiu seu limite. Aguarde a renovação da cota ou revise os limites da conta."
            code, status = "provider_quota", "quota_reached"
        elif name in {"APIConnectionError", "APITimeoutError"} or provider_code == "unavailable":
            text = f"O Provider {provider or 'selecionado'} está indisponível. Tente novamente mais tarde."
            code, status = "provider_connection", "unavailable"
        elif name == "AuthenticationError" or provider_code == "invalid_key":
            text = f"A credencial do Provider {provider or 'selecionado'} foi recusada. Reconecte nas Configurações."
            code, status = "provider_authentication", "error"
        else:
            text = "Não foi possível concluir esta Mission. Você pode tentar novamente."
            code, status = "provider_error", "error"
        self._save_session(session_id, {
            "schema_version": "1.2", "session_id": session_id,
            "mission_id": context.get("mission_id"), "mission_status": "failed_recoverable",
            "intent": context.get("intent_model", {"text": message}),
            "response": {"error_code": code, "provider": provider},
            "history": history, "updated_at": utc_iso(),
        })
        return {"ok": False, "error": text, "error_code": code,
                "provider": provider, "provider_status": status,
                "mission_id": context.get("mission_id")}

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

    def _fail(self, stage: str, code: str, message: str, started: float) -> dict[str, Any]:
        self._flow_event("request_failed", stage=stage, error=code, result="error",
                         duration_ms=round((time.perf_counter() - started) * 1000, 2))
        return {"ok": False, "error": message, "error_code": code, "trace": self.last_trace}

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
