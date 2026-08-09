# Account Connection Architecture

The Windows host owns account consent and credential protection. Product Alpha 1 supports only an
OpenAI API key. It is encrypted using Windows DPAPI with `CurrentUser` scope and is never stored in
JSON, logs, UI state, history, or the bridge executable.

Future account connectors must implement authorization through official OAuth/device-code flows,
return only connection metadata to the UI, support revoke/test operations, and never request an
email password. Gmail, Outlook, calendars, and contacts are **Em preparação**.

