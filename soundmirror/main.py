"""Entry point for the SoundMirror GTK4 application."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from .window import SoundMirrorWindow  # noqa: E402


class SoundMirrorApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.example.SoundMirror",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        win = self.props.active_window
        if win is None:
            win = SoundMirrorWindow(self)
        win.present()


def main() -> None:
    import sys

    app = SoundMirrorApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
