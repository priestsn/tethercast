#!/usr/bin/env python3
"""
bc250-display — il server.

Cattura lo schermo della BC-250 con wlroots, lo codifica con l'encoder
HARDWARE h264_vaapi e lo serve via HTTP. Il tablet lo apre con Firefox
attraverso il cavo USB (adb reverse): nessuna rete, nessun internet.

    ./bc250-display.py            avvia e resta in ascolto
    ./bc250-display.py --status   mostra lo stato
    ./bc250-display.py --stop     ferma tutto

Solo libreria standard: niente da installare.
"""
import http.server, socketserver, subprocess, threading, time
import os, sys, signal, socket, json, urllib.request

# ─────────────────────── parametri ───────────────────────
PORTA      = int(os.environ.get("PORT", 8080))
USCITA     = os.environ.get("OUT", "client")
LARGHEZZA  = int(os.environ.get("W", 1200))
ALTEZZA    = int(os.environ.get("H", 720))
FPS        = int(os.environ.get("FPS", 60))
BITRATE    = os.environ.get("BITRATE", "8M")
DEVICE     = os.environ.get("VAAPI", "/dev/dri/renderD128")
HTML       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client.html")

XDG        = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
WAYLAND    = os.environ.get("WAYLAND_DISPLAY", "wayland-1")

def _sig_hyprland():
    try:
        return os.listdir(f"{XDG}/hypr")[0]
    except Exception:
        return ""

AMBIENTE = dict(os.environ)
AMBIENTE.update({
    "XDG_RUNTIME_DIR": XDG,
    "WAYLAND_DISPLAY": WAYLAND,
    "XDG_SESSION_TYPE": "wayland",
    "XDG_CURRENT_DESKTOP": "Hyprland",
    "HYPRLAND_INSTANCE_SIGNATURE": _sig_hyprland(),
})

# ─────────────────────── stato condiviso ───────────────────────
blocco      = threading.Lock()
ffmpeg      = None
wfrecorder  = None
spettatori  = []          # code che stanno leggendo il flusso
statistiche = {"avvii": 0, "frame_letti": 0, "ultimo_errore": None,
               "dal": None, "client": 0, "spettatori_max": 0}

# ─────────────────────── uscita virtuale ───────────────────────
def prepara_uscita():
    """Crea l'uscita virtuale se non c'e'. 5:3, lo stesso del tablet:
    cosi' lo schermo si riempie senza bande nere."""
    try:
        out = subprocess.run(["hyprctl", "monitors"], capture_output=True,
                             text=True, env=AMBIENTE, timeout=10).stdout
        if f"Monitor {USCITA} " not in out:
            subprocess.run(["hyprctl", "output", "create", "headless", USCITA],
                           env=AMBIENTE, timeout=10)
            time.sleep(1)
            subprocess.run(["hyprctl", "eval",
                f'hl.monitor({{ output = "{USCITA}", mode = "{LARGHEZZA}x{ALTEZZA}@{FPS}", '
                f'position = "0x0", scale = 1 }})'],
                env=AMBIENTE, timeout=10)
            time.sleep(2)
        out = subprocess.run(["hyprctl", "monitors"], capture_output=True,
                             text=True, env=AMBIENTE, timeout=10).stdout
        for riga in out.splitlines():
            if riga.startswith(f"Monitor {USCITA} "):
                return True
        return False
    except Exception as e:
        print(f"[!] uscita virtuale: {e}")
        return False

# ─────────────────────── la catena di cattura ───────────────────────
FIFO = "/tmp/bc250-display.nut"
wfr_log = open("/tmp/bc250-wfr.log", "w")

