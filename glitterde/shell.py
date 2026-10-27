"""glittershell visuals: panel, desktop icons, dock, workspace switcher, widget column.

Everything here is *static artwork* driven by theme tokens. Coordinates follow the
design target (1536x1024 logical px) and are anchored to screen edges via Layout.
"""
import math

import cairo

from . import icons as ic
from .gfx import (PI, circle, fill_rrect, inset, lin, rrect, soft_glow, stroke_rrect, text, with_a)

WHITE = (1, 1, 1, 1)


def W(a):
    return (1, 1, 1, a)


class Layout:
    """Design-target coordinates + edge anchoring for any logical screen size."""
    REF_W, REF_H = 1536, 1024

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.dx = w - self.REF_W          # shift for right-anchored items
        self.dy = h - self.REF_H          # shift for bottom-anchored items

    def fx(self, x):                      # proportional x / y (floating windows)
        return x * self.w / self.REF_W

    def fy(self, y):
        return y * self.h / self.REF_H


# -------------------------------------------------------------------- panel
def draw_panel(c, g, t, L):
    h = 40
    g.panel(c, 0, 0, L.w, h, 0, "panel", shadow=False, rim=False)
    # luminous bottom hairline
    c.set_source(lin(0, 0, L.w, 0, [(0, W(0.10)), (0.5, W(0.55)), (1, W(0.14))]))
    c.rectangle(0, h - 1, L.w, 1); c.fill()
    txt = t.color("text.primary")
    # --- left: logo, name, workspaces
    ic.sparkle_logo(c, 25, 20, 26, txt)
    text(c, "glitterDE", 52, 20.5, 13.5, txt, 600)
    c.set_source_rgba(1, 1, 1, 0.14); c.rectangle(120, 12, 1, 16); c.fill()
    acc = t.color("accent.primary")
    for i, cx in enumerate((155, 199, 243, 287)):
        if i == 0:
            fill_rrect(c, cx - 17, 7, 34, 26, 9, with_a(acc, 0.88))
            stroke_rrect(c, cx - 17, 7, 34, 26, 9, W(0.25))
        text(c, str(i + 1), cx, 20, 13, txt, 500 if i else 600, "c")
    # --- centre: now playing + transport
    ic.icon(c, "sparkle", 553, 19, 10, W(0.8))
    ic.album_art(c, 571, 8, 23, 23, 5)
    text(c, "FEVER DREAM", 604, 12.5, 11.5, txt, 500)
    text(c, "Alex Warren", 604, 27.5, 10.5, W(0.72))
    ic.icon(c, "prev", 788, 19.5, 16, txt)
    ic.icon(c, "pause", 831, 19.5, 20, txt)
    ic.icon(c, "next", 874, 19.5, 16, txt)
    # --- right: tray (right-anchored)
    d = L.dx
    fill_rrect(c, 1104 + d, 8, 24, 24, 8, W(0.15))
    ic.icon(c, "phone", 1116 + d, 20, 15, txt, 1.5)
    fill_rrect(c, 1141 + d, 8, 24, 24, 8, with_a(acc, 0.70))
    stroke_rrect(c, 1141 + d, 8, 24, 24, 8, W(0.22))
    ic.icon(c, "cloud", 1153 + d, 20, 17, W(0.96))
    ic.icon(c, "brightness", 1189 + d, 20, 17, txt, 1.5)
    ic.icon(c, "volume", 1226 + d, 20, 17, txt, 1.5)
    ic.icon(c, "wifi", 1262 + d, 20, 17, txt, 1.6)
    ic.icon(c, "bluetooth", 1298 + d, 20, 16, txt, 1.5)
    ic.battery(c, 1335 + d, 20, 22, txt, 0.74)
    text(c, "74%", 1353 + d, 20, 11, txt)
    text(c, "Sat, 26 Apr 19:42", 1394 + d, 20, 11.2, txt, 400)
    c.set_source_rgba(1, 1, 1, 0.16); c.rectangle(1486 + d, 12, 1, 16); c.fill()
    ic.icon(c, "sparkle", 1512 + d, 20, 15, W(0.95))


# ----------------------------------------------------------- desktop icons
def draw_desktop_icons(c, g, t, L):
    sh = (0, 1, (0.05, 0.02, 0.25, 0.55))
    lab = lambda s, y: text(c, s, 47.5, y, 12.5, WHITE, 500, "c", shadow=sh)
    # Home (blue folder)
    ic.folder(c, 29, 63, 37, 31, (0.62, 0.74, 1.0, 1), (0.40, 0.55, 1.0, 1)); lab("Home", 113)
    ic.trash_color(c, 47.5, 160, 38); lab("Trash", 195)
    ic.folder(c, 29, 227, 37, 31, (0.64, 0.74, 1.0, 1), (0.42, 0.56, 1.0, 1)); lab("Projects", 277)
    ic.star_blob(c, 47.5, 325, 38); lab("Docs", 360)
    ic.cloud_tile(c, 29.5, 390, 36); lab("Downloads", 443)


