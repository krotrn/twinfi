#!/usr/bin/env python3
"""Headless GUI smoke test and screenshot tool.

Builds twinfi-gtk in several states against a fake backend on a Broadway
display (no desktop session needed), exercises the main interactions, and
saves a PNG of every view. Exits non-zero on any exception; run with
G_DEBUG=fatal-criticals to also fail on GTK criticals (CI does).

    python3 scripts/gui_smoke.py [OUTPUT_DIR]        # default: ./gui-screenshots

Needs PyGObject, GTK 4, libadwaita and a headless display: gtk4-broadwayd
(Debian 12+/Ubuntu 24.04+: libgtk-4-bin, Arch: gtk4, Fedora: gtk4) or, where
GTK was built without Broadway (Ubuntu 22.04), Xvfb.

Screenshots need PyGObject >= 3.44; on older bindings the test still builds
and exercises every view but skips the PNGs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# A per-process display number avoids clashing with a leftover server.
DISPLAY = os.environ.get("BROADWAY_DISPLAY", f":{40 + os.getpid() % 50}")


def start_display():
    """Start a headless display server and point GDK at it."""
    broadwayd = shutil.which("gtk4-broadwayd") or shutil.which("broadwayd")
    if broadwayd:
        proc = subprocess.Popen([broadwayd, DISPLAY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ.update(GDK_BACKEND="broadway", BROADWAY_DISPLAY=DISPLAY)
    elif shutil.which("Xvfb"):
        proc = subprocess.Popen(
            ["Xvfb", DISPLAY, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ.update(GDK_BACKEND="x11", DISPLAY=DISPLAY, GSK_RENDERER="cairo")
    else:
        sys.exit("Need gtk4-broadwayd or Xvfb for a headless display.")
    time.sleep(1.5)
    return proc


DISPLAY_SERVER = start_display()
SCREENSHOTS = {"enabled": True}

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from twinfi_gui import compat  # noqa: E402

# PyGObject < 3.44 can't return GskRenderNode from Gtk.Snapshot.to_node()
# (3.42.1 even emits a GLib critical), so only the screenshots are skipped there.
if gi.version_info < (3, 44, 0):
    print(f"note: PyGObject {gi.__version__} is too old for screenshots; building views only")
    SCREENSHOTS["enabled"] = False
from twinfi_gui.app import AppTray  # noqa: E402
from twinfi_gui.backend import Result  # noqa: E402
from twinfi_gui.helpers import APP_ID, TRAY_ICONS  # noqa: E402
from twinfi_gui.tray import register_object  # noqa: E402
from twinfi_gui.window import MissingTwinfiWindow, TwinfiWindow  # noqa: E402

HOTSPOT = {
    "method": "hostapd",
    "base_interface": "wlo1",
    "ap_interface": "wlo1_ap",
    "ssid": "Café <Laptop> & co",
    "channel": 6,
    "band": "bg",
    "subnet": "192.168.42.0/24",
    "gateway": "192.168.42.1",
    "blocked": ["de:ad:be:ef:00:01"],
    "notes": [
        "Method hostapd: the best one for this card and setup.",
        "Your band setting is 5 GHz, but the hotspot is on 2.4 GHz because it shares your WiFi's channel. ",
        "To always use your band, set method to p2p (Wi-Fi Direct; shares the radio's speed).",
        "Channel 6 (2.4 GHz): the same as your WiFi's (this card uses one channel for both).",
    ],
}
CLIENTS = [
    {"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.42.17", "hostname": "pixel-8", "limit_kbps": 8000, "blocked": False},
    {"mac": "11:22:33:44:55:66", "ip": "", "hostname": "", "limit_kbps": None, "blocked": False},
]
BASE = {
    "stale": False,
    "interfaces": [{"name": "wlo1", "mac": "x", "type": "managed", "state": "UP", "connected_ssid": "Home"}],
    "autostart": {"init": "systemd", "enabled": False, "running": False},
    "config": {
        "active_profile": "default",
        "profiles": ["default", "travel"],
        "ssid": HOTSPOT["ssid"],
        "band": "a",
        "channel": "157",
        "method": "p2p",
        "interface": None,
    },
}
DETECT_OK = {
    "capability": {
        "interface": "wlo1",
        "supports_ap": True,
        "ap_sta": True,
        "same_channel_required": True,
        "driver": "iwlwifi",
        "chipset": "Intel Wi-Fi 6 AX201",
    },
    "methods": {"hostapd": "ready", "nmcli": "ready"},
    "verdict": {"mode": "ap+sta"},
}
DETECT_SINGLE = {
    "capability": {"interface": "wlo1", "supports_ap": True, "ap_sta": False, "driver": "rtl88x2bu"},
    "methods": {"hostapd": "needs hostapd, dnsmasq", "nmcli": "ready"},
    "verdict": {"mode": "single"},
}

SCENARIOS = {
    "on": ({**BASE, "active": True, "hotspot": HOTSPOT, "clients": CLIENTS}, DETECT_OK),
    "on-empty": ({**BASE, "active": True, "hotspot": {**HOTSPOT, "blocked": []}, "clients": []}, DETECT_OK),
    "off": ({**BASE, "active": False, "hotspot": None, "clients": []}, DETECT_OK),
    "off-single-radio": ({**BASE, "active": False, "hotspot": None, "clients": [], "stale": True}, DETECT_SINGLE),
    "unavailable": ({}, {}),
}


class FakeBackend:
    twinfi = "/usr/bin/twinfi"

    def __init__(self, status, detect):
        self._status, self._detect = status, detect
        self.calls = []

    def available(self):
        return True

    def status(self):
        return self._status

    def detect(self):
        return self._detect

    def text(self, *args):
        return "No USB WiFi adapters detected."

    def secrets(self):
        return Result(True, "", {"settings": {"ssid": HOTSPOT["ssid"]}, "password": "kd7Ws3qPzT9mXbR2"})

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return Result(True, f"{name} done")

        return call


def pump(seconds: float) -> None:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def x11_screenshot(widget: Gtk.Widget, path: Path) -> bool:
    """Grab the window from Xvfb with ImageMagick (for PyGObject < 3.44)."""
    if os.environ.get("GDK_BACKEND") != "x11" or not shutil.which("import"):
        return False
    pump(0.6)
    geometry = f"{widget.get_width()}x{widget.get_height()}+0+0"
    subprocess.run(["import", "-window", "root", "-crop", geometry, str(path)], check=False)
    return True


def screenshot(widget: Gtk.Widget, path: Path) -> None:
    if not SCREENSHOTS["enabled"]:
        if not x11_screenshot(widget, path):
            pump(0.3)  # still let the view lay out and draw
        return
    for _ in range(100):
        widget.queue_draw()
        pump(0.05)
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
        try:
            node = snapshot.to_node()
        except TypeError:  # PyGObject < 3.44 can't return GskRenderNode
            print("note: PyGObject too old for screenshots; building views only")
            SCREENSHOTS["enabled"] = False
            pump(0.3)
            return
        if node is not None:
            widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(path))
            return
    raise RuntimeError(f"nothing rendered for {path.name}")


def capture_dialog(main, path: Path) -> None:
    """Screenshot and close the dialog the main window just opened.

    libadwaita >= 1.5 shows Adw.Dialog inside its parent window; older versions
    open a separate window.
    """
    pump(0.8)
    dialog = main.get_visible_dialog() if hasattr(main, "get_visible_dialog") else None
    if dialog is not None:
        screenshot(dialog, path)  # a window snapshot doesn't include the dialog layer
        dialog.force_close()
        pump(0.3)
        return
    others = [w for w in Gtk.Window.list_toplevels() if w is not main and w.get_visible()]
    assert others, f"no dialog opened for {path.name}"
    screenshot(others[0], path)
    for window in others:
        window.close()


WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
  <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
</interface></node>"""


