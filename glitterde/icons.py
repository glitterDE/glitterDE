"""Procedural icon set ("glitter-icons" placeholder theme).

Line icons live on a 24x24 grid and are tinted by the caller (semantic colour);
coloured icons (folders, app tiles, file types) draw their own gradients.
All artwork is original; brand apps use generic stand-in glyphs.
"""
import math

import cairo

from .gfx import PI, circle, fill_rrect, lin, rrect, rrect_var, text

ROUND = cairo.LINE_CAP_ROUND


def _begin(c, cx, cy, s, col, lw):
    c.save()
    c.translate(cx - s / 2.0, cy - s / 2.0)
    c.scale(s / 24.0, s / 24.0)
    c.set_source_rgba(*col)
    c.set_line_width(lw)
    c.set_line_cap(ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)


def _poly(c, pts, close=False):
    c.move_to(*pts[0])
    for p in pts[1:]:
        c.line_to(*p)
    if close:
        c.close_path()


# ------------------------------------------------------------------ line icons
def _home(c):
    _poly(c, [(3, 11.5), (12, 3.5), (21, 11.5)]); c.stroke()
    _poly(c, [(5.5, 10), (5.5, 20), (10, 20), (10, 14.5), (14, 14.5), (14, 20), (18.5, 20), (18.5, 10)]); c.stroke()

def _monitor(c):
    rrect(c, 3, 4, 18, 12, 2.5); c.stroke()
    _poly(c, [(8, 20), (16, 20)]); c.stroke(); _poly(c, [(12, 16), (12, 20)]); c.stroke()

def _doc(c):
    rrect(c, 5.5, 3, 13, 18, 2.8); c.stroke()
    _poly(c, [(9, 10), (15, 10)]); c.stroke(); _poly(c, [(9, 14), (15, 14)]); c.stroke()

def _download(c):
    _poly(c, [(12, 4), (12, 14.5)]); c.stroke()
    _poly(c, [(8, 10.8), (12, 14.8), (16, 10.8)]); c.stroke()
    _poly(c, [(5, 15.5), (5, 19.5), (19, 19.5), (19, 15.5)]); c.stroke()

def _music(c):
    circle(c, 8, 17.5, 2.8); c.stroke()
    _poly(c, [(10.8, 17.5), (10.8, 5.5), (19, 3.5), (19, 15.5)]); c.stroke()
    circle(c, 16.2, 15.5, 2.8); c.stroke()

def _image(c):
    rrect(c, 3.5, 4.5, 17, 15, 3.2); c.stroke()
    circle(c, 9, 10, 1.6); c.stroke()
    _poly(c, [(4.5, 17.5), (9, 13.5), (13, 16.5), (16, 14), (19.5, 17)]); c.stroke()

def _film(c):
    rrect(c, 3.5, 5, 17, 14, 3.2); c.stroke()
    _poly(c, [(10, 9), (15.2, 12), (10, 15)], True); c.stroke()

def _trash(c):
    _poly(c, [(4, 7), (20, 7)]); c.stroke()
    _poly(c, [(9, 7), (9, 4.5), (15, 4.5), (15, 7)]); c.stroke()
    _poly(c, [(6, 7), (7, 20), (17, 20), (18, 7)]); c.stroke()
    _poly(c, [(10, 11), (10, 16)]); c.stroke(); _poly(c, [(14, 11), (14, 16)]); c.stroke()

def _laptop(c):
    rrect(c, 5, 5, 14, 10, 2.2); c.stroke(); _poly(c, [(3, 19), (21, 19)]); c.stroke()

def _drive(c):
    rrect(c, 4, 7, 16, 10, 2.8); c.stroke(); _poly(c, [(7.5, 14), (11, 14)]); c.stroke()
    circle(c, 16.5, 12, 0.5); c.stroke()

def _eject(c):
    _poly(c, [(6.5, 14), (12, 7.5), (17.5, 14)], True); c.fill()
    rrect(c, 6.5, 16.5, 11, 2.2, 1); c.fill()

def _search(c):
    circle(c, 10.5, 10.5, 6); c.stroke(); _poly(c, [(15, 15), (20, 20)]); c.stroke()

def _arrow_left(c):
    _poly(c, [(19, 12), (5, 12)]); c.stroke(); _poly(c, [(11, 6), (5, 12), (11, 18)]); c.stroke()

