"""Canonical Core Apps and Capability Router."""

from intent_kernel.core_apps.apps import (
    AtlasCoreApp,
    LogosCoreApp,
    OEMStudioCoreApp,
)
from intent_kernel.core_apps.router import (
    CapabilityRegistrationError,
    CapabilityRouter,
)

__all__ = [
    "AtlasCoreApp",
    "LogosCoreApp",
    "OEMStudioCoreApp",
    "CapabilityRegistrationError",
    "CapabilityRouter",
]
