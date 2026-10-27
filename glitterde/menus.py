"""GlassMenu: a themed context menu (own window, closes the moment you choose, never leaves stale pixels)."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from . import appkit, gfx
from .widgets import Ico, compositing, round_shape

from . import scheme
from .scheme import NAVY
MENU_CSS = b"""
.gmenu button { padding: 6px 10px; border-radius: 9px; background: transparent; background-image: none; border: none; box-shadow: none; }
.gmenu button:hover { background-color: rgba(255,255,255,0.20); }
.gmenu button:disabled { opacity: 0.45; }
.gmenu label.gh { font-size: 10px; font-weight: 700; opacity: 0.6; padding: 6px 12px 2px 12px; }
.gmenu label.hint { opacity: 0.6; font-size: 11px; }
.gmenu separator { background-color: rgba(255,255,255,0.22); min-height: 1px; margin: 4px 8px; }
.gmenu label.gc-title { font-size: 17px; font-weight: 700; padding: 4px 8px 0 8px; }
.gmenu label.gc-detail { font-size: 13px; opacity: 0.8; padding: 0 8px 6px 8px; }
.gmenu button.gc-ok { background-image: linear-gradient(135deg, #ff8fd2, #a98bff); color: #ffffff; border-radius: 999px; padding: 8px 24px; font-weight: 700; }
.gmenu button.gc-ok:hover { background-image: linear-gradient(135deg, #ffa3dc, #b9a0ff); }
.gmenu button.gc-ok label { color: #ffffff; }
.gmenu button.gc-cancel { background-color: rgba(255,255,255,0.16); border-radius: 999px; padding: 8px 24px; }
.gmenu.light button.gc-cancel { background-color: rgba(42,45,110,0.10); }
.gmenu button.tile { padding: 10px 4px 7px 4px; border-radius: 12px; background-color: rgba(255,255,255,0.12); }
.gmenu button.tile:hover { background-color: rgba(255,255,255,0.28); }
.gmenu button.tile label { font-size: 10px; }
.gmenu.light label, .gmenu.light button { color: #2a2d6e; }
.gmenu.light button:hover { background-color: rgba(120,130,255,0.20); }
.gmenu.light button.tile { background-color: rgba(255,255,255,0.45); }
.gmenu.light button.tile:hover { background-color: rgba(255,255,255,0.80); }
.gmenu.light separator { background-color: rgba(42,45,110,0.14); }
"""
_installed = False


class GlassMenu(Gtk.Window):
    """items: ("item", label, cb) | ("check", label, checked, cb) | ("sep",) | ("head", label) | ("item", label, cb, enabled)"""

    def __init__(self, items, light=False, theme=None, min_width=210, sticky=False):
        light = light and not scheme.is_dark()          # app menus follow the colour scheme
        global _installed
        super().__init__()
        if not _installed:
            p = Gtk.CssProvider(); p.load_from_data(MENU_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10 + 2)
            _installed = True
        self.th = theme or appkit.theme()
        self.comp = compositing()
        self.set_decorated(False); self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DROPDOWN_MENU)
        self.set_wmclass("glitterde-menu", "glitterde-menu")
        if self.comp:
            self.set_visual(Gdk.Screen.get_default().get_rgba_visual())
        self.light = light
        ctx = self.get_style_context(); ctx.add_class("gmenu")
        if light:
            ctx.add_class("light")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + m)(6)
        box.set_size_request(min_width, -1)
        self._box = box
        self._build(items, box)
        self.add(box)
        self.connect("draw", self._draw)
        if not sticky:                                     # menus close on focus loss / Escape; a confirmation dialog must not
            self.connect("focus-out-event", lambda *_: (GLib.idle_add(self.close_menu), False)[1])
            self.connect("key-press-event", lambda w, ev: (self.close_menu(), True)[1] if ev.keyval == Gdk.KEY_Escape else False)
        if not self.comp:
            self.connect("size-allocate", lambda w, a: round_shape(w, 14))

    # ---------------------------------------------------------------- item builders
    def _ink(self):
        return NAVY if self.light else (1, 1, 1, 0.95)

    def _build(self, items, box, keep_open=False):
        """Item kinds: ("item", label, cb[, enabled]) | ("itemi", icon, label, cb[, enabled[, hint]]) | ("check", label, checked, cb)
        | ("sep",) | ("head", label) | ("tiles", [(icon, label, cb), ...]) | ("sub", icon, label, [items])  (accordion, stays open)."""
        for it in items:
            kind = it[0]
            if kind == "sep":
                box.pack_start(Gtk.Separator(), False, False, 2)
            elif kind == "head":
                l = Gtk.Label(label=it[1].upper(), xalign=0); l.get_style_context().add_class("gh"); box.pack_start(l, False, False, 0)
            elif kind == "tiles":
                row = Gtk.Box(spacing=6, homogeneous=True)
                row.set_margin_bottom(4)
                for icon, lab, cb in it[1]:
                    b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.get_style_context().add_class("tile")
                    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                    ic = Ico(icon, 20, self._ink(), 1.7); ic.set_halign(Gtk.Align.CENTER)
                    l = Gtk.Label(label=lab); v.pack_start(ic, False, False, 0); v.pack_start(l, False, False, 0)
                    b.add(v); b.connect("clicked", lambda _b, f=cb: self._choose(f)); row.pack_start(b, True, True, 0)
                box.pack_start(row, False, False, 0)
            elif kind == "sub":
                _, icon, lab, children = it
                head = self._row(icon, lab, None, True, "chev_down", None)
                rev = Gtk.Revealer(); rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN); rev.set_transition_duration(140)
                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                inner.set_margin_start(14)
                self._build(children, inner, keep_open=True)
                rev.add(inner)
                arrow = head.arrow

                def toggle(_b, rev=rev, arrow=arrow):
                    on = not rev.get_reveal_child()
                    rev.set_reveal_child(on)
                    arrow.set_icon("chev_up" if on else "chev_down"); arrow.queue_draw()
                    GLib.timeout_add(170, self._fit)
                head.connect("clicked", toggle)
                rev.connect("notify::child-revealed", lambda *_: GLib.idle_add(self._fit))      # also when a section closes: the window must shrink back
                box.pack_start(head, False, False, 0); box.pack_start(rev, False, False, 0)
            elif kind == "itemi":
                _, icon, lab, cb = it[:4]
                enabled = it[4] if len(it) > 4 else True
                hint = it[5] if len(it) > 5 else None
                b = self._row(icon, lab, hint, enabled, None, None)
                b.connect("clicked", lambda _b, f=cb: self._choose(f)); box.pack_start(b, False, False, 0)
            elif kind == "check":
                lab, checked, cb = it[1], it[2], it[3]
                b = self._row(None, lab, None, True, None, checked)
                if keep_open:                                   # toggles inside a section update in place and keep the menu open
                    def tog(_b, cb=cb, b=b):
                        b.checked = not b.checked
                        b.tick.set_visible(b.checked); b.tick.queue_draw()
                        GLib.idle_add(lambda: (cb(), False)[1])
                    b.connect("clicked", tog)
                else:
                    b.connect("clicked", lambda _b, f=cb: self._choose(f))
                box.pack_start(b, False, False, 0)
            else:                                               # ("item", label, cb[, enabled])
                lab, cb = it[1], it[2]
                enabled = it[3] if len(it) > 3 else True
                b = self._row(None, lab, None, enabled, None, None)
                b.connect("clicked", lambda _b, f=cb: self._choose(f)); box.pack_start(b, False, False, 0)

    def _row(self, icon, label, hint, enabled, arrow, checked):
        b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.set_sensitive(enabled)
        row = Gtk.Box(spacing=9)
        slot = Gtk.Box(); slot.set_size_request(16, 1)
        if icon:
            row.pack_start(Ico(icon, 15, self._ink(), 1.7), False, False, 0)
        else:
            if checked is not None:                            # check rows reserve the slot and show a tick when on
                tick = Ico("check", 13, self._ink(), 2.0); tick.set_no_show_all(True); tick.set_visible(bool(checked))
                slot.pack_start(tick, False, False, 0); b.tick = tick; b.checked = bool(checked)
            row.pack_start(slot, False, False, 0)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        if hint:
            h = Gtk.Label(label=hint); h.get_style_context().add_class("hint"); row.pack_end(h, False, False, 0)
        if arrow:
            b.arrow = Ico(arrow, 11, self._ink(), 1.8); row.pack_end(b.arrow, False, False, 0)
        b.add(row)
        return b

    def _fit(self):
        """A top-level window grows when its content does but never shrinks by itself: after a section expands or collapses, ask for the
        natural height again (keeping the width), then keep the menu on its monitor."""
        if not self.get_visible():
            return False
        self.resize(max(1, self.get_allocated_width()), 1)
        GLib.idle_add(self._reclamp)
        return False

    def _reclamp(self):
        """Keep the whole menu on its monitor after a section expands."""
        if not self.get_visible():
            return False
        x, y = self.get_position()
        w, h = self.get_allocated_width(), self.get_allocated_height()
        r = _monitor_rect(x + 10, y + 10)
        ny = int(max(r.y + 4, min(r.y + r.height - h - 4, y)))
        if ny != y:
            self.move(x, ny)
        return False

    def _choose(self, cb):
        self.close_menu()
        if cb:
            GLib.idle_add(lambda: (cb(), False)[1])

    def close_menu(self):
        self.hide()
        GLib.idle_add(self.destroy)
        return False

    def _draw(self, w, cr):
        a = self.get_allocation()
        if self.light:
            m = self.th.material("window_light")
        else:
            m = self.th.material("dock")
        if self.comp:
            gfx.comp_glass(cr, a.width, a.height, 14, m, 1.25)
            gfx.stroke_rrect(cr, 0, 0, a.width, a.height, 14, (1, 1, 1, 0.55), 1.2)
        else:
            tr, tg, tb = m["tint"]
            cr.set_source_rgba(tr * 0.8, tg * 0.8, tb * 0.8, 1); cr.paint()
            gfx.stroke_rrect(cr, 0, 0, a.width, a.height, 14, (1, 1, 1, 0.5), 1.2)
        return False

    def popup_at(self, x, y):
        self.show_all()
        w, h = self.get_preferred_width()[1], self.get_preferred_height()[1]
        r = _monitor_rect(x, y)                               # the monitor the pointer is on (multi-monitor aware)
        self.move(int(max(r.x + 4, min(r.x + r.width - w - 4, x))), int(max(r.y + 4, min(r.y + r.height - h - 4, y))))
        self.present()


def _monitor_rect(x, y):
    """Geometry of the monitor containing (x, y) (nearest if off-screen), from the WM-published layout, else GDK."""
    best, bd = None, None
    for mx, my, mw, mh in gfx.gdk_monitors():
        if mw <= 0:
            continue
        dx = max(mx - x, 0, x - (mx + mw - 1)); dy = max(my - y, 0, y - (my + mh - 1))
        if bd is None or dx * dx + dy * dy < bd:
            best, bd = (mx, my, mw, mh), dx * dx + dy * dy
    r = Gdk.Rectangle()
    if best is None:
        scr = Gdk.Screen.get_default(); best = (0, 0, scr.get_width(), scr.get_height())
    r.x, r.y, r.width, r.height = best
    return r


class ChoiceButton(Gtk.Button):
    """Drop-down replacement for Gtk.ComboBoxText that opens a rounded GlassMenu (same small API + 'changed' signal)."""
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, choices=(), light=True, theme=None):
        super().__init__()
        light = light and not scheme.is_dark()
        self.choices, self.active, self.light, self.th = [], None, light, theme
        self.get_style_context().add_class("choicebtn")
        box = Gtk.Box(spacing=10)
        self.lab = Gtk.Label(xalign=0)
        self.lab.set_width_chars(14)
        box.pack_start(self.lab, True, True, 0)
        box.pack_end(Ico("chev_down", 11, NAVY if self.light else (1, 1, 1, 0.9), 1.8), False, False, 0)
        self.add(box)
        for val, lab in choices:
            self.append(val, lab)
        self.connect("clicked", self._open)

    def append(self, val, lab):
        self.choices.append((str(val), lab))

    def get_active_id(self):
        return self.active

    def set_active_id(self, val):
        val = str(val)
        for v, lab in self.choices:
            if v == val:
                changed = self.active != v
                self.active = v
                self.lab.set_text(lab)
                if changed:
                    self.emit("changed")
                return True
        return False

    def _open(self, *_):
        items = [("check", lab, v == self.active, lambda v=v: self.set_active_id(v)) for v, lab in self.choices]
        m = GlassMenu(items, light=self.light, theme=self.th, min_width=max(150, self.get_allocated_width()))
        win = self.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = self.get_allocation()
        m.popup_at(ox + a.x, oy + a.y + a.height + 4)


class GlassConfirm(GlassMenu):
    """A glass confirmation window: title, detail, Cancel / action. Enter confirms, Esc cancels. Centred on the primary monitor."""

    def __init__(self, title, detail, verb, on_ok, theme=None):
        super().__init__([], theme=theme, min_width=380, sticky=True)
        self.on_ok = on_ok
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)
        self.set_wmclass("glitterde-dialog", "glitterde-dialog")
        box = self._box
        t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class("gc-title"); box.pack_start(t, False, False, 6)
        if detail:
            d = Gtk.Label(label=detail, xalign=0); d.set_line_wrap(True); d.set_max_width_chars(44)
            d.get_style_context().add_class("gc-detail"); box.pack_start(d, False, False, 0)
        row = Gtk.Box(spacing=10); row.set_halign(Gtk.Align.END); row.set_margin_top(10); row.set_margin_bottom(4)
        cancel = Gtk.Button(label="Cancel"); cancel.get_style_context().add_class("gc-cancel"); cancel.connect("clicked", lambda *_: self._end(False))
        ok = Gtk.Button(label=verb); ok.get_style_context().add_class("gc-ok"); ok.connect("clicked", lambda *_: self._end(True))
        row.pack_start(cancel, False, False, 0); row.pack_start(ok, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.connect("key-press-event", self._key)
        self._ok = ok

    def _key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self._end(False); return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._end(True); return True
        return False

    def _end(self, ok):
        self.hide()
        GLib.idle_add(self.destroy)
        if ok:
            GLib.idle_add(lambda: (self.on_ok(), False)[1])

    def show_centered(self):
        self.show_all()
        w, h = self.get_preferred_width()[1], self.get_preferred_height()[1]
        mx, my, mw, mh = (gfx.gdk_monitors() or [(0, 0, 0, 0)])[0]
        if mw <= 0:
            r = _monitor_rect(0, 0); mx, my, mw, mh = r.x, r.y, r.width, r.height
        self.move(mx + (mw - w) // 2, my + (mh - h) // 3)
        self._ok.grab_focus()
        self.present()
