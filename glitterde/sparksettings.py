"""SparkSettings: every control here writes a real setting (settings.toml, GTK settings.ini, Xcursor)."""
import glob
import os
import platform
import shutil
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import aboutpage, appkit, config, desktopenv, displays, gfx, iconpicker, netpages, services, settings_model as model, themeeditor, tokens
from . import icons as ic
from .widgets import Ico, label, search_overlay
from .menus import ChoiceButton

from .scheme import ink
PINK = (0.97, 0.47, 0.78, 1)
# Pages with nothing to configure yet: hidden until About > "Show experimental settings" is on.
EXPERIMENTAL_PAGES = set()
ACCENTS = [("Lavender", "#9b7df0"), ("Pink", "#f777c8"), ("Sky", "#6fb4ff"), ("Mint", "#4fd1a5"), ("Peach", "#ff9e7a")]


# ------------------------------------------------------------ GTK/X helpers
def gtk_ini_set(key, value):
    d = os.path.join(GLib.get_user_config_dir(), "gtk-3.0")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, "settings.ini")
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(f, GLib.KeyFileFlags.NONE)
    except GLib.Error:
        pass
    if isinstance(value, bool):
        kf.set_boolean("Settings", key, value)
    elif isinstance(value, int):
        kf.set_integer("Settings", key, value)
    else:
        kf.set_string("Settings", key, value)
    kf.save_to_file(f)


def icon_dirs():
    return [config.BUNDLED_ICONS, os.path.expanduser("~/.icons"), os.path.expanduser("~/.local/share/icons"), "/usr/share/icons", "/usr/local/share/icons"]


def installed_icon_themes(cursors=False):
    out = {}
    for base in icon_dirs():
        for p in glob.glob(os.path.join(base, "*")):
            n = os.path.basename(p)
            has_cur = os.path.isdir(os.path.join(p, "cursors"))
            if cursors and has_cur:
                out[n] = p
            elif not cursors and os.path.exists(os.path.join(p, "index.theme")) and not has_cur and n not in ("default", "hicolor"):
                out[n] = p
    return sorted(out)


