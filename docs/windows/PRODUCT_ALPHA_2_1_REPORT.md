# Product Alpha 2.1 — Multi-Provider Gemini

Version: `0.4.0-alpha`.

## Architecture

`GeminiProvider` implements the canonical Provider Port through `LLMProvider`. The existing
`KernelBuilder`, `ProviderManager`, Kernel, Mission Engine, Constitution, Capability Router and
Knowledge Pipeline remain the single canonical graph. The Windows host supplies protected Provider
credentials to the private stdio bridge; the UI never imports Provider implementations.

## Product behavior

- OpenAI and Google Gemini can be configured independently.
- Each key is protected with Windows DPAPI (`CurrentUser`) in a separate local secret file.
- The user chooses a validated default Provider.
- Fallback is disabled by default and requires explicit, persisted authorization.
- Intent, Mission, response and history remain Provider-independent; the response records its producer.
- Gemini errors are classified as invalid key, quota reached, unavailable or generic Provider error.
- Gemini free-tier disclosure is visible before connection.

Gemini uses `gemini-2.5-flash-lite` by default and the official HTTPS `generateContent` API with the
`x-goog-api-key` header. No Google password, fake login or OAuth simulation is present.

## Validation boundaries

Automated tests use an injected transport and never contain a real key. A real Gemini request and the
Windows installer lifecycle require the local checklist. Build evidence, test totals, artifact size and
SHA-256 are recorded when the release package is generated.

Validation before packaging:

- Product/multi-provider focused suite: **37 passed**.
- IDS and Shell JavaScript suite: **38 passed**.
- Full Python suite: **587 passed, 3 historical environment failures** (Windows default encoding,
  sandboxed installed-program discovery, and denied legacy home-directory persistence).
- Focused Python coverage: Gemini Provider **74%**, product bridge **62%**, combined **65%**.
- Windows host and installer compilation: successful; the known WebView2 `WindowsBase` resolution
  warning remains non-blocking.
- Packaged bridge smoke test: startup succeeded and reported Gemini through the canonical graph without
  a Python installation or network listener.
- Real Gemini response: **not claimed** until the user supplies a key directly to the installed app.

## Release artifacts

- Setup: `IntentOS-Product-Alpha-2.1-Setup.exe` — 252,665,465 bytes — SHA-256
  `BD1D3822C1EDD05AE26DE1BA03B8A1854F197664C01648B2896CD7B541F89234`.
- Portable: `IntentOS-Product-Alpha-2.1-Portable.zip` — 91,038,165 bytes — SHA-256
  `DEC025C95F86E13ADCEE1B677BD453A1C9D2C53B4D23B7D398EC9C468E31089A`.

Official references:

- https://ai.google.dev/gemini-api/docs/api-key
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/troubleshooting
