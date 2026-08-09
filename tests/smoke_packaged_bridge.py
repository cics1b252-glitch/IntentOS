"""Post-build smoke test for the PyInstaller JSON-lines executable."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="Intent OS Unicode ") as data_root:
        environment = dict(os.environ)
        environment.update({"INTENTOS_DATA_ROOT": data_root, "PYTHONIOENCODING": "cp1252"})
        process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="strict", env=environment,
        )
        try:
            startup = json.loads(process.stdout.readline())
            assert startup["event"] == "READY"
            assert startup["ready"] is True
            assert startup["protocol_version"] == "1.0"
            process.stdin.write(json.dumps({"requestId": "health-smoke", "action": "health"}) + "\n")
            process.stdin.flush()
            health = json.loads(process.stdout.readline())
            assert health["ready"] is True and health["kernel_status"] == "ready"
            request = {"requestId": "unicode-smoke", "action": "chat",
                       "message": "Analise R$ 5.000 em FIIs 📊 — São Paulo — 日本語 — العربية",
                       "session_id": "unicode-packaged"}
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            assert response["requestId"] == "unicode-smoke"
            assert process.poll() is None, process.stderr.read()
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
