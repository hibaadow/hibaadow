#!/bin/sh
# Email ALERT_EMAIL when a timer job fails (uses the same SMTP settings as OpsEngine).
cd /opt/opsengine
python3 - "$1" <<'PY'
import os, sys
from opsengine import config, connectors
config.load_dotenv()
to = os.environ.get("ALERT_EMAIL")
if to:
    print(connectors.send("email", to, f"[OpsEngine] {sys.argv[1]}", f"{sys.argv[1]}.\n\nCheck: journalctl -u opsengine-daily -u opsengine-inbox -u opsengine-backup --since today"))
PY
