"""PulseAudio/PipeWire sink helpers via pactl (no extra Python deps)."""

from __future__ import annotations

import re
import subprocess
from typing import Optional

COMBINED_SINK_NAME = "soundmirror-combined"


class AudioError(Exception):
    pass


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        raise AudioError(
            f"{' '.join(args)} failed: {exc.stderr.strip()}"
        ) from exc


def list_sinks() -> list[dict]:
    """Return a list of sink dicts parsed from `pactl list short sinks`."""
    out = _run(["pactl", "list", "short", "sinks"])
    sinks: list[dict] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sinks.append(
            {
                "index": parts[0],
                "name": parts[1],
                "driver": parts[2] if len(parts) > 2 else "",
                "state": parts[3] if len(parts) > 3 else "",
            }
        )
    return sinks


def sink_names() -> list[str]:
    return [s["name"] for s in list_sinks()]


def default_sink() -> Optional[str]:
    out = _run(["pactl", "get-default-sink"]).strip()
    return out or None


def set_default_sink(name: str) -> None:
    _run(["pactl", "set-default-sink", name])


def load_combine_sink(slave_a: str, slave_b: str) -> str:
    """Create a combined sink that mirrors to slave_a and slave_b.

    Returns the new sink name. Uses PulseAudio module-combine-sink.
    Note: PipeWire does not support module-combine-sink; on PipeWire systems
    this will fail and you should use a PipeWire combine node instead.
    """
    _run(
        [
            "pactl",
            "load-module",
            "module-combine-sink",
            f"slaves={slave_a},{slave_b}",
            f"sink_name={COMBINED_SINK_NAME}",
            "sink_properties=device.description=SoundMirror-Combined",
        ]
    )
    return COMBINED_SINK_NAME


def unload_combine_sink() -> None:
    out = _run(["pactl", "list", "short", "modules"])
    # Collect matching module indices, then unload in descending order so
    # unloading one module does not shift the indices of the rest.
    indices: list[int] = []
    for line in out.splitlines():
        if "module-combine-sink" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        # Only unload modules that expose SoundMirror's combined sink.
        if COMBINED_SINK_NAME not in line:
            continue
        try:
            indices.append(int(parts[0]))
        except ValueError:
            continue
    for index in sorted(indices, reverse=True):
        _run(["pactl", "unload-module", str(index)])


def is_combined_loaded() -> bool:
    return COMBINED_SINK_NAME in sink_names()


def find_sink_for_device(address: str) -> Optional[str]:
    """Find the pactl sink name corresponding to a Bluetooth device address."""
    if not address:
        return None
    mac_slug = address.replace(":", "_").lower()
    for name in sink_names():
        if mac_slug in name.lower():
            return name
    return None


def get_sink_volume(sink_name: str) -> int:
    """Return volume percentage (0-100) for a sink, or 100 on fallback."""
    try:
        out = _run(["pactl", "get-sink-volume", sink_name])
        match = re.search(r"(\d+)%", out)
        if match:
            return max(0, min(100, int(match.group(1))))
    except AudioError:
        pass
    return 100


def set_sink_volume(sink_name: str, volume_percent: int) -> None:
    """Set volume percentage (0-100) for a sink."""
    vol = max(0, min(100, int(volume_percent)))
    _run(["pactl", "set-sink-volume", sink_name, f"{vol}%"])


def get_sink_mute(sink_name: str) -> bool:
    """Return True if the sink is muted."""
    try:
        out = _run(["pactl", "get-sink-mute", sink_name])
        return "yes" in out.lower()
    except AudioError:
        return False


def set_sink_mute(sink_name: str, mute: bool) -> None:
    """Set mute state for a sink."""
    val = "1" if mute else "0"
    _run(["pactl", "set-sink-mute", sink_name, val])

