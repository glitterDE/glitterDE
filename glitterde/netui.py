"""Shared Wi-Fi / Bluetooth user interface"""
import math
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import netbt, scheme
from .menus import GlassConfirm
from .widgets import Ico, label


class Host:
    """What the UI needs from the program that shows it. Subclass or duck-type."""

    def toast(self, title, text):
        pass

    def open_settings(self, page):
        pass


def ink(alpha=1.0):
    c = scheme.ink()
    return (c[0], c[1], c[2], alpha)


# ============================================================== small widgets
class SignalBars(Gtk.DrawingArea):
    """Four ascending bars; the filled ones show the signal strength (0-100)."""

    def __init__(self, level=0, size=1.0):
        super().__init__()
        self.level, self.k = level, size
        self.set_size_request(int(19 * size), int(15 * size))
        self.set_valign(Gtk.Align.CENTER)

    def set_level(self, level):
        if level != self.level:
            self.level = level
            self.queue_draw()

    def do_draw(self, cr):
        n = 0 if self.level <= 0 else 1 if self.level < 25 else 2 if self.level < 50 else 3 if self.level < 75 else 4
        a = self.get_allocation()
        k = self.k
        for i in range(4):
            h = (4 + i * 3.2) * k
            x, w = (1 + i * 4.6) * k, 3.2 * k
            cr.set_source_rgba(*ink(0.95 if i < n else 0.25))
            r = 1.2 * k
            y = a.height - 1 - h
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.close_path(); cr.fill()
        return False


class Sw(Gtk.Switch):
    """A switch whose state can be set from code without firing the callback."""

    def __init__(self, cb):
        super().__init__()
        self.set_valign(Gtk.Align.CENTER)
        self._id = self.connect("notify::active", lambda s, _p: cb(s.get_active()))

    def set_quiet(self, on):
        on = bool(on)
        if self.get_active() != on:
            self.handler_block(self._id)
            self.set_active(on)
            self.handler_unblock(self._id)


def button(text, cb, css="clear", sensitive=True):
    b = Gtk.Button(label=text)
    b.get_style_context().add_class(css)
    b.set_sensitive(sensitive)
    b.set_focus_on_click(False)
    b.connect("clicked", lambda *_: cb())
    return b


def primary(text, cb):
    b = Gtk.Button(label=text)
    for c in ("pill", "active"):
        b.get_style_context().add_class(c)
    b.set_focus_on_click(False)
    b.connect("clicked", lambda *_: cb())
    return b


def note(text, width=44):
    l = label(text, "muted", ellipsize=False)
    l.set_line_wrap(True); l.set_max_width_chars(width); l.set_xalign(0)
    return l


def spinner(on=True):
    s = Gtk.Spinner()
    if on:
        s.start()
    return s


def clear(box):
    for ch in box.get_children():
        box.remove(ch)


def two_click(btn, text, do, confirm_text="Sure?"):
    """A destructive button that asks for a second click (inline, no extra window: popups close when a dialog takes the focus)."""
    st = {"armed": False, "t": None}

    def reset():
        st["armed"], st["t"] = False, None
        btn.set_label(text)
        return False

    def click(*_):
        if st["armed"]:
            if st["t"]:
                GLib.source_remove(st["t"])
            reset(); do()
        else:
            st["armed"] = True; btn.set_label(confirm_text)
            st["t"] = GLib.timeout_add_seconds(3, reset)
    btn.connect("clicked", click)
    return btn


# ============================================================== questions from the system (pairing agent)
class GlassAsk(GlassConfirm):
    """GlassConfirm with an optional text field; reports Cancel as well. on_ok(text-or-None), on_cancel()."""

    def __init__(self, title, detail, verb, on_ok, on_cancel=None, entry=None, secret=False):
        super().__init__(title, detail, verb, lambda: None)
        self._ok_cb, self._cancel_cb, self._finished, self.entry = on_ok, on_cancel, False, None
        if entry is not None:
            e = Gtk.Entry(); e.set_placeholder_text(entry); e.set_visibility(not secret)
            e.connect("activate", lambda *_: self._end(True))
            kids = self._box.get_children()
            self._box.pack_start(e, False, False, 6)
            self._box.reorder_child(e, len(kids) - 1)
            self.entry = e
        self.connect("destroy", lambda *_: self._end(False, closing=True))

    def _end(self, ok, closing=False):
        if self._finished:
            return
        text = self.entry.get_text().strip() if self.entry is not None else None
        if ok and self.entry is not None and not text:
            return
        self._finished = True
        if not closing:
            self.hide(); GLib.idle_add(self.destroy)
        cb = self._ok_cb if ok else self._cancel_cb
        if cb:
            GLib.idle_add(lambda: (cb(text) if ok else cb(), False)[1])

    def show_centered(self):
        super().show_centered()
        if self.entry is not None:
            self.entry.grab_focus()


class AgentUI:
    """Answers BlueZ pairing questions with glass dialogs (see netbt.Bluetooth.agent_ui)."""

    def __init__(self, host):
        self.host, self.open = host, None

    def _show(self, dlg):
        if self.open is not None:
            try:
                self.open.destroy()
            except Exception:
                pass
        self.open = dlg
        dlg.show_centered()

    def confirm(self, dev, code, reply):
        self._show(GlassAsk("Pair with %s?" % dev, "Make sure this code is also shown on the device:\n\n        %s" % code, "Pair",
                            lambda _t: reply(True), lambda: reply(False)))

    def authorize(self, dev, reply):
        self._show(GlassAsk("Allow %s to connect?" % dev, "", "Allow", lambda _t: reply(True), lambda: reply(False)))

    def pin(self, dev, reply):
        self._show(GlassAsk("PIN for %s" % dev, "Enter the PIN the device asks for (often 0000 or 1234).", "Pair",
                            lambda t: reply(t), lambda: reply(None), entry="PIN"))

    def passkey(self, dev, reply):
        def ok(t):
            try:
                reply(int(t))
            except ValueError:
                reply(None)
        self._show(GlassAsk("Passkey for %s" % dev, "Enter the 6-digit code shown on the device.", "Pair", ok, lambda: reply(None), entry="Passkey"))

    def display(self, dev, code):
        self.host.toast("Bluetooth", "Type %s on %s, then press Enter" % (code, dev))

    def cancel(self):
        if self.open is not None:
            try:
                self.open.destroy()
            except Exception:
                pass
            self.open = None


