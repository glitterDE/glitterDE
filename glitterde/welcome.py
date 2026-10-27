"""glitterDE welcome: a full-screen first-run setup that asks a few questions and writes them to the normal settings.

    glitterde-welcome          run the flow (the shell starts it automatically on first run)

Pages: welcome (name) - look (scheme + theme) - wallpaper - done.
Nothing is written until the last page, except "Skip" which just marks setup as done.
"""
import glob
import math
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, gfx, tokens  # noqa: E402
from . import settings_model as prefs  # noqa: E402
from .widgets import Ico  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINK = (1.0, 0.56, 0.82)

CSS = b"""
.wel label { color: #ffffff; }
.wel label.wh1 { font-size: 38px; font-weight: 700; }
.wel label.wh2 { font-size: 16px; color: rgba(255,255,255,0.84); }
.wel label.wsec { font-size: 12px; font-weight: 700; color: rgba(255,255,255,0.66); }
.wel label.wsmall { font-size: 12px; color: rgba(255,255,255,0.70); }
.wel label.wtile { font-size: 13px; font-weight: 600; }
.wel label.wlogo { font-size: 14px; font-weight: 700; color: rgba(255,255,255,0.92); }
.wel entry.wname { font-size: 22px; padding: 14px 26px; min-height: 0; border-radius: 999px; color: #ffffff; caret-color: #ffffff;
    background-color: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.36); box-shadow: none; }
.wel entry.wname:focus { background-color: rgba(255,255,255,0.24); border-color: #ff9bd8; }
.wel button.wprimary { background-image: linear-gradient(135deg, #ff8fd2, #a98bff); color: #ffffff; border: none; border-radius: 999px;
    padding: 13px 38px; font-weight: 700; box-shadow: 0 8px 22px rgba(150,90,255,0.45); text-shadow: none; }
.wel button.wprimary label { font-size: 15px; font-weight: 700; }
.wel button.wprimary:hover { background-image: linear-gradient(135deg, #ffa3dc, #b9a0ff); }
.wel button.wghost { background: transparent; border: none; box-shadow: none; padding: 13px 20px; border-radius: 999px; }
.wel button.wghost label { font-size: 14px; color: rgba(255,255,255,0.84); }
.wel button.wghost:hover { background-color: rgba(255,255,255,0.12); }
.wel button.wtile { background-color: rgba(255,255,255,0.10); background-image: none; border: 2px solid rgba(255,255,255,0.16);
    border-radius: 18px; padding: 10px; box-shadow: none; }
.wel button.wtile:hover { background-color: rgba(255,255,255,0.18); }
.wel button.wtile:checked { background-color: rgba(255,143,210,0.22); border-color: #ff9bd8; }
.wel box.wchip { background-color: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.30); border-radius: 999px; }
.wel flowboxchild, .wel flowboxchild:focus, .wel flowboxchild:hover { background: transparent; outline: none; box-shadow: none; }
.wel switch { background-color: rgba(255,255,255,0.22); border-radius: 14px; border: none; min-width: 46px; min-height: 26px; }
.wel switch:checked { background-image: linear-gradient(135deg, #ff8fd2, #a98bff); }
.wel switch slider { background-color: #ffffff; border-radius: 12px; min-width: 22px; min-height: 22px; border: none; }
"""

WIDGETS = [("clock", "Clock", "stopwatch", "Time and date"), ("system", "System", "chip", "CPU, memory, disk"),
           ("network", "Network", "wifi", "Connection and speed"), ("media", "Now playing", "music", "Music controls"),
           ("notifications", "Notifications", "bell", "Messages in one place"), ("quick", "Quick actions", "sparkle", "Shortcuts"),
           ("bluetooth", "Bluetooth", "bluetooth", "Nearby devices")]
SCHEMES = [("light", "Light", "Bright glass, dark text"), ("dark", "Dark", "Deep glass, light text"), ("auto", "Automatic", "Follows the theme")]
CURSOR_SIZES = [(32, "Normal"), (48, "Large"), (64, "Huge")]


def rr(cr, x, y, w, h, r):
    gfx.rrect(cr, x, y, w, h, r)


def label(text, css=None, xalign=0.0, wrap=False):
    l = Gtk.Label(label=text, xalign=xalign)
    for c in (css or "").split():
        l.get_style_context().add_class(c)
    if wrap:
        l.set_line_wrap(True); l.set_max_width_chars(60)
    return l


