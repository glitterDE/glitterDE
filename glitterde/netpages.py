"""Settings > Network and Settings > Bluetooth: full pages built from the shared parts in netui.py."""
import socket

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import netbt, netui, services
from .netui import button, clear, ink, note, primary, spinner, Sw
from .widgets import Ico, label


class PageHost(netui.Host):
    """Settings has no toast area: messages appear in a line at the top of the page for a few seconds."""

    def __init__(self):
        self.line = note("", 70)
        self.line.set_no_show_all(True)
        self._t = None

    def toast(self, title, text):
        self.line.set_text("%s: %s" % (title, text))
        self.line.show()
        if self._t:
            GLib.source_remove(self._t)
        self._t = GLib.timeout_add_seconds(9, self._hide)

    def _hide(self):
        self._t = None
        self.line.hide()
        return False

    def open_settings(self, page):
        pass


def _row(text, widget, sub=None):
    r = Gtk.Box(spacing=12)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    v.pack_start(label(text), False, False, 0)
    if sub:
        v.pack_start(note(sub, 60), False, False, 0)
    r.pack_start(v, True, True, 0)
    r.pack_end(widget, False, False, 0)
    return r


class NetworkPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.win, self.host = win, PageHost()
        self.model = m = netui.WifiModel(self.host)
        self.pack_start(self.host.line, False, False, 0)
        # --- connection overview
        self.c_stat = win.card()
        top = Gtk.Box(spacing=14)
        self.ico = Ico("wifi", 30, ink(), 1.4)
        top.pack_start(self.ico, False, False, 4)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.title, self.sub = label("Network", "h1"), label("", "muted")
        v.pack_start(self.title, False, False, 0); v.pack_start(self.sub, False, False, 0)
        top.pack_start(v, True, True, 0)
        self.c_stat.inner.pack_start(top, False, False, 0)
        self.warn = note("", 70)
        self.warn.set_no_show_all(True)
        self.c_stat.inner.pack_start(self.warn, False, False, 0)
        self.grid = Gtk.Grid(column_spacing=18, row_spacing=3)
        self.c_stat.inner.pack_start(self.grid, False, False, 0)
        self.pack_start(self.c_stat, False, False, 0)
        # --- wi-fi
        self.c_wifi = win.card("Wi-Fi")
        self.sw = Sw(lambda on: m.set_wifi(on))
        self.c_wifi.inner.pack_start(_row("Wi-Fi", self.sw), False, False, 2)
        self.air = Sw(lambda on: m.set_airplane(on))
        self.c_wifi.inner.pack_start(_row("Airplane mode", self.air, "Switches off Wi-Fi and Bluetooth together."), False, False, 2)
        self.list = netui.WifiList(m, False)
        self.c_wifi.inner.pack_start(self.list, False, False, 4)
        self.hidden = netui.HiddenForm(m)
        self.c_wifi.inner.pack_start(self.hidden, False, False, 0)
        foot = Gtk.Box(spacing=6)
        self.b_scan = button("Rescan", lambda: m.refresh(rescan=True))
        self.b_hid = button("Join hidden network…", self.hidden.toggle)
        foot.pack_start(self.b_scan, False, False, 0); foot.pack_start(self.b_hid, False, False, 0)
        self.c_wifi.inner.pack_start(foot, False, False, 0)
        self.pack_start(self.c_wifi, False, False, 0)
        # --- saved networks
        self.c_saved = win.card("Saved networks")
        self.saved_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.c_saved.inner.pack_start(self.saved_box, False, False, 0)
        self.pack_start(self.c_saved, False, False, 0)
        self._saved_key = None
        # --- wired + vpn
        self.c_links = win.card("Wired and VPN")
        self.links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.c_links.inner.pack_start(self.links, False, False, 0)
        self.link_rows = {}
        self.pack_start(self.c_links, False, False, 0)
        # --- hotspot
        self.c_hot = win.card("Hotspot")
        self.c_hot.inner.pack_start(note("Share this computer's connection by turning it into a Wi-Fi network. Needs a Wi-Fi adapter that can host.", 70), False, False, 0)
        self.hs_ssid, self.hs_pw = Gtk.Entry(), Gtk.Entry()
        self.hs_ssid.set_text(socket.gethostname()[:30] or "glitterDE"); self.hs_pw.set_placeholder_text("Password (8 or more characters)"); self.hs_pw.set_visibility(False)
        self.c_hot.inner.pack_start(self.hs_ssid, False, False, 0); self.c_hot.inner.pack_start(self.hs_pw, False, False, 0)
        hr = Gtk.Box(spacing=6)
        self.hs_btn = primary("Start hotspot", self._hotspot)
        hr.pack_start(self.hs_btn, False, False, 0)
        self.c_hot.inner.pack_start(hr, False, False, 0)
        self.pack_start(self.c_hot, False, False, 0)
        # --- advanced
        self.c_adv = win.card("Advanced")
        self.c_adv.inner.pack_start(button("Open connection editor (static IP, DNS, 802.1X, VPN setup)…", m.open_editor), False, False, 0)
        self.pack_start(self.c_adv, False, False, 0)
        m.add_listener(self.refresh)
        self.connect("map", lambda *_: (m.add_listener(self.refresh), m.start(), self.refresh()))
        self.connect("unmap", lambda *_: (m.remove_listener(self.refresh), m.stop()))
        self.show_all()
        for w in (self.host.line, self.warn):
            w.hide()

    def _hotspot(self):
        ssid, pw = self.hs_ssid.get_text().strip(), self.hs_pw.get_text()
        if not ssid or len(pw) < 8:
            self.host.toast("Hotspot", "Give it a name and a password of at least 8 characters.")
            return
        self.hs_btn.set_sensitive(False)
        self.model.start_hotspot(ssid, pw, lambda ok, msg: (self.hs_btn.set_sensitive(True), ok and self.host.toast("Hotspot", "%s is on" % ssid)))

    def refresh(self):
        m = self.model
        icon, title, sub = m.summary()
        self.ico.set_icon(icon, ink())
        self.title.set_text(title); self.sub.set_text(sub)
        why = netui.unavailable_note(m)
        self.warn.set_text(why or ""); self.warn.set_visible(bool(why) and m.st["nm"] is not None)
        usable = bool(m.st["nm"])
        # details grid
        clear(self.grid)
        ap = m.connected_ap()
        dev = next((d for d in m.st["devices"] if d["state"] == "connected"), None)
        info = m.details.get(dev["name"], {}) if dev else {}
        rows = [("Address", info.get("ip")), ("Gateway", info.get("gateway")), ("DNS", info.get("dns")), ("Hardware address", info.get("mac")),
                ("Signal", ("%d%%" % ap.signal) if ap and dev and dev["type"] == "wifi" else None)]
        for i, (k, v) in enumerate([r for r in rows if r[1]]):
            self.grid.attach(label(k, "muted"), 0, i, 1, 1); self.grid.attach(label(v), 1, i, 1, 1)
        self.grid.show_all()
        has_wifi = bool(m.wifi_dev)
        self.c_wifi.set_visible(usable and (has_wifi or bool(m.st.get("wifi_hw"))))
        self.sw.set_quiet(m.st.get("wifi_on")); self.sw.set_sensitive(has_wifi and not m.radio_busy)
        self.air.set_quiet(m.st.get("airplane")); self.air.set_sensitive(not m.radio_busy)
        self.b_scan.set_visible(has_wifi); self.b_hid.set_visible(has_wifi)
        self.list.refresh()
        # saved networks (rebuilt only when they change)
        saved = m.saved_wifi()
        key = tuple((v["uuid"], v["name"], v["autoconnect"]) for v in saved)
        if key != self._saved_key:
            self._saved_key = key
            clear(self.saved_box)
            for v in saved:
                r = Gtk.Box(spacing=10)
                r.pack_start(Ico("wifi", 14, ink(0.8), 1.5), False, False, 2)
                r.pack_start(label(v["name"]), True, True, 0)
                sw = Sw(lambda on, u=v["uuid"]: m.set_auto(u, on)); sw.set_quiet(v["autoconnect"]); sw.set_tooltip_text("Connect automatically")
                r.pack_end(netui.two_click(button("Forget", lambda: None), "Forget", lambda u=v["uuid"], n=v["name"]: m.forget(u, n), "Sure?"), False, False, 0)
                r.pack_end(sw, False, False, 6)
                self.saved_box.pack_start(r, False, False, 2)
            if not saved:
                self.saved_box.pack_start(note("No saved networks yet."), False, False, 0)
            self.saved_box.show_all()
        self.c_saved.set_visible(usable and has_wifi)
        # wired + vpn
        want = [("eth:" + d["name"], d) for d in m.wired()] + [("vpn:" + v["uuid"], v) for v in m.vpns()]
        for k in [k for k in self.link_rows if k not in {w[0] for w in want}]:
            self.links.remove(self.link_rows.pop(k))
        for k, d in want:
            row = self.link_rows.get(k)
            if row is None:
                row = self.link_rows[k] = netui.LinkRow(m, "network", "")
                self.links.pack_start(row, False, False, 0)
            if k.startswith("eth:"):
                on = d["state"] == "connected"
                row.set("Ethernet (%s)" % d["name"], {"connected": "Connected", "unavailable": "No cable plugged in"}.get(d["state"], d["state"].capitalize()),
                        "Disconnect" if on else "Connect", lambda d_=d: m.toggle_wired(d_), m.conn_busy == d["name"], d["state"] != "unavailable")
            else:
                on = d["uuid"] in m.active
                row.set(d["name"], "VPN · " + ("Connected" if on else "Off"), "Turn off" if on else "Turn on", lambda d_=d: m.toggle_vpn(d_), m.conn_busy == d["uuid"])
        self.links.show_all()
        if not want:
            self.c_links.hide()
        else:
            self.c_links.show()
        self.c_hot.set_visible(usable and has_wifi)
        self.c_adv.set_visible(True)


class BluetoothPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.win, self.host = win, PageHost()
        self.bt = bt = netbt.Bluetooth(agent_ui=netui.AgentUI(self.host))
        self.pack_start(self.host.line, False, False, 0)
        # --- adapter
        self.c_ad = win.card("Bluetooth")
        self.sw = Sw(self._power)
        self.c_ad.inner.pack_start(_row("Bluetooth", self.sw), False, False, 2)
        self.status = label("", "muted")
        self.c_ad.inner.pack_start(self.status, False, False, 0)
        self.msg = note("", 70)
        self.msg.set_no_show_all(True)
        self.c_ad.inner.pack_start(self.msg, False, False, 0)
        self.vis = Sw(lambda on: bt.set_discoverable(on, lambda ok, m: None if ok else self.host.toast("Bluetooth", m)))
        self.vis_row = _row("Visible to other devices", self.vis, "Needed to pair from a phone or another computer.")
        self.c_ad.inner.pack_start(self.vis_row, False, False, 2)
        nm = Gtk.Box(spacing=6)
        self.name = Gtk.Entry(); self.name.set_placeholder_text("Name of this computer"); self.name.connect("activate", lambda *_: self._rename())
        nm.pack_start(self.name, True, True, 0); nm.pack_start(button("Rename", self._rename), False, False, 0)
        self.name_row = nm
        self.c_ad.inner.pack_start(nm, False, False, 0)
        self.air = Sw(self._airplane)
        self.c_ad.inner.pack_start(_row("Airplane mode", self.air, "Switches off Wi-Fi and Bluetooth together."), False, False, 2)
        self.pack_start(self.c_ad, False, False, 0)
        # --- paired
        self.c_my = win.card("My devices")
        self.paired = netui.BtList(bt, self.host, False, False, "No paired devices yet. Put a device in pairing mode and pair it below.")
        self.c_my.inner.pack_start(self.paired, False, False, 0)
        self.pack_start(self.c_my, False, False, 0)
        # --- nearby
        self.c_near = win.card()
        hd = Gtk.Box(spacing=8)
        hd.pack_start(label("Nearby devices", "h2"), True, True, 0)
        self.spin = Gtk.Spinner(); hd.pack_start(self.spin, False, False, 0)
        self.scan_btn = button("Scan", self._scan); hd.pack_end(self.scan_btn, False, False, 0)
        self.c_near.inner.pack_start(hd, False, False, 0)
        self.near = netui.BtList(bt, self.host, True, False, "")
        self.c_near.inner.pack_start(self.near, False, False, 0)
        self.pack_start(self.c_near, False, False, 0)
        bt.add_listener(self.refresh)
        self.connect("map", self._map); self.connect("unmap", self._unmap)
        self.connect("destroy", lambda *_: (bt.remove_listener(self.refresh), bt.stop()))
        self.show_all()
        for w in (self.host.line, self.msg):
            w.hide()

    def _map(self, *_):
        self.want_scan = True                           # BlueZ may not have answered yet: refresh() starts the scan once it is ready
        self.bt.start()
        self.bt.add_listener(self.refresh)
        self.refresh()

    def _unmap(self, *_):
        self.want_scan = False
        self.bt.stop_scan()

    def _power(self, on):
        self.sw.set_sensitive(False)

        def done(ok, msg):
            if not ok:
                self.host.toast("Bluetooth", msg or "Could not change Bluetooth")
            self.sw.set_sensitive(True)
            self.refresh()
            if ok and on:
                self.want_scan = True
        self.bt.set_power(on, done)

    def _airplane(self, on):
        netbt.set_airplane_mode(on)
        GLib.timeout_add(900, lambda: (self.bt.reload(), self.refresh(), False)[2])

    def _scan(self):
        self.want_scan = False
        (self.bt.stop_scan if self.bt.discovering else self.bt.start_scan)()

    def _rename(self):
        t = self.name.get_text().strip()
        if t and self.bt.available:
            self.bt.rename_adapter(t, lambda ok, m: None if ok else self.host.toast("Bluetooth", m))

    def refresh(self):
        bt = self.bt
        if getattr(self, "want_scan", False) and bt.available and bt.powered:
            self.want_scan = False
            bt.start_scan()
        prob = netui.bt_problem(bt)
        self.status.set_text(netui.bt_summary(bt))
        self.msg.set_text(prob or ""); self.msg.set_visible(bool(prob))
        hard = netbt.rfkill_state("bluetooth")["hard"]
        self.sw.set_quiet(bt.powered)
        self.sw.set_sensitive(bt.available and not hard)
        self.air.set_quiet(netbt.airplane_mode())
        on = bt.available and bt.powered and not hard
        self.vis.set_quiet(bt.discoverable)
        for w in (self.vis_row, self.name_row, self.c_my, self.c_near):
            w.set_visible(on)
        if on and not self.name.is_focus() and not self.name.get_text():
            self.name.set_text(bt.name)
        self.paired.refresh("No paired devices yet. Put a device in pairing mode and pair it below." if on else "")
        self.near.refresh("Searching for devices…" if bt.discovering else "Nothing found. Put the device in pairing mode, then press Scan.")
        self.scan_btn.set_label("Stop" if bt.discovering else "Scan")
        if bt.discovering:
            self.spin.start()
        else:
            self.spin.stop()
