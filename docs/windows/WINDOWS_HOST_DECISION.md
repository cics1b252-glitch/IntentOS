# Windows Host Decision — Studio 2.5

## Decision

The alpha host uses **.NET 8 WinForms with Microsoft Edge WebView2**. It loads the existing
Cognitive Shell from packaged local files through a virtual HTTPS origin. It does not start a
web server, open a public port, or launch the user's external browser.

## Options evaluated

| Option | Result | Reason |
|---|---|---|
| Existing Python desktop wrapper | Rejected | Opens an external browser and starts localhost; packaging carries the Kernel unnecessarily. |
| .NET WinForms + WebView2 | Selected | Native resizable window, local content, no Python, modest footprint, standard Windows runtime. |
| Electron | Rejected | Introduces Node/Chromium and a much larger duplicate runtime. |
| Tauri | Rejected | Adds Rust and a new toolchain without demonstrated need. |
| Legacy WinForms WebBrowser | Rejected | Obsolete engine and inadequate ES module support. |

## Dependencies and size

- Self-contained .NET 8 application; no machine-wide .NET installation is required.
- Microsoft Edge WebView2 Runtime, standard on supported Windows 10/11; a clear error is shown if absent.
- Current x64 host is approximately 188 MB before compression; the portable ZIP is approximately
  72 MB. The setup is larger because it contains both its own self-contained runtime and the payload.
- No Python, Node, Rust, local HTTP server, API key, or remote script.

## Risks and future updates

The alpha executable uses `windows/assets/intent-provisional.ico`, a deliberately provisional identity,
and is not commercially code-signed, so SmartScreen may warn. WebView2 availability
must be checked in clean-machine validation. `version.json`, an `updates` directory, stable program/data
separation, and preserve-by-default data policy prepare future in-place updates; auto-update is not implemented.
