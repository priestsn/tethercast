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

Measured on the real hardware by comparing **two screens directly**: a capture of the
host's output (`grim`, near-instantaneous) against a screenshot of the tablet. Because
both show the same colour clock, the clock's own drawing delay cancels out — and that
matters, because measuring against the system clock instead inflated every number by
about 0.35 s and once produced a physically impossible *negative* latency.

| Player configuration | Latency to the tablet |
|---|---|
| mpv defaults | **1.62 s** |
| this project's `mpv.conf` | **0.21 – 0.32 s** |

**Every measurement is checked for liveness first.** Compare two screenshots a few
seconds apart: if they are identical to the pixel, the screen is frozen and any "latency"
number is meaningless. That check is not paranoia — it caught two configurations that
looked fast and were simply showing a still frame.

Where the remaining time goes: roughly 100 ms in the capture/encode/transport chain and
130 ms in the player plus the tablet's own display pipeline. Getting below ~200 ms needs
the frames to stop making a round trip through the CPU — see *Known limits* below.

## Known limits

- **The capture path costs a CPU round trip.** The compositor hands over BGRA, the
  frames travel through a pipe (3.46 MB each, 207 MB/s at 60 fps), the CPU converts them
  to NV12 and they are uploaded back to the GPU. The two obvious ways out are both
  closed on this hardware: asking `wf-recorder` to encode with VA-API directly fails
  with `Unsupported format: bgra`, and moving the colour conversion onto the GPU with
  `hwupload,scale_vaapi=format=nv12` **segfaults** on a real capture.
- **Going lower means changing the architecture, not the settings**: either a virtual
  display the compositor renders into directly (`vkms`, `evdi`) instead of a screencopy,
  or a hardware HDMI capture dongle, which turns the tablet into an ordinary UVC monitor
  and takes the whole software chain out of the path.
- The tablet is **USB 2.0 by construction** (`bcdUSB 2.00`), so it stays at 480 Mbps
  whatever port you use. Not a bottleneck today — the stream is ~3 Mbps — but it is a
  ceiling.

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
- **`untimed=yes` freezes it too**, and it is documented as an option for *benchmarks*, not
  for watching. With it, the screen stopped on a fixed frame — and it still produced a
  beautiful "0.07 s", because that number was comparing an advancing host screen against a
  frozen tablet. **The most flattering measurement was the falsest.**
- **`vf=` in `mpv.conf` is not a valid test.** A `--vf=` on the command line *replaces* it, so
  the app's own options wipe it. Use `speed=0.25` to check whether the config is read.
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
