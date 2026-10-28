"""glitterDE live shell: real widgets + real data over the glass renderer."""
import math
import hashlib
import os
import shutil
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ValueError, ImportError):
    Wnck = None

from . import automount, config, gfx, scheme, services
from . import settings_model as prefs
from . import icons as ic
from .menus import GlassConfirm, GlassMenu
from .widgets import popup_menu, Bar, Desktop, Ico, Ring, Spark, compositing, icon_button, install_css, label, search_overlay

EXTRA_CSS = b"""
.panel-bottom { border-top: 1px solid rgba(255,255,255,0.12); }
.darkpanel iconview.view { background: transparent; background-color: transparent; color: #ecebfa; font-size: 11px; }
.darkpanel iconview.view:selected, .darkpanel iconview.view:hover { background-color: rgba(255,255,255,0.14); color: #ffffff; border-radius: 12px; }
.darkpanel label, .darkpanel entry { color: #ecebfa; }
.darkpanel label.muted { color: rgba(236,235,250,0.74); }
.darkpanel entry { background-color: rgba(255,255,255,0.09); border-color: rgba(255,255,255,0.18); caret-color: #ffffff; }
.darkpanel entry:focus { background-color: rgba(255,255,255,0.15); }
.darkpanel row:hover { background-color: rgba(255,255,255,0.08); }
.darkpanel row:selected { background-color: rgba(150,140,255,0.32); }
.darkpanel flowboxchild:hover { background-color: rgba(255,255,255,0.09); }
.darkpanel flowboxchild:focus { background-color: rgba(255,255,255,0.14); }
.darkpanel scrollbar slider { background-color: rgba(255,255,255,0.36); }
.lightpanel iconview.view { background: transparent; background-color: transparent; color: #2a2d6e; font-size: 11px; }
.lightpanel iconview.view:selected, .lightpanel iconview.view:hover { background-color: rgba(120,130,255,0.28); color: #2a2d6e; border-radius: 12px; }
.deskicon.sel { background-color: rgba(255,255,255,0.22); border-radius: 12px; }
.cardclose { opacity: 0.35; }
.cardclose:hover { opacity: 1.0; }
.lightpanel label, .lightpanel entry { color: #2a2d6e; }
.lightpanel label.muted { color: rgba(42,45,110,0.78); }
.lightpanel entry { background-color: rgba(255,255,255,0.58); border-color: rgba(255,255,255,0.8); caret-color: #2a2d6e; }
.lightpanel entry:focus { background-color: rgba(255,255,255,0.75); }
.lightpanel row:hover { background-color: rgba(120,130,255,0.14); }
.lightpanel row:selected { background-color: rgba(130,140,255,0.34); }
.lightpanel flowboxchild:hover { background-color: rgba(120,130,255,0.18); }
.lightpanel flowboxchild:focus { background-color: rgba(120,130,255,0.26); }
.lightpanel scrollbar slider { background-color: rgba(42,45,110,0.35); }
entry.withicon { padding-left: 32px; }
.panel { border-bottom: 1px solid rgba(255,255,255,0.12); }
.hovcard label { color: #ffffff; }
.hovcard label.hovhead { font-size: 10px; font-weight: 700; letter-spacing: 1px; color: rgba(255,255,255,0.62); }
.hovcard label.hovsub { font-size: 11px; color: rgba(255,255,255,0.62); }
.hovrow { padding: 7px 8px 7px 12px; border-radius: 14px; border-left: 3px solid transparent; }
.hovrow:hover { background-color: rgba(255,255,255,0.20); }
.hovrow.act { background-color: rgba(255,255,255,0.12); border-left-color: #ff9bd8; }
.hovrow.mini label.hovtitle { color: rgba(255,255,255,0.6); }
.hovx { border-radius: 999px; min-width: 24px; min-height: 24px; }
.hovx:hover { background-color: rgba(255,92,134,0.9); }
.deskicon label { text-shadow: 0 1px 3px rgba(20,10,80,0.75); font-weight: 500; }
flowboxchild:hover { background-color: rgba(255,255,255,0.20); }
.catrow label { font-size: 12px; }
.lightpanel .lname { font-weight: 700; font-size: 14px; }
.l-avatar { background-color: rgba(120,130,255,0.55); border-radius: 999px; color: #ffffff; font-weight: 700; font-size: 15px; }
.lightpanel .lsect { font-weight: 700; font-size: 13px; padding-left: 6px; }
.l-sect button { border-radius: 999px; padding: 3px 14px; background-image: none; background-color: rgba(255,255,255,0.55); border: none; color: #2a2d6e; }
.l-sect button:hover { background-color: rgba(120,130,255,0.30); }
.l-tab { border-radius: 999px; padding: 6px 18px; background-image: none; background-color: transparent; border: none; color: #2a2d6e; }
.l-tab:hover { background-color: rgba(120,130,255,0.18); }
.l-tab.on { background-color: rgba(120,130,255,0.34); font-weight: 700; }
.l-foot { padding: 6px 8px 0 8px; border-top: 1px solid rgba(42,45,110,0.14); }
.l-head { padding: 4px 6px 8px 6px; }
.lay-launchpad entry, .lay-overview entry { border-radius: 999px; min-height: 36px; font-size: 15px; padding-left: 36px; }
.lay-launchpad iconview.view, .lay-overview iconview.view { font-size: 13px; }
.lay-start iconview.view { font-size: 11px; }
.lay-kickoff iconview.view, .lay-list iconview.view { border-radius: 8px; }
.badge { background-color: #f95cb8; border-radius: 8px; padding: 0 5px; font-size: 9px; font-weight: 700; }
.dim { opacity: 0.55; }
"""


def ago(ts):
    d = max(0, int(time.time() - ts))
    return "now" if d < 60 else "%dm" % (d // 60) if d < 3600 else "%dh" % (d // 3600) if d < 86400 else "%dd" % (d // 86400)


def greeting():
    h = time.localtime().tm_hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"


def user_first_name():
    chosen = config.load().get("user", {}).get("name")
    if chosen:
        return str(chosen).split()[0]
    n = GLib.get_real_name()
    return (n if n and n != "Unknown" else GLib.get_user_name()).split()[0].capitalize()


def round_shape(win, r):
    """Round a window's corners with the X Shape extension (no compositor needed)."""
    import math
    import cairo
    a = win.get_allocation()
    w, h = a.width, a.height
    if w < 2 * r or h < 2 * r or win.get_window() is None:
        return
    rects = [cairo.RectangleInt(0, r, w, h - 2 * r)]
    for i in range(r):
        inset = r - int(math.sqrt(max(0, r * r - (r - i - 0.5) ** 2)) + 0.5)
        rects.append(cairo.RectangleInt(inset, i, w - 2 * inset, 1))
        rects.append(cairo.RectangleInt(inset, h - 1 - i, w - 2 * inset, 1))
    reg = cairo.Region(rects)
    win.shape_combine_region(reg)


MAX_WORKSPACES = 8


class Popup(Gtk.Window):
    """A small top-level glass surface (launcher, toasts): its own window, so the WM stacks it above apps."""

    def __init__(self, shell, material, radius, hint, wmclass="glitterde-popup"):
        super().__init__()
        self.oscale = 1.0
        self.shell, self.material, self.base = shell, material, radius
        self.set_decorated(False); self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        self.set_type_hint(hint)
        self.set_wmclass(wmclass, wmclass)
        self.comp = compositing()
        if self.comp:
            self.set_visual(Gdk.Screen.get_default().get_rgba_visual())
        self.connect("draw", self._draw)
        if not self.comp:
            self.connect("size-allocate", lambda w, a: round_shape(w, self.shell.theme.rad(self.base)))

    def _draw(self, w, cr):
        if self.comp:
            a = self.get_allocation()
            r = self.shell.theme.rad(self.base)
            gfx.comp_glass(cr, a.width, a.height, r, self.shell.theme.material(self.material), self.oscale)
            gfx.stroke_rrect(cr, 0, 0, a.width, a.height, r, (1, 1, 1, 0.32), 1.0)
            return False
        gw, g = self.get_window(), self.shell.desk.glass
        if gw is None or g is None:
            return False
        r = gw.get_origin(); ox, oy = r[-2], r[-1]
        a = self.get_allocation()
        cr.save(); cr.translate(-ox, -oy)
        g.panel(cr, ox, oy, a.width, a.height, 0, self.material, shadow=False, rim=False)
        cr.restore()
        gfx.stroke_rrect(cr, 0, 0, a.width, a.height, self.shell.theme.rad(self.base), (1, 1, 1, 0.32), 1.0)
        return False


class WindowHover(Popup):
    """Card listing the windows of a dock item (or a workspace) when the pointer rests on it. Click a row to bring that window forward."""

    def __init__(self, shell):
        super().__init__(shell, "dock", 16, Gdk.WindowTypeHint.TOOLTIP)
        self.set_accept_focus(False); self.set_focus_on_map(False)
        self.get_style_context().add_class("hovcard")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.box, "set_margin_" + m)(10)
        self.box.set_spacing(3)
        self.add(self.box)
        self._t = None
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", lambda *_: self.keep())
        self.connect("leave-notify-event", self._on_leave)

    def _on_leave(self, w, ev):
        if ev.detail != Gdk.NotifyType.INFERIOR:             # moving onto a row inside the card is not leaving it
            self.leave(350)
        return False

    def keep(self):
        if self._t:
            GLib.source_remove(self._t); self._t = None

    def leave(self, ms=260):
        self.keep()
        self._t = GLib.timeout_add(ms, lambda: (self.hide_now(), False)[1])

    def hide_now(self):
        self.keep()
        self.hide()

    def _row(self, w):
        ev = Gtk.EventBox(); ev.set_visible_window(True)
        ctx = ev.get_style_context(); ctx.add_class("hovrow")
        if w.is_active():
            ctx.add_class("act")
        if w.is_minimized():
            ctx.add_class("mini")
        h = Gtk.Box(spacing=12)
        pb = w.get_icon() or w.get_mini_icon()
        if pb is not None:
            if pb.get_width() != 28:
                pb = pb.scale_simple(28, 28, GdkPixbuf.InterpType.BILINEAR)
            im = Gtk.Image.new_from_pixbuf(pb); im.set_valign(Gtk.Align.CENTER); h.pack_start(im, False, False, 0)
        name = w.get_name() or w.get_class_group_name() or "Window"
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); col.set_valign(Gtk.Align.CENTER)
        t = label(name if len(name) < 34 else name[:32] + "…", "hovtitle", ellipsize=False); t.set_xalign(0)
        col.pack_start(t, False, False, 0)
        sub = "Minimised" if w.is_minimized() else ""
        try:
            ws, act = w.get_workspace(), self.shell.wnck.get_active_workspace() if self.shell.wnck else None
            if not sub and ws is not None and act is not None and ws != act and not w.is_pinned():
                sub = "Workspace %d" % (ws.get_number() + 1)
        except Exception:
            pass
        if sub:
            sl = label(sub, "hovsub", ellipsize=False); sl.set_xalign(0); col.pack_start(sl, False, False, 0)
        col.set_size_request(190, -1)
        h.pack_start(col, True, True, 0)
        x = Gtk.EventBox(); x.set_visible_window(True); x.get_style_context().add_class("hovx"); x.set_valign(Gtk.Align.CENTER)
        x.add(Ico("close", 10, (1, 1, 1, 0.8), 1.7)); x.set_tooltip_text("Close window")
        x.connect("button-release-event", lambda _w, e, w=w: (w.close(Gtk.get_current_event_time()), self.hide_now(), True)[2])
        h.pack_end(x, False, False, 0)
        ev.add(h)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        ev.connect("button-release-event", lambda _w, e, w=w: (self.pick(w), True)[1] if e.button == 1 else False)
        return ev

    def pick(self, w):
        ts = Gtk.get_current_event_time()
        self.hide_now()
        sh = self.shell
        ws = w.get_workspace()
        if ws is not None and sh.wnck and ws != sh.wnck.get_active_workspace():
            ws.activate(ts)
        if w.is_minimized():
            w.unminimize(ts)
        w.activate(ts)

    def show_for(self, anchor, wins, below=False, title=""):
        self.keep()
        for ch in self.box.get_children():
            self.box.remove(ch); ch.destroy()
        if not wins:
            self.hide(); return
        if title:
            hd = label(title.upper(), "hovhead", ellipsize=False); hd.set_xalign(0); hd.set_margin_start(12); hd.set_margin_top(2); hd.set_margin_bottom(4)
            self.box.pack_start(hd, False, False, 0)
        for w in wins:
            self.box.pack_start(self._row(w), False, False, 0)
        self.show_all()
        self.resize(1, 1)       # a GTK window never shrinks by itself: without this a short card kept the height of the previous, taller one and hung over the dock
        cw, ch_ = self.get_preferred_size()[1].width, self.get_preferred_size()[1].height
        gw = anchor.get_window()
        if gw is None:
            return
        _, ox, oy = gw.get_origin(); a = anchor.get_allocation()
        ax, ay = (ox + a.x, oy + a.y) if not anchor.get_has_window() else (ox, oy)
        pos = prefs.get("dock.position")
        mx, my, mw, mh = self.shell.mon
        low = ay + a.height // 2 > my + mh // 2                  # anchors in the lower half of the screen (workspace pill, bottom dock) never hang below
        if (below or self.shell._dock_style != "dock") and not low:   # panel items (and a dock folded into the panel): the card hangs below
            x, y = ax + a.width // 2 - cw // 2, ay + a.height + 6
        elif below or self.shell._dock_style != "dock":
            x, y = ax + a.width // 2 - cw // 2, ay - ch_ - 10
        elif pos == "left":
            x, y = ax + a.width + 6, ay + a.height // 2 - ch_ // 2
        elif pos == "right":
            x, y = ax - cw - 6, ay + a.height // 2 - ch_ // 2
        else:
            x, y = ax + a.width // 2 - cw // 2, ay - ch_ - 10
        # Never overlap the dock itself: place the card against the dock WINDOW's edge (its margin and shadow are bigger than the
        # item), not just against the hovered icon.
        dw = getattr(self.shell, "dock_win", None)
        if not below and self.shell._dock_style == "dock" and dw is not None and dw.get_visible() and dw.get_window() is not None:
            _, dx, dy = dw.get_window().get_origin(); da = dw.get_allocation()
            if pos == "left":
                x = max(x, dx + da.width + 8)
            elif pos == "right":
                x = min(x, dx - cw - 8)
            else:
                y = min(y, dy - ch_ - 8)
        x, y = max(mx + 6, min(x, mx + mw - cw - 6)), max(my + 6, min(y, my + mh - ch_ - 6))
        # Never cover the dock: clamping to the screen used to push tall cards (or ones hung below a bottom anchor) back over it.
        dw = getattr(self.shell, "dock_win", None)
        dgw = dw.get_window() if dw is not None and dw.get_visible() else None
        if dgw is not None:
            _, dx, dy = dgw.get_origin(); da = dw.get_allocation()
            if x < dx + da.width and dx < x + cw and y < dy + da.height and dy < y + ch_:       # overlaps the dock window
                if da.width >= da.height:                                                      # horizontal dock: sit above it (or below if at the top)
                    y = dy - ch_ - 8 if dy > my + mh // 2 else dy + da.height + 8
                elif dx < mx + mw // 2:                                                         # dock on the left: to its right
                    x = dx + da.width + 8
                else:                                                                           # dock on the right: to its left
                    x = dx - cw - 8
                x, y = max(mx + 6, min(x, mx + mw - cw - 6)), max(my + 6, y)
        self.move(x, y)
        if self.get_window() is not None:
            self.get_window().raise_()                    # above everything else we own, but placed so it no longer covers the dock


class DemoMedia:
    status, title, artist, length, art, name = "Playing", "Better Together", "Starset", 252_000_000, None, "demo"

    def position_us(self):
        return 154_000_000

    trackid, player, can_seek = "/demo", "demo", False

    def seek_to(self, f):
        pass

    def control(self, m):
        pass


