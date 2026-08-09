# RFC-0013: Registry & Resource Manager (RRM) & Resource Hardening

**Status:** Approved & Hardened (STUDIO 8.1)  
**Date:** 2026-08-08  
**Layer:** Intent Kernel / Resource & Registry Layer  
**Target Component:** `intent_kernel/rrm/`  

---

## 1. Executive Summary & Context

The **Registry & Resource Manager (RRM)** serves as the canonical single-source-of-truth registry and lifecycle resource management framework for **Intent OS**. It establishes a centralized, thread-safe, interface-driven service responsible for registering, discovering, tracking, and governing six fundamental system resource entities:

1. **Providers**: AI foundation model profiles (e.g., Gemini Ultra, Claude 3.5, GPT-4, Llama 3 Edge).
2. **Accounts**: Service accounts, access credentials routing, quotas, rate limits, and priority tiers.
3. **Execution Environments**: Host runtimes (Local Process, Desktop, Cloud, Edge, Browser, Remote) with resource limits and privacy constraints.
4. **Capabilities**: System-wide operational skills (e.g., financial retrieval, scenario modeling, code architecture, UI synthesis).
5. **Agents**: Specialized AI workers with historical confidence metrics, specialization tags, and capability mappings.
6. **Projects**: Scoped workspace boundaries, user/domain associations, retention classes, and assigned resource budgets.

RRM replaces fragmented ad-hoc catalogs with strongly typed canonical contracts (`ResourceType`, `ResourceStatus`, `ResourceOrigin`, `AvailabilitySource`, `AgentInstallationState`, `ResourceQueryFilter`, `ResourceHealthReport`) and exposes pure interface ports (`RRMRegistryPort`, `ResourceQueryPort`, `ProjectRegistryPort`) without introducing side-effects or external runtime execution dependencies.

---

## 2. RRM Hardening & Provenance Rules (STUDIO 8.1)

To prevent the system from mistaking template definitions for real, actionable resources, RRM enforces strict resource provenance and eligibility invariants:

### 2.1 Standard Rule: TEMPLATE != AVAILABLE
- **Seed Templates are NOT Eligible Execution Candidates**: `populate_default_catalog()` registers catalog templates marked with `is_template=True`, `status=UNCONFIGURED`/`DRAFT`, and `resource_origin=ResourceOrigin.TEMPLATE`.
- **Explicit Eligibility Check (`is_eligible`)**: Every resource model encapsulates an `is_eligible` property determining whether it can be dispatched by COR or selected for execution.
- **No Plaintext Credentials**: Credentials are never stored or logged in plain text; `secret_reference` references external secure vaults/environment variables.

### 2.2 Provenance & Lifecycle Enums
1. **`ResourceOrigin`**: `TEMPLATE`, `HOST_DISCOVERY`, `CONFIGURATION`, `USER_REGISTRATION`, `DYNAMIC_INFERENCE`.
2. **`AvailabilitySource`**: `SYNTHETIC_TEMPLATE`, `STATIC_CONFIG`, `ENVIRONMENT_PROBE`, `HEALTH_CHECK`, `UNKNOWN`.
3. **`AgentInstallationState`**: `DEFINED`, `INSTALLED`, `ENABLED`, `DISABLED`, `UNINSTALLED`.

### 2.3 Eligibility Requirements Across Resources

| Resource Type | Eligibility Conditions (`is_eligible == True`) |
| :--- | :--- |
| **`PROVIDER`** | `not is_template` AND `status == ACTIVE` AND `is_configured` AND `has_active_account` |
| **`ACCOUNT`** | `not is_template` AND `status == ACTIVE` AND `bool(secret_reference)` AND `is_configured` |
| **`EXECUTION_ENVIRONMENT`**| `not is_template` AND `status == ACTIVE` AND `is_discovered` |
| **`CAPABILITY`** | `not is_template` AND `status == ACTIVE` AND `is_executable` |
| **`AGENT`** | `not is_template` AND `status == ACTIVE` AND `is_enabled` AND `installation_state in (INSTALLED, ENABLED, AVAILABLE)` |
| **`PROJECT`** | `not is_template` AND `status == ACTIVE` |

---

## 3. System Architecture & Component Topology

