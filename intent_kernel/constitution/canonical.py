"""Canonical Constitution and governance pipeline for Intent OS v2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from intent_kernel.constitution.checker import ConstitutionChecker
from intent_kernel.constitution.models import Constitution
from intent_kernel.contracts import (
    ConstitutionDecision,
    ConstitutionVerdict,
    EventPublisher,
    Mission,
)
from intent_kernel.contracts.models import utcnow


@dataclass(frozen=True, slots=True)
class GovernanceRequest:
    """Normalized input seen by every official Guardian."""

    action: str
    data: Any = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuardianResult:
    """One Guardian's contribution to the canonical verdict."""

    guardian: str
    decision: ConstitutionDecision
    reason: str = "OK"
    rule: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Guardian(Protocol):
    """Unique contract implemented by all official Guardians."""

    name: str
    responsibility: str

    def evaluate(self, request: GovernanceRequest) -> GuardianResult: ...


class _CheckerGuardian:
    name = ""
    responsibility = ""
    check_name = ""

    def __init__(self, checker: ConstitutionChecker):
        self._checker = checker

    def evaluate(self, request: GovernanceRequest) -> GuardianResult:
        if request.action != "knowledge.ingest":
            return self._allow()
        event = _normalize_knowledge_event(request.data)
        check = getattr(self._checker, self.check_name)(event)
        if check.decision == "blocked":
            decision = ConstitutionDecision.DENY
        elif check.decision == "flagged":
            # A flag was historically advisory. Keep it non-blocking.
            decision = ConstitutionDecision.ALLOW_WITH_CONDITIONS
        else:
            decision = ConstitutionDecision.ALLOW
        return GuardianResult(
            guardian=self.name,
            decision=decision,
            reason=check.reason,
            rule=check.check_type,
            evidence={"legacy_decision": check.decision},
        )

    def _allow(self) -> GuardianResult:
        return GuardianResult(self.name, ConstitutionDecision.ALLOW)


class SecurityGuardian(_CheckerGuardian):
    name = "security"
    responsibility = "Sensitive data and user sovereignty"
    check_name = "check_soberania"


class ContinuityGuardian(_CheckerGuardian):
    name = "continuity"
    responsibility = "Mission and knowledge continuity"
    check_name = "check_continuidade"


class IntegrityGuardian(_CheckerGuardian):
    name = "integrity"
    responsibility = "Truth, confidence, and structural integrity"
    check_name = "check_verdade"

    def __init__(
        self,
        checker: ConstitutionChecker,
        constitution: Constitution,
    ):
        super().__init__(checker)
        self._constitution = constitution

    def evaluate(self, request: GovernanceRequest) -> GuardianResult:
        from intent_kernel.types import Action

        structural = self._constitution.validate(
            Action(type=request.action, data=request.data)
        )
        if not structural.allowed:
            return GuardianResult(
                guardian=self.name,
                decision=ConstitutionDecision.DENY,
                reason=structural.reason,
                rule=structural.violated_constraint,
            )
        return super().evaluate(request)


class PolicyGuardian:
    name = "policy"
    responsibility = "Constitutional policy and user authority"

    def evaluate(self, request: GovernanceRequest) -> GuardianResult:
        return GuardianResult(self.name, ConstitutionDecision.ALLOW)


class MemoryGuardian:
    name = "memory"
    responsibility = "Knowledge retention, deletion, and heritage"

    def evaluate(self, request: GovernanceRequest) -> GuardianResult:
        return GuardianResult(self.name, ConstitutionDecision.ALLOW)


class AuditGuardian:
    name = "audit"
    responsibility = "Traceability of governance decisions"

    def evaluate(self, request: GovernanceRequest) -> GuardianResult:
        return GuardianResult(self.name, ConstitutionDecision.ALLOW)


@dataclass(frozen=True, slots=True)
class ConstitutionAuditRecord:
    audit_id: str
    action: str
    decision: str
    reason: str
    guardian_results: tuple[dict[str, Any], ...]
    correlation_id: str = ""
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())


