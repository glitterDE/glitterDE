"""glitter-wm: reparenting X11 window manager with glass frames (python-xlib + cairo).

Frames are painted from the same blurred wallpaper the shell uses (pseudo-transparency),
rounded with the X Shape extension. EWMH is implemented far enough for libwnck (dock,
workspace pills) and for GTK/Qt applications to behave.
"""
import os
import select
import subprocess
import sys
import time

import array
import cairo
import gi
from Xlib import X, XK, Xatom, Xutil, display, error, protocol
from Xlib.ext import shape

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

from . import config, gfx, scheme
from . import icons as ic
from . import settings_model as prefs
from .tokens import active as active_theme

BW, TH, RAD = 5, 38, 16            # frame border, titlebar height, corner radius
PANEL_H = 38                        # shell panel height: windows are kept below it
MINW, MINH = 220, 120
STICKY = 0xFFFFFFFF
NDESK = 4
MATERIAL = {"sparkfiles": "window_light", "sparksettings": "window_glass", "sparkterm": "window_dark", "sparkcode": "window_light"}
ICON_PX = 20                         # app icon in the titlebar
VECTOR_ICONS = {"sparkfiles": "app_files", "sparkterm": "app_terminal", "sparksettings": "app_settings", "sparkcode": "app_code"}   # our own apps: drawn, not loaded
# Titlebar layouts (window.layout). side None = follow window.button_side. order is left-to-right on the side the buttons sit.
# style: glyph (hover highlight) | wide (full-height hover blocks) | dots (traffic lights) | circle (always-on round buttons) | ubuntu (orange close)
LAYOUTS = {
    "glitter":    dict(side=None,    order=("min", "max", "close"), style="glyph",  title="left",   icon=True),
    "windows":    dict(side="right", order=("min", "max", "close"), style="wide",   title="left",   icon=True),
    "macos":      dict(side="left",  order=("close", "min", "max"), style="dots",   title="center", icon=False),
    "gnome":      dict(side="right", order=("min", "max", "close"), style="circle", title="center", icon=False),
    "kde":        dict(side="right", order=("min", "max", "close"), style="glyph",  title="center", icon=True, shape="circle"),
    "elementary": dict(side="left",  order=("close", "max"),        style="circle", title="center", icon=False),
    "ubuntu":     dict(side="left",  order=("close", "min", "max"), style="ubuntu", title="left",   icon=False),
    "chromeos":   dict(side="right", order=("min", "max", "close"), style="glyph",  title="left",   icon=False),
    "minimal":    dict(side="right", order=("close",),              style="glyph",  title="left",   icon=True),
}
STYLE_GEOM = {"glyph": (21, 26, 13, 13), "wide": (23, 46, 23, 19), "dots": (20, 22, 9, 9), "circle": (22, 28, 12, 12), "ubuntu": (20, 28, 12, 12)}   # first cx, step, half-w, half-h
GLYPH = dict(left_ptr=68, fleur=52, top=138, bottom=16, left=70, right=96,
             tl=134, tr=136, bl=12, br=14)


class Client:
    def __init__(self, win, frame):
        self.win, self.frame = win, frame
        self.x = self.y = 0                  # frame position (root coords)
        self.w = self.h = 100                # client size
        self.title = ""
        self.cls = ""
        self.desktop = 0
        self.minimized = self.maximized = self.fullscreen = False
        self.saved = None
        self.is_desktop = False
        self.decorated = True
        self.hover = None
        self.focused = False
        self.mat = "window_glass"
        self.bw = BW
        self.handles = {}
        self.is_dock = False
        self.csd = False
        self.grabbed = False                 # passive click grab installed (only on windows that are not the focused top window)
        self.minw = self.minh = 0            # WM_NORMAL_HINTS minimum client size
        self._cp = None                      # last compositor hints written (skip identical rewrites)
        self.ext = (0, 0, 0, 0)              # _GTK_FRAME_EXTENTS (left, right, top, bottom): the transparent shadow a CSD window draws around itself
        self.unframed_type = False           # menus, docks, tooltips ...: never framed, whatever hints they carry
        self.above = False                   # _NET_WM_STATE_ABOVE ("always on top")
        self.icon_surf = None                # the app icon shown in the titlebar (cairo surface) ...
        self.icon_ready = False              # ... and whether it has been looked up yet

    @property
    def fw(self):
        return self.w + (2 * self.bw if self.decorated else 0)

    @property
    def fh(self):
        return self.h + ((TH + self.bw) if self.decorated else 0)

    @property
    def off(self):
        return (self.bw, TH) if self.decorated else (0, 0)


