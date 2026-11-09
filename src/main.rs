pub mod audio;
pub mod bluetooth;
pub mod window;

use libadwaita::prelude::*;

fn main() {
    let app = libadwaita::Application::builder()
        .application_id("com.example.SoundMirror")
        .build();

    app.connect_activate(|app| {
        let win = window::build_window(app);
        win.present();
    });

    app.run();
}
