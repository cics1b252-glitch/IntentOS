"""M33.2C — Hardened shared API-key ingress authenticator.

Strict ``Authorization: Bearer <token>`` parsing, constant-time
comparison, safe non-reversible credential reference, and explicit
fail-closed anonymous policy.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Optional

from intent_kernel.auth.caller_identity import AuthenticatedCaller
from intent_kernel.time_utils import utc_iso


# Keys injected via req.context that would let a caller forge the
# trusted provenance channel. Stripped before the kernel ever sees them.
RESERVED_CONTEXT_KEYS = frozenset({
    "_authenticated_caller",
    "caller",
    "authorization",
    "bearer",
    "token",
    "api_key",
    "apikey",
    "credential",
    "secret",
})


def credential_reference_for(raw_key: str) -> str:
    """Stable non-secret fingerprint for audit/provenance."""
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"api_key:{digest[:16]}"


def sanitize_context(context: dict) -> dict:
    """Return a copy of context with reserved security keys removed."""
    if not isinstance(context, dict):
        return {}
    lower_reserved = {k.lower() for k in RESERVED_CONTEXT_KEYS}
    return {
        k: v for k, v in context.items()
        if k.lower() not in lower_reserved
    }


class ApiKeyAuthenticator:
    """Hardened API-key authenticator for the ingress boundary."""

    def __init__(
        self,
        expected_key: Optional[str],
        *,
        allow_anonymous: bool = False,
    ) -> None:
        self._expected_key = expected_key if expected_key else None
        self._allow_anonymous = bool(allow_anonymous)
        self._reference = (
            credential_reference_for(expected_key)
            if expected_key else ""
        )

    @classmethod
    def from_env(cls) -> "ApiKeyAuthenticator":
        """Build from process environment (single source of truth)."""
        raw = os.environ.get("INTENT_OS_API_KEY")
        expected: Optional[str] = raw if raw and raw.strip() else None
        allow_anonymous = (
            os.environ.get("INTENT_OS_ALLOW_ANONYMOUS", "").strip().lower()
            in ("1", "true", "yes")
        )
        return cls(expected, allow_anonymous=allow_anonymous)

    def authenticate(
        self, authorization: Optional[str]
    ) -> AuthenticatedCaller:
        """Authenticate one request's Authorization header.

        Returns an AuthenticatedCaller on success (including anonymous
        when explicitly allowed). Raises on every failure — callers
        must translate to 401/503. Never logs the raw key.
        """
        now = utc_iso()
        # No key configured.
        if self._expected_key is None:
            if self._allow_anonymous:
                return AuthenticatedCaller(
                    caller_id="anonymous",
                    credential_class="anonymous",
                    validation_result="anonymous",
                    credential_reference="anonymous",
                    authenticated_at=now,
                )
            # Production fail-closed: no key means auth unavailable.
            raise AuthUnavailableError(
                "Authentication is not configured: set INTENT_OS_API_KEY "
                "or explicitly enable anonymous access with "
                "INTENT_OS_ALLOW_ANONYMOUS=true for development."
            )

        # Key configured: Authorization required, strict Bearer scheme.
        if not authorization or not authorization.strip():
            raise AuthRequiredError("Authorization header required")

        # Strict parse: exactly "Bearer <token>" with single space, case-sensitive scheme.
        # Reject malformed schemes/prefixes (e.g. "bearer", "Token", "BEARER").
        if not authorization.startswith("Bearer "):
            raise AuthRejectedError(
                "Authorization must be exactly 'Bearer <token>'"
            )
        token = authorization[7:]
        # Reject empty token, embedded whitespace, or extra Bearer prefix tricks.
        if not token or not token.strip() or token != token.strip():
            raise AuthRejectedError("Malformed Bearer token")
        if " " in token or "\t" in token or "\n" in token:
            raise AuthRejectedError("Malformed Bearer token")
        if token.startswith("Bearer "):
            raise AuthRejectedError("Malformed Bearer token")

        # Constant-time comparison.
        if not hmac.compare_digest(token, self._expected_key):
            raise AuthRejectedError("Invalid API key")

        return AuthenticatedCaller(
            caller_id=self._reference,
            credential_class="api_key",
            validation_result="valid",
            credential_reference=self._reference,
            authenticated_at=now,
        )

    @property
    def is_configured(self) -> bool:
        return self._expected_key is not None

    @property
    def allows_anonymous(self) -> bool:
        return self._allow_anonymous


class AuthError(Exception):
    """Base for authenticator errors (never carries raw key)."""


class AuthRequiredError(AuthError):
    """Missing Authorization on a protected route (→ 401)."""


class AuthRejectedError(AuthError):
    """Malformed or wrong credential (→ 401/403)."""


class AuthUnavailableError(AuthError):
    """Auth misconfigured / not available (→ 503 fail-closed)."""