# ============================================================== Wi-Fi model (state shared by every view)
class WifiModel:
    """Everything about the current network state plus the actions on it. Views register a listener and re-draw from the fields:
    st (status dict), aps (visible networks), saved, active (uuids), details (per device), busy (ssid being joined), results (ssid -> (kind, text))."""
    POLL, RESCAN_EVERY = 5, 3

    def __init__(self, host):
        self.host, self.net = host, netbt.Network()
        self.st = {"nm": None, "wifi_on": False, "devices": [], "wifi_dev": None, "airplane": False, "connectivity": "unknown", "wifi_hw": False}
        self.aps, self.saved, self.active, self.details = [], {}, set(), {}
        self.busy, self.results, self.radio_busy, self.conn_busy = None, {}, False, None
        self.listeners = []
        self._timer, self._n, self._users, self._refreshing, self._again, self._rescan_t = None, 0, 0, False, False, None

    # -------------------------------------------------------------- plumbing
    def add_listener(self, fn):
        if fn not in self.listeners:
            self.listeners.append(fn)

    def remove_listener(self, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)

    def notify(self):
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                import traceback
                traceback.print_exc()

    def start(self):
        self._users += 1
        if self._users == 1:
            self._n = 0
            self.refresh(rescan=True)
            self._timer = GLib.timeout_add_seconds(self.POLL, self._tick)

    def stop(self):
        self._users = max(0, self._users - 1)
        if self._users == 0 and self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self._n += 1
        self.refresh(rescan=(self._n % self.RESCAN_EVERY == 0))
        return True

    # -------------------------------------------------------------- reading
    @property
    def wifi_dev(self):
        return self.st.get("wifi_dev")

    @property
    def available(self):
        return bool(self.st.get("nm"))

    def connected_ap(self):
        return next((a for a in self.aps if a.in_use), None)

    def wired(self):
        return [d for d in self.st.get("devices", []) if d["type"] == "ethernet"]

    def vpns(self):
        return [v for v in self.saved.values() if v["type"] in ("vpn", "wireguard")]

    def saved_wifi(self):
        return sorted((v for v in self.saved.values() if v["type"] in ("802-11-wireless", "wifi")), key=lambda v: v["name"].lower())

    def summary(self):
        """(icon, title, subtitle) for the one-line status at the top of a view."""
        st = self.st
        if st["nm"] is None:
            return "wifi", "Network", "Checking…"
        if not st["nm"]:
            return "wifi", "Network", "NetworkManager is not available"
        ap = self.connected_ap()
        wdev = next((d for d in st["devices"] if d["type"] == "wifi"), None)
        eth = next((d for d in self.wired() if d["state"] == "connected"), None)
        info = self.details.get(wdev["name"] if wdev else "", {}) if ap else self.details.get(eth["name"] if eth else "", {})
        ip = info.get("ip")
        net = {"limited": "No internet", "portal": "Sign-in needed", "none": "No connection"}.get(st.get("connectivity"), "")
        if wdev and wdev["state"].startswith("connecting"):
            return "wifi", "Connecting…", wdev["connection"]
        if ap and st["wifi_on"]:
            bits = [b for b in (ap.band, ("%d Mbps" % ap.rate) if ap.rate else "", ip, net) if b]
            return "wifi", ap.ssid, " · ".join(bits) or "Connected"
        if eth:
            bits = [b for b in (eth["name"], ip, net) if b]
            return "network", "Wired connection", " · ".join(bits)
        if st["airplane"]:
            return "wifi", "Airplane mode", "Wireless radios are off"
        if not st["wifi_on"] and wdev:
            return "wifi", "Wi-Fi is off", "Turn it on to see networks"
        if not wdev and not self.wired():
            return "network", "No network adapter", "Nothing to connect with"
        return "wifi", "Not connected", "Pick a network below"

    # -------------------------------------------------------------- refresh
    def refresh(self, rescan=False):
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True

        def finish():
            self._refreshing = False
            now = time.time()
            for k in [k for k, v in self.results.items() if len(v) > 2 and now - v[2] > 60 and k != self.busy]:
                del self.results[k]                          # an old failure should not stick to a network forever
            self.notify()
            if self._again:
                self._again = False
                self.refresh()

        def got_status(st):
            self.st = st
            if not st["nm"]:
                self.aps, self.saved, self.active, self.details = [], {}, set(), {}
                finish(); return
            self.net.saved_connections(got_saved)

        def got_saved(sv):
            self.saved = sv
            self.net.active_uuids(got_active)

        def got_active(act):
            self.active = act
            if self.st["wifi_on"] and self.wifi_dev:
                if rescan and not self._rescan_t:
                    self.net.rescan(None, self.wifi_dev)                      # results show up ~2 s later: list again then
                    self._rescan_t = GLib.timeout_add(2600, self._after_rescan)
                self.net.scan(got_scan, saved=self.saved)
            else:
                self.aps = []
                got_scan(None)

        def got_scan(rows):
            if rows is not None:
                self.aps = rows
            todo = [d["name"] for d in self.st["devices"] if d["state"] == "connected"][:3]
            self.details = {k: v for k, v in self.details.items() if k in todo}

            def nxt():
                if not todo:
                    finish(); return
                dev = todo.pop(0)
                self.net.details(dev, lambda d: (self.details.__setitem__(dev, d), nxt()))
            nxt()
        self.net.status(got_status)

    def _after_rescan(self):
        self._rescan_t = None
        self.refresh()
        return False

    # -------------------------------------------------------------- actions
    def set_wifi(self, on):
        self.radio_busy = True
        self.notify()

        def done(ok, msg):
            self.radio_busy = False
            if not ok:
                self.host.toast("Wi-Fi", msg or "Could not change Wi-Fi")
            self.refresh(rescan=on)
        self.net.radio(on, done)

    def set_airplane(self, on):
        self.radio_busy = True
        self.notify()
        netbt.set_airplane_mode(on)
        if not on:
            self.net.radio(True, lambda *_: None)

        def later():
            self.radio_busy = False
            self.refresh(rescan=not on)
            return False
        GLib.timeout_add(900, later)

    def connect(self, ap, password=None, hidden=False):
        if self.busy:
            return
        ssid = ap.ssid
        self.busy = ssid
        self.results.pop(ssid, None)
        self.notify()

        def done(ok, kind, msg):
            self.busy = None
            if ok:
                self.results.pop(ssid, None)
                self.host.toast("Wi-Fi", msg)
            else:
                self.results[ssid] = (kind, msg, time.time())
                if kind != "password":
                    self.host.toast("Wi-Fi", "Could not connect to %s: %s" % (ssid, msg))
            self.refresh()
        self.net.connect(ap, password, done, hidden=hidden, dev=self.wifi_dev)

    def connect_hidden(self, ssid, password):
        ap = next((a for a in self.aps if a.ssid == ssid), None) or netbt.AccessPoint(ssid)
        self.connect(ap, password or None, hidden=not any(a.ssid == ssid for a in self.aps))

    def disconnect_wifi(self):
        if self.wifi_dev:
            self.net.disconnect(self.wifi_dev, lambda ok, msg: self.refresh())

    def forget(self, ap_or_uuid, name=None):
        uuid = ap_or_uuid.saved_uuid if isinstance(ap_or_uuid, netbt.AccessPoint) else ap_or_uuid

        def done(ok, msg):
            if not ok:
                self.host.toast("Wi-Fi", msg or "Could not forget the network")
            self.results.pop(name or getattr(ap_or_uuid, "ssid", ""), None)
            self.refresh()
        self.net.forget(uuid, done)

    def set_auto(self, uuid, on):
        self.net.set_autoconnect(uuid, on, lambda ok: self.refresh())

    def toggle_wired(self, dev):
        self.conn_busy = dev["name"]
        self.notify()

        def done(ok, msg):
            self.conn_busy = None
            if not ok:
                self.host.toast("Network", "%s: %s" % (dev["name"], msg or "failed"))
            self.refresh()
        (self.net.disconnect if dev["state"] == "connected" else self.net.device_connect)(dev["name"], done)

    def toggle_vpn(self, v):
        self.conn_busy = v["uuid"]
        self.notify()

        def done(ok, msg):
            self.conn_busy = None
            if not ok:
                self.host.toast("VPN", "%s: %s" % (v["name"], msg or "failed"))
            self.refresh()
        (self.net.deactivate if v["uuid"] in self.active else self.net.activate)(v["uuid"], done)

    def start_hotspot(self, ssid, password, cb):
        def done(ok, msg):
            if not ok:
                self.host.toast("Hotspot", msg or "Could not start the hotspot")
            self.refresh()
            cb(ok, msg)
        self.net.hotspot(ssid, password, done, dev=self.wifi_dev)

    def open_editor(self):
        from . import services
        if services.have("nm-connection-editor"):
            services.fire(["nm-connection-editor"])
        else:
            self.host.toast("Network", "Install nm-connection-editor for advanced network settings.")


