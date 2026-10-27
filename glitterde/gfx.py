"""Rendering primitives: rounded shapes, text, blur pyramid and the glass material.

Pure cairo + PangoCairo (no Gtk import) so scenes can be rendered headless.
Pipeline:
    wallpaper -> blur cache -> tint -> sheen/noise -> rounded mask -> rim light
"""
import math
import os

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

PI = math.pi
_WEIGHTS = {300: Pango.Weight.LIGHT, 400: Pango.Weight.NORMAL, 500: Pango.Weight.MEDIUM,
            600: Pango.Weight.SEMIBOLD, 700: Pango.Weight.BOLD}


# --------------------------------------------------------------------- shapes
def rrect(c, x, y, w, h, r):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -PI / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, PI / 2)
    c.arc(x + r, y + h - r, r, PI / 2, PI)
    c.arc(x + r, y + r, r, PI, 1.5 * PI)
    c.close_path()


def rrect_var(c, x, y, w, h, tl, tr, br, bl):
    """Rounded rect with per-corner radii."""
    c.new_sub_path()
    c.arc(x + w - tr, y + tr, tr, -PI / 2, 0)
    c.arc(x + w - br, y + h - br, br, 0, PI / 2)
    c.arc(x + bl, y + h - bl, bl, PI / 2, PI)
    c.arc(x + tl, y + tl, tl, PI, 1.5 * PI)
    c.close_path()


def lin(x0, y0, x1, y1, stops):
    p = cairo.LinearGradient(x0, y0, x1, y1)
    for pos, col in stops:
        p.add_color_stop_rgba(pos, *col)
    return p


def fill_rrect(c, x, y, w, h, r, src):
    rrect(c, x, y, w, h, r)
    c.set_source(src) if not isinstance(src, tuple) else c.set_source_rgba(*src)
    c.fill()


def stroke_rrect(c, x, y, w, h, r, src, lw=1.0):
    rrect(c, x + lw / 2, y + lw / 2, w - lw, h - lw, r - lw / 2)
    c.set_source(src) if not isinstance(src, tuple) else c.set_source_rgba(*src)
    c.set_line_width(lw)
    c.stroke()


def with_a(col, a):
    return (col[0], col[1], col[2], a)


def mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(min(len(a), len(b))))


def circle(c, cx, cy, r):
    c.new_sub_path()
    c.arc(cx, cy, r, 0, 2 * PI)


# ----------------------------------------------------------------------- text
class Fonts:
    ui = "Inter, Noto Sans, Cantarell, DejaVu Sans"
    mono = "JetBrains Mono, DejaVu Sans Mono, monospace"


def text(c, s, x, y, size, color, weight=400, anchor="l", mono=False, shadow=None, family=None,
         spacing=0.0, max_w=None):
    """Draw text with its vertical centre on y. anchor: l | c | r. size is in px."""
    lay = PangoCairo.create_layout(c)
    fd = Pango.FontDescription()
    fd.set_family(family or (Fonts.mono if mono else Fonts.ui))
    fd.set_absolute_size(size * Pango.SCALE)
    fd.set_weight(_WEIGHTS.get(weight, Pango.Weight.NORMAL))
    lay.set_font_description(fd)
    lay.set_text(s, -1)
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        lay.set_attributes(attrs)
    if max_w:
        lay.set_width(int(max_w * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    w, h = lay.get_pixel_size()
    ox = x if anchor == "l" else x - w / 2.0 if anchor == "c" else x - w
    oy = y - h / 2.0
    if shadow:
        c.move_to(ox + shadow[0], oy + shadow[1])
        c.set_source_rgba(*shadow[2])
        PangoCairo.show_layout(c, lay)
    c.move_to(ox, oy)
    c.set_source_rgba(*color)
    PangoCairo.show_layout(c, lay)
    return w


def text_width(c, s, size, weight=400, mono=False):
    lay = PangoCairo.create_layout(c)
    fd = Pango.FontDescription()
    fd.set_family(Fonts.mono if mono else Fonts.ui)
    fd.set_absolute_size(size * Pango.SCALE)
    fd.set_weight(_WEIGHTS.get(weight, Pango.Weight.NORMAL))
    lay.set_font_description(fd)
    lay.set_text(s, -1)
    return lay.get_pixel_size()[0]


# ----------------------------------------------------------------- wallpaper
def load_image(path):
    """Return a cairo ImageSurface for a PNG (or anything Pillow can read)."""
    try:
        return cairo.ImageSurface.create_from_png(path)
    except Exception:
        from PIL import Image  # optional dependency for jpg/webp wallpapers
        im = Image.open(path).convert("RGBA")
        r, g, b, a = im.split()
        data = bytearray(Image.merge("RGBA", (b, g, r, a)).tobytes())
        return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, im.width, im.height)


def cover_monitors(src, W, H, mons, scale=1):
    """Wallpaper for a multi-monitor desktop: the image is fitted to EACH monitor (mons = [(x, y, w, h), ...]), not stretched
    across the whole root. One monitor (or none known) gives the same result as cover()."""
    if len(mons) <= 1:
        return cover(src, int(W * scale), int(H * scale))
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(W * scale), int(H * scale))
    c = cairo.Context(out)
    c.set_source_rgb(0.09, 0.075, 0.16); c.paint()
    for x, y, w, h in mons:
        part = cover(src, int(w * scale), int(h * scale))
        c.set_source_surface(part, int(x * scale), int(y * scale)); c.paint()
    return out


