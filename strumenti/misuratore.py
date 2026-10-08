#!/usr/bin/env python3
"""
misuratore.py — ritardo fra lo schermo della scheda e quello del tablet.

METODO: si confrontano DUE SCHERMI, mai l'ora di sistema contro un colore.
    - grim cattura l'uscita della scheda (quasi istantanea)
    - adb screencap cattura il tablet (LENTO: ~0,6 s)
Entrambe contengono la stessa striscia colorata.

⚠️⚠️ IL DETTAGLIO CHE SBAGLIAVO: le due catture NON sono simultanee. Lo
screencap del tablet arriva ~0,6 s dopo il grim. Se si confrontano i
colori come se fossero dello stesso istante si misura

        d = Δ − L          (Δ = distanza fra le due catture)

cioe' l'INVERSO di quello che interessa. Con Δ≈0,6 s e d≈0,16 si
leggeva "160 ms" mentre il ritardo vero era ~440 ms. Il valore era
piccolo proprio perche' il ritardo era grande: la cosa piu' insidiosa
e' un errore che sembra un miglioramento.

Qui si cronometra ogni cattura e si ricava:
        L = (istante_tablet − istante_scheda) − d

⚠️ ATTENZIONE ALLA SCALA: hyprctl riporta le coordinate in unita'
logiche, i pixel sono unita' logiche x scala.
"""
import os
import subprocess
import time
import colorsys

import numpy as np
from PIL import Image

CICLO = 20.0
USCITA = os.environ.get("OUT", "client")
TABLET = os.environ.get("TABLET", "HA1NRY34")
FILE_ESITO = os.environ.get("FILE_ESITO", "/tmp/tethercast-latency.txt")
INTERVALLO = float(os.environ.get("INTERVALLO", 0.4))
SX = int(os.environ.get("STRIP_X", 16))
SY = int(os.environ.get("STRIP_Y", 634))
SL = int(os.environ.get("STRIP_W", 360))
SA = int(os.environ.get("STRIP_H", 70))
SAT_MIN = float(os.environ.get("SAT_MIN", 0.60))
AMBIENTE = dict(os.environ)


def geometria():
    try:
        out = subprocess.run(["hyprctl", "monitors"], capture_output=True,
                             text=True, env=AMBIENTE, timeout=10).stdout
        for blocco in out.split("Monitor "):
            if blocco.startswith(USCITA):
                modo, scala = None, 1.0
                for r in blocco.splitlines()[:6]:
                    r = r.strip()
                    if "x" in r and "@" in r:
                        modo = r.split()[0]
                    if r.startswith("scale:"):
                        scala = float(r.split()[1])
                if modo:
                    l, a = modo.split("@")[0].split("x")
                    return int(l), int(a), scala
    except Exception:
        pass
    return 1200, 720, 1.0


def tinta(percorso, box):
    try:
        im = Image.open(percorso)
        im.load()
    except Exception:
        return None, None, 0
    a = np.asarray(im.convert("RGB")).astype(float)
    x0, y0, x1, y1 = (max(0, int(v)) for v in box)
    x1 = min(a.shape[1], x1)
    y1 = min(a.shape[0], y1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        return None, None, 0
    r = a[y0:y1, x0:x1]
    mx, mn = r.max(axis=2), r.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    mask = sat > SAT_MIN
    n = int(mask.sum())
    if n < 200:
        return None, None, n
    m = r[mask].mean(axis=0)
    h, s, v = colorsys.rgb_to_hsv(*(m / 255.0))
    return h * CICLO, m.round(0), n


def main():
    larg, alt, scala = geometria()
    box_s = (SX * scala, SY * scala, (SX + SL) * scala, (SY + SA) * scala)
    print("misuratore avviato", flush=True)
    print("  uscita %s %dx%d scala %.2f | striscia %s" %
          (USCITA, larg, alt, scala, tuple(round(v) for v in box_s)), flush=True)

    ultimi = []
    while True:
        try:
            # --- cattura della scheda, cronometrata ---
            g0 = time.time()
            subprocess.run(["grim", "-o", USCITA, "/tmp/mis_scheda.png"],
                           env=AMBIENTE, capture_output=True)
            g1 = time.time()

            # --- cattura del tablet, cronometrata ---
            s0 = time.time()
            with open("/tmp/mis_tablet.png", "wb") as f:
                f.write(subprocess.run(
                    ["adb", "-s", TABLET, "exec-out", "screencap", "-p"],
                    capture_output=True).stdout)
            s1 = time.time()

            im_t = Image.open("/tmp/mis_tablet.png")
            lt, at = im_t.size
            fattore = lt / float(larg * scala) if larg * scala else 1.0
            box_t = tuple(v * fattore for v in box_s)

            cs, rs, ns = tinta("/tmp/mis_scheda.png", box_s)
            ct, rt, nt = tinta("/tmp/mis_tablet.png", box_t)
            if cs is None or ct is None:
                print("  SCARTATO (scheda %d px, tablet %d px)" % (ns, nt), flush=True)
                time.sleep(INTERVALLO)
                continue

            # d = quanto il colore del tablet e' AVANTI rispetto a quello
            # della scheda. Siccome la cattura del tablet e' piu' tarda,
            # il ritardo vero e' l'intervallo meno questo scarto.
            d = (ct - cs) % CICLO
            if d > CICLO / 2:
                d -= CICLO
            delta = (s0 + s1) / 2 - (g0 + g1) / 2
            ritardo = delta - d
            # se uscisse negativo o assurdo, il campione non e' affidabile
            if ritardo < 0 or ritardo > 15:
                print("  campione incoerente: delta %.2f  d %+.2f  -> %.2f" %
                      (delta, d, ritardo), flush=True)
                time.sleep(INTERVALLO)
                continue

            ms = ritardo * 1000.0
            ultimi.append(ms)
            if len(ultimi) > 6:
                ultimi.pop(0)
            mediana = sorted(ultimi)[len(ultimi) // 2]
            print("  RITARDO %7.1f ms   (delta %.2f  d %+.2f)  scheda %s tablet %s" %
                  (mediana, delta, d, rs, rt), flush=True)
            try:
                with open(FILE_ESITO, "w") as f:
                    f.write("%d\n" % round(mediana))
            except Exception:
                pass
        except Exception as e:
            print("  errore: %s" % e, flush=True)
        time.sleep(INTERVALLO)


if __name__ == "__main__":
    main()
