"""System tray: StatusNotifierItem (KDE / AppIndicator / Ayatana) watcher + host, with DBusMenu context menus."""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

SNI = "org.kde.StatusNotifierItem"
WATCHER_NAMES = ("org.kde.StatusNotifierWatcher", "org.freedesktop.StatusNotifierWatcher")
WATCHER_PATH = "/StatusNotifierWatcher"
DBUSMENU = "com.canonical.dbusmenu"
PROPS = "org.freedesktop.DBus.Properties"

WATCHER_XML = """
<node>
  <interface name="%s">
    <method name="RegisterStatusNotifierItem"><arg type="s" direction="in" name="service"/></method>
    <method name="RegisterStatusNotifierHost"><arg type="s" direction="in" name="service"/></method>
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="ProtocolVersion" type="i" access="read"/>
    <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
    <signal name="StatusNotifierHostRegistered"/>
    <signal name="StatusNotifierHostUnregistered"/>
  </interface>
</node>
"""


def _now():
    return (GLib.get_real_time() // 1000) & 0xFFFFFFFF


class Item:
    """One tray icon: a remote StatusNotifierItem."""

    def __init__(self, tray, key, bus, path):
        self.tray, self.key, self.bus, self.path = tray, key, bus, path
        self.props = {}
        self.tries = 0
        self.icon_dirs = set()
        self._subs = []
        c = tray.conn
        self._subs.append(c.signal_subscribe(bus, SNI, None, path, None, Gio.DBusSignalFlags.NONE, lambda *_: self.refresh()))
        self._watch = Gio.bus_watch_name_on_connection(c, bus, Gio.BusNameWatcherFlags.NONE, None, lambda *_: tray.remove(key))
        self.refresh()

    def destroy(self):
        for s in self._subs:
            self.tray.conn.signal_unsubscribe(s)
        Gio.bus_unwatch_name(self._watch)

    # ---- properties
    def refresh(self):
        self.tray.conn.call(self.bus, self.path, PROPS, "GetAll", GLib.Variant("(s)", (SNI,)), GLib.VariantType("(a{sv})"),
                            Gio.DBusCallFlags.NONE, 2000, None, self._got)

    def _got(self, conn, res):
        try:
            self.props = conn.call_finish(res).unpack()[0]
        except GLib.Error:
            # the app registered before it finished exporting its object (or its main loop is busy): ask again a few times
            self.tries += 1
            if self.tries <= 6 and self.key in self.tray.items:
                GLib.timeout_add(500 * self.tries, lambda: (self.refresh(), False)[1])
            return
        self.tries = 0
        th = self.props.get("IconThemePath")
        if th and th not in self.icon_dirs:
            self.icon_dirs.add(th)
            try:
                Gtk.IconTheme.get_default().append_search_path(th)
            except Exception:
                pass
        self.tray.changed()

    @property
    def status(self):
        return self.props.get("Status", "Active")

    @property
    def title(self):
        tt = self.props.get("ToolTip")
        t = tt[2] if isinstance(tt, (tuple, list)) and len(tt) >= 3 and tt[2] else ""
        return t or self.props.get("Title") or self.props.get("Id") or ""

    def pixbuf(self, size):
        """The icon at `size` px (theme name first, else the largest IconPixmap), or None."""
        attn = self.status == "NeedsAttention"
        fg = Gdk.RGBA(); fg.parse("rgba(255,255,255,0.95)")           # the panel is always dark glass: symbolic icons must be light
        name = (self.props.get("AttentionIconName") if attn else None) or self.props.get("IconName")
        scale = 1
        if name:
            try:
                th = Gtk.IconTheme.get_default()
                if name.startswith("/"):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(name, size, size)
                info = th.lookup_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                if info is not None:
                    if info.is_symbolic():
                        return info.load_symbolic(fg, None, None, None)[0]
                    return info.load_icon()
            except GLib.Error:
                pass
        pm = (self.props.get("AttentionIconPixmap") if attn else None) or self.props.get("IconPixmap") or []
        if pm:
            w, h, data = max(pm, key=lambda p: p[0] * p[1])
            if w > 0 and h > 0 and len(data) >= w * h * 4:
                raw = bytearray(data[:w * h * 4])              # ARGB32, network byte order  ->  RGBA
                for i in range(0, len(raw), 4):
                    a, r, g, b = raw[i:i + 4]
                    raw[i:i + 4] = bytes((r, g, b, a))
                pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(raw)), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
                return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR) if (w, h) != (size, size) else pb
        return None

    # ---- actions
    def _call(self, method, args=None):
        self.tray.conn.call(self.bus, self.path, SNI, method, args, None, Gio.DBusCallFlags.NONE, 2000, None, None)

    def activate(self, x, y):
        if self.props.get("ItemIsMenu"):
            return False                                           # the caller shows the menu instead
        self._call("Activate", GLib.Variant("(ii)", (int(x), int(y))))
        return True

    def secondary(self, x, y):
        self._call("SecondaryActivate", GLib.Variant("(ii)", (int(x), int(y))))

    def scroll(self, delta, horizontal=False):
        self._call("Scroll", GLib.Variant("(is)", (int(delta), "horizontal" if horizontal else "vertical")))

    def native_menu(self, x, y):
        self._call("ContextMenu", GLib.Variant("(ii)", (int(x), int(y))))

    def has_menu(self):
        m = self.props.get("Menu")
        return bool(m) and str(m) != "/"

    def menu_items(self, done):
        """Fetch the DBusMenu and call done(items) with GlassMenu items; done(None) when the app has no menu."""
        mp = str(self.props.get("Menu") or "")
        if not mp or mp == "/":
            done(None); return
        c = self.tray.conn

        def layout(_c, res):
            try:
                _rev, root = c.call_finish(res).unpack()
            except GLib.Error:
                done(None); return
            items = self._convert(root[2], mp)
            done(items or None)

        def shown(_c, res):
            try:
                c.call_finish(res)
            except GLib.Error:
                pass
            c.call(self.bus, mp, DBUSMENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), GLib.VariantType("(u(ia{sv}av))"),
                   Gio.DBusCallFlags.NONE, 3000, None, layout)
        c.call(self.bus, mp, DBUSMENU, "AboutToShow", GLib.Variant("(i)", (0,)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1500, None, shown)

    def _event(self, mp, mid):
        self.tray.conn.call(self.bus, mp, DBUSMENU, "Event", GLib.Variant("(isvu)", (mid, "clicked", GLib.Variant("i", 0), _now())),
                            None, Gio.DBusCallFlags.NONE, 2000, None, None)

    def _convert(self, children, mp):
        out = []
        for ch in children:
            try:
                mid, pr, kids = ch
            except (TypeError, ValueError):
                continue
            if not pr.get("visible", True):
                continue
            if pr.get("type") == "separator":
                if out and out[-1][0] != "sep":
                    out.append(("sep",))
                continue
            lab = str(pr.get("label", "")).replace("__", "\0").replace("_", "").replace("\0", "_")
            en = bool(pr.get("enabled", True))
            if kids or pr.get("children-display") == "submenu":
                sub = self._convert(kids, mp)
                out.append(("sub", None, lab, sub or [("item", "(empty)", lambda: None, False)]))
            elif pr.get("toggle-type") in ("checkmark", "radio"):
                out.append(("check", lab, pr.get("toggle-state", 0) == 1, lambda m=mid: self._event(mp, m)))
            else:
                out.append(("item", lab, lambda m=mid: self._event(mp, m), en))
        while out and out[-1][0] == "sep":
            out.pop()
        return out


class Tray:
    def __init__(self, on_change):
        self.on_change = on_change
        self.items = {}
        self.conn = None
        self._reg = None
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            print("glitterde: no session bus, tray disabled:", e, file=sys.stderr)
            return
        self._info = {n: Gio.DBusNodeInfo.new_for_xml(WATCHER_XML % n).interfaces[0] for n in WATCHER_NAMES}
        for name in WATCHER_NAMES:
            try:
                self.conn.register_object(WATCHER_PATH, self._info[name], self._method, self._get_prop, None)
            except GLib.Error as e:
                print("glitterde: tray watcher object:", e, file=sys.stderr)
            Gio.bus_own_name_on_connection(self.conn, name, Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE,
                                           self._owned, self._lost)

    def _owned(self, conn, name):
        self._emit("StatusNotifierHostRegistered", None)
        GLib.timeout_add(700, self._discover)

    def _discover(self):
        """Items that were already running (and registered with nobody, or with a watcher that has since gone) are picked up by name:
        KStatusNotifierItem / Electron / Qt apps own org.kde.StatusNotifierItem-<pid>-<n>."""
        def got(c, res):
            try:
                names = c.call_finish(res).unpack()[0]
            except GLib.Error:
                return
            for n in names:
                if n.startswith("org.kde.StatusNotifierItem-"):
                    self.add(n, n)
        self.conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None,
                       GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 2000, None, got)
        return False

    def _lost(self, conn, name):
        print("glitterde: tray: could not own %s (another tray host is running?)" % name, file=sys.stderr)

    def _emit(self, sig, params):
        if self.conn is None:
            return
        for n in WATCHER_NAMES:
            try:
                self.conn.emit_signal(None, WATCHER_PATH, n, sig, params)
            except GLib.Error:
                pass

    # ---- watcher interface
    def _get_prop(self, conn, sender, path, iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", [k for k in self.items])
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if prop == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    def _method(self, conn, sender, path, iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            self.add(params.unpack()[0], sender)
        invocation.return_value(None)                    # RegisterStatusNotifierHost: we ARE the host

    def add(self, service, sender):
        if service.startswith("/"):
            bus, p = sender, service
        elif "/" in service:
            bus, p = service.split("/", 1); p = "/" + p
        else:
            bus, p = service, "/StatusNotifierItem"
        key = bus + p
        if key in self.items:
            return
        self.items[key] = Item(self, key, bus, p)
        self._emit("StatusNotifierItemRegistered", GLib.Variant("(s)", (key,)))

    def remove(self, key):
        it = self.items.pop(key, None)
        if it is not None:
            it.destroy()
            self._emit("StatusNotifierItemUnregistered", GLib.Variant("(s)", (key,)))
            self.changed()

    def changed(self):
        try:
            self.on_change()
        except Exception as e:
            print("glitterde: tray redraw failed:", e, file=sys.stderr)

    def visible_items(self):
        return [i for i in self.items.values() if i.props and i.status != "Passive"]
