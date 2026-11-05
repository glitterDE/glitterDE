"""SparkMonitor: the glitterDE system monitor and task manager.

A sidebar of live resource cards (CPU, memory, disk, network, storage) and, next to it, either the process list or a detail page with a
history graph for the selected resource. Processes can be searched, sorted, ended (SIGTERM), force-quit (SIGKILL), paused, resumed and
re-prioritised. A process is only ever signalled if it is still the process the list showed (a recycled PID is never hit).

    sparkmonitor [--page processes|cpu|memory|disk|network|storage]
"""
import math
import os
import signal
import sys
import time
from collections import deque

import cairo  # noqa: F401  (drawing contexts come from Gtk; imported so a missing pycairo fails early and clearly)
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import appkit, config, gfx, scheme
from . import sysinfo as si
from .menus import GlassConfirm, GlassMenu
from .widgets import Ico, icon_button, label, search_overlay

CFG = "monitor.toml"
HISTORY = 60                                         # samples kept per graph
SIDEBAR_WIDTH = 262
INTERVALS = (("Fast (1 second)", 1.0), ("Normal (2 seconds)", 2.0), ("Slow (5 seconds)", 5.0), ("Paused", 0.0))
DEFAULTS = {"interval": 2.0, "per_core": False, "kernel": False, "confirm": True, "cmdline": False, "scope": "mine", "sort_col": 4,
            "sort_desc": True, "page": "processes"}
CRITICAL_NAMES = {"glitter-wm", "glitter-comp", "glitterde-session", "glitterde-shell", "systemd", "init", "Xorg", "Xwayland", "dbus-daemon",
                  "dbus-broker", "dbus-broker-lau"}
CRITICAL_CMD = ("glitter-wm", "glitter-comp", "glitterde-session", "glitterde-shell")
PRIORITIES = (("Very high", -10), ("High", -5), ("Normal", 0), ("Low", 10), ("Very low", 19))

# ListStore columns of the process table
C_PID, C_NAME, C_USER, C_STATE, C_CPU, C_MEM, C_IO, C_CMD, C_START, C_NICE, C_THREADS, C_KERNEL = range(12)


# ------------------------------------------------------------------------------------------------------------------------ helpers
def nice_max(v, floor=1.0):
    """A round axis maximum (1, 2, 2.5, 5 x 10^n) above v."""
    v = max(v * 1.15, floor)
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def fmt_pct(v):
    return "%d%%" % round(v)


def _mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


SERIES_ROLES = {"cpu": "accent.pink", "mem": "accent.blue", "swap": "status.warning", "read": "status.success", "write": "accent.pink",
                "rx": "status.info", "tx": "accent.pink", "core": "accent.primary", "system": "status.warning"}


def series_palette(th):
    """{name: (r, g, b)} graph colours from the theme's semantic roles, darkened on the light scheme so lines stay visible on frosted glass."""
    dark = scheme.is_dark()
    navy = tuple(scheme.NAVY[:3])
    out = {}
    for name, role in SERIES_ROLES.items():
        c = tuple(th.color(role)[:3])
        out[name] = c if dark else _mix(c, navy, 0.38)
    return out


def ink3():
    return tuple(scheme.ink()[:3])


def is_critical(p):
    return p.pid == 1 or p.name in CRITICAL_NAMES or any(k in p.cmd for k in CRITICAL_CMD)


# ------------------------------------------------------------------------------------------------------------------------ widgets
class Graph(Gtk.DrawingArea):
    """Scrolling history graph. series = [(key, name)]; ymax=None auto-scales (to a round number above `floor`)."""

    def __init__(self, series, ymax=None, fmt=fmt_pct, height=150, mini=False, floor=1.0):
        super().__init__()
        self.keys = [k for k, _ in series]
        self.names = dict(series)
        self.data = {k: deque([0.0] * HISTORY, maxlen=HISTORY) for k in self.keys}
        self.colors, self.ink = {}, (1, 1, 1)
        self.ymax, self.fmt, self.mini, self.floor = ymax, fmt, mini, floor
        self.caption = ""
        self.set_size_request(86 if mini else -1, height)
        if not mini:
            self.set_hexpand(True)

    def push(self, **vals):
        for k in self.keys:
            self.data[k].append(float(vals.get(k, 0.0)))
        self.queue_draw()

    def clear(self):
        for d in self.data.values():
            d.clear()
            d.extend([0.0] * HISTORY)
        self.queue_draw()

    def top(self):
        return self.ymax if self.ymax else nice_max(max(max(d) for d in self.data.values()), self.floor)

    def do_draw(self, cr):
        a = self.get_allocation()
        w, h = a.width, a.height
        ink = self.ink
        r = 7 if self.mini else 12
        gfx.fill_rrect(cr, 0, 0, w, h, r, ink + (0.06,))
        cr.save()
        gfx.rrect(cr, 0, 0, w, h, r)
        cr.clip()
        top = self.top()
        y0 = 4 if self.mini else 26
        y1 = h - (3 if self.mini else 6)
        if not self.mini:
            for i in range(1, 4):
                y = y0 + (y1 - y0) * i / 4.0
                cr.move_to(0, y)
                cr.line_to(w, y)
                cr.set_source_rgba(*(ink + (0.08,)))
                cr.set_line_width(1)
                cr.stroke()
            step = w / 6.0
            for i in range(1, 6):                              # time marks: one per tenth of the history
                cr.move_to(i * step, y0)
                cr.line_to(i * step, y1)
                cr.set_source_rgba(*(ink + (0.05,)))
                cr.stroke()
        for k in self.keys:
            col = self.colors.get(k, (0.6, 0.6, 1.0))
            vals = list(self.data[k])
            n = len(vals)
            pts = [(w * i / (n - 1.0), y1 - (y1 - y0) * min(1.0, v / top)) for i, v in enumerate(vals)]
            cr.move_to(pts[0][0], y1)
            for p in pts:
                cr.line_to(*p)
            cr.line_to(pts[-1][0], y1)
            cr.close_path()
            cr.set_source(gfx.lin(0, y0, 0, y1, [(0, col + (0.42,)), (1, col + (0.04,))]))
            cr.fill()
            cr.move_to(*pts[0])
            for p in pts[1:]:
                cr.line_to(*p)
            cr.set_source_rgba(*(col + (0.96,)))
            cr.set_line_width(1.3 if self.mini else 1.8)
            cr.set_line_join(1)                                # cairo.LINE_JOIN_ROUND
            cr.stroke()
        cr.restore()
        gfx.stroke_rrect(cr, 0.5, 0.5, w - 1, h - 1, r, ink + (0.16,), 1.0)
        if not self.mini:
            gfx.text(cr, self.fmt(top), 12, 14, 10.5, ink + (0.7,), 400, "l")
            gfx.text(cr, self.caption, w - 12, 14, 10.5, ink + (0.7,), 400, "r")
            gfx.text(cr, self.fmt(0), 12, h - 11, 10.5, ink + (0.55,), 400, "l")
            if len(self.keys) > 1:                             # legend
                x = w / 2.0 - sum(gfx.text_width(cr, self.names[k], 10.5) + 22 for k in self.keys) / 2.0
                for k in self.keys:
                    col = self.colors.get(k, (0.6, 0.6, 1.0))
                    cr.arc(x + 4, 14, 4, 0, 2 * math.pi)
                    cr.set_source_rgba(*(col + (1.0,)))
                    cr.fill()
                    x += 12 + gfx.text(cr, self.names[k], x + 12, 14, 10.5, ink + (0.8,), 400, "l") + 10
        return False


