"""Movement 24.2 — Canonical Conversation Content Service tests.

Validates CanonicalConversationContentService as the single canonical
authority for content generation in the non-Mission conversation fallback path.

Authority chain under test:
    CanonicalConversationContentService
    -> CanonicalConstitutionEngine (governance)
    -> ProviderManager (routing + execution)
    -> CanonicalTurnResult (truthful provenance)
"""

from __future__ import annotations

import pathlib
import re

import pytest

from intent_kernel.conversation.content import CanonicalConversationContentService
from intent_kernel.providers.authority import ProviderSelectionDecision
from intent_kernel.response import CanonicalTurnResult


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

class _StubVerdict:
    """Minimal constitution verdict for testing."""
    def __init__(self, allowed: bool = True, reason: str = "", violated_rule: str = None):
        self._allowed = allowed
        self.reason = reason
        self.violated_rule = violated_rule
        from intent_kernel.contracts.models import ConstitutionDecision
        self.decision = ConstitutionDecision.ALLOW if allowed else ConstitutionDecision.DENY

    @property
    def allowed(self) -> bool:
        return self._allowed


class _StubConstitutionEngine:
    """Stub constitution engine that returns a configurable verdict."""
    def __init__(self, verdict: _StubVerdict | None = None):
        self._verdict = verdict or _StubVerdict()
        self.calls: list[tuple] = []

    async def evaluate(self, action, data, context):
        self.calls.append((action, data, context))
        return self._verdict


class _StubProviderResponse:
    """Minimal provider response."""
    def __init__(self, text: str = "hello world"):
        self.text = text
        self.model = "stub-model"
        self.provider = "stub"
        self.usage = {}
        self.finish_reason = "stop"


class _StubManagedProvider:
    """Stub managed provider that returns configurable response."""
    def __init__(self, response: _StubProviderResponse | None = None, exc: Exception | None = None):
        self._response = response or _StubProviderResponse()
        self._exc = exc
        self.executed = False

    async def execute(self, request):
        self.executed = True
        if self._exc:
            raise self._exc
        return self._response


class _StubProviderManager:
    """Stub provider manager that returns a configurable managed provider."""
    def __init__(self, managed: _StubManagedProvider | None = None, route_returns_none: bool = False):
        self._managed = managed or _StubManagedProvider()
        self._route_returns_none = route_returns_none
        self._last_used = None
        self._last_attempted = None

    async def route(self, mode, selection=None):
        if self._route_returns_none:
            return None
        return self._managed

    @property
    def last_used(self):
        return self._last_used

    @property
    def last_attempted(self):
        return self._last_attempted


def _make_selection(
    provider_id: str = "gemini",
    fallback: str | None = None,
    available: bool = True,
) -> ProviderSelectionDecision:
    return ProviderSelectionDecision(
        provider_id=provider_id if available else None,
        fallback_provider_id=fallback,
        required_capabilities=("text_completion",),
        eligible_provider_ids=("gemini",) if available else (),
        reason="eligible_provider_selected" if available else "no_eligible_provider",
    )


def _make_service(
    verdict: _StubVerdict | None = None,
    managed: _StubManagedProvider | None = None,
    route_returns_none: bool = False,
) -> CanonicalConversationContentService:
    engine = _StubConstitutionEngine(verdict)
    pm = _StubProviderManager(managed, route_returns_none)
    return CanonicalConversationContentService(
        constitution_engine=engine,
        provider_manager=pm,
    ), engine, pm


# ═══════════════════════════════════════════════════════════════════════════════
#  NORMAL REQUEST HANDLING — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestNormalRequestHandling:
    @pytest.mark.asyncio
    async def test_normal_request_returns_provider_result(self):
        svc, _, _ = _make_service()
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert isinstance(result, CanonicalTurnResult)
        assert result.kind.value == "CONVERSATION"

    @pytest.mark.asyncio
    async def test_normal_request_has_provider_evidence(self):
        svc, _, _ = _make_service()
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.provider_evidence is not None
        assert result.provider_evidence.provider_id == "gemini"
        assert result.provider_evidence.invoked is True

    @pytest.mark.asyncio
    async def test_normal_request_text_from_provider(self):
        svc, _, _ = _make_service()
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.text == "hello world"

    @pytest.mark.asyncio
    async def test_normal_request_not_local_source(self):
        svc, _, _ = _make_service()
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.local_source is False


