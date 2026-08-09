"""Pipeline nodes — individual processing steps."""

from __future__ import annotations

from intent_kernel.types import (
    EpistemicStatus,
    PipelineContext,
)


async def intake_node(ctx: PipelineContext) -> PipelineContext:
    """Intake — initial processing of the intent."""
    # The intent is already parsed by IntentEngine
    # Just pass through with initial metadata
    ctx.data["raw_text"] = ctx.intent.raw_text
    ctx.data["entities_found"] = ctx.intent.entities
    return ctx


async def classify_node(ctx: PipelineContext) -> PipelineContext:
    """Classify — domain and mode are already determined."""
    # Classification done by IntentEngine, just record it
    ctx.data["domain"] = ctx.intent.domain.value
    ctx.data["mode"] = ctx.intent.mode.value
    return ctx


async def diagnose_node(ctx: PipelineContext) -> PipelineContext:
    """Diagnose — analyze ambiguities and gaps."""
    ambiguities = ctx.intent.ambiguities
    if ambiguities:
        ctx.data["ambiguities"] = ambiguities
        ctx.data["needs_clarification"] = len(ambiguities) > 0
    else:
        ctx.data["ambiguities"] = []
        ctx.data["needs_clarification"] = False
    return ctx


async def plan_node(ctx: PipelineContext) -> PipelineContext:
    """Plan — select techniques and approach."""
    domain = ctx.intent.domain
    mode = ctx.intent.mode

    # Determine response structure based on mode
    if mode.value in ("expert", "architect"):
        ctx.data["response_structure"] = [
            "summary",
            "analysis",
            "recommendation",
            "alternatives",
            "risks",
            "confidence",
        ]
    else:
        ctx.data["response_structure"] = [
            "summary",
            "recommendation",
            "confidence",
        ]

    return ctx


async def build_node(ctx: PipelineContext) -> PipelineContext:
    """Build — generate the response.

    Priority:
    1. Module handler (domain-specific)
    2. Provider (LLM or mock)
    3. Fallback template
    """
    from intent_kernel.types import EpistemicStatus, IntentInput

    # The official composition pre-executes characterized canonical routes.
    # Legacy routing remains a compatibility fallback for unmigrated domains.
    canonical = ctx.data.get("canonical_capability_result")
    if canonical is not None and not canonical.success:
        code = (
            canonical.error_code.value
            if canonical.error_code is not None
            else "execution_failure"
        )
        ctx.output_text = (
            "**Capability indisponível**\n\n"
            f"A solicitação não pôde ser executada (`{code}`)."
        )
        ctx.confidence = 1.0
        ctx.epistemic_status = EpistemicStatus.FACT
        return ctx
    if canonical is not None and canonical.success:
        ctx.output_text = str(canonical.output or "")
        ctx.confidence = canonical.confidence
        status = canonical.metadata.get(
            "epistemic_status",
            canonical.metadata
            .get("legacy_result", {})
            .get("epistemic_status", "conclusion"),
        )
        try:
            ctx.epistemic_status = EpistemicStatus(status)
        except ValueError:
            ctx.epistemic_status = EpistemicStatus.CONCLUSION
        return ctx

    # Check for domain-specific module
    router = ctx.data.get("router")
    if router:
        intent_input = IntentInput(
            text=ctx.intent.raw_text,
        )
        # Set domain from parsed intent for routing
        intent_input.domain = ctx.intent.domain
        module = router.route(intent_input)
        if module and module.name != "core":
            # Use domain-specific module
            result = await module.execute(intent_input, ctx)
            ctx.output_text = result.get("text", "")
            ctx.confidence = result.get("confidence", 0.5)
            status_str = result.get("epistemic_status", "conclusion")
            try:
                ctx.epistemic_status = EpistemicStatus(status_str)
            except ValueError:
                ctx.epistemic_status = EpistemicStatus.CONCLUSION
            return ctx

    # Fall back to provider
    provider = ctx.data.get("provider")
    if provider:
        from intent_kernel.contracts import (
            ProviderMessage,
            ProviderRequest,
        )
        result = await provider.execute(
            ProviderRequest(
                messages=[
                    ProviderMessage(
                        role="system",
                        content=_system_prompt(ctx),
                    ),
                    ProviderMessage(
                        role="user",
                        content=ctx.intent.raw_text,
                    ),
                ]
            )
        )
        ctx.output_text = result.text
        ctx.confidence = 0.6
        ctx.epistemic_status = EpistemicStatus.CONCLUSION
    else:
        # Fallback — generate structured response
        ctx.output_text = _fallback_build(ctx)
        ctx.confidence = 0.4
        ctx.epistemic_status = EpistemicStatus.ASSUMPTION

    return ctx


