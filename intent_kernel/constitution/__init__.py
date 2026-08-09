"""Constitution module — Living Constitution for the Intent OS Kernel."""

from intent_kernel.constitution.models import Constitution, Constraint, Pillar
from intent_kernel.constitution.defaults import create_default_constitution
from intent_kernel.constitution.checker import (
    ConstitutionChecker,
    ConstitutionCheckResult,
    ConstitutionVerdict as LegacyCheckerVerdict,
)
from intent_kernel.constitution.canonical import (
    AuditGuardian,
    CanonicalConstitutionEngine,
    ConstitutionAuditRecord,
    ConstitutionPipeline,
    ContinuityGuardian as CanonicalContinuityGuardian,
    GovernanceRequest,
    Guardian,
    GuardianResult,
    IntegrityGuardian,
    MemoryGuardian,
    PolicyGuardian,
    SecurityGuardian,
)
from intent_kernel.contracts import ConstitutionVerdict

__all__ = [
    "Constitution",
    "Constraint",
    "Pillar",
    "create_default_constitution",
    "ConstitutionChecker",
    "ConstitutionCheckResult",
    "ConstitutionVerdict",
    "LegacyCheckerVerdict",
    "CanonicalConstitutionEngine",
    "ConstitutionPipeline",
    "ConstitutionAuditRecord",
    "GovernanceRequest",
    "Guardian",
    "GuardianResult",
    "SecurityGuardian",
    "PolicyGuardian",
    "CanonicalContinuityGuardian",
    "MemoryGuardian",
    "IntegrityGuardian",
    "AuditGuardian",
]
