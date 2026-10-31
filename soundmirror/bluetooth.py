"""BlueZ D-Bus helpers for discovering, pairing and connecting audio devices."""

from __future__ import annotations

import dbus
from dbus.mainloop.glib import DBusGMainLoop

BLUEZ_SERVICE = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"

PROP_POWERED = "Powered"
PROP_DISCOVERING = "Discovering"
PROP_ALIAS = "Alias"
PROP_ADDRESS = "Address"
PROP_ICON = "Icon"
PROP_PAIRED = "Paired"
PROP_TRUSTED = "Trusted"
PROP_CONNECTED = "Connected"
PROP_UUIDS = "UUIDs"

AUDIO_UUIDS = {
    "0000110b-0000-1000-8000-00805f9b34fb",  # A2DP Audio Sink
    "0000110a-0000-1000-8000-00805f9b34fb",  # Audio Source
    "0000110d-0000-1000-8000-00805f9b34fb",  # Advanced Audio
    "00001108-0000-1000-8000-00805f9b34fb",  # Headset
    "00001112-0000-1000-8000-00805f9b34fb",  # Headset Audio Gateway
    "0000111e-0000-1000-8000-00805f9b34fb",  # Handsfree
    "0000111f-0000-1000-8000-00805f9b34fb",  # Handsfree Audio Gateway
}


class BluetoothError(Exception):
    pass