def _arrow_right(c):
    _poly(c, [(5, 12), (19, 12)]); c.stroke(); _poly(c, [(13, 6), (19, 12), (13, 18)]); c.stroke()

def _arrow_up(c):
    _poly(c, [(12, 19), (12, 5)]); c.stroke(); _poly(c, [(6, 11), (12, 5), (18, 11)]); c.stroke()

def _minimize(c):
    _poly(c, [(6, 12), (18, 12)]); c.stroke()

def _maximize(c):
    rrect(c, 9.5, 4.5, 10, 10, 2.5); c.stroke(); rrect(c, 4.5, 9.5, 10, 10, 2.5); c.stroke()

def _close(c):
    _poly(c, [(6, 6), (18, 18)]); c.stroke(); _poly(c, [(18, 6), (6, 18)]); c.stroke()

def _sparkle(c):
    c.move_to(12, 1.5)
    c.curve_to(12.9, 8.4, 15.6, 11.1, 22.5, 12)
    c.curve_to(15.6, 12.9, 12.9, 15.6, 12, 22.5)
    c.curve_to(11.1, 15.6, 8.4, 12.9, 1.5, 12)
    c.curve_to(8.4, 11.1, 11.1, 8.4, 12, 1.5)
    c.fill()

def _phone(c):
    rrect(c, 7, 2.5, 10, 19, 2.8); c.stroke(); _poly(c, [(10.5, 18.6), (13.5, 18.6)]); c.stroke()

def _bell(c):
    c.move_to(6.2, 17.2); c.curve_to(7.4, 15.6, 7.6, 13.4, 7.6, 11)
    c.curve_to(7.6, 8, 9.6, 6, 12, 6); c.curve_to(14.4, 6, 16.4, 8, 16.4, 11)
    c.curve_to(16.4, 13.4, 16.6, 15.6, 17.8, 17.2); c.close_path(); c.fill()
    c.move_to(10, 19.4); c.curve_to(10.6, 21, 13.4, 21, 14, 19.4); c.set_line_width(1.8); c.stroke()
    _poly(c, [(12, 3.6), (12, 6)]); c.stroke()

def _sendfile(c):
    rrect(c, 5, 3.5, 14, 17, 3.2); c.stroke()
    _poly(c, [(12, 16.5), (12, 9)]); c.stroke(); _poly(c, [(8.8, 12), (12, 8.8), (15.2, 12)]); c.stroke()

def _clipboard(c):
    rrect(c, 9.2, 7.6, 10, 13, 2.4); c.fill()
    rrect(c, 4.8, 3.4, 10, 13, 2.4); c.fill()

def _wifi(c):
    for r in (4.2, 8.2, 12.2):
        c.new_sub_path(); c.arc(12, 19, r, -3 * PI / 4, -PI / 4); c.stroke()
    circle(c, 12, 18.6, 1.1); c.fill()

def _bluetooth(c):
    _poly(c, [(7, 7.5), (17, 16.5), (12, 21), (12, 3), (17, 7.5), (7, 16.5)]); c.stroke()

def _volume(c):
    _poly(c, [(3.5, 9.6), (7.5, 9.6), (12.5, 5.4), (12.5, 18.6), (7.5, 14.4), (3.5, 14.4)], True); c.fill_preserve(); c.stroke()
    c.new_sub_path(); c.arc(12.5, 12, 4.4, -0.95, 0.95); c.stroke()
    c.new_sub_path(); c.arc(12.5, 12, 8, -0.95, 0.95); c.stroke()

def _brightness(c):
    circle(c, 12, 12, 3.9); c.stroke()
    for k in range(8):
        a = k * PI / 4
        c.move_to(12 + 7 * math.cos(a), 12 + 7 * math.sin(a)); c.line_to(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)); c.stroke()

def _cloud(c):
    c.move_to(7, 18); c.curve_to(4.5, 18, 3, 16.3, 3, 14.3); c.curve_to(3, 12.4, 4.5, 11, 6.3, 10.8)
    c.curve_to(6.8, 7.8, 9, 6, 12, 6); c.curve_to(15, 6, 17.2, 8, 17.7, 10.7)
    c.curve_to(19.8, 10.9, 21.5, 12.4, 21.5, 14.5); c.curve_to(21.5, 16.5, 19.9, 18, 17.8, 18); c.close_path(); c.fill()

