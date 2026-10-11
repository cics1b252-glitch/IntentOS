"""FRONT-TP-05B: local-only governed Technical Preview harness.

    HARNESS != AUTHORITY          HARNESS != APPROVER
    THE HARNESS NEVER AUTO-APPROVES

Operator flow (explicit, in this order):

    1. prepare a DISPOSABLE, isolated root
    2. present the proposed action and its exact bounded scope
    3. request EXPLICIT operator approval (a human act; never automatic)
    4. establish authority from the approved grant
    5. register the trusted local approval (token stays INTERNAL)
    6. execute ONE governed CREATE_TEST_FILE effect
    7. display an INDEPENDENTLY observed verification

Deliberate properties
---------------------
* The harness NEVER approves on the operator's behalf. ``approve()`` must be
  called with an affirmative operator decision, or no authority exists.
* The approval token is minted, consumed and dropped inside
  :func:`run_preview`. It is never accepted from, nor returned to, the caller,
  never read from HTTP, request context, environment or CLI, and never
  serialized. :func:`PreviewReport` carries only a fingerprint.
* Real effects are limited to CREATE_TEST_FILE inside the disposable root.
* Native preventive containment and independent host observation are
  preserved from M34/M35; nothing here re-implements them.
* Default simulation behaviour is untouched: nothing here alters the shared
  runtime's default executor beyond the single bound dispatch, which is
  restored by the selector.
* Not exposed through HTTP: this module is import-only, in-process.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from intent_kernel.adapters.local_filesystem import (
    CAPABILITY,
    OPERATION,
    CreateTestFileAuthority,
    LocalFilesystemObserver,
    sha256_bytes,
)
from intent_kernel.adapters.native_containment import platform_capabilities
from intent_kernel.adapters.preview_selection import (
    PreviewSelectionDenied,
    run_bound_dispatch,
)
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    establish_intent_authority_from_grant,
    propose_intent_authority,
)
from intent_kernel.preview.trusted_approval import (
    LOCAL_APPROVALS,
    register_local_approval,
    token_fingerprint,
)
from intent_kernel.runtime.executor_port import InMemoryActionExecutor
from intent_kernel.runtime.models import ActionContract

OPERATION_NAME = OPERATION
DEFAULT_CONTENT = b"intent-os governed technical preview\n"


class PreviewDenied(RuntimeError):
    """The preview was refused. Carries a stable, displayable reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class PreviewProposal:
    """What the operator is asked to approve. Display-only, never authority."""

    authorized_root: str
    target_name: str
    content_sha256: str
    content_bytes: int
    capability: str
    operation: str
    max_risk_level: str
    max_side_effect: str
    requires_verification: bool
    valid_from: str
    valid_until: str

    def render(self) -> str:
        """Human-readable presentation of the exact proposed scope."""
        return "\n".join([
            "PROPOSED GOVERNED PREVIEW EFFECT",
            "-------------------------------",
            f"  capability         : {self.capability}",
            f"  operation          : {self.operation}",
            f"  authorized root    : {self.authorized_root}",
            f"  exact target       : {self.target_name}",
            f"  content sha256     : {self.content_sha256}",
            f"  content bytes      : {self.content_bytes}",
            f"  max risk level     : {self.max_risk_level}",
            f"  max side effect    : {self.max_side_effect}",
            f"  requires verif.    : {self.requires_verification}",
            f"  valid from / until : {self.valid_from} .. {self.valid_until}",
        ])


@dataclass
class PreviewReport:
    """Operator-facing result. Contains NO token, ever."""

    approved: bool
    outcome: str
    reason: str
    authorized_root: str = ""
    target_name: str = ""
    observed_exists: bool = False
    observed_sha256: str = ""
    matches_authorized: bool = False
    approval_fingerprint: str = ""
    cleaned_root: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        lines = [
            "GOVERNED PREVIEW RESULT",
            "------------------------",
            f"  outcome            : {self.outcome}",
            f"  reason             : {self.reason}",
        ]
        if self.authorized_root:
            lines += [
                f"  authorized root    : {self.authorized_root}",
                f"  exact target       : {self.target_name}",
                f"  file observed      : {self.observed_exists}",
                f"  observed sha256    : {self.observed_sha256}",
                f"  matches authority  : {self.matches_authorized}",
                f"  approval id        : {self.approval_fingerprint} (fingerprint only)",
                f"  root cleaned up    : {self.cleaned_root}",
            ]
        return "\n".join(lines)


