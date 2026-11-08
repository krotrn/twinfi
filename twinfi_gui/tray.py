"""System tray icon: a StatusNotifierItem with a com.canonical.dbusmenu menu.

StatusNotifierItem is how apps put an icon in the panel on KDE Plasma, Xfce,
Cinnamon, MATE, Budgie, LXQt, Unity, waybar and other Wayland bars, and
GNOME with the AppIndicator extension (on by default in Ubuntu). The usual
library for it, libayatana-appindicator, is built on GTK 3 and can't load next
to GTK 4, so this speaks the two D-Bus interfaces directly with Gio.

Nothing happens on a desktop without a tray (no StatusNotifierWatcher on the
session bus); ``available`` stays False and the app behaves as before. When a
tray appears later (a panel restart, an extension turned on), the icon
registers itself then.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Tuple

from gi.repository import Gio, GLib

from .helpers import MenuItem

WATCHERS = ("org.kde.StatusNotifierWatcher", "org.freedesktop.StatusNotifierWatcher")
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
PROPERTIES = "org.freedesktop.DBus.Properties"

ITEM_XML = """<node>{}</node>""".format(
    "".join(
        f"""
  <interface name="{name}">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <method name="ProvideXdgActivationToken"><arg type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewMenu"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>"""
        for name in ("org.kde.StatusNotifierItem", "org.freedesktop.StatusNotifierItem")
    )
)

MENU_XML = """<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
  </interface>
</node>"""


def svg_pixmaps(svg: bytes, sizes=(16, 22, 24, 32, 48)) -> list:
    """``IconPixmap`` renderings of ``svg`` (ARGB32, network byte order).

    The fallback for trays whose icon theme lacks ``IconName``; [] when SVG
    can't be rendered here.
    """
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError):
        return []
    pixmaps = []
    for size in sizes:
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.set_size(size, size)
            loader.write(svg)
            loader.close()
            pixbuf = loader.get_pixbuf().add_alpha(False, 0, 0, 0)
        except GLib.Error:
            return []
        width, height, stride = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride()
        pixels = pixbuf.get_pixels()
        rgba = b"".join(pixels[y * stride : y * stride + width * 4] for y in range(height))
        argb = bytearray(len(rgba))
        argb[0::4], argb[1::4], argb[2::4], argb[3::4] = rgba[3::4], rgba[0::4], rgba[1::4], rgba[2::4]
        pixmaps.append((width, height, bytes(argb)))
    return pixmaps


def register_object(bus: Gio.DBusConnection, path: str, iface: Gio.DBusInterfaceInfo, method_call) -> int:
    """Export ``iface`` at ``path``; Properties calls also go to ``method_call``.

    GLib 2.84 added register_object_with_closures2 and PyGObject now deprecates
    the older closure form, which is all GLib < 2.84 has.
    """
    register = getattr(bus, "register_object_with_closures2", None) or bus.register_object
    return register(path, iface, method_call, None, None)


