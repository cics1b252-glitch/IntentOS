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


# --------------------------------------------------------------------------
# Platform containment capability (M34-F).  Honest, not aspirational.
# --------------------------------------------------------------------------
#: ``O_NOFOLLOW`` makes the kernel refuse to traverse a symlink at the final
#: component. ``dir_fd`` lets the write be anchored to an already-opened
#: directory handle so no path string is re-resolved at write time. Together
#: they close the check->write race. Windows exposes neither.
_HAS_O_NOFOLLOW = hasattr(os, "O_NOFOLLOW") and hasattr(os, "supports_dir_fd") \
    and os.O_NOFOLLOW in os.supports_dir_fd
_SUPPORTS_DIR_FD = hasattr(os, "supports_dir_fd") and os.open in os.supports_dir_fd

#: What containment this platform can actually guarantee. Reported explicitly
#: so no caller can mistake "checked" for "atomic".
CONTAINMENT_MODE = (
    "POSIX_ATOMIC_NOFOLLOW" if (_HAS_O_NOFOLLOW and _SUPPORTS_DIR_FD)
    else "REVALIDATE_NO_ATOMIC_GUARANTEE"
)


class UnsupportedGuaranteeError(RuntimeError):
    """Caller demanded a containment guarantee this platform cannot provide.

    Fail-closed: rather than silently downgrading to a weaker posture, a
    caller that requires atomic containment is refused outright.
    """


def require_atomic_containment() -> str:
    """Fail closed unless the platform can guarantee atomic containment.

    Returns the containment mode. Raises UnsupportedGuaranteeError when the
    caller demands a guarantee the platform cannot uphold - the concurrent
    hostile-path-mutation threat model is explicitly unsupported here and is
    never reported as protected.
    """
    if CONTAINMENT_MODE != "POSIX_ATOMIC_NOFOLLOW":
        raise UnsupportedGuaranteeError(
            "atomic containment against concurrent hostile path mutation is "
            "NOT available on this platform "
            f"(mode={CONTAINMENT_MODE}); refusing to claim the guarantee"
        )
    return CONTAINMENT_MODE


class ContainmentBreach(RuntimeError):
    """A write landed outside the authorized root. Detected, not assumed."""


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
        # Parent creation is itself containment-relevant: mkdir(exist_ok=True)
        # happily traverses an existing symlinked component, so the chain is
        # re-verified AFTER creation and the final write is re-verified AFTER.
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_chain_contained(target)

        # Exclusive create unless overwrite was separately authorized. 'xb'
        # maps to O_CREAT|O_EXCL, which fails if the leaf already exists AND
        # (on POSIX) is the strongest primitive available without O_NOFOLLOW.
        if self._grant.allow_overwrite:
            target.write_bytes(content)
        else:
            try:
                with open(target, "xb") as handle:
                    handle.write(content)
            except FileExistsError:
                # A concurrent racer won the exclusive create. Surface the
                # canonical stable deny code, never a raw OS exception.
                self.denials.append("overwrite-not-authorized")
                return ExecutionReceipt(
                    reported_path=str(target),
                    reported_success=False,
                    reported_digest="",
                    effect_occurred=False,
                )

        # Post-write containment proof. If a concurrent hostile mutation
        # redirected the write, this catches it instead of reporting success.
        self._assert_chain_contained(target, stage="post-write")
        landed = target.resolve()
        if landed != self._grant.authorized_target.resolve():
            raise ContainmentBreach(
                f"write landed at {landed}, not the authorized target"
            )
        if sha256_bytes(target.read_bytes()) != self._grant.expected_content_sha256:
            raise ContainmentBreach("post-write digest does not match authority")

        return ExecutionReceipt(
            reported_path=str(target),
            reported_success=True,
            reported_digest=sha256_bytes(content),
            effect_occurred=True,
        )

    def _assert_chain_contained(self, target: Path, stage: str = "pre-write") -> None:
        """Re-verify every component from the root down to the leaf."""
        root = self._grant.authorized_root
        probe = root
        if probe.is_symlink():
            raise ContainmentBreach(f"authorized root is a symlink ({stage})")
        for part in target.relative_to(root).parts:
            probe = probe / part
            if probe.is_symlink():
                raise ContainmentBreach(
                    f"symlinked path component at {probe} ({stage})"
                )
        resolved = target.resolve()
        if resolved != root and root not in resolved.parents:
            raise ContainmentBreach(
                f"{resolved} escapes {root} ({stage})"
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