async def stress_test_node(ctx: PipelineContext) -> PipelineContext:
    """Stress test — argue against the recommendation."""
    if ctx.output_text:
        # Append a stress test section to the output
        stress = (
            "\n\n---\n\n"
            "**⚖️ Stress Test:**\n"
            "- Qual é o principal risco desta recomendação?\n"
            "- Sob que condições ela estaria errada?\n"
            "- Existe uma alternativa claramente superior?\n"
        )
        ctx.output_text += stress
        ctx.data["stress_test"] = stress
    return ctx


async def review_node(ctx: PipelineContext) -> PipelineContext:
    """Review — validate output quality."""
    # Basic quality checks
    issues = []

    if not ctx.output_text:
        issues.append("Empty output")

    if ctx.confidence < 0.3:
        issues.append("Very low confidence")

    if ctx.intent.ambiguities and len(ctx.intent.ambiguities) > 2:
        issues.append("Multiple unresolved ambiguities")

    ctx.data["review_issues"] = issues
    ctx.data["review_passed"] = len(issues) == 0

    return ctx


async def knowledge_check_node(ctx: PipelineContext) -> PipelineContext:
    """Knowledge check — identify what should be persisted to PKB."""
    events_to_create = []

    # If there's a decision, create a DECISION event
    if ctx.intent.domain.value in ("finance", "business", "engineering"):
        from intent_kernel.pkb.models import KnowledgeEvent
        from intent_kernel.types import EventType

        events_to_create.append(
            KnowledgeEvent(
                type=EventType.DECISION,
                domain=ctx.intent.domain,
                title=f"Decisão: {ctx.intent.intent[:80]}",
                content={"question": ctx.intent.intent, "domain": ctx.intent.domain.value},
                summary=ctx.output_text[:200] if ctx.output_text else "",
                confidence=ctx.confidence,
                epistemic_status=ctx.epistemic_status,
                source="system",
                session_id=ctx.data.get("session_id", ""),
                tags=[ctx.intent.domain.value],
            )
        )

    ctx.events = events_to_create
    return ctx


async def deliver_node(ctx: PipelineContext) -> PipelineContext:
    """Deliver — finalize output with metadata."""
    # Append mode/domain indicators
    mode_emoji = {
        "quick": "⚡",
        "basic": "📋",
        "detail": "🔍",
        "expert": "🧠",
        "architect": "🏗️",
    }

    emoji = mode_emoji.get(ctx.mode.value, "📋")

    # Add footer
    footer = (
        f"\n\n---\n"
        f"{emoji} Modo: {ctx.mode.value.upper()} | "
        f"🏷️ Domínio: {ctx.intent.domain.value} | "
        f"🔒 Confiança: {ctx.confidence:.0%}"
    )

    ctx.output_text += footer

    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _system_prompt(ctx: PipelineContext) -> str:
    """Generate system prompt based on context."""
    return (
        "Você é o Intent OS, um sistema operacional cognitivo. "
        f"Domínio: {ctx.intent.domain.value}. "
        f"Modo: {ctx.mode.value}. "
        "Processo: Compreender → Diagnosticar → Construir → Revisar → Entregar. "
        "Respostas devem ser: claras, estruturadas, honestas sobre confiança. "
        "Classifique sua resposta com status epistêmico (fato/estimativa/conclusão/suposição)."
    )


def _fallback_build(ctx: PipelineContext) -> str:
    """Generate a fallback response without a provider."""
    domain = ctx.intent.domain.value
    mode = ctx.mode.value

    return (
        f"**Processamento Intent OS**\n\n"
        f"**Intenção:** {ctx.intent.intent[:100]}\n\n"
        f"**Classificação:**\n"
        f"- Domínio: {domain}\n"
        f"- Modo: {mode}\n"
        f"- Entidades: {', '.join(ctx.intent.entities[:5]) if ctx.intent.entities else 'nenhuma detectada'}\n\n"
        f"**Resposta:**\n"
        f"Para processar completamente esta intenção, um provedor de LLM é necessário. "
        f"O Kernel está funcionando corretamente — falta apenas o provider.\n\n"
        f"📋 *Suposição operacional: resposta sem LLM.*"
    )
