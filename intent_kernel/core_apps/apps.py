"""Official Core App adapters over the characterized domain implementations."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    Domain,
    EffectType,
    ErrorCode,
    KnowledgeStore,
    Provider,
    ProviderMessage,
    ProviderRequest,
)
from intent_kernel.modules.atlas import Atlas
from intent_kernel.modules.fin import FinanceModule
from intent_kernel.modules.logos import Logos
from intent_kernel.modules.oem_studio import OEMStudio


class AtlasCoreApp:
    """Canonical Atlas boundary preserving the existing FIN response."""

    app_id = "atlas"

    def __init__(
        self,
        atlas: Atlas | None = None,
        finance_module: FinanceModule | None = None,
    ):
        self.domain = atlas or Atlas()
        self._finance = finance_module or FinanceModule()

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return (
            Capability(
                name="finance.intent",
                description="Characterized financial intent handling",
                domains=(Domain.FINANCE,),
                effect=EffectType.COMPUTE,
            ),
        )

    async def execute(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResult:
        if request.capability != "finance.intent":
            return _unavailable(request.capability)
        from intent_kernel.types import Domain as LegacyDomain
        from intent_kernel.types import IntentInput

        intent = IntentInput(
            text=str(
                request.payload.get("text", request.mission.objective)
            ),
            context=dict(request.context),
            domain=LegacyDomain.FINANCE,
        )
        legacy = await self._finance.execute(intent, request.context)
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output=legacy.get("text", legacy),
            confidence=float(legacy.get("confidence", 0.0)),
            metadata={"legacy_result": legacy},
        )

    async def health(self) -> bool:
        return True


class LogosCoreApp:
    """Canonical Logos boundary with the canonical PKB Port injected."""

    app_id = "logos"

    def __init__(
        self,
        logos: Logos | None = None,
        knowledge_store: KnowledgeStore | None = None,
        provider: Provider | None = None,
    ):
        self.domain = logos or Logos()
        self._knowledge_store = knowledge_store
        self._provider = provider

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return (
            Capability(
                name="knowledge.intent",
                description="Characterized knowledge-domain response",
                domains=(
                    Domain.RESEARCH,
                    Domain.WRITING,
                    Domain.PLANNING,
                    Domain.EDUCATION,
                ),
                effect=EffectType.GENERATE,
            ),
            Capability(
                name="knowledge.project.create",
                description="Create a Logos project",
                domains=(Domain.RESEARCH, Domain.WRITING),
                effect=EffectType.PERSIST,
            ),
            Capability(
                name="knowledge.project.list",
                description="List Logos projects",
                domains=(Domain.RESEARCH, Domain.WRITING),
                effect=EffectType.READ,
            ),
            Capability(
                name="knowledge.search",
                description="Query the canonical PKB",
                domains=(Domain.RESEARCH,),
                effect=EffectType.READ,
            ),
        )

    async def execute(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResult:
        if request.capability == "knowledge.intent":
            return await _provider_intent(request, self._provider)
        if request.capability == "knowledge.project.create":
            result = self.domain.create_project(
                name=str(request.payload.get("name", request.mission.objective)),
                description=str(request.payload.get("description", "")),
                domain=str(request.payload.get("domain", "general")),
                tags=list(request.payload.get("tags", [])),
            )
        elif request.capability == "knowledge.project.list":
            result = self.domain.list_projects()
        elif (
            request.capability == "knowledge.search"
            and self._knowledge_store is not None
        ):
            result = await self._knowledge_store.query(
                dict(request.payload.get("filters", {}))
            )
        else:
            return _unavailable(request.capability)
        return _success(request.capability, result)

    async def health(self) -> bool:
        if self._knowledge_store is None:
            return True
        return bool(await self._knowledge_store.health())


class OEMStudioCoreApp:
    """Canonical OEM Studio boundary without infrastructure ownership."""

    app_id = "oem_studio"

    def __init__(
        self,
        studio: OEMStudio | None = None,
        provider: Provider | None = None,
    ):
        self.domain = studio or OEMStudio()
        self._provider = provider

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return (
            Capability(
                name="engineering.intent",
                description="Characterized engineering-domain response",
                domains=(Domain.ENGINEERING, Domain.PROGRAMMING),
                effect=EffectType.GENERATE,
            ),
            Capability(
                name="engineering.project.create",
                description="Create an OEM Studio project",
                domains=(Domain.ENGINEERING,),
                effect=EffectType.PERSIST,
            ),
            Capability(
                name="engineering.project.list",
                description="List OEM Studio projects",
                domains=(Domain.ENGINEERING,),
                effect=EffectType.READ,
            ),
        )

    async def execute(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResult:
        if request.capability == "engineering.intent":
            return await _provider_intent(request, self._provider)
        if request.capability == "engineering.project.create":
            result = self.domain.create_project(
                name=str(request.payload.get("name", request.mission.objective)),
                description=str(request.payload.get("description", "")),
                domain=str(request.payload.get("domain", "engineering")),
                tags=list(request.payload.get("tags", [])),
            )
        elif request.capability == "engineering.project.list":
            result = self.domain.list_projects()
        else:
            return _unavailable(request.capability)
        return _success(request.capability, result)

    async def health(self) -> bool:
        return True


def _success(capability: str, value: Any) -> CapabilityResult:
    return CapabilityResult(
        capability=capability,
        success=True,
        output=_plain(value),
        confidence=1.0,
    )


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _unavailable(capability: str) -> CapabilityResult:
    return CapabilityResult(
        capability=capability,
        success=False,
        error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
    )


async def _provider_intent(
    request: CapabilityRequest,
    provider: Provider | None,
) -> CapabilityResult:
    if provider is None:
        return CapabilityResult(
            capability=request.capability,
            success=False,
            error_code=ErrorCode.PROVIDER_UNAVAILABLE,
        )
    domain = request.mission.context.domain.value
    mode = request.mission.context.mode.value
    response = await provider.execute(
        ProviderRequest(
            messages=[
                ProviderMessage(
                    role="system",
                    content=(
                        "Você é o Intent OS, um sistema operacional cognitivo. "
                        f"Domínio: {domain}. "
                        f"Modo: {mode}. "
                        "Processo: Compreender → Diagnosticar → Construir → "
                        "Revisar → Entregar. Respostas devem ser: claras, "
                        "estruturadas, honestas sobre confiança. Classifique "
                        "sua resposta com status epistêmico "
                        "(fato/estimativa/conclusão/suposição)."
                    ),
                ),
                ProviderMessage(
                    role="user",
                    content=str(
                        request.payload.get(
                            "text",
                            request.mission.objective,
                        )
                    ),
                ),
            ],
            metadata={"mission_id": str(request.mission.id)},
        )
    )
    metadata = {
        "epistemic_status": "conclusion",
        "provider_invocation_attempted": bool(response.provider),
    }
    if response.provider:
        metadata.update({
            "provider": response.provider,
            "model": response.model,
            "usage": response.usage,
        })
    if response.metadata.get("provider_selection"):
        metadata["provider_selection"] = response.metadata["provider_selection"]
        metadata["provider_selection_authority"] = "RRM"
    return CapabilityResult(
        capability=request.capability,
        success=response.error_code is None,
        output=response.text,
        confidence=0.6,
        error_code=response.error_code,
        metadata=metadata,
    )