def avvia_catena():
    """wf-recorder cattura frame grezzi -> ffmpeg codifica in hardware e
    scrive l'fMP4 sullo stdout, da cui lo leggiamo e lo distribuiamo."""
    global ffmpeg, wfrecorder, FIFO

    for p in (ffmpeg, wfrecorder):
        if p and p.poll() is None:
            p.kill()
    # pulizia dura: catturatori rimasti da esecuzioni precedenti. Se ne
    # sopravvive anche uno, tiene occupata l'uscita e il flusso nuovo non
    # parte piu'. E' il difetto che faceva sembrare rotta la catena.
    subprocess.run(["pkill", "-x", "wf-recorder"], capture_output=True)
    subprocess.run(["pkill", "-f", "ffmpeg.*rawvideo.*" + FIFO], capture_output=True)
    time.sleep(1.5)
    if os.path.exists(FIFO):
        try:
            os.remove(FIFO)
        except OSError:
            pass
    os.mkfifo(FIFO)

    # 1. cattura: frame BGRA grezzi dal compositor.
    #    'echo y |' e' la forma che funziona: risponde al prompt "sovrascrivo?"
    #    PRIMA che wf-recorder apra la FIFO. Scrivere su stdin dopo l'avvio
    #    non basta, perche' il prompt viene letto subito e il processo resta fermo.
    wfrecorder = subprocess.Popen(
        # -D e' ESSENZIALE: senza, wf-recorder chiede un frame al compositor
        # solo quando qualcosa cambia sullo schermo ("damage"). Su un'uscita
        # virtuale vuota non cambia mai niente, quindi manda i primi fotogrammi
        # e poi resta in attesa per sempre. Con -D cattura a raffica continua.
        ["sh", "-c", f'echo y | exec wf-recorder -D -o "{USCITA}" '
                     f'-c rawvideo -x bgra -f "{FIFO}"'],
        stdout=subprocess.DEVNULL, stderr=wfr_log, env=AMBIENTE)

    # 2. encoder HARDWARE + contenitore per lo streaming
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
         "-vaapi_device", DEVICE,
         # wf-recorder NON scrive pixel grezzi: scrive un contenitore NUT
         # ("Output #0, nut") con dentro i frame rawvideo. Leggendolo come
         # rawvideo gli header del contenitore finiscono interpretati come
         # pixel, ogni frame risulta spostato rispetto al precedente e si
         # ottiene l'immagine che scorre in diagonale con i canali di colore
         # fuori registro. Va letto per quello che e': -f nut.
         "-f", "nut", "-i", FIFO,
         "-vf", "format=nv12,hwupload",
         "-c:v", "h264_vaapi",
         # ── RATE-CONTROL A QUALITA' COSTANTE ──
         # Prima: -b:v 8M -maxrate 8M -bufsize 16M, cioe' un buffer VBV da
         # 16 Mbit = 2 SECONDI di flusso. Il rate-control di un encoder
         # hardware con VBV grosso ritarda l'uscita dei fotogrammi per
         # rispettare la media: e' ritardo puro su un cavo, dove la banda
         # non e' mai un problema (USB 2.0 = 480 Mbps, qui ne passano 3).
         # Con CQP il codificatore emette ogni fotogramma appena pronto, a
         # qualita' fissa, senza nessuna media da inseguire.
         # Nota: -low_power NON e' supportato da questo driver (rifiutato).
         "-rc_mode", "CQP", "-qp", "24",
         "-g", str(FPS // 2), "-bf", "0",
         # ── LOTTA AL RITARDO (misurato: 1,33 s prima di queste opzioni) ──
         # 1. mpv/ffmpeg aspettano di avere N frame in coda prima di
         #    consegnarli: per un flusso dal cavo e' solo ritardo inutile.
         #    async_depth e' la coda dell'encoder hardware (default 4 frame).
         "-async_depth", "1",
         # 2. LA CAUSA PRINCIPALE: per MPEG-TS ffmpeg mette di default
         #    muxdelay=0,7 s, cioe' trattiene ogni pacchetto sette decimi di
         #    secondo prima di scriverlo. A zero il pacchetto esce subito.
         "-muxdelay", "0", "-muxpreload", "0", "-max_delay", "0",
         # 3. niente attesa di riempimento dei buffer del demuxer
         "-fflags", "+nobuffer", "-flags", "low_delay",
         # dump_extra ripete i parametri SPS/PPS su ogni keyframe: senza,
         # chi si aggancia a flusso gia' iniziato non sa che codec sta
         # guardando e fallisce con "non-existing PPS 0 referenced".
         "-bsf:v", "dump_extra=freq=keyframe",
         # MPEG-TS: e' l'unico contenitore che consegna i frame appena pronti.
         # MP4 e Matroska si tengono in buffer ~1 KB di header e sembrano morti.
         "-f", "mpegts", "-mpegts_flags", "+resend_headers",
         "-flush_packets", "1",
         "-"],
        stdout=subprocess.PIPE, stderr=open("/tmp/bc250-ffmpeg.log", "w"), env=AMBIENTE)

    with blocco:
        statistiche["avvii"] += 1
        statistiche["dal"] = time.time()

def distribuisci(origine):
    """Legge l'MPEG-TS da ffmpeg e lo passa a tutti gli spettatori collegati.

    ⚠️ NON usare origine.stdout.read(N): in Python quella chiamata ASPETTA di
    avere N byte prima di restituirli. Con letture da 64 KB e un bitrate di
    2,8 Mbps significa tenere in gabbia 187 ms di flusso a ogni giro — che si
    sommano tutti al ritardo percepito. os.read invece torna appena c'e'
    QUALCOSA da leggere, quindi il primo byte utile parte subito.
    """
    fd = origine.stdout.fileno()
    while True:
        pezzo = os.read(fd, 65536)
        if not pezzo:
            break
        with blocco:
            statistiche["frame_letti"] += len(pezzo)
            vivi = []
            for coda in spettatori:
                try:
                    coda.append(pezzo)
                except Exception:
                    continue
                vivi.append(coda)
            spettatori[:] = vivi
            in_corso = len(vivi)
            statistiche["spettatori_max"] = max(statistiche["spettatori_max"], in_corso)

def sorveglia():
    """Se la catena muore, la fa ripartire. E' il motivo per cui questo
    client non va 'sistemato ogni due giorni'."""
    global ffmpeg
    while True:
        time.sleep(5)
        morto = ffmpeg is None or ffmpeg.poll() is not None
        if morto:
            with blocco:
                statistiche["ultimo_errore"] = "la catena si e' fermata, riavvio"
            print("[!] catena ferma: riavvio")
            time.sleep(2)
            avvia_catena()
            threading.Thread(target=leggi_e_distribuisci, daemon=True).start()

