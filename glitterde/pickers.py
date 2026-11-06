"""Glass replacements for GTK's stock chooser dialogs: application chooser, font chooser and colour chooser.

    app  = choose_app(parent, "text/plain")                 # Gio.AppInfo, or None when cancelled
    font = choose_font(parent, "Inter 11")                  # Pango font string ("Inter Bold 11"), or None
    rgb  = choose_color(parent, (0.97, 0.47, 0.78))         # (r, g, b) floats 0..1, or None

    FontButton / ColorButton are drop-in replacements for Gtk.FontButton / Gtk.ColorButton (same small API and the same
    "font-set" / "color-set" signals) that open these dialogs.

Like GlassPrompt and the file chooser they are glass windows that run a nested main loop and return the answer. The decisions (filtering
apps, HSV maths, hex parsing, matching a font style) are plain functions at the top, independent of GTK.
"""
import colorsys
import re

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango, PangoCairo  # noqa: E402

from . import appkit, gfx, scheme
from .menus import ChoiceButton
from .widgets import Ico, label

SAMPLE = "The quick brown fox jumps over the lazy dog\n0123456789   ÀÉÎÕÜ ß æø   { } [ ] ( ) < > ; : = + -"


# ------------------------------------------------------------------------------------------------------------------------ pure logic
def hsv_to_rgb(h, s, v):
    return colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))


def rgb_to_hsv(r, g, b):
    return colorsys.rgb_to_hsv(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb[:3])


def parse_hex(text):
    """(r, g, b) floats from '#rgb', '#rrggbb' or the same without '#'; None when it is not a colour."""
    t = text.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{3}|[0-9a-fA-F]{6}", t):
        return None
    if len(t) == 3:
        t = "".join(ch * 2 for ch in t)
    return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def app_matches(app, query):
    """Every word of the query appears in the app's name, description, command or id (case-insensitive)."""
    words = query.lower().split()
    if not words:
        return True
    hay = " ".join(str(x or "") for x in (app.get_display_name(), app.get_description(), app.get_executable(), app.get_id())).lower()
    return all(w in hay for w in words)


def app_sections(recommended, others, query=""):
    """([recommended], [other applications]) after filtering by the search words; an app is never listed twice."""
    seen, rec, rest = set(), [], []
    for app in recommended:
        if app.get_id() not in seen and app_matches(app, query):
            seen.add(app.get_id())
            rec.append(app)
    for app in sorted(others, key=lambda a: (a.get_display_name() or "").casefold()):
        if app.get_id() not in seen and app_matches(app, query):
            seen.add(app.get_id())
            rest.append(app)
    return rec, rest


def closest_face(faces, weight, style, stretch):
    """Index of the face (name, weight, style, stretch) closest to the wanted one; ties go to the first."""
    best, best_d = 0, None
    for i, (_, w, s, st) in enumerate(faces):
        d = abs(int(w) - int(weight)) + (0 if int(s) == int(style) else 1000) + abs(int(st) - int(stretch)) * 10
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def fmt_size(pt):
    return ("%d" % round(pt)) if abs(pt - round(pt)) < 0.05 else ("%.1f" % pt)


# ------------------------------------------------------------------------------------------------------------------------ shared dialog base
class _Chooser(appkit.GlassDialog):
    """Modal glass dialog with Cancel / OK that returns an answer from run()."""

    def __init__(self, title, parent, size, ok="OK"):
        super().__init__(title, getattr(parent, "wm_class", None) or "glitterde-chooser", parent=parent, size=size)
        self.set_modal(True)
        self._result, self._loop = None, None
        try:                                                   # GlassDialog closes on any Escape: use our own key handler
            sid = GObject.signal_lookup("key-press-event", Gtk.Widget)
            GObject.signal_handlers_disconnect_matched(self, GObject.SignalMatchType.ID, sid, 0, None, None, None)
        except Exception:
            pass
        self.connect("key-press-event", self._on_key)
        self.ok_btn = Gtk.Button(label=ok)
        self.ok_btn.get_style_context().add_class("pill")
        self.ok_btn.get_style_context().add_class("active")
        self.ok_btn.connect("clicked", lambda *_: self._accept())
        self.close_btn.set_label("Cancel")
        row = self.close_btn.get_parent()
        row.remove(self.close_btn)
        row.pack_end(self.ok_btn, False, False, 6)
        row.pack_end(self.close_btn, False, False, 0)
        self.connect("destroy", lambda *_: self._loop and self._loop.quit())

    def _on_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.ok_btn.get_sensitive():
            self._accept()
            return True
        return self._extra_key(ev)

    def _extra_key(self, ev):
        return False

    def _accept(self):
        raise NotImplementedError

    def _finish(self, result):
        self._result = result
        self.destroy()

    def run(self):
        self._loop = GLib.MainLoop()
        self.show_all()
        self.present()
        self._loop.run()
        return self._result


