#!/usr/bin/env bash
# Build the "Gym" watch app and install it on a watch connected by USB.
# Usage: ./build.sh [device]   (default fr55; the watch must be mounted, e.g. D:\GARMIN)
set -euo pipefail
cd "$(dirname "$0")"
DEVICE="${1:-fr55}"
ENV_FILE="../.deploy.env"
SDK_BIN="${CIQ_SDK_BIN:-$(ls -d "$APPDATA"/Garmin/ConnectIQ/Sdks/*/bin 2>/dev/null | sort | tail -1)}"
[ -x "$SDK_BIN/monkeyc.bat" ] || [ -x "$SDK_BIN/monkeyc" ] || { echo "Connect IQ SDK not found (set CIQ_SDK_BIN)"; exit 1; }

# Secrets.mc is generated here and never committed (the repo is public).
python - "$ENV_FILE" <<'PY'
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

[ -f developer_key.der ] || {
  openssl genrsa -out developer_key.pem 4096 2>/dev/null
  openssl pkcs8 -topk8 -inform PEM -outform DER -in developer_key.pem -out developer_key.der -nocrypt
  rm -f developer_key.pem
  echo "developer key created"
}

mkdir -p bin
MONKEYC="$SDK_BIN/monkeyc"; [ -f "$MONKEYC.bat" ] && MONKEYC="$MONKEYC.bat"
"$MONKEYC" -d "$DEVICE" -f monkey.jungle -o bin/Gym.prg -y developer_key.der -l 0 -r
echo "built bin/Gym.prg for $DEVICE"

# Same file name as the first install so the watch replaces the app in place.
for drive in /d /e /f /g; do
  if [ -d "$drive/GARMIN/APPS" ]; then
    cp bin/Gym.prg "$drive/GARMIN/APPS/PESAS.PRG"
    echo "installed to $drive/GARMIN/APPS/PESAS.PRG - unplug the watch to finish"
    exit 0
  fi
done
echo "watch not found over USB; copy bin/Gym.prg to GARMIN/APPS/PESAS.PRG manually"