def fake_tray_watcher(bus: Gio.DBusConnection) -> list:
    """Stand in for a panel's tray: own the watcher name and record registrations."""
    items = []

    def call(_bus, _sender, _path, _iface, _method, params, invocation):
        items.append(params.unpack()[0])
        invocation.return_value(None)

    iface = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]
    register_object(bus, "/StatusNotifierWatcher", iface, call)
    Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, None, None)
    return items


def visible_share(texture, rgb) -> float:
    """Share of a texture's opaque pixels close to ``rgb`` (0 when nothing is drawn)."""
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(texture.save_to_png_bytes().get_data())
    loader.close()
    pixbuf = loader.get_pixbuf().add_alpha(False, 0, 0, 0)
    pixels, stride = pixbuf.get_pixels(), pixbuf.get_rowstride()
    seen = close = 0
    for y in range(pixbuf.get_height()):
        for x in range(pixbuf.get_width()):
            r, g, b, a = pixels[y * stride + x * 4 : y * stride + x * 4 + 4]
            if a > 128:
                seen += 1
                close += all(abs(c - want) < 60 for c, want in zip((r, g, b), rgb, strict=True))
    return close / seen if seen > 100 else 0.0


def check_tray_icons() -> None:
    """Each tray icon takes the colour GTK asks for, as on a light or dark panel."""
    if not SCREENSHOTS["enabled"]:
        return  # rendering needs PyGObject >= 3.44
    host = Gtk.Window()
    host.present()
    pump(0.3)
    red = Gdk.RGBA()
    red.parse("#ff0000")
    for name in TRAY_ICONS:
        path = compat.ICONS_DIR / "hicolor/symbolic/apps" / f"{name}.svg"
        paintable = Gtk.IconPaintable.new_for_file(Gio.File.new_for_path(str(path)), 64, 1)
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot_symbolic(snapshot, 64, 64, [red])
        texture = host.get_renderer().render_texture(snapshot.to_node(), None)
        share = visible_share(texture, (255, 0, 0))
        assert share > 0.95, f"{name}: only {share:.0%} of the icon took the panel colour"
    host.close()


