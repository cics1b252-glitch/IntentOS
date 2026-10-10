"""FRONT-M34: CREATE_TEST_FILE - real host filesystem effect, governed.

INTEGRATION POINT
    This module implements the EXISTING frozen port
    ``intent_kernel.runtime.executor_port.ActionExecutorPort``. It adds no
    new port, changes no frozen Core contract, and grants no authority. The
    governed path it rides is the canonical one:

        MissionRuntime.run_mission
            -> ProductiveDispatchGuard.acquire   (durable attempt authority)
            -> executor.execute(contract)        <-- THIS adapter
            -> independent verification

    Authority is NOT taken from the caller, the plan, or the executor's own
    response. It is re-proven HERE, at effect time, against an
    ``IntentAuthorityRecord`` the adapter was constructed with. Absence,
    expiry, revocation, or any mismatch means the filesystem is not touched.

CANONICAL INVARIANTS ENFORCED
    CREATE_TEST_FILE_ADAPTER != AUTHORITY
    EXECUTOR_SUCCESS != OBSERVED_EFFECT          (see observer below)
    AUTHORIZED_TARGET != OBSERVED_TARGET         (digest-bound)
    AUTHORITY_MISSING != UNLIMITED_AUTHORITY     (absence denies)

The independent observer lives in ``intent_kernel.runtime.verification``'s
port but is implemented here as ``LocalFilesystemObserver``: it re-reads the
host filesystem itself and never inspects the executor's return value.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from intent_kernel.mission.intent_authority import IntentAuthorityRecord
from intent_kernel.runtime.executor_port import ActionExecutorPort
from intent_kernel.runtime.models import ActionContract

CAPABILITY = "m34.create_test_file"
OPERATION = "CREATE_TEST_FILE"


class CreateTestFileDenied(RuntimeError):
    """Effect refused before any filesystem mutation. Carries a stable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass
class CreateTestFileAuthority:
    """Explicit, bounded, intent-derived authority for exactly one effect.

    Constructed ONLY from an approved proposal. Nothing here is inferred from
    a message, a plan, a default, or an executor response.
    """

    authorized_root: Path
    authorized_target: Path
    expected_content_sha256: str
    allow_overwrite: bool = False
    max_content_bytes: int = 64 * 1024
    authority: Optional[IntentAuthorityRecord] = None
    revoked: bool = False
    now_provider: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.authorized_root = Path(self.authorized_root).resolve()
        self.authorized_target = Path(self.authorized_target)
        if len(str(self.expected_content_sha256)) != 64:
            raise CreateTestFileDenied("malformed-content-digest")
        if self.authority is None:
            # Absence of authority is never unlimited authority. The caller
            # must supply an established record; this is not a default grant.
            raise CreateTestFileDenied("authority-missing")
        if not self.authority.ceiling.is_constraining:
            raise CreateTestFileDenied("authority-unbounded")

    # -- authority proof, re-run at EFFECT time ---------------------------
    def _now(self) -> datetime:
        if self.now_provider is not None:
            return self.now_provider()
        return datetime.now(timezone.utc)

    def _effective_target(self, relative: str) -> Path:
        if not relative or os.path.isabs(relative):
            raise CreateTestFileDenied("target-not-relative")
        # Resolve WITHOUT following a symlink at the final component first,
        # so a symlinked leaf cannot smuggle the write outside the root.
        candidate = self.authorized_root / relative
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise CreateTestFileDenied("target-unresolvable", str(exc)) from exc
        root = self.authorized_root
        if resolved != root and root not in resolved.parents:
            raise CreateTestFileDenied("target-escape", str(resolved))
        # Explicit symlink check on every existing ancestor component.
        probe = self.authorized_root
        for part in Path(relative).parts:
            probe = probe / part
            if probe.is_symlink():
                raise CreateTestFileDenied("symlink-escape", str(probe))
        return resolved

    def prove(self, relative: str, content: bytes) -> Path:
        """Re-prove the full authority chain for ONE effect. Raises on deny."""
        if self.revoked:
            raise CreateTestFileDenied("authority-revoked")
        ceiling = self.authority.ceiling

        # 1. validity window (evaluated now, not at establishment time).
        now = self._now()
        start = _parse_iso(ceiling.valid_from)
        end = _parse_iso(ceiling.valid_until)
        if start is not None and now < start:
            raise CreateTestFileDenied("authority-not-yet-valid")
        if end is not None and now >= end:
            raise CreateTestFileDenied("authority-expired")

        # 2. capability + operation ceilings.
        if ceiling.allow_capabilities and CAPABILITY not in ceiling.allow_capabilities:
            raise CreateTestFileDenied("capability-escalation")
        if ceiling.allowed_operations and OPERATION not in ceiling.allowed_operations:
            raise CreateTestFileDenied("operation-escalation")

        # 3. size ceiling.
        if len(content) > self.max_content_bytes:
            raise CreateTestFileDenied("content-too-large")

        # 4. content digest binding.
        if sha256_bytes(content) != self.expected_content_sha256:
            raise CreateTestFileDenied("content-substitution")

        # 5. exact target binding + traversal/symlink containment.
        target = self._effective_target(relative)
        if target != self.authorized_target.resolve():
            raise CreateTestFileDenied("target-substitution")

        # 6. overwrite requires separate authorization.
        if target.exists() and not self.allow_overwrite:
            raise CreateTestFileDenied("overwrite-not-authorized")
        return target


