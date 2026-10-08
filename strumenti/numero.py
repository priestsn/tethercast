#!/usr/bin/env python3
"""
numero.py — mostra il ritardo in grande, nella finestrella accanto
alla striscia colorata.

Legge /tmp/tethercast-latency.txt (lo scrive misuratore.py) e lo
ridisegna. Il colore del testo cambia con la soglia, cosi' si capisce
a colpo d'occhio se va bene o no.

Tiene lo sfondo NERO: la finestrella non deve inquinare la lettura
della striscia accanto, che invece e' colorata di proposito.
"""
import os
import sys
import time

FILE = os.environ.get("FILE_ESITO", "/tmp/tethercast-latency.txt")

# soglie: sotto 100 ms e' usabile, sotto 200 e' accettabile, oltre no
def colore(ms):
    if ms < 100:
        return "\033[1;32m"      # verde
    if ms < 200:
        return "\033[1;33m"      # giallo
    return "\033[1;31m"          # rosso


ultimo = None
try:
    while True:
        try:
            with open(FILE) as f:
                ms = int(f.read().strip())
        except Exception:
            ms = None

        if ms != ultimo:
            sys.stdout.write("\033[2J\033[H")          # pulisci
            sys.stdout.write("\033]11;#000000\007")     # sfondo nero
            if ms is None:
                sys.stdout.write("\033[1;37m  -- ms\033[0m")
            else:
                sys.stdout.write("%s%4d ms\033[0m" % (colore(ms), ms))
            sys.stdout.flush()
            ultimo = ms
        time.sleep(0.2)
except KeyboardInterrupt:
    sys.stdout.write("\033]111\007")
    sys.stdout.flush()