def _chev_down(c):
    _poly(c, [(7, 9.5), (12, 14.5), (17, 9.5)]); c.stroke()

def _chev_up(c):
    _poly(c, [(7, 14.5), (12, 9.5), (17, 14.5)]); c.stroke()

def _chev_right(c):
    _poly(c, [(9.5, 7), (14.5, 12), (9.5, 17)]); c.stroke()

def _prev(c):
    rrect(c, 5, 5, 2.6, 14, 1.2); c.fill(); _poly(c, [(19, 5.2), (9.5, 12), (19, 18.8)], True); c.fill()

def _next(c):
    rrect(c, 16.4, 5, 2.6, 14, 1.2); c.fill(); _poly(c, [(5, 5.2), (14.5, 12), (5, 18.8)], True); c.fill()

def _play(c):
    _poly(c, [(7, 4.5), (19, 12), (7, 19.5)], True); c.fill()

def _check(c):
    _poly(c, [(5, 12.5), (10, 17.5), (19, 7)]); c.stroke()

def _pause(c):
    rrect(c, 6, 4.5, 4.2, 15, 1.6); c.fill(); rrect(c, 13.8, 4.5, 4.2, 15, 1.6); c.fill()

def _gear(c):
    pts = []
    for k in range(8):
        a = k * PI / 4
        for da, r in ((-0.30, 7.7), (-0.17, 10.3), (0.17, 10.3), (0.30, 7.7)):
            pts.append((12 + r * math.cos(a + da), 12 + r * math.sin(a + da)))
    _poly(c, pts, True)
    circle(c, 12, 12, 3.6)
    c.set_fill_rule(cairo.FILL_RULE_EVEN_ODD); c.fill()

def _grid(c):
    for gy in (6, 12, 18):
        for gx in (6, 12, 18):
            circle(c, gx, gy, 1.95); c.fill()

def _terminal(c):
    _poly(c, [(5.5, 7.5), (10.5, 12), (5.5, 16.5)]); c.stroke(); _poly(c, [(12.5, 17), (18.5, 17)]); c.stroke()

def _stopwatch(c):
    circle(c, 12, 13.5, 6.6); c.stroke(); _poly(c, [(12, 13.5), (12, 10)]); c.stroke(); _poly(c, [(10, 4.6), (14, 4.6)]); c.stroke()

def _chip(c):
    rrect(c, 6.5, 6.5, 11, 11, 2.6); c.stroke(); circle(c, 12, 12, 1.4); c.fill()
    for p in (9.5, 14.5):
        _poly(c, [(p, 3.5), (p, 6.5)]); c.stroke(); _poly(c, [(p, 17.5), (p, 20.5)]); c.stroke()
        _poly(c, [(3.5, p), (6.5, p)]); c.stroke(); _poly(c, [(17.5, p), (20.5, p)]); c.stroke()

def _network(c):
    for p in ((12, 6), (6, 17.5), (18, 17.5)):
        circle(c, *p, 2.3); c.stroke()
    _poly(c, [(12, 8.3), (12, 12.5), (6, 15.2)]); c.stroke(); _poly(c, [(12, 12.5), (18, 15.2)]); c.stroke()

def _power(c):
    c.new_sub_path(); c.arc(12, 13, 7.5, -PI / 2 + 0.75, -PI / 2 + 2 * PI - 0.75); c.stroke()
    _poly(c, [(12, 3.5), (12, 12)]); c.stroke()

def _plus(c):
    _poly(c, [(12, 5), (12, 19)]); c.stroke(); _poly(c, [(5, 12), (19, 12)]); c.stroke()

def _list(c):
    for y in (7, 12, 17):
        _poly(c, [(5, y), (19, y)]); c.stroke()

def _pin(c):
    rrect(c, 6, 6, 12, 12, 3.5); c.stroke(); _poly(c, [(9.5, 12), (14.5, 12)]); c.stroke()

def _star(c):
    pts = [(12 + (10 if k % 2 == 0 else 4.4) * math.cos(-PI / 2 + k * PI / 5),
            12 + (10 if k % 2 == 0 else 4.4) * math.sin(-PI / 2 + k * PI / 5)) for k in range(10)]
    _poly(c, pts, True); c.stroke()