class Composition(Gtk.DrawingArea):
    """One horizontal bar split into labelled segments (memory: in use / cache / free)."""

    def __init__(self):
        super().__init__()
        self.segs, self.ink = [], (1, 1, 1)                    # [(fraction, (r, g, b), alpha, name)]
        self.set_size_request(-1, 46)
        self.set_hexpand(True)

    def set(self, segs):
        self.segs = segs
        self.queue_draw()

    def do_draw(self, cr):
        a = self.get_allocation()
        w = a.width
        gfx.fill_rrect(cr, 0, 0, w, 20, 8, self.ink + (0.08,))
        cr.save()
        gfx.rrect(cr, 0, 0, w, 20, 8)
        cr.clip()
        x = 0.0
        for frac, col, alpha, _ in self.segs:
            seg = max(0.0, frac) * w
            if seg > 0.5:
                cr.rectangle(x, 0, seg, 20)
                cr.set_source_rgba(*(col + (alpha,)))
                cr.fill()
            x += seg
        cr.restore()
        gfx.stroke_rrect(cr, 0.5, 0.5, w - 1, 19, 8, self.ink + (0.16,), 1.0)
        lx = 2
        for frac, col, alpha, name in self.segs:
            cr.arc(lx + 5, 35, 4.5, 0, 2 * math.pi)
            cr.set_source_rgba(*(col + (max(alpha, 0.35),)))
            cr.fill()
            lx += 14 + gfx.text(cr, name, lx + 14, 35, 11, self.ink + (0.85,), 400, "l") + 14
        return False