def check_qr_without_pillow() -> None:
    """The share dialog's QR code draws from qrcode's matrix; Pillow isn't needed."""
    try:
        import qrcode
    except ImportError:
        print("note: python qrcode is not installed; QR check skipped")
        return
    from twinfi_gui import share

    payload = "WIFI:T:WPA;S:Smoke Test;P:kd7Ws3qPzT9mXbR2;;"
    blocked = ("PIL", "PIL.Image", "qrcode.image.pil")
    saved = {name: sys.modules.get(name) for name in blocked}
    sys.modules.update(dict.fromkeys(blocked))  # None: any import of them fails
    try:
        texture = share.qr_texture(payload)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    assert texture is not None, "no QR code without Pillow"

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    scale = texture.get_width() // len(matrix)
    assert scale > 0 and texture.get_width() == texture.get_height() == len(matrix) * scale, texture.get_width()

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(texture.save_to_png_bytes().get_data())
    loader.close()
    pixbuf = loader.get_pixbuf()
    pixels, stride, step = pixbuf.get_pixels(), pixbuf.get_rowstride(), pixbuf.get_n_channels()
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            cx, cy = x * scale + scale // 2, y * scale + scale // 2
            red = pixels[cy * stride + cx * step]
            assert (red < 64) == dark, f"module ({x}, {y}) drawn {'light' if dark else 'dark'}"


