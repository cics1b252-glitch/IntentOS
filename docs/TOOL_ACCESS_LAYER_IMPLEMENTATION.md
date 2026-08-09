# Tool Access Layer Implementation Guide (RFC-0016 / STUDIO 10.3)

**Component:** `intent_kernel.tools`  
**Status:** IMPLEMENTED & STABILIZED  

---

## Overview

The Capability & Tool Access Layer provides controlled tool discovery, permission management, capability routing, credential reference isolation, and safe simulation tools for Intent OS.

---

## Directory Structure

```
intent_kernel/tools/
├── __init__.py           # Package exports
├── models.py             # ToolResource, ToolCandidate, PermissionDecision, CredentialReference, DryRun
├── registry.py           # ToolRegistryPort & InMemoryToolRegistry
├── permissions.py        # PermissionManager (scoped grants, project isolation, revocations)
├── router.py             # CapabilityRouter (capability mapping, scoring, ranking)
├── authorization.py      # ToolAuthorizationGate (pre-execution verification)
├── secret_resolver.py    # SecretResolverPort & FakeSecretResolver
├── health.py             # ToolHealthPort & InMemoryToolHealthAdapter
└── adapters.py           # Email, Calendar, Filesystem, Browser Simulation Tools
```

---

## Usage Examples

### 1. Registering a Tool in the Registry

```python
from intent_kernel.tools import InMemoryToolRegistry, ToolResource, ToolStatus, ToolType

registry = InMemoryToolRegistry()
tool = ToolResource(
    tool_id="tool_cal_google",
    name="Google Calendar Connector",
    capabilities=["external.calendar.create", "external.calendar.read"],
    status=ToolStatus.AVAILABLE,
    tool_type=ToolType.CALENDAR,
    required_permissions=["calendar.create"],
    supports_dry_run=True,
    supports_verification=True,
    supports_idempotency=True,
)
await registry.register_tool(tool)
```

### 2. Granting Permissions and Routing Capabilities

```python
from intent_kernel.tools import CapabilityRouter, PermissionManager

perm_mgr = PermissionManager()
perm_mgr.grant_permission("tool_cal_google", "calendar.create", project_id="PROJ_1")

router = CapabilityRouter(registry=registry, permission_manager=perm_mgr)
candidates = await router.route_capability("external.calendar.create", project_id="PROJ_1")

top_candidate = candidates[0]
print(top_candidate.tool_id, top_candidate.selection_score)
```

### 3. Evaluating Authorization Gate

```python
from intent_kernel.tools import ToolAuthorizationGate

gate = ToolAuthorizationGate()
verdict = await gate.evaluate_tool(top_candidate, tool, project_id="PROJ_1")
print(verdict)  # ToolAuthorizationDecisionState.ALLOW
```

### 4. Performing a Safe Dry Run

```python
from intent_kernel.tools import CalendarSimulationTool, DryRunRequest

cal_sim = CalendarSimulationTool()
dry_req = DryRunRequest(
    tool_id="tool_sim_calendar",
    capability="external.calendar.create",
    inputs={"title": "Sprint Planning", "start": "2026-08-10T10:00:00Z"},
)
dry_res = await cal_sim.dry_run(dry_req)
assert not dry_res.executed
print(dry_res.intended_action)
```

---

## Mandatory Security Invariants

1. **No Raw Secrets:** `CredentialReference` contains only opaque references (`reference_id`). Secrets are resolved in ephemeral memory via `SecretResolverPort` at execution time.
2. **Project Isolation:** Grants for `PROJ_A` do not leak to `PROJ_B` unless granted at `GLOBAL` project scope.
3. **No External Network Calls:** Simulation adapters operate completely in memory with zero network dependencies.
