# Intent OS — Kernel v0.1.0

> **O sistema operacional cognitivo.**

## Product Alpha 2.1.4

The first-intent flow now preserves a single canonical Mission from interpretation through
execution and persistence. Legacy timestamps are normalized to UTC ISO 8601 with safe backups,
the UI never renders `Invalid Date`, and diagnostics identify the exact completed or failed stage
without exposing prompts or credentials.

## Product Alpha 2.1.3

The Windows host now paints a native startup surface immediately, initializes WebView2 and the
local bridge asynchronously, and offers retry, diagnostics, cache recovery, and safe mode.

## Product Alpha 2.1.2

The Windows product supports OpenAI and Google Gemini through the same canonical Intent → Mission →
Execution flow. Provider credentials are protected locally by Windows, the default Provider is chosen
by the user, and fallback requires explicit authorization.

## Product Alpha 1

The Windows Product Alpha provides Portuguese first-run configuration, a DPAPI-protected OpenAI
connection, functional conversation through the canonical Kernel, persistent local history, an
explicit demonstration mode, settings, and diagnostics. Build artifacts are produced by
`windows/build.ps1`; installation remains per-user and requires neither administrator access nor
an installed Python runtime.

Intent OS processa intenções do usuário e transforma em respostas estruturadas, com persistência de conhecimento e validação constitucional.

## Quick Start

```bash
# Install
cd intent-os
pip install -e ".[dev]"

# Run tests
pytest

# Interactive mode
python -m intent_kernel
```

## Architecture

```
Constitution (valida tudo)
     │
  Kernel (pure Python, zero deps)
     │
  ├── IntentEngine (parse + classify)
  ├── PipelineDAG (QUICK → ARCHITECT)
  ├── KnowledgeManager (Curator + PKB)
  ├── EventBus (pub/sub interno)
  ├── ModuleRouter (plugins)
  └── ProviderManager (LLM routing)
```

## Principles (Constitution v1.0.0)

1. **Soberania** — Usuário é dono dos seus dados
2. **Verdade** — Sistema nunca inventa
3. **Continuidade** — Conhecimento sobrevive entre sessões
4. **Evolução** — Sistema nunca está pronto

## Modes

| Mode | Depth | When |
|------|-------|------|
| ⚡ QUICK | Direct answer | Simple tasks |
| 📋 BASIC | Standard | Common tasks |
| 🔍 DETAIL | Structured | Complex tasks |
| 🧠 EXPERT | Analysis + risks | Decisions |
| 🏗️ ARCHITECT | Full planning | Systems |

## License

MIT
