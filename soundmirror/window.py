"""GTK4 main window for SoundMirror."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib  # noqa: E402

from .bluetooth import (  # noqa: E402
    BluetoothManager,
    BluetoothError,
    ADAPTER_IFACE,
    DEVICE_IFACE,
    PROP_CONNECTED,
    PROP_POWERED,
)
from .audio import (  # noqa: E402
    AudioError,
    list_sinks,
    sink_names,
    default_sink,
    set_default_sink,
    load_combine_sink,
    unload_combine_sink,
    is_combined_loaded,
    find_sink_for_device,
    get_sink_volume,
    set_sink_volume,
    get_sink_mute,
    set_sink_mute,
)


COMBINED_SINK_NAME = "soundmirror-combined"


class SoundMirrorWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title("SoundMirror")
        self.set_default_size(700, 520)

        self.bt = BluetoothManager()
        self._refresh_id: int | None = None
        self._combined_sink: str | None = None
        self._mirror_was_active: bool = False
        self._reenable_retries: int = 0
        self._reenable_id: int | None = None
        self._current_device_paths: set[str] = set()

        self._build_ui()
        self._init_bluetooth()
        self._refresh_devices()

        # Periodically check (every 2 seconds) for connected device changes
        GLib.timeout_add_seconds(2, self._poll_devices)

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        self.set_content(box)

        # Bluetooth status row with refresh button
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.status_label = Gtk.Label(label="Initializing Bluetooth…")
        self.status_label.set_xalign(0)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("title-4")
        status_box.append(self.status_label)

        self.btn_refresh = Gtk.Button(label="Refresh")
        self.btn_refresh.set_icon_name("view-refresh-symbolic")
        self.btn_refresh.connect("clicked", lambda _b: self._on_manual_refresh())
        status_box.append(self.btn_refresh)
        box.append(status_box)

        # Device list section
        list_label = Gtk.Label(label="Connected Bluetooth Audio Devices:")
        list_label.set_xalign(0)
        list_label.set_margin_top(6)
        list_label.add_css_class("heading")
        box.append(list_label)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.device_list = Gtk.ListBox()
        self.device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.device_list.add_css_class("boxed-list")
        scrolled.set_child(self.device_list)
        box.append(scrolled)

        # Mirror control
        mirror_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mirror_box.set_margin_top(12)
        self.switch_mirror = Gtk.Switch()
        self.switch_mirror.set_valign(Gtk.Align.CENTER)
        self.switch_mirror.connect("notify::active", self._on_mirror_toggled)

        mirror_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        mirror_info.set_hexpand(True)
        mirror_title = Gtk.Label(label="Mirror output to both headsets")
        mirror_title.set_xalign(0)
        mirror_title.add_css_class("heading")
        self.mirror_subtitle = Gtk.Label(
            label="Connect at least 2 Bluetooth headsets in Ubuntu Settings."
        )
        self.mirror_subtitle.set_xalign(0)
        self.mirror_subtitle.add_css_class("dim-label")
        mirror_info.append(mirror_title)
        mirror_info.append(self.mirror_subtitle)

        mirror_box.append(self.switch_mirror)
        mirror_box.append(mirror_info)
        box.append(mirror_box)

        # Log / info
        self.log_label = Gtk.Label(label="")
        self.log_label.set_xalign(0)
        self.log_label.set_wrap(True)
        self.log_label.set_margin_top(8)
        box.append(self.log_label)

    # ---------------------------------------------------------------- bt init

    def _init_bluetooth(self) -> None:
        # Start clean: never carry over a combined sink from a previous run.
        try:
            if is_combined_loaded():
                unload_combine_sink()
        except AudioError:
            pass
        try:
            path = self.bt.pick_default_adapter()
            powered = self.bt.is_powered()
            state = "ON" if powered else "OFF"
            self.status_label.set_text(
                f"Adapter: {path} — Bluetooth: {state}"
            )
            self.log("Bluetooth ready. Click Scan / Refresh.")
        except BluetoothError as exc:
            self.status_label.set_text("Bluetooth unavailable")
            self.log(str(exc), error=True)

        # React to Bluetooth power / connection changes so a Bluetooth
        # toggle-off/on does not leave the mirror in a broken state.
        try:
            self.bt.add_property_watcher(self._on_bt_property_changed)
        except BluetoothError as exc:
            self.log(f"Could not watch Bluetooth state: {exc}", error=True)

    def log(self, message: str, error: bool = False) -> None:
        prefix = "Error: " if error else ""
        self.log_label.set_text(prefix + message)
        if error:
            self.log_label.add_css_class("destructive-action")
        else:
            self.log_label.remove_css_class("destructive-action")

    # ---------------------------------------------------------------- actions

    def _on_manual_refresh(self) -> None:
        self._refresh_devices()
        self.log("Device list refreshed.")

    def _poll_devices(self) -> bool:
        """Poll periodically to pick up any devices connected externally."""
        try:
            devices = self.bt.audio_devices(connected_only=True)
            paths = {d["path"] for d in devices}
            if paths != self._current_device_paths:
                self._refresh_devices()
        except BluetoothError:
            pass
        return True

    def _refresh_devices(self) -> None:
        while True:
            child = self.device_list.get_first_child()
            if child is None:
                break
            self.device_list.remove(child)

        try:
            devices = self.bt.audio_devices(connected_only=True)
        except BluetoothError as exc:
            self.log(str(exc), error=True)
            return

        self._current_device_paths = {d["path"] for d in devices}

        count = len(devices)
        if count >= 2:
            self.mirror_subtitle.set_text(
                f"{count} audio devices connected. Ready to mirror."
            )
            self.switch_mirror.set_sensitive(True)
        elif count == 1:
            self.mirror_subtitle.set_text(
                f"1 connected ({devices[0]['alias']}). Connect 1 more headset."
            )
            self.switch_mirror.set_sensitive(False)
        else:
            self.mirror_subtitle.set_text(
                "No headsets connected. Connect 2 in Ubuntu Settings."
            )
            self.switch_mirror.set_sensitive(False)

        if not devices:
            empty_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=8
            )
            empty_box.set_margin_top(28)
            empty_box.set_margin_bottom(28)
            empty_label = Gtk.Label(
                label="No connected Bluetooth audio devices found.\n\n"
                "Connect your headsets using Ubuntu Bluetooth Settings,\n"
                "and they will appear here automatically."
            )
            empty_label.set_justify(Gtk.Justification.CENTER)
            empty_label.add_css_class("dim-label")
            empty_box.append(empty_label)
            self.device_list.append(empty_box)
            return

        for dev in devices:
            self._add_device_row(dev)

    def _add_device_row(self, dev: dict) -> None:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.set_margin_top(12)
        card.set_margin_bottom(12)
        card.set_margin_start(14)
        card.set_margin_end(14)

        # Header: Icon, Name, Address, Status
        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon = Gtk.Image.new_from_icon_name("audio-headphones-symbolic")
        icon.set_pixel_size(24)
        top_box.append(icon)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        name = Gtk.Label(label=dev["alias"])
        name.set_xalign(0)
        name.add_css_class("heading")
        addr = Gtk.Label(label=dev["address"])
        addr.set_xalign(0)
        addr.add_css_class("dim-label")
        info.append(name)
        info.append(addr)
        top_box.append(info)

        badge = Gtk.Label(label="Connected")
        badge.add_css_class("accent")
        badge.set_valign(Gtk.Align.CENTER)
        top_box.append(badge)
        card.append(top_box)

        # Volume Controls per device
        sink_name = find_sink_for_device(dev["address"])
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vol_box.set_margin_top(4)

        if sink_name:
            curr_vol = get_sink_volume(sink_name)
            is_muted = get_sink_mute(sink_name)

            btn_mute = Gtk.Button()
            mute_icon = (
                "audio-volume-muted-symbolic"
                if is_muted
                else "audio-volume-high-symbolic"
            )
            btn_mute.set_icon_name(mute_icon)
            btn_mute.set_valign(Gtk.Align.CENTER)
            btn_mute.add_css_class("flat")

            scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 0, 100, 1
            )
            scale.set_hexpand(True)
            scale.set_valign(Gtk.Align.CENTER)
            scale.set_draw_value(False)
            scale.set_value(curr_vol)

            lbl_percent = Gtk.Label(label=f"{curr_vol}%")
            lbl_percent.set_valign(Gtk.Align.CENTER)
            lbl_percent.set_width_chars(5)
            lbl_percent.set_xalign(1)

            def on_vol_changed(sc, sname=sink_name, b_mute=btn_mute, lbl=lbl_percent):
                val = int(sc.get_value())
                lbl.set_text(f"{val}%")
                try:
                    set_sink_volume(sname, val)
                    if val > 0 and get_sink_mute(sname):
                        set_sink_mute(sname, False)
                        b_mute.set_icon_name("audio-volume-high-symbolic")
                except AudioError:
                    pass

            scale.connect("value-changed", on_vol_changed)

            def on_mute_clicked(_btn, sname=sink_name, b_mute=btn_mute):
                try:
                    now_muted = not get_sink_mute(sname)
                    set_sink_mute(sname, now_muted)
                    b_mute.set_icon_name(
                        "audio-volume-muted-symbolic"
                        if now_muted
                        else "audio-volume-high-symbolic"
                    )
                except AudioError:
                    pass

            btn_mute.connect("clicked", on_mute_clicked)

            vol_box.append(btn_mute)
            vol_box.append(scale)
            vol_box.append(lbl_percent)
        else:
            sink_status = Gtk.Label(label="Audio stream initializing…")
            sink_status.add_css_class("dim-label")
            vol_box.append(sink_status)

        card.append(vol_box)
        row.set_child(card)
        row.dev_path = dev["path"]
        self.device_list.append(row)

    # ---------------------------------------------------------------- mirror

    def _on_mirror_toggled(self, switch, _pspec) -> None:
        if switch.get_active():
            self._enable_mirror()
        else:
            self._disable_mirror()

    def _choose_audio_sinks(self) -> tuple[str, str]:
        sinks = sink_names()
        candidates = [
            s
            for s in sinks
            if s != COMBINED_SINK_NAME
            and ("bluez" in s.lower() or "a2dp" in s.lower())
        ]
        if len(candidates) < 2:
            raise AudioError(
                f"Need two Bluetooth A2DP sinks; found: {sinks or 'none'}"
            )
        return candidates[0], candidates[1]

    def _enable_mirror(self) -> None:
        # Guard: never create more than one combined sink.
        if is_combined_loaded():
            self.log("Mirroring already active.")
            self.switch_mirror.set_active(True)
            return

        try:
            a, b = self._choose_audio_sinks()
        except AudioError as exc:
            self.log(str(exc), error=True)
            self.switch_mirror.set_active(False)
            return

        try:
            name = load_combine_sink(a, b)
            set_default_sink(name)
            self._combined_sink = name
            self.log(f"Mirroring to {a} + {b} (default sink: {name})")
        except AudioError as exc:
            self.log(str(exc), error=True)
            self.switch_mirror.set_active(False)

    def _disable_mirror(self) -> None:
        try:
            unload_combine_sink()
            sinks = sink_names()
            for s in sinks:
                if s != COMBINED_SINK_NAME:
                    set_default_sink(s)
                    break
            self._combined_sink = None
            self.log("Mirroring stopped.")
        except AudioError as exc:
            self.log(str(exc), error=True)

    # --------------------------------------------------- bt state change handling

    def _on_bt_property_changed(self, interface: str, changed: dict) -> None:
        if interface == ADAPTER_IFACE and PROP_POWERED in changed:
            powered = bool(changed[PROP_POWERED])
            if powered:
                self._on_bt_powered_on()
            else:
                self._on_bt_powered_off()
        elif interface == DEVICE_IFACE:
            self._refresh_devices()
            if changed.get(PROP_CONNECTED):
                self._schedule_reenable_mirror()

    def _on_bt_powered_off(self) -> None:
        self.status_label.set_text("Bluetooth: OFF")
        self.log("Bluetooth powered off.")
        # Remember whether mirror was active so we can restore it when bluetooth
        # comes back, then stop mirroring cleanly.
        self._mirror_was_active = bool(self.switch_mirror.get_active())
        if self.switch_mirror.get_active():
            self.switch_mirror.set_active(False)
        if self._reenable_id is not None:
            GLib.source_remove(self._reenable_id)
            self._reenable_id = None
            self._reenable_retries = 0

    def _on_bt_powered_on(self) -> None:
        self.status_label.set_text("Bluetooth: ON")
        self.log("Bluetooth powered on. Re-establishing mirror…")
        # Drop any stale combined sink left over from before the outage so the
        # mirror is rebuilt against the newly-available bluez sinks.
        try:
            if is_combined_loaded():
                unload_combine_sink()
        except AudioError:
            pass
        self._refresh_devices()
        self._schedule_reenable_mirror()

    def _schedule_reenable_mirror(self) -> None:
        if not self._mirror_was_active:
            return
        if self._reenable_id is not None:
            return  # already retrying
        self._reenable_retries = 0
        self._reenable_id = GLib.timeout_add_seconds(2, self._reenable_mirror_retry)

    def _reenable_mirror_retry(self) -> bool:
        """Retry re-enabling the mirror until two bluez sinks appear."""
        self._reenable_retries += 1
        if self._reenable_retries > 15:  # ~30 seconds
            self._reenable_id = None
            self._mirror_was_active = False
            self.log("Bluetooth back, but no two A2DP sinks found; toggle mirror manually.")
            return False
        try:
            sinks = sink_names()
            bluez = [
                s
                for s in sinks
                if s != COMBINED_SINK_NAME
                and ("bluez" in s.lower() or "a2dp" in s.lower())
            ]
            if len(bluez) >= 2:
                self.switch_mirror.set_active(True)
                self._reenable_id = None
                self._mirror_was_active = False
                self.log("Mirroring re-established after Bluetooth reconnect.")
                return False
        except AudioError:
            pass
        return True  # keep retrying