# --------------------------------------------------------------------- dock
def draw_dock(c, g, t, L):
    w, h = 505, 65
    x = (L.w - w) / 2.0
    y = L.h - 79
    g.panel(c, x, y, w, h, 26, "dock", shadow_alpha=0.34)
    cy = y + h / 2.0
    ctr = L.w / 2.0 - 767.5
    items = [(555, "grid", True), (618, "browser", False), (678, "music", False), (739, "chat", False),
             (798, "files", False), (862, "term", False), (920, "settings", False), (982, "grid2", True)]
    for cx, kind, bare in items:
        cx += ctr
        if not bare:
            fill_rrect(c, cx - 22, cy - 22, 44, 44, 13, (0.20, 0.15, 0.55, 0.20))
        if kind == "grid":
            ic.app_launcher(c, cx, cy, 40, True)
        elif kind == "grid2":
            ic.app_launcher(c, cx, cy, 40, False)
        elif kind == "browser":
            ic.app_browser(c, cx, cy, 34)
        elif kind == "music":
            ic.app_music(c, cx, cy, 36)
        elif kind == "chat":
            ic.app_chat(c, cx, cy, 36)
        elif kind == "files":
            ic.app_files(c, cx, cy, 38)
        elif kind == "term":
            ic.app_terminal(c, cx, cy, 36)
        elif kind == "settings":
            ic.app_settings(c, cx, cy, 38)


# ------------------------------------------------- bottom corner affordances
def draw_workspace_switcher(c, g, t, L):
    x, y, w, h = 17, L.h - 56, 198, 36
    g.panel(c, x, y, w, h, 15, "dock", shadow_alpha=0.28)
    cy = y + h / 2.0
    ic.sparkle_logo(c, 37, cy, 21, WHITE)
    acc = t.color("accent.primary")
    for i, cx in enumerate((75, 114, 153, 191)):
        if i == 0:
            fill_rrect(c, cx - 16, cy - 12, 32, 24, 9, with_a(acc, 0.88))
            stroke_rrect(c, cx - 16, cy - 12, 32, 24, 9, W(0.25))
        text(c, str(i + 1), cx, cy + 0.5, 12.5, WHITE, 500, "c")


def draw_to_phone(c, g, t, L):
    x, y, w, h = 1412 + L.dx, L.h - 54, 105, 36
    g.panel(c, x, y, w, h, 13, "card", shadow_alpha=0.26)
    ic.icon(c, "phone", x + 24, y + h / 2, 17, WHITE, 1.5)
    text(c, "To phone", x + 46, y + h / 2 + 0.5, 11.5, WHITE, 500)


# ---------------------------------------------------------- widget column
def _card(c, g, x, y, w, h, title=None, icon=None):
    g.panel(c, x, y, w, h, 19, "card", shadow_alpha=0.26)
    if title:
        ic.icon(c, icon, x + 24, y + 19, 16, W(0.95), 1.5)
        text(c, title, x + 47, y + 18.5, 12, WHITE, 500)


def draw_widgets(c, g, t, L):
    d = L.dx
    X, WD = 1251 + d, 266
    _phone_card(c, g, t, X, 60, WD)
    _system_card(c, g, t, X, 263, WD)
    _network_card(c, g, t, X, 416, WD)
    _playing_card(c, g, t, X, 556, WD)
    _notif_card(c, g, t, X, 738, WD)


