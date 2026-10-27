"""glitterde-shell: displays the (non-functional) glitterDE desktop in one fullscreen window.

Two modes:
  * GUI        - a GTK3 window that works under X11 (Xephyr) and Wayland (Weston)
  * --screenshot FILE - headless render to PNG (no display needed)
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="glitterde-shell", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theme", default=None, help="theme directory (default: the theme chosen in SparkSettings)")
    ap.add_argument("--wallpaper", help="override wallpaper (PNG; JPG/WebP need python3-pil)")
    ap.add_argument("--size", metavar="WxH", help="window size (default: whole monitor)")
    ap.add_argument("--windowed", action="store_true", help="normal window instead of fullscreen")
    ap.add_argument("--ui-scale", type=float, help="force UI scale (default: fit the 1536x1024 design to the screen)")
    ap.add_argument("--reduced-effects", action="store_true", help="opaque surfaces, no blur (THEMING s.7)")
    ap.add_argument("--screenshot", metavar="FILE", help="render headless to PNG and exit")
    ap.add_argument("--welcome", action="store_true", help="run the first-run welcome flow even if setup was already done")
    ap.add_argument("--static", action="store_true", help="old non-functional picture of the design target")
    ap.add_argument("--demo", action="store_true", help="fill in sample phone / media / notification data")
    ap.add_argument("--as-desktop", action="store_true", help="X11: act as the desktop window under a window manager")
    ap.add_argument("--no-quit-key", action="store_true", help="disable Ctrl+Q")
    return ap.parse_args(argv)


def _size(s, default):
    if not s:
        return default
    w, h = s.lower().split("x")
    return int(w), int(h)


def main(argv=None):
    args = parse_args(argv)
    if args.reduced_effects:
        os.environ["GLITTERDE_REDUCED_EFFECTS"] = "1"
    if args.wallpaper:
        os.environ["GLITTERDE_WALLPAPER"] = args.wallpaper
    from .tokens import Theme
    from . import scene
    if args.theme:
        theme = Theme(args.theme)
    elif args.screenshot or args.static:                  # the static design-target render is always Trans Pride
        theme = Theme(os.path.join(ROOT, "themes", "trans-pride"))
    else:
        from .tokens import active                        # the live shell starts with the theme saved in SparkSettings
        theme = active()

    if args.screenshot:                                   # headless static render: no Gtk import
        w, h = _size(args.size, (1536, 1024))
        t0 = time.time()
        surf = scene.render(theme, w, h, 1, args.ui_scale)
        surf.write_to_png(args.screenshot)
        print("glitterde-shell: wrote %s (%dx%d, %.2fs)" % (args.screenshot, w, h, time.time() - t0))
        return 0

    if not args.static:
        from . import live
        return live.run(args, theme)

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    class Shell(Gtk.Window):
        def __init__(self):
            super().__init__(title="glitterDE")
            self.set_name("glitterde-shell")
            self.set_wmclass("glitterde-shell", "glitterde-shell")
            self.set_decorated(False)
            self.set_app_paintable(True)
            self.surface = None
            self.rendered_for = None
            self.pending = None
            display = Gdk.Display.get_default()
            mon = display.get_primary_monitor() or display.get_monitor(0)
            geo = mon.get_geometry()
            w, h = _size(args.size, (geo.width, geo.height))
            self.set_default_size(w, h)
            self.area = Gtk.DrawingArea()
            self.add(self.area)
            self.area.connect("draw", self.on_draw)
            self.area.connect("size-allocate", self.on_alloc)
            self.connect("destroy", Gtk.main_quit)
            if not args.no_quit_key:
                self.connect("key-press-event", self.on_key)
            if not args.windowed:
                self.move(geo.x, geo.y)                   # X11 without a WM: place at origin
                self.fullscreen()                         # WMs / Wayland compositors
            else:
                self.set_decorated(True)
            self.show_all()

        def on_key(self, _w, ev):
            if ev.keyval in (Gdk.KEY_q, Gdk.KEY_Q) and ev.state & Gdk.ModifierType.CONTROL_MASK:
                Gtk.main_quit()
            return False

        def on_alloc(self, area, alloc):
            key = (alloc.width, alloc.height, self.get_scale_factor())
            if key == self.rendered_for or key[0] < 200:
                return
            if self.pending:
                GLib.source_remove(self.pending)
            # debounce so interactive resizes don't re-render for every pixel
            self.pending = GLib.timeout_add(120 if self.surface else 10, self.rerender, key)

        def rerender(self, key):
            self.pending = None
            w, h, s = key
            try:
                self.surface = scene.render(theme, w, h, s, args.ui_scale)
                self.rendered_for = key
            except Exception as e:                        # never take the session down
                print("glitterde-shell: render failed:", e, file=sys.stderr)
                raise
            self.area.queue_draw()
            return False

        def on_draw(self, _a, cr):
            if self.surface is None:                      # first frame, before the scene is ready
                cr.set_source_rgb(0.09, 0.075, 0.16)
                cr.paint()
                return True
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()
            return True

    Shell()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
