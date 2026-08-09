"""Knowledge Heritage Guardian — Constitution v1.1.

Protects: User ownership of knowledge.
Ensures: KC is exportable, versionable, auditable, recoverable, no proprietary formats.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


class KnowledgeHeritageGuardian:
    """Protects Knowledge Heritage principle.

    Ensures:
    - All persisted data is exportable
    - No mandatory proprietary formats
    - Versioning exists
    - Traceability is maintained
    - Recovery is possible
    """

    def __init__(self):
        self._flagged_count = 0
        self._required_capabilities = {
            "export": True,
            "versioning": True,
            "audit_trail": True,
            "recovery": True,
            "no_proprietary_format": True,
        }

    @property
    def name(self) -> str:
        return "knowledge_heritage"

    @property
    def description(self) -> str:
        return "Knowledge Heritage — KC belongs to the user."

    @property
    def principle(self) -> str:
        return "O Knowledge Core pertence ao usuário. Todo conhecimento deve ser exportável, versionável, auditável e recuperável."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate event against Knowledge Heritage principle."""
        # Check if event has proper versioning
        if not self._has_versioning(event):
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason="Event lacks versioning. Knowledge Heritage requires version tracking.",
            )

        # Check if event has audit trail
        if not self._has_audit_trail(event):
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason="Event lacks audit trail. Knowledge Heritage requires traceability.",
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def validate_store(self, store_capabilities: dict[str, bool]) -> GuardianVerdict:
        """Validate that a KnowledgeStore meets Heritage requirements.

        Args:
            store_capabilities: Dict indicating which capabilities the store has.
                Expected keys: export, versioning, audit_trail, recovery, no_proprietary_format
        """
        missing = [
            cap for cap, required in self._required_capabilities.items()
            if required and not store_capabilities.get(cap, False)
        ]

        if missing:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason=f"Store missing Heritage capabilities: {', '.join(missing)}",
                details={"missing_capabilities": missing},
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="Store meets Heritage requirements.")

    def _has_versioning(self, event: dict[str, Any]) -> bool:
        """Check if event has version information."""
        return "version" in event or "lifecycle" in event

    def _has_audit_trail(self, event: dict[str, Any]) -> bool:
        """Check if event has audit trail."""
        lifecycle = event.get("lifecycle", {})
        if isinstance(lifecycle, dict):
            transitions = lifecycle.get("transitions", [])
            return len(transitions) > 0 or "currentLevel" in lifecycle
        return False

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "flagged": self._flagged_count,
            "required_capabilities": list(self._required_capabilities.keys()),
        }