def _phone_card(c, g, t, x, y, w):
    h = 187
    g.panel(c, x, y, w, h, 19, "card", shadow_alpha=0.28)
    # upper block divider (curved lower edge like the design target)
    rrect(c, x + 1, y + 1, w - 2, 96, 18)
    c.set_source(lin(0, y, 0, y + 97, [(0, W(0.04)), (1, W(0.10))])); c.fill()
    c.set_source(lin(x, 0, x + w, 0, [(0, W(0.0)), (0.5, W(0.35)), (1, W(0.0))]))
    c.rectangle(x + 18, y + 96, w - 36, 1); c.fill()
    # phone silhouette
    px, py = x + 18, y + 12
    rrect(c, px, py, 25, 52, 5)
    c.set_source_rgba(1, 1, 1, 0.22); c.fill_preserve()
    c.set_source_rgba(1, 1, 1, 0.92); c.set_line_width(2.0); c.stroke()
    fill_rrect(c, px + 8.5, py + 46, 8, 2, 1, W(0.9))
    text(c, "Ruby's A24", x + 60, y + 23, 13, WHITE, 500)
    ic.icon(c, "chev_right", x + 244, y + 23, 15, WHITE, 2.0)
    ok = (0.45, 0.88, 0.80, 1)
    fill_rrect(c, x + 60, y + 38, 14, 8, 3, with_a(ok, 0.95)); stroke_rrect(c, x + 60, y + 38, 14, 8, 3, W(0.4), 0.8)
    text(c, "Connected", x + 79, y + 42.5, 10.5, (0.62, 0.92, 0.88, 1))
    c.save(); c.translate(x + 66, y + 62); c.rotate(-PI / 2)       # vertical battery glyph
    ic.battery(c, 0, 0, 16, W(0.9), 0.74); c.restore()
    text(c, "74%", x + 79, y + 62, 10.5, W(0.92))
    text(c, "2degrees 4G", x + 125, y + 62, 10.5, W(0.92))
    ic.icon(c, "stopwatch", x + 66, y + 83, 14, W(0.9), 1.5)
    text(c, "Silent", x + 79, y + 83, 10.5, W(0.92))
    # action tiles
    tiles = [("Notifications", "bell", 1258, 71, True), ("Send file", "sendfile", 1331, 58, False),
             ("File bin", "trash", 1392, 57, False), ("Clipboard", "clipboard", 1452, 59, False)]
    ty, th = y + 108, 62
    for label, icn, rx, tw, sel in tiles:
        tx = x + (rx - 1251)
        if sel:
            fill_rrect(c, tx, ty, tw, th, 13, lin(0, ty, 0, ty + th, [(0, (0.55, 0.62, 1.0, 0.42)), (1, (0.45, 0.50, 0.95, 0.30))]))
            stroke_rrect(c, tx, ty, tw, th, 13, W(0.28))
        else:
            fill_rrect(c, tx, ty, tw, th, 13, W(0.09))
            stroke_rrect(c, tx, ty, tw, th, 13, W(0.14))
        cx = tx + tw / 2.0
        if icn == "sendfile":
            fill_rrect(c, cx - 11, ty + 14, 22, 22, 6, (0.35, 0.55, 1.0, 0.55))
            ic.icon(c, icn, cx, ty + 25, 15, WHITE, 1.5)
        else:
            ic.icon(c, icn, cx, ty + 25, 19, W(0.96), 1.6)
        text(c, label, cx, ty + 48, 10, WHITE, 400, "c")
        if label == "Notifications":
            circle(c, tx + 55, ty + 17, 6.6); c.set_source_rgba(0.98, 0.35, 0.72, 1); c.fill()
            text(c, "3", tx + 55, ty + 17.3, 8.5, WHITE, 700, "c")


def _arc_ring(c, cx, cy, r, frac, lw, col_a, col_b):
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(lw)
    c.new_path()
    c.set_source_rgba(1, 1, 1, 0.20)
    c.arc(cx, cy, r, 0, 2 * PI); c.stroke()
    c.new_path()
    a0 = -PI / 2
    c.set_source(lin(cx - r, cy - r, cx + r, cy + r, [(0, col_a), (1, col_b)]))
    c.arc(cx, cy, r, a0, a0 + 2 * PI * frac); c.stroke()


def _system_card(c, g, t, x, y, w):
    _card(c, g, x, y, w, 140, "System", "chip")
    pink = (1.0, 0.55, 0.85, 1)
    rings = [(45, 0.12, "12%", "CPU", None, (1, 1, 1, 0.97), (1, 1, 1, 0.95)),
             (133, 0.26, "8.4 GB", "RAM", "8.4 GB / 32 GB", (1, 1, 1, 0.97), pink),
             (222, 0.42, "42%", "Disk", None, (0.86, 0.80, 1.0, 0.95), pink)]
    for ox, frac, val, lab, sub, ca, cb in rings:
        cx, cy = x + ox, y + 77
        _arc_ring(c, cx, cy, 28.5, frac, 5.5, ca, cb)
        text(c, val, cx, cy + 0.5, 13.5 if "GB" not in val else 12.5, WHITE, 400, "c")
        if sub:
            text(c, lab, cx, y + 109, 11, WHITE, 600, "c")
            text(c, sub, cx, y + 121, 8.5, W(0.75), 400, "c")
        else:
            text(c, lab, cx, y + 120, 11, W(0.95), 400, "c")


