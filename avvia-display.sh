#!/usr/bin/env bash
# ============================================================
#  bc250-display — avvia tutto e apre lo schermo sul tablet
#
#    ./avvia-display.sh          avvia e apre sul tablet
#    ./avvia-display.sh stop     ferma tutto
#    ./avvia-display.sh stato    stato del flusso
# ============================================================
set -u

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
SIG=$(ls /run/user/1000/hypr 2>/dev/null | head -1)
export HYPRLAND_INSTANCE_SIGNATURE="${HYPRLAND_INSTANCE_SIGNATURE:-$SIG}"

PORT="${PORT:-8080}"
TABLET="${TABLET:-}"        # lasciato vuoto: prende il primo dispositivo adb
DIR="$(cd "$(dirname "$0")" && pwd)"

ferma() {
  pkill -f bc250-display.py 2>/dev/null
  pkill -x wf-recorder 2>/dev/null
  pkill -f "ffmpeg.*rawvideo.*bc250-display" 2>/dev/null
  rm -f /tmp/bc250-display.nut 2>/dev/null
  for M in client; do hyprctl output remove "$M" >/dev/null 2>&1; done
  echo "fermato"
}

stato() {
  curl -s --max-time 4 "http://127.0.0.1:${PORT}/stato" 2>/dev/null || echo "server non in ascolto"
}

case "${1:-avvia}" in
  stop|ferma)  ferma; exit 0 ;;
  stato)       stato; exit 0 ;;
esac

# ── 1. pulizia di eventuali esecuzioni precedenti ──
ferma >/dev/null 2>&1
sleep 2

# ── 2. il server: cattura, encoder hardware, HTTP ──
echo "avvio il server (uscita virtuale 1200x720, encoder h264_vaapi)…"
cd "$DIR"
nohup python3 -u bc250-display.py > /tmp/bc250-display.log 2>&1 &
sleep 12

if ! curl -s --max-time 4 "http://127.0.0.1:${PORT}/stato" >/dev/null 2>&1; then
  echo "il server non risponde; log:"
  tail -12 /tmp/bc250-display.log | sed 's/^/  /'
  exit 1
fi
echo "  server attivo sulla porta $PORT"

# ── 3. il ponte verso il tablet dentro il cavo USB ──
adb start-server >/dev/null 2>&1
DISPOSITIVO="${TABLET:-$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1; exit}')}"

if [ -z "$DISPOSITIVO" ]; then
  echo "  nessun tablet collegato via adb: collega il cavo USB e riprova"
  echo "  il server resta attivo: puoi aprirlo anche dal PC su http://127.0.0.1:${PORT}/"
  exit 0
fi

adb -s "$DISPOSITIVO" reverse "tcp:${PORT}" "tcp:${PORT}" >/dev/null 2>&1
echo "  ponte USB attivo per $DISPOSITIVO"

# ── 4. apro il client sul tablet ──
adb -s "$DISPOSITIVO" shell am start -a android.intent.action.VIEW \
    -d "http://127.0.0.1:${PORT}/" >/dev/null 2>&1
echo "  client aperto sul tablet"

echo
echo "sul tablet dovresti vedere lo schermo della BC250."
echo "  chiudi il pannello di traduzione di Firefox se compare (Not now)."
echo "  per lo schermo pieno: menu di Firefox > Aggiungi a schermata home, poi aprilo da lì."
echo
echo "  stato:  $0 stato"
echo "  stop:   $0 stop"
