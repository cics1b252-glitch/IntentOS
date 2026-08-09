# Manual Test — Windows Alpha

Record date, Windows edition/build, username path, result, and evidence for each item.

- [ ] Install without administrator privileges on a clean Windows user.
- [ ] Confirm Start menu shortcut and optional Desktop shortcut.
- [ ] Confirm **Intent OS Alpha** in Installed apps.
- [ ] First launch creates data directories and `preferences/host.json`.
- [ ] Window opens without browser chrome or external browser.
- [ ] Resize, minimize, maximize, close, and verify no process remains.
- [ ] Attempt a second instance and confirm it is rejected clearly.
- [ ] Change theme, ambient, density, reduced motion; reopen and confirm persistence.
- [ ] Restart Windows and reopen.
- [ ] Uninstall preserving data; reinstall and confirm preferences return.
- [ ] Uninstall deleting data; confirm program and data removal.
- [ ] Install over the same/older simulated version and confirm complete replacement.
- [ ] Test with a Windows username/path containing spaces.
- [ ] Launch on a machine without Python.
- [ ] Confirm no listening/public TCP port is opened.
- [ ] Remove `ui/shell/index.html` temporarily and confirm a clear startup error.
- [ ] Verify logs contain lifecycle/errors but no typed content or secrets.
- [ ] Document unsigned-alpha SmartScreen behavior.

Clean-machine installation, restart, Installed apps confirmation, and SmartScreen behavior require
local human execution. They are not claimed by automated tests.

