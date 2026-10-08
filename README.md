# tethercast

<p align="center">
  <img src="logo.png" alt="tethercast" width="180">
</p>

**Turn an Android tablet into a second monitor for a Linux machine — over a USB cable, with no network at all.**

No Wi‑Fi, no internet, no router. Just the cable.

```
┌────────────────┐   USB 2.0    ┌─────────────────┐
│  Linux box     │──────────────│  Android tablet │
│  (BC-250)      │  adb reverse │  (mpv-android)  │
└────────────────┘              └─────────────────┘
   wf-recorder → ffmpeg h264_vaapi → MPEG-TS → HTTP :8080
```

## Why this exists

Most "tablet as second display" tools assume a network. If you are somewhere without
internet — a couch, a train, a garage — they are useless. This one only needs the cable
you already have to charge the tablet.

It was built for an AMD BC‑250 board (a console APU with a **custom VA‑API driver** that
only ffmpeg and Sunshine know how to use) driving a Lenovo tablet with a vanilla
TrebleDroid GSI.

## How it works

| Stage | What | Notes |
|---|---|---|
| Capture | `wf-recorder` on a dedicated virtual output | wlroots screencopy, DMA-BUF, `-D` damage tracking |
| Encode | `ffmpeg` + `h264_vaapi` | **hardware** encoder on the AMD APU, `rc_mode CQP` |
| Transport | MPEG-TS over HTTP, `Transfer-Encoding: chunked` | one HTTP stream, no player state |
| Bridge | `adb reverse tcp:8080 tcp:8080` | rides inside the USB cable, needs no network |
| Client | **mpv-android** | a native app — no browser involved |

## Install

On the Linux side (`~/bc250-display/`):

```bash
# 1. the capture binary
pacman -S wf-recorder        # or your distro's equivalent

# 2. the two services
cp tethercast.service tablet-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tethercast.service tablet-watch.service
```

Then plug the tablet in. `tablet-watch` opens the USB bridge, launches the player, and
**relaunches it if it dies** — so the screen comes back by itself.

## Configuration

The player reads its config from its **internal** app directory, which needs root:

```bash
adb push mpv.conf /sdcard/mpv.conf
adb shell su -c "cp /sdcard/mpv.conf /data/data/is.xyz.mpv/files/mpv.conf"
adb shell su -c "chown 10237:10237 /data/data/is.xyz.mpv/files/mpv.conf"
adb shell su -c "chmod 600 /data/data/is.xyz.mpv/files/mpv.conf"
adb shell su -c "restorecon /data/data/is.xyz.mpv/files/mpv.conf"
```

All **four** steps matter. Miss the last one and SELinux blocks the app from reading a
file it owns — the config silently does nothing.

## Measured latency

**The project ships its own latency meter** (`strumenti/`): two small windows in a
corner of the screen, a colour strip and a number. They are part of the stream, so you
see the real figure on the tablet while you use it — green under 100 ms, amber under 200,
red above.

The method compares **two screens**, never the system clock against a colour:

```
1. grim -o <output>      capture the host screen   (~0.28 s, NOT instantaneous)
2. adb exec-out screencap -p > tablet.png          (~0.4 s)
3. the colour strip is in both: the difference is the latency
```

**Both captures are timed at their midpoints and the interval is subtracted**, because
they are not simultaneous. Skipping that step was the worst bug in this whole project:
it makes the meter report `Δ − L` instead of `L`, so a *larger* latency reads as a
*smaller* number. It displayed a comfortable 160 ms while the truth was ~500 ms.

The method is validated against a case whose answer is known: two captures of the *same*
screen must yield zero.

| | |
|---|---|
| two captures of the same screen (true latency 0) | **−0.005 s**, spread 0.058 s |
| host screen → tablet screen | **~0.5 – 0.6 s** |

Every measurement also checks that the image is **alive** first. Two screenshots a few
seconds apart; if they are identical to the pixel the screen is frozen and any latency
number is meaningless.

## What it would take to go much lower

**10–20 ms is not reachable, and the reason is arithmetic, not effort.** One frame at
60 Hz lasts 16.7 ms; the target is *less than one frame*. The signal must be captured,
converted, encoded, transported, decoded, composited and lit — each stage costs at least
a frame, and the tablet's own compositor plus panel are 30–60 ms before this project does
anything at all.

Realistic floors:

