"""Screenshot UI: the moment it opens the screen is frozen (a picture of exactly what you were looking at), dimmed slightly, and only a
small options bar appears at the bottom:

    [ Area | Screen | Window ]   Delay   Copy   [ Capture ]  [x]

Area: drag a rectangle on the frozen picture.  Screen: capture it all.  Window: hover a window and click it.
Enter captures, 1 / 2 / 3 pick the mode, Esc cancels. With a delay the frozen picture is dropped and the screen is grabbed again after
the countdown (so you can open a menu first). The saved file path is announced with a notification.
"""
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, scheme
from .screenshot import crop, grab_screen, notify, save_pixbuf, shot_folder
from .widgets import Ico, install_css

CSS = b"""
.shotbar { background-color: rgba(26,20,66,0.86); border-radius: 22px; border: 1px solid rgba(255,255,255,0.28); padding: 8px 12px; }
.shotbar button { background-image: none; background-color: transparent; border: none; border-radius: 14px; padding: 6px 12px; color: #ffffff; }
.shotbar button:hover { background-color: rgba(255,255,255,0.14); }
.shotbar button.on { background-color: rgba(150,160,255,0.55); font-weight: 700; }
.shotbar button.go { background-color: #f95cb8; font-weight: 700; padding: 6px 18px; }
.shotbar button.go:hover { background-color: #ff74c6; }
.shotbar label { color: #ffffff; }
.shotbar label.dim { color: rgba(255,255,255,0.7); }
.shotbar separator { background-color: rgba(255,255,255,0.22); min-width: 1px; margin: 4px 6px; }
"""

MODES = (("area", "cursor", "Area"), ("full", "monitor", "Screen"), ("window", "windows", "Window"))
DELAYS = (0, 3, 5, 10)


def window_rects(skip):
    """Top-level windows, top of the stack first: [(x, y, w, h)], excluding desktop / panels / our own window."""
    out = []
    try:
        for w in reversed(Gdk.Screen.get_default().get_window_stack() or []):
            if w == skip or not w.is_visible() or w.get_state() & Gdk.WindowState.ICONIFIED:
                continue
            if w.get_type_hint() in (Gdk.WindowTypeHint.DESKTOP, Gdk.WindowTypeHint.DOCK, Gdk.WindowTypeHint.NOTIFICATION,
                                     Gdk.WindowTypeHint.DROPDOWN_MENU, Gdk.WindowTypeHint.POPUP_MENU, Gdk.WindowTypeHint.TOOLTIP):
                continue
            r = w.get_frame_extents()
            if r.width > 8 and r.height > 8:
                out.append((r.x, r.y, r.width, r.height))
    except Exception:
        pass
    return out


