"""The About page of SparkSettings: hero banner, live usage tiles, system + glitterDE details, links, experimental switch."""
import math
import os
import platform
import random
import shlex
import socket
import subprocess

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config, gfx
from . import icons as ic
from . import scheme, tokens
from . import settings_model as model
from .widgets import Ico, compositing, label

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ data
def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def version():
    return _read(os.path.join(ROOT, "VERSION"), "0.13.1")


def os_name():
    for ln in _read("/etc/os-release").splitlines():
        if ln.startswith("PRETTY_NAME="):
            return ln.split("=", 1)[1].strip().strip('"')
    return "Linux"


def cpu_name():
    for ln in _read("/proc/cpuinfo").splitlines():
        if ln.startswith("model name"):
            n = ln.split(":", 1)[1].strip()
            break
    else:
        n = platform.processor() or "Unknown processor"
    for junk in ("(R)", "(TM)", "(tm)", " CPU", "  "):
        n = n.replace(junk, " " if junk == "  " else "")
    return "%s  ·  %d thread%s" % (" ".join(n.split()), os.cpu_count() or 1, "" if (os.cpu_count() or 1) == 1 else "s")


def gpu_name():
    try:
        out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return "Unknown"
    names = []
    for ln in out.splitlines():
        try:
            parts = shlex.split(ln)
        except ValueError:
            continue
        if len(parts) >= 4 and any(k in parts[1] for k in ("VGA", "3D controller", "Display controller")):
            names.append("%s %s" % (parts[2].replace("Corporation", "").strip(), parts[3]))
    return "  +  ".join(names) if names else "Unknown"


def meminfo():
    d = {}
    for ln in _read("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        try:
            d[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    total = d.get("MemTotal", 0)
    return total, max(0, total - d.get("MemAvailable", d.get("MemFree", 0)))


def disk():
    try:
        s = os.statvfs(os.path.expanduser("~"))
        total = s.f_blocks * s.f_frsize
        return total, total - s.f_bavail * s.f_frsize
    except OSError:
        return 0, 0


def uptime_text():
    try:
        up = int(float(_read("/proc/uptime", "0").split()[0]))
    except (ValueError, IndexError):
        return "Unknown"
    d, h, m = up // 86400, up % 86400 // 3600, up % 3600 // 60
    return ("%d day%s, " % (d, "" if d == 1 else "s") if d else "") + "%d h %02d min" % (h, m)


def load_fraction():
    try:
        return min(1.0, os.getloadavg()[0] / float(os.cpu_count() or 1))
    except OSError:
        return 0.0


def gb(n):
    return "%.1f GB" % (n / 1e9) if n < 1e12 else "%.2f TB" % (n / 1e12)


def displays():
    d = Gdk.Display.get_default()
    out = []
    for i in range(d.get_n_monitors()):
        m = d.get_monitor(i); g = m.get_geometry(); s = m.get_scale_factor()
        out.append("%d × %d%s" % (g.width * s, g.height * s, "  (x%d)" % s if s > 1 else ""))
    return "  +  ".join(out) or "Unknown"


def session_text():
    t = (os.environ.get("XDG_SESSION_TYPE") or ("x11" if "X11" in type(Gdk.Display.get_default()).__name__ else "wayland")).upper()
    return "X11" if t.startswith("X") else t.capitalize() if t != "WAYLAND" else "Wayland"


def wm_name():
    try:
        return Gdk.Screen.get_default().get_window_manager_name() or "Unknown"
    except Exception:
        return "Unknown"


def collect(th):
    tm, tu = meminfo()
    dt, du = disk()
    mode = scheme.mode() if hasattr(scheme, "mode") else "auto"
    return dict(
        device=[("Device name", socket.gethostname(), "laptop"), ("Operating system", os_name(), "sparkle"),
                ("Kernel", platform.release(), "chip"), ("Processor", cpu_name(), "chip"), ("Graphics", gpu_name(), "monitor"),
                ("Memory", "%s  ·  %s in use" % (gb(tm), gb(tu)) if tm else "Unknown", "chip"),
                ("Storage", "%s  ·  %s used" % (gb(dt), gb(du)) if dt else "Unknown", "drive"),
                ("Displays", displays(), "monitor"), ("Uptime", uptime_text(), "stopwatch")],
        desktop=[("Version", "glitterDE %s (prototype)" % version(), "sparkle"), ("Theme", th.meta.get("name", th.theme_id), "palette"),
                 ("Colour scheme", str(mode).capitalize(), "drop"), ("Session", session_text(), "windows"),
                 ("Window manager", wm_name(), "windows"),
                 ("Compositor", "glitter-comp - blur and shadows active" if compositing() else "None - pseudo-glass over the wallpaper", "brightness"),
                 ("Toolkit", "GTK %d.%d.%d  ·  Python %s" % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version(), platform.python_version()), "gear"),
                 ("Settings file", config.path(), "doc")],
        mem=(tm, tu), disk=(dt, du))


# ------------------------------------------------------------------ drawing
def _star(cr, x, y, r, alpha):
    cr.save(); cr.translate(x, y)
    cr.move_to(0, -r)
    cr.curve_to(r * 0.08, -r * 0.2, r * 0.2, -r * 0.08, r, 0)
    cr.curve_to(r * 0.2, r * 0.08, r * 0.08, r * 0.2, 0, r)
    cr.curve_to(-r * 0.08, r * 0.2, -r * 0.2, r * 0.08, -r, 0)
    cr.curve_to(-r * 0.2, -r * 0.08, -r * 0.08, -r * 0.2, 0, -r)
    cr.set_source_rgba(1, 1, 1, alpha); cr.fill(); cr.restore()


def _mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3)) + (1,)


