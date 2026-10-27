"""GTK3 building blocks: Desktop (wallpaper + glass behind real widgets), icons, rings, CSS."""
import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import gfx
from . import icons as ic

CSS = b"""
* { font-family: Inter, "Noto Sans", Cantarell, "DejaVu Sans", sans-serif; font-size: 12px; color: #ffffff; }
window, .desk { background: transparent; }
/* glitterDE draws its own glass: neutralise whatever the system GTK theme or a user ~/.config/gtk-3.0/gtk.css paints on containers */
scrolledwindow, viewport, .view, iconview, treeview.view, list, listbox, row, stack, notebook, notebook > stack, paned, frame, flowbox, flowboxchild
    { background-color: transparent; background-image: none; }
scrolledwindow, frame { border-color: transparent; box-shadow: none; }
label.title { font-size: 12px; font-weight: 500; }
label.big { font-size: 13px; font-weight: 600; }
label.muted { color: rgba(255,255,255,0.93); font-size: 11px; text-shadow: 0 1px 2px rgba(20,10,80,0.40); }
label.tiny { color: rgba(255,255,255,0.93); font-size: 10px; text-shadow: 0 1px 2px rgba(20,10,80,0.40); }
label.clock { font-size: 40px; font-weight: 300; }
label.date { font-size: 14px; }
label.dark { color: #2a2d6e; }
button { background-image: none; background-color: transparent; border: none; box-shadow: none;
         text-shadow: none; padding: 0; min-height: 0; min-width: 0; border-radius: 12px; outline: none; }
button:hover { background-color: rgba(255,255,255,0.16); }
button:active { background-color: rgba(255,255,255,0.26); }
button:focus { background-color: rgba(255,255,255,0.12); }
button.tile { background-color: rgba(255,255,255,0.09); border: 1px solid rgba(255,255,255,0.14); padding: 6px 4px; }
button.tile:hover { background-color: rgba(255,255,255,0.18); }
button.tile.on { background-color: rgba(155,125,240,0.55); border-color: rgba(255,255,255,0.35); }
button.pill { border-radius: 14px; padding: 3px 11px; }
button.pill.active { background-color: rgba(155,125,240,0.92); border: 1px solid rgba(255,255,255,0.28); }
button.clear { background-color: rgba(255,255,255,0.13); border: 1px solid rgba(255,255,255,0.14); border-radius: 14px; padding: 5px; }
button.app { padding: 8px 4px; border-radius: 16px; }
entry { background-color: rgba(255,255,255,0.17); border: 1px solid rgba(255,255,255,0.30); border-radius: 16px;
        padding: 4px 12px; color: #fff; caret-color: #fff; box-shadow: none; min-height: 0; }
entry:focus { background-color: rgba(255,255,255,0.26); border-color: rgba(255,255,255,0.6); }
entry placeholder, entry text placeholder { color: rgba(255,255,255,0.7); }
entry selection { background-color: rgba(155,125,240,0.8); }
list, row, flowbox, flowboxchild, scrolledwindow, viewport, .transparent { background: transparent; background-color: transparent; }
row { border-radius: 10px; padding: 5px 8px; }
row:hover { background-color: rgba(255,255,255,0.14); }
row:selected { background-color: rgba(255,255,255,0.34); }
flowboxchild { border-radius: 16px; }
flowboxchild:focus, flowboxchild:selected { background-color: rgba(255,255,255,0.22); }
scrollbar { background: transparent; }
scrollbar trough { background: transparent; border: none; min-width: 5px; }
scrollbar slider { background-color: rgba(255,255,255,0.38); border-radius: 3px; min-width: 4px; min-height: 28px; border: none; }
calendar { background: transparent; background-color: transparent; color: #fff; border: none; padding: 2px; }
calendar.header { color: #fff; border-bottom: 1px solid rgba(255,255,255,0.25); background: transparent; }
calendar.button { color: #fff; background: transparent; }
calendar.highlight { color: rgba(255,255,255,0.75); }
calendar:indeterminate { color: rgba(255,255,255,0.35); }
calendar:selected { background-color: rgba(155,125,240,0.95); color: #fff; border-radius: 8px; }
tooltip, tooltip * { color: #fff; }
tooltip { background-color: rgba(52,44,120,0.92); border-radius: 8px; }
entry.withicon { padding-left: 32px; }
menu, .menu { background-color: rgba(58,50,130,0.93); border-radius: 12px; padding: 4px; border: 1px solid rgba(255,255,255,0.3); }
menuitem { padding: 6px 12px; border-radius: 8px; }
menuitem:hover { background-color: rgba(255,255,255,0.2); }
"""


