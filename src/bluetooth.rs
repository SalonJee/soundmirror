use std::collections::HashMap;
use zbus::blocking::Connection;
use zbus::zvariant::{OwnedObjectPath, OwnedValue};

pub const BLUEZ_SERVICE: &str = "org.bluez";
pub const DBUS_OM_IFACE: &str = "org.freedesktop.DBus.ObjectManager";
pub const ADAPTER_IFACE: &str = "org.bluez.Adapter1";
pub const DEVICE_IFACE: &str = "org.bluez.Device1";

pub const AUDIO_UUIDS: &[&str] = &[
    "0000110b-0000-1000-8000-00805f9b34fb", // A2DP Audio Sink
    "0000110a-0000-1000-8000-00805f9b34fb", // Audio Source
    "0000110d-0000-1000-8000-00805f9b34fb", // Advanced Audio
    "00001108-0000-1000-8000-00805f9b34fb", // Headset
    "00001112-0000-1000-8000-00805f9b34fb", // Headset Audio Gateway
    "0000111e-0000-1000-8000-00805f9b34fb", // Handsfree
    "0000111f-0000-1000-8000-00805f9b34fb", // Handsfree Audio Gateway
];

#[derive(Debug, Clone)]
pub struct BluetoothDevice {
    pub path: String,
    pub address: String,
    pub alias: String,
    pub icon: String,
    pub connected: bool,
    pub paired: bool,
    pub trusted: bool,
}

pub struct BluetoothManager {
    conn: Connection,
    adapter_path: Option<String>,
}

type ManagedObjects = HashMap<OwnedObjectPath, HashMap<String, HashMap<String, OwnedValue>>>;

impl BluetoothManager {
    pub fn new() -> Result<Self, String> {
        let conn = Connection::system().map_err(|e| format!("Failed to connect to system D-Bus: {}", e))?;
        let mut mgr = Self {
            conn,
            adapter_path: None,
        };
        let _ = mgr.pick_default_adapter();
        Ok(mgr)
    }

    fn get_managed_objects(&self) -> Result<ManagedObjects, String> {
        let msg = self.conn
            .call_method(
                Some(BLUEZ_SERVICE),
                "/",
                Some(DBUS_OM_IFACE),
                "GetManagedObjects",
                &(),
            )
            .map_err(|e| format!("GetManagedObjects failed: {}", e))?;

        msg.body()
            .deserialize::<ManagedObjects>()
            .map_err(|e| format!("Failed to parse GetManagedObjects response: {}", e))
    }

    pub fn pick_default_adapter(&mut self) -> Result<String, String> {
        let objects = self.get_managed_objects()?;
        for (path, ifaces) in &objects {
            if let Some(adapter_props) = ifaces.get(ADAPTER_IFACE) {
                let powered = adapter_props
                    .get("Powered")
                    .and_then(|v| bool::try_from(v).ok())
                    .unwrap_or(false);
                if powered {
                    let p = path.as_str().to_string();
                    self.adapter_path = Some(p.clone());
                    return Ok(p);
                }
            }
        }

        // Fall back to first adapter found
        for (path, ifaces) in &objects {
            if ifaces.contains_key(ADAPTER_IFACE) {
                let p = path.as_str().to_string();
                self.adapter_path = Some(p.clone());
                return Ok(p);
            }
        }

        Err("No Bluetooth adapter found".to_string())
    }

    pub fn adapter_path(&mut self) -> Result<String, String> {
        if let Some(ref p) = self.adapter_path {
            return Ok(p.clone());
        }
        self.pick_default_adapter()
    }

    pub fn is_powered(&mut self) -> bool {
        let adapter = match self.adapter_path() {
            Ok(p) => p,
            Err(_) => return false,
        };

        let objects = match self.get_managed_objects() {
            Ok(o) => o,
            Err(_) => return false,
        };

        for (path, ifaces) in objects {
            if path.as_str() == adapter {
                if let Some(props) = ifaces.get(ADAPTER_IFACE) {
                    return props
                        .get("Powered")
                        .and_then(|v| bool::try_from(v).ok())
                        .unwrap_or(false);
                }
            }
        }
        false
    }

    pub fn audio_devices(&mut self, connected_only: bool) -> Result<Vec<BluetoothDevice>, String> {
        let adapter_path = self.adapter_path()?;
        let objects = self.get_managed_objects()?;
        let mut devices = Vec::new();

        for (path, ifaces) in objects {
            let path_str = path.as_str();
            if !path_str.starts_with(&format!("{}/", adapter_path)) {
                continue;
            }

            let props = match ifaces.get(DEVICE_IFACE) {
                Some(p) => p,
                None => continue,
            };

            let connected = props
                .get("Connected")
                .and_then(|v| bool::try_from(v).ok())
                .unwrap_or(false);

            if connected_only && !connected {
                continue;
            }

            let address = props
                .get("Address")
                .and_then(|v| <&str>::try_from(v).ok())
                .unwrap_or("")
                .to_string();

            let alias = props
                .get("Alias")
                .and_then(|v| <&str>::try_from(v).ok())
                .unwrap_or("Unknown Device")
                .to_string();

            let icon = props
                .get("Icon")
                .and_then(|v| <&str>::try_from(v).ok())
                .unwrap_or("")
                .to_lowercase();

            let paired = props
                .get("Paired")
                .and_then(|v| bool::try_from(v).ok())
                .unwrap_or(false);

            let trusted = props
                .get("Trusted")
                .and_then(|v| bool::try_from(v).ok())
                .unwrap_or(false);

            // Extract UUIDs
            let mut uuids = Vec::new();
            if let Some(val) = props.get("UUIDs") {
                if let Ok(arr) = <&zbus::zvariant::Array>::try_from(val) {
                    for item in arr.iter() {
                        if let Ok(s) = <&str>::try_from(item) {
                            uuids.push(s.to_lowercase());
                        }
                    }
                }
            }

            let is_audio = uuids.iter().any(|u| {
                AUDIO_UUIDS.iter().any(|&known| u == known)
                    || u.contains("110b")
                    || u.contains("110a")
                    || u.contains("110d")
                    || u.contains("1108")
                    || u.contains("111e")
            }) || icon.contains("audio")
                || icon.contains("headset")
                || icon.contains("headphone");

            if !is_audio {
                continue;
            }

            devices.push(BluetoothDevice {
                path: path_str.to_string(),
                address,
                alias,
                icon,
                connected,
                paired,
                trusted,
            });
        }

        Ok(devices)
    }
}
