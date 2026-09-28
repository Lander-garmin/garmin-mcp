#!/usr/bin/env bash
# Build the "Trainer" widget and install it on a watch connected by USB.
# Usage: ./build.sh [device]   (default fr55)
set -euo pipefail
cd "$(dirname "$0")"
DEVICE="${1:-fr55}"
SDK_BIN="${CIQ_SDK_BIN:-$(ls -d "$APPDATA"/Garmin/ConnectIQ/Sdks/*/bin 2>/dev/null | sort | tail -1)}"
[ -x "$SDK_BIN/monkeyc.bat" ] || [ -x "$SDK_BIN/monkeyc" ] || { echo "Connect IQ SDK not found (set CIQ_SDK_BIN)"; exit 1; }
KEY="../watch-app/developer_key.der"   # same developer key as the Gym app
[ -f "$KEY" ] || { echo "missing $KEY (run watch-app/build.sh once)"; exit 1; }

# Secrets.mc is generated here and never committed (the repo is public).
python - "../.deploy.env" <<'PY'
import hashlib, hmac, re, sys
env = open(sys.argv[1], encoding="utf-8").read()
secret = re.search(r'JWT_SECRET="?([^"\n]+)"?', env).group(1)
key = hmac.new(secret.encode(), b"watch-api", hashlib.sha256).hexdigest()[:32]
open("source/Secrets.mc", "w", encoding="utf-8").write(
    '(:background)\nmodule Secrets {\n'
    '    const SERVER_URL = "https://svc-sync-eu-2609.onrender.com";\n'
    f'    const WATCH_KEY = "{key}";\n'
    '}\n'
)
print("Secrets.mc written")
PY

mkdir -p bin
MONKEYC="$SDK_BIN/monkeyc"; [ -f "$MONKEYC.bat" ] && MONKEYC="$MONKEYC.bat"
"$MONKEYC" -d "$DEVICE" -f monkey.jungle -o bin/Coach.prg -y "$KEY" -l 0 -r
echo "built bin/Coach.prg for $DEVICE"

for drive in /d /e /f /g; do
  if [ -d "$drive/GARMIN/APPS" ]; then
    rm -f "$drive/GARMIN/APPS/COACH.PRG"   # old watch-face build, replaced by the widget
    cp bin/Coach.prg "$drive/GARMIN/APPS/COACHW.PRG"
    echo "installed to $drive/GARMIN/APPS/COACHW.PRG - unplug the watch; the Trainer widget appears with UP/DOWN"
    exit 0
  fi
done
echo "watch not connected: bin/Coach.prg is ready to copy to GARMIN/APPS/COACHW.PRG"
