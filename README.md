# SoundMirror

Desktop app for Ubuntu that mirrors audio output to two Bluetooth headsets
(e.g. two pairs of AirPods) at the same time.

## Requirements

- Ubuntu (tested on 22.04/24.04)
- Python 3.10+
- `python3-gi`, `python3-dbus`, `libadwaita-1`
- PulseAudio (module-combine-sink) — PipeWire is not supported by this version

Install deps:

```bash
sudo apt install python3-gi python3-dbus libadwaita-1-0 gir1.2-adw-1 pulseaudio
```

## Setup & Run

1. Clone and enter the repository:
```bash
git clone <this-repo> soundmirror
cd soundmirror
```

2. Create virtual environment with system site packages (needed for `gi` and `dbus`):
```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
```

3. Run the app:
```bash
soundmirror
```

### (Optional) Run from anywhere without activating the venv

Symlink the executable to `~/.local/bin` so you can launch `soundmirror` from any terminal:

```bash
mkdir -p ~/.local/bin
ln -sf "$(pwd)/.venv/bin/soundmirror" ~/.local/bin/soundmirror
```

**What this command does:**
- `mkdir -p ~/.local/bin`: Ensures the `~/.local/bin` folder exists in your home directory (creating parent folders if necessary without throwing errors).
- `ln -sf <target> <link_name>`:
  - `ln`: Creates a link between files.
  - `-s` (symbolic): Creates a soft shortcut/symlink (pointing to the original file) rather than copying it.
  - `-f` (force): Overwrites any existing link with that name if one already exists.
- **Why it works without activating `.venv`:** The generated `soundmirror` script contains a shebang header (`#!/.../.venv/bin/python3`) that automatically tells Linux to execute it using the virtual environment's Python interpreter. As long as `~/.local/bin` is in your `$PATH`, you can simply run `soundmirror` from any directory.

## How it works

1. Connect both of your Bluetooth headsets (e.g. AirPods) using Ubuntu's native Bluetooth Settings.
2. Launch SoundMirror (`soundmirror`). Any connected headsets automatically show up in the list in real-time.
3. Toggle **Mirror output to both headsets**.

This creates a PulseAudio combined sink (`module-combine-sink`) that writes to
both A2DP sinks simultaneously and sets it as the default output.

## Caveats

- **Latency / drift:** The two headsets are independent clocks, so audio can
  drift out of sync over time. There is no perfect fix in userspace.
- **A2DP only:** Headset/HFP mode (microphone) uses a different profile and
  won't be mirrored this way.
- **PipeWire:** Ubuntu 24.04+ may use PipeWire, which does not support
  `module-combine-sink`. This build targets PulseAudio.
