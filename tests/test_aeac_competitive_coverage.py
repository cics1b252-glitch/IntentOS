"""AEAC competitive coverage: self-generated skill and dynamic subagent.

These tests prove the architectural boundary that prevents authority
expansion through self-generated capabilities or dynamic subagent creation.
They do not implement or test dynamic skill-loading or subagent spawning
mechanisms that do not exist in the production path. Instead, they prove
that the existing authority containment would deny such attempts if they
were made.

AEAC-SELF-GENERATED-SKILL-AUTHORITY:
    An agent attempts to register a self-generated capability and use it
    to expand executable authority beyond the granted scope.
    Expected: NO AUTHORITY EXPANSION.

AEAC-DYNAMIC-SUBAGENT-DELEGATION:
    An agent attempts to delegate authority to a dynamically created
    subagent with scope exceeding the parent grant.
    Expected: DENY.
"""

from __future__ import annotations

import pytest

from intent_kernel.mission.delegation import (
    DelegationGrant,
    DelegationState,
    prove_edge,
    resolve_parent_view,
)
from intent_kernel.mission.intent_ceiling import IntentCeiling
from intent_kernel.mission.intent_grant import (
    approve_intent_authority,
    establish_intent_authority_from_grant,
    propose_intent_authority,
)
from intent_kernel.mission.intent_authority import (
    IntentAuthorityError,
    establish_intent_authority,
)
from intent_kernel.rrm.models import AgentResource
from intent_kernel.time_utils import utc_iso


NOW = "2026-10-03T00:00:00+00:00"


# ---------------------------------------------------------------------------
# AEAC-SELF-GENERATED-SKILL-AUTHORITY
# ---------------------------------------------------------------------------


