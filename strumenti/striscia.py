#!/usr/bin/env python3
"""
striscia.py — l'orologio del misuratore di latenza.

Riempie la finestrella con una tinta che compie un giro completo ogni
20 secondi (OSC 11 = colore di sfondo del terminale). Il misuratore
legge quella tinta sia dallo schermo della scheda sia da quello del
tablet: la differenza fra le due e' il ritardo.

Perche' 20 secondi e non 10: la lettura e' ambigua di un giro intero.
Con 20 s il valore sta comodamente entro +-10 s e un ritardo di 1-2 s
non si confonde con uno di 11-12 s.
"""
import sys
import time
import colorsys

CICLO = 20.0
PASSO = 0.05

ultimo = None
try:
    while True:
        t = time.time()
        r, g, b = colorsys.hsv_to_rgb((t % CICLO) / CICLO, 1.0, 1.0)
        hexcol = "%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
        if hexcol != ultimo:
            sys.stdout.write("\033]11;#%s\007" % hexcol)
            # il testo (se c'e') resta, rimpicciolito a un carattere:
            # lo sfondo e' quello che conta, lo leggiamo noi
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            ultimo = hexcol
        time.sleep(PASSO)
except KeyboardInterrupt:
    sys.stdout.write("\033]111\007")
    sys.stdout.flush()