class ShotBar(Gtk.Window):
    def __init__(self, frozen, win_rects, mode="area"):
        super().__init__()
        self.frozen, self.win_rects = frozen, win_rects
        conf = config.load().get("screenshot", {})
        self.mode = conf.get("mode", mode) if conf.get("mode") in ("area", "full", "window") else mode
        self.delay = int(conf.get("delay", 0)) if int(conf.get("delay", 0)) in DELAYS else 0
        self.copy = bool(conf.get("copy", False))
        self.start = self.cur = None
        self.hover = None
        install_css()
        p = Gtk.CssProvider(); p.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 20)
        # NOTE: no set_app_paintable(True): on a depth-24 window inside the WM's 32-bit frame it leaves the alpha channel at 0 and the
        # compositor then shows the whole window as black (that is what made the old area picker look like a frozen screen).
        self.set_decorated(False); self.set_keep_above(True)
        self.set_role("glitterde-screenshot-area"); self.set_title("Screenshot")
        self.fullscreen()
        self.connect("key-press-event", self._key)
        ov = Gtk.Overlay()
        self.canvas = Gtk.DrawingArea()
        self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.canvas.connect("draw", self._draw)
        self.canvas.connect("button-press-event", self._press); self.canvas.connect("button-release-event", self._release)
        self.canvas.connect("motion-notify-event", self._motion)
        self.canvas.connect("realize", lambda w: w.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "crosshair")))
        ov.add(self.canvas)
        ov.add_overlay(self._build_bar())
        self.add(ov)

    # ------------------------------------------------------------------ bar
    def _build_bar(self):
        bar = Gtk.Box(spacing=4); bar.get_style_context().add_class("shotbar")
        self.mode_btns = {}
        for mid, icn, title in MODES:
            b = Gtk.Button(); box = Gtk.Box(spacing=6)
            box.pack_start(Ico(icn, 15, (1, 1, 1, 0.95), 1.5), False, False, 0); box.pack_start(Gtk.Label(label=title), False, False, 0)
            b.add(box); b.connect("clicked", lambda _b, m=mid: self._set_mode(m))
            bar.pack_start(b, False, False, 0); self.mode_btns[mid] = b
        bar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.delay_btn = Gtk.Button(); self.delay_btn.connect("clicked", self._cycle_delay)
        self.delay_btn.set_tooltip_text("Wait before capturing, to open a menu first")
        bar.pack_start(self.delay_btn, False, False, 0)
        self.copy_btn = Gtk.Button(label="Copy"); self.copy_btn.set_tooltip_text("Also put the picture on the clipboard")
        self.copy_btn.connect("clicked", self._toggle_copy)
        bar.pack_start(self.copy_btn, False, False, 0)
        bar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        go = Gtk.Button(label="Capture"); go.get_style_context().add_class("go"); go.connect("clicked", lambda *_: self._capture_current())
        bar.pack_start(go, False, False, 0)
        x = Gtk.Button(); x.add(Ico("close", 12, (1, 1, 1, 0.95), 1.8)); x.set_tooltip_text("Cancel (Esc)"); x.connect("clicked", lambda *_: self._cancel())
        bar.pack_start(x, False, False, 0)
        wrap = Gtk.EventBox(); wrap.add(bar); wrap.set_visible_window(False)            # swallows clicks on the bar's padding
        wrap.set_halign(Gtk.Align.CENTER); wrap.set_valign(Gtk.Align.END); wrap.set_margin_bottom(40)
        self._refresh_bar()
        return wrap

    def _refresh_bar(self):
        for m, b in self.mode_btns.items():
            ctx = b.get_style_context(); (ctx.add_class if m == self.mode else ctx.remove_class)("on")
        self.delay_btn.set_label("No delay" if not self.delay else "%d s delay" % self.delay)
        ctx = self.delay_btn.get_style_context(); (ctx.add_class if self.delay else ctx.remove_class)("on")
        ctx = self.copy_btn.get_style_context(); (ctx.add_class if self.copy else ctx.remove_class)("on")
        self.canvas.queue_draw()

    def _set_mode(self, m):
        self.mode = m; self.start = self.cur = None; self._save_prefs(); self._refresh_bar()

    def _cycle_delay(self, *_):
        self.delay = DELAYS[(DELAYS.index(self.delay) + 1) % len(DELAYS)]; self._save_prefs(); self._refresh_bar()

    def _toggle_copy(self, *_):
        self.copy = not self.copy; self._save_prefs(); self._refresh_bar()

    def _save_prefs(self):
        for k, v in (("mode", self.mode), ("delay", self.delay), ("copy", self.copy)):
            config.set("screenshot", k, v)

    # ------------------------------------------------------------------ canvas
    def _rect(self):
        if self.mode == "area" and self.start and self.cur:
            x1, y1 = self.start; x2, y2 = self.cur
            return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
        if self.mode == "window":
            return self.hover
        if self.mode == "full":
            return 0, 0, self.frozen.get_width(), self.frozen.get_height()
        return None

    def _draw(self, w, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.frozen, 0, 0); cr.paint()
        cr.set_source_rgba(0.05, 0.03, 0.15, 0.45); cr.paint()
        r = self._rect()
        if r and r[2] > 0 and r[3] > 0:
            cr.save(); cr.rectangle(*r); cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.frozen, 0, 0); cr.paint(); cr.restore()
            cr.set_source_rgba(1, 0.6, 0.85, 1); cr.set_line_width(2); cr.rectangle(r[0] + 1, r[1] + 1, max(0, r[2] - 2), max(0, r[3] - 2)); cr.stroke()
            if self.mode == "area":
                cr.set_source_rgba(0.1, 0.05, 0.25, 0.85); cr.rectangle(r[0], max(0, r[1] - 24), 92, 22); cr.fill()
                cr.set_source_rgb(1, 1, 1); cr.set_font_size(13); cr.move_to(r[0] + 8, max(0, r[1] - 24) + 16); cr.show_text("%d × %d" % (r[2], r[3]))
        else:
            hint = {"area": "Drag to select an area", "window": "Click a window", "full": ""}[self.mode]
            cr.set_source_rgba(1, 1, 1, 0.92); cr.set_font_size(18)
            ext = cr.text_extents(hint); cr.move_to((self.canvas.get_allocated_width() - ext.width) / 2, 60); cr.show_text(hint)
        return True

    def _press(self, w, ev):
        if ev.button != 1:
            self._cancel(); return True
        if self.mode == "area":
            self.start = self.cur = (int(ev.x), int(ev.y))
        return True

    def _motion(self, w, ev):
        if self.mode == "area" and self.start:
            self.cur = (int(ev.x), int(ev.y)); self.canvas.queue_draw()
        elif self.mode == "window":
            h = next((r for r in self.win_rects if r[0] <= ev.x < r[0] + r[2] and r[1] <= ev.y < r[1] + r[3]), None)
            if h != self.hover:
                self.hover = h; self.canvas.queue_draw()
        return True

    def _release(self, w, ev):
        if ev.button != 1:
            return True
        if self.mode == "area" and self.start:
            r = self._rect(); self.start = self.cur = None
            if r and r[2] > 3 and r[3] > 3:
                self._capture(r)
            else:
                self.canvas.queue_draw()
        elif self.mode == "window" and self.hover:
            self._capture(self.hover)
        elif self.mode == "full":
            self._capture(self._rect())
        return True

    def _key(self, w, ev):
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self._cancel()
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._capture_current()
        elif k in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3):
            self._set_mode(("area", "full", "window")[k - Gdk.KEY_1])
        else:
            return False
        return True

    # ------------------------------------------------------------------ capture
    def _capture_current(self):
        r = self._rect()
        if self.mode in ("area", "window") and not (r and r[2] > 3 and r[3] > 3):
            self.canvas.queue_draw(); return                      # nothing chosen yet: stay open
        self._capture(r)

    def _cancel(self):
        self.destroy(); Gtk.main_quit()

    def _capture(self, rect):
        copy, delay, frozen = self.copy, self.delay, self.frozen
        self.hide()
        if delay:
            notify("Screenshot in %d seconds" % delay, "")
            GLib.timeout_add(delay * 1000 + 200, lambda: (self._finish(grab_screen(), rect, copy), False)[1])
        else:
            self._finish(frozen, rect, copy)                      # what you saw when you pressed the key, not what happened since

    def _finish(self, pb, rect, copy):
        shot = crop(pb, *rect) if rect else pb
        save_pixbuf(shot or pb, copy)


def main(mode="area"):
    # Freeze FIRST, before any of our own windows exist, so the picture is exactly what was on screen.
    frozen = grab_screen()
    rects = window_rects(None)
    if os.environ.get("GLITTERDE_DEBUG"):
        frozen.savev("/tmp/frozen_debug.png", "png", [], [])
    win = ShotBar(frozen, rects, mode)
    win.connect("destroy", lambda *_: None)
    win.show_all()
    win.present()
    Gtk.main()
    return 0
