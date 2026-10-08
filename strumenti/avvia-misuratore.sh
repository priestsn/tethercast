#!/usr/bin/env bash
# ============================================================
#  avvia-misuratore.sh — apre le due finestrelle e il misuratore
#
#  Le finestrelle vanno piazzate A CALDO: hyprctl reload NON riesegue la
#  configurazione Lua di omarchy, quindi una regola scritta nel file
#  varrebbe solo dal prossimo avvio della sessione. I dispatcher invece
#  funzionano subito:
#      hl.dsp.window.float({ action = "enable" })
#      hl.dsp.window.resize({ x = ..., y = ... })
#      hl.dsp.window.move({ x = ..., y = ... })
#  ⚠️ Agiscono sulla finestra ATTIVA: vanno eseguiti SUBITO dopo aver
#  aperto la finestra, prima che qualcos'altro prenda il fuoco.
#  ⚠️ Il percorso e' hl.dsp.window.move, NON hl.window.move (che esiste
#  ma vuole altri argomenti e fa fallire la chiamata).
# ============================================================
set -u
export XDG_RUNTIME_DIR=/run/user/1000
export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr 2>/dev/null | head -1)
export WAYLAND_DISPLAY=wayland-1

USCITA="${OUT:-client}"
TABLET="${TABLET:-HA1NRY34}"
DIR="$(cd "$(dirname "$0")" && pwd)"

# geometria: la striscia in basso a sinistra, il numero subito a destra
STRIP_X=16;  STRIP_Y=634;  STRIP_W=360; STRIP_H=70
NUM_X=384;   NUM_Y=634;    NUM_W=150;   NUM_H=70

sistema_finestra() {
  local x="$1" y="$2" l="$3" a="$4"
  hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = \"enable\" }))" >/dev/null 2>&1
  sleep 0.3
  hyprctl eval "hl.dispatch(hl.dsp.window.resize({ x = $l, y = $a }))" >/dev/null 2>&1
  sleep 0.3
  hyprctl eval "hl.dispatch(hl.dsp.window.move({ x = $x, y = $y }))" >/dev/null 2>&1
  sleep 0.3
}

apri() {
  local titolo="$1" comando="$2"
  systemd-run --user --unit="$titolo" --collect \
    --setenv=WAYLAND_DISPLAY=wayland-1 \
    --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
    --setenv=HYPRLAND_INSTANCE_SIGNATURE="$HYPRLAND_INSTANCE_SIGNATURE" \
    foot -o font=monospace:size=18 -o colors.background=000000 \
         -T "$titolo" -a "$USCITA" -e $comando >/dev/null 2>&1
}

echo "=== 1. fermo eventuali copie precedenti ==="
for u in tethercast-striscia tethercast-numero tethercast-misura; do
  systemctl --user stop "$u" 2>/dev/null
done
pkill -f striscia.py 2>/dev/null
pkill -f numero.py 2>/dev/null
sleep 1

echo "=== 2. la striscia colorata (l'orologio) ==="
apri tethercast-striscia "python3 $DIR/striscia.py"
sleep 4
sistema_finestra "$STRIP_X" "$STRIP_Y" "$STRIP_W" "$STRIP_H"

echo "=== 3. la finestra del numero ==="
apri tethercast-numero "python3 $DIR/numero.py"
sleep 4
sistema_finestra "$NUM_X" "$NUM_Y" "$NUM_W" "$NUM_H"

echo
echo "=== 4. dove sono finite ==="
hyprctl clients 2>/dev/null | grep -B20 "tethercast" | grep -E "at:|size:|floating:|title:|monitor:" | head -12 | sed 's/^/  /'

echo
echo "=== 5. avvio il misuratore ==="
systemd-run --user --unit=tethercast-misura --collect \
  --setenv=WAYLAND_DISPLAY=wayland-1 \
  --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  --setenv=HYPRLAND_INSTANCE_SIGNATURE="$HYPRLAND_INSTANCE_SIGNATURE" \
  --setenv=OUT="$USCITA" --setenv=TABLET="$TABLET" \
  --setenv=STRIP_X="$STRIP_X" --setenv=STRIP_Y="$STRIP_Y" \
  --setenv=STRIP_W="$STRIP_W" --setenv=STRIP_H="$STRIP_H" \
  python3 "$DIR/misuratore.py" >/dev/null 2>&1
sleep 1
echo "  attivo: $(systemctl --user is-active tethercast-misura.service 2>/dev/null)"
echo
echo "=== 6. prime letture ==="
sleep 12
journalctl --user -u tethercast-misura --no-pager -n 8 2>/dev/null | tail -8 | sed 's/^/  /'
echo
echo "  valore attuale: $(cat /tmp/tethercast-latency.txt 2>/dev/null || echo 'non ancora')"
