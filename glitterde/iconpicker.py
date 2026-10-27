"""IconPicker: choose the apps-menu button icon (glitterDE sparkle or any icon from the GTK icon theme)."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import gfx
from . import icons as ic
from .scheme import ink
from .widgets import Ico, draw_gtk_icon, label, search_overlay

SPARKLE = "sparkle_logo"
# A curated set shown first; only the ones the current icon theme really has are offered.
CURATED = [
    "view-app-grid-symbolic", "view-grid-symbolic", "open-menu-symbolic", "view-more-symbolic", "view-more-horizontal-symbolic",
    "start-here-symbolic", "go-home-symbolic", "user-home-symbolic", "computer-symbolic", "folder-symbolic",
    "emblem-favorite-symbolic", "starred-symbolic", "face-smile-symbolic", "weather-clear-symbolic", "weather-clear-night-symbolic",
    "system-search-symbolic", "system-run-symbolic", "preferences-system-symbolic", "emblem-system-symbolic",
    "applications-system-symbolic", "applications-games-symbolic", "applications-science-symbolic",
    "emoji-nature-symbolic", "emoji-objects-symbolic", "emoji-symbols-symbolic", "emoji-food-symbolic",
    "media-record-symbolic", "media-playback-start-symbolic", "view-list-symbolic", "view-list-bullet-symbolic",
    "sidebar-show-symbolic", "display-brightness-symbolic", "keyboard-symbolic", "bookmark-new-symbolic",
    "security-high-symbolic", "help-about-symbolic", "dialog-information-symbolic", "list-add-symbolic", "find-location-symbolic",
    "applications-multimedia-symbolic", "applications-graphics-symbolic", "applications-internet-symbolic",
]


def pretty(name):
    if name == SPARKLE:
        return "glitterDE sparkle"
    n = name[:-9] if name.endswith("-symbolic") else name
    return n.replace("-", " ")


def normalise(value):
    """Stored value -> bare name ('sparkle_logo' or an icon-theme name)."""
    v = str(value or SPARKLE)
    return v[4:] if v.startswith("gtk:") else v


class IconPicker(Gtk.Box):
    MAX_RESULTS = 84

    def __init__(self, current, on_pick, theme=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.current, self.on_pick, self.th = normalise(current), on_pick, theme
        self.theme = Gtk.IconTheme.get_default()
        self._tiles = {}
        # --- current icon preview, drawn the way it looks on the panel
        top = Gtk.Box(spacing=14)
        self.preview = Gtk.DrawingArea(); self.preview.set_size_request(64, 64)
        self.preview.connect("draw", self._draw_preview)
        top.pack_start(self.preview, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); v.set_valign(Gtk.Align.CENTER)
        self.cur_title = label("", "title"); self.cur_sub = label("", "muted", ellipsize=False)
        v.pack_start(self.cur_title, False, False, 0); v.pack_start(self.cur_sub, False, False, 0)
        top.pack_start(v, True, True, 0)
        reset = Gtk.Button(label="Use glitterDE sparkle"); reset.get_style_context().add_class("clear")
        reset.set_valign(Gtk.Align.CENTER); reset.connect("clicked", lambda *_: self.pick(SPARKLE))
        top.pack_end(reset, False, False, 0)
        self.pack_start(top, False, False, 0)
        # --- search
        self.entry = Gtk.Entry(); self.entry.set_placeholder_text("Search every icon in your GTK icon theme...")
        self.entry.connect("changed", lambda e: self._search_later())
        self.pack_start(search_overlay(self.entry, (0.165, 0.176, 0.43, 0.8)), False, False, 0)
        # --- grid
        self.flow = Gtk.FlowBox(); self.flow.set_selection_mode(Gtk.SelectionMode.NONE); self.flow.set_homogeneous(True)
        self.flow.set_max_children_per_line(7); self.flow.set_min_children_per_line(3)
        self.flow.set_row_spacing(4); self.flow.set_column_spacing(4)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(250); sw.set_max_content_height(250); sw.add(self.flow)
        self.pack_start(sw, False, False, 0)
        self.status = label("", "muted", ellipsize=False)
        self.pack_start(self.status, False, False, 0)
        self._timer = None
        self._update_current()
        self._fill(self._curated())

    # ------------------------------------------------------------ data
    def _usable(self, n):
        """has_icon() is true for names a theme merely mentions; only offer icons that really resolve to a file."""
        try:
            return self.theme.lookup_icon(n, 24, 0) is not None
        except Exception:
            return False

    def _curated(self):
        return [SPARKLE] + [n for n in CURATED if self._usable(n)]

    def _search(self, q):
        q = q.lower().strip()
        out = []
        for n in self.theme.list_icons(None):
            if q in n.lower():
                out.append(n)
        out.sort(key=lambda n: (not n.endswith("-symbolic"), len(n), n))          # symbolic ones recolour with the panel, so they come first
        return [n for n in out if self._usable(n)]

    def _search_later(self):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(220, self._do_search)

    def _do_search(self):
        self._timer = None
        q = self.entry.get_text().strip()
        if not q:
            self.status.set_text("")
            self._fill(self._curated())
            return False
        hits = self._search(q)
        self._fill(hits[:self.MAX_RESULTS])
        n = len(hits)
        self.status.set_text("No icon matches '%s'." % q if not n else
                             ("Showing %d of %d icons" % (self.MAX_RESULTS, n)
                              if n > self.MAX_RESULTS else "%d icon%s match." % (n, "" if n == 1 else "s")))
        return False

    # ------------------------------------------------------------ ui
    def _fill(self, names):
        for ch in self.flow.get_children():
            self.flow.remove(ch)
        self._tiles = {}
        for n in names:
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.get_style_context().add_class("tilebtn")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            ico = Ico(SPARKLE if n == SPARKLE else "gtk:" + n, 24, ink(), 1.6); ico.set_margin_top(4)
            lab = label(pretty(n), "muted", 0.5, width_chars=11)
            lab.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            v.pack_start(ico, False, False, 0); v.pack_start(lab, False, False, 0)
            b.add(v); b.set_tooltip_text(n if n != SPARKLE else "glitterDE sparkle (default)")
            b.connect("clicked", lambda _b, n=n: self.pick(n))
            if n == self.current:
                b.get_style_context().add_class("sel")
            self._tiles[n] = b
            self.flow.add(b)
        self.flow.show_all()

    def _update_current(self):
        self.cur_title.set_text(pretty(self.current))
        self.cur_sub.set_text("Default" if self.current == SPARKLE else
                              self.current + ("" if self._usable(self.current) else " (missing from the icon theme)"))
        self.preview.queue_draw()

    def _draw_preview(self, w, cr):
        a = w.get_allocation()
        gfx.rrect(cr, 0, 0, a.width, a.height, 18)
        cr.set_source(gfx.lin(0, 0, a.width, a.height, [(0, (0.36, 0.30, 0.74, 1)), (1, (0.22, 0.19, 0.50, 1))])); cr.fill()
        cx, cy = a.width / 2, a.height / 2
        if self.current == SPARKLE or not draw_gtk_icon(cr, self.current, cx, cy, 30, (1, 1, 1, 0.96), w.get_scale_factor()):
            ic.sparkle_logo(cr, cx, cy, 30, (1, 1, 1, 0.96))
        return False

    def pick(self, name):
        for n, b in self._tiles.items():
            ctx = b.get_style_context()
            ctx.add_class("sel") if n == name else ctx.remove_class("sel")
        self.current = name
        self._update_current()
        self.on_pick(name)