```
+-------------------------------------------------------------------------------+
|                      REGISTRY & RESOURCE MANAGER (RRM)                        |
|                                                                               |
|   +-------------------+  +-------------------+  +-------------------------+   |
|   | Provider Resource |  | Account Resource  |  | Execution Environment   |   |
|   +-------------------+  +-------------------+  +-------------------------+   |
|   | Capability Resource| |  Agent Resource   |  | Project Resource        |   |
|   +-------------------+  +-------------------+  +-------------------------+   |
+-------------------------------------------------------------------------------+
                                    │
                         RRM Canonical Ports
               (RRMRegistryPort, ResourceQueryPort)
                                    │
              +---------------------+---------------------+
              │                                           │
              ▼                                           ▼
   +---------------------+                     +---------------------+
   |  RRMToCORAdapter    |                     | Project Governance  |
   +---------------------+                     +---------------------+
              │                                           │
              ▼                                           ▼
   +---------------------+                     +---------------------+
   |  COR Orchestrator   |                     | System Core / Apps  |
   +---------------------+                     +---------------------+
```

### Key Architectural Invariants
- **No Direct Execution Side Effects**: RRM solely manages registration, query, quota tracking, and metadata state. No LLM calls, network sockets, or remote commands are executed within RRM.
- **Decoupled Interfaces**: All interactions with RRM occur via defined Python `Protocol` ports (`RRMRegistryPort`, `ResourceQueryPort`, `ProjectRegistryPort`).
- **Thread Safety**: Concurrent access to the canonical store is protected via readers-writer reentrant locks (`threading.RLock`).
- **Zero Modification to AME / Constitution**: RRM operates independently at the infrastructure/registry layer without altering AME memory models or Constitutional rule evaluation engines.
- **Git-Isolated Workflow**: AI Studio treats `.git` as strictly read-only. No Git commands (`git commit`, `git reset`, `git gc`, `git fsck`, etc.) are executed by AI Studio.

---

## 4. Public Interfaces (Ports)

### 4.1 `RRMRegistryPort`
```python
class RRMRegistryPort(Protocol):
    def register_provider(self, provider: ProviderResource) -> ProviderResource: ...
    def get_provider(self, provider_id: str) -> Optional[ProviderResource]: ...
    def list_providers(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProviderResource]: ...
    
    def register_account(self, account: AccountResource) -> AccountResource: ...
    def get_account(self, account_id: str) -> Optional[AccountResource]: ...
    def list_accounts(self, provider_id: Optional[str] = None, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[AccountResource]: ...

    def register_environment(self, environment: ExecutionEnvironmentResource) -> ExecutionEnvironmentResource: ...
    def get_environment(self, environment_id: str) -> Optional[ExecutionEnvironmentResource]: ...
    def list_environments(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ExecutionEnvironmentResource]: ...
    
    def register_capability(self, capability: CapabilityResource) -> CapabilityResource: ...
    def get_capability(self, capability_name_or_id: str) -> Optional[CapabilityResource]: ...
    def list_capabilities(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[CapabilityResource]: ...
    
    def register_agent(self, agent: AgentResource) -> AgentResource: ...
    def get_agent(self, agent_id: str) -> Optional[AgentResource]: ...
    def list_agents(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[AgentResource]: ...
    
    def register_project(self, project: ProjectResource) -> ProjectResource: ...
    def get_project(self, project_id: str) -> Optional[ProjectResource]: ...
    def list_projects(self, status: Optional[ResourceStatus] = None, only_eligible: bool = False) -> List[ProjectResource]: ...

    def query_resources(self, filter_criteria: ResourceQueryFilter, only_eligible: bool = False) -> List[Any]: ...
    def update_resource_status(self, resource_type: ResourceType, resource_id: str, status: ResourceStatus) -> bool: ...
    def check_health(self) -> ResourceHealthReport: ...
    def get_metrics(self) -> RRMRegistryMetrics: ...
```

---

## 5. Integration with Capability Orchestrator (COR)

RRM connects to COR (`intent_kernel/cor.py`) via `RRMToCORAdapter`. The adapter translates between RRM's canonical resource models and COR's expected `RegistryCatalog` interfaces:

```
[ CapabilityOrchestrator (COR) ]
              │
      Queries Registry (only_eligible=True)
              │
              ▼
   [ RRMToCORAdapter ]
              │
   Converts Eligible Dataclasses
              │
              ▼
  [ RegistryResourceManager (RRM) ]
```

This ensures that COR receives ONLY verified, eligible, and configured execution candidates, preventing "fictitious" template resources from entering execution plans.

---

## 6. Testing & Verification

The RRM module is verified by a test suite (`tests/test_rrm.py`) covering:
1. Hardening & Resource Provenance tests (Rules A-J).
2. Full CRUD and status transitions for all 6 resource entity types.
3. Thread-safe concurrent operations.
4. Multi-criteria filtering with `ResourceQueryFilter`.
5. Health status reporting and metric calculations.
6. Integration with COR via `RRMToCORAdapter`.


---
*End of RFC-0013: Registry & Resource Manager (RRM)*
