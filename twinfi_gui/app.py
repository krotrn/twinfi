"""twinfi-gtk: application bootstrap."""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from twinfi_cli import __version__  # noqa: E402

from .backend import TwinfiBackend  # noqa: E402
from .compat import ICONS_DIR, ensure_font_dpi, register_bundled_icons, show_about  # noqa: E402
from .helpers import (  # noqa: E402
    APP_ID,
    TRAY_ICONS,
    band_change,
    band_label,
    load_gui_prefs,
    tray_icons_installed,
    tray_state,
    tray_status,
)
from .tray import TrayIcon, svg_pixmaps  # noqa: E402
from .window import MissingTwinfiWindow, TwinfiWindow  # noqa: E402

TRAY_GRACE = 3  # seconds a --background start waits for a tray before showing the window


class AppTray:
    """The tray icon for one window: status as icon and tooltip, plus a menu."""

    def __init__(self, app: "TwinfiApp", window: TwinfiWindow):
        self.app, self.window = app, window
        self.hide_when_off = bool(load_gui_prefs().get("tray_hide_when_off"))
        # Pictures for trays that can't look up the icon by name, and the only
        # picture when the icons aren't installed in the system theme: the same
        # icons in a grey that reads on light and dark panels.
        self.pixmaps = {}
        for name in TRAY_ICONS:
            try:
                svg = (ICONS_DIR / "hicolor/symbolic/apps" / f"{name}.svg").read_text()
            except OSError:
                svg = ""
            self.pixmaps[name] = svg_pixmaps(svg.replace("#2e3436", "#bebebe").encode()) if svg else []
        self.icon = TrayIcon(
            "twinfi",
            "Hotspot (twinfi)",
            window.toggle_visible,
            self._on_menu,
            app.on_tray_change,
            use_icon_names=tray_icons_installed(),
        )
        window.tray = self
        self.update({}, False)

    @property
    def available(self) -> bool:
        return self.icon.available

    def update(self, data: dict, busy: bool) -> None:
        icon, title, body, items = tray_state(data, busy)
        status = tray_status(data, busy, self.hide_when_off)
        self.icon.update(icon, title, body, items, self.pixmaps[icon], status)

    def set_hide_when_off(self, hide: bool) -> None:
        """Let the panel hide the icon while the hotspot is off (applies at once)."""
        self.hide_when_off = hide
        self.window.update_tray()

    def _on_menu(self, key: str) -> None:
        window = self.window
        if key == "toggle":
            window.hotspot_page.toggle_hotspot()
        elif key == "share":
            window.present()
            window.share()
        elif key in ("devices", "settings"):
            window.show_page("clients" if key == "devices" else "settings")
            window.present()
        elif key.startswith("profile:"):
            name = key.split(":", 1)[1]
            window.run_privileged(lambda: window.backend.use_profile(name))
        elif key.startswith("band:"):
            changes = band_change(window.data.get("config") or {}, key.split(":", 1)[1])
            window.run_privileged(
                lambda: window.backend.set_config(changes, success=f"Band set to {band_label(changes['band'])}.")
            )
        elif key == "autostart":
            enabled = not (window.data.get("autostart") or {}).get("enabled")
            window.run_privileged(lambda: window.backend.set_autostart(enabled))
        elif key == "show":
            window.present()
        elif key == "quit":
            self.app.quit()

    def close(self) -> None:
        self.icon.close()


class TwinfiApp(Adw.Application):
    def __init__(self, backend: TwinfiBackend, background: bool = False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.backend = backend
        self.background = background  # start hidden in the tray (e.g. at login)
        self.tray = None
        self.connect("activate", self._on_activate)
        for name, callback, accels in (
            ("quit", lambda *_: self.quit(), ["<Control>q"]),
            ("about", lambda *_: show_about(self.get_active_window(), __version__, APP_ID), []),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        self.set_accels_for_action("win.refresh", ["<Control>r", "F5"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        register_bundled_icons(APP_ID)
        ensure_font_dpi()

    def do_shutdown(self):
        if self.tray is not None:
            self.tray.close()
        Adw.Application.do_shutdown(self)

    def _on_activate(self, app):
        window = self.get_active_window()
        if window is not None:
            window.present()
        elif not self.backend.available():
            MissingTwinfiWindow(app, self.backend.twinfi).present()
        else:
            window = TwinfiWindow(app, self.backend)
            self.tray = AppTray(self, window)
            if self.background:
                # Show the window after all if no tray turns up to hold the icon.
                GLib.timeout_add_seconds(TRAY_GRACE, lambda: self.on_tray_change(self.tray.available) and False)
            else:
                window.present()

    def on_tray_change(self, available: bool) -> None:
        """Never leave the app running with neither a window nor a tray icon."""
        window = self.tray.window if self.tray else None
        if not available and window is not None and not window.get_visible():
            window.present()


def main():
    background = "--background" in sys.argv[1:]
    raise SystemExit(TwinfiApp(TwinfiBackend(), background=background).run(sys.argv[:1]))