# ============================================================== Wi-Fi views

def refit(widget, delay=170):
    """A top-level window grows with its content but is not always told to when a Revealer inside it animates open: ask for the natural size
    again once the animation has run, keeping the width (and, for a popup that hangs from the bottom, the bottom edge)."""
    def go():
        top = widget.get_toplevel()
        if top is None or not isinstance(top, Gtk.Window) or not top.get_visible():
            return False
        gw = top.get_window()
        w = max(1, top.get_allocated_width())
        before = None
        if gw is not None:
            before = (top.get_position(), top.get_allocated_height())
        top.resize(w, 1)

        def settle():
            if gw is not None and before is not None and top.get_visible():
                (x, y), h0 = before
                h1 = top.get_allocated_height()
                scr = Gdk.Screen.get_default()
                if y > scr.get_height() / 2:                       # anchored to the bottom: keep the bottom edge where it was
                    top.move(x, y + h0 - h1)
                else:                                              # otherwise never run off the bottom of the screen
                    top.move(x, max(4, min(y, scr.get_height() - h1 - 4)))
            return False
        GLib.timeout_add(60, settle)
        return False
    GLib.timeout_add(delay, go)


def row_opened(lst, row):
    """A row in a popup list opened or closed. The list sits in a scroller capped at ~250px, so the opened options used to appear
    \"not to expand\" (they were clipped below the cap). Raise the cap while any row is open, scroll the row fully into view and make the
    flyout window itself grow (or shrink back) to fit."""
    sc = lst.get_ancestor(Gtk.ScrolledWindow)
    if sc is None:
        return
    base = getattr(sc, "_glitter_base", None)
    if base is None:
        base = sc._glitter_base = sc.get_max_content_height()
    any_open = any(r.rev.get_reveal_child() for r in lst.rows.values())
    sc.set_max_content_height(base + 260 if any_open else base)
    sc.queue_resize()

    def reveal():
        if row.get_parent() is None or not row.rev.get_reveal_child():
            return False
        pt = row.translate_coordinates(lst, 0, 0)
        if pt:
            sc.get_vadjustment().clamp_page(pt[1], pt[1] + row.get_allocated_height())
        return False
    GLib.timeout_add(180, reveal)
    refit(sc)


