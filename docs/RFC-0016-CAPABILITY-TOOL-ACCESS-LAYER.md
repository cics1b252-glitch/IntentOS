# RFC-0016 — Controlled Tool Discovery, Permissions & Action Routing

**Status:** STABLE  
**Author:** Intent OS Kernel Team  
**Date:** August 2026  
**Layer:** Studio 10.3 / Capability & Tool Access Layer  

---

## 1. Context & Motivation

The Intent OS Cognitive Pipeline translates high-level user intent into structured execution graphs (`ExecutionGraph`) and runs them securely via the Mission Runtime (`RFC-0015`). However, a critical architectural gap previously existed between **abstract capabilities** requested in planning (e.g. `external.email.send`) and **concrete execution tools** (e.g. Gmail, Outlook, SMTP, test adapters).

RFC-0016 establishes the **Capability & Tool Access Layer**, a controlled, auditable, and security-first intermediary layer that handles:
1. **Tool Discovery & Registration** without automatic authorization.
2. **Abstract Capability to Tool Mapping**.
3. **Explicit Multi-Scoped Permission Model** (ONCE, MISSION, SESSION, PROJECT, USER, ORGANIZATION).
4. **Tool Candidate Scoring & Ranking** based on health, verification, idempotency, cost, and environment compatibility.
5. **Pre-execution Authorization Gate** that strictly separates **Authorization** from **Confirmation**.
6. **Credential Reference Boundary** ensuring raw credentials and secrets NEVER enter tool models, checkpoints, memory, or traces.
7. **Zero-Side-Effect Dry Run & Simulation Contracts**.

---

## 2. Fundamental Axioms

```
CAPABILITY != TOOL
TOOL_DISCOVERED != TOOL_AUTHORIZED
TOOL_AUTHORIZED != ACTION_AUTHORIZED
ACTION_EXECUTED != ACTION_VERIFIED
CONNECTED_SERVICE != UNRESTRICTED_ACCESS
```

1. **Capability vs. Tool:** Planning requests abstract capabilities (`external.calendar.create`). Tools are concrete providers (`google_calendar_v3`, `test.calendar`).
2. **Discovered vs. Authorized:** Discovering or installing a tool NEVER grants automatic authorization to invoke it.
3. **Authorization vs. Confirmation:** Authorizing access to a calendar service is distinct from confirming a specific high-impact event creation.
4. **Credential Boundary:** Tools operate on opaque `CredentialReference` tokens. `SecretResolverPort` resolves ephemeral tokens in memory at the exact execution boundary.

---

## 3. Architecture & Topology

```
User Intent
    ↓
IUE ──► AME ──► CDM ──► CPE ──► COR ──► ECC ──► Mission Runtime
                                                     │
                                             (ActionContract)
                                                     ▼
                                              Action Gate
                                                     │
                                                     ▼
                                             Capability Router
                                                     │
                                                     ▼
                                          Tool Access Layer
                                                     │
                                                     ▼
                                          Tool Authorization Gate
                                                     │
                                                     ▼
                                            ActionExecutorPort
                                                     │
                                                     ▼
                                            [ SIMULATION TOOL ]
                                                     │
                                                     ▼
                                             Verification Gate
                                                     │
                                                     ▼
                                              Completion Gate
                                                     │
                                                     ▼
                                                    ECC
```

---

## 4. Key Components & Contracts

### 4.1 ToolResource & Lifecycle Statuses
Tools are declared as `ToolResource` instances in the `ToolRegistryPort`.
- **Statuses:** `DISCOVERED`, `AVAILABLE`, `DEGRADED`, `UNAVAILABLE`, `UNAUTHORIZED`, `DISABLED`, `REVOKED`, `UNSUPPORTED`.
- **Origins:** `BUILT_IN`, `USER_INSTALLED`, `SYSTEM_DISCOVERED`, `PLUGIN`, `CONNECTOR`, `LOCAL_APPLICATION`, `REMOTE_SERVICE`, `ENTERPRISE_MANAGED`.
- **Types:** `MEMORY`, `FILESYSTEM`, `EMAIL`, `CALENDAR`, `CONTACTS`, `BROWSER`, `SEARCH`, `DATABASE`, `API`, `CODE_EXECUTION`, etc.

### 4.2 Capability Router & Candidate Ranking
The `CapabilityRouter` receives an abstract capability requirement, queries the registry, applies project/mission persistent rules (e.g., `"Never use cloud tools for PROJECT_ALPHA"`), evaluates tool health and required permissions, and returns ranked `ToolCandidate` instances scored by:
- Health status (`HEALTHY` vs `DEGRADED`)
- Verification support (`supports_verification`)
- Idempotency support (`supports_idempotency`)
- Permission status (`GRANTED` vs `NOT_CONFIGURED` / `REVOKED`)

### 4.3 Permission Manager & Scopes
`PermissionManager` manages permission grants across explicit scopes (`ONCE`, `MISSION`, `SESSION`, `PROJECT`, `USER`, `INSTALLATION`, `ORGANIZATION`). Supports project-level isolation and revocations.

### 4.4 Tool Authorization Gate
`ToolAuthorizationGate` evaluates selected tool candidates prior to execution against:
- Tool status and health
- Required permission states (`GRANTED`, `NOT_CONFIGURED`, `DENIED`, `REVOKED`)
- Constitutional rules
- Mission constraints
Returns explicit verdicts: `ALLOW`, `DENY`, `REQUEST_PERMISSION`, `REQUEST_CONFIRMATION`, `WAIT_TOOL`, `RESELECT_TOOL`.

### 4.5 Credential Boundary & Secret Resolver Port
- `CredentialReference`: Contains metadata (`reference_id`, `credential_type`, `provider_family`, `scope`, `status`). ZERO raw secrets or tokens.
- `SecretResolverPort`: Abstract interface (`resolve()`, `validate()`, `revoke()`).
- `FakeSecretResolver`: Safe test adapter generating ephemeral tokens in memory during execution.

### 4.6 Dry Run & Simulation Adapters
All simulation tools (`EmailSimulationTool`, `CalendarSimulationTool`, `FilesystemSimulationTool`, `BrowserSimulationTool`) implement `dry_run()` returning `DryRunResult` with `executed=False`, detailing intended actions, affected resources, expected effects, and required permissions without executing real network calls or external side-effects.

---

## 5. Verification & Compliance

- **Unit Tests:** 223/223 tests passing.
- **Network Safety:** 0 external network requests performed.
- **Credential Safety:** 0 secrets logged, serialized, or leaked into traces/checkpoints.
- **Architectural Boundary:** RRM, ECC, AME, BCC, COR, and Mission Runtime boundaries strictly preserved.
