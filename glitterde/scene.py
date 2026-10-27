"""Compose the full glitterDE desktop into a cairo surface (headless-safe)."""
import cairo

from . import apps, gfx, shell
from .shell import Layout

REF_W, REF_H = 1536, 1024


def ui_scale_for(w, h):
    return max(0.5, min(w / REF_W, h / REF_H))


def render(theme, width, height, gdk_scale=1, ui_scale=None, wallpaper=None):
    """Render the desktop at logical size (width x height) * gdk_scale physical pixels."""
    ui = ui_scale or ui_scale_for(width, height)
    pw, ph = int(round(width * gdk_scale)), int(round(height * gdk_scale))
    lw, lh = width / ui, height / ui
    sx, sy = pw / lw, ph / lh
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
    surf.set_device_scale(sx, sy)
    wall = gfx.cover(gfx.load_image(wallpaper or theme.wallpaper()), pw, ph)
    wall.set_device_scale(sx, sy)
    c = cairo.Context(surf)
    c.set_antialias(cairo.ANTIALIAS_BEST)
    c.set_source_surface(wall, 0, 0)
    c.paint()
    g = gfx.Glass(theme, wall, sx)
    L = Layout(lw, lh)

    shell.draw_desktop_icons(c, g, theme, L)
    # floating windows (z-order: files < terminal < settings), proportional placement
    apps.draw_sparkfiles(c, g, theme, L.fx(190), L.fy(75))
    apps.draw_sparkterm(c, g, theme, L.fx(748), L.fy(210))
    apps.draw_sparksettings(c, g, theme, L.fx(118), L.fy(525))
    shell.draw_widgets(c, g, theme, L)
    shell.draw_dock(c, g, theme, L)
    shell.draw_workspace_switcher(c, g, theme, L)
    shell.draw_to_phone(c, g, theme, L)
    shell.draw_panel(c, g, theme, L)
    return surf
