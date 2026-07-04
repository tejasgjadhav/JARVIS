#!/usr/bin/env python3
"""J.A.R.V.I.S. desktop launcher.

Started by JARVIS.app (the Desktop icon). Boots the Flask backend, waits for
the port to come up, then opens a chromeless Chrome "app window" pointed at it.
Quitting JARVIS from the Dock kills this process, which tears down the server.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

# PORT may be overridden in .env
PORT = 3000
env_file = HERE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.startswith("PORT="):
            try:
                PORT = int(line.split("=", 1)[1].strip())
            except ValueError:
                pass

URL = f"http://localhost:{PORT}"


def port_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), 0.5):
            return True
    except OSError:
        return False


def log(msg: str) -> None:
    print(f"[launcher] {msg}", flush=True)


# 1. Start the backend unless something is already serving the port.
server = None
if port_up():
    log(f"port {PORT} already serving — reusing existing server")
else:
    log("starting Flask backend (server.py)…")
    server = subprocess.Popen([sys.executable, str(HERE / "server.py")], cwd=str(HERE))

# 2. Wait for it to accept connections (up to ~20s).
for _ in range(40):
    if port_up():
        break
    time.sleep(0.5)
else:
    log("ERROR: server did not come up on port %d — check /tmp/jarvis_launcher.log" % PORT)
    sys.exit(1)

log(f"backend ready at {URL}")

# 3. Open a chromeless Chrome app window (falls back to default browser).
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
profile = str(HERE / ".chrome-app-profile")
if os.path.exists(chrome):
    log("opening Chrome app window")
    subprocess.Popen([
        chrome,
        f"--app={URL}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ])
else:
    log("Chrome not found — opening default browser")
    subprocess.Popen(["open", URL])

# 4. Stay alive so quitting the app tears down the server we started.
try:
    if server is not None:
        server.wait()
    else:
        # We reused an existing server; idle until killed.
        while True:
            time.sleep(3600)
except KeyboardInterrupt:
    pass
finally:
    if server is not None:
        server.terminate()
        log("backend stopped")