class Settings(appkit.GlassWindow):
    def __init__(self, page=None):
        super().__init__("Settings", "sparksettings", "window_light", (900, 600))
        self.pages, self.rows, self._builders = {}, {}, {}
        root = Gtk.Box(spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(root, "set_margin_" + m)(4)
        self.add(root)
        # sidebar
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.get_style_context().add_class("sidebar"); side.set_size_request(210, -1)
        for m in ("top", "bottom", "start", "end"):
            getattr(side, "set_margin_" + m)(0)
        self.q = Gtk.Entry(); self.q.set_placeholder_text("Search settings...")
        
        self.q.connect("changed", lambda e: self._filter(e.get_text()))
        side.set_margin_top(0)
        self.list = Gtk.ListBox(); self.list.connect("row-selected", self._select)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(self.list)
        side.pack_start(search_overlay(self.q, (0.165, 0.176, 0.43, 0.8)), False, False, 0); side.pack_start(sw, True, True, 0)
        root.pack_start(side, False, False, 0)
        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        wrap = Gtk.Box(); wrap.get_style_context().add_class("inner"); wrap.pack_start(self.stack, True, True, 0)
        root.pack_start(wrap, True, True, 0)

        self._groups, self._collapsed, self._built, self._all_builders = {}, set(), set(), {}
        # Grouped by what the person is trying to change: how it looks, what the desktop shows, how the shell and windows behave, the
        # connections, the hardware, and the system itself.  (Page names are also used by "Settings..." menu items in the shell.)
        tree = [("Appearance", "palette", [("Theme", self.p_theme), ("Colours", self.p_colours), ("Transparency", lambda: self.model_page("Transparency")),
                                           ("Fonts", self.p_fonts), ("Icons", self.p_icons), ("Cursor", self.p_cursor)]),
                ("Desktop", "monitor", [("Wallpaper", self.p_wall), ("Desktop icons", lambda: self.model_page("Desktop icons")),
                                        ("Widgets", self.p_widgets), ("Windows", lambda: self.model_page("Windows"))]),
                ("Shell", "panel_left", [("Panel", lambda: self.model_page("Panel")), ("Dock", self.p_dock), ("Launcher", self.p_launcher),
                                         ("Notifications", lambda: self.model_page("Notifications"))]),
                ("Connections", "wifi", [("Network", self.p_network), ("Bluetooth", self.p_bluetooth)]),
                ("Hardware", "laptop", [("Display", self.p_display), ("Audio", self.p_audio), ("Power", self.p_power),
                                        ("Drives", lambda: self.model_page("Drives"))]),
                ("System", "settings_gear_outline", [("About", self.p_about)])]
        for g, icn, kids in tree:
            gr = Gtk.ListBoxRow(); gr.group = g; gr.set_selectable(False)
            b = Gtk.Box(spacing=10); b.pack_start(Ico(icn, 14, ink(), 1.5), False, False, 2)
            b.pack_start(label(g, "h2"), True, True, 0)
            arrow = Ico("chev_up", 12, (0.165, 0.176, 0.43, .7), 1.8); b.pack_start(arrow, False, False, 0)
            gr.add(b); gr.arrow = arrow
            ev = Gtk.EventBox(); self.list.add(gr)
            self._groups[g] = []
            for name, builder in kids:
                r = Gtk.ListBoxRow(); r.page = name; r.group_of = g; r.experimental = name in EXPERIMENTAL_PAGES; r.set_no_show_all(True)   # appkit.run() calls show_all(): rows keep their own visibility
                rb = Gtk.Box(spacing=8); rb.set_margin_start(16)
                rb.pack_start(label("•", "muted"), False, False, 0); rb.pack_start(label(name), False, False, 0)
                rb.show_all(); r.add(rb); self.list.add(r); self.rows[name] = r; self._groups[g].append(r)
                self._builders[name] = self._all_builders[name] = builder       # pages are built lazily on first view
        self.list.connect("row-activated", self._activate)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.add_named(self._wrap_page("Search results", self.results), "__results__")
        self.show_all()
        self._refresh_rows()
        want = self.rows.get(page or "Theme") or self.rows["Theme"]
        if not want.get_visible():
            want = self.rows["Theme"]
        self.list.select_row(want)

    def _wrap_page(self, title, content):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + m)(16)
        box.pack_start(label(title, "h1"), False, False, 0)
        box.pack_start(content, True, True, 0)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(box)
        return sw

    def _select(self, lb, row):
        if row is not None and hasattr(row, "page"):
            self._ensure(row.page)
            self.stack.set_visible_child_name(row.page)

    def _reload(self):
        """settings.toml changed on disk: besides the base-class repaint, bring every visible control in line with it."""
        r = super()._reload()
        # (apps re-exec on a colour-scheme change inside super()._reload(); when we are still here, just sync)
        self._sync_rows()
        return r

    def _sync_rows(self):
        model._cache["mt"] = None                                    # force a re-read: two writes inside one mtime tick must not hide the second
        live = []
        for sid, fn, alive in getattr(self, "_row_sync", []):
            if alive() is None:
                continue
            live.append((sid, fn, alive))
            try:
                fn()
            except Exception:
                pass
        self._row_sync = live

    def on_scheme_change(self):
        import sys
        page = self.stack.get_visible_child_name() or ""
        os.execv(sys.executable, [sys.executable, sys.argv[0]] + ([page] if page else []))

    def _ensure(self, name):
        b = self._builders.pop(name, None)
        if b is not None:
            w = self._wrap_page(name, b())
            w.show_all()
            self.stack.add_named(w, name)
            self._built.add(name)

    def _refresh_rows(self, text=""):
        """One place decides which sidebar rows show: group collapsed? experimental page hidden? search text?"""
        t = text.lower().strip()
        exp = model.experimental_enabled()
        for g, rows in self._groups.items():
            for r in rows:
                vis = (exp or not r.experimental) and (bool(t) or g not in self._collapsed) and \
                      (not t or t in r.page.lower() or t in g.lower())
                r.set_visible(vis)

    def apply_experimental(self):
        """The About switch changed: show/hide experimental pages and rebuild the pages that list settings (they are built lazily again)."""
        self._refresh_rows(self.q.get_text())
        cur = self.stack.get_visible_child_name()
        for name in list(self._built):
            if name == "About":
                continue
            w = self.stack.get_child_by_name(name)
            if w is not None:
                self.stack.remove(w)
            self._built.discard(name)
            self._builders[name] = self._all_builders[name]
        if cur and cur != "About" and cur in self._builders:
            self._ensure(cur); self.stack.set_visible_child_name(cur)

    def _edit_theme(self, theme, new_copy):
        themeeditor.ThemeEditor(self, theme, lambda: self._rebuild_page("Theme"), new_copy)

    @staticmethod
    def _open_dir(path):
        """Show a folder in our own file manager (always present), falling back to whatever the system has registered."""
        if shutil.which("sparkfiles") or os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "sparkfiles")):
            services.fire(["sparkfiles", path])
            return
        from gi.repository import Gio
        try:
            if Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None):
                return
        except GLib.Error:
            pass
        services.fire(["xdg-open", path])

    def _rebuild_page(self, name):
        """Throw a page away and build it again (its content depends on something that just changed)."""
        w = self.stack.get_child_by_name(name)
        if w is not None:
            self.stack.remove(w)
        self._built.discard(name)
        self._builders[name] = self._all_builders[name]
        self._ensure(name)
        self.stack.set_visible_child_name(name)

    def _activate(self, lb, row):
        if hasattr(row, "group"):                   # collapse / expand a group
            show = row.group in self._collapsed
            (self._collapsed.discard if show else self._collapsed.add)(row.group)
            self._refresh_rows(self.q.get_text())
            row.arrow.set_icon("chev_up" if show else "chev_down")

    def _filter(self, t):
        t = t.lower().strip()
        self._refresh_rows(t)
        if not t:
            row = self.list.get_selected_row()
            if row is not None and hasattr(row, "page"):
                self._ensure(row.page)
                self.stack.set_visible_child_name(row.page)
            return
        hits = [st for st in model.visible_settings() if t in st["title"].lower() or t in st["desc"].lower()]
        for ch in self.results.get_children():
            self.results.remove(ch)
        if hits:
            card = self.card()
            for st in hits[:14]:
                card.inner.pack_start(self.setting_row(st, show_page=True), False, False, 4)
            self.results.pack_start(card, False, False, 0)
        else:
            self.results.pack_start(self.note("No settings match."), False, False, 0)
        self.results.show_all()
        self.stack.set_visible_child_name("__results__")

    # -------------------------------------------------------------- helpers
    def card(self, title=None):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); b.get_style_context().add_class("card2")
        for m in ("top", "bottom", "start", "end"):
            getattr(b, "set_margin_" + m)(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(inner, "set_margin_" + m)(12)
        if title:
            inner.pack_start(label(title, "h2"), False, False, 0)
        b.pack_start(inner, False, False, 0)
        b.inner = inner
        return b

    def note(self, text):
        l = label(text, "muted", ellipsize=False)
        l.set_line_wrap(True); l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR); l.set_max_width_chars(58); l.set_xalign(0)
        l.set_margin_top(4)
        return l

    # ---------------------------------------------- model-generated controls
    def setting_row(self, st, show_page=False):
        sid, typ = st["id"], st["type"]
        box = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        left.pack_start(label(st["title"] + (("   (" + st["page"] + ")") if show_page else ""), "title"), False, False, 0)
        d = label(st["desc"], "muted", ellipsize=False); d.set_line_wrap(True); d.set_max_width_chars(46); d.set_xalign(0)
        left.pack_start(d, False, False, 0)
        box.pack_start(left, True, True, 0)
        cur = model.get(sid)
        ctl = Gtk.Box(spacing=6); ctl.set_valign(Gtk.Align.CENTER)
        reset = Gtk.Button(); reset.set_no_show_all(True); reset.add(Ico("arrow_left", 11, ink(), 1.8)); reset.get_child().show(); reset.set_tooltip_text("Reset to default (%s)" % (st["default"],))
        state = {"t": None, "loading": True}

        def write(v):
            if state["loading"]:
                return
            model.set(sid, v)
            reset.set_visible(v != st["default"])

        if typ == "bool":
            w = self.switch(bool(cur), write)
        elif typ in ("int", "float"):
            w = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, st["min"], st["max"], st.get("step", 1))
            w.set_digits(0 if typ == "int" else 2); w.set_value(cur); w.set_size_request(170, -1); w.set_value_pos(Gtk.PositionType.RIGHT)

            def ch(sc):
                if state["loading"]:                                  # moved by sync(), not by the user
                    return
                if state["t"]:
                    GLib.source_remove(state["t"])
                v = sc.get_value()
                v = int(round(v)) if typ == "int" else round(v, 2)
                state["t"] = GLib.timeout_add(250, lambda: (write(v), state.update(t=None), False)[2])
            w.connect("value-changed", ch)
        elif typ == "choice":
            w = ChoiceButton(light=True, theme=self.th)
            for val, lab in st["choices"]:
                w.append(val, lab)
            w.set_active_id(str(cur))
            w.connect("changed", lambda c: write(c.get_active_id()))
        elif typ == "font":
            w = Gtk.FontButton(); w.set_font(cur or "Inter 10"); w.connect("font-set", lambda b: write(b.get_font()))
        elif typ == "icon":
            w = Gtk.Button(label="Change icon…"); w.get_style_context().add_class("clear")
            w.connect("clicked", lambda *_: self.list.select_row(self.rows["Launcher"]))
        else:
            w = Gtk.Entry(); w.set_text(str(cur)); w.connect("activate", lambda e: write(e.get_text()))

        def do_reset(*_):
            model.reset(sid)
            state["loading"] = True
            dv = st["default"]
            if typ == "bool": w.set_active(dv)
            elif typ in ("int", "float"): w.set_value(dv)
            elif typ == "choice": w.set_active_id(str(dv))
            elif typ == "font": w.set_font(dv or "Inter 10")
            elif typ == "icon": pass
            state["loading"] = False
            reset.set_visible(False)
        reset.connect("clicked", do_reset)

        def sync():
            """The setting changed elsewhere (shell '+' button, WM, another settings window, a hand edit): follow it."""
            if state["t"] or state["loading"]:                        # the user is dragging this very control right now
                return
            nv = model.get(sid)
            state["loading"] = True
            try:
                if typ == "bool" and w.get_active() != bool(nv): w.set_active(bool(nv))
                elif typ in ("int", "float") and abs(w.get_value() - nv) > 1e-9: w.set_value(nv)
                elif typ == "choice" and w.get_active_id() != str(nv): w.set_active_id(str(nv))
            finally:
                state["loading"] = False
            reset.set_visible(nv != st["default"])
        if typ in ("bool", "int", "float", "choice"):
            self._row_sync = [f for f in getattr(self, "_row_sync", []) if f[0] != sid or f[2]() is not None] + [(sid, sync, lambda: box if box.get_parent() else None)]
        ctl.pack_start(reset, False, False, 0); ctl.pack_start(w, False, False, 0)
        box.pack_end(ctl, False, False, 0)
        state["loading"] = False
        box.show_all()
        reset.set_visible(cur != st["default"])
        return box

    def model_page(self, page):
        p = self.page_box(); c = self.card()
        for st in model.visible_settings():
            if st.get("page") == page and st["type"] != "icon":         # the icon has its own picker
                c.inner.pack_start(self.setting_row(st), False, False, 5)
        p.pack_start(c, False, False, 0)
        return p

    def row(self, text, widget):
        r = Gtk.Box(spacing=12); r.pack_start(label(text), True, True, 0); r.pack_end(widget, False, False, 0)
        return r

    def switch(self, state, cb):
        s = Gtk.Switch(); s.set_active(state); s.set_valign(Gtk.Align.CENTER)
        s.connect("notify::active", lambda sw, _p: cb(sw.get_active()))
        return s

    def page_box(self):
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

    # ------------------------------------------------------------- Appearance
    def p_theme(self):
        p = self.page_box()
        sc = self.card("Colour scheme")
        cur_pref = str(config.load().get("appearance", {}).get("color_scheme", "auto")).lower()
        row = Gtk.Box(spacing=12, homogeneous=True); group = None
        for key, name, sub, base in (("light", "Light", "Bright glass, dark text", (0.91, 0.88, 0.99)),
                                     ("dark", "Dark", "Deep glass, light text", (0.14, 0.12, 0.26)),
                                     ("auto", "Automatic", "Follows the theme", None)):
            b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or b
            b.set_mode(False); b.get_style_context().add_class("tilebtn")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            prev = Gtk.DrawingArea(); prev.set_size_request(-1, 58)

            def draw(w, cr, base=base):
                a = w.get_allocation(); gfx.rrect(cr, 0, 0, a.width, a.height, 10)
                if base:
                    cr.set_source_rgb(*base); cr.fill_preserve()
                    ink_ = (0.16, 0.17, 0.43) if base[0] > 0.5 else (0.93, 0.92, 0.98)
                    cr.set_source_rgba(*ink_, 0.85); cr.new_path()
                    for i, wd in enumerate((0.5, 0.35)):
                        gfx.rrect(cr, 12, 14 + i * 14, (a.width - 24) * wd, 6, 3); cr.fill()
                else:                                                  # half light / half dark
                    cr.clip_preserve(); cr.set_source_rgb(0.91, 0.88, 0.99); cr.paint()
                    cr.new_path(); cr.rectangle(a.width / 2, 0, a.width / 2, a.height); cr.set_source_rgb(0.14, 0.12, 0.26); cr.fill()
                return False
            prev.connect("draw", draw)
            v.pack_start(prev, False, False, 0)
            v.pack_start(label(name, "title"), False, False, 0); v.pack_start(label(sub, "muted"), False, False, 0)
            b.add(v); b.set_active(key == cur_pref)
            b.connect("toggled", lambda w, k=key: w.get_active() and config.set("appearance", "color_scheme", k))
            row.pack_start(b, True, True, 0)
        sc.inner.pack_start(row, False, False, 4)
        p.pack_start(sc, False, False, 0)
        c = self.card("Installed themes")
        cur = tokens.active().theme_id
        group = None
        for tid, d in tokens.find_themes().items():
            try:
                th = tokens.Theme(d)
            except Exception:
                continue
            b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or b
            b.set_mode(False); b.get_style_context().add_class("tilebtn")
            row = Gtk.Box(spacing=12)
            sw = Gtk.DrawingArea(); sw.set_size_request(74, 30)
            cols = [th.material(m)["tint"] for m in ("panel", "card", "window_glass", "window_light")] + [th.color("accent.primary")[:3]]
            sw.connect("draw", lambda w, cr, cs=cols: ([(cr.set_source_rgb(*col), cr.rectangle(i * 14.5, 3, 14.5, 24), cr.fill()) for i, col in enumerate(cs)], False)[1])
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.set_valign(Gtk.Align.CENTER)
            v.pack_start(label(th.meta.get("name", tid), "title"), False, False, 0)
            first = open(os.path.join(d, "palette.toml")).readline().strip("# \n").split(": ", 1)
            v.pack_start(label(first[1] if len(first) > 1 else "v" + str(th.meta.get("version", "")), "muted"), False, False, 0)
            row.pack_start(sw, False, False, 0); row.pack_start(v, True, True, 0)
            b.add(row); b.set_active(tid == cur)
            b.connect("toggled", lambda w, t=tid: w.get_active() and (config.set("appearance", "theme", t)))
            c.inner.pack_start(b, False, False, 2)
        p.pack_start(c, False, False, 0)
        cur_theme = tokens.active()
        ce = self.card("Make it yours")
        row = Gtk.Box(spacing=8)
        for text, cb in (("Customise this theme…", lambda b: self._edit_theme(cur_theme, False)),
                         ("New theme from this one…", lambda b: self._edit_theme(cur_theme, True)),
                         ("Open themes folder", lambda b: (os.makedirs(themeeditor.USER_DIR, exist_ok=True), self._open_dir(themeeditor.USER_DIR)))):
            bt = Gtk.Button(label=text); bt.get_style_context().add_class("clear"); bt.connect("clicked", cb); row.pack_start(bt, False, False, 0)
        if themeeditor.is_user_theme(cur_theme):
            bt = Gtk.Button(label="Delete this theme"); bt.get_style_context().add_class("clear")
            bt.connect("clicked", lambda b: (themeeditor.delete_user_theme(cur_theme), self._rebuild_page("Theme")))
            row.pack_end(bt, False, False, 0)
        ce.inner.pack_start(row, False, False, 0)
        p.pack_start(ce, False, False, 0)
        return p

    def p_colours(self):
        p = self.page_box(); c = self.card("Accent colour")
        row = Gtk.Box(spacing=10)
        cur = self.th.pal["accent"]["primary"]
        group = None
        for name, hexv in ACCENTS:
            b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or b
            b.set_mode(False); b.get_style_context().add_class("tilebtn")
            da = Gtk.DrawingArea(); da.set_size_request(46, 30)
            rgb = tuple(int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
            da.connect("draw", lambda w, cr, rgb=rgb, n=name: (ic.squircle(cr, 8, 0, 30, rgb + (1,), tuple(v * .8 for v in rgb) + (1,), 10),
                                                               False)[1])
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.pack_start(da, False, False, 0); v.pack_start(label(name, "muted", 0.5), False, False, 0)
            b.add(v); b.set_active(hexv.lower() == cur.lower())
            b.connect("toggled", lambda w, h=hexv: w.get_active() and config.set("accent", "primary", h))
            row.pack_start(b, False, False, 0)
        c.inner.pack_start(row, False, False, 0)
        p.pack_start(c, False, False, 0)
        return p

    def p_cursor(self):
        p = self.page_box(); c = self.card("Cursor theme")
        themes = installed_icon_themes(cursors=True) or ["default"]
        cur = config.cursor_theme() or Gtk.Settings.get_default().get_property("gtk-cursor-theme-name") or themes[0]
        size = int(config.load().get("cursor", {}).get("size", 32))
        fl = Gtk.FlowBox(); fl.set_max_children_per_line(6); fl.set_selection_mode(Gtk.SelectionMode.NONE); fl.set_homogeneous(True)
        group = None
        for t in themes[:18]:
            b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or b
            b.set_mode(False); b.get_style_context().add_class("tilebtn")
            da = Gtk.DrawingArea(); da.set_size_request(54, 40)
            da.connect("draw", self._draw_cursor, t == cur)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.pack_start(da, False, False, 0)
            v.pack_start(label(t, "muted", 0.5, width_chars=11), False, False, 0)
            b.add(v); b.set_active(t == cur)
            b.connect("toggled", lambda w, n=t: w.get_active() and self._set_cursor(theme=n))
            fl.add(b)
        c.inner.pack_start(fl, False, False, 0)
        p.pack_start(c, False, False, 0)
        c2 = self.card("Size")
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 16, 64, 8); sc.set_value(size); sc.set_digits(0)
        sc.set_value_pos(Gtk.PositionType.RIGHT); sc.set_hexpand(True)
        sc.connect("value-changed", lambda s: self._set_cursor(size=int(s.get_value())))
        c2.inner.pack_start(sc, False, False, 0)
        p.pack_start(c2, False, False, 0)
        return p

    @staticmethod
    def _draw_cursor(da, cr, sel):
        cx, cy = da.get_allocated_width() / 2, da.get_allocated_height() / 2
        pts = [(0, 0), (0, 14.5), (3.6, 11.2), (6.2, 17), (8.4, 16), (5.8, 10.4), (10.6, 10.4)]
        cr.save(); cr.translate(cx - 6, cy - 10); cr.scale(1.3, 1.3)
        cr.move_to(*pts[0])
        for q in pts[1:]:
            cr.line_to(*q)
        cr.close_path(); cr.set_source_rgba(*(PINK if sel else (0.12, 0.12, 0.2, 1))); cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .9); cr.set_line_width(.9); cr.stroke(); cr.restore()
        return False

    def _set_cursor(self, theme=None, size=None):
        d = config.load().get("cursor", {})
        theme = theme or d.get("theme") or "default"
        size = size or int(d.get("size", 32))
        config.set("cursor", "theme", theme); config.set("cursor", "size", size)
        s = Gtk.Settings.get_default(); s.set_property("gtk-cursor-theme-name", theme); s.set_property("gtk-cursor-theme-size", size)
        import threading
        threading.Thread(target=desktopenv.apply_cursor, args=(theme, size), daemon=True).start()   # files, X resources, gsettings, D-Bus env

    def p_icons(self):
        p = self.page_box(); c = self.card("Icon theme")
        cur = Gtk.Settings.get_default().get_property("gtk-icon-theme-name")
        group = None
        for t in installed_icon_themes()[:14]:
            b = Gtk.RadioButton.new_with_label_from_widget(group, t) if group else Gtk.RadioButton(label=t)
            group = group or b
            b.set_active(t == cur)
            b.connect("toggled", lambda w, n=t: w.get_active() and (gtk_ini_set("gtk-icon-theme-name", n),
                                                                     Gtk.Settings.get_default().set_property("gtk-icon-theme-name", n)))
            c.inner.pack_start(b, False, False, 0)
        p.pack_start(c, False, False, 0)
        return p

    def p_fonts(self):
        p = self.page_box(); c = self.card("GTK applications")
        fb = Gtk.FontButton(); fb.set_font(Gtk.Settings.get_default().get_property("gtk-font-name") or "Inter 10")
        fb.connect("font-set", lambda b: gtk_ini_set("gtk-font-name", b.get_font()))
        c.inner.pack_start(self.row("Default font for other GTK apps", fb), False, False, 2)
        p.pack_start(c, False, False, 0)
        p.pack_start(self.model_page("Fonts"), False, False, 0)
        return p

    def p_anim(self):
        p = self.page_box(); c = self.card()
        on = Gtk.Settings.get_default().get_property("gtk-enable-animations")
        c.inner.pack_start(self.row("Enable animations in apps", self.switch(on, lambda v: gtk_ini_set("gtk-enable-animations", v))), False, False, 0)
        p.pack_start(c, False, False, 0)
        return p

    def p_transp(self):
        p = self.page_box(); c = self.card("Glass effects")
        u = config.load().get("appearance", {})
        c.inner.pack_start(self.row("Transparency (tinted glass surfaces)", self.switch(u.get("transparency", True), lambda v: config.set("appearance", "transparency", v))), False, False, 2)
        c.inner.pack_start(self.row("Blur behind surfaces", self.switch(u.get("blur", True), lambda v: config.set("appearance", "blur", v))), False, False, 2)
        p.pack_start(c, False, False, 0)
        return p

    # ---------------------------------------------------------------- Desktop
    def p_wall(self):
        p = self.page_box(); c = self.card("Wallpaper")
        fl = Gtk.FlowBox(); fl.set_max_children_per_line(3); fl.set_selection_mode(Gtk.SelectionMode.NONE)
        cur = self.th.wallpaper()
        files = sorted(glob.glob(os.path.join(appkit.ROOT, "wallpapers", "*.png")) + glob.glob(os.path.expanduser("~/Pictures/*.png")) +
                       glob.glob(os.path.expanduser("~/Pictures/*.jpg")))[:12]
        group = None
        for f in files:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(f, 168, 112, True)
            except GLib.Error:
                continue
            b = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or b
            b.set_mode(False); b.get_style_context().add_class("tilebtn")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
            v.pack_start(label(os.path.basename(f), "muted", 0.5, width_chars=20), False, False, 0)
            b.add(v); b.set_active(os.path.abspath(f) == os.path.abspath(cur))
            b.connect("toggled", lambda w, fp=f: w.get_active() and config.set("wallpaper", "path", os.path.abspath(fp)))
            fl.add(b)
        c.inner.pack_start(fl, False, False, 0)
        pick = Gtk.Button(label="Choose picture…"); pick.get_style_context().add_class("clear"); pick.connect("clicked", self._pick_wall)
        c.inner.pack_start(pick, False, False, 0)
        p.pack_start(c, False, False, 0)
        p.pack_start(self.model_page("Wallpaper"), False, False, 0)
        return p

    def _pick_wall(self, *_):
        d = Gtk.FileChooserDialog(title="Choose wallpaper", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        appkit.style_stock_dialog(d)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button("Use", Gtk.ResponseType.OK)
        f = Gtk.FileFilter(); f.set_name("Pictures"); f.add_mime_type("image/png"); f.add_mime_type("image/jpeg"); d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            config.set("wallpaper", "path", d.get_filename())
        d.destroy()

    def p_launcher(self):
        p = self.page_box(); c = self.card("Apps menu icon")
        c.inner.pack_start(iconpicker.IconPicker(model.get("launcher.button_icon"), lambda n: model.set("launcher.button_icon", n), self.th),
                           False, False, 0)
        p.pack_start(c, False, False, 0)
        p.pack_start(self.model_page("Launcher"), False, False, 0)
        return p

    def p_dock(self):
        p = self.page_box(); self.dock_card = self.card("Pinned apps"); p.pack_start(self.dock_card, False, False, 0)
        add = Gtk.Button(label="Add app…"); add.get_style_context().add_class("clear"); add.connect("clicked", self._add_fav)
        p.pack_start(add, False, False, 0)
        self._dock_refresh()
        p.pack_start(self.model_page("Dock"), False, False, 0)
        return p

    def _favs(self):
        conf = config.load("panel.toml").get("dock", {}).get("favorites")
        if conf is not None:
            return list(conf)
        return [a.get_id() for a in services.default_favorites(services.all_apps())]

    def _dock_refresh(self):
        for ch in self.dock_card.inner.get_children()[1:]:
            self.dock_card.inner.remove(ch)
        from gi.repository import Gio
        for fid in self._favs():
            app = Gio.DesktopAppInfo.new(fid if fid.endswith(".desktop") else fid + ".desktop")
            r = Gtk.Box(spacing=10)
            if app and app.get_icon():
                im = Gtk.Image.new_from_gicon(app.get_icon(), Gtk.IconSize.LARGE_TOOLBAR); r.pack_start(im, False, False, 0)
            r.pack_start(label(app.get_display_name() if app else fid), True, True, 0)
            rm = Gtk.Button(label="Remove"); rm.connect("clicked", lambda _b, f=fid: self._save_favs([x for x in self._favs() if x != f]))
            r.pack_end(rm, False, False, 0)
            self.dock_card.inner.pack_start(r, False, False, 2)
        self.dock_card.show_all()

    def _save_favs(self, ids):
        config.save({"dock": {"favorites": ids}}, "panel.toml")
        self._dock_refresh()

    def _add_fav(self, *_):
        d = Gtk.AppChooserDialog(transient_for=self, modal=True, content_type="application/octet-stream")
        d.get_widget().set_show_all(True)
        appkit.style_stock_dialog(d)
        if d.run() == Gtk.ResponseType.OK:
            app = d.get_app_info()
            if app and app.get_id() not in self._favs():
                self._save_favs(self._favs() + [app.get_id()])
        d.destroy()

    WIDGETS = [("clock", "Clock"), ("system", "System"), ("network", "Network"), ("bluetooth", "Bluetooth"),
               ("phone", "GlitterLink"), ("media", "Now playing"), ("quick", "Quick actions"), ("notifications", "Notifications")]

    def p_widgets(self):
        p = self.page_box(); c = self.card("Desktop widgets")
        enabled = set((config.load().get("widgets", {}).get("enabled", "") or "").split(","))
        for wid, title in self.WIDGETS:
            if wid == "phone" and not model.experimental_enabled():        # GlitterLink has no daemon yet (roadmap phase 10)
                continue
            def tog(v, w=wid):
                cur = set((config.load().get("widgets", {}).get("enabled", "") or "").split(",")) - {""}
                (cur.add if v else cur.discard)(w)
                config.set("widgets", "enabled", ",".join(sorted(cur)))
            c.inner.pack_start(self.row(title, self.switch(wid in enabled, tog)), False, False, 3)
        p.pack_start(c, False, False, 0)
        rb = Gtk.Button(label="Reset widget positions"); rb.get_style_context().add_class("clear")
        rb.connect("clicked", lambda *_: config.remove("widget_pos"))
        p.pack_start(rb, False, False, 0)
        return p

    # ---------------------------------------------------------------- Devices
    def p_audio(self):
        p = self.page_box(); c = self.card("Output")
        au = services.Audio()
        if not au.available:
            c.inner.pack_start(self.note("No audio control found."), False, False, 0)
        else:
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); sc.set_digits(0); sc.set_hexpand(True)
            sc.set_value_pos(Gtk.PositionType.RIGHT)
            mute = self.switch(False, lambda v: None)
            state = {"init": True, "t": None}

            def got(v, muted):
                if v is not None:
                    sc.set_value(v * 100)
                state["init"] = False
            au.get(got)

            def changed(s):
                if state["init"]:
                    return
                if state["t"]:
                    GLib.source_remove(state["t"])
                state["t"] = GLib.timeout_add(120, lambda: (au.set(s.get_value() / 100), state.update(t=None), False)[2])
            sc.connect("value-changed", changed)
            m = Gtk.Button(label="Mute / unmute"); m.get_style_context().add_class("clear"); m.connect("clicked", lambda *_: au.toggle_mute())
            c.inner.pack_start(sc, False, False, 0); c.inner.pack_start(m, False, False, 0)
            # which output the sound goes to (speakers, headphones, HDMI, Bluetooth ...)
            dev = ChoiceButton(light=True, theme=self.th)
            dst = {"init": True}

            def listed(rows):
                for key, name, default in rows:
                    dev.append(key, name)
                    if default:
                        dev.set_active_id(key)
                dst["init"] = False
                if not rows:
                    dev.lab.set_text("No output devices")
            dev.connect("changed", lambda b: None if dst["init"] else au.set_default(b.get_active_id(), lambda: au.get(got)))
            au.sinks(listed)
            c.inner.pack_start(self.row("Output device", dev), False, False, 3)
        p.pack_start(c, False, False, 0)
        return p

    def p_display(self):
        """Resolution, refresh rate, rotation, position, primary display and on/off for every connected screen (xrandr).
        Changes are applied together with Apply; a countdown reverts them unless they are confirmed (a black screen must never stick)."""
        p = self.page_box()
        if not displays.available():
            c = self.card("Displays")
            c.inner.pack_start(self.note("Display settings need xrandr (package x11-xserver-utils, or xorg-xrandr on Arch)."), False, False, 0)
            p.pack_start(c, False, False, 0)
            return p
        st = {"outs": displays.query(), "orig": None, "work": None, "timer": None}
        st["orig"] = displays.layout_of(st["outs"])
        st["work"] = {k: dict(v) for k, v in st["orig"].items()}
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        p.pack_start(holder, False, False, 0)
        bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        p.pack_start(bar_box, False, False, 0)
        msg = self.note("")
        msg.set_no_show_all(True)
        p.pack_start(msg, False, False, 0)

        def say(text):
            msg.set_text(text or ""); msg.set_visible(bool(text))

        def dirty():
            return st["work"] != st["orig"]

        class Preview(Gtk.DrawingArea):
            def __init__(self):
                super().__init__()
                self.set_size_request(-1, 150)

            def do_draw(self, cr):
                from .scheme import ink as _ink
                lay, outs = st["work"], {o.name: o for o in st["outs"]}
                on = [(n, s_) for n, s_ in lay.items() if s_.get("on")]
                W, H = self.get_allocated_width(), self.get_allocated_height()
                if not on:
                    return False
                rects = []
                for n, s_ in on:
                    w, h = displays._size(outs[n], s_["mode"], s_["rotation"])
                    rects.append((n, s_["x"], s_["y"], w, h))
                minx, miny = min(r[1] for r in rects), min(r[2] for r in rects)
                maxx, maxy = max(r[1] + r[3] for r in rects), max(r[2] + r[4] for r in rects)
                k = min((W - 24) / max(1.0, maxx - minx), (H - 24) / max(1.0, maxy - miny))
                ox, oy = (W - (maxx - minx) * k) / 2, (H - (maxy - miny) * k) / 2
                ink_ = _ink()
                for n, x, y, w, h in rects:
                    rx, ry, rw, rh = ox + (x - minx) * k + 1.5, oy + (y - miny) * k + 1.5, w * k - 3, h * k - 3
                    gfx.rrect(cr, rx, ry, rw, rh, 8)
                    cr.set_source_rgba(0.66, 0.55, 1.0, 0.30 if not lay[n].get("primary") else 0.55); cr.fill_preserve()
                    cr.set_source_rgba(*ink_[:3], 0.55); cr.set_line_width(1.2); cr.stroke()
                    gfx.text(cr, n + ("  ★" if lay[n].get("primary") else ""), rx + rw / 2, ry + rh / 2, 11, ink_, 600, "c")
                return False

        prev = Preview()

        def rebuild():
            for ch in holder.get_children():
                holder.remove(ch); ch.destroy()
            lay, outs = st["work"], st["outs"]
            if not outs:
                c = self.card("Displays")
                c.inner.pack_start(self.note("No connected displays were found."), False, False, 0)
                holder.pack_start(c, False, False, 0); holder.show_all(); return
            pc = self.card("Arrangement")
            pc.inner.pack_start(prev, False, False, 0)
            pc.inner.pack_start(self.note("Pick a position for each screen below. The star marks the main display (panel, dock and new windows go there)."),
                                False, False, 0)
            holder.pack_start(pc, False, False, 0)
            for o in outs:
                s_ = lay[o.name]
                c = self.card("%s%s" % (o.name, ("  ·  " + o.model) if o.model else ""))
                if len(outs) > 1:
                    c.inner.pack_start(self.row("Use this display", self.switch(bool(s_["on"]), lambda v, n=o.name: toggle(n, v))), False, False, 2)
                if s_["on"]:
                    res = ChoiceButton(light=True, theme=self.th)
                    for m in o.modes:
                        res.append(m.key, m.label() + ("  (recommended)" if m.preferred is not None else ""))
                    res.set_active_id(s_["mode"] or "")
                    res.connect("changed", lambda w, n=o.name: set_mode(n, w.get_active_id()))
                    c.inner.pack_start(self.row("Resolution", res), False, False, 2)
                    cm = o.mode(s_["mode"])
                    if cm and len(cm.rates) > 1:
                        rt = ChoiceButton(light=True, theme=self.th)
                        for r in cm.rates:
                            rt.append("%g" % r, "%g Hz" % round(r, 2))
                        rt.set_active_id("%g" % (s_["rate"] or cm.rates[0]))
                        rt.connect("changed", lambda w, n=o.name: set_rate(n, float(w.get_active_id())))
                        c.inner.pack_start(self.row("Refresh rate", rt), False, False, 2)
                    rot = ChoiceButton(light=True, theme=self.th)
                    for k_, lab in displays.ROTATIONS:
                        rot.append(k_, lab)
                    rot.set_active_id(s_["rotation"])
                    rot.connect("changed", lambda w, n=o.name: set_rot(n, w.get_active_id()))
                    c.inner.pack_start(self.row("Orientation", rot), False, False, 2)
                    others = [x for x in outs if x.name != o.name and lay[x.name]["on"]]
                    if others:
                        pos = ChoiceButton(light=True, theme=self.th)
                        for x in others:
                            for k_, lab in displays.POSITIONS:
                                pos.append("%s|%s" % (k_, x.name), "%s %s" % (lab, x.name))
                        pos.append("keep", "Keep current position")
                        pos.set_active_id("keep")
                        pos.connect("changed", lambda w, n=o.name: set_pos(n, w.get_active_id()))
                        c.inner.pack_start(self.row("Position", pos), False, False, 2)
                    if len(outs) > 1:
                        mb = Gtk.Button(label="Main display" if s_.get("primary") else "Make main display")
                        mb.get_style_context().add_class("clear"); mb.set_sensitive(not s_.get("primary"))
                        mb.connect("clicked", lambda *_, n=o.name: make_primary(n))
                        c.inner.pack_start(self.row("Main display", mb), False, False, 2)
                holder.pack_start(c, False, False, 0)
            holder.show_all()
            refresh_bar()

        def toggle(n, v):
            if not v and sum(1 for s_ in st["work"].values() if s_["on"]) <= 1:
                say("At least one display must stay on."); GLib.idle_add(rebuild); return
            o = next(x for x in st["outs"] if x.name == n)
            s_ = st["work"][n]
            s_["on"] = bool(v)
            if v and not s_["mode"]:
                m, r = o.preferred()
                s_["mode"], s_["rate"] = (m.key, r) if m else (None, None)
            if not v and s_.get("primary"):
                displays.set_primary(st["work"], next(k for k, x in st["work"].items() if x["on"]))
            if v:                                                   # a screen that was off goes to the right of the others
                right = max((st["work"][k]["x"] + displays._size(next(x for x in st["outs"] if x.name == k), st["work"][k]["mode"], st["work"][k]["rotation"])[0]
                             for k in st["work"] if k != n and st["work"][k]["on"]), default=0)
                s_["x"], s_["y"] = right, 0
            GLib.idle_add(rebuild)

        def set_mode(n, key):
            o = next(x for x in st["outs"] if x.name == n)
            m = o.mode(key)
            if m is None or st["work"][n]["mode"] == key:
                return
            st["work"][n]["mode"] = key
            st["work"][n]["rate"] = m.rates[0]
            reflow(n)

        def set_rate(n, r):
            st["work"][n]["rate"] = r
            refresh_bar()

        def set_rot(n, rot):
            if st["work"][n]["rotation"] != rot:
                st["work"][n]["rotation"] = rot
                reflow(n)

        def reflow(n):
            """A size change moves the neighbours: keep each screen's side, re-pack so nothing overlaps and nothing leaves a gap."""
            lay, outs = st["work"], {o.name: o for o in st["outs"]}
            order = sorted([k for k, s_ in lay.items() if s_["on"]], key=lambda k: (lay[k]["x"], lay[k]["y"]))
            x = 0
            for k in order:
                w, h = displays._size(outs[k], lay[k]["mode"], lay[k]["rotation"])
                lay[k]["x"] = x
                x += w
            for k in order:
                lay[k]["y"] = 0
            GLib.idle_add(rebuild)

        def set_pos(n, val):
            if val == "keep":
                return
            rel, other = val.split("|", 1)
            displays.place(st["work"], st["outs"], n, rel, other)
            GLib.idle_add(rebuild)

        def make_primary(n):
            displays.set_primary(st["work"], n)
            GLib.idle_add(rebuild)

        # ---- Apply / Reset, with a revert countdown
        btn_row = Gtk.Box(spacing=8)
        apply_b = Gtk.Button(label="Apply"); apply_b.get_style_context().add_class("pill"); apply_b.get_style_context().add_class("active")
        reset_b = Gtk.Button(label="Reset"); reset_b.get_style_context().add_class("pill")
        btn_row.pack_end(apply_b, False, False, 0); btn_row.pack_end(reset_b, False, False, 0)
        bar_box.pack_start(btn_row, False, False, 0)
        confirm = Gtk.Box(spacing=10); confirm.set_no_show_all(True)
        c_lab = label("", "title", ellipsize=False)
        keep_b = Gtk.Button(label="Keep changes"); keep_b.get_style_context().add_class("pill"); keep_b.get_style_context().add_class("active")
        undo_b = Gtk.Button(label="Revert"); undo_b.get_style_context().add_class("pill")
        confirm.pack_start(c_lab, True, True, 0); confirm.pack_end(keep_b, False, False, 0); confirm.pack_end(undo_b, False, False, 0)
        bar_box.pack_start(confirm, False, False, 0)

        def refresh_bar():
            counting = st["timer"] is not None
            btn_row.set_visible(not counting)
            apply_b.set_sensitive(dirty()); reset_b.set_sensitive(dirty())
            confirm.set_visible(counting)

        def stop_timer():
            if st["timer"] is not None:
                GLib.source_remove(st["timer"]); st["timer"] = None

        def revert(*_):
            stop_timer()
            ok, m = displays.apply_layout(st["orig"])
            st["work"] = {k: dict(v) for k, v in st["orig"].items()}
            say("" if ok else "Could not restore the previous layout: " + m)
            rebuild()

        def keep(*_):
            stop_timer()
            st["outs"] = displays.query()
            st["orig"] = displays.layout_of(st["outs"])
            st["work"] = {k: dict(v) for k, v in st["orig"].items()}
            displays.save(st["orig"])
            say("Display settings saved. They are restored every time you log in.")
            rebuild()

        def apply_(*_):
            say("")
            ok, m = displays.apply_layout(st["work"])
            if not ok:
                say("Could not apply: " + (m or "xrandr failed") + ". Nothing was saved.")
                revert(); return
            left = {"n": 15}
            c_lab.set_text("Keep these display settings?  Reverting in 15 s")

            def tick():
                left["n"] -= 1
                if left["n"] <= 0:
                    st["timer"] = None
                    revert(); return False
                c_lab.set_text("Keep these display settings?  Reverting in %d s" % left["n"])
                return True
            st["timer"] = GLib.timeout_add_seconds(1, tick)
            refresh_bar()

        apply_b.connect("clicked", apply_); reset_b.connect("clicked", lambda *_: (st.update(work={k: dict(v) for k, v in st["orig"].items()}), rebuild()))
        keep_b.connect("clicked", keep); undo_b.connect("clicked", revert)
        p.connect("destroy", lambda *_: stop_timer())

        # ---- the rest of what "display options" means day to day
        c2 = self.card("Colour and comfort")
        tool = "gammastep" if services.have("gammastep") else ("redshift" if services.have("redshift") else None)
        if tool:
            row = Gtk.Box(spacing=8)
            for lab, temp in (("Warm (3500 K)", 3500), ("Warmer (2700 K)", 2700)):
                b = Gtk.Button(label=lab); b.get_style_context().add_class("clear")
                b.connect("clicked", lambda _b, t=temp: services.fire([tool, "-O", str(t)])); row.pack_start(b, False, False, 0)
            off = Gtk.Button(label="Night light off"); off.get_style_context().add_class("clear")
            off.connect("clicked", lambda *_: services.fire([tool, "-x"])); row.pack_start(off, False, False, 0)
            c2.inner.pack_start(label("Night light", "h2"), False, False, 2); c2.inner.pack_start(row, False, False, 0)
        else:
            c2.inner.pack_start(self.note("Night light needs gammastep or redshift."), False, False, 0)
        bl = services.Backlight()
        if bl.available:
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1); sc.set_value((bl.get() or 0.5) * 100); sc.set_value_pos(Gtk.PositionType.RIGHT)
            sc.connect("value-changed", lambda w: bl.set(w.get_value() / 100.0))
            c2.inner.pack_start(label("Screen brightness", "h2"), False, False, 4); c2.inner.pack_start(sc, False, False, 0)
        p.pack_start(c2, False, False, 0)
        rebuild()
        return p

    # ---------------------------------------------- network / bluetooth / power
    def p_network(self):
        return netpages.NetworkPage(self)

    def p_bluetooth(self):
        return netpages.BluetoothPage(self)

    def p_power(self):
        p = self.page_box(); c = self.card("Power")
        b = services.battery_info()
        c.inner.pack_start(self.row("Battery", label(("%d%% - %s" % (b["percent"], services.battery_text(b))) if b else "No battery", "muted")), False, False, 2)
        if services.have("powerprofilesctl"):
            row = Gtk.Box(spacing=8, homogeneous=True)
            for prof, lab in (("power-saver", "Power saver"), ("balanced", "Balanced"), ("performance", "Performance")):
                bt = Gtk.Button(label=lab); bt.get_style_context().add_class("clear")
                bt.connect("clicked", lambda _b, p_=prof: services.fire(["powerprofilesctl", "set", p_])); row.pack_start(bt, True, True, 0)
            c.inner.pack_start(label("Power profile", "h2"), False, False, 4); c.inner.pack_start(row, False, False, 0)
        else:
            c.inner.pack_start(self.note("Power profiles are not available."), False, False, 4)
        bl = services.Backlight()
        if bl.available:
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1); sc.set_value((bl.get() or 0.5) * 100); sc.set_value_pos(Gtk.PositionType.RIGHT)
            sc.connect("value-changed", lambda w: bl.set(w.get_value() / 100.0))
            c.inner.pack_start(label("Screen brightness", "h2"), False, False, 4); c.inner.pack_start(sc, False, False, 0)
        p.pack_start(c, False, False, 0)
        return p

    # ----------------------------------------------------------------- System
    def p_about(self):
        return aboutpage.build(self)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    appkit.run(Settings(argv[0] if argv else None))