class Welcome(Gtk.Window):
    def __init__(self):
        super().__init__(title="Welcome to glitterDE")
        self.set_role("glitterde-welcome")
        self.set_app_paintable(True); self.set_decorated(False); self.fullscreen()
        self.get_style_context().add_class("wel")
        p = Gtk.CssProvider(); p.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 20)
        mx, my, mw, mh = gfx.gdk_monitors()[0]
        if mw <= 0:
            scr = Gdk.Screen.get_default(); mw, mh = scr.get_width(), scr.get_height()
        self.cw, self.ch = min(1000, mw - 80), min(660, mh - 70)
        # answers
        self.ans = dict(name="", scheme="auto", theme=tokens.active().theme_id, panel="top", dock="bottom", wallpaper=None,
                        widgets={"clock", "system", "media", "notifications"}, clock24=True, greeting=True, cursor=32)
        self.themes = {}
        for tid, d in tokens.find_themes().items():
            try:
                self.themes[tid] = tokens.Theme(d)
            except Exception:
                pass
        self.wall_files = [os.path.join(ROOT, "wallpapers", f) for f in ("dusk-bay.png", "aurora.png", "midnight.png", "peach.png", "lavender-mist.png")]
        self.wall_files = [f for f in self.wall_files if os.path.exists(f)]
        self.ans["wallpaper"] = self.wall_files[0] if self.wall_files else None
        self._covers, self._bg, self._bg_key = {}, None, None
        self.connect("draw", self._draw_bg)
        self.connect("key-press-event", self._key)

        outer = Gtk.Box(); outer.set_halign(Gtk.Align.CENTER); outer.set_valign(Gtk.Align.CENTER)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.set_size_request(self.cw, self.ch)
        for m in ("top", "bottom"):
            getattr(self.card, "set_margin_" + m)(0)
        self.card.connect("draw", self._draw_card)
        outer.pack_start(self.card, False, False, 0)
        self.add(outer)

        head = Gtk.Box(spacing=8); head.set_margin_top(22); head.set_margin_start(34); head.set_margin_end(26)
        head.pack_start(Ico("sparkle", 20, (1, 1, 1, 0.95), 1.6), False, False, 0)
        head.pack_start(label("glitterDE", "wlogo"), False, False, 0)
        self.b_skip = Gtk.Button(label="Skip setup"); self.b_skip.get_style_context().add_class("wghost")
        self.b_skip.connect("clicked", lambda *_: self._finish(skip=True)); head.pack_end(self.b_skip, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE); self.stack.set_transition_duration(280)
        self.pages = [self.p_hello, self.p_look, self.p_wallpaper, self.p_done]
        self.built = {}
        self.card.pack_start(self.stack, True, True, 0)

        foot = Gtk.Box(spacing=8); foot.set_margin_bottom(24); foot.set_margin_start(30); foot.set_margin_end(30)
        self.b_back = Gtk.Button(label="Back"); self.b_back.get_style_context().add_class("wghost"); self.b_back.connect("clicked", lambda *_: self.go(self.i - 1))
        self.dots = Gtk.DrawingArea(); self.dots.set_size_request(4 * 22, 20); self.dots.connect("draw", self._draw_dots)
        self.b_next = Gtk.Button(label="Next"); self.b_next.get_style_context().add_class("wprimary"); self.b_next.connect("clicked", lambda *_: self.go(self.i + 1))
        foot.pack_start(self.b_back, False, False, 0)
        foot.set_center_widget(self.dots)
        foot.pack_end(self.b_next, False, False, 0)
        self.card.pack_start(foot, False, False, 0)
        self.i = -1
        self.go(0)

    # ------------------------------------------------------------------ navigation
    def go(self, n):
        if n >= len(self.pages):
            self._finish(); return
        n = max(0, n)
        if n not in self.built:
            w = self.pages[n]()
            w.show_all()
            self.stack.add_named(w, str(n)); self.built[n] = w
        elif n == len(self.pages) - 1:                    # the summary page is rebuilt so it reflects the latest answers
            self.stack.remove(self.built[n]); self.built[n] = self.pages[n](); self.built[n].show_all(); self.stack.add_named(self.built[n], str(n))
        self.i = n
        self.stack.set_visible_child_name(str(n))
        self.b_back.set_visible(n > 0 and n < len(self.pages) - 1)
        self.b_skip.set_visible(n < len(self.pages) - 1)
        self.b_next.set_label("Start" if n == len(self.pages) - 1 else "Let's go" if n == 0 else "Next")
        self.dots.queue_draw()
        if n == 0 and hasattr(self, "entry"):
            self.entry.grab_focus()

    def _key(self, w, ev):
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.go(self.i + 1); return True
        if ev.keyval == Gdk.KEY_Left and self.i > 0 and not self.entry.has_focus():
            self.go(self.i - 1); return True
        return False

    # ------------------------------------------------------------------ painting
    def _wall_cover(self, path, w, h):
        key = (path, w, h)
        if key not in self._covers:
            try:
                self._covers[key] = gfx.cover(gfx.load_image(path), w, h)
            except Exception:
                s = gfx.cairo.ImageSurface(gfx.cairo.FORMAT_ARGB32, max(1, w), max(1, h)); self._covers[key] = s
        return self._covers[key]

    def _draw_bg(self, w, cr):
        a = self.get_allocation(); W, H = a.width, a.height
        path = self.ans["wallpaper"]
        if self._bg is None or self._bg_key != (path, W, H):
            q = 4                                           # blur at 1/4 size: cheap, and blur hides the scaling
            small = self._wall_cover(path, W // q, H // q) if path else None
            self._bg = gfx.blur(small, 7) if small is not None else None
            self._bg_key = (path, W, H)
        if self._bg is not None:
            cr.save(); cr.scale(W / self._bg.get_width(), H / self._bg.get_height()); cr.set_source_surface(self._bg, 0, 0); cr.paint(); cr.restore()
        g = gfx.cairo.RadialGradient(W / 2, H / 2, min(W, H) * 0.25, W / 2, H / 2, max(W, H) * 0.75)
        g.add_color_stop_rgba(0, 0.10, 0.06, 0.30, 0.30); g.add_color_stop_rgba(1, 0.04, 0.02, 0.14, 0.72)
        cr.set_source(g); cr.paint()
        return False

    def _draw_card(self, w, cr):
        a = w.get_allocation()
        for i, al in enumerate((0.05, 0.07, 0.09)):         # soft shadow
            rr(cr, -i * 6, 10 - i * 3, a.width + i * 12, a.height + i * 6, 40 + i * 6); cr.set_source_rgba(0.05, 0.02, 0.2, al); cr.fill()
        rr(cr, 0, 0, a.width, a.height, 36)
        g = gfx.cairo.LinearGradient(0, 0, 0, a.height)
        g.add_color_stop_rgba(0, 1, 1, 1, 0.22); g.add_color_stop_rgba(1, 0.75, 0.7, 1, 0.12)
        cr.set_source(g); cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.16); cr.set_line_width(1.0); cr.stroke()
        return False

    def _draw_dots(self, w, cr):
        for k in range(len(self.pages)):
            x = 11 + k * 22
            if k == self.i:
                rr(cr, x - 9, 6, 18, 8, 4); cr.set_source_rgba(1, 0.6, 0.85, 1)
            else:
                rr(cr, x - 4, 6, 8, 8, 4); cr.set_source_rgba(1, 1, 1, 0.38 if k < self.i else 0.22)
            cr.fill()
        return False

    # ------------------------------------------------------------------ building blocks
    def page(self, title, sub=None):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b.set_margin_start(48); b.set_margin_end(48); b.set_margin_top(10); b.set_margin_bottom(6)
        b.pack_start(label(title, "wh1"), False, False, 0)
        if sub:
            b.pack_start(label(sub, "wh2", wrap=True), False, False, 0)
        sp = Gtk.Box(); sp.set_size_request(-1, 14); b.pack_start(sp, False, False, 0)
        return b

    def tile(self, group, active, on_select, child, w=-1, h=-1):
        b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
        b.set_mode(False); b.get_style_context().add_class("wtile"); b.add(child); b.set_size_request(w, h)
        b.set_active(active)
        b.connect("toggled", lambda x: x.get_active() and on_select())
        return b

    def mini(self, w, h, draw):
        d = Gtk.DrawingArea(); d.set_size_request(w, h); d.connect("draw", lambda wd, cr: (draw(cr, wd.get_allocation().width, wd.get_allocation().height), False)[1])
        return d

    def vtile(self, preview, name, sub=None):
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        v.pack_start(preview, False, False, 0)
        v.pack_start(label(name, "wtile", 0.5), False, False, 0)
        if sub:
            v.pack_start(label(sub, "wsmall", 0.5), False, False, 0)
        return v

    # ------------------------------------------------------------------ pages
    def p_hello(self):
        b = self.page("Welcome")
        b.set_valign(Gtk.Align.CENTER)
        logo = Ico("sparkle", 72, (1, 0.72, 0.9, 1), 1.4); logo.set_halign(Gtk.Align.CENTER); logo.set_margin_bottom(6)
        b.pack_start(logo, False, False, 0)
        for ch in b.get_children():
            if isinstance(ch, Gtk.Label):
                ch.set_xalign(0.5); ch.set_justify(Gtk.Justification.CENTER)
        b.reorder_child(logo, 0)
        self.entry = Gtk.Entry(); self.entry.get_style_context().add_class("wname"); self.entry.set_placeholder_text("Your name")
        self.entry.set_text(self._default_name()); self.entry.set_alignment(0.5); self.entry.set_width_chars(22); self.entry.set_halign(Gtk.Align.CENTER)
        self.entry.connect("changed", lambda e: self.ans.update(name=e.get_text().strip()))
        self.ans["name"] = self.entry.get_text().strip()
        b.pack_start(self.entry, False, False, 6)
        return b

    @staticmethod
    def _default_name():
        n = GLib.get_real_name()
        n = n if n and n != "Unknown" else GLib.get_user_name()
        return n.split()[0].capitalize()

    def _preview_theme(self):
        tid = self.ans["theme"] if self.ans["theme"] in self.themes else next(iter(self.themes))
        return self.themes[tid]

    def _dark(self):
        s = self.ans["scheme"]
        if s == "auto":
            return str(self._preview_theme().meta.get("appearance", {}).get("app_scheme", "light")).lower() == "dark"
        return s == "dark"

    def p_look(self):
        b = self.page("Choose a look")
        row = Gtk.Box(spacing=26)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); left.set_size_request(560, -1)
        sr = Gtk.Box(spacing=10, homogeneous=True); g = None
        for key, name, sub in SCHEMES:
            def pv(cr, w, h, key=key):
                rr(cr, 0, 0, w, h, 10)
                if key == "auto":
                    cr.clip_preserve(); cr.set_source_rgb(0.91, 0.88, 0.99); cr.paint()
                    cr.new_path(); cr.rectangle(w / 2, 0, w / 2, h); cr.set_source_rgb(0.14, 0.12, 0.26); cr.fill()
                else:
                    light = key == "light"
                    cr.set_source_rgb(*((0.91, 0.88, 0.99) if light else (0.14, 0.12, 0.26))); cr.fill()
                    cr.set_source_rgba(*((0.16, 0.17, 0.43) if light else (0.93, 0.92, 0.98)), 0.85)
                    rr(cr, 10, 12, w * 0.5, 6, 3); cr.fill(); rr(cr, 10, 24, w * 0.33, 6, 3); cr.fill()
            t = self.tile(g, key == self.ans["scheme"], lambda k=key: self._pick("scheme", k), self.vtile(self.mini(104, 42, pv), name))
            g = g or t; sr.pack_start(t, True, True, 0)
        left.pack_start(sr, False, False, 0)
        fb = Gtk.FlowBox(); fb.set_max_children_per_line(3); fb.set_min_children_per_line(3); fb.set_selection_mode(Gtk.SelectionMode.NONE)
        fb.set_row_spacing(8); fb.set_column_spacing(8); fb.set_homogeneous(True)
        g = None
        for tid, th in self.themes.items():
            cols = [th.material(m)["tint"] for m in ("panel", "card", "window_glass", "window_light")] + [th.color("accent.primary")[:3]]

            def sw(cr, w, h, cols=cols):
                for i, c in enumerate(cols):
                    cr.set_source_rgb(*c); rr(cr, i * (w / 5), 0, w / 5 + (1 if i < 4 else 0), h, 0); cr.fill()
            inner = Gtk.Box(spacing=0, orientation=Gtk.Orientation.VERTICAL)
            area = self.mini(150, 18, lambda cr, w, h, sw=sw: (rr(cr, 0, 0, w, h, 9), cr.clip(), sw(cr, w, h)))
            inner.pack_start(area, False, False, 0); inner.pack_start(label(th.meta.get("name", tid), "wtile", 0.5), False, False, 4)
            t = self.tile(g, tid == self.ans["theme"], lambda k=tid: self._pick("theme", k), inner)
            g = g or t; fb.add(t)
        left.pack_start(fb, False, False, 0)
        row.pack_start(left, False, False, 0)
        b.pack_start(row, False, False, 0)
        return b

    def _pick(self, key, val):
        self.ans[key] = val
        if hasattr(self, "preview"):
            self.preview.queue_draw()
        if key == "wallpaper":
            self.queue_draw()

    def p_wallpaper(self):
        b = self.page("Wallpaper")
        fb = Gtk.FlowBox(); fb.set_max_children_per_line(3); fb.set_min_children_per_line(3); fb.set_selection_mode(Gtk.SelectionMode.NONE)
        fb.set_row_spacing(10); fb.set_column_spacing(10); fb.set_homogeneous(True); fb.set_valign(Gtk.Align.START)
        g = None
        names = {"dusk-bay": "Dusk Bay", "aurora": "Aurora", "midnight": "Midnight", "peach": "Peach", "lavender-mist": "Lavender Mist"}
        self._wall_tiles = []
        for f in self.wall_files:
            nm = names.get(os.path.splitext(os.path.basename(f))[0], os.path.basename(f))
            pv = self.mini(200, 84, lambda cr, w, h, f=f: (rr(cr, 0, 0, w, h, 10), cr.clip(), cr.set_source_surface(self._wall_cover(f, w, h), 0, 0), cr.paint()))
            t = self.tile(g, f == self.ans["wallpaper"], lambda f=f: self._pick("wallpaper", f), self.vtile(pv, nm))
            g = g or t; fb.add(t)
        more = Gtk.Button(); more.get_style_context().add_class("wtile")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ic = Ico("plus", 26, (1, 1, 1, 0.9), 1.8); ic.set_size_request(200, 84); v.pack_start(ic, False, False, 0)
        v.pack_start(label("Choose a picture…", "wtile", 0.5), False, False, 0)
        more.add(v); more.connect("clicked", self._choose_picture); fb.add(more)
        b.pack_start(fb, False, False, 0)
        return b

    def _choose_picture(self, *_):
        d = Gtk.FileChooserDialog(title="Choose a wallpaper", parent=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Choose", Gtk.ResponseType.OK)
        f = Gtk.FileFilter(); f.set_name("Pictures"); f.add_mime_type("image/png"); f.add_mime_type("image/jpeg"); f.add_mime_type("image/webp"); d.add_filter(f)
        d.set_current_folder(os.path.expanduser("~/Pictures") if os.path.isdir(os.path.expanduser("~/Pictures")) else os.path.expanduser("~"))
        if d.run() == Gtk.ResponseType.OK:
            self._pick("wallpaper", d.get_filename())
        d.destroy()

    def p_done(self):
        name = self.ans["name"]
        b = self.page(("All set, %s" % name) if name else "All set")
        b.set_valign(Gtk.Align.CENTER)
        b.set_halign(Gtk.Align.CENTER)
        return b

    # ------------------------------------------------------------------ finish
    def _finish(self, skip=False):
        try:
            if not skip:
                a = self.ans
                if a["name"]:
                    config.set("user", "name", a["name"])
                config.set("appearance", "theme", a["theme"])
                prefs.set("appearance.color_scheme", a["scheme"])
                prefs.set("panel.position", a["panel"]); prefs.set("dock.position", a["dock"])
                prefs.set("panel.clock_24h", a["clock24"]); prefs.set("panel.show_greeting", a["greeting"])
                if a["wallpaper"]:
                    config.set("wallpaper", "path", os.path.abspath(a["wallpaper"]))
                config.set("widgets", "enabled", ",".join(k for k, *_ in WIDGETS if k in a["widgets"]))
                config.set("cursor", "size", int(a["cursor"]))
            config.set("shell", "welcomed", True)
            config.set("shell", "setup_done", True)
        finally:
            Gtk.main_quit()


def main(argv=None):
    from . import widgets
    widgets.install_css()
    w = Welcome()
    w.connect("destroy", lambda *_: Gtk.main_quit())
    w.show_all()
    w.b_back.set_visible(False)
    Gtk.main()
    return 0