class WM:
    def __init__(self):
        self.d = display.Display()
        self.screen = self.d.screen()
        self.root = self.screen.root
        self.W, self.H = self.screen.width_in_pixels, self.screen.height_in_pixels
        self.mons = self._monitors()
        self.areas = []
        self.clients, self.by_win, self.by_frame, self.stack = [], {}, {}, []
        self.cur = 0
        self.focus_c = None
        self.drag = None
        self.cascade = 0
        self.shape_evt = getattr(self.d.extension_event, "ShapeNotify", None)
        self.ndesk = prefs.get("workspaces.count")
        self.by_handle = {}
        self.d.set_error_handler(self._on_error)
        self.A = {n: self.d.intern_atom(n) for n in (
            "WM_PROTOCOLS WM_DELETE_WINDOW WM_STATE WM_TAKE_FOCUS WM_CHANGE_STATE UTF8_STRING _NET_SUPPORTED "
            "_NET_SUPPORTING_WM_CHECK _NET_WM_NAME _NET_CLIENT_LIST _NET_CLIENT_LIST_STACKING _NET_ACTIVE_WINDOW "
            "_NET_NUMBER_OF_DESKTOPS _NET_CURRENT_DESKTOP _NET_DESKTOP_NAMES _NET_DESKTOP_GEOMETRY _NET_DESKTOP_VIEWPORT "
            "_NET_WORKAREA _NET_WM_DESKTOP _NET_WM_STATE _NET_WM_STATE_HIDDEN _NET_WM_STATE_FULLSCREEN "
            "_NET_WM_STATE_MAXIMIZED_VERT _NET_WM_STATE_MAXIMIZED_HORZ _NET_CLOSE_WINDOW _NET_FRAME_EXTENTS "
            "_NET_WM_WINDOW_TYPE _NET_WM_WINDOW_TYPE_DESKTOP _NET_WM_WINDOW_TYPE_DOCK _NET_WM_WINDOW_TYPE_NORMAL "
            "_NET_WM_WINDOW_TYPE_DIALOG _NET_WM_WINDOW_TYPE_UTILITY _NET_WM_WINDOW_TYPE_SPLASH _NET_WM_WINDOW_TYPE_MENU "
            "_NET_WM_WINDOW_TYPE_TOOLTIP _NET_WM_WINDOW_TYPE_NOTIFICATION _NET_WM_WINDOW_TYPE_POPUP_MENU "
            "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU _NET_WM_WINDOW_TYPE_COMBO _NET_WM_WINDOW_TYPE_DND _NET_WM_WINDOW_TYPE_TOOLBAR "
            "_NET_WM_STATE_SKIP_TASKBAR _GLITTER_LAUNCHER _GLITTER_MONITORS _NET_MOVERESIZE_WINDOW _NET_WM_MOVERESIZE \n            _GLITTER_BLUR _GLITTER_SHADOW _GLITTER_RADIUS _GLITTER_BODY_Y _GLITTER_OPAQUE WM_WINDOW_ROLE _MOTIF_WM_HINTS _GTK_FRAME_EXTENTS _NET_WM_STATE_ABOVE _NET_WM_ICON _GLITTER_WINMENU _GLITTER_DOCKAPP").split()}
        A = self.A
        self.unframed_types = {A[k] for k in A if k.startswith("_NET_WM_WINDOW_TYPE_") and k.split("TYPE_")[1] in
                               ("DOCK", "SPLASH", "MENU", "TOOLTIP", "NOTIFICATION", "POPUP_MENU", "DROPDOWN_MENU",
                                "COMBO", "DND", "TOOLBAR")}
        # become the WM (fails with BadAccess if another one runs)
        self._fail = None
        self.d.set_error_handler(self._catch_redirect)
        self.root.change_attributes(event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask |
                                    X.PropertyChangeMask | X.ButtonPressMask | X.KeyPressMask | X.KeyReleaseMask)
        self.d.sync()
        if self._fail:
            sys.exit("glitter-wm: another window manager is already running")
        self.d.set_error_handler(self._on_error)

        self.load_theme()
        self._detect_comp()
        self._cursors()
        self._ewmh_init()
        self._grab_keys()
        self._settings_mtime = self._mtime()
        self._adopt_existing()

    # --------------------------------------------------------------- setup
    def _catch_redirect(self, err, req):
        if isinstance(err, error.BadAccess):
            self._fail = err

    def _on_error(self, err, req):
        if not isinstance(err, (error.BadWindow, error.BadMatch, error.BadAccess, error.BadDrawable, error.BadValue)):
            print("glitter-wm: X error", err, file=sys.stderr)

    def load_theme(self):
        self.theme = active_theme()
        self.load_prefs()
        wp = self.theme.wallpaper()
        mt = os.path.getmtime(wp) if os.path.exists(wp) else 0
        wall = gfx.cover_monitors(gfx.load_image(wp), self.W, self.H, self.mons)
        self.glass = gfx.Glass(self.theme, wall, 1, cache_key=(wp, mt, self.W, self.H, prefs.get("desktop.wallpaper_fit"), tuple(self.mons)))
        self.accent = self.theme.color("accent.primary")

    def _detect_comp(self):
        """Compositor present? Then frames get a 32-bit (alpha) visual and per-window blur/shadow hints."""
        owner = self.d.get_selection_owner(self.d.intern_atom("_NET_WM_CM_S%d" % self.d.get_default_screen()))
        self.comp = bool(owner) and owner != X.NONE and not os.environ.get("GLITTERDE_NO_COMP")
        self.vis32 = self.cmap32 = None
        if self.comp:
            for dp in self.screen.allowed_depths:
                if dp.depth == 32 and dp.visuals:
                    self.vis32 = dp.visuals[0]
                    break
            if self.vis32 is None:
                self.comp = False
            else:
                self.cmap32 = self.root.create_colormap(self.vis32.visual_id, X.AllocNone)
        print("glitter-wm: cursor theme=%s size=%s" % (config.load().get("cursor", {}).get("theme", "(default)"), config.load().get("cursor", {}).get("size", "(default)")), file=sys.stderr)
        print("glitter-wm: compositor %s" % ("detected: translucent glass frames" if self.comp else "not found: pseudo-glass frames"),
              file=sys.stderr)

    def _comp_props(self, c):
        if not self.comp or c.is_desktop:
            return
        full = c.maximized or c.fullscreen
        pop = c.cls in ("glitterde-popup", "glitterde-menu", "glitterde-dock")
        blur = self.blur_lvl if ((c.cls in MATERIAL or pop) and not c.fullscreen) else 0
        pr = {"glitterde-dock": 26, "glitterde-menu": 14, "glitterde-popup": 20}
        rad = 0 if full else (RAD if c.decorated else (self.theme.rad(pr[c.cls]) if pop else 0))
        shadow = int(self.shadow_on and not full and (c.decorated or pop))
        opaque = (1 if scheme.is_dark() else 2) if c.fullscreen else 0       # fullscreen glass must not show the desktop behind it
        vals = (int(blur), shadow, int(rad), int(c.off[1]), opaque)      # last: where the client area starts inside the frame (the compositor's resize hold)
        if vals == c._cp:
            return                                   # nothing changed: every drag/resize step used to rewrite these (3 round trips)
        c._cp = vals
        for atom, v in zip(("_GLITTER_BLUR", "_GLITTER_SHADOW", "_GLITTER_RADIUS", "_GLITTER_BODY_Y", "_GLITTER_OPAQUE"), vals):
            c.frame.change_property(self.A[atom], Xatom.CARDINAL, 32, [v])

    def _client_material(self, win):
        """Material the app declared in WM_WINDOW_ROLE ("glitter-material:<name>"); None if it didn't."""
        try:
            pr = win.get_full_property(self.A["WM_WINDOW_ROLE"], 0)
            if pr is not None and pr.value:
                role = bytes(pr.value).decode("utf-8", "ignore").strip("\0 ")
                if role.startswith("glitter-material:"):
                    name = role.split(":", 1)[1]
                    if name in self.theme.pal["materials"]:
                        return name
        except Exception:
            pass
        return None

    def load_prefs(self):
        global TH, RAD
        TH = prefs.get("window.titlebar_height")
        RAD = self.theme.rad(16)
        self.layout = LAYOUTS.get(prefs.get("window.layout"), LAYOUTS["glitter"])
        self.btn_side, self.btn_size = self.layout["side"] or prefs.get("window.button_side"), prefs.get("window.button_size")
        self.btn_shape, self.inactive = self.layout.get("shape") or prefs.get("window.button_shape"), prefs.get("window.inactive_opacity")
        self.shadow_on, self.ffm = prefs.get("window.shadow"), prefs.get("window.focus_follows_mouse")
        self.margin = prefs.get("window.edge_margin")
        self.blur_lvl = ({"light": 1, "normal": 2, "strong": 3}.get(self.theme.blur_level, 2)
                         if (self.theme.blur and self.theme.transparency) else 0)
        self.update_area()
        n = prefs.get("workspaces.count")
        if getattr(self, "_ewmh_done", False) and n != self.ndesk:
            self.set_ndesk(n)

    def _monitors(self):
        """[(x, y, w, h), ...] primary first. Uses RandR and Xinerama and keeps whichever lists MORE monitors
        (nested servers such as Xephyr report a single RandR monitor but two Xinerama screens)."""
        rr, xin = [], []
        try:
            r = self.root.xrandr_get_monitors()
            rr = [(bool(m.primary), m.x, m.y, m.width_in_pixels, m.height_in_pixels) for m in r.monitors]
        except Exception:
            pass
        try:
            if self.d.has_extension("XINERAMA"):
                xin = [(i == 0, sc.x, sc.y, sc.width, sc.height) for i, sc in enumerate(self.d.xinerama_query_screens().screens)]
        except Exception:
            pass
        mons = rr if len(rr) >= len(xin) else xin
        mons = [m for m in mons if m[3] > 0 and m[4] > 0]
        if not mons:
            return [(0, 0, self.W, self.H)]
        mons.sort(key=lambda m: not m[0])                    # primary first
        return [m[1:] for m in mons]

    def _publish_monitors(self):
        """Shell and apps read this (GDK cannot see Xinerama-only layouts): _GLITTER_MONITORS = x y w h per monitor, primary first."""
        flat = [v for m in self.mons for v in m]
        self._prop(self.root, "_GLITTER_MONITORS", Xatom.CARDINAL, 32, flat)

    def area_at(self, x, y):
        """Work area (x1, y1, x2, y2) of the monitor containing the point (nearest one if it is off-screen)."""
        best, bd = None, None
        for i, (mx, my, mw, mh) in enumerate(self.mons):
            a = self.areas[i] if i < len(self.areas) else (mx, my, mx + mw, my + mh)
            dx = max(mx - x, 0, x - (mx + mw - 1)); dy = max(my - y, 0, y - (my + mh - 1))
            d = dx * dx + dy * dy
            if bd is None or d < bd:
                best, bd = a, d
        return best

    def _pointer(self):
        try:
            q = self.root.query_pointer()
            return q.root_x, q.root_y
        except Exception:
            return self.W // 2, self.H // 2

    def update_area(self):
        """Usable area per monitor. The panel and dock live on the PRIMARY monitor only; other monitors are fully usable."""
        ph = prefs.get("panel.height")
        px, py, pw, phh = self.mons[0]
        self.ax1, self.ay1, self.ax2, self.ay2 = px, py, px + pw, py + phh
        if prefs.get("panel.position") == "bottom":
            self.ay2 = py + phh - ph
        else:
            self.ay1 = py + ph
        if prefs.get("dock.reserve_space"):
            for c in self.clients:
                if c.cls == "glitterde-dock" and not c.minimized:
                    if not (px <= c.x + c.w / 2 < px + pw and py <= c.y + c.h / 2 < py + phh):
                        continue                                   # a dock on another monitor does not shrink the primary area
                    if c.w > c.h and c.y > py + phh / 2:
                        self.ay2 = min(self.ay2, c.y - 4)
                    elif c.x < px + pw / 3:
                        self.ax1 = max(self.ax1, c.x + c.w + 4)
                    elif c.x > px + pw * 2 / 3:
                        self.ax2 = min(self.ax2, c.x - 4)
        self.areas = [(self.ax1, self.ay1, self.ax2, self.ay2)] + [(x, y, x + w, y + h) for x, y, w, h in self.mons[1:]]
        if getattr(self, "_ewmh_done", False):
            self._prop(self.root, "_NET_WORKAREA", Xatom.CARDINAL, 32,
                       [self.ax1, self.ay1, self.ax2 - self.ax1, self.ay2 - self.ay1] * self.ndesk)
            for c in self.clients:                       # keep maximised windows inside the (possibly changed) area
                if c.maximized and not c.fullscreen:
                    self._fit_max(c)
                    self.apply_geometry(c, repaint=False)

    def _fit_max(self, c):
        """Place a maximised window on the monitor it is on."""
        ax1, ay1, ax2, ay2 = self.area_at(c.x + c.fw // 2, c.y + 10)
        c.x, c.y = ax1, ay1
        if c.decorated:
            c.w, c.h = ax2 - ax1 - 2 * c.bw, ay2 - ay1 - TH - c.bw
        else:                                              # client-side decorated: the client IS the whole window
            c.w, c.h = ax2 - ax1, ay2 - ay1

    def _check_monitors(self):
        """Hot-plug: notice a changed monitor layout, rescale the root properties and rescue windows left off-screen."""
        sc = self.root.get_geometry()
        mons = self._monitors()
        if mons == self.mons and (sc.width, sc.height) == (self.W, self.H):
            return
        self.W, self.H, self.mons = sc.width, sc.height, mons
        print("glitter-wm: monitors now %s" % (mons,), file=sys.stderr)
        self.update_area()
        self._prop(self.root, "_NET_DESKTOP_GEOMETRY", Xatom.CARDINAL, 32, [self.W, self.H])
        self._publish_monitors()
        for c in self.clients:
            if c.is_desktop:
                c.w, c.h = self.W, self.H
                self.apply_geometry(c, repaint=False)
            elif c.fullscreen:                                 # stays fullscreen: cover the monitor it was on (or the primary one if that is gone)
                cx, cy = c.x + c.w // 2, c.y + 10
                mx, my, mw, mh = next((m for m in self.mons if m[0] <= cx < m[0] + m[2] and m[1] <= cy < m[1] + m[3]), self.mons[0])
                c.x, c.y, c.w, c.h = mx, my, mw, mh
                self.apply_geometry(c, repaint=False)
            elif not c.is_dock:
                cx, cy = c.x + c.fw // 2, c.y + 10
                if not any(mx <= cx < mx + mw and my <= cy < my + mh for mx, my, mw, mh in self.mons):
                    ax1, ay1, ax2, ay2 = self.areas[0]
                    c.x, c.y = ax1 + 40, ay1 + 40
                    self.apply_geometry(c, repaint=False)
        self.d.flush()

    def set_ndesk(self, n, save=False):
        n = max(1, min(8, int(n)))
        self.ndesk = n
        for c in self.clients:
            if c.desktop != STICKY and c.desktop >= n:
                self.move_to_desktop(c, n - 1)
        if self.cur >= n:
            self.switch_desktop(n - 1)
        A = self.A
        self._prop(self.root, "_NET_NUMBER_OF_DESKTOPS", Xatom.CARDINAL, 32, [n])
        self._prop(self.root, "_NET_DESKTOP_NAMES", A["UTF8_STRING"], 8, b"\0".join(str(i + 1).encode() for i in range(n)) + b"\0")
        self._prop(self.root, "_NET_WORKAREA", Xatom.CARDINAL, 32, [self.ax1, self.ay1, self.ax2 - self.ax1, self.ay2 - self.ay1] * n)
        if save:
            prefs.set("workspaces.count", n)
        self.d.flush()

    def reload_all(self):
        self.update_area()
        for c in self.clients:
            if c.decorated and not c.is_desktop:
                self.apply_geometry(c, repaint=False)
            self._comp_props(c)
            self._paint(c)
        self.d.flush()

    def _mtime(self):
        try:
            return os.path.getmtime(config.path())
        except OSError:
            return 0

    XC_NAMES = dict(left_ptr="left_ptr", fleur="fleur", top="top_side", bottom="bottom_side", left="left_side",
                    right="right_side", tl="top_left_corner", tr="top_right_corner", bl="bottom_left_corner",
                    br="bottom_right_corner")

    def _xcursor_load(self):
        """Load cursors from the user's Xcursor theme (cursor.theme / cursor.size in settings)."""
        import ctypes
        import ctypes.util
        try:
            xc = ctypes.CDLL(ctypes.util.find_library("Xcursor") or "libXcursor.so.1")
            x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        except OSError:
            return False
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xc.XcursorLibraryLoadCursor.restype = ctypes.c_ulong
        xc.XcursorLibraryLoadCursor.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        xc.XcursorSetTheme.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        xc.XcursorSetDefaultSize.argtypes = [ctypes.c_void_p, ctypes.c_int]
        if getattr(self, "_xdpy", None) is None:
            self._xdpy = x11.XOpenDisplay(None)       # cursors live as long as this extra connection does
        if not self._xdpy:
            return False
        cfg = config.load().get("cursor", {})
        theme = config.cursor_theme()
        if theme:
            xc.XcursorSetTheme(self._xdpy, theme.encode())
        if cfg.get("size"):
            xc.XcursorSetDefaultSize(self._xdpy, int(cfg["size"]))
        new = {}
        for key, name in self.XC_NAMES.items():
            cid = xc.XcursorLibraryLoadCursor(self._xdpy, name.encode())
            if not cid:
                return False
            new[key] = self.d.create_resource_object("cursor", cid)
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XSync(self._xdpy, 0)                      # make sure the server knows the cursors before we use their ids
        self.cur_map = new
        return True

    def _cursors(self):
        if not getattr(self, "cur_map", None):
            self.cur_map = {}
        ok = self._xcursor_load()
        print("glitter-wm: cursors via %s" % ("Xcursor theme" if ok else "classic X cursor font (libXcursor unavailable)"), file=sys.stderr)
        if not ok:                                     # fall back to the classic X cursor font
            font = self.d.open_font("cursor")
            for k, g in GLYPH.items():
                self.cur_map[k] = font.create_glyph_cursor(font, g, g + 1, (0, 0, 0), (0xffff, 0xffff, 0xffff))
        self.root.change_attributes(cursor=self.cur_map["left_ptr"])
        for c in self.clients:
            c.frame.change_attributes(cursor=self.cur_map["left_ptr"])
            for name, hw in c.handles.items():
                hw.change_attributes(cursor=self.cur_map[self.HCUR[name]])
        self.d.flush()

    def _prop(self, win, atom, typ, fmt, data):
        win.change_property(self.A[atom] if isinstance(atom, str) else atom, typ, fmt, data)

    def _ewmh_init(self):
        A = self.A
        self.check = self.root.create_window(-10, -10, 1, 1, 0, self.screen.root_depth)
        for w in (self.root, self.check):
            self._prop(w, "_NET_SUPPORTING_WM_CHECK", Xatom.WINDOW, 32, [self.check.id])
        self._prop(self.check, "_NET_WM_NAME", A["UTF8_STRING"], 8, b"glitter-wm")
        # _GTK_FRAME_EXTENTS must be advertised too: without it GTK3 apps assume a WM that cannot handle client-side shadows and draw
        # a thick opaque 5px border ("solid-csd") instead of a soft, transparent one
        sup = [A[k] for k in A if k.startswith("_NET_") or k == "_GTK_FRAME_EXTENTS"]
        self._prop(self.root, "_NET_SUPPORTED", Xatom.ATOM, 32, sup)
        self._prop(self.root, "_NET_NUMBER_OF_DESKTOPS", Xatom.CARDINAL, 32, [self.ndesk])
        self._prop(self.root, "_NET_DESKTOP_NAMES", A["UTF8_STRING"], 8, b"\0".join(str(i + 1).encode() for i in range(self.ndesk)) + b"\0")
        self._prop(self.root, "_NET_DESKTOP_GEOMETRY", Xatom.CARDINAL, 32, [self.W, self.H])
        self._prop(self.root, "_NET_DESKTOP_VIEWPORT", Xatom.CARDINAL, 32, [0, 0])
        self._prop(self.root, "_NET_WORKAREA", Xatom.CARDINAL, 32, [self.ax1, self.ay1, self.ax2 - self.ax1, self.ay2 - self.ay1] * self.ndesk)
        self._ewmh_done = True
        self._publish_monitors()
        self._publish()

    def _publish(self):
        """Write the EWMH root properties, but only those that changed (every click used to rewrite all four, which wakes libwnck in
        the shell, which then rebuilds its window lists)."""
        last = self.__dict__.setdefault("_pub", {})
        for name, typ, val in (("_NET_CURRENT_DESKTOP", Xatom.CARDINAL, [self.cur]),
                               ("_NET_CLIENT_LIST", Xatom.WINDOW, [c.win.id for c in self.clients]),
                               ("_NET_CLIENT_LIST_STACKING", Xatom.WINDOW, [c.win.id for c in self.stack]),
                               ("_NET_ACTIVE_WINDOW", Xatom.WINDOW, [self.focus_c.win.id if self.focus_c else 0])):
            if last.get(name) != val:
                last[name] = val
                self._prop(self.root, name, typ, 32, val)
        self.d.flush()

    # Super+<key> shortcuts: key name -> action tag. A bare tap of Super still opens the launcher (on RELEASE, so Super+D is not
    # preceded by a launcher flash).
    SUPER_KEYS = {"d": "desktop", "e": "files", "t": "terminal", "i": "settings", "q": "close", "m": "minimize", "Up": "maximize",
                  "Down": "restore", "Tab": "cycle", "Left": "ws-prev", "Right": "ws-next", **{str(n): "dock-%d" % n for n in range(1, 10)}}

    def _detect_super_mask(self):
        """The modifier bit the Super (Windows) keys are really bound to. Mod4 is the usual answer, but custom xmodmap/XKB setups put
        Super on Mod3 or Mod5, and then grabs on a hard-coded Mod4 never fire (a bare Super tap would still open the launcher)."""
        try:
            supers = {self.d.keysym_to_keycode(XK.string_to_keysym(n)) for n in ("Super_L", "Super_R")} - {0}
            for i, kcs in enumerate(self.d.get_modifier_mapping()):
                if i >= 3 and supers & set(kcs):                      # rows 0-2 are Shift / Lock / Control
                    return 1 << i
        except Exception:
            pass
        return X.Mod4Mask

    def _grab_keys(self):
        self.keys = {}
        self.super_mask = self._detect_super_mask()
        mods = [0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask]
        for name, base, tag in (("F4", X.Mod1Mask, "close"), ("Tab", X.Mod1Mask, "cycle"), ("Super_L", 0, "launcher"),
                                ("Super_R", 0, "launcher"), ("Print", 0, "shot-menu"),
                                *[(k, self.super_mask, "super-" + t) for k, t in self.SUPER_KEYS.items()]):
            kc = self.d.keysym_to_keycode(XK.string_to_keysym(name))
            if not kc:
                continue
            for m in mods:
                self.root.grab_key(kc, base | m, True, X.GrabModeAsync, X.GrabModeAsync)
                self.keys[(kc, base)] = tag

    def _adopt_existing(self):
        for w in self.root.query_tree().children:
            try:
                a = w.get_attributes()
            except error.BadWindow:
                continue
            if a.override_redirect or a.map_state != X.IsViewable or w.id == self.check.id:
                continue
            self.manage(w, existing=True)

    # ----------------------------------------------------------- properties
    def _text(self, win, *atoms):
        for a in atoms:
            try:
                p = win.get_full_property(a, X.AnyPropertyType)
            except error.BadWindow:
                return ""
            if p and p.value:
                v = p.value
                return v.decode("utf-8", "replace") if isinstance(v, bytes) else bytes(v).decode("latin1")
        return ""

    def _client_decorates_itself(self, win):
        """True for client-side-decorated windows: no WM titlebar wanted (MOTIF hints / _GTK_FRAME_EXTENTS)."""
        try:
            p = win.get_full_property(self.A["_MOTIF_WM_HINTS"], X.AnyPropertyType)
            if p and len(p.value) >= 3 and (p.value[0] & 2) and p.value[2] == 0:
                return True
            g = win.get_full_property(self.A["_GTK_FRAME_EXTENTS"], X.AnyPropertyType)
            return bool(g and len(g.value) == 4)
        except error.BadWindow:
            return False

    def _types(self, win):
        try:
            p = win.get_full_property(self.A["_NET_WM_WINDOW_TYPE"], Xatom.ATOM)
        except error.BadWindow:
            return []
        return list(p.value) if p else []

    def _delete_supported(self, win):
        try:
            p = win.get_full_property(self.A["WM_PROTOCOLS"], Xatom.ATOM)
        except error.BadWindow:
            return False
        return bool(p and self.A["WM_DELETE_WINDOW"] in list(p.value))

    # ------------------------------------------------- CSD shadows, dynamic decoration
    def _frame_extents(self, win):
        """_GTK_FRAME_EXTENTS (left, right, top, bottom): the invisible shadow border a client-side-decorated window draws."""
        try:
            g = win.get_full_property(self.A["_GTK_FRAME_EXTENTS"], X.AnyPropertyType)
            if g and len(g.value) == 4:
                return tuple(max(0, min(400, int(v))) for v in g.value)
        except error.BadWindow:
            pass
        return (0, 0, 0, 0)

    def _min_y(self, c, area_top):
        """Smallest frame y: the VISIBLE top edge of the window may touch the screen-edge gap. A CSD window with a big shadow has that much
        transparent space above its real edge, which must be allowed to hang over the panel (it is see-through and click-through anyway)."""
        return area_top + self.margin - (c.ext[2] if c.csd else 0)

    def _recheck_decor(self, c):
        """A client changed _MOTIF_WM_HINTS / _GTK_FRAME_EXTENTS after it was mapped (Chrome does this when it switches between its own
        titlebar and the system one): update the shadow insets and, if it now draws (or no longer draws) its own titlebar, re-frame it."""
        if c.is_desktop or c.is_dock or c.unframed_type or c.fullscreen:
            return
        csd = self._client_decorates_itself(c.win)
        c.ext = self._frame_extents(c.win) if csd else (0, 0, 0, 0)
        if csd != c.csd:
            self._redecorate(c)

    def _redecorate(self, c):
        win, desk, mini, mx, saved = c.win, c.desktop, c.minimized, c.maximized, c.saved
        self.unmanage(c)                         # gives the window back to the root at its current place ...
        n = self.manage(win, existing=True)      # ... and frames it again with the new decoration state
        if n is None:
            return
        n.ignore_unmap += 1                      # the client was reparented twice while mapped: swallow the second Unmap as well
        if desk != n.desktop:
            self.move_to_desktop(n, desk)
        if mini:
            self.minimize(n)
        if mx and not n.maximized:
            self.toggle_max(n)
            n.saved = saved or n.saved

    # --------------------------------------------------------------- titlebar icon
    def _tb(self, c):
        """Titlebar geometry for the active layout: button centres, icon centre, title x / anchor / max width, button hit sizes."""
        L, side = self.layout, self.btn_side
        first, step, hw, hh = STYLE_GEOM[L["style"]]
        fw, order = c.fw, L["order"]
        if side == "left":
            btns = {n: first + i * step for i, n in enumerate(order)}
            zl, zr = btns[order[-1]] + hw + 10, 8
        else:
            btns = {n: fw - first - i * step for i, n in enumerate(reversed(order))}
            zl, zr = 8, fw - (btns[order[0]] - hw - 10)
        icon = None
        if L["icon"]:
            icon = zl + 14
            zl += 32
        else:
            zl += 8 if side == "left" else 6
        if L["title"] == "center":
            free_l, free_r = zl, fw - zr
            center = (free_l + free_r) / 2.0
            return dict(btns=btns, icon=icon, tx=center, anchor="c", tw=max(40, min(free_r - free_l, 2 * min(center - free_l, free_r - center))), hw=hw, hh=hh)
        return dict(btns=btns, icon=icon, tx=zl + 4, anchor="l", tw=max(40, fw - zl - zr - 8), hw=hw, hh=hh)

    def _icon_cx(self, c):
        return self._tb(c)["icon"]

    def _pixbuf_to_surface(self, pb):
        w, h, rs, n = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
        src = pb.get_pixels()
        out = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                i = y * rs + x * n
                a = src[i + 3] if n == 4 else 255
                o = (y * w + x) * 4
                out[o] = src[i + 2] * a // 255; out[o + 1] = src[i + 1] * a // 255; out[o + 2] = src[i] * a // 255; out[o + 3] = a
        return cairo.ImageSurface.create_for_data(out, cairo.FORMAT_ARGB32, w, h, w * 4)

    def _wm_icon(self, win):
        """The icon the client published in _NET_WM_ICON (best size for the titlebar), as a cairo surface; None if it has none."""
        try:
            p = win.get_full_property(self.A["_NET_WM_ICON"], X.AnyPropertyType)
        except error.BadWindow:
            return None
        if not p or len(p.value) < 3:
            return None
        v, n, i, icons = p.value, len(p.value), 0, []
        while i + 2 <= n:
            w, h = int(v[i]), int(v[i + 1])
            if w <= 0 or h <= 0 or w > 1024 or h > 1024 or i + 2 + w * h > n:
                break
            icons.append((w, h, i + 2)); i += 2 + w * h
        if not icons:
            return None
        big = [t for t in icons if max(t[0], t[1]) >= ICON_PX]
        w, h, off = min(big, key=lambda t: t[0] * t[1]) if big else max(icons, key=lambda t: t[0] * t[1])
        raw = bytearray(array.array("I", [int(x) & 0xFFFFFFFF for x in v[off:off + w * h]]).tobytes())
        if sys.byteorder == "little":                    # ARGB words are B,G,R,A in memory: GdkPixbuf wants R,G,B,A
            raw[0::4], raw[2::4] = raw[2::4], raw[0::4]
        else:
            raw = bytearray(b for px in range(w * h) for b in (raw[px * 4 + 1], raw[px * 4 + 2], raw[px * 4 + 3], raw[px * 4]))
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(raw)), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
        k = ICON_PX / float(max(w, h))
        if k != 1:
            pb = pb.scale_simple(max(1, int(round(w * k))), max(1, int(round(h * k))), GdkPixbuf.InterpType.HYPER)
        return self._pixbuf_to_surface(pb)

    def _app_icon_names(self):
        """{lower-case WM_CLASS / desktop-id / executable: icon name or file} from the installed .desktop files (built once)."""
        m = getattr(self, "_app_icons", None)
        if m is None:
            m = {}
            try:
                from gi.repository import Gio
                for a in Gio.AppInfo.get_all():
                    gi_ = a.get_icon()
                    if gi_ is None:
                        continue
                    name = gi_.get_names()[0] if hasattr(gi_, "get_names") and gi_.get_names() else \
                        (gi_.get_file().get_path() if hasattr(gi_, "get_file") else None)
                    if not name:
                        continue
                    keys = set()
                    swc = a.get_startup_wm_class() if hasattr(a, "get_startup_wm_class") else None
                    if swc:
                        keys.add(swc.lower())
                    aid = (a.get_id() or "").lower()
                    aid = aid[:-8] if aid.endswith(".desktop") else aid
                    keys.update({aid, aid.split(".")[-1]})
                    ex = a.get_executable()
                    if ex:
                        keys.add(os.path.basename(ex).lower())
                    for k in keys:
                        if k:
                            m.setdefault(k, name)
            except Exception:
                pass
            self._app_icons = m
        return m

    def _find_icon_file(self, name):
        import glob
        if os.path.isabs(name):
            return name if os.path.exists(name) else None
        bases = [config.BUNDLED_ICONS, os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons")]
        bases += [os.path.join(d, "icons") for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
        theme = ""
        try:
            kf = GLib.KeyFile(); kf.load_from_file(os.path.join(GLib.get_user_config_dir(), "gtk-3.0", "settings.ini"), GLib.KeyFileFlags.NONE)
            theme = kf.get_string("Settings", "gtk-icon-theme-name")
        except GLib.Error:
            pass
        found = []
        for b in bases:
            for th in ([theme] if theme else []) + ["hicolor"]:
                for pat in ("%s/%s/*/apps/%s.*", "%s/%s/apps/*/%s.*"):
                    for f in glob.glob(pat % (b, th, name)):
                        if f.endswith((".png", ".svg", ".xpm")):
                            found.append(f)
            for f in glob.glob("%s/../pixmaps/%s.*" % (b, name)):
                if f.endswith((".png", ".svg", ".xpm")):
                    found.append(f)
        if not found:
            return None

        def rank(f):
            import re
            m = re.search(r"/(\d+)(?:x\d+)?/", f)
            sz = int(m.group(1)) if m else (512 if "scalable" in f or f.endswith(".svg") else 48)
            return (sz < ICON_PX * 2, abs(sz - ICON_PX * 2), f.endswith(".svg"))
        return min(found, key=rank)

    def _ensure_icon(self, c):
        if c.icon_ready:
            return
        c.icon_ready = True
        c.icon_surf = None
        try:
            c.icon_surf = self._wm_icon(c.win)
            if c.icon_surf is None and c.cls not in VECTOR_ICONS:
                nm = self._app_icon_names()
                wc = c.win.get_wm_class() or ("", "")
                name = next((nm[k] for k in (c.cls, (wc[0] or "").lower()) if k and k in nm), None)
                path = self._find_icon_file(name) if name else None
                if path:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, ICON_PX, ICON_PX, True)
                    c.icon_surf = self._pixbuf_to_surface(pb)
        except Exception as e:                           # an icon is cosmetic: never let it break painting
            if os.environ.get("GLITTERDE_DEBUG"):
                print("glitter-wm: icon for %s: %s" % (c.cls, e), file=sys.stderr)

    def _draw_app_icon(self, cr, c, cx, cy, alpha):
        self._ensure_icon(c)
        if c.icon_surf is not None:
            w, h = c.icon_surf.get_width(), c.icon_surf.get_height()
            cr.set_source_surface(c.icon_surf, int(round(cx - w / 2.0)), int(round(cy - h / 2.0)))
            cr.paint_with_alpha(alpha)
        elif c.cls in VECTOR_ICONS:
            cr.push_group(); getattr(ic, VECTOR_ICONS[c.cls])(cr, cx, cy, ICON_PX); cr.pop_group_to_source(); cr.paint_with_alpha(alpha)
        else:                                            # nothing better known: a pastel tile with the app's initial
            cr.push_group()
            ic.squircle(cr, cx - ICON_PX / 2, cy - ICON_PX / 2, ICON_PX, (0.72, 0.62, 1, 1), (0.50, 0.44, 0.95, 1), ICON_PX * 0.30)
            ch = ((c.title or c.cls or "?").strip()[:1] or "?").upper()
            gfx.text(cr, ch, cx, cy + 0.5, ICON_PX * 0.62, (1, 1, 1, 1), 700, "c")
            cr.pop_group_to_source(); cr.paint_with_alpha(alpha)

    def _open_winmenu(self, c, x_root, y_root):
        """Ask the shell (which owns the toolkit) to pop up the window menu for this client: payload in a small file, then a property bump."""
        sh = next((x for x in self.clients if x.is_desktop), None)
        if sh is None:
            return
        try:
            rd = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
            with open(os.path.join(rd, "glitterde-winmenu-%d" % os.getuid()), "w") as f:
                f.write("%d %d %d\n" % (c.win.id, x_root, y_root))
        except OSError:
            return
        self._menu_n = getattr(self, "_menu_n", 0) + 1
        sh.win.change_property(self.A["_GLITTER_WINMENU"], Xatom.CARDINAL, 32, [self._menu_n])
        self.d.flush()

    # --------------------------------------------------------------- manage
    def manage(self, win, existing=False):
        if win.id in self.by_win:
            return self.by_win[win.id]
        try:
            g = win.get_geometry()
        except error.BadWindow:
            return None
        types = self._types(win)
        try:                                              # read the initial state NOW: later steps rewrite _NET_WM_STATE
            _st = win.get_full_property(self.A["_NET_WM_STATE"], Xatom.ATOM)
            want_fs = _st is not None and self.A["_NET_WM_STATE_FULLSCREEN"] in list(_st.value)
        except error.BadWindow:
            want_fs = False
        c = Client(win, None)
        c.is_desktop = self.A["_NET_WM_WINDOW_TYPE_DESKTOP"] in types
        c.focusable = not any(t in (self.A["_NET_WM_WINDOW_TYPE_NOTIFICATION"], self.A["_NET_WM_WINDOW_TYPE_TOOLTIP"],
                                    self.A["_NET_WM_WINDOW_TYPE_DOCK"], self.A["_NET_WM_WINDOW_TYPE_DND"]) for t in types)
        c.is_dock = self.A["_NET_WM_WINDOW_TYPE_DOCK"] in types
        typed_unframed = any(t in self.unframed_types for t in types)
        c.unframed_type = typed_unframed or c.is_dock
        c.decorated = not c.is_desktop and not typed_unframed
        if c.decorated and self._client_decorates_itself(win):     # CSD / frameless apps draw their own titlebar
            c.decorated, c.csd = False, True
        c.ext = self._frame_extents(win) if c.csd else (0, 0, 0, 0)
        c.title = self._text(win, self.A["_NET_WM_NAME"], Xatom.WM_NAME)
        try:                                              # honour the client's minimum size when resizing
            nh = win.get_wm_normal_hints()
            if nh and (nh.flags & Xutil.PMinSize):
                c.minw, c.minh = max(0, nh.min_width), max(0, nh.min_height)
        except Exception:
            pass
        cls = win.get_wm_class()
        c.cls = (cls[1] if cls else "").lower()
        c.mat = self._client_material(win) or MATERIAL.get(c.cls, "window_glass")
        if os.environ.get("GLITTERDE_DEBUG"):
            print("glitter-wm: %s material=%s" % (c.cls, c.mat), file=sys.stderr)
        c.bw = 0 if ((self.comp and c.decorated) or c.csd) else BW      # compositor: seamless window, no border ring (CSD windows have no WM border at all)
        c.w, c.h = max(g.width, 40), max(g.height, 30)
        if c.is_desktop:
            c.w, c.h, c.x, c.y = self.W, self.H, 0, 0
            c.desktop = STICKY
        else:
            c.desktop = self.cur
            if c.decorated or c.csd:
                ax1, ay1, ax2, ay2 = self.area_at(*self._pointer())
                aw, ah = ax2 - ax1, ay2 - ay1
                c.w, c.h = min(c.w, aw - 2 * c.bw), min(c.h, ah - TH * (1 if c.decorated else 0) - c.bw)
                try:
                    hints = win.get_wm_normal_hints()
                except Exception:
                    hints = None
                wants = bool(hints and (hints.flags & (Xutil.USPosition | Xutil.PPosition)) and (g.x or g.y))
                if existing or wants:                                  # honour the position the app asked for (yad --posx/--posy ...)
                    off_y = TH if c.decorated else 0
                    wx1, wy1, wx2, wy2 = self.area_at(g.x, g.y)
                    c.x = max(wx1, min(wx2 - c.fw, g.x - c.bw))
                    c.y = max(self._min_y(c, wy1), min(wy2 - 60, g.y - off_y))
                else:
                    off = (self.cascade % 6) * 28
                    self.cascade += 1
                    c.x = max(ax1, ax1 + (aw - c.fw) // 2 + off - 60)
                    c.y = max(self._min_y(c, ay1), ay1 + (ah - c.fh) // 2 + off - 30)
            else:
                c.x, c.y = g.x, g.y
        fw, fh = c.fw, c.fh
        mask = (X.SubstructureRedirectMask | X.SubstructureNotifyMask | X.ButtonPressMask | X.ButtonReleaseMask |
                X.PointerMotionMask | X.ExposureMask | X.LeaveWindowMask | X.EnterWindowMask)
        if self.comp and not c.is_desktop:
            c.frame = self.root.create_window(c.x, c.y, fw, fh, 0, 32, X.InputOutput, self.vis32.visual_id,
                                             background_pixel=0, border_pixel=0, colormap=self.cmap32, event_mask=mask)
        else:
            c.frame = self.root.create_window(c.x, c.y, fw, fh, 0, self.screen.root_depth, X.InputOutput,
                                             **({"background_pixel": self.screen.black_pixel} if c.decorated else {"background_pixmap": X.NONE}),
                                             event_mask=mask)
        c.depth = 32 if (self.comp and not c.is_desktop) else self.screen.root_depth
        self._comp_props(c)
        win.change_save_set(X.SetModeInsert)
        win.change_attributes(event_mask=X.PropertyChangeMask | X.StructureNotifyMask | X.FocusChangeMask)
        ox, oy = c.off
        c.ignore_unmap = 1 if existing else 0
        win.reparent(c.frame, ox, oy)
        win.configure(border_width=0)
        if (c.w, c.h) != (g.width, g.height):           # the window asked for more than fits: resize the REAL window, not only our bookkeeping
            win.configure(width=c.w, height=c.h)        # (before, the client stayed bigger than its frame and was told a smaller size)
        # click-to-focus: sync-grab button presses, replay them to the client. Only on windows that are NOT the focused top
        # window (focus() removes the grab again): clicks and scrolling inside the active window never wait for the WM.
        if c.focusable:
            self._grab_click(c)
        self.clients.append(c); self.stack.append(c)
        self.by_win[win.id] = c; self.by_frame[c.frame.id] = c
        self._shape(c)
        if not c.decorated and not c.is_desktop and not self.comp:
            try:
                c.win.shape_select_input(1)
            except Exception:
                pass
        if c.decorated and c.bw == 0:
            self._make_handles(c)
        self._send_configure(c)
        self._prop(win, "_NET_WM_DESKTOP", Xatom.CARDINAL, 32, [c.desktop])
        self._prop(win, "_NET_FRAME_EXTENTS", Xatom.CARDINAL, 32, [c.bw, c.bw, TH, c.bw] if c.decorated else [0, 0, 0, 0])
        self._set_wm_state(c, 1)
        c.frame.map(); win.map()
        if c.csd:
            self._send_configure(c)                      # CSD clients compute drag start coordinates from the position they were last told
        if c.cls == "glitterde-dock":
            c.is_dock = True
            self.update_area()
        if c.is_desktop:
            c.frame.configure(stack_mode=X.Below)
        else:
            c.frame.configure(stack_mode=X.Above)
        self._paint(c)
        if os.environ.get('GLITTERDE_DEBUG'):
            print('manage %s cls=%s frame=(%d,%d) client=%dx%d bw=%d decorated=%s csd=%s hint-pos=%s area=(%d,%d,%d,%d)' % (c.title[:20], c.cls, c.x, c.y, c.w, c.h, c.bw, c.decorated, c.csd, (g.x, g.y), self.ax1, self.ay1, self.ax2, self.ay2), file=sys.stderr)
        if c.focusable:
            self.focus(c, raise_=not c.is_desktop)
        if want_fs and not c.is_desktop:                  # GTK sets _NET_WM_STATE_FULLSCREEN before mapping (e.g. the welcome flow)
            self.set_fullscreen(c, True)
        self._publish()
        return c

    def unmanage(self, c, destroyed=False):
        if c not in self.clients:
            return
        self.clients.remove(c)
        if c in self.stack:
            self.stack.remove(c)
        self.by_win.pop(c.win.id, None); self.by_frame.pop(c.frame.id, None)
        if getattr(self, "_raised_top", None) is c:
            self._raised_top = None
        if not destroyed:
            try:
                self._ungrab_click(c)
                c.win.reparent(self.root, c.x + c.off[0], c.y + c.off[1])
                c.win.change_save_set(X.SetModeDelete)
                self._set_wm_state(c, 0)
            except error.BadWindow:
                pass
        was_dock = c.cls == "glitterde-dock"
        for hw in list(c.handles.values()):
            self.by_handle.pop(hw.id, None)
        try:
            c.frame.destroy()
        except error.BadWindow:
            pass
        if self.focus_c is c:
            self.focus_c = None
            nxt = [x for x in reversed(self.stack) if self._visible(x) and not x.is_desktop and not x.minimized]
            self.focus(nxt[0] if nxt else next((x for x in self.clients if x.is_desktop), None))
        if was_dock:
            self.update_area()
        self._publish()

    def _visible(self, c):
        return c.desktop in (self.cur, STICKY)

    def _set_wm_state(self, c, state):
        self._prop(c.win, "WM_STATE", self.A["WM_STATE"], 32, [state, 0])
        ours = {self.A["_NET_WM_STATE_ABOVE"], self.A["_NET_WM_STATE_HIDDEN"], self.A["_NET_WM_STATE_MAXIMIZED_VERT"],
                self.A["_NET_WM_STATE_MAXIMIZED_HORZ"], self.A["_NET_WM_STATE_FULLSCREEN"]}
        try:
            p = c.win.get_full_property(self.A["_NET_WM_STATE"], Xatom.ATOM)
            keep = [a for a in (list(p.value) if p else []) if a not in ours]
        except error.BadWindow:
            keep = []
        if c.above:
            keep.append(self.A["_NET_WM_STATE_ABOVE"])
        if c.minimized:
            keep.append(self.A["_NET_WM_STATE_HIDDEN"])
        if c.maximized:
            keep += [self.A["_NET_WM_STATE_MAXIMIZED_VERT"], self.A["_NET_WM_STATE_MAXIMIZED_HORZ"]]
        if c.fullscreen:
            keep.append(self.A["_NET_WM_STATE_FULLSCREEN"])
        self._prop(c.win, "_NET_WM_STATE", Xatom.ATOM, 32, keep)

    # ------------------------------------------------------------- geometry
    def _mirror_client_shape(self, c):
        """Undecorated windows (popups, dock, CSD apps): give the frame the same outline as the client."""
        try:
            shape.Combine(display=self.d.display, opcode=self.d.display.get_extension_major(shape.extname),
                          destination_window=c.frame, source_window=c.win, operation=shape.SO.Set,
                          destination_kind=shape.SK.Bounding, source_kind=shape.SK.Bounding, x_offset=0, y_offset=0)
        except Exception:
            pass

    def _shape(self, c):
        if self.comp and not c.is_desktop:
            return                      # alpha provides the rounding
        if not c.decorated and not c.is_desktop:
            self._mirror_client_shape(c)
            return
        fw, fh = c.fw, c.fh
        rects = []
        r = RAD if (c.decorated and not c.maximized and not c.fullscreen) else 0
        if r:
            import math
            for i in range(r):
                inset = r - int(math.sqrt(max(0, r * r - (r - i - 0.5) ** 2)) + 0.5)
                rects.append((inset, i, fw - 2 * inset, 1))
                rects.append((inset, fh - 1 - i, fw - 2 * inset, 1))
            rects.append((0, r, fw, fh - 2 * r))
        else:
            rects.append((0, 0, fw, fh))
        c.frame.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.Unsorted, 0, 0, rects)

    def _send_configure(self, c):
        ox, oy = c.off
        ev = protocol.event.ConfigureNotify(window=c.win, event=c.win, x=c.x + ox, y=c.y + oy, width=c.w, height=c.h,
                                           border_width=0, above_sibling=X.NONE, override=False)
        c.win.send_event(ev, event_mask=X.StructureNotifyMask)

    def apply_geometry(self, c, repaint=True):
        ox, oy = c.off
        c.frame.configure(x=c.x, y=c.y, width=c.fw, height=c.fh)
        c.win.configure(x=ox, y=oy, width=c.w, height=c.h)
        self._shape(c)
        self._comp_props(c)
        self._place_handles(c)
        self._send_configure(c)
        if repaint:
            self._paint(c)
        self.d.flush()

    def toggle_max(self, c):
        if c.is_desktop or (not c.decorated and not c.csd and not c.maximized):
            return
        if c.maximized:
            c.maximized = False
            if c.saved:
                c.x, c.y, c.w, c.h = c.saved
        else:
            c.saved = (c.x, c.y, c.w, c.h)
            c.maximized = True
            self._fit_max(c)
        self._set_wm_state(c, 1)
        self.apply_geometry(c)

    def set_fullscreen(self, c, on):
        if on == c.fullscreen or c.is_desktop:
            return
        c.fullscreen = on
        if on:
            c.saved = (c.x, c.y, c.w, c.h, c.decorated)
            mx, my, mw, mh = next((m for m in self.mons if m[0] <= c.x + c.fw // 2 < m[0] + m[2] and m[1] <= c.y + 10 < m[1] + m[3]), self.mons[0])
            c.decorated, c.x, c.y, c.w, c.h = False, mx, my, mw, mh      # fullscreen covers its own monitor, not the whole root
        elif c.saved:
            c.x, c.y, c.w, c.h, c.decorated = c.saved
        self._set_wm_state(c, 1)
        self.apply_geometry(c)
        self.raise_(c, force=True)                        # on: cover the docks; off: put the docks back on top

    def minimize(self, c):
        if c.is_desktop or c.minimized:
            return
        c.minimized = True
        c.frame.unmap()
        self._set_wm_state(c, 3)
        if self.focus_c is c:
            self.focus_c = None
            nxt = [x for x in reversed(self.stack) if self._visible(x) and not x.minimized and not x.is_desktop]
            self.focus(nxt[0] if nxt else next((x for x in self.clients if x.is_desktop), None))
        self._publish()

    def restore(self, c):
        if c.minimized:
            c.minimized = False
            if self._visible(c):
                c.frame.map()
            self._set_wm_state(c, 1)
        self.raise_(c)
        self.focus(c)

    def _x_top(self, c):
        """Is c's frame the topmost regular window according to the X server? Frames mapped by restore / desktop switches /
        new windows land on top without touching our own bookkeeping, so the cached "last raised" window cannot be trusted."""
        try:
            kids = self.root.query_tree().children
        except error.XError:
            return False
        for ch in reversed(kids):
            o = self.by_frame.get(ch.id)
            if o is None or o.is_dock or o.is_desktop or o.minimized or not self._visible(o):
                continue
            if o.above and o is not c:
                return False
            return o is c
        return False

    def raise_(self, c, force=False):
        if c.is_desktop:
            return
        if not force and not c.fullscreen and self._x_top(c):
            self._top_regular = c if (c.focusable and not c.is_dock) else getattr(self, "_top_regular", None)
            return                                    # really on top (checked against the X server): a restack would only make the compositor redo its blur
        c.frame.configure(stack_mode=X.Above)
        if c.focusable and not c.is_dock:
            self._top_regular = c
        top = getattr(self, "_top_regular", None)
        for d in self.stack:                              # "always on top" windows stay above the others (docks still go above those)
            if d.above and d is not c and self._visible(d) and not d.minimized:
                d.frame.configure(stack_mode=X.Above)
        fs = top is not None and top.fullscreen and top in self.clients and self._visible(top) and not top.minimized
        for d in self.clients:
            if d.is_dock and d is not c:
                if fs:                                    # a fullscreen window covers the docks: keep them right below it
                    d.frame.configure(sibling=top.frame, stack_mode=X.Below)
                else:
                    d.frame.configure(stack_mode=X.Above)
        if c in self.stack:
            self.stack.remove(c)
        self.stack.append(c)
        self._raised_top = c
        self._publish()

    # --- passive click grabs: only windows that are not (focused AND on top) need the WM to see their clicks
    def _grab_click(self, c):
        if not c.grabbed:
            c.win.grab_button(X.AnyButton, X.AnyModifier, True, X.ButtonPressMask, X.GrabModeSync, X.GrabModeAsync, X.NONE, X.NONE)
            c.grabbed = True

    def _ungrab_click(self, c):
        if c.grabbed:
            c.win.ungrab_button(X.AnyButton, X.AnyModifier)
            c.grabbed = False

    def _sync_grab(self, c):
        if c is None or c not in self.clients or not c.focusable:
            return
        settled = c is self.focus_c and (c.is_desktop or self._x_top(c))
        self._ungrab_click(c) if settled else self._grab_click(c)

    def focus(self, c, raise_=True):
        if c is None:
            self.d.set_input_focus(X.PointerRoot, X.RevertToPointerRoot, X.CurrentTime)
            return
        if raise_ and not c.is_desktop:
            self.raise_(c)
        old = self.focus_c
        self.focus_c = c
        try:
            self.d.set_input_focus(c.win, X.RevertToPointerRoot, X.CurrentTime)
        except error.BadWindow:
            pass
        changed = []
        for x in (old, c):
            if x and x in self.clients and x not in changed:
                nf = x is c
                if x.focused != nf:                   # repaint a titlebar only when its focus look actually changes
                    x.focused = nf
                    changed.append(x)
        for x in (old, c):
            self._sync_grab(x)
        self._publish()
        for x in changed:
            if x.decorated:
                try:
                    self._paint(x)
                except Exception as e:                        # cosmetic: never let it undo the focus change
                    print("glitter-wm: titlebar repaint failed: %s" % e, file=sys.stderr)

    def close(self, c):
        if self._delete_supported(c.win):
            ev = protocol.event.ClientMessage(window=c.win, client_type=self.A["WM_PROTOCOLS"],
                                              data=(32, [self.A["WM_DELETE_WINDOW"], X.CurrentTime, 0, 0, 0]))
            c.win.send_event(ev)
        else:
            c.win.kill_client()
        self.d.flush()

    def switch_desktop(self, n):
        if not 0 <= n < self.ndesk or n == self.cur:
            return
        self.cur = n
        for c in self.clients:
            if self._visible(c) and not c.minimized:
                c.frame.map()
            elif not self._visible(c):
                c.frame.unmap()
        self._top_regular = self._raised_top = None
        for x in list(self.stack):                          # newly mapped frames landed on top in map order: restore our stacking order
            if self._visible(x) and not x.minimized and not x.is_desktop and not x.is_dock:
                self.raise_(x, force=True)
        nxt = [x for x in reversed(self.stack) if self._visible(x) and not x.minimized and not x.is_desktop]
        self.focus(nxt[0] if nxt else next((x for x in self.clients if x.is_desktop), None), raise_=False)
        self._publish()

    def move_to_desktop(self, c, n):
        c.desktop = n if n == STICKY else max(0, min(self.ndesk - 1, n))
        self._prop(c.win, "_NET_WM_DESKTOP", Xatom.CARDINAL, 32, [c.desktop])
        if not self._visible(c):
            c.frame.unmap()
            if self.focus_c is c:
                self.focus_c = None
        self._publish()

    # ------------------------------------------------------------- painting
    def _btns(self, c):
        return self._tb(c)["btns"]

    def _regions(self, c, x, y):
        fw, fh = c.fw, c.fh
        if not c.decorated:
            return "client"
        if y < TH:
            tb = self._tb(c)
            for name, cx in tb["btns"].items():
                if abs(x - cx) <= tb["hw"] and abs(y - TH / 2) <= max(tb["hh"], 13 if tb["hh"] < 19 else TH / 2):
                    return name
            if tb["icon"] is not None and abs(x - tb["icon"]) <= 14 and abs(y - TH / 2) <= 14:
                return "icon"
            k = 4 if c.bw == 0 else 12
            edge = ("t" if y < 4 else "") + ("l" if x < k else "") + ("r" if x >= fw - k else "")
            return "resize:" + edge if edge else "title"
        if c.bw == 0:
            return "client"                      # edges below the titlebar are separate input-only handles
        bw = c.bw
        e = ("b" if y >= fh - bw - 2 else "") + ("l" if x < bw + 2 else "") + ("r" if x >= fw - bw - 2 else "")
        if e:
            if "b" in e and (x < 14 or x >= fw - 14):
                e = "b" + ("l" if x < 14 else "r")
            return "resize:" + e
        return "client"

    HCUR = {"l": "left", "r": "right", "b": "bottom", "t": "top", "tl": "tl", "tr": "tr", "bl": "bl", "br": "br"}

    def _make_handles(self, c):
        for name, cur in self.HCUR.items():
            w = c.frame.create_window(0, 0, 1, 1, 0, X.CopyFromParent, X.InputOnly, X.CopyFromParent,
                                      event_mask=X.ButtonPressMask, cursor=self.cur_map[cur])
            c.handles[name] = w
            self.by_handle[w.id] = (c, name)
        self._place_handles(c)

    def _place_handles(self, c):
        if not c.handles:
            return
        show = c.decorated and not c.maximized and not c.fullscreen
        fw, fh, T, K = c.fw, c.fh, 5, 18
        geo = {"l": (0, K, T, fh - 2 * K), "r": (fw - T, K, T, fh - 2 * K), "b": (K, fh - T, fw - 2 * K, T),
               "t": (K, 0, fw - 2 * K, 4), "tl": (0, 0, K, K), "tr": (fw - K, 0, K, K),
               "bl": (0, fh - K, K, K), "br": (fw - K, fh - K, K, K)}
        for n, w in c.handles.items():
            x, y, ww, hh = geo[n]
            if show and ww > 0 and hh > 0:
                w.configure(x=x, y=y, width=ww, height=hh)
                w.map()
            else:
                w.unmap()

    def _paint_chrome(self, cr, c, ink, light):
        """Icon, title and buttons of the titlebar in the active layout."""
        tb, L = self._tb(c), self.layout
        style, hv, cy = L["style"], c.hover, TH / 2
        if tb["icon"] is not None:
            if hv == "icon":
                gfx.fill_rrect(cr, tb["icon"] - 14, cy - 14, 28, 28, 9, (0.4, 0.4, 0.9, 0.22) if light else (1, 1, 1, 0.22))
            self._draw_app_icon(cr, c, tb["icon"], cy + 0.5, 1.0 if c.focused else 0.78)
        gfx.text(cr, c.title or c.cls or "Untitled", tb["tx"], cy + 0.5, 12.5, (ink[0], ink[1], ink[2], 1.0 if c.focused else 0.7), 500,
                 anchor=tb["anchor"], max_w=tb["tw"])
        glyphs = {"min": "minimize", "max": "maximize", "close": "close"}
        hov_any = hv in tb["btns"]
        for name, cx in tb["btns"].items():
            on = hv == name
            fg = (ink[0], ink[1], ink[2], 0.95 if c.focused else 0.65)
            if style == "glyph":
                if on:
                    col = (0.95, 0.36, 0.5, 0.9) if name == "close" else (1, 1, 1, 0.26) if not light else (0.4, 0.4, 0.9, 0.22)
                    if self.btn_shape == "circle":
                        gfx.circle(cr, cx, cy, 12); cr.set_source_rgba(*col); cr.fill()
                    else:
                        gfx.fill_rrect(cr, cx - 13, cy - 12, 26, 24, 9, col)
                    fg = (1, 1, 1, 1) if name == "close" else fg
                ic.icon(cr, glyphs[name], cx, cy, self.btn_size, fg, 1.8)
            elif style == "wide":
                if on:
                    gfx.fill_rrect(cr, cx - 23, 0, 46, TH, 0, (0.9, 0.2, 0.3, 0.95) if name == "close" else (1, 1, 1, 0.22) if not light else (0.4, 0.4, 0.9, 0.2))
                ic.icon(cr, glyphs[name], cx, cy, self.btn_size - 1, (1, 1, 1, 1) if (on and name == "close") else fg, 1.5)
            elif style == "dots":
                base = {"close": (1.0, 0.37, 0.34), "min": (1.0, 0.74, 0.2), "max": (0.16, 0.78, 0.25)}[name]
                if not c.focused:
                    base = (0.62, 0.62, 0.68)
                gfx.circle(cr, cx, cy, 6.5); cr.set_source_rgba(*base, 1); cr.fill_preserve(); cr.set_source_rgba(0, 0, 0, 0.18); cr.set_line_width(0.8); cr.stroke()
                if hov_any and c.focused:
                    ic.icon(cr, glyphs[name], cx, cy, 8, (0.15, 0.1, 0.2, 0.75), 1.9)
            elif style == "circle":
                col = (0.95, 0.36, 0.5, 0.95) if (on and name == "close") else ((1, 1, 1, 0.20) if not light else (0.2, 0.2, 0.6, 0.13))
                gfx.circle(cr, cx, cy, 10.5); cr.set_source_rgba(*col); cr.fill()
                ic.icon(cr, glyphs[name], cx, cy, 9, (1, 1, 1, 1) if (on and name == "close") else fg, 1.8)
            else:                                                   # ubuntu: orange close, grey the rest, glyphs always visible
                col = (0.91, 0.33, 0.13, 1) if name == "close" else ((0.5, 0.46, 0.58, 0.9) if c.focused else (0.5, 0.46, 0.58, 0.5))
                gfx.circle(cr, cx, cy, 10); cr.set_source_rgba(*col); cr.fill()
                ic.icon(cr, glyphs[name], cx, cy, 9, (1, 1, 1, 1), 1.8)

    def _paint(self, c, bands=None):
        if not c.decorated or c.is_desktop:
            return
        fw, fh = c.fw, c.fh
        tb_only = self.comp and c.bw == 0                 # seamless window: this frame is just the titlebar
        sh = TH if tb_only else fh
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, fw, sh)
        cr = cairo.Context(surf)
        cr.set_antialias(cairo.ANTIALIAS_BEST)
        light = c.mat == "window_light"
        ink = (0.165, 0.176, 0.43, 1) if light else (1, 1, 1, 1)
        rad = 0 if (c.maximized or c.fullscreen) else RAD
        osc = 1.0 if (c.focused or tb_only) else self.inactive     # seamless: body never dims, so the bar must not either
        m = self.theme.material(c.mat)
        if tb_only:
            gfx.comp_glass(cr, fw, sh, 0, m, osc, corners=(rad, rad, 0, 0), sheen=False)
        elif self.comp:
            gfx.comp_glass(cr, fw, fh, rad, m, osc)
        else:
            cr.save()
            cr.translate(-c.x, -c.y)
            self.glass.panel(cr, c.x, c.y, fw, fh, 0, c.mat, shadow=False, rim=False, opacity_scale=osc)
            cr.restore()
        if not tb_only:
            cr.set_source(gfx.lin(0, 0, 0, TH, [(0, (1, 1, 1, 0.14)), (1, (1, 1, 1, 0.02))]))
            cr.rectangle(0, 0, fw, TH); cr.fill()
        rim = (1, 1, 1, 0.65 if c.focused else 0.38)
        if tb_only:
            gfx.rrect_var(cr, 0.5, 0.5, fw - 1, fh - 1, rad, rad, 0, 0)
            cr.set_source_rgba(*rim); cr.set_line_width(1.2); cr.stroke()
        else:
            gfx.stroke_rrect(cr, 0, 0, fw, fh, rad, rim, 1.2)
        self._paint_chrome(cr, c, ink, light)
        surf.flush()
        buf = bytes(surf.get_data())
        gc = c.frame.create_gc()
        stride = fw * 4
        try:
            if tb_only:
                self._put(c.frame, gc, 0, 0, fw, TH, c.depth, buf)
            else:
                bw = c.bw
                self._put(c.frame, gc, 0, 0, fw, TH, c.depth, buf[:TH * stride])
                self._put(c.frame, gc, 0, fh - bw, fw, bw, c.depth, buf[(fh - bw) * stride:fh * stride])
                mid = fh - TH - bw
                if mid > 0:
                    left_b = b"".join(buf[(TH + r) * stride:(TH + r) * stride + bw * 4] for r in range(mid))
                    right_b = b"".join(buf[(TH + r) * stride + (fw - bw) * 4:(TH + r + 1) * stride] for r in range(mid))
                    self._put(c.frame, gc, 0, TH, bw, mid, c.depth, left_b)
                    self._put(c.frame, gc, fw - bw, TH, bw, mid, c.depth, right_b)
        finally:
            gc.free()
        self.d.flush()

    def _put(self, drawable, gc, x, y, w, h, depth, buf):
        """PutImage that never exceeds the X request size limit. python-xlib has no BIG-REQUESTS: one request carries at most ~262 KB,
        and a 1920 px wide titlebar is already 292 KB, so any window wider than ~1700 px used to fail to paint (blank gradient titlebar)
        and the exception aborted whatever the WM was doing, including replaying the click it was holding."""
        stride = w * 4
        try:
            words = self.d.display.info.max_request_length                # 65535 words without BIG-REQUESTS
        except AttributeError:
            words = 65535
        limit = max(1024, words * 4 - 256)
        rows = max(1, limit // max(1, stride))
        for r in range(0, h, rows):
            n = min(rows, h - r)
            drawable.put_image(gc, x, y + r, w, n, X.ZPixmap, depth, 0, buf[r * stride:(r + n) * stride])

    def repaint_all(self):
        for c in self.clients:
            self._paint(c)

    # ---------------------------------------------------------------- events
    def run(self):
        d = self.d
        last_check = time.time()
        while True:
            while d.pending_events():
                self.handle(d.next_event())
            pend = getattr(self, "_drag_pending", None)
            if pend is not None and self.drag:                    # a coalesced motion is waiting: apply it as soon as its slot has passed
                time.sleep(0.004)
                self.on_motion(pend)
                continue
            r, _, _ = select.select([d.fileno()], [], [], 0.03 if getattr(self, "_super_launch_at", None) else 1.0)
            self._poll_super_tap()
            if time.time() - last_check > 1.0:
                last_check = time.time()
                try:
                    self._check_monitors()
                except Exception as e:
                    print("glitter-wm: monitor check failed: %s" % e, file=sys.stderr)
                mt = self._mtime()
                if mt != self._settings_mtime:
                    self._settings_mtime = mt
                    self.load_theme()
                    self._cursors()
                    self.reload_all()

    def handle(self, ev):
        t = ev.type
        if self.shape_evt is not None and t == self.shape_evt:       # a client changed its outline (rounded popups)
            c = self.by_win.get(ev.affected_window.id)
            if c and not c.decorated and not c.is_desktop:
                self._shape(c)
                self.d.flush()
            return
        h = {X.MapRequest: self.on_map_request, X.ConfigureRequest: self.on_configure_request,
             X.UnmapNotify: self.on_unmap, X.DestroyNotify: self.on_destroy, X.PropertyNotify: self.on_property,
             X.ClientMessage: self.on_client_message, X.ButtonPress: self.on_button, X.ButtonRelease: self.on_release,
             X.MotionNotify: self.on_motion, X.Expose: self.on_expose, X.KeyPress: self.on_key, X.KeyRelease: self.on_key_release,
             X.LeaveNotify: self.on_leave, X.EnterNotify: self.on_enter}.get(t)
        if h:
            try:
                h(ev)
            except error.BadWindow:
                pass
            except Exception:
                import traceback
                traceback.print_exc()          # keep the session alive; the traceback goes to the log

    def on_map_request(self, ev):
        c = self.by_win.get(ev.window.id)
        if c:
            self.restore(c)
        else:
            self.manage(ev.window)

    def on_configure_request(self, ev):
        c = self.by_win.get(ev.window.id)
        m = ev.value_mask
        if not c:
            kw = {}
            for bit, key in ((X.CWX, "x"), (X.CWY, "y"), (X.CWWidth, "width"), (X.CWHeight, "height"),
                             (X.CWBorderWidth, "border_width")):
                if m & bit:
                    kw[key] = getattr(ev, key)
            if m & X.CWStackMode:
                kw["stack_mode"] = ev.stack_mode
            ev.window.configure(**kw)
            return
        if c.is_desktop or c.maximized or c.fullscreen:
            self._send_configure(c)
            return
        if m & X.CWWidth:
            c.w = max(40, ev.width)
        if m & X.CWHeight:
            c.h = max(30, ev.height)
        if m & X.CWX:                            # ICCCM: honour requested position (client coords -> frame coords)
            c.x = max(-c.fw + 60, ev.x - c.off[0])
        if m & X.CWY:
            c.y = ev.y - c.off[1] if c.is_dock else max(self._min_y(c, self.area_at(ev.x, ev.y)[1]), ev.y - c.off[1])
        self.apply_geometry(c)
        if c.cls == "glitterde-dock":
            self.update_area()

    def on_unmap(self, ev):
        c = self.by_win.get(ev.window.id)
        if c and ev.event == c.frame.id or c and ev.event == ev.window:
            if c.ignore_unmap > 0:
                c.ignore_unmap -= 1
            else:
                self.unmanage(c)

    def on_destroy(self, ev):
        c = self.by_win.get(ev.window.id)
        if c:
            self.unmanage(c, destroyed=True)

    def on_property(self, ev):
        c = self.by_win.get(ev.window.id)
        if not c:
            return
        if ev.atom in (self.A["_NET_WM_NAME"], Xatom.WM_NAME):
            c.title = self._text(c.win, self.A["_NET_WM_NAME"], Xatom.WM_NAME)
            if not c.icon_surf and c.cls not in VECTOR_ICONS:
                self._paint(c)                          # the initial-letter tile follows the title
            self._paint(c)
        elif ev.atom == self.A["_NET_WM_ICON"]:
            c.icon_ready = False
            self._paint(c)
        elif ev.atom in (self.A["_MOTIF_WM_HINTS"], self.A["_GTK_FRAME_EXTENTS"]):
            self._recheck_decor(c)

    def on_client_message(self, ev):
        A, ct = self.A, ev.client_type
        c = self.by_win.get(ev.window.id)
        data = ev.data[1]
        if ct == A["_NET_CURRENT_DESKTOP"]:
            self.switch_desktop(data[0])
        elif ct == A["_NET_NUMBER_OF_DESKTOPS"]:
            self.set_ndesk(data[0], save=True)
        elif not c:
            return
        elif ct == A["_NET_ACTIVE_WINDOW"]:
            if c.desktop not in (self.cur, STICKY):
                self.switch_desktop(c.desktop)
            self.restore(c)
        elif ct == A["_NET_CLOSE_WINDOW"]:
            self.close(c)
        elif ct == A["_NET_WM_MOVERESIZE"]:
            self._client_moveresize(c, data[0], data[1], data[2])
        elif ct == A["_NET_MOVERESIZE_WINDOW"]:
            fl = data[0]
            if c.is_desktop or c.maximized or c.fullscreen:
                return
            ox, oy = c.off
            if fl & 0x400:
                c.w = max(40, data[3])
            if fl & 0x800:
                c.h = max(30, data[4])
            if fl & 0x100:
                c.x = data[1] - ox
            if fl & 0x200:
                c.y = data[2] - oy
            self.apply_geometry(c)
        elif ct == A["WM_CHANGE_STATE"] and data[0] == 3:
            self.minimize(c)
        elif ct == A["_NET_WM_DESKTOP"]:
            self.move_to_desktop(c, data[0])
        elif ct == A["_NET_WM_STATE"]:
            action = data[0]
            for atom in (data[1], data[2]):
                on = {1: True, 0: False}.get(action)
                if atom == A["_NET_WM_STATE_FULLSCREEN"]:
                    self.set_fullscreen(c, (not c.fullscreen) if on is None else on)
                elif atom in (A["_NET_WM_STATE_MAXIMIZED_VERT"], A["_NET_WM_STATE_MAXIMIZED_HORZ"]):
                    if on is None or on != c.maximized:
                        self.toggle_max(c)
                        break
                elif atom == A["_NET_WM_STATE_ABOVE"]:
                    c.above = (not c.above) if on is None else on
                    self._set_wm_state(c, 1)
                    self.raise_(c, force=True)
                elif atom == A["_NET_WM_STATE_HIDDEN"]:
                    self.minimize(c) if on in (True, None) else self.restore(c)

    def on_expose(self, ev):
        c = self.by_frame.get(ev.window.id)
        if c and ev.count == 0:
            self._paint(c)

    def on_enter(self, ev):
        if self.ffm and not self.drag and ev.mode == X.NotifyNormal:
            c = self.by_frame.get(ev.window.id)
            if c and not c.is_desktop and c is not self.focus_c:
                self.focus(c, raise_=False)

    def on_leave(self, ev):
        c = self.by_frame.get(ev.window.id)
        if c and c.hover:
            c.hover = None
            self._paint(c)

    def on_key(self, ev):
        if os.environ.get('GLITTERDE_DEBUG'):
            print('wm key', ev.detail, ev.state, self.keys.get((ev.detail, self._key_base(ev.state))), file=sys.stderr)
        base = self._key_base(ev.state)
        tag = self.keys.get((ev.detail, base))
        if tag == "close" and self.focus_c and not self.focus_c.is_desktop:
            self.close(self.focus_c)
        elif tag == "cycle":
            order = [x for x in self.stack if self._visible(x) and not x.is_desktop and not x.minimized]
            if len(order) > 1:
                self.focus(order[0])
        elif tag and tag.startswith("shot-"):
            tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "glitterde-screenshot")
            try:
                subprocess.Popen([sys.executable, tool, "--ui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                pass
        elif tag == "launcher":                          # Super pressed: it is a "tap" only if released with no other key in between
            self._super_down, self._super_used, self._super_launch_at = True, False, None
        elif tag and tag.startswith("super-"):
            self._super_used = True
            self._super_action(tag[6:])

    def _key_base(self, state):
        """Modifiers that matter for our shortcuts; Caps/Num Lock, AltGr and the like must not stop them from matching."""
        return state & (X.ShiftMask | X.ControlMask | X.Mod1Mask | getattr(self, "super_mask", X.Mod4Mask))

    def on_key_release(self, ev):
        base = self._key_base(ev.state)
        if self.keys.get((ev.detail, base)) == "launcher" and getattr(self, "_super_down", False):
            self._super_down = False
            if not self._super_used:                      # held-down Super autorepeats as release+press: wait a moment to be sure it is a real release
                self._super_launch_at = time.time() + 0.03

    def _poll_super_tap(self):
        at = getattr(self, "_super_launch_at", None)
        if at is not None and time.time() >= at:
            self._super_launch_at = None
            self._open_launcher()

    def _open_launcher(self):
        sh = next((x for x in self.clients if x.is_desktop), None)
        if sh:
            self._launch_n = getattr(self, "_launch_n", 0) + 1       # property change = reliable signal for GTK
            sh.win.change_property(self.A["_GLITTER_LAUNCHER"], Xatom.CARDINAL, 32, [self._launch_n])
            self.d.flush()

    def _run_app(self, name, *args):
        tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", name)
        try:
            subprocess.Popen([sys.executable, tool, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    def _normal_clients(self):
        return [x for x in self.clients if not x.is_desktop and not x.is_dock and x.focusable and self._visible(x)]

    def toggle_show_desktop(self):
        """Win+D: minimise everything, press again to bring the same windows back."""
        hidden = [c for c in getattr(self, "_desk_hidden", []) if c in self.clients and c.minimized]
        if hidden and not [c for c in self._normal_clients() if not c.minimized]:
            self._desk_hidden = []
            for c in hidden:
                self.restore(c)
            return
        vis = [c for c in self._normal_clients() if not c.minimized]
        self._desk_hidden = vis
        for c in vis:
            self.minimize(c)

    def _super_action(self, act):
        f = self.focus_c
        if act == "desktop":
            self.toggle_show_desktop()
        elif act == "files":
            self._run_app("sparkfiles")
        elif act == "terminal":
            self._run_app("sparkterm")
        elif act == "settings":
            self._run_app("sparksettings")
        elif act == "close" and f and not f.is_desktop:
            self.close(f)
        elif act == "minimize" and f and not f.is_desktop:
            self.minimize(f)
        elif act == "maximize" and f and not f.is_desktop and not f.maximized:
            self.toggle_max(f)
        elif act == "restore" and f and not f.is_desktop:
            self.toggle_max(f) if f.maximized else self.minimize(f)
        elif act == "cycle":
            order = [x for x in self.stack if self._visible(x) and not x.is_desktop and not x.minimized]
            if len(order) > 1:
                self.focus(order[0])
        elif act in ("ws-prev", "ws-next"):
            self.switch_desktop((self.cur + (1 if act == "ws-next" else -1)) % self.ndesk)
        elif act.startswith("dock-"):
            self._dock_app(int(act[5:]))

    def _dock_app(self, n):
        """Win+1..9: tell the shell to activate / launch the n-th dock item (the shell owns the dock)."""
        sh = next((x for x in self.clients if x.is_desktop), None)
        if not sh:
            return
        try:
            rd = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
            with open(os.path.join(rd, "glitterde-dockapp-%d" % os.getuid()), "w") as fh:
                fh.write(str(n))
        except OSError:
            return
        self._dockapp_n = getattr(self, "_dockapp_n", 0) + 1
        sh.win.change_property(self.A["_GLITTER_DOCKAPP"], Xatom.CARDINAL, 32, [self._dockapp_n])
        self.d.flush()

    def on_button(self, ev):
        c = self.by_win.get(ev.window.id)
        if c:                                    # click inside an UNFOCUSED client (focused ones are not grabbed): focus/raise, then replay
            try:
                if ev.detail <= 3 and (self.focus_c is not c or (not c.is_desktop and not self._x_top(c))):
                    self.focus(c, raise_=not c.is_desktop)     # scrolling over a background window must not steal focus or restack
            finally:                                           # the pointer stays frozen for EVERY app until this is sent
                self.d.allow_events(X.ReplayPointer, ev.time)
            return
        hh = self.by_handle.get(ev.window.id)
        if hh:
            c, name = hh
            self.focus(c)
            if ev.detail == 1:
                self._begin_drag(c, ev, "resize:" + name)
            return
        c = self.by_frame.get(ev.window.id)
        if not c:
            return
        reg = self._regions(c, ev.event_x, ev.event_y)
        self.focus(c)
        if ev.detail == 3 and reg in ("title", "icon"):                  # right-click the titlebar: the same window menu as the icon
            self._open_winmenu(c, ev.root_x, ev.root_y)
            return
        if ev.detail != 1:
            return
        if reg == "icon":
            now = time.time()
            if now - getattr(c, "last_icon_click", 0) < 0.4:          # double-click the icon: close (classic window-menu behaviour)
                c.last_icon_click = 0
                self.close(c)
            else:
                c.last_icon_click = now
                self._open_winmenu(c, c.x + self._icon_cx(c) - 14, c.y + TH + 2)
        elif reg == "min":
            self.minimize(c)
        elif reg == "max":
            self.toggle_max(c)
        elif reg == "close":
            self.close(c)
        elif reg == "title":
            now = time.time()
            if now - getattr(c, "last_click", 0) < 0.35:
                self.toggle_max(c); c.last_click = 0
                return
            c.last_click = now
            if not c.maximized:
                self._begin_drag(c, ev, "move")
        elif reg.startswith("resize:") and not c.maximized:
            self._begin_drag(c, ev, reg)

    DRAG_CUR = {"resize:b": "bottom", "resize:t": "top", "resize:l": "left", "resize:r": "right", "resize:tl": "tl",
                "resize:tr": "tr", "resize:bl": "bl", "resize:br": "br"}

    def _begin_drag(self, c, ev, kind):
        return self._start_drag(c, ev.root_x, ev.root_y, kind)

    def _buttons_held(self):
        try:
            return bool(self.root.query_pointer().mask & (X.Button1Mask | X.Button2Mask | X.Button3Mask | X.Button4Mask | X.Button5Mask))
        except Exception:
            return True

    def _end_stale_drag(self):
        try:
            self.d.ungrab_pointer(X.CurrentTime)
        except Exception:
            pass
        self.drag = None

    def _start_drag(self, c, px, py, kind):
        cur = self.cur_map["fleur" if kind == "move" else self.DRAG_CUR.get(kind, "br")]
        mask = X.ButtonReleaseMask | X.PointerMotionMask
        st = X.AlreadyGrabbed
        for _ in range(6):                                # the client (GTK4) releases its own grab asynchronously: give it a moment instead of giving up
            st = c.frame.grab_pointer(False, mask, X.GrabModeAsync, X.GrabModeAsync, X.NONE, cur, X.CurrentTime)
            if st != X.AlreadyGrabbed:
                break
            time.sleep(0.01)
        if st != X.GrabSuccess:
            if os.environ.get("GLITTERDE_DEBUG"):
                print("glitter-wm: drag grab failed (status %s)" % st, file=sys.stderr)
            return False
        held = self._buttons_held()                       # a client may ask for a drag after its button was already released: never start one that cannot end
        if not held:
            self.d.ungrab_pointer(X.CurrentTime)
            return False
        self.drag = dict(c=c, kind=kind, px=px, py=py, g=(c.x, c.y, c.w, c.h))
        return True

    # direction codes of _NET_WM_MOVERESIZE (EWMH): 0..7 = resize from tl,t,tr,r,br,b,bl,l; 8 = move; 11 = cancel
    MR_EDGE = {0: "tl", 1: "t", 2: "tr", 3: "r", 4: "br", 5: "b", 6: "bl", 7: "l"}

    def _client_moveresize(self, c, x_root, y_root, direction):
        """A client-side-decorated window (VS Code, Firefox/LibreWolf, GTK headerbars, Qt frameless ...) asks the WM to start a drag:
        this is the ONLY way those windows can be moved or resized, because the WM draws no frame for them."""
        if c.is_desktop or c.fullscreen:
            return
        if direction == 11:                               # cancel
            if self.drag and self.drag["c"] is c:
                self.d.ungrab_pointer(X.CurrentTime)
                self.drag = None
            return
        if direction == 8:
            kind = "move"
        elif direction in self.MR_EDGE:
            kind = "resize:" + self.MR_EDGE[direction]
        else:
            return                                        # keyboard-driven move/resize (9, 10) is not supported
        if self.drag:
            if self._buttons_held():
                return
            self._end_stale_drag()                        # a drag whose release we never saw would otherwise block every later move/resize
        self.focus(c)
        if c.maximized:
            if kind != "move":
                return
            frac = (x_root - c.x) / float(max(1, c.fw))   # dragging a maximised window restores it under the pointer
            self.toggle_max(c)
            a_ = self.area_at(x_root, y_root)
            c.x, c.y = int(x_root - frac * c.fw), max(self._min_y(c, a_[1]), y_root - 16)
            self.apply_geometry(c)
        self._start_drag(c, x_root, y_root, kind)

    def on_motion(self, ev):
        while self.d.pending_events():           # compress motion events
            nxt = self.d.next_event()
            if nxt.type == X.MotionNotify:
                ev = nxt
            else:
                self.handle(nxt)
                break
        dr = self.drag
        if dr:
            now = time.monotonic()
            if now - dr.get("t", 0) < 0.008:                       # more than ~125 steps/s only burn CPU: keep the newest, apply it on the next tick
                self._drag_pending = ev
                return
            dr["t"] = now
            self._drag_pending = None
            c = dr["c"]; dx, dy = ev.root_x - dr["px"], ev.root_y - dr["py"]
            x, y, w, h = dr["g"]
            k = dr["kind"]
            if k == "move":
                a_ = self.area_at(ev.root_x, ev.root_y)                  # the monitor under the pointer decides the top/bottom limits
                c.x, c.y = x + dx, max(self._min_y(c, a_[1]), min(a_[3] - 40, y + dy))
                c.frame.configure(x=c.x, y=c.y)
                if now - dr.get("cfg", 0) > 0.05:                 # the client only needs to hear about the new position now and then (and at the end)
                    dr["cfg"] = now
                    self._send_configure(c)
                if not self.comp:                 # glass is position-independent under a compositor: nothing to repaint
                    self._paint(c)
                self.d.flush()
                return
            e = k.split(":")[1]
            nx, ny, nw, nh = x, y, w, h
            mw, mh = max(MINW, c.minw), max(MINH, c.minh)
            if "r" in e:
                nw = max(mw, w + dx)
            if "b" in e:
                nh = max(mh, h + dy)
            if "l" in e:
                nw = max(mw, w - dx); nx = x + (w - nw)
            if "t" in e:
                nh = max(mh, h - dy); ny = max(self._min_y(c, self.area_at(ev.root_x, ev.root_y)[1]), y + (h - nh))
            if (nx, ny, nw, nh) == (c.x, c.y, c.w, c.h):
                return
            c.x, c.y, c.w, c.h = nx, ny, nw, nh
            # while the size changes the titlebar is repainted at most ~30 times a second; the final paint happens on release
            slow = now - dr.get("paint", 0) < 0.033 and nw != dr["g"][2] and c.decorated
            if slow:
                self.apply_geometry(c, repaint=False)
                dr["dirty"] = True
            else:
                dr["paint"] = now; dr["dirty"] = False
                self.apply_geometry(c)
            self.d.flush()
            return
        c = self.by_frame.get(ev.window.id)
        if c:
            reg = self._regions(c, ev.event_x, ev.event_y)
            hov = reg if reg in ("min", "max", "close", "icon") else None
            if hov != c.hover:
                c.hover = hov
                self._paint(c)
            cur = {"b": "bottom", "t": "top", "l": "left", "r": "right", "tl": "tl", "tr": "tr", "bl": "bl", "br": "br"}.get(
                reg.split(":")[1], "br") if reg.startswith("resize:") else "left_ptr"
            c.frame.change_attributes(cursor=self.cur_map[cur])

    def on_release(self, ev):
        if self.drag:
            self.d.ungrab_pointer(X.CurrentTime)
            c = self.drag["c"]
            pend = getattr(self, "_drag_pending", None)
            if pend is not None:                                  # apply the last coalesced motion so the window ends exactly under the pointer
                self.drag["t"] = 0; self.on_motion(pend)
            self._drag_pending = None
            self.drag = None
            self._send_configure(c)
            self._paint(c)
            self.d.flush()


def main():
    wm = WM()
    print("glitter-wm: managing %dx%d, %d existing window(s)" % (wm.W, wm.H, len(wm.clients)), file=sys.stderr)
    try:
        wm.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