def _palette(c):
    circle(c, 12, 12, 8.5); c.stroke(); circle(c, 8.5, 10.5, 1.1); c.fill(); circle(c, 12, 7.8, 1.1); c.fill(); circle(c, 15.6, 10.5, 1.1); c.fill()

def _cursor(c):
    _poly(c, [(7, 4), (7, 18.5), (10.8, 15), (13.4, 20.5), (15.6, 19.5), (13, 14.2), (18, 14)], True); c.stroke()

def _fonts(c):
    _poly(c, [(5, 19), (10, 5), (15, 19)]); c.stroke(); _poly(c, [(7, 14), (13, 14)]); c.stroke()

def _anim(c):
    circle(c, 8.5, 12, 4.5); c.stroke(); circle(c, 15.5, 12, 4.5); c.stroke()

def _drop(c):
    c.move_to(12, 4); c.curve_to(16, 9.5, 18, 12, 18, 14.5); c.curve_to(18, 18, 15.3, 20, 12, 20)
    c.curve_to(8.7, 20, 6, 18, 6, 14.5); c.curve_to(6, 12, 8, 9.5, 12, 4); c.stroke()

def _windows(c):
    rrect(c, 3.5, 6, 17, 13, 2.6); c.stroke(); _poly(c, [(3.5, 10), (20.5, 10)]); c.stroke()

def _settings_gear_outline(c):
    circle(c, 12, 12, 3.2); c.stroke(); circle(c, 12, 12, 8); c.stroke()


def _save(c):
    rrect(c, 4.5, 4.5, 15, 15, 3); c.stroke(); _poly(c, [(8, 4.5), (8, 9), (15, 9), (15, 4.5)]); c.stroke(); rrect(c, 8, 13, 8, 6.5, 1.2); c.stroke()

def _folder_line(c):
    _poly(c, [(3.5, 6.5), (9, 6.5), (11, 9), (20.5, 9), (20.5, 18.5), (3.5, 18.5)], True); c.stroke()

def _file_plus(c):
    _poly(c, [(6.5, 3.5), (14, 3.5), (18.5, 8), (18.5, 20.5), (6.5, 20.5)], True); c.stroke(); _poly(c, [(14, 3.5), (14, 8), (18.5, 8)]); c.stroke()
    _poly(c, [(12.5, 12), (12.5, 17)]); c.stroke(); _poly(c, [(10, 14.5), (15, 14.5)]); c.stroke()

def _code(c):
    _poly(c, [(8.5, 7.5), (4, 12), (8.5, 16.5)]); c.stroke(); _poly(c, [(15.5, 7.5), (20, 12), (15.5, 16.5)]); c.stroke()
    _poly(c, [(13.4, 5.5), (10.6, 18.5)]); c.stroke()

def _refresh(c):
    c.new_sub_path(); c.arc(12, 12, 7.5, 0.2 * PI, 1.65 * PI); c.stroke(); _poly(c, [(13.8, 1.6), (15.4, 5.3), (11.5, 6.2)]); c.stroke()

def _panel_left(c):
    rrect(c, 3.5, 5, 17, 14, 3); c.stroke(); _poly(c, [(9.5, 5), (9.5, 19)]); c.stroke()

def _collapse(c):
    _poly(c, [(7, 9.5), (12, 5), (17, 9.5)]); c.stroke(); _poly(c, [(7, 14.5), (12, 19), (17, 14.5)]); c.stroke()


ICONS = {k[1:]: v for k, v in list(globals().items()) if k.startswith("_") and not k.startswith("__") and callable(v)
         and k not in ("_begin", "_poly")}


def icon(c, name, cx, cy, s, col, lw=1.7):
    _begin(c, cx, cy, s, col, lw)
    ICONS[name](c)
    c.restore()


def battery(c, cx, cy, s, col, pct=0.74):
    _begin(c, cx, cy, s, col, 1.6)
    rrect(c, 2.5, 6.5, 17, 11, 3.2); c.stroke()
    rrect(c, 20.6, 10.2, 1.8, 3.6, 0.9); c.fill()
    rrect(c, 4.6, 8.6, 12.8 * pct, 6.8, 1.5); c.fill()
    c.restore()


