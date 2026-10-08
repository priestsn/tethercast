#!/usr/bin/env python3
"""
valida_metodo.py — il metodo e' giusto?

Si confrontano DUE CATTURE DELLO STESSO SCHERMO (la scheda con se stessa).
Il ritardo vero e' ZERO per definizione: deve uscire ~0.

⚠️ PRIMO TENTATIVO SBAGLIATO: cronometravo solo la PAUSA fra le catture e
non la durata di grim, che e' ~0,3 s. Risultava un offset costante di
-0,28 s che sembrava un errore del metodo, mentre era un errore del
cronometro. Qui si usano i PUNTI MEDI di ogni cattura, come fa il
misuratore vero.

E' l'unico modo di distinguere un metodo giusto da uno che sembra
plausibile: applicarlo a un caso di cui si conosce la risposta.
"""
import os
import subprocess
import time
import colorsys

import numpy as np
from PIL import Image

AMBIENTE = dict(os.environ)
CICLO = 20.0
BOX = (16, 634, 376, 704)


def scatta(percorso):
    t0 = time.time()
    subprocess.run(["grim", "-o", "client", percorso], env=AMBIENTE, capture_output=True)
    t1 = time.time()
    return (t0 + t1) / 2, t1 - t0


def tinta(percorso):
    im = Image.open(percorso)
    im.load()
    a = np.asarray(im.convert("RGB")).astype(float)
    r = a[BOX[1]:BOX[3], BOX[0]:BOX[2]]
    mx, mn = r.max(axis=2), r.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    mask = sat > 0.60
    if mask.sum() < 200:
        return None, int(mask.sum())
    m = r[mask].mean(axis=0)
    h, _, _ = colorsys.rgb_to_hsv(*(m / 255.0))
    return h * CICLO, int(mask.sum())


print("  validazione: due catture della STESSA scheda, ritardo vero = 0")
print()
print("  %-8s %-9s %-9s %-11s %-9s %s" %
      ("pausa", "durata", "delta", "d", "L", "giudizio"))
print("  " + "-" * 62)

esiti = []
for pausa in (0.0, 0.3, 0.8, 1.5):
    m1, d1 = scatta("/tmp/v1.png")
    time.sleep(pausa)
    m2, d2 = scatta("/tmp/v2.png")

    c1, n1 = tinta("/tmp/v1.png")
    c2, n2 = tinta("/tmp/v2.png")
    if c1 is None or c2 is None:
        print("  %-8.1f cattura senza striscia (px %d, %d)" % (pausa, n1, n2))
        continue
    d = (c2 - c1) % CICLO
    if d > CICLO / 2:
        d -= CICLO
    delta = m2 - m1
    L = delta - d
    esiti.append(L)
    print("  %-8.1f %-9.2f %-9.2f %+-9.2f %+-9.3f %s" %
          (pausa, (d1 + d2) / 2, delta, d, L,
           "OK" if abs(L) < 0.10 else "SCARTO"))

if esiti:
    media = sum(esiti) / len(esiti)
    print()
    print("  media degli scarti: %+.3f s" % media)
    print("  escursione: %.3f s" % (max(esiti) - min(esiti)))
    print()
    if abs(media) < 0.10 and (max(esiti) - min(esiti)) < 0.12:
        print("  >>> METODO VALIDO: a ritardo noto zero restituisce zero <<<")
    else:
        print("  >>> METODO NON AFFIDABILE: va corretto prima di credergli <<<")
