"""SparkTerm: tabbed VTE terminal with the glitterDE palette."""
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import appkit
from .widgets import Ico, icon_button, label


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA(); c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


PALETTE = [rgba(*c) for c in (
    (0.13, 0.11, 0.30), (0.96, 0.43, 0.55), (0.52, 0.88, 0.62), (0.98, 0.84, 0.50),
    (0.62, 0.72, 1.00), (0.98, 0.66, 0.92), (0.45, 0.85, 0.95), (0.88, 0.86, 0.97),
    (0.38, 0.34, 0.60), (1.00, 0.55, 0.65), (0.65, 0.95, 0.72), (1.00, 0.92, 0.62),
    (0.78, 0.85, 1.00), (1.00, 0.78, 0.96), (0.62, 0.93, 1.00), (1.00, 1.00, 1.00))]


def mono_font(spec):
    """Font description for the terminal; falls back to a real monospace face if the configured one is missing
    (a proportional fallback ruins column alignment)."""
    from gi.repository import Pango, PangoCairo
    fd = Pango.FontDescription(spec)
    fam = (fd.get_family() or "").split(",")[0].strip().lower()
    fm = PangoCairo.font_map_get_default()
    avail = {f.get_name().lower(): f for f in fm.list_families()}
    f = avail.get(fam)
    if f is None or not f.is_monospace():
        for cand in ("jetbrains mono", "dejavu sans mono", "liberation mono", "noto sans mono", "monospace"):
            if cand in avail and (cand == "monospace" or avail[cand].is_monospace()):
                fd.set_family(avail[cand].get_name()); break
        else:
            fd.set_family("monospace")
    return fd