def install_css():
    scr = Gdk.Screen.get_default()
    p = Gtk.CssProvider()
    p.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(scr, p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)
    from . import settings_model as prefs
    fam = (prefs.get("fonts.ui") or "").split(",")[0].strip()
    if fam:                                   # user-chosen interface font (strip a trailing size like "Inter 10")
        import re
        fam = re.sub(r"\s+\d+(\.\d+)?$", "", fam)
        q = Gtk.CssProvider()
        q.load_from_data(('* { font-family: "%s", Inter, "Noto Sans", sans-serif; }' % fam.replace('"', "")).encode())
        Gtk.StyleContext.add_provider_for_screen(scr, q, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10 + 1)


class Region:
    def __init__(self, widget, material, radius, shadow=True, rim=True, rr=None, alpha=0.30):
        self.widget, self.material, self.radius = widget, material, radius
        self.shadow, self.rim, self.rr, self.alpha = shadow, rim, rr, alpha


class Desktop(Gtk.Fixed):
    """Paints wallpaper, then a glass material behind every registered widget, then the widgets."""

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.get_style_context().add_class("desk")
        self.regions = []
        self.wall = None
        self.glass = None
        self._key = None
        self._wp = None
        self._wp_path = None
        self._cache = {}

    def add_glass(self, widget, material, radius, **kw):
        self.regions.append(Region(widget, material, radius, **kw))

    def do_size_allocate(self, alloc):
        Gtk.Fixed.do_size_allocate(self, alloc)
        key = (alloc.width, alloc.height, self.get_scale_factor())
        if key != self._key and alloc.width > 100:
            self._key = key
            self._build_wall(alloc.width, alloc.height, key[2])

    def _build_wall(self, w, h, s):
        wp = self.theme.wallpaper()
        if self._wp is None or self._wp_path != wp:
            self._wp, self._wp_path = gfx.load_image(wp), wp
        mons = gfx.gdk_monitors()
        wall = gfx.cover_monitors(self._wp, w, h, mons, s)
        wall.set_device_scale(s, s)
        import os
        mt = os.path.getmtime(wp) if os.path.exists(wp) else 0
        self._cache = {}
        from . import settings_model as prefs
        self.wall, self.glass = wall, gfx.Glass(self.theme, wall, s, cache_key=(wp, mt, w * s, h * s, s, prefs.get("desktop.wallpaper_fit"), tuple(mons)))

    def reload(self, theme):
        self.theme = theme
        if self._key:
            self._build_wall(self._key[0], self._key[1], self._key[2])
        self.queue_draw()

    def do_draw(self, cr):
        if self.wall is None:
            cr.set_source_rgb(0.09, 0.075, 0.16)
            cr.paint()
            return Gtk.Fixed.do_draw(self, cr)
        cr.set_source_surface(self.wall, 0, 0)
        cr.paint()
        ok, clip = Gdk.cairo_get_clip_rectangle(cr)
        sc = self.get_scale_factor()
        for r in self.regions:
            w = r.widget
            if not w.get_visible() or not w.get_mapped():
                continue
            pos = w.translate_coordinates(self, 0, 0)
            a = w.get_allocation()
            if pos is None or a.width < 4:
                continue
            x, y = pos
            m = 60
            if ok and (x + a.width + m < clip.x or x - m > clip.x + clip.width or
                       y + a.height + m < clip.y or y - m > clip.y + clip.height):
                continue
            rad = self.theme.rad(r.radius)
            key = (x, y, a.width, a.height, r.material, rad, r.shadow, r.rim, r.rr, r.alpha, id(self.glass), sc)
            surf = self._cache.pop(key, None)
            pad = 70 if r.shadow else 4
            if surf is None:                               # glass is expensive: render once per placement, then blit
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (a.width + 2 * pad) * sc, (a.height + 2 * pad) * sc)
                surf.set_device_scale(sc, sc)
                c2 = cairo.Context(surf)
                c2.translate(pad - x, pad - y)
                self.glass.panel(c2, x, y, a.width, a.height, rad, r.material, shadow=r.shadow,
                                 shadow_alpha=r.alpha, rim=r.rim, rr=r.rr)
            self._cache[key] = surf                        # most-recently-used goes last
            while len(self._cache) > 48:
                self._cache.pop(next(iter(self._cache)))
            cr.set_source_surface(surf, x - pad, y - pad)
            cr.paint()
        return Gtk.Fixed.do_draw(self, cr)


# -------------------------------------------------------------------- icons
_GTK_ICON_CACHE = {}


