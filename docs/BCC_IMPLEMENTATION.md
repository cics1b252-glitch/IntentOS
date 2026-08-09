# Bootstrap Cognitive Cortex (BCC) Implementation — RFC-0014 / RFC-0014.1

## Overview

The Bootstrap Cognitive Cortex (BCC) is the local, self-aware cognitive bootstrap layer of Intent OS. It operates deterministically without relying on external LLM providers, while maintaining complete capability self-awareness, project context continuity, and explicit registration in RRM.

## Architecture & Subordination

BCC is subordinate to the Executive Cognitive Controller (ECC). It does not take over executive control or simulate external LLMs.

- **Local Cognitive Modes**: `LOCAL_CAPABLE`, `LOCAL_PARTIAL`, `EXTERNAL_PROVIDER_RECOMMENDED`, `EXTERNAL_PROVIDER_REQUIRED`, `OFFLINE_ONLY`, `RESOURCE_UNAVAILABLE`.
- **RRM Registration**: Registered as `agent_bcc_local_cortex` with `ResourceOrigin.CONFIGURATION` and `ResourceStatus.ACTIVE`.
- **Knowledge Boundaries**: Returns `UNKNOWN` or `INSUFFICIENT_KNOWLEDGE` when queried for missing facts, preventing hallucination.
