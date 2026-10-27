"""First-party app mock-ups: SparkFiles, SparkSettings, SparkTerm (static artwork)."""
import math

import cairo

from . import icons as ic
from .gfx import (PI, circle, fill_rrect, inset, lin, rrect, rrect_var, stroke_rrect, text, with_a)

WHITE = (1, 1, 1, 1)
NAVY = (0.165, 0.176, 0.43, 1)          # text.on_light
NAVY_M = (0.40, 0.42, 0.68, 1)          # text.on_light_muted
PINK = (0.97, 0.47, 0.78, 1)


def W(a):
    return (1, 1, 1, a)


def navy(a=1.0):
    return (NAVY[0], NAVY[1], NAVY[2], a)


def _controls(c, cx_list, y, col, size=12.5, kinds=("minimize", "maximize", "close")):
    for cx, k in zip(cx_list, kinds):
        ic.icon(c, k, cx, y + 0.5, size, (0.1, 0.05, 0.4, 0.25), 2.4)       # soft contrast halo
        ic.icon(c, k, cx, y, size, col, 1.9)


# ============================================================ SparkFiles
FOLDERS = [
    ("Desktop", (0.64, 0.72, 1.0, 1), (0.40, 0.52, 0.98, 1), "monitor"),
    ("Documents", (0.98, 0.68, 1.0, 1), (0.84, 0.40, 0.95, 1), None),
    ("Downloads", (0.68, 0.88, 1.0, 1), (0.45, 0.72, 1.0, 1), None),
    ("Music", (0.82, 0.64, 1.0, 1), (0.66, 0.46, 0.95, 1), None),
    ("Pictures", (0.66, 0.70, 1.0, 1), (0.46, 0.52, 0.96, 1), None),
    ("Public", (0.58, 0.72, 1.0, 1), (0.38, 0.55, 0.98, 1), None),
    ("Templates", (0.86, 0.70, 1.0, 1), (0.68, 0.50, 0.95, 1), None),
    ("Videos", (0.54, 0.68, 1.0, 1), (0.36, 0.52, 0.98, 1), None),
]


