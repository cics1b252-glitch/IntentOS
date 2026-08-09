"""Secret Resolver Port & Safe Fake Adapter — RFC-0016 (STUDIO 10.3).

Defines SecretResolverPort interface and safe FakeSecretResolver adapter.
Ensures raw secrets are NEVER logged, serialized, or stored in traces/checkpoints.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from intent_kernel.tools.models import CredentialReference


class SecretResolverPort(ABC):
    """Abstract port for resolving secret references safely."""

    @abstractmethod
    async def resolve(self, reference_id: str) -> Optional[str]:
        """Resolve a secret reference ID to an ephemeral in-memory secret string."""
        pass

    @abstractmethod
    async def validate(self, reference_id: str) -> bool:
        """Validate if a credential reference is active and valid."""
        pass

    @abstractmethod
    async def revoke(self, reference_id: str) -> bool:
        """Revoke a credential reference."""
        pass


class FakeSecretResolver(SecretResolverPort):
    """Safe test adapter for credential resolution without real external storage."""

    def __init__(self) -> None:
        self._valid_references: set = {"cred_ref_test_valid", "cred_ref_default"}
        self._revoked_references: set = set()

    def register_valid_reference(self, reference_id: str) -> None:
        self._valid_references.add(reference_id)

    async def resolve(self, reference_id: str) -> Optional[str]:
        if reference_id in self._revoked_references or reference_id not in self._valid_references:
            return None
        # Return ephemeral dummy secret for test execution
        return f"ephemeral_test_token_{reference_id}"

    async def validate(self, reference_id: str) -> bool:
        if reference_id in self._revoked_references:
            return False
        return reference_id in self._valid_references

    async def revoke(self, reference_id: str) -> bool:
        if reference_id in self._valid_references:
            self._valid_references.remove(reference_id)
        self._revoked_references.add(reference_id)
        return True