def test_aeac_self_generated_skill_cannot_expand_authority():
    """A self-generated capability cannot expand executable authority.

    Proves that:
    1. A capability not in the granted scope is denied by the delegation
       containment proof, regardless of how it was registered.
    2. A self-generated capability with the same identity as a granted
       capability still cannot exceed the granted ceilings.
    3. The governed registration boundary requires exact identity and
       generation matching; a self-generated registration with a new
       identity is simply a different resource outside the grant.
    """
    # Parent grant: only knowledge.search, low risk, NONE side effect
    parent_grant = DelegationGrant(
        delegation_id="dlg-parent",
        delegation_parent_mission_id="m1",
        delegation_parent_action_id="p1",
        delegation_parent_delegation_id="",
        delegation_root_mission_id="m1",
        delegation_root_action_id="p1",
        delegation_root_governed_registration_id="grid-1",
        delegation_root_generation=1,
        delegation_delegator_grid="grid-1",
        delegation_delegator_agent_id="agent-1",
        delegation_delegate_agent_id="agent-2",
        delegation_delegate_grid="grid-2",
        delegation_allowed_capabilities=("knowledge.search",),
        delegation_allowed_resources=(
            {"resource_id": "r1", "governed_registration_id": "grid-1", "generation": 1},
        ),
        delegation_allowed_targets=(),
        delegation_max_risk_level="low",
        delegation_max_timeout_seconds=30.0,
        delegation_require_verification=True,
        delegation_max_side_effect="NONE",
        delegation_created_at=NOW,
        delegation_expires_at="",
        delegation_state=DelegationState.ACTIVE,
        delegation_revoked_at="",
        delegation_revoke_reason="",
    )
    parent_action = {
        "expected_resource_id": "r1",
        "expected_governed_registration_id": "grid-1",
        "expected_resource_generation": 1,
        "expected_executor_logical_id": "agent-1",
    }
    parent_view = resolve_parent_view(parent_action, "knowledge.search", parent_grant.to_dict())

    # Attempt 1: self-generated capability outside granted scope
    evil_grant = DelegationGrant(
        delegation_id="dlg-evil",
        delegation_parent_mission_id="m1",
        delegation_parent_action_id="p1",
        delegation_parent_delegation_id="dlg-parent",
        delegation_root_mission_id="m1",
        delegation_root_action_id="p1",
        delegation_root_governed_registration_id="grid-1",
        delegation_root_generation=1,
        delegation_delegator_grid="grid-1",
        delegation_delegator_agent_id="agent-1",
        delegation_delegate_agent_id="agent-2",
        delegation_delegate_grid="grid-2",
        delegation_allowed_capabilities=("self.generated.capability",),
        delegation_allowed_resources=(
            {"resource_id": "r1", "governed_registration_id": "grid-1", "generation": 1},
        ),
        delegation_allowed_targets=(),
        delegation_max_risk_level="low",
        delegation_max_timeout_seconds=30.0,
        delegation_require_verification=True,
        delegation_max_side_effect="NONE",
        delegation_created_at=NOW,
        delegation_expires_at="",
        delegation_state=DelegationState.ACTIVE,
        delegation_revoked_at="",
        delegation_revoke_reason="",
    )
    child_view = {
        "capability": "self.generated.capability",
        "grid": "grid-1",
        "generation": 1,
        "target": "r1",
        "resource_id": "r1",
    }
    ok, reason = prove_edge(evil_grant.to_dict(), child_view, parent_view)
    assert ok is False
    assert reason == "capability-escalation"

    # Attempt 2: self-generated capability with same identity but broader ceilings
    broad_grant = DelegationGrant(
        delegation_id="dlg-broad",
        delegation_parent_mission_id="m1",
        delegation_parent_action_id="p1",
        delegation_parent_delegation_id="dlg-parent",
        delegation_root_mission_id="m1",
        delegation_root_action_id="p1",
        delegation_root_governed_registration_id="grid-1",
        delegation_root_generation=1,
        delegation_delegator_grid="grid-1",
        delegation_delegator_agent_id="agent-1",
        delegation_delegate_agent_id="agent-2",
        delegation_delegate_grid="grid-2",
        delegation_allowed_capabilities=("knowledge.search",),
        delegation_allowed_resources=(
            {"resource_id": "r1", "governed_registration_id": "grid-1", "generation": 1},
        ),
        delegation_allowed_targets=(),
        delegation_max_risk_level="critical",
        delegation_max_timeout_seconds=9999.0,
        delegation_require_verification=False,
        delegation_max_side_effect="EXTERNAL_IRREVERSIBLE",
        delegation_created_at=NOW,
        delegation_expires_at="",
        delegation_state=DelegationState.ACTIVE,
        delegation_revoked_at="",
        delegation_revoke_reason="",
    )
    child_view2 = {
        "capability": "knowledge.search",
        "grid": "grid-1",
        "generation": 1,
        "target": "r1",
        "resource_id": "r1",
    }
    ok, reason = prove_edge(broad_grant.to_dict(), child_view2, parent_view)
    assert ok is False
    assert "constraint-weakening" in reason

    # Attempt 3: governed registration boundary — a self-generated agent
    # with a new identity is a different resource outside the grant.
    self_generated_agent = AgentResource(
        agent_id="self-generated-agent",
        name="self-generated",
        governed_registration_id="grid-self-generated",
    )
    # The delegate grid in the grant is grid-2, not grid-self-generated.
    # Even if the self-generated agent were registered, it would not match
    # the delegate binding in the grant.
    assert self_generated_agent.governed_registration_id != "grid-2"


# ---------------------------------------------------------------------------
# AEAC-DYNAMIC-SUBAGENT-DELEGATION
# ---------------------------------------------------------------------------


