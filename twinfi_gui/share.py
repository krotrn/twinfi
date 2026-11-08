"""Share dialog: QR code + network name + password."""

from __future__ import annotations

from gi.repository import Adw, Gdk, GLib, Gtk

from .compat import Dialog, copy_to_clipboard
from .helpers import qr_pixels, wifi_share_string


def qr_texture(payload: str):
    """A Gdk.Texture of the QR code, or None if the qrcode module is missing."""
    drawn = qr_pixels(payload)
    if drawn is None:
        return None
    side, rgb = drawn
    return Gdk.MemoryTexture.new(side, side, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(rgb), side * 3)


class ShareDialog:
    def __init__(self, parent: Gtk.Window, ssid: str, password: str, hidden: bool = False):
        self.window = Adw.Window(
            transient_for=parent, modal=True, title="Share hotspot", default_width=360, resizable=False
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(Adw.HeaderBar())

        body = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        texture = qr_texture(wifi_share_string(ssid, password, hidden))
        if texture is not None:
            frame = Gtk.Box(halign=Gtk.Align.CENTER)
            frame.add_css_class("card")
            picture = Gtk.Picture.new_for_paintable(texture)
            picture.set_size_request(240, 240)
            frame.append(picture)
            body.append(frame)
            hint = Gtk.Label(label="Point a phone camera at the code to join.", wrap=True)
        else:
            hint = Gtk.Label(label="Install python3-qrcode to show a QR code.", wrap=True)
        hint.add_css_class("dim-label")
        body.append(hint)

        group = Adw.PreferencesGroup()
        for title, value in (("Network name", ssid), ("Password", password)):
            row = Adw.ActionRow(title=title)
            label = Gtk.Label(label=value, selectable=True, wrap=True, xalign=1)
            label.add_css_class("monospace")
            row.add_suffix(label)
            button = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy")
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, v=value: copy_to_clipboard(body, v))
            row.add_suffix(button)
            group.add(row)
        body.append(group)
        self.dialog = Dialog(parent, "Share hotspot", body)

    def present(self) -> None:
        self.dialog.present()
