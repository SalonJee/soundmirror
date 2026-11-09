use std::cell::RefCell;
use std::collections::HashSet;
use std::rc::Rc;
use std::time::Duration;

use gtk4::prelude::*;
use libadwaita as adw;
use libadwaita::prelude::*;

use crate::audio;
use crate::bluetooth::{BluetoothDevice, BluetoothManager};

pub struct WindowState {
    pub bt: BluetoothManager,
    pub current_paths: HashSet<String>,
    pub status_label: gtk4::Label,
    pub mirror_subtitle: gtk4::Label,
    pub switch_mirror: gtk4::Switch,
    pub device_list: gtk4::ListBox,
    pub log_label: gtk4::Label,
    pub combined_sink: Option<String>,
}

impl WindowState {
    pub fn log(&self, msg: &str, is_error: bool) {
        let prefix = if is_error { "Error: " } else { "" };
        self.log_label.set_text(&format!("{}{}", prefix, msg));
        if is_error {
            self.log_label.add_css_class("destructive-action");
        } else {
            self.log_label.remove_css_class("destructive-action");
        }
    }

    pub fn update_adapter_status(&mut self) {
        match self.bt.adapter_path() {
            Ok(path) => {
                let powered = self.bt.is_powered();
                let state_str = if powered { "ON" } else { "OFF" };
                self.status_label
                    .set_text(&format!("Adapter: {} — Bluetooth: {}", path, state_str));
            }
            Err(e) => {
                self.status_label.set_text("Bluetooth unavailable");
                self.log(&e, true);
            }
        }
    }

    pub fn refresh_devices(&mut self) {
        // Clear current list items
        while let Some(child) = self.device_list.first_child() {
            self.device_list.remove(&child);
        }

        let devices = match self.bt.audio_devices(true) {
            Ok(devs) => devs,
            Err(err) => {
                self.log(&err, true);
                return;
            }
        };

        self.current_paths = devices.iter().map(|d| d.path.clone()).collect();
        let count = devices.len();

        if count >= 2 {
            self.mirror_subtitle
                .set_text(&format!("{} audio devices connected. Ready to mirror.", count));
            self.switch_mirror.set_sensitive(true);
        } else if count == 1 {
            self.mirror_subtitle.set_text(&format!(
                "1 connected ({}). Connect 1 more headset.",
                devices[0].alias
            ));
            self.switch_mirror.set_sensitive(false);
        } else {
            self.mirror_subtitle
                .set_text("No headsets connected. Connect 2 in Ubuntu Settings.");
            self.switch_mirror.set_sensitive(false);
        }

        if devices.is_empty() {
            let empty_box = gtk4::Box::new(gtk4::Orientation::Vertical, 8);
            empty_box.set_margin_top(28);
            empty_box.set_margin_bottom(28);

            let empty_label = gtk4::Label::new(Some(
                "No connected Bluetooth audio devices found.\n\nConnect your headsets using Ubuntu Bluetooth Settings,\nand they will appear here automatically.",
            ));
            empty_label.set_justify(gtk4::Justification::Center);
            empty_label.add_css_class("dim-label");
            empty_box.append(&empty_label);

            self.device_list.append(&empty_box);
            return;
        }

        for dev in devices {
            self.add_device_row(&dev);
        }
    }

    fn add_device_row(&self, dev: &BluetoothDevice) {
        let row = gtk4::ListBoxRow::new();
        row.set_activatable(false);

        let card = gtk4::Box::new(gtk4::Orientation::Vertical, 8);
        card.set_margin_top(12);
        card.set_margin_bottom(12);
        card.set_margin_start(14);
        card.set_margin_end(14);

        // Header: Icon, Name, Address, Status
        let top_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 12);

        let icon = gtk4::Image::from_icon_name("audio-headphones-symbolic");
        icon.set_pixel_size(24);
        top_box.append(&icon);

        let info = gtk4::Box::new(gtk4::Orientation::Vertical, 2);
        info.set_hexpand(true);

        let name = gtk4::Label::new(Some(&dev.alias));
        name.set_xalign(0.0);
        name.add_css_class("heading");

        let addr = gtk4::Label::new(Some(&dev.address));
        addr.set_xalign(0.0);
        addr.add_css_class("dim-label");

        info.append(&name);
        info.append(&addr);
        top_box.append(&info);

        let badge = gtk4::Label::new(Some("Connected"));
        badge.add_css_class("accent");
        badge.set_valign(gtk4::Align::Center);
        top_box.append(&badge);

        card.append(&top_box);