@dataclass
class ExecutionReceipt:
    """What the executor claims. NOT evidence of anything."""

    reported_path: str
    reported_success: bool
    reported_digest: str
    effect_occurred: bool = False


class LocalFileSystemExecutor(ActionExecutorPort):
    """Real host filesystem executor for CREATE_TEST_FILE."""

    SUPPORTED_CAPABILITIES = {CAPABILITY}

    def __init__(self, grant: CreateTestFileAuthority) -> None:
        self._grant = grant
        self.effect_calls = 0
        self.denials: list = []

    async def can_execute(self, action: ActionContract) -> bool:
        return action.capability in self.SUPPORTED_CAPABILITIES

    async def execute(self, action: ActionContract) -> ExecutionReceipt:
        if action.capability not in self.SUPPORTED_CAPABILITIES:
            self.denials.append("unsupported-capability")
            raise CreateTestFileDenied("unsupported-capability", action.capability)
        if action.action_type != OPERATION:
            self.denials.append("operation-escalation")
            raise CreateTestFileDenied("operation-escalation", action.action_type)

        payload = dict(action.inputs_reference or {})
        relative = str(payload.get("path", ""))
        content_raw = payload.get("content", "")
        content = (
            content_raw.encode("utf-8")
            if isinstance(content_raw, str)
            else bytes(content_raw or b"")
        )

        # Authority is proven HERE, at effect time, before any mutation.
        try:
            target = self._grant.prove(relative, content)
        except CreateTestFileDenied as exc:
            self.denials.append(exc.code)
            return ExecutionReceipt(
                reported_path=relative,
                reported_success=False,
                reported_digest="",
                effect_occurred=False,
            )

        self.effect_calls += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create unless overwrite was separately authorized.
        if self._grant.allow_overwrite:
            target.write_bytes(content)
        else:
            with open(target, "xb") as handle:
                handle.write(content)

        return ExecutionReceipt(
            reported_path=str(target),
            reported_success=True,
            reported_digest=sha256_bytes(content),
            effect_occurred=True,
        )

    async def cancel(self, action_id: str) -> bool:
        return False

    async def get_status(self, action_id: str) -> str:
        return "SUCCEEDED" if self.effect_calls else "UNKNOWN"


@dataclass
class ObservationResult:
    """Independent observation of the ACTUAL host filesystem."""

    observed: bool
    exists: bool
    observed_sha256: str
    matches_authorized: bool
    reason: str = ""


class LocalFilesystemObserver:
    """Independent post-effect observation.

    It reads the host filesystem directly. It never receives, parses or
    trusts the executor's ``ExecutionReceipt``. An executor that lies about
    success, or reports success for an effect that never happened, cannot
    influence this component.
    """

    def __init__(self, grant: CreateTestFileAuthority) -> None:
        self._grant = grant

    def observe(self) -> ObservationResult:
        target = self._grant.authorized_target
        if not target.exists():
            return ObservationResult(
                observed=True, exists=False, observed_sha256="",
                matches_authorized=False, reason="effect-absent",
            )
        if not target.is_file():
            return ObservationResult(
                observed=True, exists=True, observed_sha256="",
                matches_authorized=False, reason="not-a-regular-file",
            )
        actual = sha256_bytes(target.read_bytes())
        return ObservationResult(
            observed=True,
            exists=True,
            observed_sha256=actual,
            matches_authorized=(
                actual == self._grant.expected_content_sha256
            ),
            reason="digest-match" if actual == self._grant.expected_content_sha256
            else "digest-mismatch",
        )