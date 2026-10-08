#!/usr/bin/env bash
# ============================================================
#  tablet-watch.sh — tiene il tablet collegato da solo
#
#  Gira sulla BC250 come servizio. Fa due cose:
#   1. quando il tablet compare su adb: apre il ponte USB e lancia mpv
#   2. ogni pochi secondi: se il flusso non ha PIU' lettori ma il tablet
#      e' collegato, rilanciа mpv
#
#  Il punto 2 e' quello che conta: senza, se mpv muore o viene chiuso
#  per sbaglio, lo schermo resta nero finche' non intervieni a mano.
#  Con, il monitor si riprende da solo.
# ============================================================
set -u

TABLET="${TABLET:-HA1NRY34}"
PORTA="${PORTA:-8080}"
GIRI=3                 # ogni quanti cicli controllare chi legge il flusso

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

collega() {
  local dev="$1"
  adb -s "$dev" reverse "tcp:${PORTA}" "tcp:${PORTA}" >/dev/null 2>&1
  adb -s "$dev" shell am force-stop com.orbiscreen.android >/dev/null 2>&1
  adb -s "$dev" shell am force-stop is.xyz.mpv >/dev/null 2>&1
  sleep 1
  adb -s "$dev" shell am start -n is.xyz.mpv/.MPVActivity \
      -a android.intent.action.VIEW \
      -d "http://127.0.0.1:${PORTA}/live" \
      -t "video/mp2t" >/dev/null 2>&1
}

spettatori() {
  curl -s --max-time 4 "http://127.0.0.1:${PORTA}/stato" 2>/dev/null \
    | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('spettatori', 0))
except Exception:
    print(-1)
" 2>/dev/null
}

log "sorvegliante avviato (tablet: $TABLET, porta: $PORTA)"
trovato=""
giro=0

while true; do
  if [ -n "$TABLET" ]; then
    attuale=$(adb devices 2>/dev/null | awk -v t="$TABLET" '$1==t && $2=="device" {print $1}')
  else
    attuale=$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1; exit}')
  fi

  if [ -n "$attuale" ]; then
    # il tablet e' appena comparso
    if [ "$attuale" != "$trovato" ]; then
      log "tablet comparso: $attuale"
      trovato="$attuale"
      if [ "$(spettatori)" = "-1" ]; then
        log "  il server non risponde, aspetto"
        trovato=""
        sleep 3
        continue
      fi
      collega "$attuale"
      log "  ponte USB attivo, mpv avviato"
      sleep 10
      continue
    fi

    # tablet gia' collegato: ogni tanto verifico che qualcuno legga il flusso
    giro=$((giro + 1))
    if [ "$giro" -ge "$GIRI" ]; then
      giro=0
      s=$(spettatori)
      if [ "$s" = "0" ]; then
        log "nessun lettore sul flusso: rilancio mpv"
        collega "$attuale"
        sleep 10
        continue
      fi
    fi
  else
    if [ -n "$trovato" ]; then
      log "tablet scollegato"
      trovato=""
    fi
  fi

  sleep 3
done
