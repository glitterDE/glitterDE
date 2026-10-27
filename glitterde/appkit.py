"""Shared toolkit for Spark* apps: glass window (pseudo-transparent backdrop), CSS, helpers."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config, scheme, gfx
from . import settings_model as prefs
from .tokens import active
from .widgets import CSS, compositing, install_css

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_CSS = b"""
.lightpanel label, .lightpanel entry, .lightpanel button { color: #2a2d6e; }
.lightpanel scale value, .lightpanel scale { color: #2a2d6e; }
.lightpanel scale highlight, .lightpanel scale trough { border: none; box-shadow: none; outline: none; }
.lightpanel label.muted { color: rgba(30,32,90,0.86); }
.lightpanel entry { background-color: rgba(255,255,255,0.58); border-color: rgba(255,255,255,0.8); caret-color: #2a2d6e; }
.lightpanel entry:focus { background-color: rgba(255,255,255,0.78); }
.lightpanel button:hover { background-color: rgba(120,130,255,0.18); }
.lightpanel row:hover { background-color: rgba(120,130,255,0.14); }
.lightpanel row:selected { background-color: rgba(130,140,255,0.38); }
.lightpanel flowboxchild:hover { background-color: rgba(120,130,255,0.16); }
.lightpanel flowboxchild:selected { background-color: rgba(130,140,255,0.36); }
.lightpanel scrollbar slider { background-color: rgba(42,45,110,0.35); }
.lightpanel separator { background-color: rgba(255,255,255,0.55); min-height: 1px; }
.inner { background-color: rgba(255,255,255,0.46); border: 1px solid rgba(255,255,255,0.42); border-radius: 14px; }
.proptitle { font-size: 17px; font-weight: 700; }
.sidebar { background-color: rgba(150,166,255,0.40); border: 1px solid rgba(255,255,255,0.32); border-radius: 14px; }
.card2 { background-color: rgba(255,255,255,0.45); border: 1px solid rgba(255,255,255,0.40); border-radius: 14px; }
.choicebtn { background-color: rgba(255,255,255,0.62); border: 1px solid rgba(255,255,255,0.85); border-radius: 10px; padding: 5px 10px; min-height: 0; box-shadow: none; background-image: none; }
.choicebtn:hover { background-color: rgba(255,255,255,0.85); }
.choicebtn label { color: #2a2d6e; }
.tilebtn { background-color: rgba(255,255,255,0.55); border-radius: 12px; border: 2px solid transparent; padding: 8px; }
.tilebtn:checked, .tilebtn.sel { background-color: rgba(255,200,236,0.7); border-color: #ff73c4; }
.h1 { font-size: 17px; font-weight: 600; }
.h2 { font-size: 12px; font-weight: 600; }
.darkpanel label, .darkpanel entry, .darkpanel button { color: #ecebfa; }
.darkpanel scale value, .darkpanel scale { color: #ecebfa; }
.darkpanel scale highlight, .darkpanel scale trough { border: none; box-shadow: none; outline: none; }
.darkpanel label.muted { color: rgba(236,235,250,0.74); }
.darkpanel entry { background-color: rgba(255,255,255,0.09); border-color: rgba(255,255,255,0.18); caret-color: #ffffff; }
.darkpanel entry:focus { background-color: rgba(255,255,255,0.15); }
.darkpanel button:hover { background-color: rgba(255,255,255,0.11); }
.darkpanel row:hover { background-color: rgba(255,255,255,0.08); }
.darkpanel row:selected { background-color: rgba(150,140,255,0.32); }
.darkpanel flowboxchild:hover { background-color: rgba(255,255,255,0.09); }
.darkpanel flowboxchild:selected { background-color: rgba(150,140,255,0.34); }
.darkpanel scrollbar slider { background-color: rgba(255,255,255,0.36); }
.darkpanel separator { background-color: rgba(255,255,255,0.14); min-height: 1px; }
.darkpanel .inner { background-color: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); }
.darkpanel .sidebar { background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.10); }
.darkpanel .card2 { background-color: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10); }
.darkpanel .choicebtn { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.20); }
.darkpanel .choicebtn:hover { background-color: rgba(255,255,255,0.18); }
.darkpanel .choicebtn label { color: #ecebfa; }
.darkpanel .tilebtn { background-color: rgba(255,255,255,0.08); }
.darkpanel .tilebtn:checked, .darkpanel .tilebtn.sel { background-color: rgba(255,115,196,0.26); border-color: #ff73c4; }
.darkpanel iconview.view { background: transparent; background-color: transparent; color: #ecebfa; font-size: 11px; }
.darkpanel iconview.view:selected, .darkpanel iconview.view:hover { background-color: rgba(255,255,255,0.14); color: #ffffff; border-radius: 12px; }
scale trough { background-color: rgba(120,120,220,0.30); border-radius: 3px; min-height: 5px; }
scale highlight { background-image: linear-gradient(to right, #ffb8e6, #ff8fd2); border-radius: 3px; }
scale slider { background-color: #fff; border-radius: 9px; min-width: 16px; min-height: 16px; border: none; box-shadow: 0 1px 4px rgba(60,40,140,0.35); }
switch { background-color: rgba(120,120,220,0.35); border-radius: 12px; border: none; min-width: 40px; min-height: 22px; }
switch:checked { background-color: #ff73c4; }
switch slider { background-color: #fff; border-radius: 10px; min-width: 18px; min-height: 18px; border: none; }
notebook, notebook > header, notebook > stack { background: transparent; border: none; }
notebook > header > tabs > tab { background-color: rgba(255,255,255,0.10); border-radius: 12px; padding: 4px 10px; margin: 2px; border: none; min-height: 0; }
notebook > header > tabs > tab:checked { background-color: rgba(255,255,255,0.26); }
"""


def theme():
    return active()


def screen_size():
    s = Gdk.Screen.get_default()
    return s.get_width(), s.get_height()


def make_glass(th):
    W, H = screen_size()
    wp = th.wallpaper()
    mt = os.path.getmtime(wp) if os.path.exists(wp) else 0
    wall = gfx.cover_monitors(gfx.load_image(wp), W, H, gfx.gdk_monitors())
    return gfx.Glass(th, wall, 1, cache_key=(wp, mt, W, H, prefs.get("desktop.wallpaper_fit"), tuple(gfx.gdk_monitors())))


class GlassWindow(Gtk.Window):
    """Top-level whose background is the blurred wallpaper under it, tinted by a theme material."""

    def __init__(self, title, wm_class, material="window_glass", size=(900, 580), light=True):
        super().__init__(title=title)
        self._maxed = False
        self.connect("window-state-event", self._on_state)
        ct = config.cursor_theme()                       # GTK apps follow the configured (or bundled default) cursor theme
        if ct:
            Gtk.Settings.get_default().set_property("gtk-cursor-theme-name", ct)
        install_css()
        p = Gtk.CssProvider(); p.load_from_data(APP_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10 + 1)
        self.set_wmclass(wm_class, wm_class)
        self.set_default_size(*size)
        self.set_app_paintable(True)
        self.material = scheme.app_material(material) if light else material       # light apps become dark under the dark scheme
        self.set_role("glitter-material:" + self.material)      # the WM reads this so its titlebar matches the body
        self._scheme = scheme.mode()
        if light:
            self.get_style_context().add_class(scheme.panel_class())
        self.th = theme()
        self.comp = compositing()
        self.glass = None if self.comp else make_glass(self.th)
        if self.comp:                            # real glass: alpha window, the compositor blurs what is behind
            self.set_visual(Gdk.Screen.get_default().get_rgba_visual())
        self.connect("draw", self._draw_backdrop)
        if not self.comp:                       # pseudo-glass depends on screen position; real alpha glass does not
            self.connect("configure-event", lambda *_: self.queue_draw() or False)
        self._quit_id = self.connect("destroy", lambda *_: Gtk.main_quit())
        self._watch = Gio.File.new_for_path(config.path()).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._watch.connect("changed", self._settings_changed)
        self._pending = None

    def _settings_changed(self, *_):
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(300, self._reload)

    def _reload(self):
        self._pending = None
        self.th = theme()
        if scheme.refresh() and scheme.mode() != self._scheme:
            self.on_scheme_change()                      # light <-> dark changes materials and ink everywhere: rebuild the window
            return False
        if not self.comp:
            self.glass = make_glass(self.th)
        self.queue_draw()
        return False

    def on_scheme_change(self):
        """Default: re-exec this app so every widget picks up the new scheme (apps override to keep their place)."""
        import sys
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_state(self, w, ev):
        m = bool(ev.new_window_state & (Gdk.WindowState.MAXIMIZED | Gdk.WindowState.FULLSCREEN))
        if m != self._maxed:
            self._maxed = m
            self.queue_draw()                           # maximised windows have square corners
        return False

    def _draw_backdrop(self, w, cr):
        gw = self.get_window()
        if gw is None:
            return False
        a = self.get_allocation()
        if self.comp:
            rad = 0 if self._maxed else self.th.rad(16)
            gfx.comp_glass(cr, a.width, a.height, 0, self.th.material(self.material), 1.0,
                           corners=(0, 0, rad, rad), sheen=False)
            gfx.rrect_var(cr, 0.5, -20, a.width - 1, a.height + 19.5, 0, 0, rad, rad)   # side + bottom rim only
            cr.set_source_rgba(1, 1, 1, 0.22); cr.set_line_width(1.0); cr.stroke()
            return False
        if "X11" in type(Gdk.Display.get_default()).__name__:
            r = gw.get_origin()
            ox, oy = r[-2], r[-1]
        else:                                   # Wayland: clients can't know their position; sample the screen centre
            W, H = screen_size()
            ox, oy = max(0, (W - a.width) // 2), max(0, (H - a.height) // 2)
        cr.save()
        cr.translate(-ox, -oy)
        self.glass.panel(cr, ox, oy, a.width, a.height, 0, self.material, shadow=False, rim=False)
        cr.restore()
        return False


def run(win):
    win.show_all()
    Gtk.main()


class GlassDialog(GlassWindow):
    """A small secondary window (properties, confirmations) in the same glass as the app it belongs to: transient to its parent, closing it
    does not end the application. Put content into .body; a Close button is provided (.close_btn)."""

    def __init__(self, title, wm_class, parent=None, size=(460, 10)):
        super().__init__(title, wm_class, size=size)
        self.disconnect(self._quit_id)                       # GlassWindow ends the program when it is destroyed; a dialog must not
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_destroy_with_parent(True)
        self.set_resizable(True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, "set_margin_" + m)(14)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner = Gtk.Box(); inner.get_style_context().add_class("inner")           # the same frosted panel the file area uses
        inner.pack_start(self.body, True, True, 0)
        outer.pack_start(inner, True, True, 0)
        row = Gtk.Box(); self.close_btn = Gtk.Button(label="Close"); self.close_btn.get_style_context().add_class("pill")
        self.close_btn.connect("clicked", lambda *_: self.destroy())
        row.pack_end(self.close_btn, False, False, 0)
        outer.pack_start(row, False, False, 0)
        self.add(outer)
        self.connect("map", lambda *_: self.close_btn.grab_focus())      # not the first selectable label
        self.connect("key-press-event", lambda w, ev: (self.destroy(), True)[1] if ev.keyval == Gdk.KEY_Escape else False)

    def get_content_area(self):
        return self.body