def _props_call(props: dict, method: str, params: GLib.Variant, invocation: Gio.DBusMethodInvocation) -> None:
    """Answer org.freedesktop.DBus.Properties calls from a dict of variants."""
    if method == "Get":
        name = params.unpack()[1]
        if name in props:
            invocation.return_value(GLib.Variant("(v)", (props[name],)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownProperty", name)
    elif method == "GetAll":
        invocation.return_value(GLib.Variant("(a{sv})", (props,)))
    else:
        invocation.return_dbus_error("org.freedesktop.DBus.Error.PropertyReadOnly", "Properties are read-only")


class TrayIcon:
    """One tray icon. ``on_activate(token)`` runs on a click on the icon (``token``
    is the xdg-activation token for Wayland, or None); ``on_menu(key)`` on a menu
    item; ``on_change(available)`` whenever a tray starts or stops showing it.
    """

    def __init__(
        self,
        item_id: str,
        title: str,
        on_activate: Callable[[Optional[str]], None],
        on_menu: Callable[[str], None],
        on_change: Optional[Callable[[bool], None]] = None,
        icon_theme_path: str = "",
    ):
        self.item_id, self.title, self.icon_theme_path = item_id, title, icon_theme_path
        self.on_activate, self.on_menu, self.on_change = on_activate, on_menu, on_change
        self.icon_name = ""
        self.pixmaps: list = []
        self.status = "Active"
        self.tooltip = ("", "")
        self.items: List[MenuItem] = []
        self._nodes: Dict[int, Tuple[Optional[MenuItem], List[int]]] = {0: (None, [])}
        self.revision = 1
        self.available = False
        self._watcher: Optional[str] = None
        self._have_name = False
        self._token: Optional[str] = None
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self.bus = None
            return
        self._ids = [
            register_object(self.bus, ITEM_PATH, iface, self._item_call)
            for iface in Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces
        ]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._ids.append(register_object(self.bus, MENU_PATH, menu, self._menu_call))
        self._owner = Gio.bus_own_name_on_connection(
            self.bus, self.name, Gio.BusNameOwnerFlags.NONE, self._on_name_acquired, None
        )
        self._watches = [
            Gio.bus_watch_name_on_connection(
                self.bus, watcher, Gio.BusNameWatcherFlags.NONE, self._on_watcher_appeared, self._on_watcher_vanished
            )
            for watcher in WATCHERS
        ]

    # ── public ────────────────────────────────────────────────────────────────

    def update(
        self, icon_name: str, title: str, body: str, items: List[MenuItem], pixmaps: list = (), status: str = "Active"
    ) -> None:
        """Show a new state; emits only the change signals that apply.

        ``status`` is "Active", or "Passive" to let the panel hide the icon.
        """
        if status != self.status:
            self.status = status
            self._emit_item("NewStatus", GLib.Variant("(s)", (status,)))
        if icon_name != self.icon_name:
            self.icon_name, self.pixmaps = icon_name, list(pixmaps)
            self._emit_item("NewIcon")
        if (title, body) != self.tooltip:
            self.tooltip = (title, body)
            self._emit_item("NewToolTip")
        if items != self.items:
            self.items = list(items)
            self._nodes = self._number(self.items)
            self.revision += 1
            self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (self.revision, 0)))

    def close(self) -> None:
        if self.bus is None:
            return
        for watch in self._watches:
            Gio.bus_unwatch_name(watch)
        Gio.bus_unown_name(self._owner)
        for reg in self._ids:
            self.bus.unregister_object(reg)
        self.bus = None
        self._set_available(False)

    # ── registration with the tray ────────────────────────────────────────────

    def _on_name_acquired(self, *_):
        self._have_name = True
        self._register()

    def _on_watcher_appeared(self, _bus, name, _owner):
        if self._watcher is None:
            self._watcher = name
            self._register()

    def _on_watcher_vanished(self, _bus, name):
        if name == self._watcher:
            self._watcher = None
            self._set_available(False)

    def _register(self) -> None:
        if self.bus is None or not self._have_name or self._watcher is None:
            return
        watcher = self._watcher

        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error:
                self._set_available(False)
                return
            self._set_available(watcher == self._watcher)

        self.bus.call(
            watcher,
            "/StatusNotifierWatcher",
            watcher,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self.name,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            done,
        )

    def _set_available(self, available: bool) -> None:
        if available != self.available:
            self.available = available
            if self.on_change:
                self.on_change(available)

    def _emit(self, path: str, iface: str, signal: str, params: Optional[GLib.Variant] = None) -> None:
        if self.bus is not None:
            self.bus.emit_signal(None, path, iface, signal, params)

    def _emit_item(self, signal: str, params: Optional[GLib.Variant] = None) -> None:
        for iface in ("org.kde.StatusNotifierItem", "org.freedesktop.StatusNotifierItem"):
            self._emit(ITEM_PATH, iface, signal, params)

    # ── org.kde.StatusNotifierItem ────────────────────────────────────────────

    def _item_props(self) -> dict:
        v = GLib.Variant
        return {
            "Category": v("s", "Hardware"),
            "Id": v("s", self.item_id),
            "Title": v("s", self.title),
            "Status": v("s", self.status),
            "WindowId": v("i", 0),
            "IconName": v("s", self.icon_name),
            "IconThemePath": v("s", self.icon_theme_path),
            "IconPixmap": v("a(iiay)", self.pixmaps),
            "OverlayIconName": v("s", ""),
            "OverlayIconPixmap": v("a(iiay)", []),
            "AttentionIconName": v("s", ""),
            "AttentionIconPixmap": v("a(iiay)", []),
            "AttentionMovieName": v("s", ""),
            "ToolTip": v("(sa(iiay)ss)", (self.icon_name, [], *self.tooltip)),
            "ItemIsMenu": v("b", False),
            "Menu": v("o", MENU_PATH),
        }

    def _item_call(self, _bus, _sender, _path, iface, method, params, invocation):
        if iface == PROPERTIES:
            _props_call(self._item_props(), method, params, invocation)
            return
        if method in ("Activate", "SecondaryActivate"):
            token, self._token = self._token, None
            GLib.idle_add(lambda: self.on_activate(token) and False)
        elif method == "ProvideXdgActivationToken":
            self._token = params.unpack()[0]
        invocation.return_value(None)

    # ── com.canonical.dbusmenu ────────────────────────────────────────────────

    @staticmethod
    def _number(items: List[MenuItem]) -> Dict[int, Tuple[Optional[MenuItem], List[int]]]:
        """Give every item an id (depth first from 1; 0 is the root): id -> (item, child ids)."""
        nodes: Dict[int, Tuple[Optional[MenuItem], List[int]]] = {0: (None, [])}

        def add(item: MenuItem, parent: int) -> None:
            item_id = len(nodes)
            nodes[item_id] = (item, [])
            nodes[parent][1].append(item_id)
            for child in item.children:
                add(child, item_id)

        for item in items:
            add(item, 0)
        return nodes

    def _menu_item_props(self, item_id: int) -> dict:
        v = GLib.Variant
        item, children = self._nodes[item_id]
        if item is None:
            return {"children-display": v("s", "submenu")}
        if item.key == "-":
            return {"type": v("s", "separator"), "visible": v("b", item.visible)}
        props = {
            # dbusmenu labels use "_" for mnemonics; network names may contain one.
            "label": v("s", item.label.replace("_", "__")),
            "enabled": v("b", item.enabled),
            "visible": v("b", item.visible),
        }
        if children:
            props["children-display"] = v("s", "submenu")
        if item.toggle:
            props["toggle-type"] = v("s", item.toggle)
            props["toggle-state"] = v("i", int(item.checked))
        return props

    def _layout(self, item_id: int) -> tuple:
        """``(ia{sv}av)`` for an item and everything below it."""
        children = [GLib.Variant("(ia{sv}av)", self._layout(child)) for child in self._nodes[item_id][1]]
        return item_id, self._menu_item_props(item_id), children

    def _known(self, item_id: int) -> bool:
        return item_id in self._nodes

    def _clicked(self, item_id: int) -> None:
        item, children = self._nodes.get(item_id, (None, []))
        if item is not None and not children:
            key = item.key
            GLib.idle_add(lambda: self.on_menu(key) and False)

    def _menu_call(self, _bus, _sender, _path, iface, method, params, invocation):
        v = GLib.Variant
        if iface == PROPERTIES:
            props = {
                "Version": v("u", 3),
                "TextDirection": v("s", "ltr"),
                "Status": v("s", "normal"),
                "IconThemePath": v("as", []),
            }
            _props_call(props, method, params, invocation)
        elif method == "GetLayout":
            parent = params.unpack()[0]
            if not self._known(parent):
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", f"No item {parent}")
                return
            invocation.return_value(v("(u(ia{sv}av))", (self.revision, self._layout(parent))))
        elif method == "GetGroupProperties":
            ids = [i for i in params.unpack()[0] if self._known(i)]
            invocation.return_value(v("(a(ia{sv}))", ([(i, self._menu_item_props(i)) for i in ids],)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            props = self._menu_item_props(item_id) if self._known(item_id) else {}
            if name in props:
                invocation.return_value(v("(v)", (props[name],)))
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", f"No property {name}")
        elif method == "Event":
            item_id, event = params.unpack()[:2]
            if event == "clicked":
                self._clicked(item_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            errors = []
            for item_id, event, _data, _time in params.unpack()[0]:
                if not self._known(item_id):
                    errors.append(item_id)
                elif event == "clicked":
                    self._clicked(item_id)
            invocation.return_value(v("(ai)", (errors,)))
        elif method == "AboutToShow":
            invocation.return_value(v("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(v("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