class BluetoothManager:
    def __init__(self) -> None:
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self._adapter_path: str | None = None
        self._adapter = None
        self._om = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, "/"), DBUS_OM_IFACE
        )
        self._props = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, "/"), PROPERTIES_IFACE
        )

    def _get(self, obj, iface: str, prop: str):
        return dbus.Interface(obj, PROPERTIES_IFACE).Get(iface, prop)

    def _set(self, obj, iface: str, prop: str, value) -> None:
        dbus.Interface(obj, PROPERTIES_IFACE).Set(iface, prop, value)

    # ------------------------------------------------------------------ setup

    def pick_default_adapter(self) -> str:
        objects = self._om.GetManagedObjects()
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces:
                adapter = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE, path), ADAPTER_IFACE
                )
                if self._get(adapter, ADAPTER_IFACE, PROP_POWERED):
                    self._adapter_path = path
                    self._adapter = adapter
                    return path
        # Fall back to first adapter even if unpowered, then power it on.
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces:
                adapter = dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE, path), ADAPTER_IFACE
                )
                try:
                    self._set(adapter, ADAPTER_IFACE, PROP_POWERED, True)
                except dbus.DBusException:
                    pass
                self._adapter_path = path
                self._adapter = adapter
                return path
        raise BluetoothError("No Bluetooth adapter found")

    def adapter_path(self) -> str:
        if not self._adapter_path:
            self.pick_default_adapter()
        assert self._adapter_path is not None
        return self._adapter_path

    def adapter(self):
        if not self._adapter:
            self.pick_default_adapter()
        assert self._adapter is not None
        return self._adapter

    def ensure_powered(self) -> None:
        try:
            self._set(self.adapter(), ADAPTER_IFACE, PROP_POWERED, True)
        except dbus.DBusException as exc:
            raise BluetoothError(f"Cannot power adapter: {exc}") from exc

    def is_powered(self) -> bool:
        adapter = self.adapter()
        return bool(self._get(adapter, ADAPTER_IFACE, PROP_POWERED))

    # ------------------------------------------------------------- discovery

    def start_discovery(self) -> None:
        try:
            self.adapter().StartDiscovery()
        except dbus.DBusException as exc:
            raise BluetoothError(f"Discovery failed: {exc}") from exc

    def stop_discovery(self) -> None:
        try:
            self.adapter().StopDiscovery()
        except dbus.DBusException:
            pass

    def audio_devices(self, connected_only: bool = True) -> list[dict]:
        """Return known audio devices (filtered to connected only by default)."""
        out: list[dict] = []
        objects = self._om.GetManagedObjects()
        adapter_path = self.adapter_path()
        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue
            dev = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE, path), DEVICE_IFACE
            )
            try:
                connected = bool(self._get(dev, DEVICE_IFACE, PROP_CONNECTED))
            except dbus.DBusException:
                continue

            if connected_only and not connected:
                continue

            uuids = [
                str(u).lower()
                for u in (self._get(dev, DEVICE_IFACE, PROP_UUIDS) or [])
            ]
            icon = str(self._get(dev, DEVICE_IFACE, PROP_ICON) or "").lower()

            is_audio = (
                any(
                    u in AUDIO_UUIDS
                    or "110b" in u
                    or "110a" in u
                    or "110d" in u
                    or "1108" in u
                    or "111e" in u
                    for u in uuids
                )
                or any(k in icon for k in ("audio", "headset", "headphone"))
            )
            if not is_audio:
                continue

            # Only show devices belonging to our adapter.
            if not path.startswith(adapter_path + "/"):
                continue

            out.append(
                {
                    "path": path,
                    "address": str(self._get(dev, DEVICE_IFACE, PROP_ADDRESS) or ""),
                    "alias": str(self._get(dev, DEVICE_IFACE, PROP_ALIAS) or "Unknown Device"),
                    "icon": icon,
                    "paired": bool(self._get(dev, DEVICE_IFACE, PROP_PAIRED)),
                    "trusted": bool(self._get(dev, DEVICE_IFACE, PROP_TRUSTED)),
                    "connected": connected,
                }
            )
        return out

    # ----------------------------------------------------------------- device

    def _device(self, path: str):
        return dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, path), DEVICE_IFACE
        )

    def pair(self, path: str) -> None:
        try:
            self._device(path).Pair()
        except dbus.DBusException as exc:
            raise BluetoothError(f"Pair failed: {exc}") from exc

    def trust(self, path: str) -> None:
        try:
            self._set(self._device(path), DEVICE_IFACE, PROP_TRUSTED, True)
        except dbus.DBusException as exc:
            raise BluetoothError(f"Trust failed: {exc}") from exc

    def connect(self, path: str) -> None:
        try:
            self._device(path).Connect()
        except dbus.DBusException as exc:
            raise BluetoothError(f"Connect failed: {exc}") from exc

    def disconnect(self, path: str) -> None:
        try:
            self._device(path).Disconnect()
        except dbus.DBusException as exc:
            raise BluetoothError(f"Disconnect failed: {exc}") from exc

    def remove(self, path: str) -> None:
        try:
            self.adapter().RemoveDevice(path)
        except dbus.DBusException as exc:
            raise BluetoothError(f"Remove failed: {exc}") from exc

    # -------------------------------------------------------------- property watch

    def add_property_watcher(self, callback) -> None:
        """Watch BlueZ signals for property changes and new/removed devices."""
        self._prop_callback = callback
        self.bus.add_signal_receiver(
            self._on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPERTIES_IFACE,
        )
        self.bus.add_signal_receiver(
            self._on_interfaces_added,
            signal_name="InterfacesAdded",
            dbus_interface=DBUS_OM_IFACE,
        )
        self.bus.add_signal_receiver(
            self._on_interfaces_removed,
            signal_name="InterfacesRemoved",
            dbus_interface=DBUS_OM_IFACE,
        )

    def _on_interfaces_added(self, path, interfaces) -> None:
        if self._prop_callback is not None and DEVICE_IFACE in interfaces:
            self._prop_callback(DEVICE_IFACE, {"path": str(path), "added": True})

    def _on_interfaces_removed(self, path, interfaces) -> None:
        if self._prop_callback is not None and DEVICE_IFACE in interfaces:
            self._prop_callback(DEVICE_IFACE, {"path": str(path), "removed": True})

    def _on_properties_changed(self, *args) -> None:
        if self._prop_callback is None or len(args) < 3:
            return
        interface, changed, _invalidated = args[-3:]
        if interface in (ADAPTER_IFACE, DEVICE_IFACE):
            self._prop_callback(interface, dict(changed or {}))