class SparkTerm(appkit.GlassWindow):
    def __init__(self, cwd=None, command=None):
        super().__init__("SparkTerm", "sparkterm", "window_dark", (820, 520), light=False)
        self.cwd, self.command = cwd or GLib.get_home_dir(), command
        self.nb = Gtk.Notebook(); self.nb.set_scrollable(True); self.nb.set_show_border(False)
        self.nb.set_margin_start(4); self.nb.set_margin_end(4); self.nb.set_margin_bottom(4)
        add = icon_button("plus", 13, "New tab (Ctrl+Shift+T)", self.new_tab, pad=7)
        add.show_all(); self.nb.set_action_widget(add, Gtk.PackType.END)
        self.add(self.nb)
        self.connect("key-press-event", self._key)
        if Vte is None:
            self.nb.append_page(label("SparkTerm needs the VTE library: install gir1.2-vte-2.91", "muted", 0.5, ellipsize=False),
                                Gtk.Label(label="Error"))
        else:
            self.new_tab()

    def new_tab(self, *_):
        from gi.repository import Pango
        from . import config
        from .menus import GlassMenu
        t = Vte.Terminal()
        t.set_font(mono_font(config.load().get("fonts", {}).get("monospace", "JetBrains Mono 10")))
        t.set_colors(rgba(0.93, 0.90, 1.0), rgba(0.10, 0.08, 0.30, 0.0), PALETTE)
        t.set_color_cursor(rgba(0.72, 0.58, 1.0)); t.set_color_cursor_foreground(rgba(0.1, 0.08, 0.3))
        t.set_cursor_shape(getattr(Vte.CursorShape, "IBEAM", Vte.CursorShape.BLOCK))
        t.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        try:
            t.set_clear_background(False)           # keep the glass visible behind the text
        except AttributeError:
            pass
        t.set_scrollback_lines(10000); t.set_audible_bell(False); t.set_mouse_autohide(True)
        t.set_margin_start(10); t.set_margin_top(6); t.set_margin_bottom(4)
        # clickable links (Ctrl+click)
        t.url_tag = None
        try:
            rx = Vte.Regex.new_for_match(r"https?://[^\s<>\"']+", -1, 0x40080400)
            t.url_tag = t.match_add_regex(rx, 0)
            t.match_set_cursor_name(t.url_tag, "pointer")
        except Exception:
            pass
        argv = self.command or [os.environ.get("SHELL") or "/bin/bash"]
        try:
            t.spawn_async(Vte.PtyFlags.DEFAULT, self.cwd, argv, None, GLib.SpawnFlags.SEARCH_PATH, None, None, -1, None, None)
        except TypeError:
            t.spawn_sync(Vte.PtyFlags.DEFAULT, self.cwd, argv, None, GLib.SpawnFlags.SEARCH_PATH, None, None, None)

        def press(term, ev):
            if ev.button == 1 and ev.state & Gdk.ModifierType.CONTROL_MASK:
                url = term.match_check_event(ev)[0]
                if url:
                    Gtk.show_uri_on_window(self, url, Gdk.CURRENT_TIME); return True
            if ev.button == 3:
                has_sel = term.get_has_selection()
                GlassMenu([("item", "Copy", lambda: term.copy_clipboard_format(Vte.Format.TEXT), has_sel),
                           ("item", "Paste", term.paste_clipboard), ("sep",),
                           ("item", "New tab", self.new_tab), ("sep",),
                           ("item", "Zoom in", lambda: self.zoom(0.1)), ("item", "Zoom out", lambda: self.zoom(-0.1)),
                           ("item", "Reset zoom", lambda: self.zoom(0)), ("sep",),
                           ("item", "Clear scrollback", lambda: term.reset(True, True))],
                          theme=self.th).popup_at(ev.x_root, ev.y_root)
                return True
            return False
        t.connect("button-press-event", press)
        head = Gtk.Box(spacing=6)
        title = label("Terminal", width_chars=24)
        title.set_width_chars(14)                    # a tab must never shrink to just "..." when more tabs are opened
        head.set_size_request(150, -1)
        close = icon_button("close", 9, "Close tab", None, pad=4)
        head.pack_start(title, False, False, 0); head.pack_start(close, False, False, 0); head.show_all()
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_overlay_scrolling(True); sw.add(t); sw.term = t
        page = self.nb.append_page(sw, head)
        self.nb.set_tab_reorderable(sw, True)
        sw.show_all(); self.nb.set_current_page(page); t.grab_focus()
        t.connect("window-title-changed", lambda term: (title.set_text(term.get_window_title() or "Terminal"),
                                                        self.set_title(term.get_window_title() or "SparkTerm")))
        t.connect("child-exited", lambda term, *_: self.close_tab(sw))
        close.connect("clicked", lambda *_: self.close_tab(sw))
        self.nb.set_show_tabs(self.nb.get_n_pages() > 1)

    def zoom(self, delta):
        sw = self.nb.get_nth_page(self.nb.get_current_page())
        if sw is not None and hasattr(sw, "term"):
            t = sw.term
            t.set_font_scale(1.0 if delta == 0 else max(0.5, min(3.0, t.get_font_scale() + delta)))

    def close_tab(self, t):
        i = self.nb.page_num(t)
        if i >= 0:
            self.nb.remove_page(i)
        if self.nb.get_n_pages() == 0:
            Gtk.main_quit()
        self.nb.set_show_tabs(self.nb.get_n_pages() > 1)

    def _key(self, w, ev):
        ctrl_shift = ev.state & Gdk.ModifierType.CONTROL_MASK and ev.state & Gdk.ModifierType.SHIFT_MASK
        page = self.nb.get_nth_page(self.nb.get_current_page())
        cur = getattr(page, "term", page)
        if ctrl_shift and ev.keyval in (Gdk.KEY_T, Gdk.KEY_t):
            self.new_tab(); return True
        if ctrl_shift and ev.keyval in (Gdk.KEY_W, Gdk.KEY_w) and page is not None:
            self.close_tab(page); return True
        if ev.state & Gdk.ModifierType.CONTROL_MASK and ev.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.zoom(0.1); return True
        if ev.state & Gdk.ModifierType.CONTROL_MASK and ev.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom(-0.1); return True
        if ev.state & Gdk.ModifierType.CONTROL_MASK and ev.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.zoom(0); return True
        if ctrl_shift and Vte and isinstance(cur, Vte.Terminal):
            if ev.keyval in (Gdk.KEY_C, Gdk.KEY_c):
                cur.copy_clipboard_format(Vte.Format.TEXT); return True
            if ev.keyval in (Gdk.KEY_V, Gdk.KEY_v):
                cur.paste_clipboard(); return True
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cwd, cmd = None, None
    if "-e" in argv:
        i = argv.index("-e"); cmd = argv[i + 1:]; argv = argv[:i]
    if argv and os.path.isdir(argv[0]):
        cwd = argv[0]
    appkit.run(SparkTerm(cwd, cmd))
