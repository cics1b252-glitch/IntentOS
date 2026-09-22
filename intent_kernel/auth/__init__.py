"""M33.2C auth package — caller identity + hardened API-key ingress."""

from intent_kernel.auth.api_key_auth import (
    ApiKeyAuthenticator,
    AuthError,
    AuthRejectedError,
    AuthRequiredError,
    AuthUnavailableError,
    credential_reference_for,
    sanitize_context,
)
from intent_kernel.auth.caller_identity import AuthenticatedCaller

__all__ = [
    "ApiKeyAuthenticator",
    "AuthError",
    "AuthRejectedError",
    "AuthRequiredError",
    "AuthUnavailableError",
    "AuthenticatedCaller",
    "credential_reference_for",
    "sanitize_context",
]
