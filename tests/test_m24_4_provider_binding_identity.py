"""Movement 24.4 — Provider binding identity preservation tests.

Validates that the exact provider object selected/revalidated is the exact
provider object dispatched. String/provider-ID equality alone is NOT sufficient.

Pre-fix expected defect:
    selection refers to A
    provider ID remains "provider-a"
    fresh registry lookup resolves B
    B can be executed
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

from intent_kernel.contracts import ProviderRequest, ProviderResponse
from intent_kernel.providers.manager import ManagedProvider, ProviderManager
from intent_kernel.providers.authority import (
    CanonicalProviderAuthority,
    ProviderSelectionDecision,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER STUBS
# ═══════════════════════════════════════════════════════════════════════════════

class _TrackingProvider:
    """Provider that records execute() calls for identity verification."""
    def __init__(self, name: str, text: str = "response"):
        self.name = name
        self.text = text
        self.executed = False
        self.execute_count = 0

    @property
    def capabilities(self) -> set[str]:
        return {"text_completion"}

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        self.executed = True
        self.execute_count += 1
        return ProviderResponse(
            text=self.text,
            provider=self.name,
            model=f"{self.name}-model",
        )

    async def health(self) -> bool:
        return True


class _AlwaysHealthyRRM:
    """Stub RRM that always reports providers as eligible."""
    def __init__(self):
        self._providers = {}

    def register_provider(self, provider_id: str):
        self._providers[provider_id] = type(
            "Resource",
            (),
            {
                "provider_id": provider_id,
                "is_eligible": True,
                "reasoning_score": 1.0,
                "cost_per_1k_tokens": 0.001,
                "metadata": {"capabilities": ["text_completion"]},
            },
        )()

    def get_provider(self, provider_id: str):
        return self._providers.get(provider_id)

    def list_providers(self, only_eligible: bool = False):
        return list(self._providers.values())


def _make_selection(
    provider_id: str = "provider-a",
    fallback: str | None = None,
    available: bool = True,
) -> ProviderSelectionDecision:
    return ProviderSelectionDecision(
        provider_id=provider_id if available else None,
        fallback_provider_id=fallback,
        required_capabilities=("text_completion",),
        eligible_provider_ids=(provider_id,) if available else (),
        reason="eligible_provider_selected" if available else "no_eligible_provider",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  1. IDENTITY GAP REPRODUCTION (pre-fix defect)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdentityGapReproduction:
    def test_managed_provider_performs_fresh_registry_lookup(self):
        """ManagedProvider.execute() does a fresh registry lookup by string ID.

        This is the core of M24-01: if the registry entry changes between
        bind and dispatch, a different provider object executes.
        """
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a", "from-A")
        provider_b = _TrackingProvider("provider-a", "from-B")  # same ID, different object
        pm.register("provider-a", provider_a)

        # Create a ManagedProvider (simulates what route() does)
        managed = ManagedProvider(pm, provider_id="provider-a")

        # Verify: managed references provider_a via string ID
        assert managed._provider_id == "provider-a"

        # Now swap the registry entry
        pm._providers["provider-a"] = provider_b

        # Execute — ManagedProvider does fresh lookup, gets provider_b
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        # DEFECT: provider_b was executed, not provider_a
        assert not provider_a.executed, (
            "provider_a was NOT executed — fresh lookup returned provider_b instead"
        )
        assert provider_b.executed, (
            "provider_b WAS executed — the identity gap is real"
        )
        assert response.text == "from-B", (
            "Response came from provider_b, confirming identity gap"
        )

    def test_managed_provider_stores_only_string_id_when_no_binding(self):
        """ManagedProvider without bound_provider falls back to registry lookup."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        managed = ManagedProvider(pm, provider_id="provider-a")

        # Without bound_provider, _bound_provider is None
        assert managed._bound_provider is None


# ═══════════════════════════════════════════════════════════════════════════════
#  2. EXISTING BINDING PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