# ------------------------------------------------------------------------------------------------------------------------ applications
class AppChooser(_Chooser):
    def __init__(self, parent=None, content_type="application/octet-stream", title="Open with", ok="Open"):
        super().__init__(title, parent, (520, 580), ok)
        try:
            self.recommended = [a for a in Gio.AppInfo.get_all_for_type(content_type) if a.should_show()]
        except Exception:
            self.recommended = []
        self.others = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        box = self.body
        for m, v in (("start", 14), ("end", 14), ("top", 12), ("bottom", 10)):
            getattr(box, "set_margin_" + m)(v)
        box.pack_start(label(title, "proptitle", 0.0), False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search applications")
        self.entry.connect("changed", lambda *_: self._fill())
        box.pack_start(self.entry, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda lb, r: self._accept())
        self.list.connect("row-selected", lambda *_: self._sync_ok())
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(380)
        sw.add(self.list)
        self.sw = sw
        box.pack_start(sw, True, True, 0)
        self.connect("map", lambda *_: self.entry.grab_focus())
        self._fill()

    def _fill(self):
        for ch in self.list.get_children():
            self.list.remove(ch)
        rec, rest = app_sections(self.recommended, self.others, self.entry.get_text())
        for title, apps in (("Recommended", rec), ("All applications" if rec else "Applications", rest)):
            if not apps:
                continue
            hdr = Gtk.ListBoxRow()
            hdr.app = None
            hdr.set_selectable(False)
            hdr.set_activatable(False)
            hdr.add(label(title, "muted"))
            self.list.add(hdr)
            for a in apps:
                self.list.add(self._row(a))
        self.list.show_all()
        first = next((r for r in self.list.get_children() if r.app is not None), None)
        if first is not None:
            self.list.select_row(first)
        self._sync_ok()

    @staticmethod
    def _row(app):
        r = Gtk.ListBoxRow()
        r.app = app
        h = Gtk.Box(spacing=12)
        h.set_border_width(3)
        img = Gtk.Image()
        icon = app.get_icon()
        if icon is not None:
            img.set_from_gicon(icon, Gtk.IconSize.DND)
        img.set_pixel_size(32)
        h.pack_start(img, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(label(app.get_display_name() or app.get_id() or "", None), False, False, 0)
        if app.get_description():
            col.pack_start(label(app.get_description(), "muted"), False, False, 0)
        h.pack_start(col, True, True, 0)
        r.add(h)
        return r

    def _sync_ok(self):
        r = self.list.get_selected_row()
        self.ok_btn.set_sensitive(r is not None and r.app is not None)

    def _extra_key(self, ev):
        if ev.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            rows = [r for r in self.list.get_children() if r.app is not None]
            if rows:
                cur = self.list.get_selected_row()
                i = rows.index(cur) if cur in rows else -1
                nxt = rows[max(0, min(len(rows) - 1, i + (1 if ev.keyval == Gdk.KEY_Down else -1)))]
                self.list.select_row(nxt)
                y = nxt.translate_coordinates(self.list, 0, 0)
                adj = self.sw.get_vadjustment()
                if y:
                    h = nxt.get_allocated_height()
                    if y[1] < adj.get_value():
                        adj.set_value(y[1])
                    elif y[1] + h > adj.get_value() + adj.get_page_size():
                        adj.set_value(y[1] + h - adj.get_page_size())
            return True
        return False

    def _accept(self):
        r = self.list.get_selected_row()
        if r is not None and r.app is not None:
            self._finish(r.app)


def choose_app(parent=None, content_type="application/octet-stream", title="Open with", ok="Open"):
    """The chosen Gio.AppInfo, or None when cancelled."""
    return AppChooser(parent, content_type, title, ok).run()


# ------------------------------------------------------------------------------------------------------------------------ fonts
class FontChooser(_Chooser):
    def __init__(self, parent=None, current="Sans 10", title="Choose font", ok="Select", mono=False):
        super().__init__(title, parent, (620, 560), ok)
        self.fams = {f.get_name(): f for f in PangoCairo.font_map_get_default().list_families()}
        self.faces, self.family = [], ""
        cur = Pango.FontDescription.from_string(current or "Sans 10")
        want_family = (cur.get_family() or "Sans").split(",")[0].strip()
        size = cur.get_size() / Pango.SCALE if cur.get_size() > 0 else 10.0
        self.want = (cur.get_weight(), cur.get_style(), cur.get_stretch())
        box = self.body
        for m, v in (("start", 14), ("end", 14), ("top", 12), ("bottom", 10)):
            getattr(box, "set_margin_" + m)(v)
        box.pack_start(label(title, "proptitle", 0.0), False, False, 0)
        top = Gtk.Box(spacing=8)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search fonts")
        self.entry.set_hexpand(True)
        top.pack_start(self.entry, True, True, 0)
        self.mono = Gtk.CheckButton(label="Monospace only")
        self.mono.set_active(mono)
        top.pack_start(self.mono, False, False, 0)
        box.pack_start(top, False, False, 0)
        mid = Gtk.Box(spacing=12)
        self.store = Gtk.ListStore(str, bool)
        fams = sorted(((n, f.is_monospace()) for n, f in self.fams.items()), key=lambda x: x[0].casefold())
        for n, m in fams:
            self.store.append([n, m])
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.tree = Gtk.TreeView(model=self.filter)
        self.tree.set_headers_visible(False)
        self.tree.set_enable_search(False)
        r = Gtk.CellRendererText()
        r.set_padding(8, 4)
        r.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.tree.append_column(Gtk.TreeViewColumn("Font", r, text=0))
        self.tree.get_selection().connect("changed", lambda *_: self._family_changed())
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_size_request(250, 250)
        sw.add(self.tree)
        mid.pack_start(sw, False, True, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.pack_start(label("Style", "h2"), False, False, 0)
        self.style = ChoiceButton(light=True, theme=appkit.theme())
        self.style.connect("changed", lambda *_: self._update_preview())
        side.pack_start(self.style, False, False, 0)
        side.pack_start(label("Size", "h2"), False, False, 4)
        self.size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 6, 48, 1)
        self.size.set_digits(0)
        self.size.set_value(max(6, min(48, round(size))))
        self.size.set_value_pos(Gtk.PositionType.RIGHT)
        self.size.connect("value-changed", lambda *_: self._update_preview())
        side.pack_start(self.size, False, False, 0)
        self.result_lbl = label("", "muted", 0.0, ellipsize=False)
        self.result_lbl.set_line_wrap(True)
        side.pack_start(self.result_lbl, False, False, 8)
        mid.pack_start(side, True, True, 0)
        box.pack_start(mid, True, True, 0)
        prev = Gtk.Box()
        prev.get_style_context().add_class("card2")
        prev.set_border_width(10)
        self.preview = Gtk.Label(label=SAMPLE)
        self.preview.set_xalign(0)
        self.preview.set_line_wrap(True)
        self.preview.set_selectable(False)
        self.preview.set_size_request(-1, 110)
        self.preview.set_valign(Gtk.Align.CENTER)
        prev.pack_start(self.preview, True, True, 4)
        box.pack_start(prev, False, False, 0)
        self.entry.connect("changed", lambda *_: self.filter.refilter())
        self.mono.connect("toggled", lambda *_: self.filter.refilter())
        self._select_family(want_family)
        self.connect("map", lambda *_: self.entry.grab_focus())

    def _visible(self, model, it, _d=None):
        name, mono = model.get_value(it, 0), model.get_value(it, 1)
        if self.mono.get_active() and not mono:
            return False
        q = self.entry.get_text().strip().lower()
        return not q or q in name.lower()

    def _select_family(self, name):
        for row in self.filter:
            if row[0].lower() == name.lower():
                self.tree.get_selection().select_path(row.path)
                self.tree.scroll_to_cell(row.path, None, True, 0.5, 0.0)
                return
        first = self.filter.get_iter_first()
        if first is not None:
            self.tree.get_selection().select_iter(first)

    def _family_changed(self):
        model, it = self.tree.get_selection().get_selected()
        if it is None:
            return
        self.family = model.get_value(it, 0)
        fam = self.fams[self.family]
        self.faces = [(f.get_face_name(), d.get_weight(), d.get_style(), d.get_stretch(), f) for f in fam.list_faces() for d in (f.describe(),)]
        keep = closest_face([x[:4] for x in self.faces], *self.want) if self.faces else 0
        self.style.choices = []
        for i, f in enumerate(self.faces):
            self.style.append(i, f[0])
        if self.faces:
            self.style.set_active_id(keep)
        self._update_preview()

    def _desc(self):
        sid = self.style.get_active_id()
        if not self.faces or sid is None:
            d = Pango.FontDescription.from_string(self.family or "Sans")
        else:
            d = self.faces[int(sid)][4].describe()
        d.set_size(int(self.size.get_value() * Pango.SCALE))
        return d

    def _update_preview(self):
        if not self.family:
            return
        d = self._desc()
        self.want = (d.get_weight(), d.get_style(), d.get_stretch())          # remember the style across families
        shown = Pango.FontDescription.from_string(d.to_string())
        shown.set_size(int(max(9, min(40, self.size.get_value())) * Pango.SCALE))
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_font_desc_new(shown))
        self.preview.set_attributes(attrs)
        self.result_lbl.set_text(d.to_string())
        self.ok_btn.set_sensitive(True)

    def _accept(self):
        if self.family:
            self._finish(self._desc().to_string())


def choose_font(parent=None, current="Sans 10", title="Choose font", ok="Select", mono=False):
    """A Pango font string ('Inter Bold 11'), or None when cancelled."""
    return FontChooser(parent, current, title, ok, mono).run()


class FontButton(Gtk.Button):
    """Gtk.FontButton look-alike: shows the font, opens the glass font chooser, emits 'font-set'."""
    __gsignals__ = {"font-set": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, font="Sans 10", mono=False, title="Choose font"):
        super().__init__()
        self.font, self.mono, self.title = font, mono, title
        self.get_style_context().add_class("choicebtn")
        box = Gtk.Box(spacing=10)
        self.lab = Gtk.Label(xalign=0)
        self.lab.set_width_chars(16)
        box.pack_start(self.lab, True, True, 0)
        box.pack_end(Ico("chev_down", 11, scheme.ink(), 1.8), False, False, 0)
        self.add(box)
        self.set_font(font)
        self.connect("clicked", self._open)

    def set_font(self, font):
        self.font = font
        self.lab.set_text(font or "Default")

    def get_font(self):
        return self.font

    def _open(self, *_):
        f = choose_font(self.get_toplevel(), self.font or "Sans 10", self.title, mono=self.mono)
        if f:
            self.set_font(f)
            self.emit("font-set")


# ------------------------------------------------------------------------------------------------------------------------ colours
PALETTE = ["#f777c8", "#ff8fd2", "#ffb8e6", "#c9a8ff", "#9b7df0", "#7b6cf6", "#8fb4ff", "#5fa8ff", "#6fd6e8", "#5ed48a",
           "#a6e57a", "#f3c65b", "#ffa45c", "#ff6b6b", "#ff5c7a", "#2a2d6e", "#1c1850", "#4a4a68", "#8d8fb5", "#ffffff"]


def _rounded(cr, w, h, r=10):
    gfx.rrect(cr, 0, 0, w, h, r)


class _Pad(Gtk.DrawingArea):
    """DrawingArea that reports drags / clicks as (x, y) in widget pixels."""

    def __init__(self, w, h, on_drag):
        super().__init__()
        self.set_size_request(w, h)
        self.on_drag, self._down = on_drag, False
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON1_MOTION_MASK)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", lambda *_: setattr(self, "_down", False) or True)
        self.connect("motion-notify-event", self._move)

    def _press(self, w, ev):
        if ev.button == 1:
            self._down = True
            self.on_drag(ev.x, ev.y)
        return True

    def _move(self, w, ev):
        if self._down:
            self.on_drag(ev.x, ev.y)
        return True