def check_tray(app: Adw.Application) -> None:
    """The tray icon registers, its menu drives the window, and closing hides to it."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    registered = fake_tray_watcher(bus)
    backend = FakeBackend(*SCENARIOS["on"])
    win = TwinfiWindow(app, backend)
    win.present()

    class AppStub:
        quit_called = False

        def on_tray_change(self, available):
            pass

        def quit(self):
            AppStub.quit_called = True

    tray = AppTray(AppStub(), win)
    for _ in range(200):  # registered, and the first status is in (slow runners need a while)
        pump(0.05)
        if tray.available and win.data:
            break
    assert tray.available and registered == [tray.icon.name], registered
    assert win.data, "no status after 10 s"

    def call(path, iface, method, args):
        """Call the tray like a panel would; async, as the tray answers on this main loop."""
        reply = []
        bus.call(
            tray.icon.name, path, iface, method, args, None, 0, 2000, None, lambda b, r: reply.append(b.call_finish(r))
        )
        for _ in range(100):
            pump(0.02)
            if reply:
                return reply[0].unpack()
        raise RuntimeError(f"no reply to {method}")

    def click(item_id):
        call(
            "/MenuBar",
            "com.canonical.dbusmenu",
            "Event",
            GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("s", ""), 0)),
        )
        pump(0.5)

    _root, _props, children = call(
        "/MenuBar", "com.canonical.dbusmenu", "GetLayout", GLib.Variant("(iias)", (0, -1, []))
    )[1]

    def item_prop(name):
        args = GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", name))
        return call("/StatusNotifierItem", "org.freedesktop.DBus.Properties", "Get", args)[0]

    # The app's own icon, which a panel can find even when running from source.
    tray.set_hide_when_off(False)  # whatever this user's saved setting is
    assert item_prop("IconName") == f"{APP_ID}-symbolic", item_prop("IconName")
    assert item_prop("IconThemePath") == str(compat.ICONS_DIR), item_prop("IconThemePath")
    assert item_prop("Status") == "Active"
    statuses = []
    bus.signal_subscribe(
        tray.icon.name,
        "org.kde.StatusNotifierItem",
        "NewStatus",
        "/StatusNotifierItem",
        None,
        0,
        lambda *a: statuses.append(a[-1].unpack()[0]),
    )
    saved = win.data
    win.data = {**saved, "hotspot": None}
    tray.set_hide_when_off(True)
    pump(0.2)
    assert item_prop("Status") == "Passive" and statuses == ["Passive"], statuses
    assert item_prop("IconName") == f"{APP_ID}-off-symbolic", item_prop("IconName")
    tray.set_hide_when_off(False)
    win.data = saved
    win.update_tray()
    pump(0.2)
    assert item_prop("Status") == "Active" and statuses == ["Passive", "Active"], statuses

    labels = {props.get("label"): item_id for item_id, props, _ in children if "label" in props}
    assert "Stop Hotspot" in labels and "Quit" in labels, labels
    submenus = {props.get("label"): sub for _, props, sub in children if sub}
    profiles = {props["label"]: props.get("toggle-state") for _, props, _ in submenus["Profile"]}
    assert profiles == {"default": 1, "travel": 0}, profiles
    assert len(submenus["Band"]) == 2, submenus
    click(labels["Settings…"])
    assert win.stack.get_visible_child_name() == "settings"
    click(labels["Stop Hotspot"])
    assert "stop" in backend.calls, backend.calls

    win.close()  # with a tray: hide, don't quit
    pump(0.2)
    assert not win.get_visible(), "closing with a tray should hide the window"
    call("/StatusNotifierItem", "org.kde.StatusNotifierItem", "Activate", GLib.Variant("(ii)", (0, 0)))
    pump(0.3)
    assert win.get_visible(), "clicking the tray icon should show the window"
    click(labels["Quit"])
    assert AppStub.quit_called

    tray.close()
    win.tray = None
    win.close()
    pump(0.2)


def run(app: Adw.Application, out: Path) -> None:
    compat.register_bundled_icons("com.github.twinfi.Gtk")
    compat.ensure_font_dpi()  # same startup steps as twinfi_gui.app
    # Headless displays have no frame clock driving animations, so dialogs would
    # stay at their first (transparent) frame. Real sessions are unaffected.
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    for name, (status, detect) in SCENARIOS.items():
        print(f"scenario {name}", flush=True)
        backend = FakeBackend(status, detect)
        win = TwinfiWindow(app, backend)
        win.present()
        pump(0.8)
        for page in ("hotspot", "clients", "settings"):
            print(f"  page {page}", flush=True)
            win.show_page(page)
            screenshot(win, out / f"{name}-{page}.png")
        if status.get("hotspot"):
            win.show_page("hotspot")
            print("  share dialog", flush=True)
            win.share()
            capture_dialog(win, out / f"{name}-share.png")
            if win.clients_page.rows:
                print("  client menu", flush=True)
                win.show_page("clients")  # a popover can only open on a visible row
                pump(0.3)
                row = next(iter(win.clients_page.rows.values()))
                row.popover.popup()
                pump(0.3)
                row.apply_btn.emit("clicked")
                pump(0.5)
                assert "limit" in backend.calls, backend.calls
        print("  toggle", flush=True)
        win.hotspot_page.toggle.emit("clicked")
        pump(0.5)
        if status:
            assert {"stop", "start"} & set(backend.calls), backend.calls
        else:
            assert win.hotspot_page.toggle.get_label() == "Try Again"
        win.close()
        pump(0.2)

    print("narrow window", flush=True)
    narrow = TwinfiWindow(app, FakeBackend(*SCENARIOS["on"]))
    narrow.set_default_size(360, 700)
    narrow.present()
    pump(1.0)
    screenshot(narrow, out / "narrow.png")
    narrow.close()

    print("why it runs this way", flush=True)  # below the fold of the Hotspot tab
    why = TwinfiWindow(app, FakeBackend(*SCENARIOS["on"]))
    why.present()
    pump(1.0)
    assert why.hotspot_page.why.get_visible(), "notes of a running hotspot aren't shown"
    screenshot(why.hotspot_page.why, out / "on-hotspot-why.png")
    why.close()

    print("about window", flush=True)
    host = TwinfiWindow(app, FakeBackend(*SCENARIOS["off"]))
    host.present()
    pump(0.5)
    compat.show_about(host, "0.0.0", "com.github.twinfi.Gtk")
    capture_dialog(host, out / "about.png")
    host.close()

    print("system tray", flush=True)
    check_tray(app)
    print("tray icons", flush=True)
    check_tray_icons()
    print("QR code without Pillow", flush=True)
    check_qr_without_pillow()

    missing = MissingTwinfiWindow(app, "/usr/bin/twinfi")
    missing.present()
    screenshot(missing, out / "missing-twinfi.png")
    missing.close()


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "gui-screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = Adw.Application(application_id="com.github.twinfi.Smoke")
    failure = []

    def activate(app):
        app.hold()
        try:
            run(app, out)
        except Exception as exc:  # noqa: BLE001 - report anything as a failure
            import traceback

            traceback.print_exc()
            failure.append(exc)
        finally:
            app.release()
            app.quit()

    app.connect("activate", activate)
    app.run([])
    DISPLAY_SERVER.terminate()
    version = ".".join(map(str, compat.ADW_VERSION))
    gtk = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}"
    if failure:
        print(f"GUI smoke test FAILED (libadwaita {version}, GTK {gtk})")
        return 1
    print(f"GUI smoke test passed (libadwaita {version}, GTK {gtk}); screenshots in {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
