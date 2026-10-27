"""glitterde-screenshot: take a screenshot of the whole screen, a region or the active window.

    glitterde-screenshot [--full | --area | --window] [--delay SECONDS] [--copy] [-o FILE]

Default: whole screen, saved to ~/Pictures/Screenshots/Screenshot_<date>_<time>.png, and a notification says where.
Print Screen (handled by glitter-wm) opens the Screenshot window (--ui).
Region mode freezes the screen, dims it, and lets you drag a rectangle (Esc / right-click cancels).
"""
import argparse
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402


def grab_screen():
    """The whole screen as the user sees it (includes compositor output, because GetImage on the root returns what is on screen)."""
    root = Gdk.get_default_root_window()
    return Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())


def active_window_rect():
    """(x, y, w, h) of the focused window including its titlebar, or None."""
    try:
        w = Gdk.Screen.get_default().get_active_window()
        if w is None or w.get_type_hint() == Gdk.WindowTypeHint.DESKTOP:
            return None
        r = w.get_frame_extents()
        return r.x, r.y, r.width, r.height
    except Exception:
        return None


def crop(pb, x, y, w, h):
    x, y = max(0, x), max(0, y)
    w, h = min(w, pb.get_width() - x), min(h, pb.get_height() - y)
    return pb.new_subpixbuf(x, y, w, h) if w > 0 and h > 0 else None


def shot_folder():
    """Where screenshots go: the folder chosen in the Screenshot settings, else ~/Pictures/Screenshots."""
    try:
        from . import config
        chosen = config.load().get("screenshot", {}).get("folder")
    except Exception:
        chosen = None
    d = chosen or os.path.join(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures"), "Screenshots")
    os.makedirs(d, exist_ok=True)
    return d


def default_path():
    return os.path.join(shot_folder(), time.strftime("Screenshot_%Y-%m-%d_%H-%M-%S.png"))


def save_pixbuf(pb, copy=False, out=None):
    """Write the picture, announce it, optionally copy it to the clipboard, then end the main loop (after a while if a clipboard owner is needed)."""
    out = out or default_path()
    pb.savev(out, "png", [], [])
    print(out)
    notify("Screenshot saved", out, out)
    if copy:
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD); cb.set_image(pb); cb.store()
        GLib.timeout_add_seconds(120, Gtk.main_quit)              # stay alive so the clipboard content can be pasted
    else:
        Gtk.main_quit()


def notify(summary, body, icon=""):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Screenshot", 0, icon, summary, body, [], {}, 5000)), None, Gio.DBusCallFlags.NONE, 1500, None)
    except GLib.Error:
        pass


class Selector(Gtk.Window):
    """Frozen, dimmed full-screen picture; drag to choose a region."""

    def __init__(self, pb, done):
        super().__init__()
        self.pb, self.done = pb, done
        self.set_decorated(False); self.fullscreen(); self.set_keep_above(True)      # not app-paintable: that renders black under glitter-comp
        self.set_role("glitterde-screenshot-area")
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.start = self.cur = None
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press); self.connect("button-release-event", self._release)
        self.connect("motion-notify-event", self._motion); self.connect("key-press-event", self._key)
        self.connect("realize", lambda w: w.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "crosshair")))

    def _rect(self):
        if not self.start or not self.cur:
            return None
        x1, y1 = self.start; x2, y2 = self.cur
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)

    def _draw(self, w, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0); cr.paint()
        cr.set_source_rgba(0.05, 0.03, 0.15, 0.55); cr.paint()
        r = self._rect()
        if r and r[2] > 0 and r[3] > 0:
            cr.save(); cr.rectangle(*r); cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0); cr.paint(); cr.restore()
            cr.set_source_rgba(1, 0.6, 0.85, 1); cr.set_line_width(2); cr.rectangle(r[0] + 1, r[1] + 1, r[2] - 2, r[3] - 2); cr.stroke()
            cr.set_source_rgba(0.1, 0.05, 0.25, 0.85); cr.rectangle(r[0], max(0, r[1] - 24), 92, 22); cr.fill()
            cr.set_source_rgb(1, 1, 1); cr.set_font_size(13); cr.move_to(r[0] + 8, max(0, r[1] - 24) + 16); cr.show_text("%d × %d" % (r[2], r[3]))
        else:
            cr.set_source_rgba(1, 1, 1, 0.9); cr.set_font_size(18); cr.move_to(30, 44); cr.show_text("Drag to select an area · Esc to cancel")
        return True

    def _press(self, w, ev):
        if ev.button != 1:
            self._finish(None); return True
        self.start = self.cur = (int(ev.x), int(ev.y)); return True

    def _motion(self, w, ev):
        if self.start:
            self.cur = (int(ev.x), int(ev.y)); self.queue_draw()
        return True

    def _release(self, w, ev):
        r = self._rect()
        self._finish(r if r and r[2] > 3 and r[3] > 3 else None); return True

    def _key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self._finish(None)
        return True

    def _finish(self, rect):
        self.hide(); self.destroy(); self.done(rect)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="glitterde-screenshot", description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="whole screen (default)"); g.add_argument("--area", action="store_true", help="drag a region")
    g.add_argument("--window", action="store_true", help="the focused window")
    g.add_argument("--ui", "--menu", dest="ui", action="store_true", help="open the Screenshot window")
    g.add_argument("--classic-ui", action="store_true", help="the older Screenshot window")
    ap.add_argument("--delay", type=float, default=0, help="wait this many seconds first (to open a menu, say)")
    ap.add_argument("--copy", action="store_true", help="also put the picture on the clipboard")
    ap.add_argument("-o", "--output", help="file to write (default ~/Pictures/Screenshots/...)")
    args = ap.parse_args(argv)
    if args.ui:                                     # freeze the screen and show only a small options bar at the bottom
        from .shotbar import main as ui
        return ui()
    if args.classic_ui:
        from .sparkshot import main as ui
        return ui()
    out = args.output or default_path()
    state = {}

    def save(pb):
        if pb is None:
            Gtk.main_quit(); return
        pb.savev(out, "png", [], [])
        print(out)
        notify("Screenshot saved", out, out)
        if args.copy:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD); cb.set_image(pb); cb.store()
            GLib.timeout_add_seconds(120, Gtk.main_quit)          # stay alive so the clipboard content can be pasted
        else:
            Gtk.main_quit()

    win_rect = [active_window_rect()]          # taken before any menu steals the focus

    def start():
        full = grab_screen()
        if args.window:
            r = win_rect[0] or active_window_rect()
            save(crop(full, *r) if r else full)
        elif args.area:
            Selector(full, lambda r: save(crop(full, *r) if r else None)).show_all()
        else:
            save(full)
        return False

    GLib.timeout_add(int(max(args.delay, 0) * 1000) + 120, start)      # tiny pause so a closing menu/popup is gone from the picture
    Gtk.main()
    return 0