class Hero(Gtk.DrawingArea):
    """Quiet banner: a soft two-tone gradient taken from the active theme, the mark, the name and the version."""

    def __init__(self, th):
        super().__init__()
        self.th = th
        self.set_size_request(-1, 132)
        rnd = random.Random(5)
        self.sparks = [(rnd.uniform(0.55, 0.97), rnd.uniform(0.15, 0.85), rnd.choice((3, 4, 6)), rnd.uniform(0.15, 0.35)) for _ in range(5)]

    def do_draw(self, cr):
        a = self.get_allocation(); w, h = a.width, a.height
        th = self.th
        acc, sec = th.color("accent.primary")[:3], th.color("surface.primary")[:3]
        c1, c2 = _mix(sec, acc, 0.35), _mix(sec, (0.1, 0.08, 0.25), 0.25)
        lum = 0.299 * c1[0] + 0.587 * c1[1] + 0.114 * c1[2]
        fg = (0.1, 0.09, 0.22) if lum > 0.68 else (1, 1, 1)
        gfx.rrect(cr, 0, 0, w, h, 20)
        cr.set_source(gfx.lin(0, 0, w, h, [(0, c1), (1, c2)])); cr.fill_preserve()
        cr.clip()
        for fx, fy, r, al in self.sparks:
            cr.save(); _star(cr, fx * w, fy * h, r, al); cr.restore()
        ic.sparkle_logo(cr, 66, h / 2, 56, fg + (1,))
        gfx.text(cr, "glitterDE", 118, h / 2 - 16, 28, fg + (1,), 700)
        gfx.text(cr, "Version %s" % version(), 119, h / 2 + 14, 13, fg + (0.8,), 500)
        cr.reset_clip()
        return False


class Tile(Gtk.DrawingArea):
    """A usage tile: caption, big value, bar."""

    def __init__(self, title, value, sub, frac, rgb):
        super().__init__()
        self.title, self.value, self.sub, self.frac, self.rgb = title, value, sub, max(0.0, min(1.0, frac)), rgb
        self.set_size_request(150, 96)

    def do_draw(self, cr):
        a = self.get_allocation(); w, h = a.width, a.height
        dark = scheme.is_dark()
        ink = (0.93, 0.92, 0.98) if dark else (0.165, 0.176, 0.43)
        gfx.fill_rrect(cr, 0, 0, w, h, 14, (1, 1, 1, 0.08) if dark else (1, 1, 1, 0.5))
        gfx.text(cr, self.title.upper(), 14, 18, 10, ink + (0.62,), 700, spacing=0.8)
        gfx.text(cr, self.value, 14, 41, 21, ink + (1,), 700)
        gfx.text(cr, self.sub, 14, 62, 11, ink + (0.7,), 500, max_w=w - 28)
        gfx.fill_rrect(cr, 14, h - 18, w - 28, 7, 3.5, ink + (0.14,))
        if self.frac > 0.01:
            gfx.fill_rrect(cr, 14, h - 18, max(7, (w - 28) * self.frac), 7, 3.5,
                           gfx.lin(14, 0, w - 14, 0, [(0, _mix(self.rgb, (1, 1, 1), 0.35)), (1, self.rgb + (1,))]))
        return False