| approach | realistic latency |
|---|---|
| this software chain, tuned | **~0.5 s** (measured) |
| same chain with a virtual display instead of a screencopy | ~0.15 – 0.25 s |
| hardware HDMI capture dongle (tablet becomes a UVC monitor) | ~0.06 – 0.10 s |
| a direct display link (DisplayPort / DisplayLink) | ~0.01 – 0.03 s |

The last row is what actually reaches those numbers — and it is not streaming at all. It
is a display connection, with no capture, no codec and no player in the path.

### The two shortcuts out of the CPU round trip are both closed

The capture path makes the frames travel: compositor gives BGRA → through a pipe
(3.46 MB each, 207 MB/s at 60 fps) → the **CPU** converts to NV12 → uploaded back to the
GPU. Both obvious ways out fail on this hardware:

- `wf-recorder -c h264_vaapi` (encode directly, zero copies) →
  `[AVHWFramesContext] Unsupported format: bgra`. The custom driver refuses BGRA.
- `-vf "hwupload,scale_vaapi=format=nv12"` (convert on the GPU) works on synthetic input
  and **segfaults** on a real capture.

## What went wrong along the way

Kept here because these cost real hours:

- **A measurement error that looks like an improvement is the most dangerous kind.** The
  meter compared captures 0.67 s apart as if they were simultaneous, so it reported
  `Δ − L`. Bigger latency produced a smaller reading. Every number in this file before the
  meter existed was affected.
- **`screencopy` without `-D` stops dead.** Without damage tracking, wf-recorder only asks the
  compositor for a frame when something changes. On a fresh virtual output nothing ever
  changes, so it delivers exactly 262144 bytes and waits forever.
- **Only MPEG-TS streams.** MP4 and Matroska hold back ~1 KB of header and look frozen.
- **`-muxdelay 0` on ffmpeg does nothing here.** For MPEG-TS the default is 0.7 s and it looks
  like the obvious culprit. Measured before/after: identical. It was not that.
- **`stdout.read(N)` in Python waits for N bytes.** Reading a pipe in 64 KB blocks held 187 ms
  of stream hostage on every iteration. `os.read()` returns as soon as anything arrives.
- **`video-sync=desync` freezes the image.** Three screenshots identical to the pixel while
  data kept flowing. A "fast" configuration that freezes is worse than a slow one.
- **`untimed=yes` freezes it too**, and it is documented as an option for *benchmarks*, not
  for watching. It produced a beautiful "0.07 s" — comparing an advancing host screen
  against a frozen tablet. **The most flattering measurement was the falsest.**
- **`vf=` in `mpv.conf` is not a valid test.** A `--vf=` on the command line *replaces* it, so
  the app's own options wipe it. Use `speed=0.25` to check whether the config is read.
- **`hyprctl reload` does not re-run a Lua config**, so window rules written to the file
  apply only on the next session start. The window dispatchers (`hl.dsp.window.float`,
  `.resize`, `.move`) do work at runtime — but only on the *active* window, so they must
  run immediately after the window opens. The path is `hl.dsp.window.move`, not
  `hl.window.move`.
- **`hyprctl` reports positions in logical units**, but captured pixels are logical × scale.
  With scale 1.25 the meter sampled 150 px too high, found the desktop and measured noise.
- **A colour cycle shorter than ~20 s aliases.** The reading is ambiguous by one full cycle;
  at 10 s the margin was ±5 s and samples came out nonsense (9 s of apparent spread).
- **Bound the per-viewer queue in BYTES, not chunks.** Chunks from ffmpeg are ~4 KB, not the
  64 KB the read asks for, so a "3 chunks" cap became 12 KB — about 35 ms — and fired
  constantly. Measured: over 2000 chunks discarded, a mangled stream, and a player that
  fell behind. A cap that tight makes latency *worse*.
- **`grim` needs `HYPRLAND_INSTANCE_SIGNATURE` and `WAYLAND_DISPLAY`**, which a plain SSH
  session does not have. Without them it fails silently and writes no file at all.
- **Start the test clock with `systemd-run --user`, not `nohup … &`.** Launched from an SSH
  session it dies when the session ends, the screen goes still, and the measurement becomes
  garbage that is easy to blame on the player.

## Requirements

- Linux with a Wayland wlroots compositor (Hyprland, Sway)
- An ffmpeg build with `h264_vaapi` and a working VA‑API driver
- `adb`, `wf-recorder`
- Android tablet with USB debugging **and root** (for the player config)
- `mpv-android` on the tablet

## License

MIT — see [LICENSE](LICENSE).
