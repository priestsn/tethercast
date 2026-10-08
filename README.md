# tethercast

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

Measured on the real hardware by encoding the current time into a **colour** and reading
the average pixel value out of the tablet's framebuffer — no OCR, no guessing. The method's
own noise floor (checked against a direct capture, where latency is zero by definition) is
**0.03 s**.

| Player configuration | Latency to the tablet |
|---|---|
| mpv defaults | **1.62 s** |
| this project's `mpv.conf` | **~0.7 s** |

The capture chain itself is only **~0.2 s**. Almost everything else was the player
buffering a stream that arrives over a half-metre cable.

## What went wrong along the way

Kept here because these cost real hours:

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
- **`vf=` in `mpv.conf` is not a valid test.** A `--vf=` on the command line *replaces* it, so
  the app's own options wipe it. Use `speed=0.25` to check whether the config is read.
- **A colour cycle shorter than ~20 s aliases.** The reading is ambiguous by one full cycle;
  at 10 s the margin was ±5 s and samples came out nonsense (9 s of apparent spread).

## Requirements

- Linux with a Wayland wlroots compositor (Hyprland, Sway)
- An ffmpeg build with `h264_vaapi` and a working VA‑API driver
- `adb`, `wf-recorder`
- Android tablet with USB debugging **and root** (for the player config)
- `mpv-android` on the tablet

## License

MIT — see [LICENSE](LICENSE).