def sparkle_logo(c, cx, cy, s, col):
    """glitterDE mark: big four-point sparkle with a small companion + dots."""
    _begin(c, cx, cy, s, col, 1)
    c.save(); c.translate(-1.2, 1.4); c.scale(0.80, 0.80); c.translate(2.4, -2.9)
    _sparkle(c); c.restore()
    c.save(); c.translate(15.6, 1.2); c.scale(0.36, 0.36); _sparkle(c); c.restore()
    circle(c, 3.4, 20.6, 0.9); c.fill(); circle(c, 21.2, 17.2, 0.8); c.fill()
    c.restore()


# -------------------------------------------------------------- coloured icons
def folder(c, x, y, w, h, top, bot, glow=True):
    """Soft pastel folder: tab, back plate, glossy front."""
    r = h * 0.16
    dark = tuple(max(0, v * 0.90) for v in bot[:3]) + (1,)
    rrect_var(c, x, y, w * 0.46, h * 0.30, r * 0.9, r * 1.4, 0, 0)
    c.set_source(lin(x, y, x, y + h, [(0, dark), (1, dark)])); c.fill()
    fill_rrect(c, x, y + h * 0.10, w, h * 0.86, r, lin(x, y, x, y + h, [(0, dark), (1, bot)]))
    fy = y + h * 0.28
    fill_rrect(c, x, fy, w, h - (fy - y), r, lin(x, fy, x + w * 0.3, y + h, [(0, top), (1, bot)]))
    # glossy edge + inner glow
    rrect(c, x + 0.5, fy + 0.5, w - 1, h - (fy - y) - 1, r)
    c.set_source_rgba(1, 1, 1, 0.55); c.set_line_width(1.0); c.stroke()
    c.set_source(lin(x, fy, x, fy + 8, [(0, (1, 1, 1, 0.45)), (1, (1, 1, 1, 0))]))
    rrect(c, x + 1, fy + 1, w - 2, 8, r); c.fill()


def squircle(c, x, y, s, c1, c2, r=None, gloss=True):
    r = s * 0.30 if r is None else r
    fill_rrect(c, x, y, s, s, r, lin(x, y, x + s * 0.4, y + s, [(0, c1), (1, c2)]))
    if gloss:
        c.save(); rrect(c, x, y, s, s, r); c.clip()
        c.set_source(lin(x, y, x, y + s * 0.5, [(0, (1, 1, 1, 0.35)), (1, (1, 1, 1, 0))]))
        c.rectangle(x, y, s, s * 0.5); c.fill(); c.restore()


def trash_color(c, cx, cy, s):
    w = s * 0.62; h = s * 0.66; x = cx - w / 2; y = cy - h / 2 + s * 0.08
    lid_y = y - s * 0.12
    # handle
    rrect(c, cx - s * 0.12, lid_y - s * 0.09, s * 0.24, s * 0.12, s * 0.05)
    c.set_source_rgba(0.80, 0.62, 1.0, 1); c.fill()
    fill_rrect(c, cx - w * 0.62, lid_y, w * 1.24, s * 0.12, s * 0.06, lin(0, lid_y, 0, lid_y + s * 0.12, [(0, (0.86, 0.72, 1, 1)), (1, (0.70, 0.52, 0.98, 1))]))
    rrect_var(c, x, y + s * 0.02, w, h, 0, 0, s * 0.12, s * 0.12)
    c.set_source(lin(x, y, x + w, y + h, [(0, (0.80, 0.62, 1.0, 1)), (1, (0.52, 0.40, 0.95, 1))])); c.fill()
    for k in (-1, 0, 1):
        fill_rrect(c, cx + k * w * 0.24 - s * 0.025, y + h * 0.28, s * 0.05, h * 0.46, s * 0.025, (0.22, 0.14, 0.55, 0.85))


def star_blob(c, cx, cy, s):
    pts = []
    n = 5
    for k in range(n * 2):
        r = s * (0.50 if k % 2 == 0 else 0.30)
        pts.append((cx + r * math.cos(-PI / 2 + k * PI / n), cy + r * math.sin(-PI / 2 + k * PI / n)))
    c.save()
    # rounded star via thick round-joined stroke + fill
    c.set_line_join(cairo.LINE_JOIN_ROUND); c.set_line_width(s * 0.16)
    _poly(c, pts, True)
    g = lin(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, [(0, (0.98, 0.70, 1.0, 1)), (1, (0.62, 0.42, 0.96, 1))])
    c.set_source(g); c.fill_preserve(); c.stroke()
    # inner small star
    ip = []
    for k in range(10):
        r = s * (0.15 if k % 2 == 0 else 0.07)
        ip.append((cx + r * math.cos(-PI / 2 + k * PI / 5), cy + s * 0.02 + r * math.sin(-PI / 2 + k * PI / 5)))
    _poly(c, ip, True); c.set_source_rgba(0.28, 0.20, 0.62, 0.95); c.fill()
    c.restore()


