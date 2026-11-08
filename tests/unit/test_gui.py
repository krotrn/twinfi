"""GUI logic that doesn't need GTK, plus a portability check of the GTK code."""

import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

from twinfi_gui import backend, helpers

GUI_DIR = Path(__file__).resolve().parents[2] / "twinfi_gui"


def completed(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class HelperTests(unittest.TestCase):
    def test_wifi_share_string_escapes(self):
        self.assertEqual(helpers.wifi_share_string("My;Net", 'pa:ss,"w'), r"WIFI:T:WPA;S:My\;Net;P:pa\:ss\,\"w;;")
        self.assertEqual(helpers.wifi_share_string("", "x"), "")
        self.assertEqual(helpers.wifi_share_string("N", "p", hidden=True), "WIFI:T:WPA;S:N;P:p;H:true;;")

    def test_rates_and_client_text(self):
        self.assertEqual(helpers.format_rate(8000), "8 Mbit/s")
        self.assertEqual(helpers.format_rate(500), "500 kbit/s")
        self.assertEqual(helpers.format_rate(None), "")
        client = {"hostname": "", "mac": "aa", "ip": "", "limit_kbps": 1500}
        self.assertEqual(helpers.client_title(client), "Unknown device")
        self.assertEqual(helpers.client_subtitle(client), "no address yet · aa · limited to 1.5 Mbit/s")

    def test_hero_text(self):
        self.assertEqual(helpers.hero_text({})[0], "Status unavailable")
        self.assertEqual(helpers.hero_text({"hotspot": None, "config": {}})[0], "Hotspot is off")
        title, subtitle, _ = helpers.hero_text({"hotspot": {"ssid": "S"}, "clients": [{}]})
        self.assertEqual((title, subtitle), ("Hotspot is on", "S · 1 device connected"))

    def menu(self, items):
        """key -> MenuItem, submenus included."""
        flat = {}
        for item in items:
            flat[item.key] = item
            flat.update(self.menu(item.children))
        return flat

    def test_tray_state(self):
        data = {
            "hotspot": {"ssid": "S"},
            "clients": [],
            "config": {"profiles": ["default", "travel"], "active_profile": "travel", "band": "a"},
            "autostart": {"init": "systemd", "enabled": True},
        }
        icon, title, body, items = helpers.tray_state(data)
        self.assertEqual(
            (icon, title, body), ("com.github.twinfi.Gtk-symbolic", "Hotspot is on", "S · 0 devices connected")
        )
        menu = self.menu(items)
        self.assertEqual((menu["toggle"].label, menu["toggle"].enabled), ("Stop Hotspot", True))
        self.assertTrue(menu["share"].visible and menu["devices"].visible)
        self.assertTrue(menu["profile:travel"].checked and not menu["profile:default"].checked)
        self.assertTrue(menu["band:a"].checked)
        self.assertFalse(menu["band:a"].enabled)  # like the window: only while the hotspot is off
        self.assertTrue(menu["autostart"].visible and menu["autostart"].checked)
        self.assertEqual(menu["autostart"].toggle, "checkmark")

        off = {**data, "hotspot": None, "config": {"profiles": ["default"], "band": "bg"}, "autostart": {}}
        _, title, _, items = helpers.tray_state(off, busy=True)
        menu = self.menu(items)
        self.assertEqual(title, "Working…")
        self.assertEqual((menu["toggle"].label, menu["toggle"].enabled), ("Start Hotspot", False))
        self.assertFalse(menu["share"].visible or menu["devices"].visible)
        self.assertFalse(menu["profiles"].visible)  # one profile: nothing to switch
        self.assertFalse(menu["autostart"].visible)  # unknown init system
        self.assertTrue(self.menu(helpers.tray_state(off)[3])["band:a"].enabled)
        self.assertFalse(self.menu(helpers.tray_state({})[3])["toggle"].enabled)

    def test_tray_icon_is_the_apps_own_not_a_wifi_status_icon(self):
        # A theme Wi-Fi icon in the tray looks like the network applet's.
        on = helpers.tray_state({"hotspot": {"ssid": "S"}})[0]
        off = helpers.tray_state({"hotspot": None, "config": {}})[0]
        self.assertEqual(on, "com.github.twinfi.Gtk-symbolic")
        problem = helpers.tray_state({})[0]  # twinfi could not report a status
        self.assertEqual(off, "com.github.twinfi.Gtk-off-symbolic")
        self.assertEqual(problem, "com.github.twinfi.Gtk-error-symbolic")
        for name in (on, off, problem):
            self.assertTrue((GUI_DIR / "data/icons/hicolor/symbolic/apps" / f"{name}.svg").is_file(), name)

    def test_tray_icons_follow_the_panel_text_colour(self):
        # Plasma recolours an icon by replacing its "current-color-scheme" stylesheet;
        # GTK recolours the fills of -symbolic icons. Both need currentColor fills only.
        import xml.etree.ElementTree as ET

        ns = "{http://www.w3.org/2000/svg}"
        for name in helpers.TRAY_ICONS:
            path = GUI_DIR / "data/icons/hicolor/symbolic/apps" / f"{name}.svg"
            root = ET.parse(path).getroot()
            styles = [s for s in root.iter(f"{ns}style") if s.get("id") == "current-color-scheme"]
            self.assertEqual(len(styles), 1, name)
            self.assertRegex(styles[0].text or "", r"\.ColorScheme-Text\s*\{\s*color:\s*#[0-9a-fA-F]{6};?\s*\}", name)
            shapes = [e for e in root.iter() if e.tag[len(ns) :] in ("path", "circle", "rect", "ellipse", "polygon")]
            self.assertTrue(shapes, name)
            for shape in shapes:
                self.assertEqual(shape.get("class"), "ColorScheme-Text", (name, shape.attrib))
                self.assertEqual(shape.get("fill"), "currentColor", (name, shape.attrib))
                self.assertIsNone(shape.get("stroke"), (name, shape.attrib))  # outlines only: fills recolour everywhere
            outside = path.read_text().replace(styles[0].text or "", "")
            self.assertNotRegex(outside, r"#[0-9a-fA-F]{3,6}\b", name)

    def fake_qrcode(self, matrix):
        """A qrcode module whose codes are ``matrix``; records the data it was given."""
        module = types.ModuleType("qrcode")
        module.constants = SimpleNamespace(ERROR_CORRECT_M=0)
        seen = module.seen = []

        class QRCode:
            def __init__(self, **kwargs):
                pass

            def add_data(self, data):
                seen.append(data)

            def make(self, fit):
                pass

            def get_matrix(self):
                return matrix

        module.QRCode = QRCode
        return module

    def test_qr_pixels_draw_the_modules_without_pillow(self):
        fake = self.fake_qrcode([[True, False], [False, True]])
        with mock.patch.dict(sys.modules, {"qrcode": fake, "PIL": None, "PIL.Image": None}):
            size, rgb = helpers.qr_pixels("WIFI:S:N;;", scale=3)
        self.assertEqual(fake.seen, ["WIFI:S:N;;"])
        self.assertEqual((size, len(rgb)), (6, 6 * 6 * 3))

        def pixel(x, y):
            return rgb[(y * size + x) * 3 : (y * size + x) * 3 + 3]

        black, white = b"\x00\x00\x00", b"\xff\xff\xff"
        self.assertEqual([pixel(0, 0), pixel(2, 2), pixel(3, 3), pixel(5, 5)], [black] * 4)
        self.assertEqual([pixel(3, 0), pixel(5, 2), pixel(0, 3), pixel(2, 5)], [white] * 4)

    def test_qr_pixels_without_qrcode(self):
        with mock.patch.dict(sys.modules, {"qrcode": None}):
            self.assertIsNone(helpers.qr_pixels("x"))

    def test_nothing_pulls_in_pillow(self):
        # QR codes are drawn from qrcode's matrix; Pillow is no longer needed.
        root = GUI_DIR.parent
        pyproject, lock = root / "pyproject.toml", root / "uv.lock"
        if not (pyproject.is_file() and lock.is_file()):
            self.skipTest("pyproject.toml and uv.lock are not part of this tree")
        gui_extra = re.search(r"^gui = \[(.*)\]", pyproject.read_text(), re.M)
        self.assertIsNotNone(gui_extra)
        self.assertNotIn("pil", gui_extra.group(1).lower())
        self.assertNotRegex(lock.read_text(), r'name = "pillow"')

    def test_tray_status(self):
        on, off = {"hotspot": {"ssid": "S"}}, {"hotspot": None, "config": {}}
        self.assertEqual(helpers.tray_status(off), "Active")  # shown unless asked otherwise
        self.assertEqual(helpers.tray_status(off, hide_when_off=True), "Passive")
        self.assertEqual(helpers.tray_status(on, hide_when_off=True), "Active")
        self.assertEqual(helpers.tray_status(off, busy=True, hide_when_off=True), "Active")
        self.assertEqual(helpers.tray_status({}, hide_when_off=True), "Active")  # status unknown: stay visible

    def test_gui_prefs(self):
        self.assertEqual(helpers.gui_prefs_path({"XDG_CONFIG_HOME": "/cfg"}), Path("/cfg/twinfi/gui.json"))
        self.assertEqual(helpers.gui_prefs_path({"HOME": "/h"}), Path("/h/.config/twinfi/gui.json"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "twinfi" / "gui.json"
            self.assertEqual(helpers.load_gui_prefs(path), {})
            helpers.save_gui_prefs({"tray_hide_when_off": True}, path)
            self.assertEqual(helpers.load_gui_prefs(path), {"tray_hide_when_off": True})
            path.write_text("{not json")
            self.assertEqual(helpers.load_gui_prefs(path), {})
            path.write_text("[1]")
            self.assertEqual(helpers.load_gui_prefs(path), {})

    def test_packages_install_every_bundled_icon(self):
        root = GUI_DIR.parent
        packagings = ("debian/twinfi.install", "packaging/arch/PKGBUILD")
        if not all((root / p).is_file() for p in packagings):
            # Distribution package builds (e.g. Debian's pybuild) copy only the package and tests.
            self.skipTest("packaging files are not part of this tree")
        icons = sorted((GUI_DIR / "data/icons/hicolor").glob("*/apps/*.svg"))
        for packaging in packagings:
            text = (root / packaging).read_text()
            for icon in icons:
                self.assertIn(str(icon.relative_to(root)), text, packaging)

    def test_band_change_resets_a_channel_the_band_lacks(self):
        self.assertEqual(helpers.band_change({"channel": "6"}, "a"), {"band": "a", "channel": "auto"})
        self.assertEqual(helpers.band_change({"channel": "6"}, "bg"), {"band": "bg"})
        self.assertEqual(helpers.band_change({}, "a"), {"band": "a"})

    def test_login_entry(self):
        path = helpers.login_entry_path({"XDG_CONFIG_HOME": "/cfg"})
        self.assertEqual(path, Path("/cfg/autostart/com.github.twinfi.Gtk.desktop"))
        self.assertIn("Exec=/x/twinfi-gtk --background\n", helpers.login_entry("/x/twinfi-gtk"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autostart" / "a.desktop"
            helpers.set_login_start(True, path)
            self.assertIn("--background", path.read_text())
            helpers.set_login_start(False, path)
            self.assertFalse(path.exists())
            helpers.set_login_start(False, path)  # already off

    def test_method_and_channel_choices(self):
        self.assertEqual([m[0] for m in helpers.METHODS], ["auto", "hostapd", "nmcli", "p2p", "nmcli-single"])
        five = helpers.channel_options("a")
        self.assertEqual(five[0], ("auto", "Automatic (least crowded)"))
        self.assertIn(("149", "Channel 149"), five)
        self.assertEqual(len(helpers.channel_options("bg")), 14)
        self.assertEqual(helpers.index_of(five, "149"), 5)
        self.assertEqual(helpers.index_of(five, "6"), 0)  # not on this band: automatic

    def test_uplink(self):
        data = {
            "hotspot": {"base_interface": "wlo1"},
            "interfaces": [{"name": "wlo1", "connected_ssid": "Home"}, {"name": "x", "connected_ssid": "Other"}],
        }
        self.assertEqual(helpers.uplink(data), "Home")
        self.assertIsNone(helpers.uplink({}))

    def test_capability_rows(self):
        self.assertEqual(helpers.capability_rows({}), [])
        rows = helpers.capability_rows(
            {
                "capability": {"supports_ap": True, "ap_sta": True, "same_channel_required": True},
                "methods": {"hostapd": "needs hostapd", "nmcli": "ready"},
            }
        )
        self.assertEqual([r[2] for r in rows], [True, True, False, False, True])
        self.assertEqual(rows[3][1], "Needs hostapd")
        p2p = helpers.capability_rows(
            {
                "capability": {"supports_ap": True, "ap_sta": True, "same_channel_required": True},
                "methods": {"p2p": "ready"},
            }
        )
        self.assertEqual(
            p2p[2][1:], ("Hotspot may use a different channel than your Wi-Fi (as a Wi-Fi Direct group)", True)
        )
        self.assertEqual(p2p[3][0], "Wi-Fi Direct (own channel)")
        five = helpers.capability_rows({"capability": {"supports_ap": True, "ap_frequencies": [2437, 5745]}})
        self.assertEqual(five[-1][0], "Hotspot on 5 GHz")
        self.assertTrue(five[-1][2])
        self.assertEqual(helpers.band_label("a"), "5 GHz")


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.b = backend.TwinfiBackend("/usr/bin/twinfi")

    def test_privileged_runs_twinfi_directly(self):
        with mock.patch.object(backend.subprocess, "run", return_value=completed()) as run:
            self.assertTrue(self.b.start(allow_disconnect=True).ok)
        argv = run.call_args[0][0]
        self.assertEqual(argv[:3], ["pkexec", "/usr/bin/twinfi", "start"])
        self.assertIn("--allow-disconnect", argv)

    def test_password_goes_over_stdin(self):
        with mock.patch.object(backend.subprocess, "run", return_value=completed()) as run:
            self.b.save_config("Cafe", "secret123", "a", "")
        argv = run.call_args[0][0]
        self.assertNotIn("secret123", " ".join(argv))
        self.assertIn("--password-stdin", argv)
        self.assertIn("band=a", argv)
        self.assertIn("interface=auto", argv)
        self.assertIn("hidden=no", argv)
        self.assertIn("method=auto", argv)
        self.assertIn("channel=auto", argv)
        self.assertEqual(run.call_args.kwargs["input"], "secret123\n")
        with mock.patch.object(backend.subprocess, "run", return_value=completed()) as run:
            self.b.save_config("Cafe", "", "a", "wlan1", hidden=True, method="p2p", channel="157")
        self.assertIsNone(run.call_args.kwargs["input"])
        self.assertIn("hidden=yes", run.call_args[0][0])
        self.assertIn("method=p2p", run.call_args[0][0])
        self.assertIn("channel=157", run.call_args[0][0])

    def test_pkexec_failures(self):
        cases = [
            (completed(126), "Authentication cancelled."),
            (completed(127, err="Error executing command as another user: Not authorized"), "Not authorized."),
            (completed(127, err="==== AUTHENTICATION FAILED ===\nNo authentication agent found."), "No polkit"),
            (completed(1, err="  ✘  Could not start the hotspot.\n     hint"), "Could not start the hotspot."),
            (completed(3, out="", err=""), "Unknown error"),
        ]
        for proc, message in cases:
            with mock.patch.object(backend.subprocess, "run", return_value=proc):
                self.assertTrue(self.b.stop().message.startswith(message), (proc, self.b.stop().message))
        with mock.patch.object(backend.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIn("pkexec", self.b.stop().message)
        with mock.patch.object(backend.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIn("timed out", self.b.stop().message)

    def test_secrets(self):
        payload = {"settings": {"ssid": "S"}, "password": "p4ssword"}
        with mock.patch.object(backend.subprocess, "run", return_value=completed(out=json.dumps(payload))) as run:
            result = self.b.secrets()
        self.assertEqual(result.data["password"], "p4ssword")
        self.assertEqual(run.call_args[0][0][2:], ["config", "--json", "--show-password"])
        with mock.patch.object(backend.subprocess, "run", return_value=completed(out="not json")):
            self.assertFalse(self.b.secrets().ok)

    def test_unprivileged_reads(self):
        with mock.patch.object(backend.subprocess, "run", return_value=completed(out=json.dumps({"active": True}))):
            self.assertEqual(self.b.status(), {"active": True})
            self.assertEqual(self.b.detect(), {"active": True})
        with mock.patch.object(backend.subprocess, "run", return_value=completed(1)):
            self.assertEqual(self.b.status(), {})
        with mock.patch.object(backend.subprocess, "run", return_value=completed(out="\x1b[1mhi\x1b[0m")):
            self.assertEqual(self.b.text("detect"), "hi")
        with mock.patch.object(backend.subprocess, "run", side_effect=OSError("nope")):
            self.assertEqual(self.b.text("detect"), "nope")
            self.assertEqual(self.b.status(), {})

    def test_command_shapes(self):
        with mock.patch.object(backend.subprocess, "run", return_value=completed()) as run:
            for call, tail in (
                (lambda: self.b.use_profile("travel"), ["profile", "use", "travel"]),
                (lambda: self.b.create_profile("t2"), ["profile", "create", "t2"]),
                (lambda: self.b.disconnect("phone", block=True), ["clients", "disconnect", "phone", "--block"]),
                (lambda: self.b.unblock("aa"), ["clients", "unblock", "aa"]),
                (lambda: self.b.limit("phone", 100), ["clients", "limit", "phone", "100"]),
                (lambda: self.b.unlimit("phone"), ["clients", "unlimit", "phone"]),
                (lambda: self.b.set_autostart(True), ["enable"]),
                (lambda: self.b.set_autostart(False), ["disable"]),
                (lambda: self.b.stop(), ["stop"]),
                (
                    lambda: self.b.set_config({"band": "a", "channel": "auto"}),
                    ["config", "--set", "band=a", "--set", "channel=auto"],
                ),
            ):
                call()
                self.assertEqual(run.call_args[0][0][2:], tail)
        self.assertFalse(backend.TwinfiBackend("/nonexistent/twinfi").available())


# libadwaita 1.0 / GTK 4.6 is the floor (Ubuntu & Pop!_OS 22.04, Linux Mint 21).
BASELINE_ADW = {
    "ActionRow",
    "Application",
    "ApplicationWindow",
    "Clamp",
    "ComboRow",
    "ExpanderRow",
    "HeaderBar",
    "PreferencesGroup",
    "PreferencesPage",
    "StatusPage",
    "Toast",
    "ToastOverlay",
    "ViewStack",
    "ViewSwitcher",
    "ViewSwitcherPolicy",
    "Window",
    "get_major_version",
    "get_minor_version",
}
NEWER_METHODS = (
    "add_titled_with_icon",  # Adw 1.2
    "set_header_suffix",  # Adw 1.1
    "set_subtitle_selectable",  # Adw 1.3
    "AlertDialog",
    "MessageDialog",
    "SwitchRow",
    "SpinRow",
    "ToolbarView",
    "Banner",
    "Breakpoint",
    "NavigationView",
    "OverlaySplitView",
    "Spinner",  # Adw 1.2+ widgets
)


class PortabilityTests(unittest.TestCase):
    def sources(self):
        return {p: p.read_text() for p in GUI_DIR.rglob("*.py") if p.name != "compat.py"}

    def test_only_baseline_libadwaita_widgets(self):
        for path, text in self.sources().items():
            used = set(re.findall(r"\bAdw\.(\w+)", text))
            self.assertLessEqual(used, BASELINE_ADW, f"{path.name} uses {used - BASELINE_ADW}; go through compat.py")

    def test_no_newer_apis(self):
        for path, text in self.sources().items():
            for name in NEWER_METHODS:
                needle = f"Adw.{name}" if name[0].isupper() else f".{name}("
                self.assertFalse(needle in text, f"{path.name} uses {needle}; go through compat.py")

    def test_desktop_file_matches_app_id(self):
        desktop = (GUI_DIR / "data" / f"{helpers.APP_ID}.desktop").read_text()
        self.assertIn(f"StartupWMClass={helpers.APP_ID}", desktop)

    def test_metainfo_matches_app_id_and_version(self):
        import xml.etree.ElementTree as ET

        from twinfi_cli import __version__

        root = ET.parse(GUI_DIR / "data" / f"{helpers.APP_ID}.metainfo.xml").getroot()
        self.assertEqual(root.findtext("id"), helpers.APP_ID)
        self.assertEqual(root.findtext("launchable"), f"{helpers.APP_ID}.desktop")
        self.assertEqual(root.find("releases/release").get("version"), __version__)


def load_tray():
    """twinfi_gui.tray, with a stand-in for PyGObject where it isn't installed."""
    try:
        import gi  # noqa: F401
    except ImportError:
        pass
    else:
        from twinfi_gui import tray

        return tray

    class Variant:
        def __init__(self, fmt, value):
            self.fmt, self.value = fmt, value

        def unpack(self):
            return self.value

    glib = types.SimpleNamespace(Variant=Variant, Error=type("Error", (Exception,), {}))
    gio = types.SimpleNamespace(bus_get_sync=lambda *_: None, BusType=types.SimpleNamespace(SESSION=0))
    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")
    repository.GLib, repository.Gio = glib, gio
    gi.repository = repository
    with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        sys.modules.pop("twinfi_gui.tray", None)
        from twinfi_gui import tray
    return tray


class TrayIconTests(unittest.TestCase):
    def setUp(self):
        self.tray = load_tray()

    def icon(self, use_icon_names):
        """A TrayIcon with no session bus; emitted item signals go to self.signals."""
        with mock.patch.object(self.tray.Gio, "bus_get_sync", side_effect=self.tray.GLib.Error()):
            icon = self.tray.TrayIcon("twinfi", "Hotspot", print, print, use_icon_names=use_icon_names)
        self.signals = []
        icon._emit_item = lambda signal, params=None: self.signals.append(signal)
        return icon

    def prop(self, icon, name):
        value = icon._item_props()[name].unpack()
        if name == "IconPixmap":  # GLib unpacks "ay" as a list of ints
            value = [(w, h, bytes(data)) for w, h, data in value]
        return value

    def test_icon_theme_path_is_never_sent(self):
        # Quickshell reads IconThemePath as a flat folder, so a theme tree there
        # shows a "missing icon" picture instead of the icon.
        for use_icon_names in (True, False):
            icon = self.icon(use_icon_names)
            icon.update(helpers.TRAY_ICON_ON, "t", "b", [], [(1, 1, b"\0\0\0\0")])
            self.assertEqual(self.prop(icon, "IconThemePath"), "")

    def test_installed_icons_go_out_by_name_with_pixmaps(self):
        icon = self.icon(True)
        pixmaps = [(1, 1, b"\xff\0\0\0")]
        icon.update(helpers.TRAY_ICON_ON, "t", "b", [], pixmaps)
        self.assertEqual(self.prop(icon, "IconName"), helpers.TRAY_ICON_ON)
        self.assertEqual(self.prop(icon, "IconPixmap"), pixmaps)

    def test_without_installed_icons_only_pixmaps_go_out_and_changes_still_show(self):
        icon = self.icon(False)
        on, off = [(1, 1, b"\xff\0\0\0")], [(1, 1, b"\x80\0\0\0")]
        icon.update(helpers.TRAY_ICON_ON, "t", "b", [], on)
        self.assertEqual(self.signals.count("NewIcon"), 1)
        self.assertEqual(self.prop(icon, "IconName"), "")
        self.assertEqual(self.prop(icon, "IconPixmap"), on)
        self.assertEqual(self.prop(icon, "ToolTip")[0], "")

        icon.update(helpers.TRAY_ICON_OFF, "t", "b", [], off)
        self.assertEqual(self.signals.count("NewIcon"), 2)
        self.assertEqual(self.prop(icon, "IconName"), "")
        self.assertEqual(self.prop(icon, "IconPixmap"), off)

        icon.update(helpers.TRAY_ICON_OFF, "t", "b", [], off)  # same icon: no signal
        self.assertEqual(self.signals.count("NewIcon"), 2)
        icon.update(helpers.TRAY_ICON_ERROR, "t", "b", [], on)
        self.assertEqual(self.signals.count("NewIcon"), 3)


class TrayIconsInstalledTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def install(self, data_dir, names=helpers.TRAY_ICONS):
        apps = self.root / data_dir / "icons/hicolor/symbolic/apps"
        apps.mkdir(parents=True, exist_ok=True)
        for name in names:
            (apps / f"{name}.svg").write_text("<svg/>")

    def installed(self, **env):
        env.setdefault("XDG_DATA_HOME", str(self.root / "home"))
        return helpers.tray_icons_installed(env)

    def test_found_in_a_system_data_dir(self):
        dirs = f"{self.root / 'a'}:{self.root / 'b'}"
        self.assertFalse(self.installed(XDG_DATA_DIRS=dirs))
        self.install("b")
        self.assertTrue(self.installed(XDG_DATA_DIRS=dirs))

    def test_found_in_the_user_data_dir(self):
        self.install("home")
        self.assertTrue(self.installed(XDG_DATA_DIRS=str(self.root / "a")))
        self.assertFalse(self.installed(XDG_DATA_HOME=str(self.root / "other"), XDG_DATA_DIRS=str(self.root / "a")))

    def test_every_tray_icon_is_needed(self):
        # An older install without the off and error icons would show a missing icon.
        self.install("a", [helpers.TRAY_ICON_ON])
        self.assertFalse(self.installed(XDG_DATA_DIRS=str(self.root / "a")))

    def test_default_dirs_and_relative_entries(self):
        with mock.patch.object(Path, "is_file", autospec=True, side_effect=lambda p: str(p).startswith("/usr/share/")):
            self.assertTrue(helpers.tray_icons_installed({"XDG_DATA_HOME": str(self.root)}))
            self.assertFalse(helpers.tray_icons_installed({"XDG_DATA_DIRS": "relative/share"}))


if __name__ == "__main__":
    unittest.main()