def leggi_e_distribuisci():
    if ffmpeg and ffmpeg.stdout:
        distribuisci(ffmpeg)

# ─────────────────────── HTTP ───────────────────────
class Gestore(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Niente algoritmo di Nagle: senza, il sistema puo' trattenere un
    # pacchetto piccolo (per esempio la testata di un chunk) in attesa di
    # altro da accorpare, aggiungendo fino a 40 ms per volta — e qui i
    # pezzi piccoli sono la norma, non l'eccezione.
    disable_nagle_algorithm = True

    def log_message(self, *a):
        pass

    def do_GET(self):
        percorso = self.path.split("?")[0]

        if percorso in ("/", "/index.html"):
            try:
                with open(HTML, "rb") as f:
                    corpo = f.read()
            except FileNotFoundError:
                corpo = b"client.html non trovato accanto allo script"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)
            return

        if percorso == "/mpegts.js":
            percorso_file = os.path.join(os.path.dirname(HTML), "mpegts.js")
            try:
                with open(percorso_file, "rb") as f:
                    corpo = f.read()
            except FileNotFoundError:
                self.send_error(404, "mpegts.js non trovato accanto a client.html")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(corpo)
            return

        if percorso == "/live":
            # Il flusso non finisce mai, quindi non c'e' un Content-Length.
            # Un browser che riceve un corpo senza lunghezza nota e senza
            # Transfer-Encoding lo rifiuta con NetworkError: va dichiarato
            # "chunked", cioe' una sequenza di pezzi che continua finche'
            # la connessione resta aperta.
            self.protocol_version = "HTTP/1.1"
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            coda = []
            with blocco:
                spettatori.append(coda)
                statistiche["client"] += 1
                statistiche["spettatori_max"] = max(statistiche["spettatori_max"],
                                                    len(spettatori))
            print(f"[+] client collegato ({len(spettatori)} attivi)")
            try:
                while True:
                    if coda:
                        pezzo = coda.pop(0)
                        # ogni pezzo va preceduto dalla sua lunghezza in esadecimale
                        # bytes non supportano %, quindi la lunghezza in
                        # esadecimale va costruita come stringa e codificata
                        self.wfile.write(f"{len(pezzo):X}\r\n".encode())
                        self.wfile.write(pezzo)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    else:
                        time.sleep(0.002)
            except Exception:
                pass
            finally:
                with blocco:
                    if coda in spettatori:
                        spettatori.remove(coda)
                print(f"[-] client scollegato ({len(spettatori)} attivi)")
            return

        if percorso == "/stato":
            with blocco:
                s = dict(statistiche)
            s.update({
                "attivo": bool(ffmpeg and ffmpeg.poll() is None),
                "spettatori": len(spettatori),
                "uscita": USCITA,
                "risoluzione": f"{LARGHEZZA}x{ALTEZZA}@{FPS}",
                "bitrate": BITRATE,
                "encoder": "h264_vaapi (hardware)",
                "sessione": AMBIENTE.get("HYPRLAND_INSTANCE_SIGNATURE", ""),
            })
            if s.get("dal"):
                s["attivo_da_s"] = round(time.time() - s["dal"])
            corpo = json.dumps(s, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return

        self.send_error(404)

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

# ─────────────────────── avvio ───────────────────────
def stato():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/stato", timeout=3) as r:
            print(r.read().decode())
    except Exception as e:
        print(f"nessun server in ascolto sulla porta {PORTA} ({e})")

def ferma():
    for nome in ("bc250-display.py", "wf-recorder"):
        subprocess.run(["pkill", "-f", nome])
    if os.path.exists(FIFO):
        os.remove(FIFO)
    print("fermato")

def main():
    if "--status" in sys.argv:
        return stato()
    if "--stop" in sys.argv:
        return ferma()

    print(f"bc250-display → {LARGHEZZA}x{ALTEZZA}@{FPS}  encoder h264_vaapi (hardware)")
    if not os.path.exists(HTML):
        print(f"[!] client.html non trovato: {HTML}")
    print("uscita virtuale:", "ok" if prepara_uscita() else "NON CREATA")

    avvia_catena()
    threading.Thread(target=leggi_e_distribuisci, daemon=True).start()
    threading.Thread(target=sorveglia, daemon=True).start()

    def chiudi(*a):
        for p in (ffmpeg, wfrecorder):
            if p:
                p.kill()
        subprocess.run(["pkill", "-x", "wf-recorder"], capture_output=True)
        if os.path.exists(FIFO):
            os.remove(FIFO)
        sys.exit(0)
    signal.signal(signal.SIGTERM, chiudi)
    signal.signal(signal.SIGINT, chiudi)

    print(f"in ascolto su http://0.0.0.0:{PORTA}/")
    print(f"sul tablet:  adb reverse tcp:{PORTA} tcp:{PORTA}  →  http://127.0.0.1:{PORTA}/")
    with Server(("0.0.0.0", PORTA), Gestore) as httpd:
        httpd.serve_forever()

if __name__ == "__main__":
    main()