_xdisp = None


def gdk_monitors():
    """[(x, y, w, h), ...] primary first. Prefers the layout the window manager publishes on the root window
    (_GLITTER_MONITORS), because GDK cannot see Xinerama-only setups such as a two-screen Xephyr; falls back to GDK."""
    try:
        global _xdisp
        if _xdisp is None:
            from Xlib import display as _xd
            _xdisp = _xd.Display()
        d = _xdisp
        pr = d.screen().root.get_full_property(d.intern_atom("_GLITTER_MONITORS"), 0)
        if pr is not None and len(pr.value) >= 4:
            v = [int(x) for x in pr.value]
            mons = [tuple(v[i:i + 4]) for i in range(0, len(v) - len(v) % 4, 4)]
            if all(m[2] > 0 and m[3] > 0 for m in mons):
                return mons
    except Exception:
        _xdisp = None
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
        d = Gdk.Display.get_default()
        out = []
        for i in range(d.get_n_monitors()):
            m = d.get_monitor(i); g = m.get_geometry()
            out.append((not m.is_primary(), (g.x, g.y, g.width, g.height)))
        out.sort(key=lambda t: t[0])
        if out:
            return [g for _, g in out]
    except Exception:
        pass
    return [(0, 0, 0, 0)]


def cover(src, pw, ph, mode=None):
    """Fit an image to pw x ph pixels. mode: cover (crop) | fit (letterbox) | center | stretch."""
    if mode is None:
        from . import settings_model
        mode = settings_model.get("desktop.wallpaper_fit")
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
    c = cairo.Context(out)
    c.set_source_rgb(0.09, 0.075, 0.16)
    c.paint()
    iw, ih = src.get_width(), src.get_height()
    if mode == "stretch":
        sx, sy = pw / iw, ph / ih
    elif mode == "fit":
        sx = sy = min(pw / iw, ph / ih)
    elif mode == "center":
        sx = sy = 1.0
    else:
        sx = sy = max(pw / iw, ph / ih)
    c.translate((pw - iw * sx) / 2, (ph - ih * sy) / 2)
    c.scale(sx, sy)
    c.set_source_surface(src, 0, 0)
    c.get_source().set_filter(cairo.FILTER_BEST)
    c.paint()
    return out


# ---------------------------------------------------------------------- blur
def _resample(src, w, h):
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
    c = cairo.Context(out)
    c.scale(out.get_width() / src.get_width(), out.get_height() / src.get_height())
    c.set_source_surface(src, 0, 0)
    p = c.get_source()
    p.set_filter(cairo.FILTER_BILINEAR if out.get_width() < src.get_width() else cairo.FILTER_BEST)
    p.set_extend(cairo.EXTEND_PAD)
    c.paint()
    return out


