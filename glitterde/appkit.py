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
/* tree views (SparkFiles list view, file choosers ...): the base sheet makes every .view transparent, which also hid the selection */
.lightpanel treeview.view { color: #2a2d6e; }
.darkpanel treeview.view { color: #ecebfa; }
.lightpanel treeview.view:selected, .lightpanel treeview.view:selected:focus { background-color: rgba(96,108,255,0.40); color: #1f2160; border-radius: 0; }
.darkpanel treeview.view:selected, .darkpanel treeview.view:selected:focus { background-color: rgba(168,150,255,0.46); color: #ffffff; border-radius: 0; }
.lightpanel treeview.view header button { color: #2a2d6e; background: transparent; border: none; box-shadow: none; }
.darkpanel treeview.view header button { color: #ecebfa; background: transparent; border: none; box-shadow: none; }
.sparkmenubar, box.sparkmenubar { background: transparent; background-image: none; border: none; box-shadow: none; padding: 0; }
.sparkmenubar button.sparkmenubtn { padding: 4px 11px; margin: 0 1px; min-height: 0; min-width: 0; border-radius: 999px; font-weight: 500; background: transparent; background-image: none;
                                    border: none; box-shadow: none; text-shadow: none; }
.sparkmenubar button.sparkmenubtn:hover { background-color: rgba(255,255,255,0.26); }
.sparkmenubar button.sparkmenubtn:active, .sparkmenubar button.sparkmenubtn:checked { background-color: rgba(255,255,255,0.40); }
.lightpanel switch { border-color: rgba(42,45,110,0.22); }
.lightpanel switch:checked { background-color: #ff73c4; }
.lightpanel entry { background-image: none; }
.lightpanel check, .lightpanel radio { background-color: rgba(255,255,255,0.7); border-color: rgba(42,45,110,0.40); color: #2a2d6e; }
.lightpanel check:checked, .lightpanel radio:checked { background-color: #ff73c4; border-color: rgba(42,45,110,0.30); color: #ffffff; }
.lightpanel spinbutton, .lightpanel combobox button { background-color: rgba(255,255,255,0.58); border-color: rgba(255,255,255,0.8); color: #2a2d6e; }
.lightpanel textview, .lightpanel textview text { color: #2a2d6e; }
.lightpanel expander arrow { color: #2a2d6e; }
.lightpanel levelbar trough { background-color: rgba(42,45,110,0.16); }
.darkpanel switch { border-color: rgba(255,255,255,0.22); }
.darkpanel check, .darkpanel radio { background-color: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.35); color: #ecebfa; }
.darkpanel check:checked, .darkpanel radio:checked { background-color: #ff73c4; color: #ffffff; }
.darkpanel spinbutton, .darkpanel combobox button { background-color: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.20); color: #ecebfa; }
.darkpanel textview, .darkpanel textview text { color: #ecebfa; }
progressbar trough { background-color: rgba(120,120,220,0.30); border: none; border-radius: 4px; min-height: 8px; }
progressbar progress { background-image: linear-gradient(to right, #ffb8e6, #ff8fd2); border: none; border-radius: 4px; min-height: 8px; }
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

# stock Gtk dialogs (file choosers, app chooser ...) cannot be glass; they get an opaque surface in the scheme's colours instead of the
# transparent one the base sheet would give them (black on a window without an alpha channel).
_STOCK_TMPL = """
.glitter-stock.%(c)s, .glitter-stock.%(c)s .background, .glitter-stock.%(c)s box, .glitter-stock.%(c)s stack, .glitter-stock.%(c)s paned,
.glitter-stock.%(c)s filechooser, .glitter-stock.%(c)s filechooserwidget, .glitter-stock.%(c)s viewport, .glitter-stock.%(c)s actionbar,
.glitter-stock.%(c)s headerbar, .glitter-stock.%(c)s .dialog-action-area, .glitter-stock.%(c)s .path-bar { background-color: %(surf)s; background-image: none; color: %(ink)s; }
.glitter-stock.%(c)s placessidebar, .glitter-stock.%(c)s placessidebar list, .glitter-stock.%(c)s placessidebar viewport, .glitter-stock.%(c)s .sidebar,
.glitter-stock.%(c)s placessidebar scrolledwindow { background-color: %(side)s; background-image: none; }
.glitter-stock.%(c)s label, .glitter-stock.%(c)s button, .glitter-stock.%(c)s button label, .glitter-stock.%(c)s treeview.view, .glitter-stock.%(c)s entry,
.glitter-stock.%(c)s placessidebar row, .glitter-stock.%(c)s placessidebar row label, .glitter-stock.%(c)s headerbar label, .glitter-stock.%(c)s menuitem,
.glitter-stock.%(c)s image, .glitter-stock.%(c)s check, .glitter-stock.%(c)s radio { color: %(ink)s; }
.glitter-stock.%(c)s label.dim-label, .glitter-stock.%(c)s .dim-label, .glitter-stock.%(c)s treeview.view header button { color: %(soft)s; }
.glitter-stock.%(c)s placessidebar row:hover, .glitter-stock.%(c)s row:hover, .glitter-stock.%(c)s treeview.view:hover { background-color: %(hover)s; }
.glitter-stock.%(c)s placessidebar row:selected, .glitter-stock.%(c)s row:selected, .glitter-stock.%(c)s treeview.view:selected,
.glitter-stock.%(c)s treeview.view:selected:focus { background-color: %(sel)s; color: %(selink)s; }
.glitter-stock.%(c)s treeview.view { background-color: transparent; }
.glitter-stock.%(c)s button { background-image: none; background-color: %(btn)s; border: 1px solid %(line)s; border-radius: 10px; padding: 5px 14px; min-height: 0;
                              box-shadow: none; text-shadow: none; }
.glitter-stock.%(c)s button:hover { background-color: %(hover)s; }
.glitter-stock.%(c)s button.suggested-action { background-color: %(sel)s; }
.glitter-stock.%(c)s entry { background-color: %(entry)s; border: 1px solid %(line)s; border-radius: 8px; }
.glitter-stock.%(c)s scrolledwindow { border: 1px solid %(line)s; border-radius: 8px; background-color: transparent; }
.glitter-stock.%(c)s separator { background-color: %(line)s; }
.glitter-stock.%(c)s popover, .glitter-stock.%(c)s popover box, .glitter-stock.%(c)s menu { background-color: %(side)s; color: %(ink)s; }
"""
STOCK_CSS = (
    _STOCK_TMPL % dict(c="lightpanel", surf="#efecfb", side="#e4e0f7", ink="#2a2d6e", soft="#5a5d94", hover="rgba(96,108,255,0.16)",
                       sel="rgba(96,108,255,0.40)", selink="#1f2160", btn="rgba(42,45,110,0.08)", line="rgba(42,45,110,0.20)",
                       entry="rgba(255,255,255,0.80)") +
    _STOCK_TMPL % dict(c="darkpanel", surf="#23243f", side="#2b2c4d", ink="#ecebfa", soft="#b5b3d6", hover="rgba(255,255,255,0.12)",
                       sel="rgba(168,150,255,0.46)", selink="#ffffff", btn="rgba(255,255,255,0.10)", line="rgba(255,255,255,0.20)",
                       entry="rgba(255,255,255,0.09)")).encode()
_stock_provider = None


def style_stock_dialog(d):
    """Make a plain Gtk dialog (FileChooserDialog, AppChooserDialog ...) legible: opaque surface and ink that follow the colour scheme.
    Also follows a light/dark switch while the dialog is open."""
    global _stock_provider
    if _stock_provider is None:
        _stock_provider = Gtk.CssProvider(); _stock_provider.load_from_data(STOCK_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), _stock_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 14)
    ctx = d.get_style_context()
    ctx.add_class("glitter-stock")
    ctx.remove_class("lightpanel"); ctx.remove_class("darkpanel"); ctx.add_class(scheme.panel_class())
    return d


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
            gfx.rrect_var(cr, 0.5, -20, a.width - 1, a.height + 19.5, 0, 0, rad, rad)   # side + bottom rim only; the titlebar draws the top + upper sides
            cr.set_source_rgba(*gfx.WINDOW_RIM); cr.set_line_width(1.0); cr.stroke()    # (the very same line, so edge and titlebar read as one frame)
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
        super().__init__(title, wm_class, material="window_light", size=size)
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


class GlassPrompt(GlassDialog):
    """A small modal question with a text field (rename, new folder, Wi-Fi password): glass like everything else, Enter confirms, Esc cancels.
    result = GlassPrompt(...).run()  ->  the text, or None when cancelled."""

    def __init__(self, title, prompt, default="", parent=None, ok="OK", secret=False, wm_class="glitterde-prompt"):
        super().__init__(title, wm_class, parent=parent, size=(400, 10))
        self._result, self._loop = None, None
        self.set_modal(True)
        self.close_btn.set_label("Cancel")
        from .widgets import label as _label
        box = self.body
        box.set_margin_start(18); box.set_margin_end(18); box.set_margin_top(16); box.set_margin_bottom(14)
        box.pack_start(_label(prompt, ellipsize=False), False, False, 0)
        self.entry = Gtk.Entry(); self.entry.set_text(default); self.entry.set_activates_default(False)
        self.entry.set_visibility(not secret)
        self.entry.connect("activate", lambda *_: self._accept())
        box.pack_start(self.entry, False, False, 4)
        self.ok_btn = Gtk.Button(label=ok); self.ok_btn.get_style_context().add_class("pill")
        self.ok_btn.get_style_context().add_class("active")
        self.ok_btn.connect("clicked", lambda *_: self._accept())
        row = self.close_btn.get_parent()                       # Cancel on the left, the action on the right
        row.remove(self.close_btn)
        row.pack_end(self.ok_btn, False, False, 6); row.pack_end(self.close_btn, False, False, 0)
        self.connect("map", lambda *_: (self.entry.grab_focus(), self.entry.select_region(0, -1)))
        self.connect("destroy", lambda *_: self._loop and self._loop.quit())

    def _accept(self):
        t = self.entry.get_text().strip()
        if t:
            self._result = t
            self.destroy()

    def run(self):
        self._loop = GLib.MainLoop()
        self.show_all()
        self.present()
        self._loop.run()
        return self._result


def ask_text(parent, title, prompt, default="", ok="OK", secret=False):
    return GlassPrompt(title, prompt, default, parent=parent, ok=ok, secret=secret).run()