def prepare_disposable_root(parent: Optional[Path] = None) -> Path:
    """Create an isolated, disposable directory for one preview run."""
    root = Path(tempfile.mkdtemp(prefix="intentos-preview-",
                                 dir=str(parent) if parent else None))
    return root


def propose_preview(
    *,
    root: Path,
    target_name: str = "governed-preview.txt",
    content: bytes = DEFAULT_CONTENT,
    ttl_seconds: int = 300,
    now: Optional[datetime] = None,
) -> PreviewProposal:
    """Build the PROPOSAL only. This grants nothing and approves nothing."""
    if not isinstance(target_name, str) or not target_name \
            or "/" in target_name or "\\" in target_name:
        raise PreviewDenied("invalid-target-name", str(target_name))
    now = now or datetime.now(timezone.utc)
    caps = platform_capabilities()
    if not caps.get("preventive"):
        raise PreviewDenied(
            "platform-not-supported", str(caps.get("platform")))
    root = Path(root)
    if not root.is_dir():
        raise PreviewDenied("root-missing", str(root))
    return PreviewProposal(
        authorized_root=str(root),
        target_name=target_name,
        content_sha256=sha256_bytes(content),
        content_bytes=len(content),
        capability=CAPABILITY,
        operation=OPERATION_NAME,
        max_risk_level="low",
        max_side_effect="LOCAL_REVERSIBLE",
        requires_verification=True,
        valid_from=(now - timedelta(seconds=1)).isoformat(),
        valid_until=(now + timedelta(seconds=ttl_seconds)).isoformat(),
    )


class _Runtime:
    """Dedicated runtime view; default executor stays InMemory."""

    def __init__(self) -> None:
        self.executor = InMemoryActionExecutor()


async def _execute_once(root: Path, target_name: str, content: bytes) -> Dict[str, Any]:
    from intent_kernel.runtime.mission_runtime import MissionRuntime  # noqa: F401

    class _RT:
        def __init__(self) -> None:
            self.executor = InMemoryActionExecutor()

    async def run(runtime):
        contract = ActionContract(
            action_id="tp05-preview", capability=CAPABILITY,
            action_type=OPERATION_NAME, idempotency_key="tp05-preview",
        )
        contract.inputs_reference = {
            "path": target_name, "content": content.decode(),
        }
        return await runtime.executor.execute(contract)

    runtime = _RT()
    return await run_bound_dispatch(
        mission_runtime=runtime, authority=None,  # replaced below
        authorized_root=root, target_name=target_name, content=content,
        run=run,
    )