def cloud_tile(c, x, y, s):
    squircle(c, x, y, s, (0.62, 0.80, 1.0, 1), (0.40, 0.58, 1.0, 1))
    icon(c, "cloud", x + s / 2, y + s / 2 - s * 0.02, s * 0.62, (1, 1, 1, 0.97))
    icon(c, "download", x + s / 2 + s * 0.04, y + s / 2 + s * 0.04, s * 0.26, (0.35, 0.5, 0.95, 1), 2.6)


def file_icon(c, x, y, w, h, c1, c2, label=None, glyph=None):
    r = w * 0.20
    fill_rrect(c, x, y, w, h, r, lin(x, y, x, y + h, [(0, c1), (1, c2)]))
    c.save(); rrect(c, x, y, w, h, r); c.clip()
    c.set_source(lin(x, y, x, y + h * 0.5, [(0, (1, 1, 1, 0.30)), (1, (1, 1, 1, 0))])); c.rectangle(x, y, w, h * 0.5); c.fill(); c.restore()
    if label:
        text(c, label, x + w / 2, y + h * 0.5, w * 0.30, (1, 1, 1, 0.98), 700, "c")
    if glyph:
        icon(c, glyph, x + w / 2, y + h / 2, w * 0.60, (1, 1, 1, 0.95), 1.9)


def album_art(c, x, y, w, h, r):
    c.save(); rrect(c, x, y, w, h, r); c.clip()
    c.set_source(lin(x, y, x + w, y + h, [(0, (0.98, 0.52, 0.72, 1)), (0.45, (0.55, 0.45, 0.9, 1)), (1, (0.10, 0.12, 0.30, 1))]))
    c.rectangle(x, y, w, h); c.fill()
    c.set_source_rgba(1, 0.85, 0.9, 0.55); c.arc(x + w * 0.64, y + h * 0.30, w * 0.20, 0, 2 * PI); c.fill()
    c.set_source_rgba(0.06, 0.07, 0.22, 0.95)                   # rocky silhouette
    _poly(c, [(x, y + h), (x, y + h * 0.62), (x + w * 0.22, y + h * 0.52), (x + w * 0.40, y + h * 0.70),
              (x + w * 0.58, y + h * 0.44), (x + w * 0.78, y + h * 0.64), (x + w, y + h * 0.5), (x + w, y + h)], True)
    c.fill()
    c.set_source_rgba(1, 0.9, 0.95, 0.9); c.arc(x + w * 0.5, y + h * 0.38, w * 0.04, 0, 2 * PI); c.fill()
    c.restore()


# ----------------------------------------------------------------------- apps
def app_launcher(c, cx, cy, s, bright=True):
    x, y = cx - s / 2, cy - s / 2
    if bright:
        squircle(c, x, y, s, (0.70, 0.45, 0.98, 1), (0.55, 0.40, 0.92, 1), s * 0.26)
    else:
        squircle(c, x, y, s, (0.60, 0.55, 0.92, 0.9), (0.50, 0.46, 0.85, 0.9), s * 0.26, gloss=False)
    icon(c, "grid", cx, cy, s * 0.52, (1, 1, 1, 0.95))


def app_browser(c, cx, cy, s):
    r = s * 0.5
    c.set_source(lin(cx + r, cy - r, cx - r, cy + r, [(0, (1.0, 0.80, 0.22, 1)), (0.45, (1.0, 0.42, 0.40, 1)), (1, (0.95, 0.20, 0.60, 1))]))
    circle(c, cx, cy, r); c.fill()
    c.set_source(lin(cx, cy - r * 0.6, cx, cy + r * 0.8, [(0, (0.55, 0.40, 1.0, 1)), (1, (0.35, 0.22, 0.85, 1))]))
    circle(c, cx - r * 0.05, cy + r * 0.12, r * 0.52); c.fill()
    c.set_source_rgba(1, 1, 1, 0.28); c.arc(cx - r * 0.1, cy - r * 0.05, r * 0.30, PI, 1.7 * PI); c.set_line_width(s * 0.07); c.stroke()
    c.set_source_rgba(1, 0.75, 0.25, 0.95); c.move_to(cx + r * 0.1, cy - r * 0.95)
    c.curve_to(cx + r * 0.9, cy - r * 0.8, cx + r * 1.0, cy + r * 0.1, cx + r * 0.55, cy - r * 0.15)
    c.curve_to(cx + r * 0.7, cy - r * 0.5, cx + r * 0.4, cy - r * 0.8, cx + r * 0.1, cy - r * 0.95); c.fill()