def draw_gtk_icon(cr, name, cx, cy, px, color, scale=1):
    """Draw a named icon from the user's GTK icon theme, recoloured when it is symbolic. Returns False if the theme has no such icon."""
    key = (name, int(px), int(scale), tuple(round(v, 2) for v in color[:3]))
    pb = _GTK_ICON_CACHE.get(key)
    if pb is None:
        try:
            th = Gtk.IconTheme.get_default()
            info = th.lookup_icon_for_scale(name, int(px), int(scale), Gtk.IconLookupFlags.FORCE_SIZE) or th.lookup_icon_for_scale(name, int(px), int(scale), 0)
            if info is None:
                return False
            if info.is_symbolic() or name.endswith("-symbolic"):
                pb, _ = info.load_symbolic(Gdk.RGBA(*color[:3], 1.0), None, None, None)
            else:
                pb = info.load_icon()
        except Exception:
            return False
        if len(_GTK_ICON_CACHE) > 200:
            _GTK_ICON_CACHE.clear()
        _GTK_ICON_CACHE[key] = pb
    cr.save()
    cr.translate(cx - px / 2.0, cy - px / 2.0)
    cr.scale(1.0 / scale, 1.0 / scale)
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint_with_alpha(color[3] if len(color) > 3 else 1.0)
    cr.restore()
    return True


class Ico(Gtk.DrawingArea):
    """Draws a glitter-icons line icon (semantic colour, any size). A name starting with "gtk:" is looked up in the GTK icon theme instead
    ("gtk:view-app-grid-symbolic"); if the theme lacks it the glitterDE sparkle is drawn."""

    def __init__(self, name, size=16, color=(1, 1, 1, 0.95), lw=1.6):
        super().__init__()
        self.name, self.px, self.color, self.lw = name, size, color, lw
        self.set_size_request(size + 2, size + 2)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

    def set_icon(self, name, color=None):
        self.name = name
        if color:
            self.color = color
        self.queue_draw()

    def do_draw(self, cr):
        a = self.get_allocation()
        if self.name.startswith("gtk:"):
            if not draw_gtk_icon(cr, self.name[4:], a.width / 2, a.height / 2, self.px, self.color, self.get_scale_factor()):
                ic.sparkle_logo(cr, a.width / 2, a.height / 2, self.px, self.color)
            return False
        if self.name == "battery":
            ic.battery(cr, a.width / 2, a.height / 2, self.px, self.color, getattr(self, "pct", 0.74))
        elif self.name == "sparkle_logo":
            ic.sparkle_logo(cr, a.width / 2, a.height / 2, self.px, self.color)
        else:
            ic.icon(cr, self.name, a.width / 2, a.height / 2, self.px, self.color, self.lw)
        return False


def icon_button(name, size=16, tip=None, cb=None, css=None, color=(1, 1, 1, 0.95), pad=6):
    b = Gtk.Button()
    ico = Ico(name, size, color)
    b.add(ico)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_focus_on_click(False)
    ico.set_margin_start(pad); ico.set_margin_end(pad); ico.set_margin_top(pad - 2); ico.set_margin_bottom(pad - 2)
    if tip:
        b.set_tooltip_text(tip)
    if cb:
        b.connect("clicked", lambda *_: cb())
    if css:
        b.get_style_context().add_class(css)
    b.ico = ico
    return b


class Ring(Gtk.DrawingArea):
    def __init__(self, size=62):
        super().__init__()
        self.frac, self.label = 0.0, ""
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)

    def set(self, frac, label):
        self.frac, self.label = max(0.0, min(1.0, frac)), label
        self.queue_draw()

    def do_draw(self, cr):
        a = self.get_allocation()
        cx, cy, r = a.width / 2, a.height / 2, min(a.width, a.height) / 2 - 4
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(5.5)
        cr.new_path(); cr.set_source_rgba(1, 1, 1, 0.20); cr.arc(cx, cy, r, 0, 2 * math.pi); cr.stroke()
        if self.frac > 0.005:
            cr.new_path()
            cr.set_source(gfx.lin(cx - r, cy - r, cx + r, cy + r, [(0, (1, 1, 1, 0.97)), (1, (1.0, 0.55, 0.85, 1))]))
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * self.frac)
            cr.stroke()
        gfx.text(cr, self.label, cx, cy + 0.5, 12.5, (1, 1, 1, 1), 500, "c")
        return False