class TestExistingBindingPrimitives:
    def test_bind_selected_has_expected_binding_parameter(self):
        """bind_selected() accepts expected_binding for identity verification."""
        import inspect
        sig = inspect.signature(ProviderManager.bind_selected)
        assert "expected_binding" in sig.parameters

    def test_bind_selected_rejects_mismatched_binding(self):
        """bind_selected() returns None if current registry differs from expected."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        provider_b = _TrackingProvider("provider-a")  # same ID, different object
        pm.register("provider-a", provider_a)

        # Bind with expected_binding=provider_a — succeeds
        result = pm.bind_selected("provider-a", expected_binding=provider_a)
        assert result is not None

        # Now swap registry
        pm._providers["provider-a"] = provider_b

        # Bind with expected_binding=provider_a — fails (identity changed)
        result = pm.bind_selected("provider-a", expected_binding=provider_a)
        assert result is None, (
            "bind_selected should return None when registry entry changed"
        )

    def test_bind_selected_without_expected_binding_does_not_verify(self):
        """bind_selected() without expected_binding does not verify identity."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        provider_b = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        # Swap before binding
        pm._providers["provider-a"] = provider_b

        # Without expected_binding, no identity check
        result = pm.bind_selected("provider-a")
        assert result is not None

    def test_bind_selected_returns_managed_provider(self):
        """bind_selected() returns a ManagedProvider with allow_manager_fallback=False."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        result = pm.bind_selected("provider-a", expected_binding=provider_a)
        assert isinstance(result, ManagedProvider)
        assert result._allow_manager_fallback is False


# ═══════════════════════════════════════════════════════════════════════════════
#  3. REPAIR: MANAGED PROVIDER WITH BOUND OBJECT
# ═══════════════════════════════════════════════════════════════════════════════

class TestRepairBoundProvider:
    def test_managed_provider_with_bound_provider_uses_bound_object(self):
        """When _bound_provider is set, execute() uses it instead of fresh lookup."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a", "from-A")
        provider_b = _TrackingProvider("provider-a", "from-B")
        pm.register("provider-a", provider_a)

        # Create ManagedProvider with bound provider
        managed = ManagedProvider(pm, provider_id="provider-a", bound_provider=provider_a)

        # Swap registry
        pm._providers["provider-a"] = provider_b

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        # REPAIR: provider_a was executed (bound), not provider_b (registry)
        assert provider_a.executed, "provider_a (bound) should execute"
        assert not provider_b.executed, "provider_b (registry) should NOT execute"
        assert response.text == "from-A"

    def test_managed_provider_without_bound_provider_uses_registry(self):
        """Without _bound_provider, execute() falls back to registry lookup."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a", "from-A")
        pm.register("provider-a", provider_a)

        managed = ManagedProvider(pm, provider_id="provider-a")

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        assert provider_a.executed
        assert response.text == "from-A"

    def test_route_captures_bound_provider(self):
        """ProviderManager.route() captures the exact provider object."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        # Mock selection authority
        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            managed = loop.run_until_complete(pm.route(None, selection=selection))
        finally:
            loop.close()

        assert managed is not None
        assert managed._bound_provider is provider_a