def app_music(c, cx, cy, s):
    r = s * 0.5
    c.set_source(lin(cx, cy - r, cx, cy + r, [(0, (0.30, 0.90, 0.45, 1)), (1, (0.12, 0.72, 0.40, 1))]))
    circle(c, cx, cy, r); c.fill()
    c.set_source_rgba(0.06, 0.18, 0.12, 0.92); c.set_line_cap(ROUND)
    for i, (w_, dy) in enumerate(((0.62, -0.20), (0.52, 0.0), (0.42, 0.19))):
        c.set_line_width(s * 0.085)
        c.new_sub_path(); c.arc(cx, cy + r * dy + r * 0.55, r * w_ * 1.3, -PI * 0.80, -PI * 0.20); c.stroke()


def app_chat(c, cx, cy, s):
    x, y = cx - s / 2, cy - s / 2
    squircle(c, x, y, s, (0.52, 0.58, 1.0, 1), (0.34, 0.40, 0.95, 1), s * 0.30)
    c.set_source_rgba(1, 1, 1, 0.98)
    rrect(c, cx - s * 0.30, cy - s * 0.20, s * 0.60, s * 0.42, s * 0.16); c.fill()
    _poly(c, [(cx - s * 0.12, cy + s * 0.18), (cx - s * 0.22, cy + s * 0.32), (cx + s * 0.02, cy + s * 0.2)], True); c.fill()
    c.set_source_rgba(0.36, 0.42, 0.95, 1)
    circle(c, cx - s * 0.11, cy + s * 0.01, s * 0.055); c.fill(); circle(c, cx + s * 0.11, cy + s * 0.01, s * 0.055); c.fill()


def app_files(c, cx, cy, s):
    folder(c, cx - s * 0.5, cy - s * 0.42, s, s * 0.86, (0.72, 0.84, 1.0, 1), (0.50, 0.66, 1.0, 1))


def app_terminal(c, cx, cy, s):
    x, y = cx - s / 2, cy - s / 2
    fill_rrect(c, x, y, s, s, s * 0.22, lin(x, y, x, y + s, [(0, (0.20, 0.20, 0.26, 1)), (1, (0.11, 0.11, 0.16, 1))]))
    icon(c, "terminal", cx - s * 0.02, cy, s * 0.62, (1, 1, 1, 0.95), 2.4)


def app_settings(c, cx, cy, s):
    x, y = cx - s / 2, cy - s / 2
    squircle(c, x, y, s, (0.58, 0.68, 1.0, 1), (0.38, 0.50, 0.98, 1), s * 0.28)
    icon(c, "gear", cx, cy, s * 0.66, (1, 1, 1, 0.97))


def app_code(c, cx, cy, s):
    x, y = cx - s / 2, cy - s / 2
    squircle(c, x, y, s, (1.0, 0.70, 0.88, 1), (0.71, 0.48, 1.0, 1), s * 0.28)
    icon(c, "code", cx, cy, s * 0.66, (1, 1, 1, 0.97), 2.3)


def app_update(c, cx, cy, s):
    x, y = cx - s / 2, cy - s / 2
    squircle(c, x, y, s, (1.0, 0.55, 0.85, 1), (0.95, 0.38, 0.78, 1), s * 0.30)
    c.set_source_rgba(1, 1, 1, 0.97); c.set_line_width(s * 0.09); c.set_line_cap(ROUND)
    c.new_sub_path(); c.arc(cx, cy, s * 0.22, PI * 0.15, PI * 1.55); c.stroke()
    _poly(c, [(cx - s * 0.30, cy - s * 0.12), (cx - s * 0.14, cy - s * 0.22), (cx - s * 0.12, cy - s * 0.02)], True); c.fill()
