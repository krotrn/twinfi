"""Pure helpers for the GTK UI (no GTK imports, unit-testable)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import NamedTuple, Optional, Tuple

APP_ID = "com.github.twinfi.Gtk"
# The tray shows the app's own icon: theme Wi-Fi icons look like the network applet's.
TRAY_ICON_ON = f"{APP_ID}-symbolic"
TRAY_ICON_OFF = f"{APP_ID}-off-symbolic"
TRAY_ICON_ERROR = f"{APP_ID}-error-symbolic"
TRAY_ICONS = (TRAY_ICON_ON, TRAY_ICON_OFF, TRAY_ICON_ERROR)
POLL_INTERVAL = 5  # seconds between status refreshes


def tray_icons_installed(environ: Optional[dict] = None) -> bool:
    """True when the system icon theme has the tray icons.

    Looks in ``$XDG_DATA_HOME/icons`` and each ``$XDG_DATA_DIRS`` entry's
    ``icons`` for ``hicolor/symbolic/apps/<name>.svg``, where the packages
    install them. Runs from source or pip don't have them there, and the tray
    must then send pixmaps only: an icon name the panel can't find shows as a
    "missing icon" picture on some panels.
    """
    env = os.environ if environ is None else environ
    data_home = env.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [Path(d) / "icons" for d in [data_home, *data_dirs] if d and os.path.isabs(d)]
    return all(any((root / "hicolor/symbolic/apps" / f"{name}.svg").is_file() for root in roots) for name in TRAY_ICONS)


BANDS = [("bg", "2.4 GHz"), ("a", "5 GHz")]
# The ``method`` setting: (value, label, what it means).
METHODS = [
    ("auto", "Automatic", "Best for your card and network"),
    ("hostapd", "hostapd", "Same channel; fastest; device control"),
    ("nmcli", "NetworkManager", "Same channel; no blocking or allowlist"),
    ("p2p", "Wi-Fi Direct", "Own channel; shares the radio's speed"),
    ("nmcli-single", "Hotspot only", "Wi-Fi disconnects while it runs"),
]
# Channels people can pick; the card may still forbid some (twinfi then says so).
CHANNELS = {
    "bg": [str(n) for n in range(1, 14)],
    "a": ["36", "40", "44", "48", "149", "153", "157", "161", "165"],
}


def channel_options(band: str) -> list:
    """(value, label) choices for the channel setting on ``band``, "auto" first."""
    return [("auto", "Automatic (least crowded)")] + [(c, f"Channel {c}") for c in CHANNELS.get(band, CHANNELS["bg"])]


def index_of(options: list, value) -> int:
    """Position of ``value`` among (value, ...) tuples, or 0 (the first, "automatic") if absent."""
    return next((i for i, option in enumerate(options) if option[0] == value), 0)


def escape_wifi_field(value: str) -> str:
    for ch in ("\\", ";", ",", ":", '"'):
        value = value.replace(ch, "\\" + ch)
    return value


def wifi_share_string(ssid: str, password: str, hidden: bool = False) -> str:
    """The ``WIFI:`` payload phone cameras understand; ``H:true`` for hidden networks."""
    if not ssid or not password:
        return ""
    tail = "H:true;" if hidden else ""
    return f"WIFI:T:WPA;S:{escape_wifi_field(ssid)};P:{escape_wifi_field(password)};{tail};"


def qr_pixels(payload: str, scale: int = 10, border: int = 2) -> Optional[Tuple[int, bytes]]:
    """(side, RGB bytes) of a square QR code image, or None if the qrcode module is missing.

    Drawn straight from qrcode's module matrix, so no imaging library is needed.
    """
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()  # border included
    dark, light = b"\x00\x00\x00" * scale, b"\xff\xff\xff" * scale
    rgb = b"".join(b"".join(dark if module else light for module in row) * scale for row in matrix)
    return len(matrix) * scale, rgb


def band_label(band: Optional[str]) -> str:
    return "5 GHz" if band == "a" else "2.4 GHz"


def format_rate(kbps: Optional[int]) -> str:
    if not kbps:
        return ""
    return f"{kbps / 1000:g} Mbit/s" if kbps >= 1000 else f"{kbps} kbit/s"


def client_title(client: dict) -> str:
    return client.get("hostname") or "Unknown device"


def client_subtitle(client: dict) -> str:
    parts = [client.get("ip") or "no address yet", client.get("mac", "")]
    if client.get("limit_kbps"):
        parts.append(f"limited to {format_rate(client['limit_kbps'])}")
    return " · ".join(p for p in parts if p)


def hero_text(data: dict) -> tuple:
    """(title, subtitle, icon) for the status hero."""
    hotspot = data.get("hotspot")
    if not data:
        return "Status unavailable", "Could not run twinfi.", "dialog-warning-symbolic"
    if hotspot:
        count = len(data.get("clients") or [])
        devices = "1 device" if count == 1 else f"{count} devices"
        return "Hotspot is on", f"{hotspot['ssid']} · {devices} connected", "network-wireless-hotspot-symbolic"
    return "Hotspot is off", "Share this computer's internet over Wi-Fi.", "network-wireless-offline-symbolic"


def uplink(data: dict) -> Optional[str]:
    """SSID of the Wi-Fi connection the hotspot shares, if still connected."""
    hotspot = data.get("hotspot") or {}
    for iface in data.get("interfaces") or []:
        if iface.get("name") == hotspot.get("base_interface") and iface.get("connected_ssid"):
            return iface["connected_ssid"]
    return None


def capability_rows(detect: dict) -> list:
    """(title, subtitle, ok) rows describing the hardware report."""
    cap = detect.get("capability") or {}
    if not cap:
        return []
    rows = [
        ("Hotspot (AP mode)", "The card can act as an access point", cap.get("supports_ap")),
        ("Keep Wi-Fi while hosting", "Hotspot and Wi-Fi connection at the same time", cap.get("ap_sta")),
    ]
    if cap.get("ap_sta"):
        p2p_ready = (detect.get("methods") or {}).get("p2p") == "ready"
        own_channel = not cap.get("same_channel_required") or p2p_ready
        subtitle = "Hotspot may use a different channel than your Wi-Fi"
        if cap.get("same_channel_required") and own_channel:
            subtitle += " (as a Wi-Fi Direct group)"
        rows.append(("Independent channel", subtitle, bool(own_channel)))
    if "ap_frequencies" in cap:
        five_ghz = any(f >= 5000 for f in cap["ap_frequencies"])
        rows.append(("Hotspot on 5 GHz", "Some 5 GHz channels allow starting a network", five_ghz))
    for name, state in (detect.get("methods") or {}).items():
        label = {"hostapd": "hostapd (client management)", "p2p": "Wi-Fi Direct (own channel)"}.get(
            name, "NetworkManager"
        )
        rows.append((label, "Ready" if state == "ready" else state.capitalize(), state == "ready"))
    return rows


class MenuItem(NamedTuple):
    """One tray menu entry; key "-" is a separator."""

    key: str
    label: str = ""
    enabled: bool = True
    visible: bool = True
    toggle: str = ""  # "radio" or "checkmark" to show ``checked``
    checked: bool = False
    children: tuple = ()


SEPARATOR = MenuItem("-")
AUTOSTART_INITS = ("systemd", "openrc", "runit")


def tray_state(data: dict, busy: bool = False) -> tuple:
    """(icon, tooltip title, tooltip body, menu items) for the tray icon.

    Like the window, profile and band can be changed only while the hotspot is
    off. Keys: "toggle", "share", "devices", "profile:<name>", "band:<band>",
    "autostart", "settings", "show", "quit".
    """
    title, subtitle, _ = hero_text(data)
    hotspot = bool(data.get("hotspot"))
    icon = TRAY_ICON_ERROR if not data else TRAY_ICON_ON if hotspot else TRAY_ICON_OFF
    config = data.get("config") or {}
    autostart = data.get("autostart") or {}
    if busy:
        title = "Working…"
    idle = bool(data) and not busy
    profiles = tuple(
        MenuItem(f"profile:{name}", name, idle and not hotspot, True, "radio", name == config.get("active_profile"))
        for name in config.get("profiles") or []
    )
    bands = tuple(
        MenuItem(f"band:{band}", label, idle and not hotspot, True, "radio", (config.get("band") or "bg") == band)
        for band, label in BANDS
    )
    items = [
        MenuItem("status", title, enabled=False),
        SEPARATOR,
        MenuItem("toggle", "Stop Hotspot" if hotspot else "Start Hotspot", idle),
        MenuItem("share", "Share…", not busy, hotspot),
        MenuItem("devices", "Connected Devices", visible=hotspot),
        SEPARATOR,
        MenuItem("profiles", "Profile", visible=len(profiles) > 1, children=profiles),
        MenuItem("bands", "Band", visible=bool(config), children=bands),
        MenuItem(
            "autostart",
            "Start Automatically",
            idle,
            autostart.get("init") in AUTOSTART_INITS,
            "checkmark",
            bool(autostart.get("enabled")),
        ),
        MenuItem("settings", "Settings…"),
        SEPARATOR,
        MenuItem("show", "Open Hotspot Window"),
        MenuItem("quit", "Quit"),
    ]
    return icon, title, subtitle, items


def tray_status(data: dict, busy: bool = False, hide_when_off: bool = False) -> str:
    """StatusNotifierItem ``Status``: "Passive" lets the panel hide the icon.

    Only while the hotspot is known to be off and nothing is in progress, so an
    error or a pending change stays in view.
    """
    if hide_when_off and data and not data.get("hotspot") and not busy:
        return "Passive"
    return "Active"


def band_change(config: dict, band: str) -> dict:
    """Settings to save for a band switch; a fixed channel the new band lacks becomes automatic."""
    changes = {"band": band}
    channel = config.get("channel") or "auto"
    if channel != "auto" and channel not in CHANNELS.get(band, []):
        changes["channel"] = "auto"
    return changes


def login_entry_path(env=os.environ) -> Path:
    """The XDG autostart entry that starts the app in the tray at login."""
    config = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return Path(config) / "autostart" / f"{APP_ID}.desktop"


def login_entry(exe: Optional[str] = None) -> str:
    exe = exe or shutil.which("twinfi-gtk") or "twinfi-gtk"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Hotspot (twinfi)\n"
        "Comment=Show the hotspot in the system tray\n"
        f"Exec={exe} --background\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def set_login_start(enabled: bool, path: Optional[Path] = None) -> None:
    """Add or remove the login autostart entry (raises OSError)."""
    path = path or login_entry_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(login_entry(), encoding="utf-8")
    elif path.exists():
        path.unlink()


def gui_prefs_path(env=os.environ) -> Path:
    """Per-user settings of the GTK app (the hotspot's own settings are system-wide)."""
    config = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return Path(config) / "twinfi" / "gui.json"


def load_gui_prefs(path: Optional[Path] = None) -> dict:
    """The saved settings; {} when there are none or the file is unreadable."""
    try:
        prefs = json.loads((path or gui_prefs_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return prefs if isinstance(prefs, dict) else {}


def save_gui_prefs(prefs: dict, path: Optional[Path] = None) -> None:
    """Write the settings (raises OSError)."""
    path = path or gui_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
