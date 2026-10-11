"""FRONT-TP-04C-R1: trusted approval provenance for the local preview.

    CALLER_ASSERTED_GRANT != APPROVED_AUTHORITY
    SCOPE_DIGEST          != APPROVAL_AUTHENTICITY
    AUTHENTICATED_CALLER  != AUTHORIZED_APPROVER

The defect this closes
----------------------
``IntentAuthorityGrant`` has no signature, MAC, secret or proof field. Its only
integrity test is ``scope_digest(ceiling) == approved_scope_digest`` - a
check a caller satisfies by computing both from their OWN ceiling. So a grant
that arrives inside a request proves only that it is self-consistent, not
that anyone approved it.

The smallest fix that is actually sound
--------------------------------------
Approval must originate OUTSIDE the caller-controlled request. This module is
an in-process, operator-populated registry:

* the operator calls :func:`register_local_approval` directly (a local,
  deliberate act) to mint a single-use, expiring, random token bound to the
  EXACT authority digest it approves;
* the token is consumed once, at native-executor selection time;
* a token that was never issued, was already used, was issued for a DIFFERENT
  authority, or has expired is refused.

Because the registry is never populated from a request, context flag, role
string, boolean or identity string, there is nothing for a caller to forge.
This is deliberately NOT a signature scheme, NOT a remote approval service and
NOT an identity provider - it is a local capability held in process memory.

The token is a bearer capability and must be handled as a secret: it is only
ever compared with :func:`hmac.compare_digest`, and a caller who already has
process-level code execution can bypass it (see TP-04D limitation L-1).
"""

from __future__ import annotations

import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

TOKEN_BYTES = 32
DEFAULT_TTL_SECONDS = 300.0


class TrustedApprovalError(RuntimeError):
    """Approval provenance missing, forged, replayed, mismatched or expired."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TrustedApproval:
    """Proof that a LOCAL OPERATOR approved one exact authority."""

    token: str
    authority_digest: str
    approved_at: str
    expires_at: str

    def to_dict(self) -> Dict[str, str]:
        """REDACTED (TP-05B). The raw token is NEVER serialized.

        This method previously returned the token verbatim. It had no callers,
        so redacting it broke no contract while removing a latent leak: any
        future caller that logged or JSON-serialized an approval object would
        have leaked a live bearer capability. ``token_fingerprint`` is enough
        to correlate an approval for audit without disclosing it.
        """
        return {
            "token_fingerprint": token_fingerprint(self.token),
            "authority_digest": self.authority_digest,
            "approved_at": self.approved_at,
            "expires_at": self.expires_at,
        }


class _Registry:
    """Single-use token store. Never populated from a request."""

    def __init__(self) -> None:
        self._tokens: Dict[str, TrustedApproval] = {}
        self._lock = threading.Lock()

    def issue(self, authority_digest: str, ttl_seconds: float,
              now: Optional[datetime] = None) -> TrustedApproval:
        if not isinstance(authority_digest, str) or not authority_digest.strip():
            raise TrustedApprovalError("approval-requires-authority-digest")
        now = now or datetime.now(timezone.utc)
        approval = TrustedApproval(
            token=secrets.token_urlsafe(TOKEN_BYTES),
            authority_digest=authority_digest,
            approved_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
        )
        with self._lock:
            self._tokens[approval.token] = approval
        return approval

    def consume(self, token: str, authority_digest: str,
                now: Optional[datetime] = None) -> TrustedApproval:
        """Verify then BURN. A token is good for exactly one dispatch."""
        if not isinstance(token, str) or not token:
            raise TrustedApprovalError("approval-token-missing")
        now = now or datetime.now(timezone.utc)
        with self._lock:
            approval = self._tokens.get(token)
            if approval is None:
                raise TrustedApprovalError("approval-token-unknown")
            # Constant-time digest comparison before any use.
            if not hmac.compare_digest(approval.authority_digest, authority_digest):
                raise TrustedApprovalError("approval-authority-mismatch")
            if now >= datetime.fromisoformat(approval.expires_at):
                self._tokens.pop(token, None)
                raise TrustedApprovalError("approval-expired")
            # Single use: burn regardless of outcome of the caller.
            self._tokens.pop(token, None)
            return approval

    def pending(self) -> int:
        with self._lock:
            return len(self._tokens)


#: Process-local registry. Populated ONLY by direct operator call.
LOCAL_APPROVALS = _Registry()


def token_fingerprint(token: str) -> str:
    """Non-reversible correlation id for audit. NOT the token."""
    if not isinstance(token, str) or not token:
        return ""
    return "tok_" + hmac.new(
        b"intentos-preview-fingerprint", token.encode("utf-8"), "sha256"
    ).hexdigest()[:16]


def register_local_approval(authority_digest: str,
                            ttl_seconds: float = DEFAULT_TTL_SECONDS,
                            now: Optional[datetime] = None) -> TrustedApproval:
    """Operator action: approve ONE exact authority digest, once.

    This is the ONLY way a native preview effect can become authorised. It is
    never reachable from a request, a context value, or a remote endpoint.
    """
    return LOCAL_APPROVALS.issue(authority_digest, ttl_seconds, now=now)


def require_trusted_approval(token: str, authority_digest: str,
                             now: Optional[datetime] = None) -> TrustedApproval:
    """Fail closed unless a valid, unconsumed, matching approval exists."""
    return LOCAL_APPROVALS.consume(token, authority_digest, now=now)