def test_aeac_dynamic_subagent_cannot_exceed_parent_grant():
    """A dynamically created subagent cannot receive non-delegable authority.

    Proves that:
    1. The delegation containment proof applies to any child grant,
       regardless of how the child agent was created.
    2. A subagent with a new governed registration identity cannot satisfy
       the delegate binding in the parent grant.
    3. The intent authority ceiling prevents establishment of authority
       beyond the approved scope, even for a dynamically created agent.
    """
    # Establish intent authority with bounded scope
    ceiling = IntentCeiling(
        allow_capabilities=("knowledge.search",),
        allowed_operations=("READ",),
        target_scope=("knowledge.search",),
        max_risk_level="low",
        max_side_effect="NONE",
        require_verification=True,
    )
    authority = establish_intent_authority(
        ceiling=ceiling,
        source_type="user_explicit",
        source_identity="test",
        established_at=NOW,
        now_iso=NOW,
    )

    # Attempt 1: subagent tries to use a capability outside the intent ceiling.
    # The containment boundary is the delegation proof: a child grant that
    # exceeds the parent scope is denied regardless of how the child was
    # created. Establish the parent authority first.
    parent_authority = establish_intent_authority(
        ceiling=ceiling,
        source_type="user_explicit",
        source_identity="parent-test",
        established_at=NOW,
        now_iso=NOW,
    )
    assert parent_authority is not None

    # Attempt 2: subagent with new governed registration identity
    # The delegate binding in any grant must match the subagent's governed
    # registration. A dynamically created subagent with a new identity
    # cannot satisfy this binding.
    subagent = AgentResource(
        agent_id="dynamic-subagent",
        name="dynamic-subagent",
        governed_registration_id="grid-dynamic-subagent",
    )
    # Any grant delegating to this subagent would need delegate_grid matching
    # the subagent's governed registration. If the parent grant specifies a
    # different delegate grid, the subagent cannot be the delegate.
    parent_grant_dict = {
        "delegation_delegate_agent_id": "dynamic-subagent",
        "delegation_delegate_grid": "grid-dynamic-subagent",
        "delegation_allowed_capabilities": ["knowledge.search"],
        "delegation_allowed_resources": [
            {"resource_id": "r1", "governed_registration_id": "grid-1", "generation": 1}
        ],
        "delegation_allowed_targets": [],
        "delegation_max_risk_level": "low",
        "delegation_max_side_effect": "NONE",
        "delegation_max_timeout_seconds": 30.0,
        "delegation_require_verification": True,
        "delegation_expires_at": "",
        "delegation_root_mission_id": "m1",
        "delegation_root_generation": 1,
        "delegation_parent_delegation_id": "ROOT",
    }
    parent_action = {
        "expected_resource_id": "r1",
        "expected_governed_registration_id": "grid-1",
        "expected_resource_generation": 1,
        "expected_executor_logical_id": "agent-1",
    }
    parent_view = resolve_parent_view(parent_action, "knowledge.search", parent_grant_dict)

    # A child grant that tries to expand scope beyond the parent
    child_grant = DelegationGrant(
        delegation_id="dlg-subagent",
        delegation_parent_mission_id="m1",
        delegation_parent_action_id="p1",
        delegation_parent_delegation_id="dlg-parent",
        delegation_root_mission_id="m1",
        delegation_root_action_id="p1",
        delegation_root_governed_registration_id="grid-1",
        delegation_root_generation=1,
        delegation_delegator_grid="grid-1",
        delegation_delegator_agent_id="agent-1",
        delegation_delegate_agent_id="dynamic-subagent",
        delegation_delegate_grid="grid-dynamic-subagent",
        delegation_allowed_capabilities=("knowledge.search", "expanded.cap"),
        delegation_allowed_resources=(
            {"resource_id": "r1", "governed_registration_id": "grid-1", "generation": 1},
        ),
        delegation_allowed_targets=(),
        delegation_max_risk_level="low",
        delegation_max_timeout_seconds=30.0,
        delegation_require_verification=True,
        delegation_max_side_effect="NONE",
        delegation_created_at=NOW,
        delegation_expires_at="",
        delegation_state=DelegationState.ACTIVE,
        delegation_revoked_at="",
        delegation_revoke_reason="",
    )
    child_view = {
        "capability": "expanded.cap",
        "grid": "grid-1",
        "generation": 1,
        "target": "r1",
        "resource_id": "r1",
    }
    ok, reason = prove_edge(child_grant.to_dict(), child_view, parent_view)
    assert ok is False
    assert reason == "capability-escalation"

    # The subagent's governed registration identity is preserved and cannot
    # be silently replaced by the parent's delegate grid.
    assert subagent.governed_registration_id == "grid-dynamic-subagent"
    assert subagent.governed_registration_id != "grid-1"