        // Volume controls per device
        let vol_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 10);
        vol_box.set_margin_top(4);

        if let Some(sink_name) = audio::find_sink_for_device(&dev.address) {
            let curr_vol = audio::get_sink_volume(&sink_name);
            let is_muted = audio::get_sink_mute(&sink_name);

            let btn_mute = gtk4::Button::new();
            let mute_icon = if is_muted {
                "audio-volume-muted-symbolic"
            } else {
                "audio-volume-high-symbolic"
            };
            btn_mute.set_icon_name(mute_icon);
            btn_mute.set_valign(gtk4::Align::Center);
            btn_mute.add_css_class("flat");

            let scale = gtk4::Scale::with_range(gtk4::Orientation::Horizontal, 0.0, 100.0, 1.0);
            scale.set_hexpand(true);
            scale.set_valign(gtk4::Align::Center);
            scale.set_draw_value(false);
            scale.set_value(curr_vol as f64);

            let lbl_percent = gtk4::Label::new(Some(&format!("{}%", curr_vol)));
            lbl_percent.set_valign(gtk4::Align::Center);
            lbl_percent.set_width_chars(5);
            lbl_percent.set_xalign(1.0);

            // Handlers
            let sname_clone = sink_name.clone();
            let btn_mute_clone = btn_mute.clone();
            let lbl_clone = lbl_percent.clone();

            scale.connect_value_changed(move |sc| {
                let val = sc.value() as u32;
                lbl_clone.set_text(&format!("{}%", val));
                let _ = audio::set_sink_volume(&sname_clone, val);
                if val > 0 && audio::get_sink_mute(&sname_clone) {
                    let _ = audio::set_sink_mute(&sname_clone, false);
                    btn_mute_clone.set_icon_name("audio-volume-high-symbolic");
                }
            });

            let sname_mute = sink_name.clone();
            let btn_mute_for_click = btn_mute.clone();

            btn_mute.connect_clicked(move |_| {
                let now_muted = !audio::get_sink_mute(&sname_mute);
                let _ = audio::set_sink_mute(&sname_mute, now_muted);
                let new_icon = if now_muted {
                    "audio-volume-muted-symbolic"
                } else {
                    "audio-volume-high-symbolic"
                };
                btn_mute_for_click.set_icon_name(new_icon);
            });

            vol_box.append(&btn_mute);
            vol_box.append(&scale);
            vol_box.append(&lbl_percent);
        } else {
            let sink_status = gtk4::Label::new(Some("Audio stream initializing…"));
            sink_status.add_css_class("dim-label");
            vol_box.append(&sink_status);
        }

        card.append(&vol_box);
        row.set_child(Some(&card));
        self.device_list.append(&row);
    }

    pub fn enable_mirror(&mut self) {
        if audio::is_combined_loaded() {
            self.log("Mirroring already active.", false);
            self.switch_mirror.set_active(true);
            return;
        }

        let sinks = audio::sink_names();
        let candidates: Vec<String> = sinks
            .into_iter()
            .filter(|s| {
                s != audio::COMBINED_SINK_NAME
                    && (s.to_lowercase().contains("bluez") || s.to_lowercase().contains("a2dp"))
            })
            .collect();

        if candidates.len() < 2 {
            self.log("Need two Bluetooth A2DP sinks to mirror.", true);
            self.switch_mirror.set_active(false);
            return;
        }

        let a = &candidates[0];
        let b = &candidates[1];

        match audio::load_combine_sink(a, b) {
            Ok(name) => {
                let _ = audio::set_default_sink(&name);
                self.combined_sink = Some(name.clone());
                self.log(
                    &format!("Mirroring to {} + {} (default sink: {})", a, b, name),
                    false,
                );
            }
            Err(e) => {
                self.log(&e, true);
                self.switch_mirror.set_active(false);
            }
        }
    }

    pub fn disable_mirror(&mut self) {
        match audio::unload_combine_sink() {
            Ok(_) => {
                let sinks = audio::sink_names();
                for s in sinks {
                    if s != audio::COMBINED_SINK_NAME {
                        let _ = audio::set_default_sink(&s);
                        break;
                    }
                }
                self.combined_sink = None;
                self.log("Mirroring stopped.", false);
            }
            Err(e) => {
                self.log(&e, true);
            }
        }
    }
}