class CanonicalConstitutionEngine:
    """The single official authority for all constitutional decisions."""

    def __init__(
        self,
        constitution: Constitution,
        *,
        guardians: list[Guardian] | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        self.constitution = constitution
        self.event_publisher = event_publisher
        checker = ConstitutionChecker()
        self.guardians: tuple[Guardian, ...] = tuple(
            guardians
            or [
                SecurityGuardian(checker),
                PolicyGuardian(),
                ContinuityGuardian(checker),
                MemoryGuardian(),
                IntegrityGuardian(checker, constitution),
                AuditGuardian(),
            ]
        )
        self._audit_log: list[ConstitutionAuditRecord] = []

    async def evaluate(
        self,
        action: str,
        data: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ConstitutionVerdict:
        request = GovernanceRequest(
            action=action,
            data=deepcopy(data),
            context=deepcopy(context or {}),
        )
        results = [guardian.evaluate(request) for guardian in self.guardians]
        verdict = self._resolve(results)
        record = self._record(request, results, verdict)
        verdict.metadata["audit_id"] = record.audit_id
        verdict.metadata["guardian_results"] = [
            _guardian_dict(result) for result in results
        ]
        await self._publish(record)
        return verdict

    def get_audit_log(self) -> list[ConstitutionAuditRecord]:
        return list(self._audit_log)

    def _resolve(
        self,
        results: list[GuardianResult],
    ) -> ConstitutionVerdict:
        denied = [
            result
            for result in results
            if result.decision is ConstitutionDecision.DENY
        ]
        conditioned = [
            result
            for result in results
            if result.decision
            is ConstitutionDecision.ALLOW_WITH_CONDITIONS
        ]
        selected = denied or conditioned
        if denied:
            decision = ConstitutionDecision.DENY
        elif conditioned:
            decision = ConstitutionDecision.ALLOW_WITH_CONDITIONS
        else:
            decision = ConstitutionDecision.ALLOW
        reason = (
            " | ".join(result.reason for result in selected)
            if selected
            else "All constitutional checks passed."
        )
        return ConstitutionVerdict(
            decision=decision,
            reason=reason,
            violated_rule=next(
                (result.rule for result in denied if result.rule),
                None,
            ),
            conditions=[
                result.reason for result in conditioned
            ],
            evidence=[
                {
                    "guardian": result.guardian,
                    **deepcopy(result.evidence),
                }
                for result in results
            ],
            constitution_version=self.constitution.version,
        )

    def _record(
        self,
        request: GovernanceRequest,
        results: list[GuardianResult],
        verdict: ConstitutionVerdict,
    ) -> ConstitutionAuditRecord:
        correlation_id = str(request.context.get("correlation_id", ""))
        record = ConstitutionAuditRecord(
            audit_id=f"constitution-{len(self._audit_log) + 1}",
            action=request.action,
            decision=verdict.decision.value,
            reason=verdict.reason,
            guardian_results=tuple(
                _guardian_dict(result) for result in results
            ),
            correlation_id=correlation_id,
        )
        self._audit_log.append(record)
        return record

    async def _publish(self, record: ConstitutionAuditRecord) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.publish(
            "constitution.audit",
            asdict(record),
            correlation_id=record.correlation_id,
        )


class ConstitutionPipeline:
    """Mission -> Constitution -> Guardians -> Verdict -> execution."""

    def __init__(self, constitution: CanonicalConstitutionEngine):
        self.constitution = constitution

    async def authorize(
        self,
        mission: Mission,
        action: str,
        data: Any = None,
    ) -> ConstitutionVerdict:
        return await self.constitution.evaluate(
            action,
            data,
            {
                "mission_id": str(mission.id),
                "correlation_id": mission.context.correlation_id,
            },
        )

    async def execute(
        self,
        mission: Mission,
        action: str,
        operation: Callable[[], Awaitable[Any]],
        data: Any = None,
    ) -> tuple[ConstitutionVerdict, Any | None]:
        verdict = await self.authorize(mission, action, data)
        if not verdict.allowed:
            return verdict, None
        return verdict, await operation()


def _normalize_knowledge_event(data: Any) -> dict[str, Any]:
    if is_dataclass(data):
        event = asdict(data)
    elif isinstance(data, dict):
        event = deepcopy(data)
    else:
        event = {"content": data}
    if "type" not in event and "event_type" in event:
        event["type"] = event["event_type"]
    lifecycle = event.get("lifecycle")
    if hasattr(lifecycle, "value"):
        event["level"] = lifecycle.value.upper()
    elif isinstance(lifecycle, str):
        event["level"] = lifecycle.upper()
    content = event.get("content")
    if not isinstance(content, dict):
        event["content"] = {"raw": str(content)}
    metadata = event.setdefault("metadata", {})
    metadata.setdefault("confidence", event.get("confidence", 1.0))
    event["content"].setdefault("source", event.get("source", "conversation"))
    return event


def _guardian_dict(result: GuardianResult) -> dict[str, Any]:
    value = asdict(result)
    value["decision"] = result.decision.value
    return value
