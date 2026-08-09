"""Symbiosis Guardian — Constitution v1.1.

Protects: Symbiotic Cognitive Layer principle.
Ensures: Kernel doesn't replace OS functions, no direct hardware access,
          no OS-specific dependencies, reuses host capabilities.
"""

from __future__ import annotations

import sys
from typing import Any

from intent_kernel.constitution.guardians import GuardianVerdict


# Forbidden imports that indicate OS-specific dependencies
OS_SPECIFIC_MODULES = {
    "winreg", "winsound", "win32api", "win32com",  # Windows
    "fcntl", "termios", "resource", "signal",       # Unix/Linux
    "android", "jnius", "pyjnius",                  # Android
    "objc", "Cocoa", "Foundation",                  # macOS
}

# Forbidden patterns in imports
FORBIDDEN_PATTERNS = [
    "subprocess",      # Direct OS command execution
    "ctypes",          # Direct hardware access
    "mmap",            # Direct memory access
    "serial",          # Serial port access
    "gpio",            # GPIO access
    "i2c",             # I2C bus access
    "spi",             # SPI bus access
]


class SymbiosisGuardian:
    """Protects the Symbiotic Cognitive Layer principle.

    Ensures the Kernel:
    - Doesn't replace OS functions
    - Doesn't access hardware directly
    - Has no OS-specific dependencies
    - Reuses host system capabilities
    """

    def __init__(self):
        self._blocked_count = 0
        self._flagged_count = 0

    @property
    def name(self) -> str:
        return "symbiosis"

    @property
    def description(self) -> str:
        return "Symbiotic Cognitive Layer — Kernel stays symbiotic with host OS."

    @property
    def principle(self) -> str:
        return "O Intent OS permanece uma Symbiotic Cognitive Layer."

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate that kernel code doesn't violate symbiosis.

        Checks:
        1. No OS-specific module imports in kernel code
        2. No direct hardware access patterns
        3. No subprocess calls from kernel core
        """
        # Check for OS-specific imports in kernel context
        if context and context.get("check_type") == "imports":
            return self._validate_imports(context.get("imports", []))

        # Check for direct hardware/system access
        if context and context.get("check_type") == "system_access":
            return self._validate_system_access(context.get("accesses", []))

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def _validate_imports(self, imports: list[str]) -> GuardianVerdict:
        """Check imports for OS-specific dependencies."""
        violations = []
        for imp in imports:
            module = imp.split(".")[0]
            if module in OS_SPECIFIC_MODULES:
                violations.append(f"OS-specific module: {module}")
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in imp.lower():
                    violations.append(f"Forbidden pattern: {pattern} in {imp}")

        if violations:
            self._blocked_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="blocked",
                reason=f"Symbiosis violation: {'; '.join(violations)}",
                details={"violations": violations},
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def _validate_system_access(self, accesses: list[str]) -> GuardianVerdict:
        """Check for direct hardware/system access."""
        violations = []
        for access in accesses:
            if any(p in access.lower() for p in FORBIDDEN_PATTERNS):
                violations.append(f"Direct system access: {access}")

        if violations:
            self._blocked_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="blocked",
                reason=f"Symbiosis violation: {'; '.join(violations)}",
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="OK")

    def check_kernel_independence(self, kernel_dir: str) -> GuardianVerdict:
        """Static analysis: scan kernel directory for forbidden imports."""
        import ast
        import pathlib

        violations = []
        kernel_path = pathlib.Path(kernel_dir)

        for py_file in kernel_path.rglob("*.py"):
            if "server" in py_file.parts:  # server is allowed to use external deps
                continue
            try:
                tree = ast.parse(py_file.read_text())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".")[0]
                        if module in OS_SPECIFIC_MODULES:
                            violations.append(f"{py_file.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module = node.module.split(".")[0]
                        if module in OS_SPECIFIC_MODULES:
                            violations.append(f"{py_file.name}: from {node.module}")

        if violations:
            self._blocked_count += 1
            return GuardianVerdict(
                guardian=self.name,
                decision="blocked",
                reason=f"Kernel has OS-specific dependencies: {'; '.join(violations[:3])}",
                details={"violations": violations},
            )

        return GuardianVerdict(guardian=self.name, decision="allowed", reason="No OS-specific dependencies found.")

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principle": self.principle,
            "blocked": self._blocked_count,
            "flagged": self._flagged_count,
        }