# ------------------------------------------------------------------ page
def build(win):
    th = win.th
    info = collect(th)
    p = win.page_box()
    p.pack_start(Hero(th), False, False, 0)

    acc = tuple(th.color("accent.primary")[:3])
    tm, tu = info["mem"]; dt, du = info["disk"]
    ld = load_fraction()
    row = Gtk.Box(spacing=10, homogeneous=True)
    row.pack_start(Tile("Memory", "%d%%" % (100 * tu / tm) if tm else "-", "%s of %s" % (gb(tu), gb(tm)), tu / tm if tm else 0, acc), True, True, 0)
    row.pack_start(Tile("Storage", "%d%%" % (100 * du / dt) if dt else "-", "%s of %s" % (gb(du), gb(dt)), du / dt if dt else 0, (0.45, 0.72, 1.0)), True, True, 0)
    row.pack_start(Tile("Processor load", "%d%%" % (ld * 100), "%d thread%s" % (os.cpu_count() or 1, "" if (os.cpu_count() or 1) == 1 else "s"), ld, (0.98, 0.55, 0.80)), True, True, 0)
    p.pack_start(row, False, False, 0)

    def rows(card, items):
        for k, v, icn in items:
            r = Gtk.Box(spacing=12)
            ico = Ico(icn, 15, scheme.ink(), 1.5); ico.set_valign(Gtk.Align.CENTER)
            r.pack_start(ico, False, False, 2)
            r.pack_start(label(k), False, False, 0)
            val = label(str(v), "muted", 1.0, ellipsize=False)
            val.set_line_wrap(True); val.set_selectable(True); val.set_max_width_chars(46); val.set_xalign(1.0); val.set_justify(Gtk.Justification.RIGHT)
            r.pack_end(val, True, True, 0)
            card.inner.pack_start(r, False, False, 4)

    c = win.card("This computer"); rows(c, info["device"]); p.pack_start(c, False, False, 0)
    c = win.card("glitterDE"); rows(c, info["desktop"]); p.pack_start(c, False, False, 0)

    # --- actions
    plain = "glitterDE %s\n" % version() + "\n".join("%s: %s" % (k, v) for k, v, _ in info["device"] + info["desktop"])
    acts = Gtk.Box(spacing=8)

    def copy(btn):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(plain, -1)
        btn.set_label("Copied!")
        GLib.timeout_add(1600, lambda: (btn.set_label("Copy system info"), False)[1])

    def open_path(path):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error:
            pass
    for text, cb in (("Copy system info", copy),
                     ("Open settings folder", lambda b: open_path(os.path.dirname(config.path())))):
        b = Gtk.Button(label=text); b.get_style_context().add_class("clear"); b.connect("clicked", cb)
        acts.pack_start(b, False, False, 0)
    p.pack_start(acts, False, False, 0)

    # --- experimental
    c = win.card("Advanced")
    sw = win.switch(model.experimental_enabled(), lambda v: (model.set("experimental.show", v), win.apply_experimental()))
    r = Gtk.Box(spacing=12)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    left.pack_start(label("Show experimental settings", "title"), False, False, 0)
    d = label("Reveal settings and pages that have nothing to configure yet, or that do not fully work yet. Off by default.", "muted", ellipsize=False)
    d.set_line_wrap(True); d.set_max_width_chars(46); d.set_xalign(0)
    left.pack_start(d, False, False, 0)
    r.pack_start(left, True, True, 0); sw.set_valign(Gtk.Align.CENTER); r.pack_end(sw, False, False, 0)
    c.inner.pack_start(r, False, False, 4)
    p.pack_start(c, False, False, 0)
    return p