def _network_card(c, g, t, x, y, w):
    h = 129
    g.panel(c, x, y, w, h, 19, "card", shadow_alpha=0.26)
    ic.icon(c, "sparkle", x + 24, y + 19, 14, W(0.95))
    text(c, "Network", x + 48, y + 19, 11.5, WHITE, 500)
    ic.icon(c, "pin", x + 245, y + 20, 12, W(0.85), 1.5)
    for ry, icn, a, b in ((y + 38, "wifi", "Wi-Fi", "Connected | 524 Mbps"), (y + 83, "network", "Ethernet", "Not connected")):
        fill_rrect(c, x + 18, ry + 2, 26, 26, 9, W(0.08))
        ic.icon(c, icn, x + 31, ry + 15, 15, W(0.92), 1.4)
        text(c, a, x + 49, ry + 8, 11, WHITE, 400)
        text(c, b, x + 49, ry + 25, 10.5, W(0.78))
    # sparkline (Wi-Fi throughput)
    pts = [0.35, 0.42, 0.38, 0.45, 0.40, 0.44, 0.36, 0.42, 0.48, 0.40, 0.46, 0.38, 0.5, 0.44, 0.41, 0.55,
           0.47, 0.43, 0.92, 0.5, 0.58, 0.46, 0.52, 0.44, 0.50, 0.42, 0.56, 0.49, 0.46, 0.53]
    sx, sy, sw, sh = x + 167, y + 41, 83, 22
    path = [(sx + sw * i / (len(pts) - 1), sy + sh * (1 - v)) for i, v in enumerate(pts)]
    c.move_to(sx, sy + sh)
    for p in path:
        c.line_to(*p)
    c.line_to(sx + sw, sy + sh); c.close_path()
    c.set_source(lin(0, sy, 0, sy + sh, [(0, (0.35, 0.82, 1.0, 0.45)), (1, (0.35, 0.82, 1.0, 0.05))])); c.fill()
    c.move_to(*path[0])
    for p in path[1:]:
        c.line_to(*p)
    c.set_source_rgba(0.45, 0.88, 1.0, 0.95); c.set_line_width(1.2); c.set_line_join(cairo.LINE_JOIN_ROUND); c.stroke()


def _playing_card(c, g, t, x, y, w):
    h = 169
    _card(c, g, x, y, w, h, "Now Playing", "music")
    ic.icon(c, "plus", x + 246, y + 17, 11, W(0.30), 1.4)
    ic.album_art(c, x + 17, y + 37, 53, 56, 9)
    text(c, "FEVER DREAM", x + 85, y + 52, 12, WHITE, 500)
    text(c, "Alex Warren", x + 85, y + 70, 11, W(0.82))
    fill_rrect(c, x + 17, y + 99, 232, 4, 2, W(0.28))
    fill_rrect(c, x + 17, y + 99, 132, 4, 2, W(0.96))
    text(c, "2:34 / 4:12", x + 249, y + 111, 9.5, W(0.85), 400, "r")
    cy = y + 140
    ic.icon(c, "prev", x + 64, cy, 18, WHITE)
    circle(c, x + 134, cy, 21.5); c.set_source_rgba(1, 1, 1, 0.16); c.fill()
    c.set_source_rgba(1, 1, 1, 0.22); circle(c, x + 134, cy, 21.5); c.set_line_width(1); c.stroke()
    ic.icon(c, "pause", x + 134, cy, 18, WHITE)
    ic.icon(c, "next", x + 204, cy, 18, WHITE)


def _notif_card(c, g, t, x, y, w):
    h = 218
    g.panel(c, x, y, w, h, 19, "card", shadow_alpha=0.28)
    ic.icon(c, "sparkle", x + 24, y + 19, 14, W(0.95))
    text(c, "Notifications", x + 44, y + 18, 11.5, WHITE, 500)
    ic.icon(c, "bell", x + 225, y + 19, 12, W(0.30))
    ic.icon(c, "list", x + 245, y + 19, 13, W(0.85), 1.5)
    rows = [("Discord", "Ruby: hey! you free later?", "2m", ic.app_chat),
            ("System Update", "Updates are ready to install", "12m", ic.app_update),
            ("Spotify", "Added to your Liked Songs", "1h", ic.app_music)]
    for i, (a, b, tm, fn) in enumerate(rows):
        cy = y + 56 + i * 51
        fn(c, x + 34, cy, 29)
        text(c, a, x + 61, cy - 7, 11, WHITE, 500)
        text(c, b, x + 61, cy + 8, 10, W(0.78))
        text(c, tm, x + 249, cy - 7, 10.5, W(0.82), 400, "r")
        if i < 2:
            c.set_source_rgba(1, 1, 1, 0.13); c.rectangle(x + 18, cy + 25, w - 36, 1); c.fill()
    fill_rrect(c, x + 15, y + 184, w - 30, 26, 13, W(0.13))
    stroke_rrect(c, x + 15, y + 184, w - 30, 26, 13, W(0.14))
    text(c, "Clear all", x + w / 2.0, y + 197.5, 11, WHITE, 400, "c")