def run_preview(
    proposal: PreviewProposal,
    content: bytes = DEFAULT_CONTENT,
    *,
    operator_approved: bool,
    approval_rationale: str = "",
    now: Optional[datetime] = None,
    cleanup: bool = True,
    parent_root: Optional[Path] = None,
) -> PreviewReport:
    """Execute ONE governed preview effect, after an EXPLICIT operator act.

    ``operator_approved`` must be True. It is never inferred, never defaulted,
    and never set True merely because the harness built the proposal.
    """
    now = now or datetime.now(timezone.utc)
    root = Path(proposal.authorized_root)

    def _cleanup(flag: bool) -> bool:
        if flag and root.exists():
            shutil.rmtree(root, ignore_errors=True)
            return True
        return False

    if operator_approved is not True:
        # TP-05D fix: a DECLINED proposal must NOT destroy its disposable root.
        # The operator may reasonably reconsider, and destroying the prepared
        # root here made a subsequent approval fail with 'authorized-root-
        # missing'. The root is cleaned only once a run is terminal.
        return PreviewReport(
            approved=False, outcome="DENIED",
            reason="operator-did-not-approve",
            authorized_root=str(root), target_name=proposal.target_name,
            cleaned_root=False,
        )

    if sha256_bytes(content) != proposal.content_sha256:
        return PreviewReport(
            approved=True, outcome="DENIED", reason="content-changed-after-proposal",
            authorized_root=str(root), target_name=proposal.target_name,
            cleaned_root=_cleanup(cleanup),
        )

    # 3. EXPLICIT operator approval -> approved grant.
    try:
        granted = approve_intent_authority(
            propose_intent_authority(
                allow_capabilities=(proposal.capability,),
                allowed_operations=(proposal.operation,),
                target_scope=(proposal.authorized_root,),
                max_risk_level=proposal.max_risk_level,
                max_side_effect=proposal.max_side_effect,
                require_verification=proposal.requires_verification,
                valid_from=proposal.valid_from,
                valid_until=proposal.valid_until,
            ),
            authority_source_type="operator_local_explicit",
            authority_source_identity=(approval_rationale or "local-operator"),
            approved_at=now.isoformat(),
        )
        # 4. Establish canonical authority.
        authority = establish_intent_authority_from_grant(
            granted, now_iso=now.isoformat())
    except Exception as exc:
        return PreviewReport(
            approved=True, outcome="DENIED",
            reason=f"authority-establishment-failed:{exc}",
            authorized_root=str(root), target_name=proposal.target_name,
            cleaned_root=_cleanup(cleanup),
        )

    # 5. Trusted local approval - token minted here, used here, never exposed.
    approval = register_local_approval(authority.authority_digest, now=now)
    fingerprint = token_fingerprint(approval.token)

    observer_grant = CreateTestFileAuthority(
        authorized_root=root, authorized_target=root / proposal.target_name,
        expected_content_sha256=sha256_bytes(content),
        authority=authority,
    )

    async def _dispatch() -> Dict[str, Any]:
        class _RT:
            def __init__(self) -> None:
                self.executor = InMemoryActionExecutor()

        async def run(runtime):
            contract = ActionContract(
                action_id="tp05-preview", capability=CAPABILITY,
                action_type=OPERATION_NAME, idempotency_key="tp05-preview",
            )
            contract.inputs_reference = {
                "path": proposal.target_name, "content": content.decode(),
            }
            return await runtime.executor.execute(contract)

        return await run_bound_dispatch(
            mission_runtime=_RT(), authority=authority, authorized_root=root,
            target_name=proposal.target_name, content=content, run=run,
            now_provider=lambda: now, approval_token=approval.token,
        )

    try:
        envelope = asyncio.run(_dispatch())
    except PreviewSelectionDenied as exc:
        LOCAL_APPROVALS._tokens.clear()
        return PreviewReport(
            approved=True, outcome="DENIED", reason=exc.code,
            authorized_root=str(root), target_name=proposal.target_name,
            approval_fingerprint=fingerprint, cleaned_root=_cleanup(cleanup),
        )
    finally:
        # Token is single-use and internal; drop any residue regardless.
        LOCAL_APPROVALS._tokens.pop(approval.token, None)

    # 7. INDEPENDENT observation of the real host filesystem.
    observation = LocalFilesystemObserver(observer_grant).observe()
    receipt = envelope["outcome"] if isinstance(envelope, dict) else {}
    effect_calls = envelope.get("effect_calls", 0)

    ok = bool(observation.exists and observation.matches_authorized
              and effect_calls == 1)
    return PreviewReport(
        approved=True,
        outcome="VERIFIED" if ok else "DENIED",
        reason="independently-observed" if ok else (
            f"verification-failed:{observation.reason}"),
        authorized_root=str(root),
        target_name=proposal.target_name,
        observed_exists=observation.exists,
        observed_sha256=observation.observed_sha256,
        matches_authorized=observation.matches_authorized,
        approval_fingerprint=fingerprint,
        cleaned_root=_cleanup(cleanup),
        detail={"effect_calls": effect_calls,
                "effect_occurred": bool(receipt.get("effect_occurred"))},
    )


def preview(operator_approved: bool = False,
            parent_root: Optional[Path] = None,
            **kwargs: Any) -> PreviewReport:
    """Convenience wrapper: prepare -> propose -> (operator decides) -> run."""
    root = prepare_disposable_root(parent_root)
    proposal = propose_preview(root=root, **kwargs)
    return run_preview(proposal, operator_approved=operator_approved,
                       cleanup=True)