class NetRow(Gtk.Box):
    """One Wi-Fi network: click to join, the arrow opens the options (password, auto-connect, disconnect, forget). Updated in place so an
    open password box or a half-typed password survives the periodic refresh."""

    def __init__(self, view, ap):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.view, self.model, self.ap, self.compact = view, view.model, ap, view.compact
        self.pw_wanted = False
        self._seen_res = None
        top = Gtk.Box(spacing=2)
        self.btn = Gtk.Button(); self.btn.set_relief(Gtk.ReliefStyle.NONE); self.btn.set_focus_on_click(False)
        h = Gtk.Box(spacing=11)
        pad = 5 if self.compact else 8
        h.set_margin_top(pad); h.set_margin_bottom(pad); h.set_margin_start(4); h.set_margin_end(4)
        self.bars = SignalBars(ap.signal, 1.0 if self.compact else 1.15)
        h.pack_start(self.bars, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.name, self.sub = label(ap.ssid, "title"), label("", "muted")
        v.pack_start(self.name, False, False, 0); v.pack_start(self.sub, False, False, 0)
        h.pack_start(v, True, True, 0)
        self.right = Gtk.Box(spacing=6)
        h.pack_end(self.right, False, False, 2)
        self.btn.add(h); self.btn.connect("clicked", self._clicked)
        top.pack_start(self.btn, True, True, 0)
        self.arrow = Ico("chev_down", 12, ink(0.8), 1.8)
        self.opt = Gtk.Button(); self.opt.set_relief(Gtk.ReliefStyle.NONE); self.opt.set_focus_on_click(False)
        self.opt.add(self.arrow); self.opt.set_tooltip_text("Options")
        self.opt.connect("clicked", lambda *_: self.toggle())
        top.pack_end(self.opt, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.rev = Gtk.Revealer(); self.rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN); self.rev.set_transition_duration(130)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_margin_start(34); body.set_margin_end(6); body.set_margin_bottom(8)
        self.pw_box = Gtk.Box(spacing=6)
        self.pw = Gtk.Entry(); self.pw.set_visibility(False); self.pw.set_placeholder_text("Password"); self.pw.set_width_chars(14)
        self.pw.connect("activate", lambda *_: self._join())
        self.pw_box.pack_start(self.pw, True, True, 0)
        self.pw_box.pack_start(primary("Join", self._join), False, False, 0)
        body.pack_start(self.pw_box, False, False, 0)
        self.info = note("", 40)
        body.pack_start(self.info, False, False, 0)
        self.auto_row = Gtk.Box(spacing=8)
        self.auto_row.pack_start(label("Connect automatically"), True, True, 0)
        self.auto = Sw(lambda on: self.model.set_auto(self.ap.saved_uuid, on))
        self.auto_row.pack_end(self.auto, False, False, 0)
        body.pack_start(self.auto_row, False, False, 0)
        self.acts = Gtk.Box(spacing=6)
        self.b_disc = button("Disconnect", lambda: self.model.disconnect_wifi())
        self.b_forget = two_click(button("Forget", lambda: None), "Forget", lambda: self.model.forget(self.ap), "Forget this network?")
        self.acts.pack_start(self.b_disc, False, False, 0); self.acts.pack_start(self.b_forget, False, False, 0)
        body.pack_start(self.acts, False, False, 0)
        self.rev.add(body)
        self.pack_start(self.rev, False, False, 0)
        self.show_all()
        self.pw_box.set_no_show_all(True)
        self.pw_box.hide()
        self.update(ap)

    # -- user actions
    def toggle(self, open_=None):
        want = (not self.rev.get_reveal_child()) if open_ is None else open_
        self.rev.set_reveal_child(want)
        self.arrow.set_icon("chev_up" if want else "chev_down")
        if not want:
            self.pw_wanted = False
            self.pw_box.hide()
        self._fill_info()
        row_opened(self.view, self)

    def _clicked(self, *_):
        ap = self.ap
        if self.model.busy:
            return
        if ap.in_use:
            self.toggle(); return
        if ap.enterprise and not ap.saved:
            self.model.host.toast("Wi-Fi", "%s needs a sign-in (802.1X). Opening the connection editor." % ap.ssid)
            self.model.open_editor(); return
        if ap.secured and not ap.saved:
            self.ask_password(); return
        self.model.connect(ap)

    def ask_password(self):
        self.pw_wanted = True
        self.pw_box.show_all()
        self.toggle(True)
        self.pw.grab_focus()

    def _join(self):
        pw = self.pw.get_text()
        if self.ap.secured and "WEP" not in self.ap.security and 0 < len(pw) < 8:
            self.model.results[self.ap.ssid] = ("password", "The password needs at least 8 characters", time.time())
            self.update(self.ap); return
        if not pw:
            return
        self.pw.set_text("")
        self.pw_wanted = False
        self.model.connect(self.ap, pw)

    # -- drawing
    def _fill_info(self):
        ap = self.ap
        bits = []
        if ap.in_use:
            d = self.model.details.get(self.model.wifi_dev or "", {})
            for k, t in (("ip", "Address"), ("gateway", "Gateway"), ("dns", "DNS"), ("mac", "Device")):
                if d.get(k):
                    bits.append("%s: %s" % (t, d[k]))
        if not self.compact or ap.in_use:
            bits.append("Security: %s" % (ap.security or "open"))
        if ap.bssids > 1:
            bits.append("%d access points" % ap.bssids)
        self.info.set_text("\n".join(bits))
        self.info.set_visible(bool(bits) and self.rev.get_reveal_child())

    def update(self, ap):
        self.ap = ap
        m = self.model
        busy = m.busy == ap.ssid
        res = m.results.get(ap.ssid)
        self.bars.set_level(ap.signal)
        self.name.set_text(ap.ssid)
        band = ap.band + (" · %d Mbps" % ap.rate if ap.rate and not self.compact else "") if ap.band else ""
        if busy:
            sub = "Connecting…"
        elif res:
            sub = res[1]
        elif ap.in_use:
            sub = "Connected" + (" · " + band if band else "")
        elif ap.saved:
            sub = "Saved" + (" · " + band if band else "")
        elif ap.enterprise:
            sub = "Needs a sign-in (802.1X)"
        elif ap.secured:
            sub = "Secured" + (" · " + band if band else "")
        else:
            sub = "Open network" + (" · " + band if band else "")
        self.sub.set_text(sub)
        clear(self.right)
        if busy:
            self.right.pack_start(spinner(), False, False, 0)
        elif ap.in_use:
            self.right.pack_start(Ico("check", 14, ink(0.95), 2.0), False, False, 0)
        self.right.show_all()
        self.btn.set_sensitive(not m.busy)
        self.auto_row.set_visible(ap.saved)
        self.auto.set_quiet(ap.autoconnect)
        self.b_disc.set_visible(ap.in_use)
        self.b_forget.set_visible(ap.saved)
        self.acts.set_visible(ap.in_use or ap.saved)
        if res and res[0] == "password" and not busy and res is not self._seen_res:
            self._seen_res = res                         # open the password box once per failure, not on every refresh
            self.ask_password()
        self._fill_info()


class WifiList(Gtk.Box):
    """The visible networks as NetRows, kept in sync with the model without rebuilding."""

    def __init__(self, model, compact=True, empty="No networks found."):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.model, self.compact, self.rows = model, compact, {}
        self.empty = note(empty)
        self.pack_start(self.empty, False, False, 4)
        self.empty.set_no_show_all(True)

    def refresh(self):
        m = self.model
        aps = m.aps if m.st.get("wifi_on") else []
        seen = set()
        for i, ap in enumerate(aps):
            seen.add(ap.ssid)
            row = self.rows.get(ap.ssid)
            if row is None:
                row = self.rows[ap.ssid] = NetRow(self, ap)
                self.pack_start(row, False, False, 0)
            else:
                row.update(ap)
            self.reorder_child(row, i)
        for ssid in [s for s in self.rows if s not in seen]:
            self.remove(self.rows.pop(ssid))
        if not aps:
            self.empty.set_text("Wi-Fi is off." if not m.st.get("wifi_on") else "Looking for networks…" if m._refreshing or m.st.get("nm") is None
                                else "No networks found.")
        self.empty.set_visible(not aps)
        self.reorder_child(self.empty, len(aps))


class LinkRow(Gtk.Box):
    """A wired device or a VPN profile with its connect / disconnect button."""

    def __init__(self, model, icon, title):
        super().__init__(spacing=10)
        self.model = model
        self.set_margin_top(4); self.set_margin_bottom(4); self.set_margin_start(4); self.set_margin_end(4)
        self.ico = Ico(icon, 16, ink(0.95), 1.5)
        self.pack_start(self.ico, False, False, 2)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.name, self.sub = label(title, "title"), label("", "muted")
        v.pack_start(self.name, False, False, 0); v.pack_start(self.sub, False, False, 0)
        self.pack_start(v, True, True, 0)
        self.slot = Gtk.Box()
        self.pack_end(self.slot, False, False, 0)

    def set(self, title, sub, btn_text, cb, busy, enabled=True):
        self.name.set_text(title); self.sub.set_text(sub)
        clear(self.slot)
        self.slot.pack_start(spinner() if busy else button(btn_text, cb, sensitive=enabled), False, False, 0)
        self.slot.show_all()


class HiddenForm(Gtk.Revealer):
    """Join a network that does not broadcast its name."""

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b.set_margin_top(4); b.set_margin_bottom(6)
        self.ssid = Gtk.Entry(); self.ssid.set_placeholder_text("Network name")
        self.pw = Gtk.Entry(); self.pw.set_placeholder_text("Password (leave empty for an open network)"); self.pw.set_visibility(False)
        for e in (self.ssid, self.pw):
            e.connect("activate", lambda *_: self.go())
            b.pack_start(e, False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_end(primary("Join", self.go), False, False, 0)
        b.pack_start(row, False, False, 0)
        self.add(b)

    def go(self):
        ssid = self.ssid.get_text().strip()
        if not ssid:
            self.ssid.grab_focus(); return
        pw = self.pw.get_text()
        if pw and 0 < len(pw) < 8:
            self.model.host.toast("Wi-Fi", "The password needs at least 8 characters"); return
        self.model.connect_hidden(ssid, pw)
        self.pw.set_text("")
        self.set_reveal_child(False)

    def toggle(self):
        self.set_reveal_child(not self.get_reveal_child())
        if self.get_reveal_child():
            self.ssid.grab_focus()


def unavailable_note(model):
    """Why there is nothing to show, in one helpful sentence (or None when NetworkManager is fine)."""
    if model.st["nm"] is None:
        return "Checking the network…"
    if model.st["nm"]:
        return None
    if not model.net.ok:
        return "NetworkManager is not installed. Install it (package: network-manager / NetworkManager) to manage Wi-Fi from here."
    return "NetworkManager is not running. Start it with:  sudo systemctl enable --now NetworkManager"


class WifiPanel(Gtk.Box):
    """The Wi-Fi / network quick-settings popup body."""

    def __init__(self, model, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.model, self.host = model, host
        head = Gtk.Box(spacing=8)
        self.ico = Ico("wifi", 16, ink(), 1.5)
        head.pack_start(self.ico, False, False, 0)
        head.pack_start(label("Network", "big"), True, True, 0)
        self.sw = Sw(lambda on: model.set_wifi(on))
        head.pack_end(self.sw, False, False, 0)
        self.pack_start(head, False, False, 2)
        self.status = label("", "muted")
        self.pack_start(self.status, False, False, 0)
        self.msg = note("")
        self.pack_start(self.msg, False, False, 0)
        self.links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.pack_start(self.links, False, False, 0)
        self.link_rows = {}
        self.list = WifiList(model, True)
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_propagate_natural_height(True); sc.set_max_content_height(250); sc.set_min_content_height(40)
        sc.add(self.list)
        self.sc = sc
        self.pack_start(sc, True, True, 0)
        self.hidden = HiddenForm(model)
        self.pack_start(self.hidden, False, False, 0)
        foot = Gtk.Box(spacing=6)
        self.b_hidden = button("Hidden network…", self.hidden.toggle)
        self.b_scan = button("Rescan", lambda: model.refresh(rescan=True))
        foot.pack_start(self.b_hidden, False, False, 0); foot.pack_start(self.b_scan, False, False, 0)
        self.pack_start(foot, False, False, 2)
        ar = Gtk.Box(spacing=8)
        ar.pack_start(label("Airplane mode"), True, True, 0)
        self.air = Sw(lambda on: model.set_airplane(on))
        ar.pack_end(self.air, False, False, 0)
        self.pack_start(ar, False, False, 2)
        self.b_more = button("Network settings…", lambda: host.open_settings("Network"))
        self.pack_start(self.b_more, False, False, 2)
        self.connect("map", self._map); self.connect("unmap", self._unmap)
        self.show_all()
        self.msg.set_no_show_all(True)

    def _map(self, *_):
        self.model.add_listener(self.refresh)
        self.model.start()
        self.refresh()

    def _unmap(self, *_):
        self.model.remove_listener(self.refresh)
        self.model.stop()

    def refresh(self):
        m = self.model
        icon, title, sub = m.summary()
        self.ico.set_icon(icon, ink())
        self.status.set_text(title + ("  ·  " + sub if sub else ""))
        why = unavailable_note(m)
        self.msg.set_text(why or ""); self.msg.set_visible(bool(why) and m.st["nm"] is not None)
        usable = bool(m.st["nm"])
        self.sw.set_quiet(m.st.get("wifi_on")); self.sw.set_sensitive(usable and bool(self.model.st.get("wifi_hw") or m.wifi_dev) and not m.radio_busy)
        self.air.set_quiet(m.st.get("airplane")); self.air.set_sensitive(not m.radio_busy)
        for w in (self.sc, self.b_hidden, self.b_scan):
            w.set_visible(usable and bool(m.wifi_dev))
        if not usable or not m.wifi_dev:
            self.hidden.set_reveal_child(False)
        self.b_more.set_visible(True)
        # wired + VPN
        want = [("eth:" + d["name"], d) for d in m.wired() if d["state"] != "unavailable" or d["connection"]] + [("vpn:" + v["uuid"], v) for v in m.vpns()]
        for k in [k for k in self.link_rows if k not in {w[0] for w in want}]:
            self.links.remove(self.link_rows.pop(k))
        for k, d in want:
            row = self.link_rows.get(k)
            if row is None:
                row = self.link_rows[k] = LinkRow(m, "network", "")
                self.links.pack_start(row, False, False, 0)
            if k.startswith("eth:"):
                on = d["state"] == "connected"
                row.set("Ethernet", ("Connected · " if on else "Not connected · ") + d["name"], "Disconnect" if on else "Connect",
                        lambda d_=d: m.toggle_wired(d_), m.conn_busy == d["name"])
            else:
                on = d["uuid"] in m.active
                row.set(d["name"], "VPN · " + ("Connected" if on else "Off"), "Turn off" if on else "Turn on", lambda d_=d: m.toggle_vpn(d_),
                        m.conn_busy == d["uuid"])
        self.links.show_all()
        self.list.refresh()


class VpnPanel(Gtk.Box):
    """The VPN quick-settings popup body: every VPN / WireGuard profile with its state, a switch, and which one is carrying the traffic."""

    def __init__(self, model, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.model, self.host = model, host
        head = Gtk.Box(spacing=8)
        self.ico = Ico("shield", 16, ink(), 1.5)
        head.pack_start(self.ico, False, False, 0)
        head.pack_start(label("VPN", "big"), True, True, 0)
        self.pack_start(head, False, False, 2)
        self.status = label("", "muted")
        self.pack_start(self.status, False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.rows, False, False, 0)
        self.link_rows = {}
        self.pack_start(button("Network settings…", lambda: host.open_settings("Network")), False, False, 2)
        self.connect("map", lambda *_: (self.model.add_listener(self.refresh), self.model.start(), self.refresh()))
        self.connect("unmap", lambda *_: (self.model.remove_listener(self.refresh), self.model.stop()))
        self.show_all()

    def refresh(self):
        m = self.model
        vpns = m.vpns()
        on = [v for v in vpns if v["uuid"] in m.active]
        self.ico.set_icon("shield", ink(0.95 if on else 0.55))
        self.status.set_text(("Connected to " + (on[0]["name"] if len(on) == 1 else "%d VPNs" % len(on))) if on else
                             ("Not connected" if vpns else "No VPN profiles yet. Add one in Network settings."))
        for k in [k for k in self.link_rows if k not in {v["uuid"] for v in vpns}]:
            self.rows.remove(self.link_rows.pop(k))
        for v in vpns:
            row = self.link_rows.get(v["uuid"])
            if row is None:
                row = self.link_rows[v["uuid"]] = LinkRow(m, "shield", "")
                self.rows.pack_start(row, False, False, 0)
            up = v["uuid"] in m.active
            kind = "WireGuard" if v["type"] == "wireguard" else "VPN"
            row.set(v["name"], kind + " · " + ("Connected" if up else "Off"), "Turn off" if up else "Turn on", lambda v_=v: m.toggle_vpn(v_), m.conn_busy == v["uuid"])
            row.ico.set_icon("shield", ink(0.95 if up else 0.5))
        self.rows.show_all()


# ============================================================== Bluetooth views
BT_ICONS = {"audio-headset": "volume", "audio-headphones": "volume", "audio-card": "volume", "input-keyboard": "cursor", "input-mouse": "cursor",
            "input-gaming": "cursor", "input-tablet": "cursor", "phone": "phone", "computer": "laptop", "video-display": "monitor",
            "camera-photo": "image", "printer": "doc"}


def bt_msgs(bt):
    if not hasattr(bt, "msgs"):
        bt.msgs = {}
    return bt.msgs


def bt_say(bt, dev, text, secs=8):
    """Show a short message under a device for a few seconds."""
    msgs = bt_msgs(bt)
    msgs[dev.path] = text
    bt._changed()

    def drop():
        if msgs.get(dev.path) == text:
            msgs.pop(dev.path, None)
            bt._changed()
        return False
    GLib.timeout_add_seconds(secs, drop)


def bt_pair(bt, host, dev):
    bt_msgs(bt).pop(dev.path, None)

    def done(ok, msg):
        if ok:
            host.toast("Bluetooth", "Paired with " + dev.title)
            if msg:
                bt_say(bt, dev, msg)
        else:
            bt_say(bt, dev, msg or "Pairing failed", 12)
            host.toast("Bluetooth", "%s: %s" % (dev.title, msg or "Pairing failed"))
    bt.pair(dev, done)


def bt_connect(bt, host, dev):
    bt_msgs(bt).pop(dev.path, None)

    def done(ok, msg):
        if ok:
            host.toast("Bluetooth", "Connected to " + dev.title)
        else:
            bt_say(bt, dev, msg or "Could not connect", 10)
            host.toast("Bluetooth", "%s: %s" % (dev.title, msg or "Could not connect"))
    bt.connect_device(dev, done)


def bt_disconnect(bt, host, dev):
    bt.disconnect_device(dev, lambda ok, msg: None if ok else bt_say(bt, dev, msg or "Could not disconnect"))


class BtRow(Gtk.Box):
    """A paired or nearby Bluetooth device."""

    def __init__(self, view, dev, nearby):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.view, self.bt, self.host, self.dev, self.nearby, self.compact = view, view.bt, view.host, dev, nearby, view.compact
        top = Gtk.Box(spacing=10)
        pad = 5 if self.compact else 8
        top.set_margin_top(pad); top.set_margin_bottom(pad); top.set_margin_start(6); top.set_margin_end(2)
        self.ico = Ico(BT_ICONS.get(dev.icon, "bluetooth"), 16, ink(0.95), 1.5)
        top.pack_start(self.ico, False, False, 2)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.name, self.sub = label(dev.title, "title"), label("", "muted")
        v.pack_start(self.name, False, False, 0); v.pack_start(self.sub, False, False, 0)
        top.pack_start(v, True, True, 0)
        self.slot = Gtk.Box(spacing=4)
        top.pack_end(self.slot, False, False, 0)
        self.arrow = None
        if not nearby:
            self.arrow = Ico("chev_down", 12, ink(0.8), 1.8)
            self.opt = Gtk.Button(); self.opt.set_relief(Gtk.ReliefStyle.NONE); self.opt.set_focus_on_click(False)
            self.opt.add(self.arrow); self.opt.set_tooltip_text("Options")
            self.opt.connect("clicked", lambda *_: self.toggle())
            top.pack_end(self.opt, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.rev = Gtk.Revealer(); self.rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN); self.rev.set_transition_duration(130)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_margin_start(34); body.set_margin_end(6); body.set_margin_bottom(8)
        rn = Gtk.Box(spacing=6)
        self.rename = Gtk.Entry(); self.rename.set_placeholder_text("Name"); self.rename.connect("activate", lambda *_: self._rename())
        rn.pack_start(self.rename, True, True, 0); rn.pack_start(button("Rename", self._rename), False, False, 0)
        body.pack_start(rn, False, False, 0)
        ar = Gtk.Box(spacing=8)
        ar.pack_start(label("Connect automatically"), True, True, 0)
        self.trust = Sw(lambda on: self.bt.set_trusted(self.dev, on))
        ar.pack_end(self.trust, False, False, 0)
        body.pack_start(ar, False, False, 0)
        self.info = note("", 40)
        body.pack_start(self.info, False, False, 0)
        acts = Gtk.Box(spacing=6)
        acts.pack_start(two_click(button("Forget", lambda: None), "Forget", lambda: self.bt.forget(self.dev, lambda ok, m: None), "Forget this device?"),
                        False, False, 0)
        body.pack_start(acts, False, False, 0)
        self.rev.add(body)
        self.pack_start(self.rev, False, False, 0)
        self.show_all()
        self.update(dev)

    def toggle(self):
        want = not self.rev.get_reveal_child()
        self.rev.set_reveal_child(want)
        self.arrow.set_icon("chev_up" if want else "chev_down")
        if want:
            self.rename.set_text(self.dev.title)
        row_opened(self.view, self)

    def _rename(self):
        t = self.rename.get_text().strip()
        if t and t != self.dev.title:
            self.bt.rename(self.dev, t)

    def update(self, dev):
        self.dev = dev
        bt = self.bt
        self.ico.set_icon(BT_ICONS.get(dev.icon, "bluetooth"), ink(0.95 if (dev.connected or self.nearby) else 0.6))
        self.name.set_text(dev.title)
        msg = bt_msgs(bt).get(dev.path)
        bat = "  ·  %d%% battery" % dev.battery if dev.battery is not None else ""
        if dev.connecting:
            sub = "Pairing…" if self.nearby else "Working…"
        elif msg:
            sub = msg
        elif self.nearby:
            r = dev.rssi
            sub = dev.kind + ("" if r is None else "  ·  " + ("Strong" if r > -60 else "Medium" if r > -75 else "Weak") + " signal")
        elif dev.connected:
            sub = "Connected" + bat
        else:
            sub = dev.kind
        self.sub.set_text(sub)
        clear(self.slot)
        if dev.connecting:
            self.slot.pack_start(spinner(), False, False, 4)
        elif self.nearby:
            self.slot.pack_start(primary("Pair", lambda: bt_pair(self.bt, self.host, self.dev)), False, False, 0)
        elif dev.connected:
            self.slot.pack_start(button("Disconnect", lambda: bt_disconnect(self.bt, self.host, self.dev)), False, False, 0)
        else:
            self.slot.pack_start(button("Connect", lambda: bt_connect(self.bt, self.host, self.dev)), False, False, 0)
        self.slot.show_all()
        if not self.nearby:
            self.trust.set_quiet(dev.trusted)
            self.info.set_text("Address: %s" % dev.address)


class BtList(Gtk.Box):
    def __init__(self, bt, host, nearby, compact=True, empty=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.bt, self.host, self.nearby, self.compact, self.rows = bt, host, nearby, compact, {}
        self.empty = note(empty)
        self.pack_start(self.empty, False, False, 4)
        self.empty.set_no_show_all(True)

    def refresh(self, empty=None):
        bt = self.bt
        devs = (bt.nearby_devices() if self.nearby else bt.paired_devices()) if bt.available and bt.powered else []
        seen = set()
        for i, d in enumerate(devs):
            seen.add(d.path)
            row = self.rows.get(d.path)
            if row is None:
                row = self.rows[d.path] = BtRow(self, d, self.nearby)
                self.pack_start(row, False, False, 0)
            else:
                row.update(d)
            self.reorder_child(row, i)
        for p in [p for p in self.rows if p not in seen]:
            self.remove(self.rows.pop(p))
        if empty is not None:
            self.empty.set_text(empty)
        self.empty.set_visible(not devs and bool(self.empty.get_text()))
        self.reorder_child(self.empty, len(devs))
        return len(devs)


def bt_problem(bt):
    """One helpful sentence when Bluetooth cannot work right now, else None."""
    if not netbt.have("bluetoothctl") and bt.service_missing:
        return "Bluetooth support (BlueZ) is not installed. Install the bluez package, then run:  sudo systemctl enable --now bluetooth"
    if bt.service_missing:
        return "The Bluetooth service is not running. Start it with:  sudo systemctl enable --now bluetooth"
    if not bt.available:
        st = netbt.rfkill_state("bluetooth")
        if st["present"]:
            return "Bluetooth is blocked by a hardware switch or key." if st["hard"] else "Bluetooth is switched off (airplane mode or rfkill)."
        return "No Bluetooth adapter found. Plug one in and it will appear here."
    st = netbt.rfkill_state("bluetooth")
    if st["hard"]:
        return "Bluetooth is switched off by a hardware key or switch."
    return None


def bt_summary(bt):
    p = bt_problem(bt)
    if p and not bt.available:
        return "Not available"
    if not bt.powered:
        return "Off"
    c = bt.connected_devices()
    if c:
        return "Connected to " + (c[0].title if len(c) == 1 else "%d devices" % len(c))
    return "On" + (" · searching" if bt.discovering else "")


class BtPanel(Gtk.Box):
    """The Bluetooth quick-settings popup body."""

    def __init__(self, bt, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.bt, self.host = bt, host
        head = Gtk.Box(spacing=8)
        self.ico = Ico("bluetooth", 16, ink(), 1.5)
        head.pack_start(self.ico, False, False, 0)
        head.pack_start(label("Bluetooth", "big"), True, True, 0)
        self.sw = Sw(self._power)
        head.pack_end(self.sw, False, False, 0)
        self.pack_start(head, False, False, 2)
        self.status = label("", "muted")
        self.pack_start(self.status, False, False, 0)
        self.msg = note("")
        self.pack_start(self.msg, False, False, 0)
        self.paired = BtList(bt, host, False, True, "No paired devices yet.")
        self.pack_start(self.paired, False, False, 0)
        self.near_head = Gtk.Box(spacing=8)
        self.near_head.pack_start(label("Nearby devices", "big"), True, True, 0)
        self.spin = Gtk.Spinner()
        self.near_head.pack_start(self.spin, False, False, 0)
        self.scan_btn = button("Scan", self._scan)
        self.near_head.pack_end(self.scan_btn, False, False, 0)
        self.pack_start(self.near_head, False, False, 2)
        self.near = BtList(bt, host, True, True, "")
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_propagate_natural_height(True); sc.set_max_content_height(200); sc.set_min_content_height(20)
        sc.add(self.near)
        self.sc = sc
        self.pack_start(sc, True, True, 0)
        self.b_more = button("Bluetooth settings…", lambda: host.open_settings("Bluetooth"))
        self.pack_start(self.b_more, False, False, 2)
        self.connect("map", self._map); self.connect("unmap", self._unmap)
        self.show_all()
        self.msg.set_no_show_all(True)

    def _map(self, *_):
        self.bt.add_listener(self.refresh)
        self.want_scan = True                           # BlueZ may not have answered yet: refresh() starts the scan once it is ready
        self.bt.start()
        self.refresh()

    def _unmap(self, *_):
        self.want_scan = False
        self.bt.remove_listener(self.refresh)
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

    def _scan(self):
        self.want_scan = False
        (self.bt.stop_scan if self.bt.discovering else self.bt.start_scan)()

    def refresh(self):
        bt = self.bt
        if getattr(self, "want_scan", False) and bt.available and bt.powered:
            self.want_scan = False
            bt.start_scan()
        prob = bt_problem(bt)
        self.ico.set_icon("bluetooth", ink(0.95 if bt.powered else 0.5))
        self.status.set_text(bt_summary(bt))
        self.msg.set_text(prob or ""); self.msg.set_visible(bool(prob))
        usable = bt.available and not netbt.rfkill_state("bluetooth")["hard"]
        self.sw.set_quiet(bt.powered); self.sw.set_sensitive(usable or netbt.rfkill_state("bluetooth")["soft"])
        on = usable and bt.powered
        for w in (self.paired, self.near_head, self.sc):
            w.set_visible(on)
        self.paired.refresh("No paired devices yet." if on else "")
        n = self.near.refresh("Searching for devices…" if bt.discovering else "Nothing nearby. Put the device in pairing mode, then Scan.")
        self.scan_btn.set_label("Stop" if bt.discovering else "Scan")
        if bt.discovering:
            self.spin.start()
        else:
            self.spin.stop()