class StatGrid(Gtk.Grid):
    """Grid of small captioned values (caption above, value below) that can be updated by key."""

    def __init__(self, items, columns=4):
        super().__init__()
        self.set_column_spacing(26)
        self.set_row_spacing(10)
        self.set_column_homogeneous(True)
        self.vals = {}
        for i, (key, title) in enumerate(items):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.pack_start(label(title, "muted"), False, False, 0)
            v = label("—", "h1")
            box.pack_start(v, False, False, 0)
            self.attach(box, i % columns, i // columns, 1, 1)
            self.vals[key] = v

    def set(self, **kw):
        for k, t in kw.items():
            if k in self.vals:
                self.vals[k].set_text(t)


def frame(child, margin=14):
    """Frosted panel (.inner) around a page's content."""
    inner = Gtk.Box()
    inner.get_style_context().add_class("inner")
    child.set_margin_start(margin); child.set_margin_end(margin); child.set_margin_top(margin); child.set_margin_bottom(margin)
    inner.pack_start(child, True, True, 0)
    return inner


def page_header(title, sub):
    row = Gtk.Box(spacing=12)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    left.pack_start(label(title, "proptitle"), False, False, 0)
    s = label(sub, "muted")
    left.pack_start(s, False, False, 0)
    row.pack_start(left, True, True, 0)
    big = label("", "clock", 1.0)
    row.pack_end(big, False, False, 0)
    return row, s, big


def page_box():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(16)
    return box


def scrolled(child):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.add(child)
    return sw


# ------------------------------------------------------------------------------------------------------------------------ the window
class SparkMonitor(appkit.GlassWindow):
    PAGES = ("processes", "cpu", "memory", "disk", "network", "storage")

    def __init__(self, page=None):
        super().__init__("SparkMonitor", "sparkmonitor", "window_light", (1080, 700))
        self.cfg = config.load(CFG)
        saved = self.cfg.get("view", {})
        self.opt = {k: (type(v)(saved[k]) if k in saved and not isinstance(v, bool) else bool(saved[k]) if k in saved else v) for k, v in DEFAULTS.items()}
        self.me = si.username(os.getuid())
        self.ncpu = os.cpu_count() or 1
        self.sampler, self.ptable = si.Sampler(), si.ProcessTable()
        self.procs, self.rows, self._cache = {}, {}, {}
        self._timer, self._ticks, self._notice_src, self._query = 0, 0, 0, ""
        self._net_sel = None                       # None = all networks, else an interface name
        self._mem_total = 1
        self._failed = set()
        self.pal = series_palette(self.th)
        self.model, self.cpu_name = None, si.cpu_model()
        self._css()

        outer = Gtk.Box(spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, "set_margin_" + m)(8)
        self.add(outer)
        outer.pack_start(self._build_sidebar(), False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.notice_box = Gtk.Box(spacing=8)
        self.notice_box.set_no_show_all(True)
        self.notice_box.get_style_context().add_class("card2")
        self.notice_box.set_border_width(8)
        self.notice_lbl = label("", None, 0.0, ellipsize=False)
        self.notice_btns = Gtk.Box(spacing=6)
        self.notice_box.pack_start(self.notice_lbl, True, True, 0)
        self.notice_box.pack_start(self.notice_btns, False, False, 0)
        self.notice_box.pack_start(icon_button("close", 9, "Dismiss", self.hide_notice, color=scheme.ink(), pad=5), False, False, 0)
        right.pack_start(self.notice_box, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        for name, builder in (("processes", self._build_procs), ("cpu", self._build_cpu), ("memory", self._build_memory),
                              ("disk", self._build_disk), ("network", self._build_network), ("storage", self._build_storage)):
            self.stack.add_named(builder(), name)
        right.pack_start(self.stack, True, True, 0)
        outer.pack_start(right, True, True, 0)
        self._recolor()
        self.connect("key-press-event", self._key)
        self.connect("delete-event", self._closing)
        self.show_all()
        self.notice_box.hide()
        want = page if page in self.PAGES else (self.opt["page"] if self.opt["page"] in self.PAGES else "processes")
        self.show_page(want)
        self.cards[want].set_active(True)
        self._start_timer()
        GLib.idle_add(lambda: (self._tick(), False)[1])

    # ---------------------------------------------------------------- styling
    def _css(self):
        ink = ink3()
        rgba = lambda a: "rgba(%d,%d,%d,%.2f)" % (ink[0] * 255, ink[1] * 255, ink[2] * 255, a)
        p = Gtk.CssProvider()
        p.load_from_data(("""
        treeview.proctree, treeview.proctree.view { background-color: transparent; background-image: none; }
        treeview.proctree header button { font-weight: 600; font-size: 11px; padding: 7px 8px; }
        treeview.proctree:hover { background-color: transparent; }
        button.card { padding: 8px 10px; border-radius: 14px; }
        button.card label.cardtitle { font-size: 13px; font-weight: 600; }
        button.card label.cardval { font-size: 12px; }
        progressbar.usage trough, progressbar.usage progress { min-height: 10px; border-radius: 5px; }
        progressbar.usage.warn progress { background-image: linear-gradient(to right, #ffd37a, #ff9f5a); }
        progressbar.usage.crit progress { background-image: linear-gradient(to right, #ff9aa8, #ff5f7a); }
        .fsrow { background-color: %s; border-radius: 12px; }
        """ % rgba(0.06)).encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 14)

    def _recolor(self):
        self.pal = series_palette(self.th)
        ink = ink3()
        for g in self._graphs():
            g.colors = {k: self.pal.get(k, self.pal["cpu"]) for k in g.keys}
            g.ink = ink
            g.queue_draw()
        self.comp.ink = ink
        self._set_composition()
        self.tree.queue_draw()

    def _graphs(self):
        return [self.g_cpu, self.g_mem, self.g_swap, self.g_disk, self.g_net, *self.core_graphs, *[c.graph for c in self.cards.values() if c.graph]]

    def _reload(self):
        r = super()._reload()
        try:
            self._recolor()
        except Exception as e:                                   # a broken theme must not take the monitor down
            print("sparkmonitor: theme reload failed:", e, file=sys.stderr)
        return r

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self):
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        side.get_style_context().add_class("sidebar")
        side.set_size_request(SIDEBAR_WIDTH, -1)
        side.set_hexpand(False)
        side.set_border_width(8)
        self.cards = {}
        group = None
        specs = (("processes", "Processes", "list", None, None, None), ("cpu", "CPU", "chip", [("cpu", "CPU")], 100, fmt_pct),
                 ("memory", "Memory", "memory", [("mem", "Memory")], 100, fmt_pct), ("disk", "Disk", "drive", [("read", "Read"), ("write", "Write")], None, si.fmt_rate),
                 ("network", "Network", "network", [("rx", "Receive"), ("tx", "Send")], None, si.fmt_rate), ("storage", "Storage", "folder_line", None, None, None))
        for key, title, icon, series, ymax, fmt in specs:
            card = self._make_card(group, key, title, icon, series, ymax, fmt)
            group = group or card
            self.cards[key] = card
            side.pack_start(card, False, False, 0)
        side.pack_start(Gtk.Box(), True, True, 0)
        self.b_menu = icon_button("list", 15, "Options", None, color=scheme.ink(), pad=7)
        self.b_menu.set_halign(Gtk.Align.START)
        self.b_menu.connect("clicked", lambda b: self._popup_above(b, self._menu_items(), 270))
        side.pack_start(self.b_menu, False, False, 0)
        return side

    def _make_card(self, group, key, title, icon, series, ymax, fmt):
        b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
        b.set_mode(False)
        b.get_style_context().add_class("tilebtn")
        b.get_style_context().add_class("card")
        row = Gtk.Box(spacing=10)
        b.graph = None
        if series:
            b.graph = Graph(series, ymax=ymax, fmt=fmt, height=44, mini=True, floor=64 * 1024 if key == "network" else 1024 * 1024)
            row.pack_start(b.graph, False, False, 0)
        else:
            row.pack_start(Ico(icon, 24, scheme.ink(), 1.5), False, False, 31)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        col.set_valign(Gtk.Align.CENTER)
        b.title_l, b.value_l, b.sub_l = label(title, "cardtitle"), label("", "cardval"), label("", "muted")
        for l in (b.title_l, b.value_l, b.sub_l):
            l.set_ellipsize(Pango.EllipsizeMode.END)
            l.set_width_chars(1)
            l.set_max_width_chars(1)
            l.set_xalign(0.0)
            col.pack_start(l, False, False, 0)
        row.pack_start(col, True, True, 0)
        b.add(row)
        b.connect("toggled", lambda w, k=key: w.get_active() and self.show_page(k))
        return b

    # ---------------------------------------------------------------- pages
    def show_page(self, name):
        self.stack.set_visible_child_name(name)
        self.opt["page"] = name
        if name != "processes":
            self.hide_notice()
        self._tick_ui(force=True)

    def _build_procs(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        bar = Gtk.Box(spacing=6)
        self.search = Gtk.Entry()
        self.search.set_placeholder_text("Search processes")
        self.search.set_width_chars(26)
        self.search.connect("changed", self._search_changed)
        bar.pack_start(search_overlay(self.search, scheme.ink()), False, False, 0)
        self.b_mine, self.b_all = Gtk.Button(label="My processes"), Gtk.Button(label="All processes")
        for b, sc in ((self.b_mine, "mine"), (self.b_all, "all")):
            b.get_style_context().add_class("pill")
            b.connect("clicked", lambda _b, s=sc: self.set_scope(s))
            bar.pack_start(b, False, False, 0)
        spacer = Gtk.Box()
        bar.pack_start(spacer, True, True, 0)
        self.b_end = Gtk.Button(label="End task")
        self.b_kill = Gtk.Button(label="Force quit")
        for b, cb in ((self.b_end, lambda *_: self.end_task(False)), (self.b_kill, lambda *_: self.end_task(True))):
            b.get_style_context().add_class("choicebtn")
            b.connect("clicked", cb)
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)

        types = (int, str, str, str, float, float, float, str, float, int, int, bool)
        self.store = Gtk.ListStore(*types)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.model = Gtk.TreeModelSort(model=self.filter)
        self.model.set_sort_func(C_NAME, lambda m, a, b, d: _cmp(m.get_value(a, C_NAME).casefold(), m.get_value(b, C_NAME).casefold()), None)
        self.tree = Gtk.TreeView(model=self.model)
        self.tree.get_style_context().add_class("proctree")
        self.tree.set_headers_clickable(True)
        self.tree.set_enable_search(False)
        self.tree.set_fixed_height_mode(False)
        self.tree.set_rubber_banding(False)

        def col(title, cid, fn=None, width=None, expand=False, xalign=0.0, ellipsize=False):
            r = Gtk.CellRendererText()
            r.set_property("xalign", xalign)
            r.set_padding(8, 5)
            if ellipsize:
                r.set_property("ellipsize", Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=cid)
            if fn:
                c.set_cell_data_func(r, fn)
            c.set_sort_column_id(cid)
            c.set_resizable(True)
            c.set_expand(expand)
            if width:
                c.set_min_width(width)
            c.set_alignment(xalign)
            self.tree.append_column(c)
            return c
        self.c_name = col("Name", C_NAME, expand=True, width=220, ellipsize=True)
        self.c_cmd = col("Command", C_CMD, width=220, ellipsize=True)
        col("PID", C_PID, width=70, xalign=1.0)
        col("User", C_USER, width=90)
        col("Status", C_STATE, width=110)
        col("CPU", C_CPU, self._cell_cpu, 80, xalign=1.0)
        col("Memory", C_MEM, self._cell_mem, 95, xalign=1.0)
        col("Disk", C_IO, self._cell_io, 95, xalign=1.0)
        self.c_cmd.set_visible(self.opt["cmdline"])
        self.model.set_sort_column_id(self.opt["sort_col"], Gtk.SortType.DESCENDING if self.opt["sort_desc"] else Gtk.SortType.ASCENDING)
        self.tree.get_selection().connect("changed", lambda *_: self._sel_changed())
        self.tree.connect("button-press-event", self._press)
        self.tree.connect("row-activated", lambda *_: self.show_properties())
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.tree)
        box.pack_start(frame(sw, 4), True, True, 0)
        self.proc_summary = label("", "muted", 0.0)
        self.proc_summary.set_margin_start(6)
        box.pack_start(self.proc_summary, False, False, 0)
        self._mark_scope()
        self._sel_changed()
        return box

    def _build_cpu(self):
        box = page_box()
        head, self.cpu_sub, self.cpu_big = page_header("CPU", self.cpu_name[0])
        box.pack_start(head, False, False, 0)
        self.g_cpu = Graph([("cpu", "Utilization")], ymax=100, fmt=fmt_pct, height=190)
        box.pack_start(self.g_cpu, False, False, 0)
        self.stats_cpu = StatGrid([("util", "Utilization"), ("speed", "Speed"), ("procs", "Processes"), ("threads", "Threads"),
                                   ("uptime", "Up time"), ("load", "Load average"), ("temp", "Temperature"), ("cores", "Logical processors")])
        box.pack_start(self.stats_cpu, False, False, 4)
        box.pack_start(label("Logical processors", "h2"), False, False, 0)
        self.core_flow = Gtk.FlowBox()
        self.core_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.core_flow.set_min_children_per_line(2)
        self.core_flow.set_max_children_per_line(4)
        self.core_flow.set_homogeneous(True)
        self.core_flow.set_row_spacing(8)
        self.core_flow.set_column_spacing(8)
        self.core_graphs, self.core_labels = [], []
        for i in range(self.ncpu):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            top = Gtk.Box()
            top.pack_start(label("Core %d" % i, "muted"), True, True, 0)
            pl = label("0%", "muted", 1.0)
            top.pack_end(pl, False, False, 0)
            g = Graph([("core", "Core")], ymax=100, fmt=fmt_pct, height=46, mini=True)
            g.set_hexpand(True)
            cell.pack_start(top, False, False, 0)
            cell.pack_start(g, False, False, 0)
            self.core_flow.add(cell)
            self.core_graphs.append(g)
            self.core_labels.append(pl)
        box.pack_start(self.core_flow, False, False, 0)
        return frame(scrolled(box), 0)

    def _build_memory(self):
        box = page_box()
        head, self.mem_sub, self.mem_big = page_header("Memory", "")
        box.pack_start(head, False, False, 0)
        self.g_mem = Graph([("mem", "In use")], ymax=100, fmt=fmt_pct, height=190)
        box.pack_start(self.g_mem, False, False, 0)
        box.pack_start(label("Composition", "h2"), False, False, 0)
        self.comp = Composition()
        box.pack_start(self.comp, False, False, 0)
        self.stats_mem = StatGrid([("used", "In use"), ("avail", "Available"), ("cached", "Cached"), ("buffers", "Buffers"),
                                   ("shared", "Shared"), ("dirty", "Waiting to be written"), ("swap", "Swap in use"), ("total", "Installed")])
        box.pack_start(self.stats_mem, False, False, 4)
        box.pack_start(label("Swap", "h2"), False, False, 0)
        self.g_swap = Graph([("swap", "Swap in use")], ymax=100, fmt=fmt_pct, height=90)
        box.pack_start(self.g_swap, False, False, 0)
        return frame(scrolled(box), 0)

    def _build_disk(self):
        box = page_box()
        head, self.disk_sub, self.disk_big = page_header("Disk", "Read and write activity of all drives")
        box.pack_start(head, False, False, 0)
        self.g_disk = Graph([("read", "Read"), ("write", "Write")], fmt=si.fmt_rate, height=190, floor=1024 * 1024)
        box.pack_start(self.g_disk, False, False, 0)
        self.stats_disk = StatGrid([("read", "Read speed"), ("write", "Write speed"), ("busy", "Active time"), ("tread", "Read since start-up"),
                                    ("twrite", "Written since start-up")], 5)
        box.pack_start(self.stats_disk, False, False, 4)
        box.pack_start(label("Drives", "h2"), False, False, 0)
        self.disk_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._disk_names = None
        box.pack_start(self.disk_list, False, False, 0)
        return frame(scrolled(box), 0)

    def _build_network(self):
        box = page_box()
        head, self.net_sub, self.net_big = page_header("Network", "")
        box.pack_start(head, False, False, 0)
        pick = Gtk.Box(spacing=8)
        pick.pack_start(label("Show", "muted"), False, False, 0)
        self.b_iface = Gtk.Button()
        self.b_iface.get_style_context().add_class("choicebtn")
        self.iface_lbl = label("All networks", None)
        row = Gtk.Box(spacing=6)
        row.pack_start(self.iface_lbl, False, False, 0)
        row.pack_start(Ico("chev_down", 11, scheme.ink(), 1.8), False, False, 0)
        self.b_iface.add(row)
        self.b_iface.connect("clicked", lambda b: self._popup_below(b, self._iface_items(), 220))
        pick.pack_start(self.b_iface, False, False, 0)
        box.pack_start(pick, False, False, 0)
        self.g_net = Graph([("rx", "Receive"), ("tx", "Send")], fmt=si.fmt_rate, height=190, floor=64 * 1024)
        box.pack_start(self.g_net, False, False, 0)
        self.stats_net = StatGrid([("rx", "Receive"), ("tx", "Send"), ("trx", "Received since start-up"), ("ttx", "Sent since start-up"),
                                   ("kind", "Connection"), ("speed", "Link speed"), ("state", "State"), ("errors", "Errors")])
        box.pack_start(self.stats_net, False, False, 4)
        box.pack_start(label("Adapters", "h2"), False, False, 0)
        self.net_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.net_list, False, False, 0)
        return frame(scrolled(box), 0)

    def _build_storage(self):
        box = page_box()
        head, self.sto_sub, self.sto_big = page_header("Storage", "Mounted file systems")
        box.pack_start(head, False, False, 0)
        self.fs_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self.fs_list, False, False, 0)
        self._fs_sig = None
        return frame(scrolled(box), 0)

    # ---------------------------------------------------------------- process table
    def _visible(self, model, it, _d=None):
        pid, name, user, cmd, kernel = model.get(it, C_PID, C_NAME, C_USER, C_CMD, C_KERNEL)
        if kernel and not self.opt["kernel"]:
            return False
        if self.opt["scope"] == "mine" and user != self.me:
            return False
        q = self._query
        if q and q not in name.lower() and q not in cmd.lower() and q not in user.lower() and not str(pid).startswith(q):
            return False
        return True

    def _search_changed(self, e):
        self._query = e.get_text().strip().lower()
        self.filter.refilter()
        self._summary()

    def set_scope(self, scope):
        self.opt["scope"] = scope
        self._mark_scope()
        self.filter.refilter()
        self._summary()

    def _mark_scope(self):
        for b, sc in ((self.b_mine, "mine"), (self.b_all, "all")):
            ctx = b.get_style_context()
            (ctx.add_class if self.opt["scope"] == sc else ctx.remove_class)("active")

    def _selected(self):
        m, it = self.tree.get_selection().get_selected()
        if it is None:
            return None
        return self.procs.get(m.get_value(it, C_PID))

    def _sel_changed(self):
        p = self._selected()
        self.b_end.set_sensitive(p is not None)
        self.b_kill.set_sensitive(p is not None)

    def _cell_cpu(self, column, r, model, it, _d=None):
        v = model.get_value(it, C_CPU)
        shown = v if self.opt["per_core"] else v / self.ncpu
        r.set_property("text", "%.1f%%" % shown if shown >= 0.05 else "0%")
        self._heat(r, model, it, min(1.0, v / self.ncpu / 60.0), self.pal["cpu"])        # the heat always follows the share of the whole machine

    def _cell_mem(self, column, r, model, it, _d=None):
        v = model.get_value(it, C_MEM)
        r.set_property("text", si.fmt_bytes(v))
        self._heat(r, model, it, min(1.0, v / max(1.0, self._mem_total * 0.2)), self.pal["mem"])

    def _cell_io(self, column, r, model, it, _d=None):
        v = model.get_value(it, C_IO)
        r.set_property("text", "—" if v < 0 else ("0" if v < 1 else si.fmt_rate(v)))
        self._heat(r, model, it, 0.0 if v < 0 else min(1.0, v / (20 * 1024 * 1024)), self.pal["read"])

    def _heat(self, r, model, it, level, rgb):
        """Tint the cell by how much the process uses (like a heat map); selected rows keep the plain selection colour."""
        if level > 0.02 and not self.tree.get_selection().iter_is_selected(it):
            r.set_property("cell-background-rgba", Gdk.RGBA(rgb[0], rgb[1], rgb[2], 0.10 + 0.30 * level))
            r.set_property("cell-background-set", True)
        else:
            r.set_property("cell-background-set", False)

    def _update_procs(self, procs):
        self.procs = {p.pid: p for p in procs}
        seen = set()
        for p in procs:
            io = -1.0 if p.io is None else p.io
            vals = (p.pid, p.name, p.user, si.STATES.get(p.state, p.state), p.cpu, float(p.mem), io, p.cmd, float(p.start), p.nice, p.threads, p.kernel)
            seen.add(p.pid)
            it = self.rows.get(p.pid)
            if it is None:
                self.rows[p.pid] = self.store.append(vals)
                self._cache[p.pid] = vals
            elif self._cache[p.pid] != vals:
                old = self._cache[p.pid]
                cols = [i for i in range(len(vals)) if vals[i] != old[i]]
                self.store.set(it, cols, [vals[i] for i in cols])
                self._cache[p.pid] = vals
        for pid in [k for k in self.rows if k not in seen]:
            self.store.remove(self.rows.pop(pid))
            self._cache.pop(pid, None)
        self._summary()

    def _summary(self):
        n, th = si.counts(self.procs.values())
        shown = len(self.model) if self.model is not None else 0
        self.proc_summary.set_text("%d shown of %d processes · %d threads" % (shown, n, th))

    # ---------------------------------------------------------------- actions on processes
    def _press(self, view, ev):
        if ev.button != 3:
            return False
        hit = view.get_path_at_pos(int(ev.x), int(ev.y))
        if hit is None:
            return False
        view.get_selection().select_path(hit[0])
        view.grab_focus()
        p = self._selected()
        if p is None:
            return True
        items = [("itemi", "list", "Properties", self.show_properties, True, "Enter"), ("sep",),
                 ("itemi", None, "End task", lambda: self.end_task(False), True, "Del"),
                 ("itemi", None, "Force quit", lambda: self.end_task(True), True, "Shift+Del"), ("sep",),
                 ("item", "Resume" if p.state == "T" else "Pause", lambda: self.pause(p.state != "T")),
                 ("head", "Priority")]
        items += [("check", "%s (%d)" % (n, v), p.nice == v, lambda v=v: self.set_priority(v)) for n, v in PRIORITIES]
        items += [("sep",), ("item", "Copy command line", lambda: self.copy(p.cmd)), ("item", "Open working folder", self.open_cwd)]
        GlassMenu(items, light=True, theme=self.th, min_width=240).popup_at(ev.x_root, ev.y_root)
        return True

    def copy(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.say("Copied")

    def open_cwd(self):
        p = self._selected()
        if p is None:
            return
        cwd = self.ptable.details(p.pid).get("cwd")
        if cwd and os.path.isdir(cwd):
            try:
                from . import services
                services.fire(["sparkfiles", cwd])
            except Exception as e:
                self.say("Could not open the folder: %s" % e)
        else:
            self.say("The working folder of this process is not accessible.")

    def end_task(self, force=False):
        p = self._selected()
        if p is None:
            return
        crit = is_critical(p)
        if not self.opt["confirm"] and not force and not crit:
            self._send(p, signal.SIGTERM)
            return
        if force:
            title, verb = "Force quit %s?" % p.name, "Force quit"
            detail = "%s (PID %d) is stopped immediately and gets no chance to save its work or clean up." % (p.name, p.pid)
        else:
            title, verb = "End %s?" % p.name, "End task"
            detail = "%s (PID %d) is asked to quit. Unsaved work in it may be lost." % (p.name, p.pid)
        if crit:
            detail += "\n\nThis is part of your desktop session or the system itself: ending it can close your session or make the desktop unusable."
        if p.user != self.me:
            detail += "\n\nIt belongs to %s, so you may not be allowed to." % p.user
        GlassConfirm(title, detail, verb, lambda: self._send(p, signal.SIGKILL if force else signal.SIGTERM), theme=self.th).show_centered()

    def _send(self, p, sig):
        ok, msg = si.signal_process(p.pid, p.start, sig)
        if not ok:
            self.say(msg or "Could not signal the process.")
            return
        self.say("%s sent to %s" % ("Force quit" if sig == signal.SIGKILL else "End request", p.name), ms=3500)
        if sig == signal.SIGTERM:
            GLib.timeout_add(3000, self._still_there, p)
        self._tick_ui(force=True)

    def _still_there(self, p):
        cur = self.procs.get(p.pid)
        if cur is not None and cur.start == p.start and cur.state not in ("Z", "X"):
            self.say("%s did not quit." % p.name, [("Force quit", lambda: self._send(p, signal.SIGKILL))], ms=12000)
        return False

    def pause(self, stop):
        p = self._selected()
        if p is None:
            return
        if stop and p.pid == os.getpid():
            self.say("Pausing SparkMonitor itself would freeze this window, so it is not allowed.")
            return
        if stop and is_critical(p):
            self.say("Pausing %s would freeze your session, so it is not allowed here." % p.name)
            return
        ok, msg = si.signal_process(p.pid, p.start, signal.SIGSTOP if stop else signal.SIGCONT)
        self.say(("Paused " if stop else "Resumed ") + p.name if ok else msg, ms=3500)

    def set_priority(self, nice):
        p = self._selected()
        if p is None:
            return
        ok, msg = si.set_nice(p.pid, nice)
        self.say("%s now has priority %d" % (p.name, nice) if ok else msg, ms=5000 if not ok else 3500)

    def show_properties(self, *_):
        p = self._selected()
        if p is None:
            return
        d = self.ptable.details(p.pid)
        parent = self.procs.get(p.ppid)
        started = time.strftime("%a %d %b %H:%M:%S", time.localtime(si.boot_time() + p.start / si.CLK))
        rows = [("Name", p.name), ("Process ID", str(p.pid)), ("Parent", "%s (%d)" % (parent.name, p.ppid) if parent else str(p.ppid)),
                ("User", p.user), ("Status", si.STATES.get(p.state, p.state)), ("Started", started),
                ("CPU time", si.fmt_duration(p.ticks / si.CLK)), ("Threads", str(p.threads)), ("Priority (nice)", str(p.nice)),
                ("Memory", "%s  (resident %s, shared %s)" % (si.fmt_bytes(p.mem), si.fmt_bytes(p.rss), si.fmt_bytes(p.shared))),
                ("Virtual memory", si.fmt_bytes(p.virt)), ("Open files", str(d["fds"]) if d.get("fds") is not None else "not accessible"),
                ("Program", d.get("exe") or "not accessible"), ("Working folder", d.get("cwd") or "not accessible"), ("Command line", p.cmd)]
        dlg = appkit.GlassDialog("Properties — %s" % p.name, "sparkmonitor-dialog", parent=self, size=(560, 10))
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(7)
        grid.set_border_width(16)
        for i, (k, v) in enumerate(rows):
            grid.attach(label(k, "muted", 0.0), 0, i, 1, 1)
            l = label(v, None, 0.0, ellipsize=False)
            l.set_line_wrap(True)
            l.set_max_width_chars(60)
            l.set_selectable(True)
            grid.attach(l, 1, i, 1, 1)
        dlg.body.pack_start(grid, True, True, 0)
        dlg.show_all()
        dlg.present()

    # ---------------------------------------------------------------- refresh loop
    def _start_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        iv = self.opt["interval"]
        if iv > 0:
            self._timer = GLib.timeout_add(int(iv * 1000), self._tick)
        for g in self._graphs():
            g.caption = ("%d seconds" % int(HISTORY * iv)) if iv else "paused"
        for k in (self.g_cpu, self.g_mem, self.g_swap, self.g_disk, self.g_net):
            k.queue_draw()

    def _guard(self, name, fn, *a):
        """Run one reader; a failing /proc file must not stop the whole refresh. Reported once per reader."""
        try:
            return fn(*a)
        except Exception as e:
            if name not in self._failed:
                self._failed.add(name)
                print("sparkmonitor: %s unavailable: %s" % (name, e), file=sys.stderr)
            return None

    def _tick(self):
        self._ticks += 1
        self.snap = {}
        self.snap["cpu"] = self._guard("cpu", self.sampler.cpu)
        self.snap["mem"] = self._guard("memory", si.memory)
        self.snap["disk"] = self._guard("disks", self.sampler.disks)
        self.snap["net"] = self._guard("network", self.sampler.network)
        procs = self._guard("processes", self.ptable.poll)
        if procs is not None:
            self._update_procs(procs)
        s = self.snap
        if s["cpu"]:
            self.g_cpu.push(cpu=s["cpu"]["total"] * 100)
            for g, l, v in zip(self.core_graphs, self.core_labels, s["cpu"]["cores"]):
                g.push(core=v * 100)
                l.set_text("%d%%" % round(v * 100))
        if s["mem"]:
            m = s["mem"]
            self._mem_total = max(1, m["total"])
            self.g_mem.push(mem=m["used"] / self._mem_total * 100)
            self.g_swap.push(swap=(m["swap_used"] / m["swap_total"] * 100) if m["swap_total"] else 0)
        if s["disk"]:
            self.g_disk.push(read=s["disk"]["read"], write=s["disk"]["write"])
        if s["net"]:
            self._push_net(s["net"])
        for key, g in (("cpu", self.cards["cpu"].graph), ("memory", self.cards["memory"].graph), ("disk", self.cards["disk"].graph), ("network", self.cards["network"].graph)):
            src = {"cpu": self.g_cpu, "memory": self.g_mem, "disk": self.g_disk, "network": self.g_net}[key]
            if key == "network":
                tot = s["net"]
                if tot:
                    g.push(rx=tot["rx"], tx=tot["tx"])           # the card always shows the whole machine, whatever adapter the page shows
            else:
                g.push(**{k: src.data[k][-1] for k in src.keys})
        self._tick_ui()
        return True

    def _push_net(self, net):
        if self._net_sel and self._net_sel in net["ifaces"]:
            i = net["ifaces"][self._net_sel]
            self.g_net.push(rx=i["rx"], tx=i["tx"])
        else:
            self.g_net.push(rx=net["rx"], tx=net["tx"])

    def _tick_ui(self, force=False):
        """Labels and detail pages; only the visible page is refreshed in full."""
        s = getattr(self, "snap", None)
        if not s:
            return
        page = self.stack.get_visible_child_name()
        slow = force or self._ticks % 5 == 1
        cpu, mem, disk, net = s["cpu"], s["mem"], s["disk"], s["net"]
        c = self.cards
        n, th = si.counts(self.procs.values())
        c["processes"].value_l.set_text("%d processes" % n)
        c["processes"].sub_l.set_text("%d threads" % th)
        if cpu:
            c["cpu"].value_l.set_text("%d%%" % round(cpu["total"] * 100))
        if slow or page == "cpu":
            fr = si.cpu_freqs()
            avg = sum(fr) / len(fr) if fr else 0
            self._freq = avg
            c["cpu"].sub_l.set_text(si.fmt_hz(avg) if avg else "%d cores" % self.ncpu)
        if mem:
            c["memory"].value_l.set_text(si.fmt_bytes(mem["used"]))
            c["memory"].sub_l.set_text("%d%% of %s" % (round(mem["used"] / max(1, mem["total"]) * 100), si.fmt_bytes(mem["total"])))
        if disk:
            c["disk"].value_l.set_text("R %s" % si.fmt_rate(disk["read"]))
            c["disk"].sub_l.set_text("W %s" % si.fmt_rate(disk["write"]))
        if net:
            c["network"].value_l.set_text("↓ %s" % si.fmt_rate(net["rx"]))
            c["network"].sub_l.set_text("↑ %s" % si.fmt_rate(net["tx"]))
        if page == "cpu" and cpu:
            self._page_cpu(cpu)
        elif page == "memory" and mem:
            self._page_memory(mem)
        elif page == "disk" and disk:
            self._page_disk(disk)
        elif page == "network" and net:
            self._page_network(net)
        if page == "storage" or (slow and self._ticks % 10 == 1):
            self._page_storage()
        if page == "processes":
            self._sel_changed()

    def _page_cpu(self, cpu):
        load = si.loadavg()
        temps = si.temperatures()
        t = si.cpu_temperature(temps)
        freq = getattr(self, "_freq", 0)
        lo, hi = si.cpu_freq_limits()
        self.cpu_big.set_text("%d%%" % round(cpu["total"] * 100))
        procs, th = si.counts(self.procs.values())
        self.stats_cpu.set(util="%d%%" % round(cpu["total"] * 100), speed=si.fmt_hz(freq) if freq else "—", procs=str(procs), threads=str(th),
                           uptime=si.fmt_duration(si.uptime()), load="%.2f  %.2f  %.2f" % load,
                           temp=("%.0f °C" % t) if t is not None else "—", cores=str(self.ncpu))
        self.cpu_sub.set_text("%s  ·  user %d%%  system %d%%  waiting %d%%" % (self.cpu_name[0], round(cpu["user"] * 100), round(cpu["system"] * 100), round(cpu["iowait"] * 100)))

    def _set_composition(self):
        m = self.snap.get("mem") if hasattr(self, "snap") else None
        if not m:
            return
        t = max(1, m["total"])
        self.comp.set([(m["used"] / t, self.pal["mem"], 0.9, "In use"), (m["cache"] / t, self.pal["mem"], 0.38, "Cache"), (m["free"] / t, self.pal["mem"], 0.0, "Free")])

    def _page_memory(self, m):
        self.mem_big.set_text("%d%%" % round(m["used"] / max(1, m["total"]) * 100))
        self.mem_sub.set_text("%s of %s in use" % (si.fmt_bytes(m["used"]), si.fmt_bytes(m["total"])))
        self._set_composition()
        self.stats_mem.set(used=si.fmt_bytes(m["used"]), avail=si.fmt_bytes(m["available"]), cached=si.fmt_bytes(m["cached"]), buffers=si.fmt_bytes(m["buffers"]),
                           shared=si.fmt_bytes(m["shared"]), dirty=si.fmt_bytes(m["dirty"]), total=si.fmt_bytes(m["total"]),
                           swap=("%s of %s" % (si.fmt_bytes(m["swap_used"]), si.fmt_bytes(m["swap_total"]))) if m["swap_total"] else "no swap")

    def _page_disk(self, d):
        self.disk_big.set_text("%d%%" % round(d["busy"] * 100))
        devs = d["devices"]
        tr = sum(v["read_total"] for v in devs.values())
        tw = sum(v["write_total"] for v in devs.values())
        self.stats_disk.set(read=si.fmt_rate(d["read"]), write=si.fmt_rate(d["write"]), busy="%d%%" % round(d["busy"] * 100),
                            tread=si.fmt_bytes(tr), twrite=si.fmt_bytes(tw))
        names = sorted(devs)
        if names != self._disk_names:
            self._disk_names = names
            for ch in self.disk_list.get_children():
                self.disk_list.remove(ch)
            self._disk_rows = {}
            for n in names:
                row = Gtk.Box(spacing=12)
                row.get_style_context().add_class("fsrow")
                row.set_border_width(10)
                row.pack_start(Ico("drive", 18, scheme.ink(), 1.6), False, False, 0)
                row.pack_start(label(n, "h1"), True, True, 0)
                l = label("", None, 1.0)
                row.pack_end(l, False, False, 0)
                self._disk_rows[n] = l
                self.disk_list.pack_start(row, False, False, 0)
            self.disk_list.show_all()
            if not names:
                self.disk_list.pack_start(label("No physical drives found.", "muted"), False, False, 0)
                self.disk_list.show_all()
        for n, l in getattr(self, "_disk_rows", {}).items():
            v = devs.get(n)
            if v:
                l.set_text("Read %s    Write %s    Active %d%%" % (si.fmt_rate(v["read"]), si.fmt_rate(v["write"]), round(v["busy"] * 100)))

    def _iface_items(self):
        net = (self.snap or {}).get("net") if hasattr(self, "snap") else None
        items = [("check", "All networks", self._net_sel is None, lambda: self._select_iface(None))]
        for n, i in sorted((net or {}).get("ifaces", {}).items()):
            items.append(("check", "%s  (%s)" % (n, {"wifi": "Wi-Fi", "ethernet": "Ethernet", "virtual": "virtual"}[i["kind"]]), self._net_sel == n, lambda n=n: self._select_iface(n)))
        return items

    def _select_iface(self, name):
        self._net_sel = name
        self.iface_lbl.set_text(name or "All networks")
        self.g_net.clear()
        self._tick_ui(force=True)

    def _page_network(self, net):
        sel = net["ifaces"].get(self._net_sel) if self._net_sel else None
        if self._net_sel and sel is None:
            self._net_sel = None
            self.iface_lbl.set_text("All networks")
        ifs = net["ifaces"]
        real = [i for i in ifs.values() if i["kind"] != "virtual"] or list(ifs.values())
        if sel:
            rx, tx, trx, ttx = sel["rx"], sel["tx"], sel["rx_total"], sel["tx_total"]
            kind = {"wifi": "Wi-Fi", "ethernet": "Ethernet", "virtual": "Virtual"}[sel["kind"]]
            speed = ("%d Mbit/s" % sel["speed"]) if sel["speed"] else "—"
            state = "Connected" if sel["up"] else "Not connected"
            err = str(sel["rx_err"] + sel["tx_err"])
        else:
            rx, tx = net["rx"], net["tx"]
            trx, ttx = sum(i["rx_total"] for i in real), sum(i["tx_total"] for i in real)
            kind = ", ".join(sorted({{"wifi": "Wi-Fi", "ethernet": "Ethernet", "virtual": "Virtual"}[i["kind"]] for i in real})) or "—"
            speed = "—"
            state = "Connected" if any(i["up"] for i in real) else "Not connected"
            err = str(sum(i["rx_err"] + i["tx_err"] for i in real))
        self.net_big.set_text(si.fmt_rate(rx + tx))
        self.net_sub.set_text(self._net_sel or "All network adapters")
        self.stats_net.set(rx=si.fmt_bits(rx), tx=si.fmt_bits(tx), trx=si.fmt_bytes(trx), ttx=si.fmt_bytes(ttx), kind=kind, speed=speed, state=state, errors=err)
        sig = tuple(sorted(ifs))
        if sig != getattr(self, "_net_sig", None):
            self._net_sig = sig
            for ch in self.net_list.get_children():
                self.net_list.remove(ch)
            self._net_rows = {}
            for n in sig:
                row = Gtk.Box(spacing=12)
                row.get_style_context().add_class("fsrow")
                row.set_border_width(10)
                icon = {"wifi": "wifi", "ethernet": "network", "virtual": "cloud"}[ifs[n]["kind"]]
                row.pack_start(Ico(icon, 18, scheme.ink(), 1.6), False, False, 0)
                row.pack_start(label(n, "h1"), True, True, 0)
                l = label("", None, 1.0)
                row.pack_end(l, False, False, 0)
                self._net_rows[n] = l
                self.net_list.pack_start(row, False, False, 0)
            self.net_list.show_all()
        for n, l in getattr(self, "_net_rows", {}).items():
            i = ifs.get(n)
            if i:
                l.set_text("%s    ↓ %s    ↑ %s" % ("Connected" if i["up"] else "Down", si.fmt_rate(i["rx"]), si.fmt_rate(i["tx"])))

    def _page_storage(self):
        fs = self._guard("filesystems", si.filesystems) or []
        sig = tuple((f["mount"], f["device"]) for f in fs)
        if sig != self._fs_sig:
            self._fs_sig = sig
            for ch in self.fs_list.get_children():
                self.fs_list.remove(ch)
            self._fs_widgets = {}
            for f in fs:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                row.get_style_context().add_class("fsrow")
                row.set_border_width(12)
                top = Gtk.Box(spacing=10)
                top.pack_start(Ico("drive", 20, scheme.ink(), 1.5), False, False, 0)
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                col.pack_start(label(f["mount"], "h1"), False, False, 0)
                col.pack_start(label("%s  ·  %s" % (f["device"], f["type"]), "muted"), False, False, 0)
                top.pack_start(col, True, True, 0)
                b = Gtk.Button(label="Open")
                b.get_style_context().add_class("choicebtn")
                b.connect("clicked", lambda _b, m=f["mount"]: self._open_mount(m))
                top.pack_end(b, False, False, 0)
                row.pack_start(top, False, False, 0)
                bar = Gtk.ProgressBar()
                bar.get_style_context().add_class("usage")
                row.pack_start(bar, False, False, 0)
                text = label("", "muted")
                row.pack_start(text, False, False, 0)
                self.fs_list.pack_start(row, False, False, 0)
                self._fs_widgets[f["mount"]] = (bar, text)
            if not fs:
                self.fs_list.pack_start(label("No file systems found.", "muted"), False, False, 0)
            self.fs_list.show_all()
        worst = 0.0
        for f in fs:
            bar, text = self._fs_widgets.get(f["mount"], (None, None))
            if bar is None:
                continue
            frac = f["used"] / f["total"] if f["total"] else 0
            worst = max(worst, frac)
            bar.set_fraction(min(1.0, frac))
            ctx = bar.get_style_context()
            for cl in ("warn", "crit"):
                ctx.remove_class(cl)
            if frac >= 0.95:
                ctx.add_class("crit")
            elif frac >= 0.85:
                ctx.add_class("warn")
            text.set_text("%s used of %s  ·  %s free" % (si.fmt_bytes(f["used"]), si.fmt_bytes(f["total"]), si.fmt_bytes(f["free"])))
        root = next((f for f in fs if f["mount"] == "/"), fs[0] if fs else None)
        c = self.cards["storage"]
        if root:
            c.value_l.set_text("%d%% used" % round(root["used"] / root["total"] * 100))
            c.sub_l.set_text("%s · %d file system%s" % (si.fmt_bytes(root["total"], 0), len(fs), "" if len(fs) == 1 else "s"))
            self.sto_big.set_text("%d%%" % round(root["used"] / root["total"] * 100))

    def _open_mount(self, mount):
        try:
            from . import services
            services.fire(["sparkfiles", mount])
        except Exception as e:
            self.say("Could not open %s: %s" % (mount, e))

    # ---------------------------------------------------------------- notices, menus, keys
    def say(self, text, buttons=None, ms=6000):
        for c in self.notice_btns.get_children():
            self.notice_btns.remove(c)
        self.notice_lbl.set_text(text)
        for t, cb in buttons or []:
            b = Gtk.Button(label=t)
            b.get_style_context().add_class("choicebtn")
            b.connect("clicked", lambda _b, cb=cb: (self.hide_notice(), cb()))
            self.notice_btns.pack_start(b, False, False, 0)
        self.notice_box.set_no_show_all(False)
        self.notice_box.show_all()
        self.notice_box.set_no_show_all(True)
        if self._notice_src:
            GLib.source_remove(self._notice_src)
        self._notice_src = GLib.timeout_add(ms, self.hide_notice)

    def hide_notice(self, *_):
        if self._notice_src:
            GLib.source_remove(self._notice_src)
            self._notice_src = 0
        self.notice_box.hide()
        return False

    def _popup_below(self, btn, items, width=230):
        win = btn.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        GlassMenu(items, light=True, theme=self.th, min_width=width).popup_at(ox + a.x, oy + a.y + a.height + 4)

    def _popup_above(self, btn, items, width=230):
        win = btn.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        menu = GlassMenu(items, light=True, theme=self.th, min_width=width)
        menu.popup_at(ox + a.x, max(0, oy + a.y - 330))

    def _menu_items(self):
        o = self.opt

        def toggle(key, after=None):
            def f():
                self.opt[key] = not self.opt[key]
                if after:
                    after()
                self.save_options()
            return f

        def interval(v):
            def f():
                self.opt["interval"] = v
                self._start_timer()
                self.save_options()
            return f
        return [("head", "Update speed")] + [("check", n, o["interval"] == v, interval(v)) for n, v in INTERVALS] + [
            ("sep",), ("head", "Processes"),
            ("check", "CPU: 100% = one core", o["per_core"], toggle("per_core", lambda: self.tree.queue_draw())),
            ("check", "Show system (kernel) threads", o["kernel"], toggle("kernel", lambda: self.filter.refilter())),
            ("check", "Show command line column", o["cmdline"], toggle("cmdline", lambda: self.c_cmd.set_visible(self.opt["cmdline"]))),
            ("check", "Ask before ending a task", o["confirm"], toggle("confirm")),
            ("sep",), ("item", "Refresh now", lambda: self._tick())]

    def _key(self, w, ev):
        st = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(st & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(st & Gdk.ModifierType.SHIFT_MASK)
        in_entry = isinstance(self.get_focus(), Gtk.Entry)
        on_procs = self.stack.get_visible_child_name() == "processes"
        if ev.keyval == Gdk.KEY_Escape and on_procs and self.search.get_text():
            self.search.set_text("")
            self.tree.grab_focus()
            return True
        if ctrl and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.cards["processes"].set_active(True)
            self.search.grab_focus()
            return True
        if ctrl and Gdk.KEY_1 <= ev.keyval <= Gdk.KEY_6:
            self.cards[self.PAGES[ev.keyval - Gdk.KEY_1]].set_active(True)
            return True
        if ev.keyval == Gdk.KEY_F5:
            self._tick()
            return True
        if on_procs and not in_entry:
            if ev.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
                self.end_task(shift)
                return True
            if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self._selected() is not None:
                self.show_properties()
                return True
        return False

    def _closing(self, w, ev):
        try:
            self.save_options()
        except Exception as e:
            print("sparkmonitor: could not save settings:", e, file=sys.stderr)
        return False

    def save_options(self):
        col, order = self.model.get_sort_column_id()[1:] if self.model is not None and self.model.get_sort_column_id()[0] else (self.opt["sort_col"], Gtk.SortType.DESCENDING)
        self.opt["sort_col"], self.opt["sort_desc"] = int(col), order == Gtk.SortType.DESCENDING
        self.cfg = config.load(CFG)
        self.cfg["view"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.opt.items()}
        try:
            config.save(self.cfg, CFG)
        except OSError:
            pass


def _cmp(a, b):
    return (a > b) - (a < b)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return
    page = None
    if "--page" in argv and argv.index("--page") + 1 < len(argv):
        page = argv[argv.index("--page") + 1]
    appkit.run(SparkMonitor(page))


if __name__ == "__main__":
    main()