def draw_sparkfiles(c, g, t, x, y):
    w, h = 540, 410
    g.panel(c, x, y, w, h, 22, "window_light", shadow_alpha=0.34)
    # --- title bar with tab
    fill_rrect(c, x + 6, y + 5, 126, 31, 13, W(0.22))
    ic.folder(c, x + 15, y + 11, 21, 18, (0.66, 0.76, 1, 1), (0.42, 0.56, 1, 1))
    text(c, "Home", x + 50, y + 18, 13, WHITE, 500)
    _controls(c, (x + 481, x + 512), y + 18, W(0.95), 13, ("minimize", "maximize"))
    # --- toolbar
    for ax, nm in ((24, "arrow_left"), (51, "arrow_right"), (77, "arrow_right")):
        ic.icon(c, nm, x + ax, y + 51, 14, W(0.75), 1.6)
    fill_rrect(c, x + 105, y + 37, 418, 28, 11, W(0.25))
    ic.icon(c, "arrow_left", x + 117, y + 51, 11, W(0.70), 1.8)
    ic.icon(c, "home", x + 139, y + 51, 14, NAVY, 1.7)
    text(c, "Home", x + 154, y + 51, 12, NAVY, 500)
    fill_rrect(c, x + 363, y + 40, 156, 22, 11, W(0.55))
    ic.icon(c, "search", x + 376, y + 51, 11, NAVY_M, 1.8)
    text(c, "Search files...", x + 389, y + 51, 10.5, NAVY_M)
    ic.icon(c, "arrow_up", x + 512, y + 51, 9, with_a(NAVY_M, 0.6), 1.8)
    # --- sidebar
    sx, sy = x + 7, y + 75
    inset(c, sx, sy, 148, 332, 14, W(0.20), W(0.26))
    fill_rrect(c, sx + 6, sy + 5, 137, 27, 10, (0.66, 0.74, 1.0, 0.65))
    items = [("home", "Home"), ("monitor", "Desktop"), ("doc", "Documents"), ("download", "Downloads"),
             ("music", "Music"), ("image", "Pictures"), ("film", "Videos"), ("trash", "Trash")]
    for i, (icn, lab) in enumerate(items):
        yy = y + 93 + i * 23.1
        ic.icon(c, icn, x + 30, yy, 13, NAVY, 1.7)
        text(c, lab, x + 50, yy, 11, NAVY, 500 if i == 0 else 400)
    text(c, "Devices", x + 23, y + 292, 11, navy(0.72))
    for yy, icn, lab, ej in ((y + 315, "laptop", "Linux (ext4)", True), (y + 338, "drive", "Data (ntfs)", False)):
        ic.icon(c, icn, x + 30, yy, 13, NAVY, 1.5)
        text(c, lab, x + 50, yy, 11, NAVY)
        if ej:
            ic.icon(c, "eject", x + 135, yy, 10, navy(0.55))
    # --- content
    cx0, cy0 = x + 162, y + 75
    inset(c, cx0, cy0, 370, 332, 14, W(0.34), W(0.30))
    cols = [206, 300, 392, 483]
    rows = [(y + 110, y + 143), (y + 197, y + 230)]
    for i, (name, top, bot, glyph) in enumerate(FOLDERS):
        fx = x + cols[i % 4]
        fy_icon, fy_lab = rows[i // 4]
        ic.folder(c, fx - 20, fy_icon - 18, 41, 36, top, bot)
        if glyph:
            ic.icon(c, glyph, fx + 0.5, fy_icon + 5, 14, W(0.85), 1.4)
        text(c, name, fx, fy_lab, 11, NAVY, 500, "c")
    text(c, "Recent", x + 175, y + 267, 12, NAVY, 600)
    c.set_source_rgba(1, 1, 1, 0.55); c.rectangle(x + 175, y + 281, 345, 1); c.fill()
    recent = [("homework.pdf", "2 hours ago", (1.0, 0.45, 0.62, 1), (0.93, 0.32, 0.55, 1), "PDF", None),
              ("trans_theme.png", "4 hours ago", (0.66, 0.58, 1.0, 1), (0.52, 0.42, 0.95, 1), None, "image"),
              ("project-logo.svg", "Yesterday", (0.35, 0.80, 1.0, 1), (0.22, 0.60, 0.98, 1), "SVG", None)]
    for i, (nm, tm, c1, c2, lab, gl) in enumerate(recent):
        yy = y + 300 + i * 43
        ic.file_icon(c, x + 178, yy - 10, 20, 24, c1, c2, lab, gl)
        text(c, nm, x + 215, yy - 4, 11, NAVY, 500)
        text(c, tm, x + 215, yy + 13, 9.5, NAVY_M)
        if i < 2:
            c.set_source_rgba(1, 1, 1, 0.42); c.rectangle(x + 175, yy + 24, 345, 1); c.fill()


# =========================================================== SparkSettings
def _cursor_glyph(c, cx, cy, s, fill, edge=None):
    pts = [(0, 0), (0, 14.5), (3.6, 11.2), (6.2, 17), (8.4, 16), (5.8, 10.4), (10.6, 10.4)]
    c.save(); c.translate(cx - 5.2 * s, cy - 8.5 * s); c.scale(s, s)
    c.move_to(*pts[0])
    for p in pts[1:]:
        c.line_to(*p)
    c.close_path()
    c.set_source_rgba(*fill); c.fill_preserve()
    if edge:
        c.set_source_rgba(*edge); c.set_line_width(1.0); c.set_line_join(cairo.LINE_JOIN_ROUND); c.stroke()
    else:
        c.new_path()
    c.restore()


def draw_sparksettings(c, g, t, x, y):
    w, h = 597, 387
    g.panel(c, x, y, w, h, 22, "window_glass", shadow_alpha=0.36)
    # title bar
    ic.sparkle_logo(c, x + 25, y + 16, 22, WHITE)
    text(c, "glitterDE Settings", x + 47, y + 15.5, 12, WHITE, 500)
    _controls(c, (x + 529, x + 554, x + 577), y + 16, W(0.95), 13)
    # sidebar
    sx, sy = x + 10, y + 33
    inset(c, sx, sy, 150, 345, 16, (0.62, 0.70, 1.0, 0.34), W(0.30))
    fill_rrect(c, x + 19, y + 41, 133, 25, 12.5, W(0.40))
    ic.icon(c, "search", x + 30, y + 53.5, 11, NAVY_M, 1.8)
    text(c, "Search settings...", x + 43, y + 53.5, 10.5, NAVY_M)
    ic.icon(c, "palette", x + 26, y + 81, 14, NAVY, 1.5)
    text(c, "Appearance", x + 43, y + 81, 11.5, NAVY, 600)
    ic.icon(c, "chev_up", x + 147, y + 81, 12, navy(0.7), 1.8)
    subs = [("Theme", 103), ("Colours", 125), ("Cursor", 146), ("Icons", 169), ("Fonts", 191),
            ("Animations", 213), ("Transparency", 236)]
    for lab, sy_ in subs:
        yy = y + sy_
        if lab == "Cursor":
            fill_rrect(c, x + 18, yy - 13, 132, 26, 9, (0.55, 0.62, 1.0, 0.45))
            fill_rrect(c, x + 18, yy - 11, 2.6, 22, 1.3, PINK)
        circle(c, x + 42, yy, 1.6); c.set_source_rgba(NAVY[0], NAVY[1], NAVY[2], 0.75); c.fill()
        text(c, lab, x + 50, yy, 10.2, NAVY, 500 if lab == "Cursor" else 400)
    for lab, yy, icn, chev in (("Desktop", 268, "monitor", "chev_right"), ("Windows", 296, "windows", "chev_right"),
                               ("Devices", 326, "monitor", "chev_down"), ("System", 356, "settings_gear_outline", None)):
        ic.icon(c, icn, x + 26, y + yy, 14, NAVY, 1.5)
        text(c, lab, x + 43, y + yy, 11, NAVY, 600)
        if chev:
            ic.icon(c, chev, x + 147, y + yy, 12, navy(0.7), 1.8)
    # content
    cx0, cy0 = x + 166, y + 33
    inset(c, cx0, cy0, 422, 345, 16, (0.92, 0.88, 1.0, 0.52), W(0.45))
    text(c, "Cursor", x + 177, y + 53, 16.5, NAVY, 600)
    inset(c, x + 177, y + 73, 401, 114, 14, W(0.30), W(0.42))
    text(c, "Cursor theme", x + 186, y + 87, 11, NAVY, 600)
    themes = [("Breeze", 332, PINK, None, True), ("Bibata Modern", 395, (0.12, 0.12, 0.18, 1), (1, 1, 1, 0.9), False),
              ("Adwaita", 460, (0.30, 0.32, 0.40, 1), None, False), ("DMZ-White", 526, (0.98, 0.98, 1, 1), (0.1, 0.1, 0.15, 1), False),
              ("DMZ-Black", 591, (0.08, 0.08, 0.12, 1), (1, 1, 1, 0.7), False), ("Custom...", 657, None, None, False)]
    for lab, tx, fcol, ecol, sel in themes:
        tcx = x + tx - 118
        if sel:
            fill_rrect(c, tcx - 29, y + 102, 58, 84, 12, lin(0, y + 102, 0, y + 186, [(0, (1, 0.86, 0.95, 0.75)), (0.72, (1, 0.82, 0.93, 0.6)), (0.73, (1, 0.74, 0.90, 0.75)), (1, (1, 0.74, 0.90, 0.75))]))
            stroke_rrect(c, tcx - 29, y + 102, 58, 84, 12, (1, 0.45, 0.78, 0.95), 1.6)
            _cursor_glyph(c, tcx, y + 131, 1.5, fcol, (1, 1, 1, 0.9))
            text(c, lab, tcx, y + 167, 9.5, NAVY, 600, "c")
        else:
            fill_rrect(c, tcx - 28, y + 103, 56, 56, 12, W(0.55))
            if fcol:
                _cursor_glyph(c, tcx, y + 131, 1.25, fcol, ecol)
            else:
                ic.icon(c, "plus", tcx, y + 131, 14, NAVY, 1.6)
            text(c, lab, tcx, y + 167, 9, NAVY_M, 400, "c")
    # size slider
    text(c, "Size", x + 177, y + 219, 12, NAVY, 600)
    _slider(c, x + 189, x + 520, y + 240, 0.78, PINK, big=True)
    text(c, "32", x + 551, y + 240, 10.5, NAVY)
    # toggle
    fill_rrect(c, x + 189, y + 272, 31, 17, 8.5, lin(0, 0, 31, 0, [(0, (1, 0.45, 0.80, 1)), (1, (1, 0.60, 0.88, 1))]))
    circle(c, x + 211.5, y + 280.5, 6.2); c.set_source_rgba(1, 1, 1, 1); c.fill()
    text(c, "Enlarge cursor when shaken", x + 228, y + 280.5, 11, NAVY)
    text(c, "Shake sensitivity", x + 188, y + 312, 11, navy(0.85))
    _slider(c, x + 189, x + 504, y + 334, 0.26, PINK, big=False)
    text(c, "Medium", x + 527, y + 334, 10.5, navy(0.85))


def _slider(c, x0, x1, cy, frac, col, big):
    th = 5 if big else 4.5
    fill_rrect(c, x0, cy - th / 2, x1 - x0, th, th / 2, (0.62, 0.62, 0.95, 0.38))
    kx = x0 + (x1 - x0) * frac
    fill_rrect(c, x0, cy - th / 2, kx - x0, th, th / 2, lin(x0, 0, kx, 0, [(0, (1, 0.72, 0.90, 1)), (1, (1, 0.58, 0.85, 1))]))
    if big:
        circle(c, kx, cy + 1, 8.5); c.set_source_rgba(0.3, 0.2, 0.6, 0.18); c.fill()
        circle(c, kx, cy, 8); c.set_source_rgba(1, 1, 1, 1); c.fill()
    else:
        circle(c, kx, cy, 6.5); c.set_source_rgba(1, 0.62, 0.88, 1); c.fill()
        circle(c, kx, cy, 6.5); c.set_source_rgba(1, 1, 1, 0.55); c.set_line_width(1.2); c.stroke()


# ============================================================== SparkTerm
def _swirl_art():
    """Procedural swirl (stand-in distro logo): thick ring, inner curl and a trailing tail."""
    cols, rows = 29, 17
    cw, ch = 5.42, 13.1
    cx, cy = 78.0, 70.0
    ramp = " .,:;ooO08@@"
    out = []
    R, th, R2 = 64.0, 15.0, 32.0
    ex, ey = cx + R * math.cos(1.05), cy + R * math.sin(1.05)          # ring end (lower right)
    tx, ty = cx + 96.0, cy + 168.0                                     # tail tip
    for r in range(rows):
        line = ""
        for q in range(cols):
            px, py = (q + 0.5) * cw, (r + 0.5) * ch
            dx, dy = px - cx, py - cy
            rad = math.hypot(dx, dy)
            ang = math.atan2(dy, dx)
            v = 0.0
            if not (-0.55 < ang < 0.95):                                # ring, open at the right
                v = max(v, 1.15 - abs(rad - R) / th * 1.1)
            if 0.0 < ang < 3.6 or ang < -2.7:                           # inner curl
                v = max(v, 1.0 - abs(rad - R2) / 7.0)
            sx, sy = tx - ex, ty - ey                                    # tail
            tt = max(0.0, min(1.0, ((px - ex) * sx + (py - ey) * sy) / (sx * sx + sy * sy)))
            dd = math.hypot(px - (ex + sx * tt), py - (ey + sy * tt))
            v = max(v, 1.1 - dd / (10.0 * (1.15 - 0.75 * tt)))
            idx = int(max(0.0, min(0.999, v)) * (len(ramp) - 1) + 0.5) if v > 0.22 else 0
            line += ramp[idx]
        out.append(line.rstrip())
    return out


ART = _swirl_art()


def draw_sparkterm(c, g, t, x, y):
    w, h = 459, 386
    g.panel(c, x, y, w, h, 20, "window_dark", shadow_alpha=0.38)
    # title bar
    circle(c, x + 17, y + 16, 8.5); c.set_source_rgba(1, 1, 1, 0.16); c.fill()
    ic.sparkle_logo(c, x + 17, y + 16, 13, (0.95, 0.80, 1, 1))
    text(c, "SparkTerm", x + 36, y + 16, 12, WHITE, 500)
    _controls(c, (x + 400, x + 422, x + 444), y + 16, W(0.92), 12.5)
    # tab strip
    fill_rrect(c, x + 8, y + 33, 443, 27, 12, W(0.07))
    fill_rrect(c, x + 12, y + 35, 156, 23, 11, W(0.12))
    ic.icon(c, "close", x + 27, y + 46.5, 8, W(0.95), 2.0)
    text(c, "ruby@cutiebox: ~", x + 46, y + 46.5, 10, W(0.90))
    ic.icon(c, "close", x + 145, y + 46.5, 7, W(0.45), 1.8)
    circle(c, x + 170, y + 46.5, 11); c.set_source_rgba(1, 1, 1, 0.13); c.fill()
    ic.icon(c, "plus", x + 170, y + 46.5, 12, WHITE, 1.8)
    fill_rrect(c, x + 434, y + 38, 16, 16, 5, W(0.14))
    circle(c, x + 442, y + 46, 3.2); c.set_source_rgba(1, 1, 1, 0.9); c.set_line_width(1.2); c.stroke()
    # text area (monospace)
    FS = 9.0
    lh = 13.1
    mx = x + 13
    ruby, at, dim = (0.72, 0.93, 0.46, 1), (0.52, 0.74, 1.0, 1), (0.80, 0.76, 1.0, 1)

    def prompt(yy, cmd=""):
        wd = 0
        wd += text(c, "ruby", mx, yy, FS, ruby, 700, mono=True)
        wd += text(c, "@cutiebox", mx + wd, yy, FS, at, 700, mono=True)
        wd += text(c, ":~$ ", mx + wd, yy, FS, dim, 400, mono=True)
        if cmd:
            text(c, cmd, mx + wd, yy, FS, W(0.95), 400, mono=True)
        return wd

    prompt(y + 74, "neofetch")
    ay = y + 98 - 1
    for i, ln in enumerate(ART):
        k = i / max(1, len(ART) - 1)
        col = (0.58 + 0.38 * k, 0.78 - 0.12 * k, 1.0, 0.95)
        text(c, ln, x + 22, ay + i * lh, FS, col, 500, mono=True)
    ix = x + 216
    key, val = (1.0, 0.64, 0.88, 1), (0.92, 0.88, 1.0, 1)
    text(c, "ruby@cutiebox", ix, y + 90, FS, (0.74, 0.70, 1.0, 1), 700, mono=True)
    c.set_source_rgba(0.74, 0.70, 1.0, 0.6); c.rectangle(ix, y + 97, 5.65 * 13, 1); c.fill()
    info = [("OS", "Debian GNU/Linux 13 (trixie) x86_64"), ("Host", "B860M GAMING X"), ("Kernel", "6.12.0-3-amd64"),
            ("Uptime", "2 hours, 14 mins"), ("Packages", "2487 (dpkg)"), ("Shell", "bash 5.2.37"),
            ("Resolution", "1920x1080"), ("DE", "glitterDE"), ("WM", "glitter-shell"),
            ("Theme", "Trans Pride (glitterDE)"), ("Icons", "glitter-icons"), ("Terminal", "SparkTerm"),
            ("CPU", "Intel Core Ultra 5 245K (14) @ 5.0GHz"), ("GPU", "Intel Arc Graphics"),
            ("Memory", "8.4GiB / 32GiB")]
    for i, (k_, v_) in enumerate(info):
        yy = y + 111 + i * lh
        wk = text(c, k_ + ":", ix, yy, FS, key, 700, mono=True)
        text(c, " " + v_, ix + wk, yy, FS, val, 400, mono=True)
    sw = [(0.98, 0.55, 0.85), (0.50, 0.62, 1.0), (0.66, 0.82, 1.0), (1.0, 0.60, 0.90),
          (0.72, 0.55, 0.98), (0.25, 0.78, 1.0), (0.70, 0.82, 1.0), (1.0, 0.68, 0.92)]
    for i, col in enumerate(sw):
        c.set_source_rgba(*col, 0.95); c.rectangle(ix + i * 19.8, y + 318, 19.8, 19); c.fill()
    prompt(y + 362)
    wd = text(c, "ruby@cutiebox:~$ ", mx, -100, FS, W(0), 400, mono=True)
    c.set_source_rgba(0.72, 0.58, 1.0, 1); c.rectangle(mx + wd + 2, y + 355, 6, 14); c.fill()
    fill_rrect(c, x + 453, y + 68, 3, 70, 1.5, W(0.22))
