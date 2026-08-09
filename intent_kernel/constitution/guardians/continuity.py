"""Continuity Guardian — Constitution v1.1.

Protects: Technological continuity.
Ensures: Provider/infra changes don't affect Kernel/KC, knowledge survives changes.
"""

from __future__ import annotations

from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


class ContinuityGuardian:
    """Protects Continuity principle (Constitution v1.1).

    Ensures:
    - Provider changes don't affect Knowledge Core
    - Infrastructure changes don't affect Kernel
    - Continuity between versions
    - Knowledge Core migration is possible
    """

    def __init__(self):
        self._flagged_count = 0
        self._version_history: list[dict] = []

    @property
    def name(self) -> str:
        return "continuity"

    @property
    def description(self) -> str:
        return "Continuity — knowledge survives technological changes."

    @property
    def principle(self) -> str:
        return "O conhecimento deve sobreviver às mudanças tecnológicas."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate that a change doesn't break continuity."""
        change_type = context.get("change_type", "") if context else ""

        # Provider change → check KC compatibility
        if change_type == "provider_change":
            return self._validate_provider_change(context or {})

        # Infrastructure change → check Kernel compatibility
        if change_type == "infra_change":
            return self._validate_infra_change(context or {})

        # Version change → check migration path
        if change_type == "version_change":
            return self._validate_version_change(context or {})

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def _validate_provider_change(self, context: dict) -> GuardianVerdict:
        """Validate that provider change doesn't affect KC."""
        kc_affected = context.get("kc_affected", False)
        if kc_affected:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason="Provider change affects KC. Knowledge Heritage requires KC independence from providers.",
            )
        return GuardianVerdict(guardian=self.name, decision="allowed", reason="Provider change does not affect KC.")

    def _validate_infra_change(self, context: dict) -> GuardianVerdict:
        """Validate that infra change doesn't affect Kernel."""
        kernel_affected = context.get("kernel_affected", False)
        if kernel_affected:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason="Infrastructure change affects Kernel. Kernel must be infrastructure-independent.",
            )
        return GuardianVerdict(guardian=self.name, decision="allowed", reason="Infrastructure change does not affect Kernel.")

    def _validate_version_change(self, context: dict) -> GuardianVerdict:
        """Validate version change has migration path."""
        has_migration = context.get("has_migration_path", False)
        from_version = context.get("from_version", "")
        to_version = context.get("to_version", "")

        self._version_history.append({
            "from": from_version,
            "to": to_version,
            "has_migration": has_migration,
        })

        if not has_migration:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason=f"Version change {from_version} → {to_version} has no migration path.",
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="Version change has migration path.")

    def validate_export(self, export_format: str) -> GuardianVerdict:
        """Validate that an export format is not proprietary."""
        proprietary_formats = ["docx", "xlsx", "pptx", "rtf", "odf"]
        if export_format.lower() in proprietary_formats:
            self._flagged_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="flagged",
                reason=f"Export format '{export_format}' may be proprietary. Prefer open formats (JSON, CSV, Markdown).",
            )
        return GuardianVerdict(guardian=self.name, decision="allowed", reason="Export format is acceptable.")

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "flagged": self._flagged_count,
            "version_history": len(self._version_history),
        }