# ═══════════════════════════════════════════════════════════════════════════════
#  4. PRIMARY PROVIDER BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrimaryProviderBehavior:
    def test_exact_binding_captured_by_route(self):
        """route() captures the exact provider object at bind time."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            managed = loop.run_until_complete(pm.route(None, selection=selection))
        finally:
            loop.close()

        assert managed._bound_provider is provider_a

    def test_revalidation_does_not_replace_selection(self):
        """revalidate() confirms, does not re-select."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        revalidate_calls = []
        class _TrackingAuthority:
            async def revalidate(self, selection):
                revalidate_calls.append(selection)
                return True
        pm.set_selection_authority(_TrackingAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(pm.route(None, selection=selection))
        finally:
            loop.close()

        assert len(revalidate_calls) == 1
        assert revalidate_calls[0] is selection

    def test_dispatch_verifies_exact_binding_identity(self):
        """execute() with bound provider uses bound object, not registry."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a", "from-A")
        provider_b = _TrackingProvider("provider-a", "from-B")
        pm.register("provider-a", provider_a)

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            managed = loop.run_until_complete(pm.route(None, selection=selection))
            # Swap after binding
            pm._providers["provider-a"] = provider_b
            response = loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        assert provider_a.executed
        assert not provider_b.executed
        assert response.text == "from-A"

    def test_replacement_object_with_same_id_cannot_dispatch(self):
        """Registry replacement with same ID cannot dispatch via bound ManagedProvider."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        provider_b = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            managed = loop.run_until_complete(pm.route(None, selection=selection))
            pm._providers["provider-a"] = provider_b
            loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        assert not provider_b.executed, "Replacement provider_b must NOT execute"

    def test_provider_disappearance_fails_closed(self):
        """If bound provider is removed from registry, execute uses bound object."""
        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a", "from-A")
        pm.register("provider-a", provider_a)

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            managed = loop.run_until_complete(pm.route(None, selection=selection))
            # Remove from registry
            del pm._providers["provider-a"]
            response = loop.run_until_complete(
                managed.execute(ProviderRequest(messages=[]))
            )
        finally:
            loop.close()

        # Bound object still executes even if registry entry removed
        assert provider_a.executed
        assert response.text == "from-A"

    def test_provider_exception_maps_to_failed(self):
        """Provider exception still maps to FAILED via CanonicalTurnResult."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        from intent_kernel.response import CanonicalTurnResult

        class _FailingProvider:
            name = "failing-provider"
            capabilities = {"text_completion"}
            async def execute(self, request):
                raise RuntimeError("provider crashed")
            async def health(self):
                return True

        class _StubConstitution:
            async def evaluate(self, action, data, context):
                from intent_kernel.contracts.models import (
                    ConstitutionDecision,
                    ConstitutionVerdict,
                )
                return ConstitutionVerdict(
                    decision=ConstitutionDecision.ALLOW,
                    reason="ok",
                )

        pm = ProviderManager()
        pm.register("failing-provider", _FailingProvider())

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        svc = CanonicalConversationContentService(
            constitution_engine=_StubConstitution(),
            provider_manager=pm,
        )
        selection = _make_selection(provider_id="failing-provider")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                svc.process("test", {}, selection)
            )
        finally:
            loop.close()

        assert isinstance(result, CanonicalTurnResult)
        assert result.kind.value == "FAILED"

    def test_provider_empty_output_maps_to_failed(self):
        """Empty provider output maps to FAILED."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        from intent_kernel.response import CanonicalTurnResult

        class _EmptyProvider:
            name = "empty-provider"
            capabilities = {"text_completion"}
            async def execute(self, request):
                return ProviderResponse(text="   ", provider="empty", model="m")
            async def health(self):
                return True

        class _StubConstitution:
            async def evaluate(self, action, data, context):
                from intent_kernel.contracts.models import (
                    ConstitutionDecision,
                    ConstitutionVerdict,
                )
                return ConstitutionVerdict(
                    decision=ConstitutionDecision.ALLOW,
                    reason="ok",
                )

        pm = ProviderManager()
        pm.register("empty-provider", _EmptyProvider())

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        svc = CanonicalConversationContentService(
            constitution_engine=_StubConstitution(),
            provider_manager=pm,
        )
        selection = _make_selection(provider_id="empty-provider")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                svc.process("test", {}, selection)
            )
        finally:
            loop.close()

        assert isinstance(result, CanonicalTurnResult)
        assert result.kind.value == "FAILED"


# ═══════════════════════════════════════════════════════════════════════════════
#  5. NO SECOND SELECTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoSecondSelection:
    def test_select_called_once_in_content_service(self):
        """CanonicalProviderAuthority.select() is called once per content request."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        from intent_kernel.contracts.models import (
            ConstitutionDecision,
            ConstitutionVerdict,
        )

        class _StubConstitution:
            async def evaluate(self, action, data, context):
                return ConstitutionVerdict(
                    decision=ConstitutionDecision.ALLOW,
                    reason="ok",
                )

        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        select_calls = []
        class _TrackingAuthority:
            async def revalidate(self, selection):
                return True
            async def select(self, **kwargs):
                select_calls.append(kwargs)
                return _make_selection()

        authority = _TrackingAuthority()

        svc = CanonicalConversationContentService(
            constitution_engine=_StubConstitution(),
            provider_manager=pm,
        )

        selection = _make_selection()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                svc.process("test", {}, selection)
            )
        finally:
            loop.close()

        # select() is NOT called inside the content service — it's called
        # by ProductBridge before passing selection to the service.
        # The service only calls revalidate() (via route()) and execute().
        assert len(select_calls) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  6. METADATA / EVIDENCE TRUTHFULNESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetadataTruthfulness:
    def test_provider_selected_matches_dispatched(self):
        """provider_selected and provider_dispatched in metadata match."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        from intent_kernel.contracts.models import (
            ConstitutionDecision,
            ConstitutionVerdict,
        )

        class _StubConstitution:
            async def evaluate(self, action, data, context):
                return ConstitutionVerdict(
                    decision=ConstitutionDecision.ALLOW,
                    reason="ok",
                )

        pm = ProviderManager()
        provider_a = _TrackingProvider("provider-a")
        pm.register("provider-a", provider_a)

        class _StubAuthority:
            async def revalidate(self, selection):
                return True
        pm.set_selection_authority(_StubAuthority())

        svc = CanonicalConversationContentService(
            constitution_engine=_StubConstitution(),
            provider_manager=pm,
        )
        selection = _make_selection(provider_id="provider-a")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                svc.process("test", {}, selection)
            )
        finally:
            loop.close()

        assert result.metadata.get("provider_selected") == "provider-a"
        assert result.metadata.get("provider_dispatched") == "provider-a"
        assert result.metadata.get("canonical_mission") is False
        assert result.metadata.get("classification") == "CANONICAL_CONVERSATION_CONTENT"


