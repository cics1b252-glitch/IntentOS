# Provider Setup

## Supported now

OpenAI through the repository's existing `OpenAIProvider`. The user provides an API key, the host
protects it with DPAPI, starts the private packaged bridge, and validates it using the Provider Port.
The bridge creates exactly one `ApplicationFactory`/canonical graph and calls `Kernel.process`.

## Product Alpha 2.1

Google Gemini is a functional second Provider using an official Gemini API key. OpenAI and Gemini
are protected independently with DPAPI, can be tested separately, and either validated Provider may be
selected as the default. Fallback is off unless the user explicitly authorizes it.

The Gemini free tier has project-specific rate limits. Google states that free-tier content may be used
to improve its products; this disclosure is shown before connection. No Google password is requested.
Demonstration mode remains local, explicit, and never claims to be connected.

