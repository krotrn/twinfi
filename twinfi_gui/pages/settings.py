"""Settings tab: network settings, profiles, start at boot and login, and the hardware report."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ..compat import EntryField, button_row, esc, switch_row
from ..helpers import (
    AUTOSTART_INITS,
    BANDS,
    METHODS,
    capability_rows,
    channel_options,
    index_of,
    load_gui_prefs,
    login_entry_path,
    save_gui_prefs,
    set_login_start,
)


class SettingsPage:
    def __init__(self, window):
        self.window = window
        self._synced: dict = {}
        self._ifaces: list = []
        self._updating = False
        self._hw_rows: list = []
        self.widget = Adw.PreferencesPage()

        # ── network ───────────────────────────────────────────────────────────
        net = Adw.PreferencesGroup(
            title="Network",
            description="Saved to the active profile. Leave the password empty to keep it. "
            "Restart the hotspot to apply changes.",
        )
        self.ssid = EntryField("Network name")
        self.password = EntryField("New password", password=True)
        self.band = Adw.ComboRow(title="Band")
        self.band.set_model(Gtk.StringList.new([label for _, label in BANDS]))
        self.band.set_subtitle("If not tied to your Wi-Fi's channel")
        self.band.connect("notify::selected", lambda *_: self._fill_channels())
        self.channel = Adw.ComboRow(title="Channel", subtitle="Used when the hotspot has a channel of its own")
        self.channel_model = Gtk.StringList()
        self.channel.set_model(self.channel_model)
        self._channels: list = []
        self._fill_channels()
        self.method = Adw.ComboRow(title="Method")
        self.method.set_model(Gtk.StringList.new([label for _, label, _ in METHODS]))
        self.method.connect("notify::selected", lambda *_: self._describe_method())
        self._describe_method()
        self.iface = Adw.ComboRow(title="Wi-Fi interface")
        self.iface_model = Gtk.StringList.new(["Automatic"])
        self.iface.set_model(self.iface_model)
        self.hidden_row, self.hidden = switch_row(
            "Hide network name", "Devices must type the name to join; the QR code still works"
        )
        save_row, self.save_btn = button_row("Save", self._on_save, style="suggested-action")
        rows = (
            self.ssid.widget,
            self.password.widget,
            self.band,
            self.channel,
            self.method,
            self.iface,
            self.hidden_row,
        )
        for row in rows + (save_row,):
            net.add(row)
        self.widget.add(net)

        # ── profiles ──────────────────────────────────────────────────────────
        profiles = Adw.PreferencesGroup(title="Profiles", description="Switch profiles on the Hotspot tab.")
        self.new_profile = EntryField("New profile name")
        create_row, _ = button_row("Create Profile", self._on_create_profile, subtitle="Copy the active profile")
        profiles.add(self.new_profile.widget)
        profiles.add(create_row)
        self.widget.add(profiles)

        # ── startup ───────────────────────────────────────────────────────────
        startup = Adw.PreferencesGroup(title="Startup")
        self.autostart_row, self.autostart = switch_row(
            "Start automatically", "Start at boot and recover after sleep and Wi-Fi changes"
        )
        self.autostart.connect("notify::active", self._on_autostart)
        startup.add(self.autostart_row)
        self.login_row, self.login = switch_row(
            "Show in the tray at login", "Open this app in the system tray when you log in"
        )
        self.login.set_active(login_entry_path().exists())
        self.login.connect("notify::active", self._on_login_start)
        startup.add(self.login_row)
        self.tray_hide_row, self.tray_hide = switch_row(
            "Hide tray icon while the hotspot is off",
            "The panel may tuck it away; some, like waybar, hide it completely",
        )
        self.tray_hide.set_active(bool(load_gui_prefs().get("tray_hide_when_off")))
        self.tray_hide.connect("notify::active", self._on_tray_hide)
        startup.add(self.tray_hide_row)
        self.widget.add(startup)

        # ── hardware ──────────────────────────────────────────────────────────
        self.hardware = Adw.PreferencesGroup(title="Hardware")
        self.card_row = Adw.ActionRow(title="Wi-Fi card", subtitle="Detecting…")
        self.hardware.add(self.card_row)
        self.usb = Adw.ExpanderRow(
            title="USB Wi-Fi adapters", subtitle="Find adapters that can host while staying connected"
        )
        self.usb_label = Gtk.Label(
            xalign=0, wrap=True, selectable=True, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12
        )
        self.usb_label.add_css_class("monospace")
        usb_buttons = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=12)
        for label, args in (("Scan", ("scan-usb",)), ("Recommend", ("recommend",))):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, a=args: self._run_text(a))
            usb_buttons.append(button)
        usb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        usb_box.append(usb_buttons)
        usb_box.append(self.usb_label)
        self.usb.add_row(usb_box)
        self.hardware.add(self.usb)
        self.widget.add(self.hardware)

    # ── updates ───────────────────────────────────────────────────────────────

    def _band(self) -> str:
        index = self.band.get_selected()
        return BANDS[index][0] if index < len(BANDS) else "bg"

    def _fill_channels(self) -> None:
        """The channel list depends on the band; keep the choice when it still exists."""
        keep = self._channels[self.channel.get_selected()][0] if self._channels else "auto"
        self._channels = channel_options(self._band())
        self.channel_model.splice(0, self.channel_model.get_n_items(), [label for _, label in self._channels])
        self.channel.set_selected(index_of(self._channels, keep))

    def _describe_method(self) -> None:
        index = self.method.get_selected()
        self.method.set_subtitle(METHODS[index][2] if index < len(METHODS) else "")

    def _sync(self, key, current, value, setter) -> None:
        """Only overwrite a field the user hasn't changed since the last sync."""
        last = self._synced.get(key)
        if last is None or current == last:
            setter(value)
            self._synced[key] = value

    def update(self, data: dict, detect: dict) -> None:
        config = data.get("config") or {}
        if not config:
            return
        self._updating = True
        try:
            self._sync("ssid", self.ssid.get_text(), config.get("ssid") or "", self.ssid.set_text)
            band_index = 1 if config.get("band") == "a" else 0
            self._sync("band", self.band.get_selected(), band_index, self.band.set_selected)
            channel_index = index_of(self._channels, config.get("channel") or "auto")
            self._sync("channel", self.channel.get_selected(), channel_index, self.channel.set_selected)
            method_index = index_of(METHODS, config.get("method") or "auto")
            self._sync("method", self.method.get_selected(), method_index, self.method.set_selected)

            names = [i["name"] for i in data.get("interfaces") or [] if i.get("type") != "AP"]
            if names != self._ifaces:
                self.iface_model.splice(1, self.iface_model.get_n_items() - 1, names)
                self._ifaces = names
            wanted = config.get("interface")
            iface_index = names.index(wanted) + 1 if wanted in names else 0
            self._sync("iface", self.iface.get_selected(), iface_index, self.iface.set_selected)
            self._sync("hidden", self.hidden.get_active(), bool(config.get("hidden")), self.hidden.set_active)

            autostart = data.get("autostart") or {}
            self.autostart_row.set_sensitive(autostart.get("init") in AUTOSTART_INITS)
            self.autostart.set_active(bool(autostart.get("enabled")))
        finally:
            self._updating = False

    def update_hardware(self, detect: dict) -> None:
        for row in self._hw_rows:
            self.hardware.remove(row)
        self._hw_rows = []
        cap = detect.get("capability") or {}
        if not cap:
            self.card_row.set_subtitle("No Wi-Fi card found" if detect else "Could not run detection")
            return
        parts = [cap.get("chipset"), cap.get("driver") and f"driver {cap['driver']}", cap.get("interface")]
        self.card_row.set_subtitle(esc(" · ".join(p for p in parts if p)))
        for title, subtitle, ok in capability_rows(detect):
            row = Adw.ActionRow(title=esc(title), subtitle=esc(subtitle))
            icon = Gtk.Image(icon_name="emblem-ok-symbolic" if ok else "action-unavailable-symbolic")
            icon.add_css_class("success" if ok else "dim-label")
            row.add_suffix(icon)
            self.hardware.add(row)
            self._hw_rows.append(row)
        # keep the USB expander last
        self.hardware.remove(self.usb)
        self.hardware.add(self.usb)

    # ── actions ───────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        ssid = self.ssid.get_text().strip()
        if not ssid:
            self.window.toast("The network name can't be empty.")
            return
        password = self.password.get_text()
        if password and not 8 <= len(password) <= 63:
            self.window.toast("Passwords need 8–63 characters.")
            return
        band = self._band()
        channel = self._channels[self.channel.get_selected()][0] if self._channels else "auto"
        method = METHODS[self.method.get_selected()][0] if self.method.get_selected() < len(METHODS) else "auto"
        index = self.iface.get_selected()
        iface = self._ifaces[index - 1] if 0 < index <= len(self._ifaces) else ""
        hidden = self.hidden.get_active()

        def work():
            result = self.window.backend.save_config(ssid, password, band, iface, hidden, method, channel)
            if result.ok:
                self._synced.clear()
            return result

        self.window.run_privileged(work, on_success=lambda: self.password.set_text(""))

    def _on_create_profile(self) -> None:
        name = self.new_profile.get_text().strip()
        if not name:
            self.window.toast("Enter a name for the new profile.")
            return
        self.window.run_privileged(
            lambda: self.window.backend.create_profile(name), on_success=lambda: self.new_profile.set_text("")
        )

    def _on_autostart(self, switch, _pspec) -> None:
        if self._updating:
            return
        enabled = switch.get_active()
        self.window.run_privileged(lambda: self.window.backend.set_autostart(enabled))

    def _on_login_start(self, switch, _pspec) -> None:
        try:
            set_login_start(switch.get_active())
        except OSError as exc:
            self.window.toast(f"Could not change the login setting: {exc.strerror or exc}")

    def _on_tray_hide(self, switch, _pspec) -> None:
        hide = switch.get_active()
        try:
            save_gui_prefs({**load_gui_prefs(), "tray_hide_when_off": hide})
        except OSError as exc:
            self.window.toast(f"Could not save the tray setting: {exc.strerror or exc}")
        if self.window.tray is not None:
            self.window.tray.set_hide_when_off(hide)

    def _run_text(self, args) -> None:
        self.usb_label.set_label("Working…")
        self.window.run_async(lambda: self.window.backend.text(*args), self.usb_label.set_label)