class ColorChooser(_Chooser):
    def __init__(self, parent=None, rgb=(1.0, 1.0, 1.0), title="Choose colour", ok="Select", palette=None):
        super().__init__(title, parent, (440, 560), ok)
        self.orig = tuple(rgb[:3])
        self.h, self.s, self.v = rgb_to_hsv(*self.orig)
        self._lock = False
        box = self.body
        for m, v in (("start", 14), ("end", 14), ("top", 12), ("bottom", 10)):
            getattr(box, "set_margin_" + m)(v)
        box.pack_start(label(title, "proptitle", 0.0), False, False, 0)
        self.sv = _Pad(380, 210, self._drag_sv)
        self.sv.connect("draw", self._draw_sv)
        box.pack_start(self.sv, False, False, 0)
        self.hue = _Pad(380, 20, self._drag_hue)
        self.hue.connect("draw", self._draw_hue)
        box.pack_start(self.hue, False, False, 0)
        row = Gtk.Box(spacing=10)
        self.swatch = Gtk.DrawingArea()
        self.swatch.set_size_request(130, 34)
        self.swatch.connect("draw", self._draw_swatch)
        row.pack_start(self.swatch, False, False, 0)
        row.pack_start(label("Hex", "muted"), False, False, 4)
        self.hex = Gtk.Entry()
        self.hex.set_width_chars(9)
        self.hex.set_max_length(7)
        self.hex.connect("changed", self._hex_changed)
        row.pack_start(self.hex, False, False, 0)
        box.pack_start(row, False, False, 4)
        box.pack_start(label("Colours", "h2"), False, False, 2)
        self.colors = list(palette or PALETTE)
        self.pal = _Pad(380, 66, self._pick_palette)
        self.pal.connect("draw", self._draw_palette)
        box.pack_start(self.pal, False, False, 0)
        self.connect("map", lambda *_: self.hex.grab_focus())
        self._sync_hex()

    # ---------------------------------------------------------------- state
    def rgb(self):
        return hsv_to_rgb(self.h, self.s, self.v)

    def _set_rgb(self, rgb):
        self.h, self.s, self.v = rgb_to_hsv(*rgb)
        self._redraw()
        self._sync_hex()

    def _redraw(self):
        for w in (self.sv, self.hue, self.swatch):
            w.queue_draw()

    def _sync_hex(self):
        self._lock = True
        self.hex.set_text(to_hex(self.rgb()))
        self.hex.get_style_context().remove_class("error")
        self._lock = False

    def _hex_changed(self, e):
        if self._lock:
            return
        c = parse_hex(e.get_text())
        ctx = e.get_style_context()
        if c is None:
            ctx.add_class("error")
            return
        ctx.remove_class("error")
        self.h, self.s, self.v = rgb_to_hsv(*c)
        self._redraw()

    def _drag_sv(self, x, y):
        a = self.sv.get_allocation()
        self.s = max(0.0, min(1.0, x / max(1, a.width)))
        self.v = 1.0 - max(0.0, min(1.0, y / max(1, a.height)))
        self._redraw()
        self._sync_hex()

    def _drag_hue(self, x, y):
        a = self.hue.get_allocation()
        self.h = max(0.0, min(0.9999, x / max(1, a.width)))
        self._redraw()
        self._sync_hex()

    def _pick_palette(self, x, y):
        a = self.pal.get_allocation()
        cols = (len(self.colors) + 1) // 2
        cw, ch = a.width / cols, a.height / 2.0
        i = int(y // ch) * cols + int(x // cw)
        if 0 <= i < len(self.colors):
            c = parse_hex(self.colors[i])
            if c:
                self._set_rgb(c)

    # ---------------------------------------------------------------- drawing
    def _draw_sv(self, w, cr):
        a = w.get_allocation()
        W, H = a.width, a.height
        cr.save()
        _rounded(cr, W, H)
        cr.clip()
        cr.set_source_rgb(*hsv_to_rgb(self.h, 1.0, 1.0))
        cr.paint()
        cr.set_source(gfx.lin(0, 0, W, 0, [(0, (1, 1, 1, 1)), (1, (1, 1, 1, 0))]))
        cr.paint()
        cr.set_source(gfx.lin(0, 0, 0, H, [(0, (0, 0, 0, 0)), (1, (0, 0, 0, 1))]))
        cr.paint()
        cr.restore()
        x, y = self.s * W, (1 - self.v) * H
        cr.arc(x, y, 7, 0, 6.2832)
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.set_line_width(3)
        cr.stroke_preserve()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.set_line_width(1.6)
        cr.stroke()
        return True

    def _draw_hue(self, w, cr):
        a = w.get_allocation()
        W, H = a.width, a.height
        cr.save()
        _rounded(cr, W, H, 8)
        cr.clip()
        cr.set_source(gfx.lin(0, 0, W, 0, [(i / 6.0, hsv_to_rgb(i / 6.0, 1, 1) + (1,)) for i in range(7)]))
        cr.paint()
        cr.restore()
        x = self.h * W
        gfx.fill_rrect(cr, x - 3, 0, 6, H, 3, (1, 1, 1, 1))
        gfx.stroke_rrect(cr, x - 3, 0, 6, H, 3, (0, 0, 0, 0.5), 1.0)
        return True

    def _draw_swatch(self, w, cr):
        a = w.get_allocation()
        W, H = a.width, a.height
        cr.save()
        _rounded(cr, W, H, 9)
        cr.clip()
        cr.rectangle(0, 0, W / 2.0, H)
        cr.set_source_rgb(*self.orig)
        cr.fill()
        cr.rectangle(W / 2.0, 0, W / 2.0, H)
        cr.set_source_rgb(*self.rgb())
        cr.fill()
        cr.restore()
        gfx.stroke_rrect(cr, 0.5, 0.5, W - 1, H - 1, 9, tuple(scheme.ink()[:3]) + (0.35,), 1.0)
        return True

    def _draw_palette(self, w, cr):
        a = w.get_allocation()
        cols = (len(self.colors) + 1) // 2
        cw, ch = a.width / cols, a.height / 2.0
        cur = to_hex(self.rgb())
        for i, hx in enumerate(self.colors):
            x, y = (i % cols) * cw, (i // cols) * ch
            c = parse_hex(hx) or (0, 0, 0)
            gfx.fill_rrect(cr, x + 2, y + 2, cw - 4, ch - 4, 8, c + (1,))
            gfx.stroke_rrect(cr, x + 2.5, y + 2.5, cw - 5, ch - 5, 8, tuple(scheme.ink()[:3]) + (0.3,), 1.0)
            if hx.lower() == cur:
                gfx.stroke_rrect(cr, x + 0.5, y + 0.5, cw - 1, ch - 1, 10, tuple(scheme.ink()[:3]) + (0.95,), 2.0)
        return True

    def _accept(self):
        if parse_hex(self.hex.get_text()) is None:             # a half-typed hex code: do not accept the previous colour silently
            self.hex.get_style_context().add_class("error")
            return
        self._finish(self.rgb())


def choose_color(parent=None, rgb=(1.0, 1.0, 1.0), title="Choose colour", ok="Select", palette=None):
    """(r, g, b) floats 0..1, or None when cancelled."""
    return ColorChooser(parent, rgb, title, ok, palette).run()


class ColorButton(Gtk.Button):
    """Gtk.ColorButton look-alike: a colour swatch that opens the glass colour chooser and emits 'color-set'."""
    __gsignals__ = {"color-set": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, rgba=None, title="Choose colour"):
        super().__init__()
        self.rgb = (rgba.red, rgba.green, rgba.blue) if rgba is not None else (1.0, 1.0, 1.0)
        self.title = title
        self.get_style_context().add_class("choicebtn")
        self.da = Gtk.DrawingArea()
        self.da.set_size_request(46, 16)
        self.da.connect("draw", self._draw)
        self.add(self.da)
        self.connect("clicked", self._open)

    @classmethod
    def new_with_rgba(cls, rgba):
        return cls(rgba)

    def set_use_alpha(self, v):
        pass                                                   # colours here are opaque

    def set_rgba(self, rgba):
        self.rgb = (rgba.red, rgba.green, rgba.blue)
        self.da.queue_draw()

    def get_rgba(self):
        return Gdk.RGBA(self.rgb[0], self.rgb[1], self.rgb[2], 1.0)

    def _draw(self, w, cr):
        a = w.get_allocation()
        gfx.fill_rrect(cr, 0, 0, a.width, a.height, 6, self.rgb + (1,))
        gfx.stroke_rrect(cr, 0.5, 0.5, a.width - 1, a.height - 1, 6, tuple(scheme.ink()[:3]) + (0.4,), 1.0)
        return True

    def _open(self, *_):
        c = choose_color(self.get_toplevel(), self.rgb, self.title)
        if c is not None:
            self.rgb = tuple(c)
            self.da.queue_draw()
            self.emit("color-set")