def blur(src, radius):
    """Pyramid blur: repeated 2x box down-sampling then smooth up-sampling."""
    if radius <= 1:
        return src
    n = max(1, min(6, int(round(math.log2(radius))) - 1))
    sizes = [(src.get_width(), src.get_height())]
    cur = src
    for _ in range(n):
        w, h = max(1, cur.get_width() // 2), max(1, cur.get_height() // 2)
        cur = _resample(cur, w, h)
        sizes.append((w, h))
    # extra softening at the smallest level
    for _ in range(2):
        cur = _resample(_resample(cur, max(1, cur.get_width() * 3 // 4), max(1, cur.get_height() * 3 // 4)),
                        cur.get_width(), cur.get_height())
    for w, h in reversed(sizes[:-1]):
        cur = _resample(cur, w, h)
    return cur


_KEEP = []


def noise_tile(n=128):
    data = bytearray(n * n * 4)
    rnd = os.urandom(n * n)
    for i in range(n * n):
        v = rnd[i]
        v = v if v > 150 else 0          # sparse speckle
        a = v // 8
        data[i * 4:i * 4 + 4] = bytes((a, a, a, a))   # premultiplied white
    surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, n, n)
    _KEEP.append(data)                      # pycairo does not own the buffer
    return surf


# --------------------------------------------------------------------- glass
class Glass:
    """Frosted-glass material renderer. `wall` is the full-canvas wallpaper surface
    (physical pixels) and `scale` the device scale mapping logical->physical."""

    def __init__(self, theme, wall, scale, cache_key=None):
        self.theme = theme
        self.scale = scale
        self.wall = wall
        self.cache_key = cache_key
        self._blurred = {}
        self._noise = noise_tile()

    def blurred(self, radius):
        key = int(radius)
        if key not in self._blurred:
            cf = None
            if self.cache_key:
                import hashlib
                d = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "glitterde")
                os.makedirs(d, exist_ok=True)
                cf = os.path.join(d, "blur-%s-%d.png" % (hashlib.md5(repr(self.cache_key).encode()).hexdigest()[:12], key))
                if os.path.exists(cf):
                    try:
                        b = cairo.ImageSurface.create_from_png(cf)
                        b.set_device_scale(self.scale, self.scale)
                        self._blurred[key] = b
                        return b
                    except Exception:
                        pass
            b = blur(self.wall, radius * self.scale)
            if cf:
                try:
                    b.write_to_png(cf)
                except Exception:
                    pass
            b.set_device_scale(self.scale, self.scale)
            self._blurred[key] = b
        return self._blurred[key]

    # drop shadow that never darkens the translucent body (clipped out)
    def shadow(self, c, x, y, w, h, r, blur_r=26, dy=10, alpha=0.30, color=(0.08, 0.03, 0.30)):
        c.save()
        pad = blur_r * 2 + 40
        c.rectangle(x - pad, y - pad, w + 2 * pad, h + 2 * pad + dy)
        rrect(c, x, y, w, h, r)
        c.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        c.clip()
        steps = 14
        for i in range(steps):
            g = blur_r * (1 - i / steps)
            a = alpha / steps * 1.9
            rrect(c, x - g, y - g + dy, w + 2 * g, h + 2 * g, r + g)
            c.set_source_rgba(color[0], color[1], color[2], a)
            c.fill()
        c.restore()

    def panel(self, c, x, y, w, h, r, material, shadow=True, shadow_alpha=0.30, rim=True,
              rr=None, tint_override=None, opacity_scale=1.0):
        m = self.theme.material(material)
        if shadow:
            self.shadow(c, x, y, w, h, r, alpha=shadow_alpha)
        c.save()
        if rr:
            rrect_var(c, x, y, w, h, *rr)
        else:
            rrect(c, x, y, w, h, r)
        c.clip()
        # 1. blurred backdrop
        if m["blur"] > 0:
            c.set_source_surface(self.blurred(m["blur"]), 0, 0)
            c.paint()
        else:
            c.set_source_surface(self.wall, 0, 0)
            c.paint_with_alpha(0.0)
        # 2. tint (slightly stronger at top for depth)
        tr, tg, tb = tint_override or m["tint"]
        op = m["opacity"] * opacity_scale
        c.set_source(lin(0, y, 0, y + h, [(0, (tr, tg, tb, min(1, op * 1.08))),
                                         (1, (tr, tg, tb, op * 0.94))]))
        c.rectangle(x, y, w, h)
        c.fill()
        # 3. sheen: diagonal specular wash
        if m["sheen"] > 0:
            c.set_source(lin(x, y, x + w * 0.9, y + h * 0.9,
                             [(0, (1, 1, 1, m["sheen"])), (0.45, (1, 1, 1, m["sheen"] * 0.25)),
                              (1, (1, 1, 1, 0))]))
            c.rectangle(x, y, w, h)
            c.fill()
        # 4. noise / grain
        if m["noise"] > 0:
            c.save()
            c.translate(x, y)
            c.set_source_surface(self._noise, 0, 0)
            c.get_source().set_extend(cairo.EXTEND_REPEAT)
            c.rectangle(0, 0, w, h)
            c.clip()
            c.paint_with_alpha(min(1.0, m["noise"] * 6))
            c.restore()
        c.restore()
        # 5. rim light
        if rim:
            self.rim(c, x, y, w, h, r, m["border"], m["border_opacity"], rr)

    def rim(self, c, x, y, w, h, r, color, a, rr=None):
        col = color
        grad = lin(x, y, x + w, y + h, [(0, (col[0], col[1], col[2], min(1, a * 1.15))),
                                         (0.5, (col[0], col[1], col[2], a * 0.45)),
                                         (1, (0.72, 0.88, 1.0, a * 0.95))])
        if rr:
            rrect_var(c, x + .5, y + .5, w - 1, h - 1, *[max(0, v - .5) for v in rr])
        else:
            rrect(c, x + .5, y + .5, w - 1, h - 1, r - .5)
        c.set_source(grad)
        c.set_line_width(1.2)
        c.stroke()
        # inner soft highlight
        rrect(c, x + 2, y + 2, w - 4, h - 4, max(0, r - 2))
        c.set_source_rgba(1, 1, 1, a * 0.16)
        c.set_line_width(1.0)
        c.stroke()


# ------------------------------------------------------------- inset helpers
def inset(c, x, y, w, h, r, fill, border=None, lw=1.0):
    """Plain translucent inner surface (no backdrop sampling)."""
    fill_rrect(c, x, y, w, h, r, fill)
    if border:
        stroke_rrect(c, x, y, w, h, r, border, lw)


def soft_glow(c, cx, cy, r, color, a=0.5):
    p = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
    p.add_color_stop_rgba(0, color[0], color[1], color[2], a)
    p.add_color_stop_rgba(1, color[0], color[1], color[2], 0)
    c.set_source(p)
    c.arc(cx, cy, r, 0, 2 * PI)
    c.fill()


def comp_glass(cr, w, h, r, m, opacity_scale=1.0, corners=None, sheen=True):
    """Translucent glass for use under a compositor: tint (+ sheen) with real alpha; the compositor blurs behind it.
    corners = (tl, tr, br, bl) overrides the single radius r."""
    cr.save()
    cr.set_operator(cairo.OPERATOR_SOURCE)
    if corners:
        rrect_var(cr, 0, 0, w, h, *corners)
    else:
        rrect(cr, 0, 0, w, h, r)
    cr.clip()
    tr, tg, tb = m["tint"]
    op = min(1.0, m["opacity"] * opacity_scale)
    cr.set_source_rgba(tr, tg, tb, op)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    if sheen and m["sheen"] > 0:
        cr.set_source(lin(0, 0, w * 0.9, h * 0.9, [(0, (1, 1, 1, m["sheen"])), (0.45, (1, 1, 1, m["sheen"] * 0.25)), (1, (1, 1, 1, 0))]))
        cr.paint()
    cr.restore()