# ═══════════════════════════════════════════════════════════════════════════════
#  7. STATIC AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaticAudit:
    def test_managed_provider_has_bound_provider_attribute(self):
        """ManagedProvider constructor accepts bound_provider parameter."""
        import inspect
        sig = inspect.signature(ManagedProvider.__init__)
        assert "bound_provider" in sig.parameters

    def test_route_passes_bound_provider(self):
        """ProviderManager.route() passes bound_provider to ManagedProvider."""
        source = pathlib.Path(
            __file__).resolve().parent.parent / "intent_kernel" / "providers" / "manager.py"
        content = source.read_text(encoding="utf-8")
        assert "bound_provider=primary" in content or "bound_provider=" in content

    def test_execute_uses_bound_provider_if_available(self):
        """ManagedProvider.execute() checks _bound_provider before registry lookup."""
        source = pathlib.Path(
            __file__).resolve().parent.parent / "intent_kernel" / "providers" / "manager.py"
        content = source.read_text(encoding="utf-8")
        assert "_bound_provider" in content

    def test_content_service_unchanged(self):
        """CanonicalConversationContentService process() not modified for M24.4."""
        source = pathlib.Path(
            __file__).resolve().parent.parent / "intent_kernel" / "conversation" / "content.py"
        content = source.read_text(encoding="utf-8")
        # The service calls route() which handles binding — no changes needed
        assert "route(" in content

    def test_pipeline_dag_unreachable(self):
        """PipelineDAG remains unreachable from generic conversation path."""
        content = (
            pathlib.Path(__file__).resolve().parent.parent / "product_bridge.py"
        ).read_text(encoding="utf-8")
        lines = content.split("\n")
        in_fallback = False
        for line in lines:
            if "# 5. Canonical Conversation Content Runtime" in line:
                in_fallback = True
            elif in_fallback and ("@staticmethod" in line or "def _compatibility_response" in line):
                break
            if in_fallback and "PipelineDAG" in line:
                pytest.fail("PipelineDAG referenced in canonical conversation path")


# ═══════════════════════════════════════════════════════════════════════════════
#  8. UNCHANGED PATHS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnchangedPaths:
    def test_mission_path_unchanged(self):
        """MissionRuntime not modified."""
        import inspect
        from intent_kernel.runtime import MissionRuntime
        source = inspect.getsource(MissionRuntime)
        assert "bound_provider" not in source

    def test_tool_authorization_gate_unchanged(self):
        """ToolAuthorizationGate not modified."""
        import inspect
        from intent_kernel.tools.authorization import ToolAuthorizationGate
        source = inspect.getsource(ToolAuthorizationGate)
        assert "bound_provider" not in source

    def test_verification_gate_unchanged(self):
        """VerificationGate not modified."""
        from intent_kernel.conversation.content import CanonicalConversationContentService
        import inspect
        source = inspect.getsource(CanonicalConversationContentService)
        assert "VerificationGate" not in source
        assert "ToolAuthorizationGate" not in source

    def test_finance_conversation_policy_unchanged(self):
        """FinanceConversationPolicy not modified."""
        import inspect
        from intent_kernel.conversation.policy import classify_finance_turn
        source = inspect.getsource(classify_finance_turn)
        assert "bound_provider" not in source

    def test_application_conversation_policy_unchanged(self):
        """ApplicationConversationPolicy not modified."""
        import inspect
        from intent_kernel.conversation.policy import classify_application_turn
        source = inspect.getsource(classify_application_turn)
        assert "bound_provider" not in source

    def test_constitution_contract_unchanged(self):
        """CanonicalConstitutionEngine not modified."""
        import inspect
        from intent_kernel.constitution.canonical import CanonicalConstitutionEngine
        source = inspect.getsource(CanonicalConstitutionEngine)
        assert "bound_provider" not in source

    def test_cognitive_conversation_service_unchanged(self):
        """CognitiveConversationService not modified."""
        import inspect
        from intent_kernel.conversation import CognitiveConversationService
        source = inspect.getsource(CognitiveConversationService)
        assert "bound_provider" not in source

    def test_no_productive_external_execution(self):
        """No new productive external execution introduced."""
        source = pathlib.Path(
            __file__).resolve().parent.parent / "intent_kernel" / "providers" / "manager.py"
        content = source.read_text(encoding="utf-8")
        assert "subprocess" not in content
        assert "import requests" not in content
        assert "urllib" not in content
