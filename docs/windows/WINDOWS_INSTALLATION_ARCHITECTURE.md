# Windows Installation Architecture

Program files live at `%LOCALAPPDATA%\Programs\IntentOS`:

```text
IntentOS/
  app/IntentOS.exe
  app/Uninstall-IntentOS.exe
  ui/                         # existing IDS and Cognitive Shell
  assets/
  runtime/
  version.json
```

User data lives separately at `%LOCALAPPDATA%\IntentOS\Data`:

```text
Data/
  preferences/host.json
  logs/intent-os-host.log
  cache/webview2/
  future-kc/
  backups/
  updates/
```

The installer writes only to the current user's profile and HKCU registry. No elevation is requested.
The uninstall entry is under `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall`. Uninstall
removes program files and explicitly offers to preserve or erase data.

The host maps packaged `ui` to `https://intent.local` through WebView2. It starts no listener or socket.

