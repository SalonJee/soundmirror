use std::process::Command;
use regex::Regex;

pub const COMBINED_SINK_NAME: &str = "soundmirror-combined";

#[derive(Debug, Clone)]
pub struct SinkInfo {
    pub index: String,
    pub name: String,
    pub driver: String,
    pub state: String,
}

fn run_pactl(args: &[&str]) -> Result<String, String> {
    let output = Command::new("pactl")
        .args(args)
        .output()
        .map_err(|e| format!("Failed to execute pactl: {}", e))?;

    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(format!("pactl {:?} failed: {}", args, err.trim()));
    }

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

pub fn list_sinks() -> Vec<SinkInfo> {
    let mut sinks = Vec::new();
    let out = match run_pactl(&["list", "short", "sinks"]) {
        Ok(o) => o,
        Err(_) => return sinks,
    };

    for line in out.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() >= 2 {
            sinks.push(SinkInfo {
                index: parts[0].to_string(),
                name: parts[1].to_string(),
                driver: parts.get(2).unwrap_or(&"").to_string(),
                state: parts.get(3).unwrap_or(&"").to_string(),
            });
        }
    }
    sinks
}

pub fn sink_names() -> Vec<String> {
    list_sinks().into_iter().map(|s| s.name).collect()
}

pub fn default_sink() -> Option<String> {
    run_pactl(&["get-default-sink"])
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

pub fn set_default_sink(name: &str) -> Result<(), String> {
    run_pactl(&["set-default-sink", name]).map(|_| ())
}

pub fn find_sink_for_device(address: &str) -> Option<String> {
    if address.is_empty() {
        return None;
    }
    let mac_slug = address.replace(':', "_").to_lowercase();
    for name in sink_names() {
        if name.to_lowercase().contains(&mac_slug) {
            return Some(name);
        }
    }
    None
}

pub fn get_sink_volume(sink_name: &str) -> u32 {
    if let Ok(out) = run_pactl(&["get-sink-volume", sink_name]) {
        let re = Regex::new(r"(\d+)%").unwrap();
        if let Some(caps) = re.captures(&out) {
            if let Some(m) = caps.get(1) {
                if let Ok(val) = m.as_str().parse::<u32>() {
                    return val.min(100);
                }
            }
        }
    }
    100
}

pub fn set_sink_volume(sink_name: &str, volume_percent: u32) -> Result<(), String> {
    let vol = volume_percent.min(100);
    let vol_str = format!("{}%", vol);
    run_pactl(&["set-sink-volume", sink_name, &vol_str]).map(|_| ())
}

pub fn get_sink_mute(sink_name: &str) -> bool {
    if let Ok(out) = run_pactl(&["get-sink-mute", sink_name]) {
        return out.to_lowercase().contains("yes");
    }
    false
}

pub fn set_sink_mute(sink_name: &str, mute: bool) -> Result<(), String> {
    let val = if mute { "1" } else { "0" };
    run_pactl(&["set-sink-mute", sink_name, val]).map(|_| ())
}

pub fn load_combine_sink(slave_a: &str, slave_b: &str) -> Result<String, String> {
    let slaves_arg = format!("slaves={},{}", slave_a, slave_b);
    let name_arg = format!("sink_name={}", COMBINED_SINK_NAME);
    let desc_arg = "sink_properties=device.description=SoundMirror-Combined";

    run_pactl(&[
        "load-module",
        "module-combine-sink",
        &slaves_arg,
        &name_arg,
        desc_arg,
    ])?;

    Ok(COMBINED_SINK_NAME.to_string())
}

pub fn unload_combine_sink() -> Result<(), String> {
    let out = run_pactl(&["list", "short", "modules"]).unwrap_or_default();
    let mut indices: Vec<u32> = Vec::new();

    for line in out.lines() {
        if line.contains("module-combine-sink") && line.contains(COMBINED_SINK_NAME) {
            let parts: Vec<&str> = line.split('\t').collect();
            if let Some(idx_str) = parts.first() {
                if let Ok(idx) = idx_str.parse::<u32>() {
                    indices.push(idx);
                }
            }
        }
    }

    // Unload in descending order
    indices.sort_by(|a, b| b.cmp(a));
    for idx in indices {
        let _ = run_pactl(&["unload-module", &idx.to_string()]);
    }

    Ok(())
}

pub fn is_combined_loaded() -> bool {
    sink_names().iter().any(|name| name == COMBINED_SINK_NAME)
}