class LiveShell:
    def __init__(self, args, theme):
        self.args, self.theme = args, theme
        _sh = config.load().get("shell", {})            # decide NOW: later startup code sets "welcomed"
        self._first_run = bool(getattr(args, "welcome", False)) or not (_sh.get("setup_done") or _sh.get("welcomed"))
        self.demo = bool(args.demo)
        self.nested = bool(os.environ.get("GLITTERDE_NESTED"))
        install_css()
        p = Gtk.CssProvider(); p.load_from_data(EXTRA_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10 + 1)

        self.win = Gtk.Window(title="glitterDE")
        self.win.set_wmclass("glitterde-shell", "glitterde-shell")
        self.win.set_decorated(False)
        self.win.set_app_paintable(True)
        self.desk = Desktop(theme)
        self.win.add(self.desk)
        self.W = self.H = 0
        self.mon = (0, 0, 0, 0)                 # primary monitor (x, y, w, h) inside the desktop window
        self.notifs = []
        self.dnd = False
        self.toast_src = None

        self.PH = prefs.get("panel.height")
        self.dock_px, self.dock_ind = prefs.get("dock.icon_size"), prefs.get("dock.indicators")
        self.top = self.PH
        self._load_widget_state(initial=True)
        self.stats = services.Stats()
        self.audio = services.Audio()
        self.light = services.Backlight()
        self.apps = services.all_apps()
        self.favs = services.default_favorites(self.apps, self._configured_favorites())
        self.wnck = self._init_wnck()
        self.use_popups = "X11" in type(Gdk.Display.get_default()).__name__
        self._opened_at = 0

        self._build_panel()
        self._build_clock_card()
        self.col_cards = [self._card_system(), self._card_network(), self._card_bluetooth(),
                          self._card_phone(), self._card_media(), self._card_quick()]
        self._build_notifications()
        self._register_widgets()
        self._build_desktop_icons()
        self._build_toast()
        GLib.idle_add(lambda: (services.start_polkit_agent(), False)[1])     # so logind can ask for authorisation when it needs to
        self._init_tray()
        self._build_workspaces()
        self._build_dock()
        self._build_launcher()          # last: drawn above everything else

        self.notif_srv = services.NotificationServer(self.on_notify, self.on_notify_close)
        self.automounter = automount.AutoMounter(self._on_drive_event, lambda: prefs.get("drives.automount"))
        GLib.timeout_add(2500, lambda: (self.refresh_notifs(), False)[1])
        try:
            self.media = DemoMedia() if self.demo else services.Media(self.on_media)
        except GLib.Error:
            self.media = DemoMedia(); self.media.status = "Stopped"; self.media.title = ""
        if self.demo:
            self._demo_data()
        self.tick_stats(); GLib.timeout_add_seconds(3, self.tick_stats)
        self.tick_clock(); GLib.timeout_add_seconds(8, self.tick_slow)
        self._wire_window()
        self.desk.connect("size-allocate", self._on_alloc)
        self.win.show_all()
        self.launcher_wrap.hide(); self.toast_wrap.hide()
        if self.tray:
            self.tray.hide()
        self.apply_prefs()
        self.rebuild_icons()
        self.on_media()
        self.win.set_focus(None)
        GLib.idle_add(lambda: setattr(self, '_ready', True))
        self.apply_widgets()
        self.relayout(force=True)
        self._first_run_hint()

    def _first_run_hint(self):
        if self.demo or self._first_run or config.load().get("shell", {}).get("welcomed"):
            return
        config.set("shell", "welcomed", True)
        GLib.timeout_add(1200, lambda: (self.show_toast("Welcome to glitterDE", "A blank slate: right-click the desktop to add widgets, or press Super to open apps.", None, 9000), False)[1])

    def _panel_search(self, e):
        t = e.get_text()
        if t and self._ready:                        # typing in the panel hands over to the launcher with the text
            e.set_text("")
            self.open_launcher(t)

    def apply_cursor(self):
        c = config.load().get("cursor", {})
        st = Gtk.Settings.get_default()
        theme = config.cursor_theme()
        if theme:
            st.set_property("gtk-cursor-theme-name", theme)
            os.environ["XCURSOR_THEME"] = theme                      # apps launched from here inherit it
        if c.get("size"):
            st.set_property("gtk-cursor-theme-size", int(c["size"]))
            os.environ["XCURSOR_SIZE"] = str(int(c["size"]))

    def _maybe_welcome(self):
        """First run (no saved choices yet) or --welcome: start the full-screen welcome flow, once."""
        if getattr(self, "_welcome_started", False) or os.environ.get("GLITTERDE_NO_WELCOME"):
            return False
        if self._first_run:
            self._welcome_started = True
            services.fire(["glitterde-welcome"])
        return False

    def _rebuild_launcher(self):
        """Colour scheme changed: the launcher's material, class and icon ink are fixed at build time, so build it again."""
        try:
            self.close_launcher()
        except Exception:
            pass
        old = getattr(self, "launcher_wrap", None)
        if old is not None:
            if self.use_popups:
                old.destroy()
            else:
                self.desk.remove(old)
        self._build_launcher()

    @staticmethod
    def _launcher_icon_name():
        """Icon of the apps-menu button: 'sparkle_logo' (glitterDE mark) or 'gtk:<icon-theme-name>'."""
        v = str(prefs.get("launcher.button_icon") or "sparkle_logo")
        return v if v == "sparkle_logo" or v.startswith("gtk:") else "gtk:" + v

    def apply_prefs(self):
        if getattr(self, "logo_btn", None) is not None:
            want = self._launcher_icon_name()
            if self.logo_btn.ico.name != want:
                self.logo_btn.ico.set_icon(want)
        if scheme.refresh() and hasattr(self, "launcher_wrap"):
            self._rebuild_launcher()
        scheme.apply_system()
        self.apply_cursor()
        if getattr(self, "greet_lbl", None):
            self.greet_lbl.set_text("%s, %s" % (greeting(), user_first_name()))     # the welcome flow can change the name
        self.PH = prefs.get("panel.height")
        self.dock_px, self.dock_ind = self._dock_icon_px(), prefs.get("dock.indicators")
        self._apply_dock_style()
        self.greet_box.set_visible(prefs.get("panel.show_greeting"))
        if getattr(self, "ws_box", None) is not None:
            want = bool(prefs.get("desktop.show_workspaces"))
            if self.ws_box.get_visible() != want:
                self.ws_box.set_visible(want)
                self.relayout()
        self.search_wrap.set_visible(prefs.get("panel.show_search"))
        for k in ("wifi", "bluetooth", "volume", "brightness"):
            show = prefs.get("panel.tray_" + k)
            if k == "brightness":                     # nothing to control on a desktop PC without backlight / night-light tool
                show = show and (self.light.available or shutil.which("gammastep") or shutil.which("redshift"))
            if k == "bluetooth":
                show = show and (self.bt_present or self.demo)
            self.tray_btns[k].set_visible(bool(show))
        self.tick_clock_once()
        self.tick_slow()

    def _dock_icon_px(self):
        px = prefs.get("dock.icon_size")
        return px if prefs.get("dock.style") == "dock" else max(16, min(px, self.PH - 14))     # icons must fit the panel

    def _apply_dock_style(self):
        """Move the application strip between the floating dock window and the panel (right side or exact centre)."""
        style = prefs.get("dock.style")
        if style == self._dock_style or not hasattr(self, "dock"):
            return
        dock, sw, entry = self.dock, self.search_wrap, self.panel_entry
        par = dock.get_parent()
        if par is not None:
            par.remove(dock)
        self.desk.regions = [r for r in self.desk.regions if r.widget is not dock]
        # the search field normally owns the panel centre; with centred apps it sits next to the logo instead
        if style == "panel_center" and sw.get_parent() is self.panel:
            self.panel.remove(sw); self._panel_left.pack_start(sw, False, False, 6); entry.set_width_chars(22)
        elif style != "panel_center" and sw.get_parent() is self._panel_left:
            self._panel_left.remove(sw); entry.set_width_chars(34); self.panel.set_center_widget(sw)
        dock.set_orientation(Gtk.Orientation.HORIZONTAL)
        if style == "dock":
            for m, v in (("start", 14), ("end", 14), ("top", 8), ("bottom", 6)):
                getattr(dock, "set_margin_" + m)(v)
            dock.set_valign(Gtk.Align.FILL)
            if self.use_popups:
                self.dock_win.add(dock)
            else:
                self.desk.put(dock, 0, 0); self.desk.add_glass(dock, "dock", 26, alpha=0.34)
        else:
            for m, v in (("start", 4), ("end", 4), ("top", 0), ("bottom", 0)):
                getattr(dock, "set_margin_" + m)(v)
            dock.set_valign(Gtk.Align.CENTER)
            if self.use_popups:
                self.dock_win.hide()
            if style == "panel_center":
                self.panel.set_center_widget(dock)
            elif style == "panel_left":
                self._panel_left.pack_start(dock, False, False, 8); self._panel_left.reorder_child(dock, 1)    # right after the logo
            else:
                self._panel_right.pack_start(dock, False, False, 8); self._panel_right.reorder_child(dock, 0)
        self._dock_style = style
        dock.show_all()
        self._dock_key = None
        self._dock_sig_cur = None
        self.refresh_dock(force=True)
        self.relayout()

    # ------------------------------------------------------------ config
    def _configured_favorites(self):
        home = os.environ.get("GLITTERDE_CONFIG_HOME") or os.path.join(GLib.get_user_config_dir(), "glitterde")
        f = os.path.join(home, "panel.toml")
        if os.path.exists(f):
            from .tokens import _load
            try:
                return _load(f).get("dock", {}).get("favorites")
            except Exception as e:
                print("glitterde: bad panel.toml:", e, file=sys.stderr)
        return None

    def _init_wnck(self):
        if Wnck is None or "X11" not in type(Gdk.Display.get_default()).__name__:
            return None
        s = Wnck.Screen.get_default()
        s.force_update()
        return s

    # ------------------------------------------------------------- panel
    def _build_panel(self):
        self.panel = Gtk.Box(spacing=8)
        self.panel.get_style_context().add_class("panel")
        logo = icon_button(self._launcher_icon_name(), 22, "Open launcher", lambda: self.toggle_launcher(), pad=7)
        self.logo_btn = logo
        left = Gtk.Box(spacing=6)
        self._panel_left = left
        left.set_margin_start(8)
        left.pack_start(logo, False, False, 0)
        self.greet_box = Gtk.Box(spacing=6)
        self.greet_lbl = label("%s, %s" % (greeting(), user_first_name()), "title")
        self.greet_box.pack_start(self.greet_lbl, False, False, 0)
        left.pack_start(self.greet_box, False, False, 0)
        self.panel.pack_start(left, False, False, 0)

        self.panel_entry = Gtk.Entry()
        self.panel_entry.set_placeholder_text("Type to search...")
        self.panel_entry.set_width_chars(34)
        self.panel_entry.get_style_context().add_class("withicon")
        self._ready = False
        self.panel_entry.connect("focus-in-event", lambda *_: (self.open_launcher() if self._ready else None, False)[1])
        self.panel_entry.connect("changed", self._panel_search)
        self.panel_entry.connect("activate", lambda e: self.open_launcher(e.get_text() or None, enter=True))
        c = Gtk.Box(); c.set_valign(Gtk.Align.CENTER); c.pack_start(self._with_search_icon(self.panel_entry), True, True, 0)
        self.search_wrap = c
        self.panel.set_center_widget(c)

        right = Gtk.Box(spacing=0)
        self._panel_right = right
        right.set_margin_end(10)
        self.bell = icon_button("bell", 17, "Notifications", lambda: self.toggle_notifs())
        self.bell_badge = label("", "badge"); self.bell_badge.set_valign(Gtk.Align.START); self.bell_badge.set_no_show_all(True)
        bellbox = Gtk.Box(); bellbox.pack_start(self.bell, False, False, 0)
        right.pack_start(bellbox, False, False, 0)
        right.pack_start(self.bell_badge, False, False, 2)
        self.tray_btns = {}
        for key, ico, size, tip in (("bluetooth", "bluetooth", 16, "Bluetooth"), ("wifi", "wifi", 17, "Network"),
                                    ("volume", "volume", 17, "Audio output"), ("brightness", "brightness", 17, "Brightness")):
            b = icon_button(ico, size, tip, None, pad=7)
            b.connect("clicked", lambda w, k=key: self.show_tray(k, w))
            self.tray_btns[key] = b
            right.pack_start(b, False, False, 0)
        self.bt_ico, self.wifi_ico = self.tray_btns["bluetooth"].ico, self.tray_btns["wifi"].ico
        self.pwr_btn = icon_button("power", 16, "Log out, restart or power off", None, pad=7)    # always visible, also on desktops without a battery
        self.pwr_btn.connect("clicked", lambda w: self.power_menu(w))
        right.pack_start(self.pwr_btn, False, False, 0)
        self.bat_btn = Gtk.Button(); self.bat_btn.set_relief(Gtk.ReliefStyle.NONE)
        bb = Gtk.Box(spacing=4); bb.set_margin_start(6); bb.set_margin_end(6)
        self.bat_ico = Ico("battery", 22, (1, 1, 1, 0.95)); self.bat_lbl = label("", "title")
        bb.pack_start(self.bat_ico, False, False, 0); bb.pack_start(self.bat_lbl, False, False, 0)
        self.bat_btn.add(bb); self.bat_btn.set_tooltip_text("Power")
        self.bat_btn.connect("clicked", lambda w: self.show_tray("power", w))
        right.pack_start(self.bat_btn, False, False, 0)
        self.clock_btn = Gtk.Button(); self.clock_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.clock_lbl = label("", "title"); self.clock_lbl.set_margin_start(8); self.clock_lbl.set_margin_end(8)
        self.clock_btn.add(self.clock_lbl); self.clock_btn.set_tooltip_text("Calendar")
        self.clock_btn.connect("clicked", lambda w: self.show_tray("clock", w))
        right.pack_start(self.clock_btn, False, False, 6)
        self.panel.pack_end(right, False, False, 0)
        self.desk.put(self.panel, 0, 0)
        self.desk.add_glass(self.panel, "panel", 0, shadow=False, rim=False)

    # ----------------------------------------------- quick settings popups (spec HIG s.23)
    def _init_tray(self):
        self.tray_kind, self._tray_opened = None, 0
        self.tray = None
        if not self.use_popups:
            return
        self.tray = Popup(self, "dock", 16, Gdk.WindowTypeHint.DROPDOWN_MENU)
        self.tray_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.tray_box.set_size_request(300, -1)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.tray_box, "set_margin_" + m)(14)
        self.tray.add(self.tray_box)
        self.tray.connect("focus-out-event", lambda *_: (GLib.idle_add(self._tray_focus_out), False)[1])
        self.tray.connect("key-press-event", lambda w, ev: (self.close_tray(), True)[1] if ev.keyval == Gdk.KEY_Escape else False)

    def _tray_focus_out(self):
        if self.tray.get_visible() and time.time() - self._tray_opened > 0.5 and not self.tray.is_active():
            self.close_tray(by_focus_out=True)
        return False

    def close_tray(self, by_focus_out=False):
        if self.tray:
            if by_focus_out and self.tray.get_visible():
                self._tray_closed = (self.tray_kind, time.time())     # remember WHAT the click-away closed, see show_tray
            self.tray.hide()
        self.tray_kind = None

    def show_tray(self, kind, anchor):
        if self.tray is None:
            self.show_toast("Quick settings", "The panel popups need an X11 session for now.")
            return
        if self.tray.get_visible() and self.tray_kind == kind:
            self.close_tray(); return
        # Pressing the panel button moves focus away from the popup, which closes it BEFORE this click handler runs. Without this
        # check the second click on the same button found the popup closed and opened it again.
        ck, ct = getattr(self, "_tray_closed", (None, 0))
        if ck == kind and time.time() - ct < 0.45:
            self._tray_closed = (None, 0); return
        if self.launcher_visible:
            self.close_launcher()
        for ch in self.tray_box.get_children():
            self.tray_box.remove(ch)
        self.tray_kind = kind
        getattr(self, "_tray_" + kind)(self.tray_box)
        self.tray_box.show_all()
        pos = anchor.translate_coordinates(self.win, 0, 0) or (self.W - 340, 0)
        mx, my, mw, mh = self.mon
        x = int(max(mx + 8, min(mx + mw - 328 - 8, pos[0] + anchor.get_allocated_width() / 2 - 164)))
        self.tray.resize(1, 1)
        top, bot = self._inset()
        th = self.tray_box.get_preferred_height()[1] + 4
        self.tray.move(x, my + (top + 2 if bot == 0 else mh - bot - th - 2))
        self._tray_opened = time.time()
        self.tray.show_all()

    def _tray_head(self, box, icon, title):
        h = Gtk.Box(spacing=8)
        h.pack_start(Ico(icon, 16, (1, 1, 1, 0.95), 1.5), False, False, 0)
        h.pack_start(label(title, "big"), False, False, 0)
        box.pack_start(h, False, False, 2)

    def _tray_switch_row(self, box, text, cb):
        r = Gtk.Box(spacing=8); r.pack_start(label(text), True, True, 0)
        sw = Gtk.Switch(); sw.set_valign(Gtk.Align.CENTER)
        state = {"init": True}
        sw.connect("notify::active", lambda s_, _p: None if state["init"] else cb(s_.get_active()))
        r.pack_end(sw, False, False, 0); box.pack_start(r, False, False, 2)
        sw.set_init = lambda v: (sw.set_active(bool(v)), state.update(init=False))
        return sw

    def _tray_slider(self, box, value, cb, icon):
        r = Gtk.Box(spacing=10); r.pack_start(Ico(icon, 15, (1, 1, 1, 0.9), 1.5), False, False, 0)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); sc.set_draw_value(False); sc.set_hexpand(True)
        sc.set_value(value * 100)
        st = {"t": None}

        def ch(w):
            if st["t"]:
                GLib.source_remove(st["t"])
            v = w.get_value() / 100.0
            st["t"] = GLib.timeout_add(80, lambda: (cb(v), st.update(t=None), False)[2])
        sc.connect("value-changed", ch)
        r.pack_start(sc, True, True, 0); box.pack_start(r, False, False, 4)
        return sc

    def _tray_btn(self, box, text, cb, ok=True):
        b = Gtk.Button(label=text); b.get_style_context().add_class("clear"); b.set_sensitive(ok)
        b.connect("clicked", lambda *_: cb()); box.pack_start(b, False, False, 2)
        return b

    # -- network
    def _tray_wifi(self, box):
        self._tray_head(box, "wifi", "Network")
        if not shutil.which("nmcli"):
            for n, kind, up, speed in services.interfaces():
                r = Gtk.Box(spacing=8); r.pack_start(Ico("wifi" if kind == "wifi" else "network", 15, (1, 1, 1, 0.9 if up else 0.4), 1.5), False, False, 0)
                r.pack_start(label("%s - %s" % (n, "connected" if up else "not connected")), False, False, 0); box.pack_start(r, False, False, 2)
            box.pack_start(self._empty("Install NetworkManager (nmcli) to scan and connect to Wi-Fi from here."), False, False, 4)
            return
        sw = self._tray_switch_row(box, "Wi-Fi", lambda v: (services.fire(["nmcli", "radio", "wifi", "on" if v else "off"]), GLib.timeout_add(1500, self._tray_refresh_wifi)))
        services.run_async(["nmcli", "radio", "wifi"], lambda out: sw.set_init("enabled" in (out or "")))
        self.net_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.pack_start(self.net_list, False, False, 0)
        if not getattr(self, "_net_busy", None):
            self._net_status = {}
        self._net_rows = []
        self._tray_refresh_wifi()
        self._tray_btn(box, "Network settings…", lambda: services.fire(["nm-connection-editor"]), bool(shutil.which("nm-connection-editor")))

    def _tray_refresh_wifi(self):
        if self.tray_kind != "wifi":
            return False

        def fill(out):
            if self.tray_kind != "wifi":
                return
            seen, rows = set(), []
            for ln in (out or "").splitlines():
                f = [x.replace("\x00", ":") for x in ln.replace("\\:", "\x00").split(":")]
                if len(f) >= 4 and f[1] and f[1] not in seen:
                    seen.add(f[1]); rows.append((f[0] == "*", f[1], int(f[2] or 0), f[3]))
            rows.sort(key=lambda r: (not r[0], -r[2]))
            self._net_rows = rows[:8]
            self._render_wifi()
        services.run_async(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], fill)
        return False

    def _status_widget(self, kind, text):
        """Right-hand side of a network / device row: spinner while working, then the outcome."""
        w = Gtk.Box(spacing=6)
        if kind == "connecting":
            sp = Gtk.Spinner(); sp.start(); w.pack_start(sp, False, False, 0)
        l = label(text, "muted", ellipsize=False)
        l.set_line_wrap(True); l.set_max_width_chars(34); l.set_xalign(0)       # a long reason wraps instead of widening the popup
        w.pack_start(l, False, False, 0)
        return w

    def _render_wifi(self):
        """Draw the network list from the last scan plus the connection status, without scanning again."""
        if self.tray_kind != "wifi":
            return
        for ch in self.net_list.get_children():
            self.net_list.remove(ch)
        status, busy = getattr(self, "_net_status", {}), getattr(self, "_net_busy", None)
        for inuse, ssid, sig, sec in self._net_rows:
            kind, text = status.get(ssid, (None, ""))
            holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE)
            r = Gtk.Box(spacing=8); r.pack_start(Ico("wifi", 14, (1, 1, 1, 0.5 + sig / 200.0), 1.5), False, False, 2)
            r.pack_start(label(ssid + ("   (connected)" if inuse and not kind else "")), True, True, 0)
            if kind:
                r.pack_end(self._status_widget(kind, text), False, False, 2)
            elif sec:
                r.pack_end(Ico("pin", 11, (1, 1, 1, 0.5), 1.4), False, False, 2)
            b.add(r)
            b.connect("clicked", lambda _b, s_=ssid, sc=bool(sec): self._wifi_connect(s_, sc))
            b.set_sensitive(not busy)
            holder.pack_start(b, False, False, 0)
            if kind == "password" and not busy:                       # inline password entry: the popup stays open and shows progress
                pr = Gtk.Box(spacing=6); pr.set_margin_start(30); pr.set_margin_end(6); pr.set_margin_bottom(4)
                e = Gtk.Entry(); e.set_visibility(False); e.set_placeholder_text("Password"); e.set_width_chars(16)
                j = Gtk.Button(label="Join"); j.get_style_context().add_class("clear")
                go = lambda *_a, s_=ssid, e_=e: self._wifi_connect(s_, True, e_.get_text())
                e.connect("activate", go); j.connect("clicked", go)
                pr.pack_start(e, True, True, 0); pr.pack_start(j, False, False, 0)
                holder.pack_start(pr, False, False, 0)
                GLib.idle_add(lambda e_=e: (e_.grab_focus(), False)[1])
            self.net_list.pack_start(holder, False, False, 0)
        if not self._net_rows:
            self.net_list.pack_start(self._empty("No networks found."), False, False, 2)
        self.net_list.show_all()

    def _wifi_connect(self, ssid, secured, password=None):
        if getattr(self, "_net_busy", None):
            return
        status = self.__dict__.setdefault("_net_status", {})
        status.clear(); status[ssid] = ("connecting", "Connecting…")
        self._net_busy = ssid
        self._render_wifi()
        argv = ["nmcli", "-w", "20", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])

        def done(ok, out, err):
            self._net_busy = None
            status.clear()
            if ok:
                status[ssid] = ("ok", "Connected")
                self.show_toast("Wi-Fi", "Connected to " + ssid)
                self.refresh_network()
            else:
                kind, text = services.net_error(err + "\n" + out)
                if kind == "password" and not secured:
                    kind = "failed"
                if kind == "password":
                    text = "Wrong password" if password else "Password needed"       # short: the row also has to show the name
                status[ssid] = (kind, text)
                if kind != "password":
                    self.show_toast("Wi-Fi", "Could not connect to %s: %s" % (ssid, text))
            if self.tray_kind == "wifi":
                self._tray_refresh_wifi()
        services.run_async_err(argv, done)

    # -- bluetooth
    def _tray_bluetooth(self, box):
        self._tray_head(box, "bluetooth", "Bluetooth")
        if not (shutil.which("bluetoothctl") and self.bt_present):
            box.pack_start(self._empty("No Bluetooth adapter found. Plug one in and it will appear here."), False, False, 4)
            return
        sw = self._tray_switch_row(box, "Bluetooth", lambda v: (services.fire(["bluetoothctl", "power", "on" if v else "off"]), GLib.timeout_add(1200, self._tray_refresh_bt)))
        services.run_async(["bluetoothctl", "show"], lambda out: sw.set_init("Powered: yes" in (out or "")))
        self.bt_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.pack_start(self.bt_list, False, False, 0)
        if not getattr(self, "_bt_busy", None):
            self._bt_status = {}
        self._bt_rows = ([], set())
        self._tray_refresh_bt()

    def _tray_refresh_bt(self):
        if self.tray_kind != "bluetooth":
            return False

        def with_conn(conn_out):
            conn = {l.split(" ", 2)[1] for l in (conn_out or "").splitlines() if l.count(" ") >= 2}

            def fill(out):
                if self.tray_kind != "bluetooth":
                    return
                devs = []
                for ln in (out or "").splitlines():
                    parts = ln.split(" ", 2)
                    if len(parts) >= 3:
                        devs.append((parts[1], parts[2]))
                self._bt_rows = (devs, conn)
                self._render_bt()
            services.run_async(["bluetoothctl", "devices", "Paired"], fill)
        services.run_async(["bluetoothctl", "devices", "Connected"], with_conn)
        return False

    def _render_bt(self):
        if self.tray_kind != "bluetooth":
            return
        devs, conn = self._bt_rows
        status, busy = getattr(self, "_bt_status", {}), getattr(self, "_bt_busy", None)
        for ch in self.bt_list.get_children():
            self.bt_list.remove(ch)
        for mac, name in devs:
            kind, text = status.get(mac, (None, ""))
            r = Gtk.Box(spacing=8); r.pack_start(Ico("bluetooth", 14, (1, 1, 1, 0.9 if mac in conn else 0.5), 1.5), False, False, 2)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col.pack_start(label(name), False, False, 0)
            if kind:
                col.pack_start(self._status_widget(kind, text), False, False, 0)
            r.pack_start(col, True, True, 0)
            b = Gtk.Button(label="Disconnect" if mac in conn else "Connect"); b.get_style_context().add_class("clear")
            b.set_sensitive(not busy)
            b.connect("clicked", lambda _b, m=mac, c=(mac in conn): self._bt_connect(m, c))
            r.pack_end(b, False, False, 0); self.bt_list.pack_start(r, False, False, 2)
        if not devs:
            self.bt_list.pack_start(self._empty("No paired devices. Pair one with bluetoothctl for now."), False, False, 2)
        self.bt_list.show_all()

    def _bt_connect(self, mac, connected):
        if getattr(self, "_bt_busy", None):
            return
        name = next((n for m, n in self._bt_rows[0] if m == mac), mac)
        status = self.__dict__.setdefault("_bt_status", {})
        status.clear(); status[mac] = ("connecting", "Disconnecting…" if connected else "Connecting…")
        self._bt_busy = mac
        self._render_bt()

        def done(ok, out, err):
            self._bt_busy = None
            good, text = services.bt_result(ok, out + "\n" + err, not connected)
            status.clear(); status[mac] = ("ok" if good else "failed", text)
            self.show_toast("Bluetooth", ("%s: %s" % (name, text)) if good else "%s: %s" % (name, text))
            if self.tray_kind == "bluetooth":
                self._tray_refresh_bt()
        services.run_async_err(["bluetoothctl", "--timeout", "20", "disconnect" if connected else "connect", mac], done)

    # -- audio
    def _tray_volume(self, box):
        self._tray_head(box, "volume", "Audio output")
        if not self.audio.available:
            box.pack_start(self._empty("No audio control found. Install pipewire (wpctl) or pulseaudio-utils (pactl)."), False, False, 4)
            return
        holder = {}

        def got(v, muted):
            holder["sc"] = self._tray_slider(box, v if v is not None else 0.5, self.audio.set, "volume"); box.show_all()
            self._tray_btn(box, "Mute / unmute", self.audio.toggle_mute); box.show_all()
        self.audio.get(got)

    # -- brightness + night light
    def _tray_brightness(self, box):
        self._tray_head(box, "brightness", "Brightness")
        if self.light.available:
            self._tray_slider(box, self.light.get() or 0.5, lambda v: self.light.set(max(0.05, v)), "brightness")
        else:
            box.pack_start(self._empty("No controllable backlight here (desktop monitors use their own buttons)."), False, False, 4)
        tool = shutil.which("gammastep") or shutil.which("redshift")
        if tool:
            name = os.path.basename(tool)
            self._tray_switch_row(box, "Night light", lambda v: services.fire([name, "-O", "3500"] if v else [name, "-x"])).set_init(False)
        else:
            box.pack_start(self._empty("Night light needs gammastep or redshift."), False, False, 4)

    # -- power
    def _tray_power(self, box):
        self._tray_head(box, "battery", "Power")
        b = services.battery()
        box.pack_start(label("Battery %d%%%s" % (b[0], " - charging" if b[1] else "") if b else "Running on mains power (no battery)", "muted"), False, False, 2)
        if shutil.which("powerprofilesctl"):
            row = Gtk.Box(spacing=6, homogeneous=True)
            for prof, lab in (("power-saver", "Saver"), ("balanced", "Balanced"), ("performance", "Perf")):
                bt = Gtk.Button(label=lab); bt.get_style_context().add_class("tile")
                bt.connect("clicked", lambda _b, p_=prof: services.fire(["powerprofilesctl", "set", p_])); row.pack_start(bt, True, True, 0)
            box.pack_start(row, False, False, 4)
        self._tray_btn(box, "Lock screen (not built yet)", lambda: None, False)
        self._tray_btn(box, "Log out", lambda: self.confirm_power("logout"))
        self._tray_btn(box, "Restart…", lambda: self.confirm_power("reboot"))
        self._tray_btn(box, "Power off…", lambda: self.confirm_power("poweroff"))
        if self.nested:
            box.pack_start(self._empty("Nested test session: Restart / Power off only show what they would do; your computer is not touched."), False, False, 2)

    # -- calendar
    def _tray_clock(self, box):
        cal = Gtk.Calendar(); cal.set_margin_top(2)
        box.pack_start(cal, False, False, 0)

    @staticmethod
    def _with_search_icon(entry, color=(1, 1, 1, 0.85)):
        return search_overlay(entry, color)

    # ------------------------------------------------------- desktop icons
    def _desktop_dir(self):
        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) or os.path.join(GLib.get_home_dir(), "Desktop")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def _build_desktop_icons(self):
        self.icons_fixed = Gtk.Fixed()
        self.desk.put(self.icons_fixed, 10, 48)
        self._sel, self._rows, self._icons_id = None, 0, None
        self._ddir = self._desktop_dir()
        self._ddir_mon = Gio.File.new_for_path(self._ddir).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._ddir_mon.connect("changed", lambda *_: self._queue_icons())
        self.desk.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        self.desk.connect("drag-data-received", self._desktop_drop)

    def _desktop_drop(self, w, ctx, x, y, sel, info, time_):
        """Files dropped on the desktop (from SparkFiles or any file manager) are copied or moved into the Desktop folder."""
        from .filesops import copy_tree, delete_tree, unique_child
        uris = sel.get_uris() or []
        move = ctx.get_selected_action() == Gdk.DragAction.MOVE
        dest = Gio.File.new_for_path(self._ddir)
        for u in uris:
            src = Gio.File.new_for_uri(u)
            if src.get_parent() is not None and src.get_parent().equal(dest):
                continue                                              # already on the desktop
            try:
                t = unique_child(dest, src.get_basename())
                if move:
                    try:
                        src.move(t, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, None, None, None)
                    except GLib.Error:
                        copy_tree(src, t); delete_tree(src)
                else:
                    copy_tree(src, t)
            except GLib.Error as e:
                print("glitterde: desktop drop failed: %s" % e.message, file=sys.stderr)
        Gtk.drag_finish(ctx, bool(uris), False, time_)

    def _queue_icons(self):
        if self._icons_id:
            GLib.source_remove(self._icons_id)
        self._icons_id = GLib.timeout_add(150, lambda: (setattr(self, "_icons_id", None), self.rebuild_icons(), False)[2])

    def _desktop_items(self):
        items = []
        home = GLib.get_home_dir()
        if prefs.get("desktop.show_home"):
            items.append(dict(name="Home", path=home, dir=True, kind="home", mtime=0))
        if prefs.get("desktop.show_trash"):
            items.append(dict(name="Trash", path="trash:///", dir=True, kind="trash", mtime=0))
        files = []
        try:
            en = Gio.File.new_for_path(self._ddir).enumerate_children(
                "standard::name,standard::display-name,standard::type,standard::is-hidden,time::modified", Gio.FileQueryInfoFlags.NONE, None)
            for i in en:
                if (i.get_is_hidden() or i.get_name().startswith(".")) and not prefs.get("desktop.show_hidden"):
                    continue
                files.append(dict(name=i.get_display_name(), path=os.path.join(self._ddir, i.get_name()),
                                  dir=i.get_file_type() == Gio.FileType.DIRECTORY, kind="file",
                                  mtime=i.get_attribute_uint64("time::modified")))
        except GLib.Error:
            pass
        sort = prefs.get("desktop.sort")
        if sort == "modified":
            files.sort(key=lambda f: -f["mtime"])
        elif sort == "type":
            files.sort(key=lambda f: (f["dir"] is False, os.path.splitext(f["name"])[1].lower(), f["name"].casefold()))
        else:
            files.sort(key=lambda f: (not f["dir"], f["name"].casefold()))
        return items + files

    @staticmethod
    def _icon_key(it):
        return it["kind"] if it["kind"] != "file" else "f" + hashlib.sha1(it["name"].encode("utf-8", "replace")).hexdigest()[:14]

    def rebuild_icons(self):
        for ch in self.icons_fixed.get_children():
            self.icons_fixed.remove(ch)
        self._sel, self._idrag, self._icon_cells = None, None, {}
        if not prefs.get("desktop.show_icons"):
            self.icons_fixed.hide()
            return
        f = {"small": 0.8, "medium": 1.0, "large": 1.3}[prefs.get("desktop.icon_size")]
        cw, chh = int(92 * f), int(88 * f)
        rows = max(1, (max(self.H, 600) - self.PH - 150 - 20) // chh)
        cols = max(1, (self.W - 20) // cw)
        self._rows, self._icon_cell, self._icon_grid = rows, (cw, chh), (cols, rows)
        self.icons_fixed.set_size_request(cols * cw, rows * chh)         # the whole area: icons can be dragged anywhere in it
        items = self._desktop_items()
        saved = {}
        for k, v in config.load().get("icon_pos", {}).items():
            try:
                c, r = (int(x) for x in str(v).split(","))
                if 0 <= c < cols and 0 <= r < rows:
                    saved[k] = (c, r)
            except ValueError:
                pass
        used = {saved[self._icon_key(it)] for it in items if self._icon_key(it) in saved}
        slots = ((c, r) for c in range(cols) for r in range(rows))        # unplaced icons fill the free cells column by column
        for it in items:
            key = self._icon_key(it)
            cell = saved.get(key)
            if cell is None:
                cell = next((x for x in slots if x not in used), (0, 0)); used.add(cell)
            self._icon_cells[key] = cell
        for n, it in enumerate(items):
            eb = Gtk.EventBox(); eb.set_visible_window(False); eb.set_above_child(True)   # catch clicks on the icon artwork too
            eb.get_style_context().add_class("deskicon")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); v.set_margin_top(4); v.set_margin_bottom(4)
            v.set_size_request(cw - 6, -1)
            da = Gtk.DrawingArea(); da.set_size_request(int(64 * f), int(46 * f))
            da.connect("draw", self._draw_desk_icon, it, f)
            l = label(it["name"], xalign=0.5, ellipsize=False)
            l.set_line_wrap(True); l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR); l.set_max_width_chars(12); l.set_lines(2)
            l.set_justify(Gtk.Justification.CENTER); l.set_ellipsize(Pango.EllipsizeMode.END)
            v.pack_start(da, False, False, 0); v.pack_start(l, False, False, 0)
            eb.add(v)
            eb.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
            eb.connect("button-press-event", self._icon_press, it)
            eb.connect("motion-notify-event", self._icon_motion)
            eb.connect("button-release-event", self._icon_release, it)
            eb.set_tooltip_text(it["name"])
            c, r = self._icon_cells[self._icon_key(it)]
            self.icons_fixed.put(eb, c * cw, r * chh)
        self.icons_fixed.show_all()

    @staticmethod
    def _draw_desk_icon(da, cr, it, f):
        w, h = da.get_allocated_width(), da.get_allocated_height()
        cr.save(); cr.translate(w / 2, h / 2); cr.scale(f, f)
        if it["kind"] == "trash":
            ic.trash_color(cr, 0, 0, 38)
        elif it["kind"] == "home":
            ic.folder(cr, -19, -16, 38, 32, (0.62, 0.74, 1.0, 1), (0.40, 0.55, 1.0, 1))
            ic.icon(cr, "home", 0, 4, 14, (1, 1, 1, 0.92), 1.5)
        else:
            from .sparkfiles import SparkFiles
            ext = os.path.splitext(it["name"])[1].lstrip(".").lower()
            cr.scale(0.85, 0.85)
            class _D:                                  # SparkFiles' painter wants a DrawingArea-like object
                def get_allocated_width(s): return 0
                def get_allocated_height(s): return 0
            SparkFiles._draw_icon(_D(), cr, it["is_dir"] if "is_dir" in it else it["dir"], it["name"], ext)
        cr.restore()
        return False

    def _select(self, eb):
        if self._sel is not None:
            self._sel.get_style_context().remove_class("sel")
        self._sel = eb
        if eb is not None:
            eb.get_style_context().add_class("sel")

    def _icon_press(self, eb, ev, it):
        if os.environ.get('GLITTERDE_DEBUG'):
            print('icon press', it['name'], ev.button, ev.type, file=sys.stderr)
        self._select(eb)
        if ev.button == 1 and ev.type == Gdk.EventType.BUTTON_PRESS:
            self._idrag = dict(eb=eb, rx=ev.x_root, ry=ev.y_root, moved=False,
                               x=self.icons_fixed.child_get_property(eb, "x"), y=self.icons_fixed.child_get_property(eb, "y"))
        if ev.button == 1 and ev.type == Gdk.EventType._2BUTTON_PRESS:
            self._idrag = None
            self.open_item(it)
        elif ev.button == 3:
            GlassMenu([("item", "Open", lambda: self.open_item(it)),
                       ("item", "Show Desktop folder in Files", lambda: services.fire(["sparkfiles", self._ddir])),
                       ("sep",),
                       ("item", "Move to Trash", lambda: self._trash(it), it["kind"] == "file")],
                      theme=self.theme).popup_at(ev.x_root, ev.y_root)
        return True

    def _icon_motion(self, eb, ev):
        d = getattr(self, "_idrag", None)
        if not d or d["eb"] is not eb or not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        dx, dy = ev.x_root - d["rx"], ev.y_root - d["ry"]
        if not d["moved"] and abs(dx) + abs(dy) < 6:          # a click, not a drag
            return True
        d["moved"] = True
        self.icons_fixed.move(eb, int(d["x"] + dx), int(d["y"] + dy))
        return True

    def _icon_release(self, eb, ev, it):
        d, self._idrag = getattr(self, "_idrag", None), None
        if not d or ev.button != 1 or not d["moved"] or d["eb"] is not eb:
            return False
        cw, chh = self._icon_cell
        cols, rows = self._icon_grid
        x, y = self.icons_fixed.child_get_property(eb, "x"), self.icons_fixed.child_get_property(eb, "y")
        want = (max(0, min(cols - 1, round(x / cw))), max(0, min(rows - 1, round(y / chh))))
        key = self._icon_key(it)
        taken = {c for k, c in self._icon_cells.items() if k != key}
        cell = min(((c, r) for c in range(cols) for r in range(rows) if (c, r) not in taken),      # snap to the nearest free cell
                   key=lambda t: (t[0] - want[0]) ** 2 + (t[1] - want[1]) ** 2, default=want)
        config.set("icon_pos", key, "%d,%d" % cell)
        GLib.idle_add(lambda: (self.rebuild_icons(), False)[1])
        return True

    def reset_icon_positions(self):
        d = config.load(); d.pop("icon_pos", None); config.save(d)
        self.rebuild_icons()

    def _trash(self, it):
        try:
            Gio.File.new_for_path(it["path"]).trash(None)
        except GLib.Error as e:
            self.show_toast("Could not move to Trash", e.message[:80])

    def open_item(self, it):
        if it["kind"] == "trash":
            services.fire(["sparkfiles", "trash:///"]); return
        path = it["path"]
        if it["dir"]:
            services.fire(["sparkfiles", path]); return
        if path.endswith(".desktop"):
            app = Gio.DesktopAppInfo.new_from_filename(path)
            if app:
                self.launch(app); return
        self.open_uri(Gio.File.new_for_path(path).get_uri(), force_default=True)

    def _desk_press(self, desk, ev):
        if ev.button == 1:
            self._select(None)
        elif ev.button == 3:
            self._desk_menu(ev)
        return False

    def _desk_menu(self, ev):
        sort_now = prefs.get("desktop.sort")
        sorts = [("name", "Name"), ("modified", "Date modified"), ("type", "Type")]
        items = [("tiles", [("plus", "New folder", self.new_desktop_folder),
                            ("image", "Wallpaper", lambda: services.fire(["sparksettings", "Wallpaper"])),
                            ("monitor", "Display", lambda: services.fire(["sparksettings", "Display"])),
                            ("gear", "Settings", lambda: services.fire(["sparksettings"]))]),
                 ("itemi", "doc", "Open Desktop folder", lambda: services.fire(["sparkfiles", self._ddir])),
                 ("itemi", "terminal", "Open terminal here", lambda: services.fire(["sparkterm", self._ddir])),
                 ("sep",),
                 ("sub", "grid", "Widgets",
                  [("check", title, key in self.enabled, lambda k=key: self.toggle_widget(k, k not in self.enabled))
                   for key, title in self.WIDGET_TITLES] + [("sep",), ("item", "Reset positions", self.reset_widget_positions)]),
                 ("check", "Show workspace selector", prefs.get("desktop.show_workspaces"), lambda: prefs.set("desktop.show_workspaces", not prefs.get("desktop.show_workspaces"))),
                 ("check", "Show desktop icons", prefs.get("desktop.show_icons"), lambda: prefs.set("desktop.show_icons", not prefs.get("desktop.show_icons"))),
                 ("item", "Reset icon positions", self.reset_icon_positions),
                 ("sub", "list", "Sort icons by",
                  [("check", lab, sort_now == key, lambda k=key: prefs.set("desktop.sort", k)) for key, lab in sorts]),
                 ("sep",),
                 ("itemi", "palette", "Appearance…", lambda: services.fire(["sparksettings", "Theme"])),
                 ("itemi", "windows", "Desktop settings…", lambda: services.fire(["sparksettings", "Desktop icons"]))]
        GlassMenu(items, theme=self.theme, min_width=232).popup_at(ev.x_root, ev.y_root)

    def new_desktop_folder(self):
        d = Gtk.Dialog(title="New folder", transient_for=self.win, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button("Create", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        e = Gtk.Entry(); e.set_text("Untitled folder"); e.set_activates_default(True)
        e.set_margin_start(14); e.set_margin_end(14); e.set_margin_bottom(10)
        d.get_content_area().pack_start(label("Folder name", margin=10) if False else Gtk.Label(label="Folder name", margin=10), False, False, 0)
        d.get_content_area().pack_start(e, False, False, 0)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK and e.get_text().strip():
            try:
                Gio.File.new_for_path(os.path.join(self._ddir, e.get_text().strip())).make_directory(None)
            except GLib.Error as err:
                self.show_toast("Could not create folder", err.message[:80])
        d.destroy()

    def open_uri(self, uri, force_default=False):
        if not force_default and uri and shutil.which("sparkfiles") and (uri == "trash:///" or (uri.startswith("file://") and os.path.isdir(Gio.File.new_for_uri(uri).get_path() or ""))):
            services.fire(["sparkfiles", uri]); return
        try:
            Gio.AppInfo.launch_default_for_uri(uri, Gdk.Display.get_default().get_app_launch_context())
        except GLib.Error as e:
            self.show_toast("Could not open", "%s (no handler installed?)" % (e.message[:80]))

    # --------------------------------------------------------- card helper
    WIDGET_TITLES = [("clock", "Clock"), ("system", "System"), ("network", "Network"), ("bluetooth", "Bluetooth"),
                     ("phone", "GlitterLink"), ("media", "Now playing"), ("quick", "Quick actions")]

    def _card(self, title, icon, width=266, extra_head=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(width - 32, -1)          # margins (16+16) are added on top
        for m in ("top", "bottom"):
            getattr(box, "set_margin_" + m)(12)
        box.set_margin_start(16); box.set_margin_end(16)
        head = Gtk.Box(spacing=8)
        head.pack_start(Ico(icon, 15, (1, 1, 1, 0.95), 1.5), False, False, 0)
        head.pack_start(label(title, "title"), False, False, 0)
        if extra_head:
            head.pack_end(extra_head, False, False, 0)
        box.pack_start(head, False, False, 2)
        wrap = Gtk.EventBox(); wrap.set_visible_window(False); wrap.add(box)
        wrap.set_size_request(width, -1)
        self.desk.add_glass(wrap, "card", 19)
        wrap.body, wrap.head = box, head
        self.desk.put(wrap, 0, 0)
        return wrap

    def _register_widgets(self):
        """Give every card its key, drag handling and a close button."""
        self.widgets = {"clock": self.clock_card, "system": self.col_cards[0], "network": self.col_cards[1],
                        "bluetooth": self.col_cards[2], "phone": self.col_cards[3], "media": self.col_cards[4],
                        "quick": self.col_cards[5]}
        for key, w in self.widgets.items():
            w.key = key
            w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
            w.connect("button-press-event", self._wpress)
            w.connect("motion-notify-event", self._wmotion)
            w.connect("button-release-event", self._wrelease)
            w.connect("size-allocate", self._widget_alloc)
            if hasattr(w, "head") and key != "clock":
                b = icon_button("close", 9, "Remove this widget (re-add it from the desktop menu)", lambda k=key: self.toggle_widget(k, False), pad=4)
                b.get_style_context().add_class("cardclose")
                w.head.pack_end(b, False, False, 0)
                b.show_all()

    def _widget_alloc(self, w, a):
        """A card grew or shrank (new notification, album art appearing ...): lay everything out again."""
        sz = (a.width, a.height)
        seen = self.__dict__.setdefault("_wsz", {})
        if seen.get(w.key) != sz:
            seen[w.key] = sz
            self.relayout()

    GAP_X, GAP_Y = 20, 28          # clear space between cards: blur radius 26 + drop 10 of the shadow, minus its faint tail

    def _resolve_widgets(self, items, top, limit, col_w):
        """items = [(key, home_x, home_y, w, h)]. Cards are placed in reading order; a card whose box (plus shadow gap) would cover one
        already placed is pushed down below it, or into the next column to the left when it would fall off the screen. Positions are
        recomputed from the HOME positions every time, so a pushed card moves back by itself once the cover is gone."""
        placed, out = [], {}
        for key, x, y, w, h in sorted(items, key=lambda i: (i[2], i[1])):
            for _col in range(4):
                for _ in range(len(placed) + 1):
                    hit = next(((px, py, pw, ph) for px, py, pw, ph in placed
                                if x < px + pw + self.GAP_X and px < x + w + self.GAP_X and y < py + ph + self.GAP_Y and py < y + h + self.GAP_Y), None)
                    if hit is None:
                        break
                    y = hit[1] + hit[3] + self.GAP_Y
                if y + h <= limit or x - col_w < 0:
                    break
                x, y = x - col_w, top                  # no room below: next column
            y = max(top, min(y, limit - h))
            placed.append((x, y, w, h)); out[key] = (int(x), int(y))
        return out

    def _wpress(self, w, ev):
        if ev.button == 3:
            GlassMenu([("item", "Remove widget", lambda: self.toggle_widget(w.key, False)),
                       ("item", "Reset position", lambda: self.reset_widget_positions(w.key))],
                      theme=self.theme).popup_at(ev.x_root, ev.y_root)
            return True
        if ev.button != 1:
            return False
        pos = w.translate_coordinates(self.desk, 0, 0)
        if pos is None:
            return False
        self._drag = dict(w=w, px=ev.x_root, py=ev.y_root, x0=pos[0], y0=pos[1], moved=False)
        w.grab_add()
        return True

    def _wmotion(self, w, ev):
        d = getattr(self, "_drag", None)
        if not d or d["w"] is not w:
            return False
        dx, dy = ev.x_root - d["px"], ev.y_root - d["py"]
        if not d["moved"] and abs(dx) + abs(dy) < 4:
            return True
        d["moved"] = True
        a = w.get_allocation()
        nx = int(max(0, min(self.W - a.width, d["x0"] + dx)))
        ny = int(max(self.top, min(self.H - a.height, d["y0"] + dy)))
        self.wpos[w.key] = (nx, ny)
        self.desk.move(w, nx, ny)
        return True

    def _wrelease(self, w, ev):
        d = getattr(self, "_drag", None)
        if not d or d["w"] is not w:
            return False
        w.grab_remove()
        self._drag = None
        if d["moved"] and w.key in self.wpos:
            config.set("widget_pos", w.key, "%d,%d" % self.wpos[w.key])
        self.relayout()                              # dropped on top of another card: one of them gives way
        return True

    def toggle_widget(self, key, on):
        if on:
            self.enabled.add(key)
        else:
            self.enabled.discard(key)
        if not self.demo:
            config.set("widgets", "enabled", ",".join(sorted(self.enabled)))
        self.apply_widgets()

    def apply_widgets(self):
        for key, w in self.widgets.items():
            w.set_visible(key in self.enabled)
        self.relayout()
        if getattr(self, "media", None) is not None:
            self.tick_stats(); self.tick_stats(); self._tick_media()      # fill newly shown widgets right away
            if "network" in self.enabled:
                self.refresh_network()

    def reset_widget_positions(self, key=None):
        d = config.load()
        if key:
            d.get("widget_pos", {}).pop(key, None)
            self.wpos.pop(key, None)
        else:
            d.pop("widget_pos", None); self.wpos.clear()
        config.save(d)
        self.relayout()

    def _load_widget_state(self, initial=False):
        d = config.load()
        if self.demo:                               # demo seeds sample widgets once; afterwards it behaves like normal
            if initial or not hasattr(self, "enabled"):
                self.enabled = {k for k, _ in self.WIDGET_TITLES}
        else:
            raw = d.get("widgets", {}).get("enabled", "")        # blank slate: no widgets until you add them
            self.enabled = set(x for x in str(raw).split(",") if x and x != "notifications")      # notifications moved into the panel
        self.wpos = {}
        for k, v in d.get("widget_pos", {}).items():
            try:
                x, y = str(v).split(","); self.wpos[k] = (int(x), int(y))
            except ValueError:
                pass

    def _empty(self, text):
        l = label(text, "muted", ellipsize=False); l.set_line_wrap(True); l.set_max_width_chars(30)
        return l

    # ---------------------------------------------------------- clock card
    def _build_clock_card(self):
        w = Gtk.EventBox(); w.set_visible_window(False); b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b.set_margin_start(22); b.set_margin_end(22); b.set_margin_top(16); b.set_margin_bottom(18)
        self.big_clock = label("", "clock"); self.big_date = label("", "date"); self.uptime_lbl = label("", "muted")
        b.pack_start(self.big_clock, False, False, 0); b.pack_start(self.big_date, False, False, 0)
        sep = Gtk.Separator(); sep.set_margin_top(8); sep.set_margin_bottom(4)
        b.pack_start(sep, False, False, 0); b.pack_start(self.uptime_lbl, False, False, 0)
        w.add(b); w.set_size_request(266, -1)
        self.clock_card = w
        self.desk.add_glass(w, "card", 22)
        self.desk.put(w, 0, 0)

    # ----------------------------------------------------------- system card
    def _card_system(self):
        c = self._card("System", "chip")
        row = Gtk.Box(spacing=6, homogeneous=True)
        self.rings = {}
        for key, name in (("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disk")):
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            r = Ring(66); self.rings[key] = r
            v.pack_start(r, False, False, 0); v.pack_start(label(name, "muted", 0.5), False, False, 0)
            sub = label("", "tiny", 0.5); self.rings[key + "_sub"] = sub
            v.pack_start(sub, False, False, 0)
            row.pack_start(v, True, True, 0)
        c.body.pack_start(row, False, False, 0)
        self.spark_sys = Spark(234, 26)
        c.body.pack_start(self.spark_sys, False, False, 2)
        return c

    def tick_stats(self):
        if not ({"system", "network"} & self.enabled):
            return True
        cpu = self.stats.cpu(); mf, mu, mt = self.stats.mem(); df, du, dt = self.stats.disk()
        self.rings["cpu"].set(cpu, "%d%%" % round(cpu * 100))
        self.rings["ram"].set(mf, "%d%%" % round(mf * 100))
        self.rings["ram_sub"].set_text("%.1f / %.0f GB" % (mu / 2**30, mt / 2**30))
        self.rings["disk"].set(df, "%d%%" % round(df * 100))
        self.rings["disk_sub"].set_text("%.0f / %.0f GB" % (du / 2**30, dt / 2**30))
        rate = self.stats.net_rate()
        self.spark_sys.push(rate); self.spark_net.push(rate)
        self.net_rate_lbl.set_text("%s/s" % self._hum(rate))
        return True

    @staticmethod
    def _hum(b):
        for u in ("B", "KB", "MB", "GB"):
            if b < 1024 or u == "GB":
                return ("%.0f %s" if u == "B" else "%.1f %s") % (b, u)
            b /= 1024.0

    # ---------------------------------------------------------- network card
    def _card_network(self):
        self.net_rate_lbl = label("", "tiny")
        c = self._card("Network", "sparkle", extra_head=self.net_rate_lbl)
        self.net_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c.body.pack_start(self.net_rows, False, False, 0)
        self.spark_net = Spark(234, 22)
        c.body.pack_start(self.spark_net, False, False, 0)
        self.ssid = None
        return c

    def refresh_network(self):
        for ch in self.net_rows.get_children():
            self.net_rows.remove(ch)
        links = services.interfaces()
        any_up = False
        for name, kind, up, speed in links:
            any_up = any_up or up
            row = Gtk.Box(spacing=10)
            row.pack_start(Ico("wifi" if kind == "wifi" else "network", 16, (1, 1, 1, 0.95 if up else 0.5), 1.5), False, False, 4)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = (self.ssid or "Wi-Fi") if kind == "wifi" else "Ethernet"
            state = ("Connected" + (" | %d Mbps" % speed if speed else "")) if up else "Not connected"
            v.pack_start(label(title if up or kind == "wifi" else "Ethernet", "title"), False, False, 0)
            v.pack_start(label(state + "  (%s)" % name, "muted"), False, False, 0)
            row.pack_start(v, True, True, 0)
            self.net_rows.pack_start(row, False, False, 0)
        if not links:
            self.net_rows.pack_start(self._empty("No network adapters found."), False, False, 0)
        self.net_rows.show_all()
        self._update_net_icon(links)

    def _update_net_icon(self, links=None):
        """Tray icon: wired glyph when an Ethernet link is the one that is up (and no Wi-Fi is), Wi-Fi glyph otherwise."""
        links = services.interfaces() if links is None else links
        any_up = any(up for _, _, up, _ in links)
        wired = any(up and kind != "wifi" for _, kind, up, _ in links)
        wifi_up = any(up and kind == "wifi" for _, kind, up, _ in links)
        self.wifi_ico.set_icon("network" if (wired and not wifi_up) else "wifi", (1, 1, 1, 0.95 if any_up else 0.4))
        self.wifi_ico.set_tooltip_text(("Wired network connected" if (wired and not wifi_up) else "Network connected") if any_up else "No network connection")

    def _poll_ssid(self):
        services.run_async(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                           lambda out: setattr(self, "ssid", next((l.split(":", 1)[1] for l in (out or "").splitlines()
                                                                   if l.startswith("yes:")), None)))

    # -------------------------------------------------------- bluetooth card
    def _card_bluetooth(self):
        c = self._card("Bluetooth", "bluetooth")
        self.bt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        c.body.pack_start(self.bt_box, False, False, 0)
        self.bt_present = shutil.which("bluetoothctl") and os.path.isdir("/sys/class/bluetooth") and bool(os.listdir("/sys/class/bluetooth"))
        return c

    def refresh_bt(self, devices=None):
        for ch in self.bt_box.get_children():
            self.bt_box.remove(ch)
        if devices is None and not self.bt_present:
            self.bt_box.pack_start(self._empty("No Bluetooth adapter found. Plug one in and it will appear here."), False, False, 0)
        elif not devices:
            self.bt_box.pack_start(self._empty("No devices connected."), False, False, 0)
        else:
            for name in devices:
                r = Gtk.Box(spacing=10); r.pack_start(Ico("bluetooth", 15, (1, 1, 1, 0.9), 1.5), False, False, 4)
                v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                v.pack_start(label(name, "title"), False, False, 0); v.pack_start(label("Connected", "muted"), False, False, 0)
                r.pack_start(v, True, True, 0); self.bt_box.pack_start(r, False, False, 0)
        self.bt_ico.color = (1, 1, 1, 0.9 if devices else 0.45); self.bt_ico.queue_draw()
        self.bt_box.show_all()

    def _poll_bt(self):
        if self.bt_present:
            services.run_async(["bluetoothctl", "devices", "Connected"],
                               lambda out: self.refresh_bt([l.split(" ", 2)[2] for l in (out or "").splitlines() if l.count(" ") >= 2]))

    # ------------------------------------------------------------ phone card
    def _card_phone(self):
        c = self._card("GlitterLink", "phone")
        self.phone_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        c.body.pack_start(self.phone_box, False, False, 0)
        self.refresh_phone()
        return c

    def refresh_phone(self):
        for ch in self.phone_box.get_children():
            self.phone_box.remove(ch)
        if self.demo:
            top = Gtk.Box(spacing=12)
            top.pack_start(Ico("phone", 40, (1, 1, 1, 0.9), 1.2), False, False, 4)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            v.pack_start(label("Pixel 8", "big"), False, False, 0)
            v.pack_start(label("Connected | 78%", "muted"), False, False, 0)
            top.pack_start(v, True, True, 0); self.phone_box.pack_start(top, False, False, 0)
            grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
            for i, (t, ico) in enumerate((("Send file", "sendfile"), ("Receive", "download"), ("Clipboard", "clipboard"), ("File bin", "trash"))):
                b = Gtk.Button(); b.get_style_context().add_class("tile")
                bx = Gtk.Box(spacing=6); bx.pack_start(Ico(ico, 14, (1, 1, 1, .95), 1.4), False, False, 2); bx.pack_start(label(t, "tiny"), False, False, 0)
                b.add(bx); grid.attach(b, i % 2, i // 2, 1, 1)
            self.phone_box.pack_start(grid, False, False, 0)
        else:
            self.phone_box.pack_start(self._empty("No paired devices yet. Pair an Android phone to share files and clipboard content."), False, False, 0)
            b = Gtk.Button(label="Pair a phone"); b.get_style_context().add_class("clear")
            b.set_sensitive(False); b.set_tooltip_text("GlitterLink daemon is roadmap phase 10 - not built yet")
            self.phone_box.pack_start(b, False, False, 2)
        self.phone_box.show_all()

    # ------------------------------------------------------------ media card
    def _card_media(self):
        c = self._card("Now playing", "music")
        self.media_empty = self._empty("Nothing playing. Any MPRIS player (Spotify, Firefox, VLC, mpv with mpris) shows up here.")
        self.media_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box(spacing=12)
        self.art = Gtk.DrawingArea(); self.art.set_size_request(54, 54); self.art.pix = None
        self.art.connect("draw", self._draw_art)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); v.set_valign(Gtk.Align.CENTER)
        self.m_title = label("", "big", width_chars=20); self.m_artist = label("", "muted", width_chars=22)
        self.m_player = label("", "tiny", width_chars=22)
        v.pack_start(self.m_title, False, False, 0); v.pack_start(self.m_artist, False, False, 0); v.pack_start(self.m_player, False, False, 0)
        top.pack_start(self.art, False, False, 0); top.pack_start(v, True, True, 0)
        self.m_bar = Bar(14, self._seek)
        times = Gtk.Box(); self.m_pos = label("0:00", "tiny"); self.m_len = label("0:00", "tiny")
        times.pack_start(self.m_pos, False, False, 0); times.pack_end(self.m_len, False, False, 0)
        ctr = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER)
        self.m_play = icon_button("pause", 20, "Play / pause", lambda: self.media.control("PlayPause"), pad=9)
        ctr.pack_start(icon_button("prev", 17, "Previous", lambda: self.media.control("Previous"), pad=9), False, False, 0)
        ctr.pack_start(self.m_play, False, False, 0)
        ctr.pack_start(icon_button("next", 17, "Next", lambda: self.media.control("Next"), pad=9), False, False, 0)
        for w in (top, self.m_bar, times, ctr):
            self.media_body.pack_start(w, False, False, 0)
        c.body.pack_start(self.media_empty, False, False, 0)
        c.body.pack_start(self.media_body, False, False, 0)
        GLib.timeout_add(900, self._maybe_welcome)
        GLib.timeout_add_seconds(1, self._tick_media)
        return c

    def _draw_art(self, da, cr):
        if da.pix:
            gfx.rrect(cr, 0, 0, 54, 54, 9); cr.clip()
            cr.scale(54.0 / da.pix.get_width(), 54.0 / da.pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, da.pix, 0, 0); cr.paint()
        else:
            ic.album_art(cr, 0, 0, 54, 54, 9)
        return False

    def on_media(self):
        m = getattr(self, "media", None)
        if m is None:                        # called by the MPRIS client while it is still being constructed
            return
        has = bool(m.name and (m.title or m.status != "Stopped"))
        if has:
            self.media_body.show_all()
        self.media_empty.set_visible(not has); self.media_body.set_visible(has)
        if has:
            self.m_title.set_text(m.title or "Unknown track"); self.m_artist.set_text(m.artist or "")
            self.m_play.ico.set_icon("pause" if m.status == "Playing" else "play")
            self.m_player.set_text((getattr(m, "player", "") or "").capitalize())
            self.m_play.ico.queue_draw()
            if m.art != getattr(self, "_art_path", None):
                self._art_path = m.art
                self.art.pix = None
                if m.art and os.path.exists(m.art):
                    try:
                        pb = GdkPixbuf.Pixbuf.new_from_file(m.art)
                        side = min(pb.get_width(), pb.get_height())              # centre-crop to a square, never squash
                        pb = pb.new_subpixbuf((pb.get_width() - side) // 2, (pb.get_height() - side) // 2, side, side)
                        self.art.pix = pb.scale_simple(108, 108, GdkPixbuf.InterpType.BILINEAR)   # 2x for sharpness
                    except (GLib.Error, ValueError):
                        pass
                self.art.queue_draw()
            self._tick_media()
        self.relayout()

    def _tick_media(self):
        m = self.media
        if "media" not in self.enabled:
            return True
        if m.name and m.length:
            pos = m.position_us()
            self.m_bar.set(pos / m.length)
            self.m_pos.set_text("%d:%02d" % divmod(pos // 10**6, 60)); self.m_len.set_text("%d:%02d" % divmod(m.length // 10**6, 60))
        return True

    def _seek(self, v):
        self.media.seek_to(v)

    # ------------------------------------------------------- quick actions
    def _card_quick(self):
        c = self._card("Quick actions", "sparkle")
        row = Gtk.Box(spacing=8, homogeneous=True)
        self.q = {}
        for key, ico, tip, cb in (("dnd", "bell", "Do not disturb (silences pop-ups)", self.toggle_dnd),
                                  ("light", "brightness", "Brightness (click to cycle)", self.cycle_brightness),
                                  ("vol", "volume", "Mute / unmute (scroll to change volume)", self.audio.toggle_mute),
                                  ("power", "stopwatch", "Session", None)):
            b = Gtk.Button(); b.get_style_context().add_class("tile")
            ico_w = Ico(ico if key != "power" else "power", 20, (1, 1, 1, 0.97), 1.7)
            ico_w.set_margin_top(7); ico_w.set_margin_bottom(7); b.add(ico_w); b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            if cb:
                b.connect("clicked", lambda _b, f=cb: f())
            self.q[key] = b; row.pack_start(b, True, True, 0)
        self.q["power"].connect("clicked", self.power_menu)
        self.q["vol"].add_events(Gdk.EventMask.SCROLL_MASK)
        self.q["vol"].connect("scroll-event", self._vol_scroll)
        for key, ok in (("light", self.light.available), ("vol", self.audio.available)):
            self.q[key].set_no_show_all(True)
            self.q[key].set_visible(bool(ok))              # hide controls the machine doesn't have
        c.body.pack_start(row, False, False, 0)
        return c

    def toggle_dnd(self):
        self.dnd = not self.dnd
        ctx = self.q["dnd"].get_style_context()
        ctx.add_class("on") if self.dnd else ctx.remove_class("on")

    def cycle_brightness(self):
        v = self.light.get() or 0.5
        self.light.set(0.25 if v > 0.9 else v + 0.25)

    def _vol_scroll(self, w, ev):
        def got(v, muted):
            if v is not None:
                self.audio.set(v + (0.05 if ev.direction == Gdk.ScrollDirection.UP else -0.05))
        self.audio.get(got)
        return True

    def power_menu(self, btn):
        ok = True                                   # nested test sessions simulate the action (see do_power) instead of greying the buttons out
        items = [("head", "Session"),
                 ("itemi", "arrow_right", "Log out", lambda: self.confirm_power("logout")),
                 ("itemi", "pause", "Suspend", lambda: self.do_power("suspend"), ok),
                 ("sep",),
                 ("itemi", "power", "Restart…", lambda: self.confirm_power("reboot"), ok),
                 ("itemi", "power", "Power off…", lambda: self.confirm_power("poweroff"), ok)]
        if self.nested:
            items.append(("head", "Nested test session: power actions are only simulated"))
        win = btn.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        m = GlassMenu(items, theme=self.theme, min_width=200)
        m.popup_at(ox + a.x + a.width - 200, oy + a.y + a.height + 6)

    def do_power(self, what):
        """Run a power action and tell the user if the system refused it (it used to fail silently)."""
        if self.nested:                              # started by scripts/run-xephyr.sh / run-weston.sh: never touch the real machine
            self.show_toast("Nested test session", "Would have run: %s. Nothing was touched." % {"reboot": "restart", "poweroff": "power off", "suspend": "suspend"}[what], None, 6000)
            return
        def result(ok, msg):
            if not ok:
                self.show_toast("Could not %s" % {"reboot": "restart", "poweroff": "power off", "suspend": "suspend"}[what],
                                msg or "The system refused the request. Another user may be logged in, or an app is blocking it.", None, 9000)
        services.power_action(what, result)

    def confirm_power(self, what):
        title, detail, verb = {
            "logout": ("Log out of glitterDE?", "Your open windows will be closed.", "Log out"),
            "reboot": ("Restart this computer?", "Save your work first - open apps will be closed.", "Restart"),
            "poweroff": ("Power off this computer?", "Save your work first - open apps will be closed.", "Power off")}[what]
        act = Gtk.main_quit if what == "logout" else (lambda: self.do_power(what))     # the shell is the session: quitting it ends the session
        GlassConfirm(title, detail, verb, act, theme=self.theme).show_centered()

    # ---------------------------------------------------- notifications UI
    def _build_notifications(self):
        """Notifications live in the panel (the bell opens a popup like the other quick settings), not in a card on the desktop."""
        self.notif_card = None
        self.refresh_notifs()

    LOCAL_NID = 1_000_000_000                      # ids at/after this are notifications raised by the shell itself (drives, power ...)

    def refresh_notifs(self):
        n = len(self.notifs)
        self.bell_badge.set_text(str(n)); self.bell_badge.set_visible(n > 0)
        if getattr(self, "tray", None) is not None and self.tray.get_visible() and self.tray_kind == "notifications":
            for ch in self.tray_box.get_children():
                self.tray_box.remove(ch)
            self._tray_notifications(self.tray_box)
            self.tray_box.show_all()
            self.tray.resize(1, 1)

    def _tray_notifications(self, box):
        h = Gtk.Box(spacing=8)
        h.pack_start(Ico("bell", 16, (1, 1, 1, 0.95), 1.5), False, False, 0)
        h.pack_start(label("Notifications", "big"), True, True, 0)
        if self.notifs:
            clr = Gtk.Button(label="Clear all"); clr.get_style_context().add_class("clear"); clr.connect("clicked", lambda *_: self.clear_notifs())
            h.pack_end(clr, False, False, 0)
        box.pack_start(h, False, False, 2)
        self._tray_switch_row(box, "Do not disturb", lambda v: self.toggle_dnd() if v != self.dnd else None).set_init(self.dnd)
        lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for n in self.notifs[:30]:
            row = Gtk.Box(spacing=10); row.set_margin_top(4); row.set_margin_bottom(4)
            row.pack_start(self._notif_icon(n), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); v.set_valign(Gtk.Align.CENTER)
            v.pack_start(label(n.summary or n.app, "title", width_chars=24), False, False, 0)
            v.pack_start(label(n.body.replace("\n", " "), "muted", width_chars=30), False, False, 0)
            acts = getattr(n, "actions", None)
            if acts:
                ar = Gtk.Box(spacing=6); ar.set_margin_top(3)
                for text, cb in acts:
                    ab = Gtk.Button(label=text); ab.get_style_context().add_class("tile")
                    ab.connect("clicked", lambda _b, cb=cb, i=n.id: (self.close_tray(), self.dismiss_notif(i), cb()))
                    ar.pack_start(ab, False, False, 0)
                v.pack_start(ar, False, False, 0)
            row.pack_start(v, True, True, 0)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); col.set_valign(Gtk.Align.START)
            col.pack_start(label(ago(n.time), "tiny"), False, False, 0)
            row.pack_end(col, False, False, 0)
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.set_tooltip_text("Click to dismiss"); b.add(row)
            b.connect("clicked", lambda _b, i=n.id: self.dismiss_notif(i))
            lst.pack_start(b, False, False, 0)
        srv = getattr(self, "notif_srv", None)
        if srv is not None and not srv.active and not self.notifs:
            lst.pack_start(self._empty("Another program owns desktop notifications (e.g. your host desktop). Close it or run glitterDE in its own session to see them here."), False, False, 4)
        elif not self.notifs:
            lst.pack_start(self._empty("You're all caught up. New notifications from your apps will appear here."), False, False, 4)
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lst.show_all()
        sc.set_min_content_height(max(40, min(380, lst.get_preferred_height()[1])))      # the popup sizes itself to the minimum: ask for the real height
        sc.set_max_content_height(380); sc.set_propagate_natural_height(True); sc.add(lst)
        box.pack_start(sc, True, True, 0)

    def _on_drive_event(self, kind, name, detail):
        if kind == "mounted":
            if prefs.get("drives.notify"):
                self.notify_local("Drives", "%s mounted" % name, "Ready to use.", "drive-removable-media",
                                  actions=[("Open", lambda u=detail: services.fire(["sparkfiles", u]))])
            if prefs.get("drives.open_after_mount"):
                services.fire(["sparkfiles", detail])
        elif kind == "failed":
            self.notify_local("Drives", "Could not mount %s" % name, detail[:140], "dialog-error", urgency=2)
        elif kind == "removed" and prefs.get("drives.notify"):
            self.show_toast("%s removed" % name, "It is safe to unplug.", None, 3000)

    def dismiss_notif(self, nid):
        if nid >= self.LOCAL_NID:
            self.notifs = [x for x in self.notifs if x.id != nid]
            self.refresh_notifs()
        else:
            self.notif_srv.close(nid, 2)

    def notify_local(self, app, summary, body, icon=None, actions=None, urgency=1):
        """A notification raised by the shell itself (a drive was mounted, a power action failed ...): same list and pop-up as app notifications."""
        self._local_n = getattr(self, "_local_n", 0) + 1
        n = services.Notification(self.LOCAL_NID + self._local_n, app, icon, summary, body, urgency, -1)
        n.actions = actions or []
        self.on_notify(n)

    def _notif_icon(self, n):
        th = Gtk.IconTheme.get_default()
        if n.icon and (os.path.exists(n.icon) or th.has_icon(n.icon)):
            try:
                if os.path.exists(n.icon):
                    return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(n.icon, 28, 28))
                return Gtk.Image.new_from_icon_name(n.icon, Gtk.IconSize.LARGE_TOOLBAR)
            except GLib.Error:
                pass
        da = Gtk.DrawingArea(); da.set_size_request(30, 30)
        hue = (sum(map(ord, n.app or "?")) * 37) % 360 / 360.0
        import colorsys
        c1 = colorsys.hsv_to_rgb(hue, 0.45, 1.0) + (1,); c2 = colorsys.hsv_to_rgb(hue, 0.65, 0.9) + (1,)
        letter = (n.app or "?")[:1].upper()

        def draw(w, cr):
            ic.squircle(cr, 0, 0, 30, c1, c2, 9)
            gfx.text(cr, letter, 15, 15.5, 13, (1, 1, 1, 1), 700, "c")
            return False
        da.connect("draw", draw)
        return da

    def on_notify(self, n):
        self.notifs = [x for x in self.notifs if x.id != n.id]
        self.notifs.insert(0, n)
        del self.notifs[30:]
        self.refresh_notifs()
        if prefs.get("notifications.popups") and (not self.dnd or n.urgency >= 2):
            self.show_toast(n.summary or n.app, n.body, n.icon, n.timeout)
        return False

    def on_notify_close(self, nid):
        self.notifs = [x for x in self.notifs if x.id != nid]
        self.refresh_notifs()
        return False

    def clear_notifs(self):
        for n in list(self.notifs):
            self.dismiss_notif(n.id)

    def toggle_notifs(self):
        self.show_tray("notifications", self.bell)

    # ------------------------------------------------------------- toast
    def _build_toast(self):
        self.toast = Gtk.Box(spacing=10)
        self.toast.set_size_request(340 - 28, -1)
        self.toast.set_margin_start(14); self.toast.set_margin_end(14); self.toast.set_margin_top(10); self.toast.set_margin_bottom(10)
        self.toast_icon = Ico("bell", 18)
        self.toast_t = label("", "big", width_chars=34); self.toast_b = label("", "muted", width_chars=40)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.pack_start(self.toast_t, False, False, 0); v.pack_start(self.toast_b, False, False, 0)
        self.toast.pack_start(self.toast_icon, False, False, 0); self.toast.pack_start(v, True, True, 0)
        if self.use_popups:
            self.toast_wrap = Popup(self, "dock", 18, Gdk.WindowTypeHint.NOTIFICATION)
            self.toast_wrap.set_accept_focus(False); self.toast_wrap.set_focus_on_map(False)
            self.toast_wrap.add(self.toast)
            self.toast_wrap.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.toast_wrap.connect("button-press-event", lambda *_: (self.toast_wrap.hide(), True)[1])
        else:
            self.toast_wrap = Gtk.EventBox(); self.toast_wrap.add(self.toast); self.toast_wrap.set_visible_window(False)
            self.toast_wrap.connect("button-press-event", lambda *_: (self.toast_wrap.hide(), True)[1])
            self.desk.put(self.toast_wrap, 0, 0)
            self.desk.add_glass(self.toast_wrap, "dock", 18, alpha=0.4)

    def show_toast(self, title, body, icon=None, timeout=-1):
        self.toast_t.set_text(title); self.toast_b.set_text(body.replace("\n", " "))
        if self.use_popups:
            pos = prefs.get("notifications.position")
            mx, my, mw, mh = self.mon
            x = mx + {"top-right": mw - 340 - 16, "top-left": 16}.get(pos, (mw - 340) // 2)
            self.toast_wrap.move(x, my + self.top + 8)
        self.toast_wrap.show_all(); self.relayout()
        if self.toast_src:
            GLib.source_remove(self.toast_src)
        ms = prefs.get("notifications.popup_seconds") * 1000 if timeout in (-1, 0) else max(2000, timeout)
        self.toast_src = GLib.timeout_add(ms, lambda: (self.toast_wrap.hide(), setattr(self, "toast_src", None), False)[2])

    # ------------------------------------------------------ workspaces / dock
    def _build_workspaces(self):
        self.ws_box = Gtk.Box(spacing=6)
        self.ws_box.set_no_show_all(True)                    # visibility follows desktop.show_workspaces, not show_all()
        self.ws_box.set_margin_start(10); self.ws_box.set_margin_end(10); self.ws_box.set_margin_top(6); self.ws_box.set_margin_bottom(6)
        self.desk.put(self.ws_box, 0, 0)
        self.desk.add_glass(self.ws_box, "dock", 16, alpha=0.28)
        if self.wnck:
            for sig in ("active-workspace-changed", "workspace-created", "workspace-destroyed"):
                self.wnck.connect(sig, lambda *_: self.refresh_ws())
        self.refresh_ws()

    def refresh_ws(self):
        for ch in self.ws_box.get_children():
            self.ws_box.remove(ch)
        self.ws_box.pack_start(Ico("sparkle_logo", 20), False, False, 6)
        spaces = self.wnck.get_workspaces() if self.wnck else []
        active = self.wnck.get_active_workspace() if self.wnck else None
        for i, ws in enumerate(spaces or [None]):
            b = Gtk.Button(label=str(i + 1)); b.get_style_context().add_class("pill")
            if ws is None or ws == active:
                b.get_style_context().add_class("active")
            if ws is not None:
                b.connect("clicked", lambda _b, w=ws: w.activate(Gtk.get_current_event_time()))
                b.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
                b.connect("enter-notify-event", lambda w_, e, b=b, ws=ws: self._hover_enter(
                    b, lambda: [x for x in self._windows() if x.get_workspace() == ws or x.is_pinned()], True, "Workspace %d" % (ws.get_number() + 1)) and False)
                b.connect("leave-notify-event", lambda w_, e: self._hover_leave() and False)
            self.ws_box.pack_start(b, False, False, 0)
        if len(spaces) < MAX_WORKSPACES:                    # the window manager caps workspaces at 8: no "+" once that many exist
            add = icon_button("plus", 13, "New workspace", lambda: self.wnck and self.wnck.get_workspace_count() < MAX_WORKSPACES and
                              self.wnck.change_workspace_count(self.wnck.get_workspace_count() + 1), pad=7)
            add.set_sensitive(bool(self.wnck))
            self.ws_box.pack_start(add, False, False, 0)
        for ch in self.ws_box.get_children():
            ch.show_all()
        self.ws_box.set_visible(bool(prefs.get("desktop.show_workspaces")))
        # The glass behind the pill (and its soft shadow) is painted by the desktop, not by the pill: when the pill shrinks the old,
        # wider glass would stay on screen until something else repainted that area. Shrink the box, then repaint the whole desktop.
        self.ws_box.queue_resize()
        self.desk.queue_resize()
        self.desk.queue_draw()
        self.relayout()

    def _build_dock(self):
        self.dock = Gtk.Box(spacing=8)
        self.dock.set_margin_start(14); self.dock.set_margin_end(14); self.dock.set_margin_top(8); self.dock.set_margin_bottom(6)
        if self.use_popups:                           # a real DOCK window: the WM keeps it above apps and reserves its space
            self.dock_win = Popup(self, "dock", 26, Gdk.WindowTypeHint.DOCK, "glitterde-dock")
            self.dock_win.set_accept_focus(False); self.dock_win.set_focus_on_map(False)
            self.dock_win.add(self.dock)
        else:
            self.desk.put(self.dock, 0, 0)
            self.desk.add_glass(self.dock, "dock", 26, alpha=0.34)
        self._dock_idle = None
        self._dock_style = "dock"                      # where self.dock is parented right now; apply_prefs moves it
        if self.wnck:
            for sig in ("window-opened", "window-closed"):
                self.wnck.connect(sig, lambda *_: self._queue_dock())
            self.wnck.connect("active-window-changed", lambda *_: self.dock.queue_draw())     # only the running-dots change: never rebuild for focus
        self.refresh_dock()

    def _queue_dock(self):
        if not self._dock_idle:
            self._dock_idle = GLib.timeout_add(60, self._dock_now)

    def _dock_now(self):
        if getattr(self, "_dock_down", False) and time.time() - self._dock_down_at < 4:
            return True                                  # a button is held on the dock (click or drag): rebuilding now would eat it
        self._dock_idle = None
        self.refresh_dock()
        return False

    def _windows(self):
        if not self.wnck:
            return []
        wins = [w for w in self.wnck.get_windows() if w.get_window_type() == Wnck.WindowType.NORMAL
                and not w.is_skip_tasklist() and (w.get_class_group_name() or "") not in ("glitterde-shell", "glitterde-popup")]
        # The dock buttons' closures keep these objects. When a window closes, libwnck lets go of its own reference; if the LAST
        # reference is then dropped by a dock button being destroyed, libwnck crashes while freeing it (SIGSEGV in libwnck, seen with gdb:
        # the whole shell - panel, dock, desktop - vanished and only the cursor was left). Keeping one reference for the session means
        # that final unref never happens inside a destroy. The cost is a few KB per window ever opened.
        self.__dict__.setdefault("_wnck_keep", set()).update(wins)
        return wins

    @staticmethod
    def _matches(app, win):
        cg, inst = (win.get_class_group_name() or "").lower(), (win.get_class_instance_name() or "").lower()
        wm = (getattr(app, "get_startup_wm_class", lambda: None)() or "").lower()
        exe = os.path.basename(app.get_executable() or "").lower()
        ident = (app.get_id() or "").lower().replace(".desktop", "")
        return any(x and x in (cg, inst) for x in (wm, exe, ident))

    def _sized_image(self, pixbuf, gicon):
        """An icon at EXACTLY dock_px. GTK's own size picking is not reliable: themes without the wanted size, file icons (Icon=/path.png)
        and window icons from libwnck come out at their native size (often 48-128 px), which looked far too big in the panel. So
        the pixbuf is fetched and scaled here, at the monitor's scale factor for a crisp result."""
        px, scale = self.dock_px, max(1, self.desk.get_scale_factor())
        want = px * scale
        pb = pixbuf
        if pb is None and gicon is not None:
            try:
                info = Gtk.IconTheme.get_default().lookup_by_gicon(gicon, want, Gtk.IconLookupFlags.FORCE_SIZE)
                pb = info.load_icon() if info else None
            except GLib.Error:
                pb = None
        if pb is None:
            img = Gtk.Image.new_from_gicon(gicon or Gio.ThemedIcon.new("application-x-executable"), Gtk.IconSize.DIALOG)
            img.set_pixel_size(px)
            return img
        w, h = pb.get_width(), pb.get_height()
        if max(w, h) != want:
            f = want / float(max(w, h))
            pb = pb.scale_simple(max(1, round(w * f)), max(1, round(h * f)), GdkPixbuf.InterpType.BILINEAR)
        img = Gtk.Image.new_from_surface(Gdk.cairo_surface_create_from_pixbuf(pb, scale, None))
        img.set_size_request(px, px)
        return img

    def _dock_item(self, app, wins, win_only=None):
        b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.set_focus_on_click(False)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        if win_only is not None:
            img = self._sized_image(win_only.get_icon(), None); name = win_only.get_name()
        else:
            gi_ = app.get_icon() or Gio.ThemedIcon.new("application-x-executable")
            img = self._sized_image(None, gi_); name = app.get_display_name()
        dot = Gtk.DrawingArea(); dot.set_size_request(self.dock_px, 6)
        running = bool(wins)

        def draw_dot(w, cr):                              # active state is read at draw time, so focus changes need no rebuild
            try:
                act = any(x.is_active() for x in wins)
            except Exception:
                act = False
            cr.set_source_rgba(1, 1, 1, 0.95 if act else 0.55); cr.arc(self.dock_px / 2, 3, 2.2, 0, 6.3)
            cr.fill() if (running and self.dock_ind) else cr.new_path()
            return False
        dot.connect("draw", draw_dot)
        if prefs.get("dock.indicator_position") == "above":
            v.pack_start(dot, False, False, 0); v.pack_start(img, False, False, 0)
        else:
            v.pack_start(img, False, False, 0); v.pack_start(dot, False, False, 0)
        b.add(v); b.set_tooltip_text(name)
        b.fav_id = app.get_id() if (app is not None and win_only is None) else None
        b.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON1_MOTION_MASK)
        b.connect("button-press-event", self._dock_press)
        b.connect("motion-notify-event", self._dock_motion)
        b.connect("button-release-event", self._dock_release)
        b.connect("clicked", lambda *_: self._dock_click_once(app, wins))
        if wins:                                           # running: a hover card with every window replaces the plain tooltip
            b.set_has_tooltip(False)
            b.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            b.connect("enter-notify-event", lambda w_, e: self._hover_enter(b, lambda: [x for x in wins if self._alive(x)], False, name if len(wins) > 1 else "") and False)
            b.connect("leave-notify-event", lambda w_, e: self._hover_leave() and False)
        return b

    # ---- hover card (dock items and workspace pills)
    def _alive(self, win):
        try:
            return win.get_xid() in {x.get_xid() for x in self._windows()}
        except Exception:
            return False

    def _hover_enter(self, anchor, get_wins, below=False, title=""):
        if getattr(self, "_hover", None) is None:
            self._hover = WindowHover(self)
        h = self._hover
        h.keep()
        if getattr(self, "_hover_t", None):
            GLib.source_remove(self._hover_t)
        delay = 60 if h.get_visible() else 350                  # switching between items is instant, the first card waits a moment
        self._hover_t = GLib.timeout_add(delay, lambda: (setattr(self, "_hover_t", None), h.show_for(anchor, get_wins(), below, title), False)[2])
        return True

    def _hover_leave(self):
        if getattr(self, "_hover_t", None):
            GLib.source_remove(self._hover_t); self._hover_t = None
        if getattr(self, "_hover", None) is not None:
            self._hover.leave()
        return True

    # ---- press / drag-to-reorder / click on the dock (pinned items can be dragged into a new order)
    def _dock_press(self, w, ev):
        if ev.button == 1:
            self._dock_down, self._dock_down_at = True, time.time()
            self._drag = {"x": ev.x_root, "y": ev.y_root, "on": False}
        return False

    def _dock_motion(self, w, ev):
        d = getattr(self, "_drag", None)
        if not d or not (ev.state & Gdk.ModifierType.BUTTON1_MASK) or w.fav_id is None:
            return False
        if not d["on"]:
            if math.hypot(ev.x_root - d["x"], ev.y_root - d["y"]) < 8:
                return False
            d["on"] = True
            gw = w.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "grabbing"))
        kids = self.dock.get_children()
        pins = [c for c in kids if getattr(c, "fav_id", None)]
        pt = w.translate_coordinates(self.dock, int(ev.x), int(ev.y))
        if pt is None:
            return True
        horiz = prefs.get("dock.position") == "bottom" or self._dock_style != "dock"
        p = pt[0] if horiz else pt[1]
        before = 0
        for c in pins:
            if c is w:
                continue
            a = c.get_allocation()
            mid = (a.x + a.width / 2) if horiz else (a.y + a.height / 2)
            if mid < p:
                before += 1
        first = kids.index(pins[0]) if pins else 1
        self.dock.reorder_child(w, first + before)
        return True

    def _dock_release(self, w, ev):
        d = getattr(self, "_drag", None)
        self._drag = None
        self._dock_down = False
        if d and d["on"]:
            self._dock_dragged = True                    # the release that ends a drag must not count as a click
            gw = w.get_window()
            if gw is not None:
                gw.set_cursor(None)
            ids = [c.fav_id for c in self.dock.get_children() if getattr(c, "fav_id", None)]
            config.save({"dock": {"favorites": ids}}, "panel.toml")
            by_id = {a.get_id(): a for a in self.favs}
            self.favs = [by_id[i] for i in ids if i in by_id] + [a for a in self.favs if a.get_id() not in ids]
        return False

    def _dock_click_once(self, app, wins):
        if getattr(self, "_dock_dragged", False):
            self._dock_dragged = False
            return
        self._dock_click(app, wins)

    def _dock_click(self, app, wins):
        if getattr(self, "_hover", None) is not None:
            self._hover.hide_now()
        if wins:
            w = wins[0]
            ts = Gtk.get_current_event_time()
            if w.is_active():
                w.minimize()
            else:
                if w.get_workspace() and w.get_workspace() != self.wnck.get_active_workspace():
                    w.get_workspace().activate(ts)
                w.activate(ts)
        elif app:
            self.launch(app)

    def refresh_dock(self, force=False):
        wins = self._windows()
        sig = (tuple(a.get_id() for a in self.favs), tuple(w.get_xid() for w in wins), self.dock_px, self.dock_ind, prefs.get("dock.indicator_position"))
        if sig == getattr(self, "_dock_sig_cur", None) and not force:
            self.dock.queue_draw()
            return                                       # nothing structural changed: keep the buttons (and any click/drag in progress)
        self._dock_sig_cur = sig
        for ch in self.dock.get_children():
            ch.set_has_tooltip(False); ch.set_tooltip_text(None)      # a live tooltip on a destroyed widget crashes GTK
            self.dock.remove(ch)
            GLib.idle_add(lambda c=ch: (c.destroy(), False)[1])
        used = set()
        for app in self.favs:
            mine = [w for w in wins if self._matches(app, w)]
            used.update(id(w) for w in mine)
            self.dock.pack_start(self._dock_item(app, mine), False, False, 0)
        for w in wins:
            if id(w) not in used:
                self.dock.pack_start(self._dock_item(None, [w], win_only=w), False, False, 0)
        self.dock.show_all()
        self._dock_key = None
        self.relayout()

    # ----------------------------------------------------------- launcher
    CAT_ICONS = {"Pinned": "star", "Applications": "grid", "System": "chip", "Development": "terminal", "Graphics": "palette",
                 "Internet": "network", "Multimedia": "music", "Office": "doc", "Games": "cursor", "Accessories": "pin", "Settings": "gear"}

    def _build_launcher(self):
        self._l_size = None
        self._l_busy = False
        self.NAVY = scheme.ink()
        self.launcher = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.launcher.get_style_context().add_class(scheme.panel_class())
        for m in ("top", "bottom", "start", "end"):
            getattr(self.launcher, "set_margin_" + m)(14)
        full_name = GLib.get_real_name()
        full_name = full_name if full_name and full_name != "Unknown" else GLib.get_user_name()
        # KDE-style header: avatar, name, machine
        self.l_head = Gtk.Box(spacing=12); self.l_head.get_style_context().add_class("l-head")
        self.l_head.pack_start(self._l_avatar(full_name), False, False, 0)
        hv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); hv.set_valign(Gtk.Align.CENTER)
        hn = Gtk.Label(label=full_name, xalign=0); hn.get_style_context().add_class("lname")
        hv.pack_start(hn, False, False, 0); hv.pack_start(label(GLib.get_host_name(), "muted"), False, False, 0)
        self.l_head.pack_start(hv, True, True, 0)
        self.launcher.pack_start(self.l_head, False, False, 0)
        # search row
        self.l_entry = Gtk.Entry(); self.l_entry.set_placeholder_text("Search apps...")
        self.l_entry.connect("changed", lambda *_: self._l_filter())
        self.l_entry.connect("activate", self._l_enter)
        top = Gtk.Box(spacing=8); self.l_top = top
        top.pack_start(self._with_search_icon(self.l_entry, (0.165, 0.176, 0.43, 0.8)), True, True, 0)
        vb = Gtk.Button(); vb.set_relief(Gtk.ReliefStyle.NONE); vb.get_style_context().add_class("clear"); vb.set_tooltip_text("Switch between grid and list")
        self.l_view_ico = Ico("grid" if self._l_view_mode() == "list" else "list", 16, self.NAVY, 1.6); vb.add(self.l_view_ico)
        vb.connect("clicked", lambda *_: self._l_toggle_view())
        self.l_vb = vb
        top.pack_start(vb, False, False, 0)
        self.launcher.pack_start(top, False, False, 0)
        # Windows-style section row: "Pinned" ........ [All apps >]
        self.l_sect = Gtk.Box(); self.l_sect.get_style_context().add_class("l-sect")
        self.l_sect_title = Gtk.Label(label="Pinned", xalign=0); self.l_sect_title.get_style_context().add_class("lsect")
        self.l_sect_btn = Gtk.Button(label="All apps  \u203a"); self.l_sect_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.l_sect_btn.connect("clicked", lambda *_: self._l_select("Applications" if self._cat() == "Pinned" else "Pinned"))
        self.l_sect.pack_start(self.l_sect_title, True, True, 0); self.l_sect.pack_end(self.l_sect_btn, False, False, 0)
        self.launcher.pack_start(self.l_sect, False, False, 0)
        body = Gtk.Box(spacing=10)
        self.launcher.pack_start(body, True, True, 0)
        self.cats = Gtk.ListBox(); self.cats.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.cats.set_size_request(150, -1)
        for c in services.CATEGORIES:
            r = Gtk.ListBoxRow(); r.cat = c; r.get_style_context().add_class("catrow")
            h = Gtk.Box(spacing=10); h.pack_start(Ico(self.CAT_ICONS[c], 14, self.NAVY, 1.5), False, False, 0); h.pack_start(label(c), False, False, 0)
            r.add(h); self.cats.add(r)
        self.cats.connect("row-selected", lambda *_: self._l_filter())
        body.pack_start(self.cats, False, False, 0)
        # virtualised grid: only visible cells are drawn, so scrolling hundreds of apps stays cheap
        # columns: icon, name (sort key), app, markup (name), markup (name + description)
        self.l_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, object, str, str)
        self.l_filter = self.l_store.filter_new(); self.l_filter.set_visible_func(self._l_visible)
        self.l_sort = Gtk.TreeModelSort(model=self.l_filter)
        self.l_sort.set_sort_func(1, self._l_cmp); self.l_sort.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.l_view = Gtk.IconView(model=self.l_sort)
        self.l_view.set_pixbuf_column(0); self.l_view.set_markup_column(3)
        self.l_view.set_activate_on_single_click(True); self.l_view.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.l_view.set_row_spacing(4); self.l_view.set_column_spacing(4); self.l_view.set_margin(4)
        for cell in self.l_view.get_cells():
            if isinstance(cell, Gtk.CellRendererText):
                cell.set_property("ellipsize", Pango.EllipsizeMode.END); cell.set_property("alignment", Pango.Alignment.CENTER)
                cell.set_property("xalign", 0.5); cell.set_property("wrap-width", 70); cell.set_property("scale", 0.92)
        self.l_view.connect("item-activated", self._l_activated)
        self.l_view.connect("button-press-event", self._l_press)
        sw = Gtk.ScrolledWindow(); sw.add(self.l_view); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.l_view_box = Gtk.Box(); self.l_view_box.set_halign(Gtk.Align.FILL)
        self.empty_l = self._empty("No apps match your search.")
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); right.pack_start(sw, True, True, 0); right.pack_start(self.empty_l, False, False, 20)
        body.pack_start(right, True, True, 0)
        # footers: Windows-style user + power row, KDE-style tab bar, GNOME-style Pinned / All switch
        self.l_foot_user = Gtk.Box(spacing=10); self.l_foot_user.get_style_context().add_class("l-foot")
        self.l_foot_user.pack_start(self._l_avatar(full_name), False, False, 0)
        un = Gtk.Label(label=full_name, xalign=0); un.get_style_context().add_class("lname")
        self.l_foot_user.pack_start(un, True, True, 0)
        pb = Gtk.Button(); pb.set_relief(Gtk.ReliefStyle.NONE); pb.get_style_context().add_class("clear"); pb.set_tooltip_text("Power")
        pb.add(Ico("power", 16, self.NAVY, 1.6)); pb.connect("clicked", lambda b: (self.close_launcher(), self.power_menu(self.pwr_btn)))
        self.l_foot_user.pack_end(pb, False, False, 0)
        self.launcher.pack_start(self.l_foot_user, False, False, 0)
        self.l_tabs = {}
        self.l_foot_tabs = Gtk.Box(spacing=4); self.l_foot_tabs.set_halign(Gtk.Align.CENTER)
        for key, text, cat in (("fav", "Favorites", "Pinned"), ("apps", "Applications", "Applications"), ("leave", "Leave", None)):
            tb = Gtk.Button(label=text); tb.set_relief(Gtk.ReliefStyle.NONE); tb.get_style_context().add_class("l-tab")
            tb.connect("clicked", (lambda _b, c=cat: self._l_select(c)) if cat else (lambda _b: (self.close_launcher(), self.power_menu(self.pwr_btn))))
            self.l_foot_tabs.pack_start(tb, False, False, 0); self.l_tabs[key] = (tb, cat)
        self.launcher.pack_start(self.l_foot_tabs, False, False, 0)
        self.l_foot_sw = Gtk.Box(spacing=4); self.l_foot_sw.set_halign(Gtk.Align.CENTER)
        for key, text, cat in (("o_fav", "Pinned", "Pinned"), ("o_all", "All apps", "Applications")):
            tb = Gtk.Button(label=text); tb.set_relief(Gtk.ReliefStyle.NONE); tb.get_style_context().add_class("l-tab")
            tb.connect("clicked", lambda _b, c=cat: self._l_select(c))
            self.l_foot_sw.pack_start(tb, False, False, 0); self.l_tabs[key] = (tb, cat)
        self.launcher.pack_start(self.l_foot_sw, False, False, 0)
        if self.use_popups:
            self.launcher_wrap = Popup(self, scheme.app_material("window_light"), 24, Gdk.WindowTypeHint.DROPDOWN_MENU)
            self.launcher_wrap.add(self.launcher)
            self.launcher_wrap.connect("focus-out-event", self._launcher_focus_out)
            self.launcher_wrap.connect("key-press-event", self._popup_key)
        else:                                   # Wayland: no positioned top-levels, draw inside the desktop surface
            self.launcher_wrap = Gtk.Box(); self.launcher_wrap.pack_start(self.launcher, True, True, 0)
            self.desk.put(self.launcher_wrap, 12, 60)
            self.desk.add_glass(self.launcher_wrap, scheme.app_material("window_light"), 24, alpha=0.36)
        self.cats.select_row(self.cats.get_row_at_index(1 if not self.favs else 0))

    def _l_avatar(self, name):
        a = Gtk.Label(label=(name or "?")[:1].upper()); a.get_style_context().add_class("l-avatar")
        a.set_size_request(34, 34); a.set_valign(Gtk.Align.CENTER)
        return a

    def _l_select(self, cat):
        if cat in services.CATEGORIES:
            self.cats.select_row(self.cats.get_row_at_index(services.CATEGORIES.index(cat)))

    def _l_chrome(self):
        """Show the parts of the launcher the current layout has (header, section row, footer, centred search) and style them."""
        e = self._l_eff(); lay = e["lay"]
        ctx = self.launcher.get_style_context()
        for c in ("glitter", "grid", "start", "launchpad", "overview", "kickoff", "list"):
            ctx.remove_class("lay-" + c)
        ctx.add_class("lay-" + lay)
        self.l_head.set_visible(e["head"])
        self.l_sect.set_visible(bool(e["sect"]))
        self.l_foot_user.set_visible(e["foot"] == "user")
        self.l_foot_tabs.set_visible(e["foot"] == "tabs")
        self.l_foot_sw.set_visible(e["foot"] == "switch")
        self.l_top.set_halign(Gtk.Align.CENTER if e["csearch"] else Gtk.Align.FILL)
        self.l_entry.set_size_request(420 if e["csearch"] else -1, -1)
        self.l_vb.set_visible(not e["csearch"] and lay in ("glitter", "grid", "list"))
        self.cats.set_visible(e["cats"])
        self.l_view.set_halign(Gtk.Align.CENTER if e["csearch"] else Gtk.Align.FILL)     # full-screen layouts: the icon block sits in the middle
        self._l_sync_chrome()

    def _l_sync_chrome(self):
        cat = self._cat()
        e = self._l_eff()
        if e["sect"]:
            self.l_sect_title.set_text(e["sect"][0] if cat == "Pinned" else "All apps")
            self.l_sect_btn.set_label(("All apps  \u203a") if cat == "Pinned" else "\u2039  Pinned")
        for key, (tb, c) in self.l_tabs.items():
            sc = tb.get_style_context()
            (sc.add_class if c and c == cat else sc.remove_class)("on")

    @property
    def launcher_visible(self):
        return self.launcher_wrap.get_visible()

    def _cat(self):
        r = self.cats.get_selected_row()
        return r.cat if r else "Applications"

    def _l_eff_base(self):
        """Effective launcher geometry AND structure for the chosen layout (launcher.layout). 'glitter' is the original, driven by the
        individual settings; the others are modelled on other desktops and ignore columns / height / position (but not the list icon size)."""
        lay = prefs.get("launcher.layout")
        mx, my, mw, mh = self.mon
        top, bot = self._inset()
        avail = max(300, mh - top - bot - 16)
        up = (lambda h: my + (top + 8 if bot == 0 else mh - bot - h - 8))      # next to the panel / dock, like the original
        lsz = prefs.get("launcher.list_icon_size")
        d = dict(head=False, sect=None, foot=None, rad=24, desc=False, csearch=False)
        if lay == "glitter" or lay not in ("grid", "launchpad", "overview", "start", "kickoff", "list"):
            cols, size, height = prefs.get("launcher.columns"), prefs.get("launcher.icon_size"), prefs.get("launcher.height")
            cats, cell = prefs.get("launcher.show_categories"), max(84, prefs.get("launcher.icon_size") + 36)
            width = (160 if cats else 0) + cols * (cell + 8) + 36
            x = mx + {"left": 12, "center": (mw - width) // 2, "right": mw - width - 12}[prefs.get("launcher.position")]
            d.update(lay="glitter", cols=cols, size=size, cell=cell, w=width, h=height, cats=cats, xy=(max(0, x), max(0, up(height))), horiz=False)
            return d
        if lay == "grid":                                             # full-width grid with the category list
            size, cell, cats, w, h = 56, 104, True, mw - 24, avail
            cols = max(3, (w - 160 - 36) // (cell + 16)); xy = (mx + 12, up(h))
            horiz = False
        elif lay == "launchpad":                                      # macOS Launchpad: the whole screen, big icons, one centred search pill
            size, cell, cats, h, w = 72, 132, False, avail, mw
            cols = max(3, min(9, (mw - 160) // (cell + 16))); xy = (mx, up(h)); horiz = False
            d.update(rad=0, csearch=True)
        elif lay == "overview":                                       # GNOME Activities: the whole screen, centred search, Pinned / All switch below
            size, cell, cats, h, w = 64, 124, False, avail, mw
            cols = max(3, min(8, (mw - 200) // (cell + 16))); xy = (mx, up(h)); horiz = False
            d.update(rad=0, csearch=True, foot="switch")
        elif lay == "start":                                          # Windows 11 Start: centred panel, Pinned grid + "All apps", user and power at the bottom
            size, cell, cats, h = 40, 92, False, min(avail, 620)
            cols = 6; w = cols * (cell + 16) + 36; xy = (mx + (mw - w) // 2, up(h)); horiz = False
            d.update(rad=18, sect=("Pinned",), foot="user")
        elif lay == "kickoff":                                        # KDE Kickoff: user header, search, described list, tab bar
            size, cell, cats, h = lsz, 360, False, min(avail, 580)
            cols = 1; w = cell + 8 + 36; xy = (mx + 12, up(h)); horiz = True
            d.update(rad=12, head=True, foot="tabs", desc=True)
        else:                                                         # list: one app per row
            size, cell, cats, h = lsz, 270, False, min(avail, 580)
            cols = 1; w = cell + 8 + 36; xy = (mx + 12, up(h)); horiz = True
        d.update(lay=lay, cols=cols, size=size, cell=cell, w=w, h=h, cats=cats, xy=(max(0, xy[0]), max(0, xy[1])), horiz=horiz)
        return d

    def _l_view_mode(self):
        return getattr(self, "_l_view_override", None) or prefs.get("launcher.view")

    def _l_eff(self):
        """Layout geometry plus the grid/list switch: list view shows one app per row, wide layouts get several list columns."""
        e = self._l_eff_base()
        if self._l_view_mode() == "list" and not e["horiz"] and e["lay"] in ("glitter", "grid"):
            cell = 300
            cols = 1 if e["lay"] == "glitter" else max(1, (e["w"] - (160 if e["cats"] else 0) - 36) // (cell + 16))
            e.update(horiz=True, cell=cell, cols=cols, size=prefs.get("launcher.list_icon_size"))
            if e["lay"] == "glitter":
                e["w"] = (160 if e["cats"] else 0) + cell + 16 + 36
                mx, my, mw, mh = self.mon
                e["xy"] = (max(0, mx + {"left": 12, "center": (mw - e["w"]) // 2, "right": mw - e["w"] - 12}[prefs.get("launcher.position")]), e["xy"][1])
        return e

    def _l_toggle_view(self):
        new = "grid" if self._l_view_mode() == "list" else "list"
        self._l_view_override = new
        config.set("launcher", "view", new)
        self.l_view_ico.set_icon("list" if new == "grid" else "grid")
        self._l_size = None
        self._l_apply_layout(); self._l_fill()
        if self.use_popups:
            self.launcher_wrap.resize(*self._l_dim); self.launcher_wrap.move(*self._l_xy)

    def _l_fill(self):
        e = self._l_eff()
        key = (e["size"], e["desc"], e["horiz"])
        if self._l_size == key and len(self.l_store):
            return
        self._l_size = key
        size = e["size"]
        self.l_view.set_markup_column(4 if e["desc"] else 3)
        self.l_store.clear()
        th = Gtk.IconTheme.get_default()
        esc = GLib.markup_escape_text
        for app in self.apps:
            pb = None
            try:
                info = th.lookup_by_gicon(app.get_icon() or Gio.ThemedIcon.new("application-x-executable"), size, Gtk.IconLookupFlags.FORCE_SIZE)
                pb = info.load_icon() if info else None
            except GLib.Error:
                pb = None
            if pb is None:
                try:
                    pb = th.load_icon("application-x-executable", size, Gtk.IconLookupFlags.FORCE_SIZE)
                except GLib.Error:
                    continue
            name = app.get_display_name()
            desc = (app.get_description() or app.get_generic_name() or "").strip().replace("\n", " ")
            desc = desc if len(desc) <= 46 else desc[:45] + "\u2026"
            plain = esc(name)
            full = "<b>%s</b>\n<span size='small' alpha='65%%'>%s</span>" % (plain, esc(desc)) if desc else "<b>%s</b>" % plain
            self.l_store.append([pb, name, app, plain, full])
        self._l_fit_width(e)

    def _l_fit_width(self, e=None):
        """Make the IconView exactly as wide as the popup was sized for (needs items in the model to measure)."""
        e = e or self._l_eff()
        cols, cell = e["cols"], e["cell"]
        self.l_view.set_columns(cols)
        iw = (cell + 8 + 40) // 2 if e["horiz"] else (cell + 16 + 29) // 2
        if len(self.l_store) == 0:
            self.l_view.set_item_width(iw); return
        if not self.l_view.get_visible():
            self.l_view.show()                                       # a hidden widget reports a natural width of 0
        target = cols * (cell + 8 if e["horiz"] else cell + 16)
        for _ in range(3):                                           # measure and correct (the formula depends on theme padding)
            self.l_view.set_item_width(max(30, min(400, iw)))
            err = self.l_view.get_preferred_width()[1] - target
            if abs(err) <= cols:
                break
            iw -= int(round(err / (2.0 * cols)))

    def _l_apply_layout(self):
        e = self._l_eff()
        self._l_lay = e["lay"]
        cols, cell, width, height, show = e["cols"], e["cell"], e["w"], e["h"], e["cats"]
        self.l_view.set_item_orientation(Gtk.Orientation.HORIZONTAL if e["horiz"] else Gtk.Orientation.VERTICAL)
        self.l_view.set_spacing(14 if e["horiz"] else 6)               # space between the icon and its name
        for cr in self.l_view.get_cells():
            if isinstance(cr, Gtk.CellRendererText):
                cr.set_property("wrap-width", cell - (76 if e["horiz"] else 14))
                cr.set_property("xalign", 0.0 if e["horiz"] else 0.5)
                cr.set_property("xpad", 6 if e["horiz"] else 0)
                cr.set_property("alignment", Pango.Alignment.LEFT if e["horiz"] else Pango.Alignment.CENTER)
                cr.set_property("scale", 1.0 if e["horiz"] else 0.92)
            elif isinstance(cr, Gtk.CellRendererPixbuf):
                cr.set_property("xpad", 6 if e["horiz"] else 0)
        # Gtk.IconView applies item-width to BOTH cells, so its natural width is ~2*item_width - 29 per column (vertical items) or
        # 2*item_width - 40 (side-by-side items). Pick the value that gives the column width the popup was sized for.
        self._l_fit_width(e)
        self.launcher.set_size_request(width - 28, height - 28)
        self._l_dim = (width, height)
        self._l_xy = e["xy"]
        self._l_chrome()
        if self.use_popups:
            self.launcher_wrap.oscale = prefs.get("launcher.opacity")
            self.launcher_wrap.base = e["rad"]
        else:
            self.desk.move(self.launcher_wrap, *self._l_xy)

    def _l_match(self, app, cat):
        q = self.l_entry.get_text().strip().lower()
        if q:
            return q in app.get_display_name().lower() or q in (app.get_description() or "").lower() or \
                q in " ".join(app.get_keywords() or []).lower() if hasattr(app, "get_keywords") else q in app.get_display_name().lower()
        return cat == "Applications" or (cat == "Pinned" and app in self.favs) or services.category_of(app) == cat

    def _rank(self, app):
        q = self.l_entry.get_text().strip().lower()
        n = app.get_display_name().lower()
        return (0 if q and n.startswith(q) else 1 if q and q in n else 2, n)

    def _l_visible(self, model, it, _d):
        app = model[it][2]
        return app is not None and self._l_match(app, self._cat())

    def _l_cmp(self, model, a, b, _d):
        ra, rb = self._rank(model[a][2]), self._rank(model[b][2])
        return (ra > rb) - (ra < rb)

    def _l_filter(self):
        if self._l_busy:
            return
        if self.l_entry.get_text().strip() and self._cat() != "Applications":
            self._l_busy = True
            self.cats.select_row(self.cats.get_row_at_index(1))
            self._l_busy = False
        self.l_filter.refilter()
        self.l_sort.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.empty_l.set_visible(len(self.l_sort) == 0)
        if hasattr(self, "l_sect"):
            self._l_sync_chrome()

    def _l_enter(self, *_):
        if len(self.l_sort):
            self.launch(self.l_sort[0][2])

    def _l_activated(self, view, path):
        self.launch(self.l_sort[path][2])

    def _fav_ids(self):
        conf = config.load("panel.toml").get("dock", {}).get("favorites")
        return list(conf) if conf is not None else [a.get_id() for a in self.favs]

    def pin_toggle(self, app):
        ids, aid = self._fav_ids(), app.get_id()
        ids = [i for i in ids if i != aid] if aid in ids else ids + [aid]
        config.save({"dock": {"favorites": ids}}, "panel.toml")

    def _l_press(self, view, ev):
        if ev.button != 3:
            return False
        path = view.get_path_at_pos(int(ev.x), int(ev.y))
        if path is None:
            return False
        app = self.l_sort[path][2]
        pinned = app.get_id() in self._fav_ids()
        GlassMenu([("item", "Open", lambda: self.launch(app)),
                   ("item", "Unpin from dock" if pinned else "Pin to dock", lambda: self.pin_toggle(app))],
                  light=True, theme=self.theme).popup_at(ev.x_root, ev.y_root)
        return True

    def _popup_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.close_launcher(); return True
        if ev.keyval == Gdk.KEY_Down and w.get_focus() is self.l_entry and len(self.l_sort):
            self.l_view.grab_focus(); self.l_view.select_path(Gtk.TreePath.new_first()); return True
        return False

    def _launcher_focus_out(self, *_):
        if time.time() - self._opened_at > 0.6:
            def _close():
                if self.launcher_visible and not self.launcher_wrap.is_active():
                    self._launcher_closed_at = time.time()
                    self.close_launcher()
                return False
            GLib.idle_add(_close)
        return False

    def _l_fix_x(self):
        """The IconView can end up wider than the computed width; place the popup using its real width."""
        if not self.launcher_visible:
            return False
        w = self.launcher_wrap.get_allocated_width()
        lay = getattr(self, "_l_lay", "glitter")
        if lay != "glitter":                                  # presets: keep centred layouts centred and everything on the monitor
            mx, my, mw, mh = self.mon
            x = mx + (mw - w) // 2 if lay in ("launchpad", "overview") else self._l_xy[0]
            x = max(mx, min(x, mx + mw - w))
            if x != self._l_xy[0]:
                self._l_xy = (x, self._l_xy[1]); self.launcher_wrap.move(*self._l_xy)
            return False
        if w > 1:
            pos = prefs.get("launcher.position")
            mx, my, mw, mh = self.mon
            x = mx + {"left": 12, "center": (mw - w) // 2, "right": mw - w - 12}[pos]
            if x != self._l_xy[0] and pos != "left":
                self._l_xy = (max(0, x), self._l_xy[1])
                self.launcher_wrap.move(*self._l_xy)
        return False

    def open_launcher(self, text=None, enter=False):
        if not self.launcher_visible:
            self._opened_at = time.time()
            self.close_tray()
            self._l_apply_layout()
            self._l_fill()
            self.cats.select_row(self.cats.get_row_at_index(1 if not self.favs else 0))
            if self.use_popups:
                self.launcher_wrap.resize(*self._l_dim)
                self.launcher_wrap.move(*self._l_xy)
            self.launcher_wrap.show_all()
            self._l_chrome()
            if self.use_popups:
                self.launcher_wrap.resize(*self._l_dim)          # show_all() re-showed the hidden parts and grew the window: shrink it back
            if self.use_popups:
                GLib.idle_add(self._l_fix_x)
        self.l_entry.grab_focus()
        if text is not None:
            self.l_entry.set_text(text); self.l_entry.set_position(-1)
        self._l_filter()
        if enter:
            self._l_enter()

    def close_launcher(self):
        self.launcher_wrap.hide(); self.l_entry.set_text("")
        self.panel_entry.set_text("")
        self.win.set_focus(None)
        self.desk.queue_draw()

    def toggle_launcher(self):
        if self.launcher_visible:
            self.close_launcher()
        elif time.time() - getattr(self, "_launcher_closed_at", 0) > 0.45:     # the same click that closed it by focus-out must not reopen it
            self.open_launcher()

    def launch(self, app):
        ok, msg = False, ""
        try:
            ok = app.launch([], Gdk.Display.get_default().get_app_launch_context())
        except GLib.Error as e:
            msg = e.message
        if not ok:                               # fall back to running the Exec line directly
            try:
                cmd = (app.get_commandline() or "").split()
                cmd = [c for c in cmd if not (c.startswith("%") and len(c) == 2)]
                GLib.spawn_async(cmd, flags=GLib.SpawnFlags.SEARCH_PATH)
                ok = True
            except Exception as e2:
                msg = msg or str(e2)
        print("glitterde: launch %s -> %s %s" % (app.get_id(), "ok" if ok else "FAILED", msg), file=sys.stderr)
        if not ok:
            self.show_toast("Could not start %s" % app.get_display_name(), msg[:100] or "unknown error")
        self.close_launcher()

    # ------------------------------------------------------- ticking / panel
    def tick_clock_once(self):
        now = time.localtime()
        tfmt = "%H:%M" if prefs.get("panel.clock_24h") else "%-I:%M %p"
        txt = time.strftime(tfmt, now)
        if prefs.get("panel.clock_date"):
            txt = time.strftime("%a, %b %-d  ", now) + txt
        self.clock_lbl.set_text(txt)
        self.big_clock.set_text(time.strftime(tfmt, now))
        self.big_date.set_text(time.strftime("%A, %B %-d", now))
        up = int(self.stats.uptime()); h, m = up // 3600, up % 3600 // 60
        self.uptime_lbl.set_text("Up %dh %02dm" % (h, m) if h else "Up %d min" % m)
        return now

    def tick_clock(self):
        now = self.tick_clock_once()
        GLib.timeout_add_seconds(61 - now.tm_sec, lambda: (self.tick_clock(), False)[1])

    def tick_slow(self):
        b = services.battery()
        self.bat_btn.set_visible(b is not None and prefs.get("panel.tray_battery"))
        if b:
            self.bat_ico.pct = b[0] / 100.0; self.bat_ico.queue_draw()
            self.bat_lbl.set_text("%d%%" % b[0])
        net_open = "network" in self.enabled
        if net_open:                                # don't poll hardware for widgets nobody can see
            self.refresh_network(); self._poll_ssid()
        else:
            self._update_net_icon()
        if self.bt_present:
            if "bluetooth" in self.enabled:
                self._poll_bt()
        elif not getattr(self, "_bt_drawn", False):
            self._bt_drawn = True; self.refresh_bt()
        return True

    # ------------------------------------------------------------- demo
    def _demo_data(self):
        for i, (app, ic_, s, b, mins) in enumerate((("Discord", "", "Discord", "Ruby: hey! you free later?", 2),
                                                   ("Music", "", "Now playing", "Better Together - Starset", 12),
                                                   ("System", "", "Screenshot saved", "Saved to Pictures", 60))):
            n = services.Notification(100 + i, app, ic_, s, b, 1, -1); n.time = time.time() - mins * 60
            self.notifs.append(n)
        self.refresh_notifs(); self.refresh_phone()

    # ------------------------------------------------------------ layout
    def _on_alloc(self, w, a):
        if (a.width, a.height) != (self.W, self.H):
            self.W, self.H = a.width, a.height
            if not getattr(self, "_mon_timer", None):
                self._mons_seen = tuple(gfx.gdk_monitors())
                self._mon_timer = GLib.timeout_add_seconds(2, self._watch_monitors)
            GLib.idle_add(self.relayout, True)

    def relayout(self, force=False):
        """Coalesce layout requests: many handlers ask for one, but a layout pass is only needed once per main-loop turn."""
        if force:
            return self._relayout_now()
        if not getattr(self, "_rl_pending", False):
            self._rl_pending = True
            GLib.idle_add(self._relayout_idle)
        return False

    def _relayout_idle(self):
        self._rl_pending = False
        self._relayout_now()
        return False

    def _refresh_mon(self):
        """Primary monitor rectangle (panel, dock, widgets, launcher and popups live there). True if it changed."""
        m = gfx.gdk_monitors()[0]
        if m[2] <= 0 or m[3] <= 0 or m[0] + m[2] > self.W + 1 or m[1] + m[3] > self.H + 1:
            m = (0, 0, self.W, self.H)
        changed = m != self.mon
        self.mon = m
        return changed

    def _watch_monitors(self):
        """Hot-plug: the WM republishes the layout; follow it (new wallpaper split, panel moves to the primary monitor)."""
        a = self.args
        if a.as_desktop and not a.size:                          # the desktop window must follow a resolution change (xrandr), or the new area stays empty
            scr = Gdk.Screen.get_default()
            sw, sh = scr.get_width(), scr.get_height()
            if sw > 0 and sh > 0 and (sw, sh) != (self.W, self.H):
                self.win.move(0, 0); self.win.resize(sw, sh)
        cur = tuple(gfx.gdk_monitors())
        if cur != getattr(self, "_mons_seen", cur):
            self.desk.reload(self.theme)
            self.relayout(True)
        self._mons_seen = cur
        return True

    def _inset(self):
        """(top, bottom) space taken by the panel."""
        return (0, self.PH) if prefs.get("panel.position") == "bottom" else (self.PH, 0)

    def _place_dock(self, W, H, top, bot):
        pos = prefs.get("dock.position")
        self.dock.set_orientation(Gtk.Orientation.HORIZONTAL if pos == "bottom" else Gtk.Orientation.VERTICAL)
        w, h = self.dock.get_preferred_width()[1], self.dock.get_preferred_height()[1]
        mx, my, W, H = self.mon                 # the dock sits on the primary monitor
        if pos == "bottom":
            x, y = mx + (W - w) // 2, my + H - bot - h - 10
        else:
            x, y = mx + (10 if pos == "left" else W - w - 10), my + top + (H - top - bot - h) // 2
        key = (x, y, w, h, pos)
        if getattr(self, "_dock_key", None) != key:
            self._dock_key = key
            self.dock_win.resize(1, 1)
            self.dock_win.move(x, y)
        if not self.dock_win.get_visible():
            self.dock_win.move(x, y)
            self.dock_win.show_all()

    def _relayout_now(self):
        if self._refresh_mon():
            self.__dict__.pop("_last_pos", None); self._dock_key = None
        mx, my, W, H = self.mon                 # everything below is laid out inside the primary monitor
        PH = self.PH
        if W < 200:
            return False
        top, bot = self._inset()
        self.top = top
        moved = []
        last = self.__dict__.setdefault("_last_pos", {})

        def put(w, x, y):
            if last.get(id(w)) != (x, y):
                last[id(w)] = (x, y)
                self.desk.move(w, x, y)
                moved.append(w)
        ctx = self.panel.get_style_context()
        (ctx.remove_class("panel") if bot else ctx.add_class("panel"))
        (ctx.add_class("panel-bottom") if bot else ctx.remove_class("panel-bottom"))
        self.panel.set_size_request(W, PH)
        put(self.panel, mx, my + (0 if not bot else H - PH))
        put(self.icons_fixed, mx + 10, my + top + 8)

        def clamp(key, w):
            a = w.get_preferred_size()[1]
            x, y = self.wpos[key]
            return int(max(0, min(self.W - a.width, x))), int(max(top, min(self.H - bot - a.height, y)))
        x, y0 = mx + W - 286, my + top + 10
        col_y = y0
        limit = my + H - bot - 14
        items = []
        for key in ("clock", "system", "network", "bluetooth", "phone", "media", "quick"):
            w = self.widgets[key]
            if key not in self.enabled:
                continue
            a = w.get_preferred_size()[1]
            if key in self.wpos:
                hx, hy = clamp(key, w)
            else:
                if col_y + a.height > limit and col_y > y0:
                    x -= 286; col_y = y0
                hx, hy = x, col_y
                col_y += a.height + self.GAP_Y
            items.append((key, hx, hy, a.width, a.height))
        ws_h = self.ws_box.get_preferred_height()[1]
        put(self.ws_box, mx + 16, my + H - bot - ws_h - 12)
        resolved = self._resolve_widgets(items, y0, limit, 286)
        for key, (rx, ry) in resolved.items():
            put(self.widgets[key], rx, ry)
        if os.environ.get("GLITTERDE_DEBUG"):
            sizes = {i[0]: (i[3], i[4]) for i in items}
            print("widgets:", " ".join("%s=%d,%d,%dx%d" % ((k,) + resolved[k] + sizes[k]) for k in sorted(resolved)), file=sys.stderr)
        if self._dock_style != "dock":
            pass                                       # applications live in the panel: no dock window to place
        elif self.use_popups:
            self._place_dock(W, H, top, bot)
        else:
            self.dock.set_size_request(-1, -1)
            dw, dh = self.dock.get_preferred_width()[1], self.dock.get_preferred_height()[1]
            put(self.dock, mx + (W - dw) // 2, my + H - bot - dh - 12)
            put(self.toast_wrap, mx + (W - 340) // 2, my + top + 8)
        rows = max(1, (max(H, 600) - PH - 150 - 20) // int(88 * {"small": 0.8, "medium": 1.0, "large": 1.3}[prefs.get("desktop.icon_size")]))
        if rows != self._rows:
            self.rebuild_icons()
        if moved:
            self.desk.queue_draw()
        return False

    # -------------------------------------------------------------- window
    def _wire_window(self):
        a = self.args
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0)
        geo = mon.get_geometry()
        scr = Gdk.Screen.get_default()
        if a.as_desktop and not a.size:                  # the desktop window covers every monitor; the panel etc. sit on the primary one
            w, h = scr.get_width(), scr.get_height()
            geo = type("G", (), {"x": 0, "y": 0, "width": w, "height": h})
        else:
            w, h = (int(v) for v in a.size.lower().split("x")) if a.size else (geo.width, geo.height)
        self.win.set_default_size(w, h)
        if a.windowed:
            self.win.set_decorated(True)
        elif "Wayland" in type(display).__name__:
            self.win.maximize()                  # apps must be able to stack above us (no layer-shell in Weston)
        else:
            if a.as_desktop:
                self.win.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
            self.win.move(geo.x, geo.y)
            self.win.fullscreen() if not a.as_desktop else self.win.resize(w, h)
        self.win.connect("destroy", Gtk.main_quit)
        self.win.connect("key-press-event", self.on_key)
        self.win.add_events(Gdk.EventMask.PROPERTY_CHANGE_MASK)
        self.win.connect("property-notify-event", self._prop_event)
        from . import config
        self._mons = []
        for name in ("settings.toml", "panel.toml"):
            m = Gio.File.new_for_path(config.path(name)).monitor_file(Gio.FileMonitorFlags.NONE, None)
            m.connect("changed", lambda *_: self._queue_reload())
            self._mons.append(m)
        self._rl = None
        self._apply_accent()
        self.win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.win.connect("button-press-event", self._focus_me)
        self.win.set_accept_focus(True); self.win.set_focus_on_map(True)

    def _prop_event(self, win, ev):
        """The WM bumps _GLITTER_LAUNCHER on our window when Super is tapped."""
        try:
            if ev.atom.name() == "_GLITTER_LAUNCHER":
                self.toggle_launcher()          # the WM focuses the popup when it maps
            elif ev.atom.name() == "_GLITTER_WINMENU":
                self.show_window_menu()         # the WM saw a click on a titlebar icon
            elif ev.atom.name() == "_GLITTER_DOCKAPP":
                self.dock_activate()            # Super+1..9
        except Exception as e:
            print("glitterde: property event:", e, file=sys.stderr)
        return False

    def dock_activate(self):
        """Super+N: bring up the N-th dock item (pinned apps first, then other running windows), or launch it if it is not running."""
        try:
            rd = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
            n = int(open(os.path.join(rd, "glitterde-dockapp-%d" % os.getuid())).read().strip())
        except (OSError, ValueError):
            return
        wins = self._windows()
        items, used = [], set()
        for app in self.favs:
            mine = [w for w in wins if self._matches(app, w)]
            used.update(id(w) for w in mine)
            items.append((app, mine))
        items += [(None, [w]) for w in wins if id(w) not in used]
        if not 1 <= n <= len(items):
            return
        app, mine = items[n - 1]
        if not mine:
            if app:
                self.launch(app)
            return
        ts = Gtk.get_current_event_time()
        w = next((x for x in mine if x.is_active()), None) or mine[0]
        if w.get_workspace() is not None and self.wnck and w.get_workspace() != self.wnck.get_active_workspace():
            w.get_workspace().activate(ts)
        if w.is_minimized():
            w.unminimize(ts)
        w.activate(ts)

    def show_window_menu(self):
        """The menu behind a titlebar's app icon: restore/maximise, minimise, always on top, workspaces, close.
        The WM leaves "window-xid x y" in a small file and bumps _GLITTER_WINMENU on the shell window."""
        if not self.wnck:
            return
        try:
            rd = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
            xid, x, y = (int(v) for v in open(os.path.join(rd, "glitterde-winmenu-%d" % os.getuid())).read().split())
        except (OSError, ValueError):
            return
        self.wnck.force_update()
        w = Wnck.Window.get(xid)
        if w is None:
            return
        ts = Gtk.get_current_event_time()
        spaces = self.wnck.get_workspaces()
        maxed = w.is_maximized()
        items = [("itemi", "maximize", "Restore" if maxed else "Maximise", lambda: w.unmaximize() if maxed else w.maximize(),
                  bool(w.get_actions() & Wnck.WindowActions.MAXIMIZE) or maxed),
                 ("itemi", "minimize", "Minimise", lambda: w.minimize()),
                 ("sep",),
                 ("check", "Always on top", w.is_above(), lambda: w.unmake_above() if w.is_above() else w.make_above()),
                 ("check", "Show on all workspaces", w.is_pinned(), lambda: w.unpin() if w.is_pinned() else w.pin())]
        if len(spaces) > 1:
            cur = w.get_workspace()
            items.append(("sub", "windows", "Move to workspace",
                          [("check", ws.get_name() or "Workspace %d" % (i + 1), ws is cur and not w.is_pinned(), lambda ws=ws: w.move_to_workspace(ws))
                           for i, ws in enumerate(spaces)]))
        items += [("sep",), ("itemi", "close", "Close", lambda: w.close(ts), True, "Alt+F4")]
        GlassMenu(items, theme=self.theme, min_width=220).popup_at(x, y)

    def _queue_reload(self):
        if self._rl:
            GLib.source_remove(self._rl)
        self._rl = GLib.timeout_add(300, self._reload_settings)

    def _reload_settings(self):
        self._rl = None
        from .tokens import active
        self.theme = active()
        self.desk.reload(self.theme)
        self.favs = services.default_favorites(self.apps, self._configured_favorites())
        self._load_widget_state()
        self._apply_accent()
        self.apply_prefs()
        self._dock_key = None
        self.refresh_dock()
        self.rebuild_icons()
        self.apply_widgets()
        for pw in (getattr(self, "launcher_wrap", None), getattr(self, "toast_wrap", None), self.tray):
            if isinstance(pw, Popup):
                pw.queue_draw()
        return False

    def _apply_accent(self):
        r, g, b, _ = self.theme.color("accent.primary")
        css = ("button.pill.active { background-color: rgba(%d,%d,%d,0.92); } "
               "button.tile.on { background-color: rgba(%d,%d,%d,0.55); }" % ((r * 255, g * 255, b * 255) * 2)).encode()
        if not hasattr(self, "_acc"):
            self._acc = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self._acc, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10 + 2)
        self._acc.load_from_data(css)

    def _focus_me(self, win, ev):
        gw = win.get_window()
        if gw and not win.is_active() and ev.window is gw:
            gw.focus(ev.time)
        if ev.window is gw and ev.y > self.PH:             # a press that no widget consumed = the bare desktop
            if ev.button == 1:
                self._select(None)
                self.close_tray()
            elif ev.button == 3:
                self._desk_menu(ev)
        return False

    def on_key(self, win, ev):
        k = ev.keyval
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and k in (Gdk.KEY_q, Gdk.KEY_Q) and not self.args.no_quit_key:
            Gtk.main_quit(); return True
        if k == Gdk.KEY_Escape:
            if self.launcher_visible:
                self.close_launcher(); return True
            return False
        if k in (Gdk.KEY_Super_L, Gdk.KEY_Super_R):
            self.toggle_launcher(); return True
        focus = win.get_focus()
        if not self.launcher_visible and not isinstance(focus, Gtk.Entry) and not ctrl and \
                not (ev.state & Gdk.ModifierType.MOD1_MASK) and ev.string and ev.string.isprintable() and ev.string.strip():
            self.open_launcher(ev.string); return True
        if self.launcher_visible and k == Gdk.KEY_Down and focus is self.l_entry:
            ch = self.flow.get_child_at_index(0)
            if ch:
                ch.grab_focus()
            return True
        return False


def run(args, theme):
    shell = LiveShell(args, theme)
    Gtk.main()
    return 0