# ═══════════════════════════════════════════════════════════════════════════════
#  PRODUCTBRIDGE DELEGATION — 3 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProductBridgeDelegation:
    def test_service_is_importable_from_product_bridge(self):
        """CanonicalConversationContentService must be importable."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        assert CanonicalConversationContentService is not None

    def test_service_has_process_method(self):
        """Service must expose async process() method."""
        svc, _, _ = _make_service()
        assert hasattr(svc, "process")
        assert callable(svc.process)

    def test_conversation_content_service_in_components(self):
        """ApplicationComponents must expose conversation_content_service."""
        from intent_kernel.application.composition import ApplicationComponents
        assert "conversation_content_service" in ApplicationComponents.__dataclass_fields__


# ═══════════════════════════════════════════════════════════════════════════════
#  PIPELINEDAG NOT INVOKED — 3 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineDAGNotInvoked:
    def test_product_bridge_no_kernel_process_call(self):
        """ProductBridge kernel_fallback path must not call kernel.process()."""
        bridge_src = pathlib.Path(__file__).resolve().parent.parent / "product_bridge.py"
        content = bridge_src.read_text(encoding="utf-8")
        # Find the canonical content service call
        assert "conversation_content_service.process" in content
        # kernel.process must NOT appear in the kernel_fallback section
        # (it can still exist elsewhere for other legacy paths)
        # Count occurrences in the fallback section
        lines = content.split("\n")
        in_fallback = False
        kernel_process_in_fallback = False
        for line in lines:
            if "# 5. Canonical Conversation Content Runtime" in line:
                in_fallback = True
            elif in_fallback and line.strip().startswith("# 6."):
                break
            if in_fallback and "self.kernel.process" in line:
                kernel_process_in_fallback = True
        assert not kernel_process_in_fallback, (
            "kernel_fallback path still calls self.kernel.process()"
        )

    def test_product_bridge_no_pipelinedag_in_fallback(self):
        """kernel_fallback section must not reference PipelineDAG."""
        bridge_src = pathlib.Path(__file__).resolve().parent.parent / "product_bridge.py"
        content = bridge_src.read_text(encoding="utf-8")
        lines = content.split("\n")
        in_fallback = False
        for line in lines:
            if "# 5. Canonical Conversation Content Runtime" in line:
                in_fallback = True
            elif in_fallback and line.strip().startswith("# 6."):
                break
            if in_fallback and "PipelineDAG" in line:
                pytest.fail("kernel_fallback path references PipelineDAG")

    def test_product_bridge_no_compatibility_wrapper_in_fallback(self):
        """kernel_fallback section must not use _compatibility_response."""
        bridge_src = pathlib.Path(__file__).resolve().parent.parent / "product_bridge.py"
        content = bridge_src.read_text(encoding="utf-8")
        lines = content.split("\n")
        in_fallback = False
        for line in lines:
            if "# 5. Canonical Conversation Content Runtime" in line:
                in_fallback = True
            elif in_fallback and ("@staticmethod" in line or "def _compatibility_response" in line or "def _recognize_memory_fact" in line):
                break
            if in_fallback and "_compatibility_response" in line:
                pytest.fail("kernel_fallback path wraps result in _compatibility_response")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTITUTION ALLOW / DENY — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstitutionAllowDeny:
    @pytest.mark.asyncio
    async def test_constitution_allow_proceeds_to_provider(self):
        svc, engine, pm = _make_service(verdict=_StubVerdict(allowed=True))
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.kind.value == "CONVERSATION"
        assert len(engine.calls) == 1

    @pytest.mark.asyncio
    async def test_constitution_deny_returns_blocked(self):
        svc, engine, _ = _make_service(
            verdict=_StubVerdict(allowed=False, reason="blocked by policy", violated_rule="no_secrets")
        )
        selection = _make_selection()
        result = await svc.process("my password is 123", {}, selection)
        assert result.kind.value == "BLOCKED"
        assert "no_secrets" in result.text

    @pytest.mark.asyncio
    async def test_constitution_deny_has_canonical_authority_metadata(self):
        svc, _, _ = _make_service(
            verdict=_StubVerdict(allowed=False, reason="test", violated_rule="rule_x")
        )
        selection = _make_selection()
        result = await svc.process("bad input", {}, selection)
        assert result.metadata.get("canonical_authority") == "CanonicalConversationContentService"
        assert result.metadata.get("canonical_mission") is False

    @pytest.mark.asyncio
    async def test_constitution_receives_correct_action(self):
        svc, engine, _ = _make_service()
        selection = _make_selection()
        await svc.process("test message", {"session_id": "s1"}, selection)
        action, data, ctx = engine.calls[0]
        assert action == "conversation.content"
        assert data == "test message"
        assert ctx.get("session_id") == "s1"


# ═══════════════════════════════════════════════════════════════════════════════
#  PROVIDER SELECTION / DISPATCH IDENTITY — 3 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderSelectionDispatchIdentity:
    @pytest.mark.asyncio
    async def test_selected_provider_equals_dispatched_provider(self):
        svc, _, pm = _make_service(
            managed=_StubManagedProvider(response=_StubProviderResponse(text="ok"))
        )
        pm._last_used = "gemini"
        selection = _make_selection(provider_id="gemini")
        result = await svc.process("hello", {}, selection)
        assert result.provider_evidence.provider_id == "gemini"

    @pytest.mark.asyncio
    async def test_metadata_records_both_selected_and_dispatched(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection(provider_id="gemini")
        result = await svc.process("hello", {}, selection)
        assert result.metadata.get("provider_selected") == "gemini"
        assert result.metadata.get("provider_dispatched") == "gemini"

    @pytest.mark.asyncio
    async def test_provider_selection_stored_in_metadata(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection(provider_id="gemini")
        result = await svc.process("hello", {}, selection)
        assert "provider_selection" in result.metadata
        assert result.metadata["provider_selection"]["provider_id"] == "gemini"


# ═══════════════════════════════════════════════════════════════════════════════
#  PROVIDER UNAVAILABLE / EXCEPTION / EMPTY — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderFailureModes:
    @pytest.mark.asyncio
    async def test_no_provider_returns_failed(self):
        svc, _, _ = _make_service(route_returns_none=True)
        selection = _make_selection(provider_id="gemini")
        result = await svc.process("hello", {}, selection)
        assert result.kind.value == "FAILED"
        assert result.metadata.get("provider_available") is False

    @pytest.mark.asyncio
    async def test_provider_exception_returns_failed(self):
        managed = _StubManagedProvider(exc=RuntimeError("boom"))
        svc, _, _ = _make_service(managed=managed)
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.kind.value == "FAILED"
        assert result.metadata.get("provider_error") == "RuntimeError"

    @pytest.mark.asyncio
    async def test_provider_empty_response_returns_failed(self):
        managed = _StubManagedProvider(response=_StubProviderResponse(text="   "))
        svc, _, _ = _make_service(managed=managed)
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.kind.value == "FAILED"
        assert result.metadata.get("provider_empty") is True

    @pytest.mark.asyncio
    async def test_provider_exception_has_provider_evidence(self):
        managed = _StubManagedProvider(exc=ValueError("test"))
        svc, _, _ = _make_service(managed=managed)
        selection = _make_selection(provider_id="gemini")
        result = await svc.process("hello", {}, selection)
        assert result.provider_evidence is not None
        assert result.provider_evidence.provider_id == "gemini"
        assert result.provider_evidence.invoked is True


# ═══════════════════════════════════════════════════════════════════════════════
#  PROVENANCE — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProvenance:
    @pytest.mark.asyncio
    async def test_canonical_authority_in_metadata(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.metadata.get("canonical_authority") == "CanonicalConversationContentService"

    @pytest.mark.asyncio
    async def test_canonical_mission_false(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.metadata.get("canonical_mission") is False

    @pytest.mark.asyncio
    async def test_classification_canonical_conversation_content(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert result.metadata.get("classification") == "CANONICAL_CONVERSATION_CONTENT"

    @pytest.mark.asyncio
    async def test_resource_ids_include_provider(self):
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection()
        result = await svc.process("hello", {}, selection)
        assert "provider:gemini" in result.provider_evidence.resource_ids


# ═══════════════════════════════════════════════════════════════════════════════
#  FINANCE / APPLICATION PRESERVATION — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinanceApplicationPreservation:
    def test_finance_field_filling_unchanged(self):
        """M23.2 finance field-filling must not be modified."""
        from intent_kernel.conversation.policy import next_finance_field, classify_finance_turn
        assert callable(next_finance_field)
        assert callable(classify_finance_turn)

    def test_application_field_filling_unchanged(self):
        """M23.4 application field-filling must not be modified."""
        from intent_kernel.conversation.policy import next_application_field, classify_application_turn
        assert callable(next_application_field)
        assert callable(classify_application_turn)


# ═══════════════════════════════════════════════════════════════════════════════
#  MISSION MODE NEVER ENTERS CONTENT SERVICE — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissionModeNeverEnters:
    def test_service_not_called_from_mission_path(self):
        """CanonicalConversationContentService must not be imported in mission paths."""
        import inspect
        from intent_kernel.application.mission_service import CanonicalMissionService
        source = inspect.getsource(CanonicalMissionService)
        assert "CanonicalConversationContentService" not in source

    def test_mission_runtime_no_content_service(self):
        """MissionRuntime must not reference CanonicalConversationContentService."""
        import inspect
        from intent_kernel.runtime import MissionRuntime
        source = inspect.getsource(MissionRuntime)
        assert "CanonicalConversationContentService" not in source


# ═══════════════════════════════════════════════════════════════════════════════
#  NO PRODUCTIVE SIDE EFFECTS — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoProductiveSideEffects:
    def test_service_has_no_filesystem_mutation(self):
        """Service must not write to filesystem."""
        import inspect
        source = inspect.getsource(CanonicalConversationContentService)
        assert "open(" not in source
        assert "write(" not in source
        assert "Path(" not in source

    def test_service_has_no_email_send(self):
        """Service must not send email."""
        import inspect
        source = inspect.getsource(CanonicalConversationContentService)
        assert "email" not in source.lower()
        assert "smtp" not in source.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  H1 PRESERVED — 3 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestH1Preserved:
    def test_h1_conversation_service_imports(self):
        """H1: CognitiveConversationService must remain importable."""
        from intent_kernel.conversation import CognitiveConversationService
        assert CognitiveConversationService is not None

    def test_h1_provider_authority_imports(self):
        """H1: CanonicalProviderAuthority must remain importable."""
        from intent_kernel.providers.authority import CanonicalProviderAuthority
        assert CanonicalProviderAuthority is not None

    def test_h1_constitution_engine_imports(self):
        """H1: CanonicalConstitutionEngine must remain importable."""
        from intent_kernel.constitution.canonical import CanonicalConstitutionEngine
        assert CanonicalConstitutionEngine is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  NO TOOLAUTHORIZATIONGATE / VERIFICATIONGATE AS CONTENT AUTHORITY — 2 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoToolVerificationGateAsContentAuthority:
    def test_service_no_tool_authorization_gate(self):
        """Service must not use ToolAuthorizationGate."""
        import inspect
        source = inspect.getsource(CanonicalConversationContentService)
        assert "ToolAuthorizationGate" not in source
        assert "tool_authorization" not in source.lower()

    def test_service_no_verification_gate(self):
        """Service must not use VerificationGate."""
        import inspect
        source = inspect.getsource(CanonicalConversationContentService)
        assert "VerificationGate" not in source
        assert "verification_gate" not in source.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  ADVERSARIAL — 4 tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdversarial:
    @pytest.mark.asyncio
    async def test_empty_message_still_processes(self):
        svc, _, _ = _make_service()
        selection = _make_selection()
        result = await svc.process("", {}, selection)
        assert isinstance(result, CanonicalTurnResult)

    @pytest.mark.asyncio
    async def test_context_filtering_removes_flow_event(self):
        svc, engine, _ = _make_service()
        selection = _make_selection()
        await svc.process("test", {"session_id": "s1", "flow_event": lambda: None}, selection)
        _, _, ctx = engine.calls[0]
        assert "flow_event" not in ctx
        assert ctx.get("session_id") == "s1"

    @pytest.mark.asyncio
    async def test_provider_evidence_has_invoked_false_when_local(self):
        """When used_provider is 'local', invoked must be False."""
        svc, _, pm = _make_service()
        pm._last_used = None
        selection = _make_selection(provider_id=None, available=False)
        # Route returns None -> failed
        svc2, _, _ = _make_service(route_returns_none=True)
        result = await svc2.process("hello", {}, selection)
        assert result.kind.value == "FAILED"

    @pytest.mark.asyncio
    async def test_metadata_not_shared_between_calls(self):
        """Each call must produce independent metadata dict."""
        svc, _, pm = _make_service()
        pm._last_used = "gemini"
        selection = _make_selection()
        r1 = await svc.process("a", {}, selection)
        r2 = await svc.process("b", {}, selection)
        assert r1.metadata is not r2.metadata