pub fn build_window(app: &adw::Application) -> adw::ApplicationWindow {
    let window = adw::ApplicationWindow::builder()
        .application(app)
        .title("SoundMirror")
        .default_width(700)
        .default_height(520)
        .build();

    let root_box = gtk4::Box::new(gtk4::Orientation::Vertical, 12);
    root_box.set_margin_top(18);
    root_box.set_margin_bottom(18);
    root_box.set_margin_start(18);
    root_box.set_margin_end(18);
    window.set_content(Some(&root_box));

    // Top status bar
    let status_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 12);
    let status_label = gtk4::Label::new(Some("Initializing Bluetooth…"));
    status_label.set_xalign(0.0);
    status_label.set_hexpand(true);
    status_label.add_css_class("title-4");
    status_box.append(&status_label);

    let btn_refresh = gtk4::Button::builder()
        .label("Refresh")
        .icon_name("view-refresh-symbolic")
        .build();
    status_box.append(&btn_refresh);
    root_box.append(&status_box);

    // List header
    let list_label = gtk4::Label::new(Some("Connected Bluetooth Audio Devices:"));
    list_label.set_xalign(0.0);
    list_label.set_margin_top(6);
    list_label.add_css_class("heading");
    root_box.append(&list_label);

    // ScrolledWindow & ListBox
    let scrolled = gtk4::ScrolledWindow::builder()
        .vexpand(true)
        .hscrollbar_policy(gtk4::PolicyType::Never)
        .vscrollbar_policy(gtk4::PolicyType::Automatic)
        .build();

    let device_list = gtk4::ListBox::new();
    device_list.set_selection_mode(gtk4::SelectionMode::None);
    device_list.add_css_class("boxed-list");
    scrolled.set_child(Some(&device_list));
    root_box.append(&scrolled);

    // Mirror control
    let mirror_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 12);
    mirror_box.set_margin_top(12);

    let switch_mirror = gtk4::Switch::new();
    switch_mirror.set_valign(gtk4::Align::Center);

    let mirror_info = gtk4::Box::new(gtk4::Orientation::Vertical, 2);
    mirror_info.set_hexpand(true);

    let mirror_title = gtk4::Label::new(Some("Mirror output to both headsets"));
    mirror_title.set_xalign(0.0);
    mirror_title.add_css_class("heading");

    let mirror_subtitle =
        gtk4::Label::new(Some("Connect at least 2 Bluetooth headsets in Ubuntu Settings."));
    mirror_subtitle.set_xalign(0.0);
    mirror_subtitle.add_css_class("dim-label");

    mirror_info.append(&mirror_title);
    mirror_info.append(&mirror_subtitle);

    mirror_box.append(&switch_mirror);
    mirror_box.append(&mirror_info);
    root_box.append(&mirror_box);

    // Log label
    let log_label = gtk4::Label::new(Some(""));
    log_label.set_xalign(0.0);
    log_label.set_wrap(true);
    log_label.set_margin_top(8);
    root_box.append(&log_label);

    // Initialize BluetoothManager
    let bt_manager = BluetoothManager::new().expect("Failed to initialize Bluetooth manager");

    let state = Rc::new(RefCell::new(WindowState {
        bt: bt_manager,
        current_paths: HashSet::new(),
        status_label,
        mirror_subtitle,
        switch_mirror: switch_mirror.clone(),
        device_list,
        log_label,
        combined_sink: None,
    }));

    // Clean up any stale combined sinks from previous runs
    let _ = audio::unload_combine_sink();

    // Initial load
    state.borrow_mut().update_adapter_status();
    state.borrow_mut().refresh_devices();

    // Refresh button event
    let state_refresh = Rc::clone(&state);
    btn_refresh.connect_clicked(move |_| {
        state_refresh.borrow_mut().update_adapter_status();
        state_refresh.borrow_mut().refresh_devices();
        state_refresh.borrow().log("Device list refreshed.", false);
    });

    // Mirror toggle event
    let state_mirror = Rc::clone(&state);
    switch_mirror.connect_active_notify(move |sw| {
        if sw.is_active() {
            state_mirror.borrow_mut().enable_mirror();
        } else {
            state_mirror.borrow_mut().disable_mirror();
        }
    });

    // Periodic polling for connected devices (every 2 seconds)
    let state_poll = Rc::clone(&state);
    glib::timeout_add_local(Duration::from_secs(2), move || {
        let mut s = state_poll.borrow_mut();
        if let Ok(devs) = s.bt.audio_devices(true) {
            let new_paths: HashSet<String> = devs.into_iter().map(|d| d.path).collect();
            if new_paths != s.current_paths {
                s.refresh_devices();
            }
        }
        glib::ControlFlow::Continue
    });

    window
}