class Spark(Gtk.DrawingArea):
    def __init__(self, w=200, h=30, n=60):
        super().__init__()
        self.set_size_request(w, h)
        self.n, self.vals = n, []

    def push(self, v):
        self.vals = (self.vals + [v])[-self.n:]
        self.queue_draw()

    def do_draw(self, cr):
        a = self.get_allocation()
        if len(self.vals) < 2:
            return False
        mx = max(max(self.vals), 1.0)
        pts = [(a.width * i / (self.n - 1) + a.width * (1 - len(self.vals) / self.n),
                a.height - 2 - (a.height - 4) * v / mx) for i, v in enumerate(self.vals)]
        cr.move_to(pts[0][0], a.height)
        for p in pts:
            cr.line_to(*p)
        cr.line_to(pts[-1][0], a.height); cr.close_path()
        cr.set_source(gfx.lin(0, 0, 0, a.height, [(0, (0.35, 0.82, 1.0, 0.45)), (1, (0.35, 0.82, 1.0, 0.04))])); cr.fill()
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.set_source_rgba(0.45, 0.88, 1.0, 0.95); cr.set_line_width(1.2); cr.set_line_join(cairo.LINE_JOIN_ROUND); cr.stroke()
        return False


class Bar(Gtk.DrawingArea):
    """Thin progress / seek bar (value 0..1). Click or drag emits on_seek(value)."""

    def __init__(self, h=14, on_seek=None):
        super().__init__()
        self.value, self.on_seek = 0.0, on_seek
        self.set_size_request(60, h)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self._press)

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self.queue_draw()

    def _press(self, w, ev):
        if self.on_seek:
            self.on_seek(max(0.0, min(1.0, ev.x / max(1, self.get_allocated_width()))))
        return True

    def do_draw(self, cr):
        a = self.get_allocation()
        y = a.height / 2 - 2
        gfx.fill_rrect(cr, 0, y, a.width, 4, 2, (1, 1, 1, 0.28))
        gfx.fill_rrect(cr, 0, y, max(4, a.width * self.value), 4, 2, (1, 1, 1, 0.96))
        return False


def label(text="", css=None, xalign=0.0, ellipsize=True, width_chars=None):
    l = Gtk.Label(label=text)
    l.set_xalign(xalign)
    if css:
        for c in css.split():
            l.get_style_context().add_class(c)
    if ellipsize:
        from gi.repository import Pango
        l.set_ellipsize(Pango.EllipsizeMode.END)
    if width_chars:
        l.set_max_width_chars(width_chars)
    return l


def search_overlay(entry, color=(1, 1, 1, 0.85)):
    """Entry with our own magnifier icon and placeholder (no icon-theme / CSS-placeholder dependency)."""
    hint = entry.get_placeholder_text() or ""
    entry.set_placeholder_text(None)
    entry.get_style_context().add_class("withicon")
    ov = Gtk.Overlay()
    ov.add(entry)
    i = Ico("search", 14, color, 1.8)
    i.set_halign(Gtk.Align.START); i.set_margin_start(11)
    ph = label(hint, "muted")
    ph.set_halign(Gtk.Align.START); ph.set_margin_start(32)
    for w in (i, ph):
        ov.add_overlay(w); ov.set_overlay_pass_through(w, True)
    entry.connect("changed", lambda e: ph.set_visible(not e.get_text()))
    return ov


def compositing():
    """True when a compositing manager owns the screen and an alpha visual exists."""
    sc = Gdk.Screen.get_default()
    return bool(sc and sc.is_composited() and sc.get_rgba_visual() is not None)


def popup_menu(menu, ev=None, widget=None):
    """Show a Gtk.Menu with an alpha window (no black corners under a compositor)."""
    if compositing():
        tl = menu.get_toplevel()
        tl.set_visual(Gdk.Screen.get_default().get_rgba_visual())
        tl.set_app_paintable(True)
    if widget is not None:
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, None)
    else:
        menu.popup_at_pointer(ev)


def round_shape(win, r):
    """Round a window's corners with the X Shape extension (no compositor needed)."""
    import math
    a = win.get_allocation()
    w, h = a.width, a.height
    if r <= 0 or w < 2 * r or h < 2 * r or win.get_window() is None:
        return
    rects = [cairo.RectangleInt(0, r, w, h - 2 * r)]
    for i in range(r):
        inset = r - int(math.sqrt(max(0, r * r - (r - i - 0.5) ** 2)) + 0.5)
        rects.append(cairo.RectangleInt(inset, i, w - 2 * inset, 1))
        rects.append(cairo.RectangleInt(inset, h - 1 - i, w - 2 * inset, 1))
    win.shape_combine_region(cairo.Region(rects))
