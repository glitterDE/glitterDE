"""SparkFiles: glitterDE file manager (GTK3, Gio)."""
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GObject, Gio, GLib, Gtk  # noqa: E402
import cairo  # noqa: E402

from . import appkit, config
from . import icons as ic
from .gfx import text
from .filesops import FileOps
from .menus import GlassMenu
from .widgets import popup_menu, Ico, icon_button, label, search_overlay

from .scheme import ink
FOLDER_COLORS = {"Documents": ((.98, .68, 1, 1), (.84, .40, .95, 1)), "Downloads": ((.68, .88, 1, 1), (.45, .72, 1, 1)),
                 "Music": ((.82, .64, 1, 1), (.66, .46, .95, 1)), "Pictures": ((.66, .70, 1, 1), (.46, .52, .96, 1)),
                 "Videos": ((.54, .68, 1, 1), (.36, .52, .98, 1)), "Templates": ((.86, .70, 1, 1), (.68, .50, .95, 1)),
                 "Desktop": ((.64, .72, 1, 1), (.40, .52, .98, 1))}
DEFAULT_FOLDER = ((.62, .74, 1, 1), (.40, .55, 1, 1))
FILE_COLORS = {"pdf": ((1, .45, .62, 1), (.93, .32, .55, 1)), "png": ((.66, .58, 1, 1), (.52, .42, .95, 1)),
               "jpg": ((.66, .58, 1, 1), (.52, .42, .95, 1)), "jpeg": ((.66, .58, 1, 1), (.52, .42, .95, 1)),
               "svg": ((.35, .80, 1, 1), (.22, .60, .98, 1)), "zip": ((1, .78, .4, 1), (.95, .6, .25, 1)),
               "mp3": ((.55, .9, .7, 1), (.3, .75, .55, 1)), "py": ((.5, .75, 1, 1), (.35, .55, .95, 1)),
               "txt": ((.78, .8, .95, 1), (.6, .64, .88, 1)), "md": ((.78, .8, .95, 1), (.6, .64, .88, 1))}
DEFAULT_FILE = ((.72, .76, 1, 1), (.55, .6, .95, 1))
ATTRS = "standard::name,standard::display-name,standard::type,standard::is-hidden,standard::size,time::modified,standard::fast-content-type,trash::orig-path,trash::deletion-date"


def ago(ts):
    d = max(0, time.time() - ts)
    return "just now" if d < 60 else "%d min ago" % (d // 60) if d < 3600 else "%d hours ago" % (d // 3600) \
        if d < 86400 else "yesterday" if d < 172800 else "%d days ago" % (d // 86400)


class SparkFiles(FileOps, appkit.GlassWindow):
    def __init__(self, start=None):
        super().__init__("Files", "sparkfiles", "window_light", (940, 600))
        self.hist, self.pos, self.cwd, self.filter, self.hidden = [], -1, None, "", False
        self.tabs, self.cur_tab = [{"hist": [], "pos": -1, "cwd": None}], 0       # every tab keeps its own history; the views below show the current one
        saved = config.load("files.toml").get("view", {})
        self.sort = saved.get("sort", "name") if saved.get("sort") in ("name", "size", "type", "modified") else "name"
        self.sort_rev = bool(saved.get("reverse", False))
        self.view = "list" if saved.get("mode") == "list" else "icons"
        self._row_icons = {}
        self.monitor, self._reload_id = None, None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, "set_margin_" + m)(4 if m != "top" else 2)
        self.add(outer)
        tb = Gtk.Box(spacing=4)
        self.b_back = icon_button("arrow_left", 15, "Back (Alt+Left)", self.back, color=ink(), pad=8)
        self.b_fwd = icon_button("arrow_right", 15, "Forward (Alt+Right)", self.forward, color=ink(), pad=8)
        self.b_up = icon_button("arrow_up", 15, "Parent folder (Backspace)", self.up, color=ink(), pad=8)
        for b in (self.b_back, self.b_fwd, self.b_up):
            tb.pack_start(b, False, False, 0)
        self.path = Gtk.Entry(); self.path.set_hexpand(True)
        self.path.connect("activate", self._path_enter)
        self._path_dirty = False
        self.path.connect("changed", lambda e: setattr(self, "_path_dirty", e.has_focus()))
        self.path.connect("focus-out-event", lambda e, ev: setattr(self, "_path_dirty", False) or False)
        self.search = Gtk.Entry(); self.search.set_width_chars(20); self.search.set_placeholder_text("Search files...")
        self.search.connect("changed", lambda e: self._set_filter(e.get_text()))
        self.b_hid = icon_button("list", 15, "Menu", None, color=ink(), pad=8)
        self.b_hid.connect("clicked", lambda b: self._main_menu(b))
        self.b_view = icon_button("grid", 15, "", self.toggle_view, color=ink(), pad=8)
        self.b_tab = icon_button("plus", 15, "New tab (Ctrl+T)", self.new_tab, color=ink(), pad=8)
        tb.pack_start(self.path, True, True, 4); tb.pack_start(search_overlay(self.search, (0.165, 0.176, 0.43, 0.8)), False, False, 0)
        tb.pack_start(self.b_tab, False, False, 0); tb.pack_start(self.b_view, False, False, 0); tb.pack_start(self.b_hid, False, False, 0)
        outer.pack_start(tb, False, False, 0)
        self.tabstrip = Gtk.Box(spacing=4); self.tabstrip.set_no_show_all(True)          # only shown once there is more than one tab
        outer.pack_start(self.tabstrip, False, False, 0)

        body = Gtk.Box(spacing=8)
        outer.pack_start(body, True, True, 0)
        # sidebar
        self.places = Gtk.ListBox(); self.places.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.places.connect("row-activated", lambda lb, r: self.go(Gio.File.new_for_uri(r.uri)))
        self.places.connect("button-press-event", self._place_click)
        side = Gtk.ScrolledWindow(); side.add(self.places); side.set_size_request(190, -1)
        side.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sbox = Gtk.Box(); sbox.get_style_context().add_class("sidebar"); sbox.pack_start(side, True, True, 0)
        body.pack_start(sbox, False, False, 0)
        # content
        self.flow = Gtk.FlowBox(); self.flow.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.flow.set_activate_on_single_click(False); self.flow.set_valign(Gtk.Align.START)
        self.flow.set_homogeneous(True); self.flow.set_max_children_per_line(30); self.flow.set_min_children_per_line(2)
        self.flow.set_row_spacing(6); self.flow.set_column_spacing(6)
        self.flow.connect("child-activated", lambda f, ch: self.open_item(ch.info, ch.file))
        self.flow.connect("button-press-event", self._flow_click)
        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.empty = label("", "muted", 0.5, ellipsize=False)
        cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(cbox, "set_margin_" + m)(12)
        cbox.pack_start(self.flow, False, False, 0); cbox.pack_start(self.empty, False, False, 20)
        cbox.pack_start(self.recent_box, False, False, 0)
        # The content area is wrapped so that the empty space around and below the icons also takes part: right-click there opens the folder
        # menu, and dragging a box from there selects the icons it touches (rubber band).
        cbox.set_vexpand(True)
        self._bg = Gtk.EventBox(); self._bg.set_visible_window(False); self._bg.add(cbox)
        self._bg.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self._bg.connect("button-press-event", self._bg_click)
        self._band = cbox; self._band_rect = None                       # the rubber band is painted over the content (no overlay widget: it would eat the clicks)
        cbox.connect_after("draw", self._draw_band)
        self._band_gesture = Gtk.GestureDrag.new(self._bg); self._band_gesture.set_button(1)
        self._band_gesture.connect("drag-begin", self._band_begin)
        self._band_gesture.connect("drag-update", self._band_update)
        self._band_gesture.connect("drag-end", self._band_end)
        sw = Gtk.ScrolledWindow(); self._sw_icons = sw; sw.add(self._bg); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str, GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_style_context().add_class("filelist")
        self.tree.set_headers_clickable(True); self.tree.set_enable_search(False); self.tree.set_rubber_banding(True)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.connect("row-activated", lambda t, path, col: self._open_row(path))
        self.tree.connect("button-press-event", self._tree_click)
        self.cols = {}
        for key, title, idx, expand, right in (("name", "Name", 1, True, False), ("size", "Size", 2, False, True),
                                               ("type", "Type", 3, False, False), ("modified", "Modified", 4, False, False)):
            col = Gtk.TreeViewColumn(); col.set_resizable(True); col.set_expand(expand); col.set_clickable(True)
            # The header text is a label with the SAME offset as the cells (12 px; the name column starts at its icon, 6 px). Relying on the
            # theme's header-button padding left every header ~11 px off its column.
            hl = Gtk.Label(label=title); hl.set_xalign(1.0 if right else 0.0)
            hl.set_margin_start(7 if key == "name" else (0 if right else 14)); hl.set_margin_end(13 if right else 0)
            hl.set_hexpand(True); hl.set_halign(Gtk.Align.FILL)          # fill the column so xalign can right-align the Size header
            hl.show(); col.set_widget(hl)
            if right:
                col.set_alignment(1.0)
            if key == "name":
                pr = Gtk.CellRendererPixbuf(); pr.set_padding(6, 2); col.pack_start(pr, False); col.add_attribute(pr, "pixbuf", 0)
            tr = Gtk.CellRendererText(); tr.set_padding(12, 5)
            tr.set_property("foreground-rgba", Gdk.RGBA(*ink()))
            if key == "name":
                from gi.repository import Pango
                tr.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
            if right:
                tr.set_property("xalign", 1.0)
            col.pack_start(tr, True); col.add_attribute(tr, "text", idx)
            if key in ("size", "type", "modified"):
                col.set_min_width({"size": 90, "type": 150, "modified": 150}[key])
            col.connect("clicked", lambda c, k=key: self.header_sort(k))
            self.tree.append_column(col); self.cols[key] = col
        lsw = Gtk.ScrolledWindow(); lsw.add(self.tree); self._sw_list = lsw; lsw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        lbox = Gtk.Box(); lbox.set_border_width(8); lbox.pack_start(lsw, True, True, 0)
        lbg = Gtk.EventBox(); lbg.set_visible_window(False); lbg.add(lbox)          # the 8 px gap around the list takes right-clicks too
        lbg.connect("button-press-event", lambda w, ev: self._background_menu(ev) if ev.button == 3 else False)
        self.stack = Gtk.Stack(); self.stack.add_named(sw, "icons"); self.stack.add_named(lbg, "list")
        cwrap = Gtk.Box(); cwrap.get_style_context().add_class("inner"); cwrap.pack_start(self.stack, True, True, 0)
        body.pack_start(cwrap, True, True, 0)
        self.status = label("", "muted"); self.status.set_margin_start(8)
        outer.pack_start(self.status, False, False, 0)

        self._build_places()
        self._style_list()
        self.connect("key-press-event", self._key)
        f = Gio.File.new_for_commandline_arg(start) if start else Gio.File.new_for_path(GLib.get_home_dir())
        self.go(f)
        self.stack.show_all()
        self._apply_view()
        self.setup_dnd()

    def _style_list(self):
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        treeview.filelist, treeview.filelist:selected { background: transparent; }
        treeview.filelist { color: inherit; }
        treeview.filelist:selected { background-color: alpha(#7a5cff, 0.28); border-radius: 8px; }
        button.filetab { padding: 2px 6px; border-radius: 9px; background-image: none; box-shadow: none; border: 1px solid transparent; }
        button.filetab.sel { background-color: alpha(#7a5cff, 0.28); }
        button.filetab:hover { background-color: alpha(#7a5cff, 0.16); }
        entry.error { border-color: #ff5c7a; box-shadow: 0 0 0 1px #ff5c7a; }
        treeview.filelist header button { background: transparent; border: none; box-shadow: none; font-weight: 600; padding: 6px 0; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ------------------------------------------------------------- views and sorting
    def _save_view(self):
        d = config.load("files.toml"); d["view"] = {"mode": self.view, "sort": self.sort, "reverse": self.sort_rev}
        config.save(d, "files.toml")

    def _apply_view(self):
        self.stack.set_visible_child_name(self.view)
        self.b_view.set_tooltip_text("Switch to icon view" if self.view == "list" else "Switch to list view")
        for k, col in self.cols.items():
            col.set_sort_indicator(k == self.sort)
            col.set_sort_order(Gtk.SortType.DESCENDING if self.sort_rev else Gtk.SortType.ASCENDING)

    def toggle_view(self, *_):
        self.view = "icons" if self.view == "list" else "list"
        self._save_view(); self._apply_view(); self.refresh()

    def header_sort(self, key):
        """Click a column header: sort by it; click the same one again: reverse."""
        self.sort_rev = (not self.sort_rev) if key == self.sort else False
        self.sort = key
        self._save_view(); self._apply_view(); self.refresh()

    def _set_sort(self, how, rev=None):
        self.sort_rev = (how == "modified") if rev is None else rev           # menu: "Last modified" keeps meaning newest first
        self.sort = how
        self._save_view(); self._apply_view(); self.refresh()

    def _sorted(self, entries):
        def kind(i):
            return i.get_file_type() == Gio.FileType.DIRECTORY
        key = {"name": lambda i: i.get_display_name().casefold(),
               "size": lambda i: i.get_size(),
               "type": lambda i: (os.path.splitext(i.get_display_name())[1].lower(), i.get_display_name().casefold()),
               "modified": lambda i: i.get_attribute_uint64("time::modified")}[self.sort]
        dirs = sorted((i for i in entries if kind(i)), key=key if self.sort != "size" else (lambda i: i.get_display_name().casefold()),
                      reverse=self.sort_rev and self.sort != "size")
        files = sorted((i for i in entries if not kind(i)), key=key, reverse=self.sort_rev)
        return dirs + files                                                   # folders stay first, whatever the order

    def _row_icon(self, is_dir, name, ext):
        k = (is_dir, name if is_dir else ext)
        pb = self._row_icons.get(k)
        if pb is None:
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 28, 28); cr = cairo.Context(surf)
            cr.scale(0.58, 0.58)
            class _D:                                                          # SparkFiles' painter wants a DrawingArea-like object
                def get_allocated_width(self): return 48
                def get_allocated_height(self): return 48
            self._draw_icon(_D(), cr, is_dir, name, ext)
            pb = self._row_icons[k] = Gdk.pixbuf_get_from_surface(surf, 0, 0, 28, 28)
        return pb

    def _open_row(self, path):
        row = self.store[path]
        self.open_item(row[5], row[6])

    def _tree_click(self, tree, ev):
        if ev.button != 3:
            return False
        hit = tree.get_path_at_pos(int(ev.x), int(ev.y))
        sel = tree.get_selection()
        if hit is None:
            sel.unselect_all()
            return self._background_menu(ev)
        if not sel.path_is_selected(hit[0]):
            sel.unselect_all(); sel.select_path(hit[0])
        row = self.store[hit[0]]
        return self._item_menu(ev, row[5], row[6])

    # ------------------------------------------------------------- sidebar
    def _build_places(self):
        D = GLib.UserDirectory
        items = [("Home", "home", GLib.get_home_dir()), ("Desktop", "monitor", GLib.get_user_special_dir(D.DIRECTORY_DESKTOP)),
                 ("Documents", "doc", GLib.get_user_special_dir(D.DIRECTORY_DOCUMENTS)),
                 ("Downloads", "download", GLib.get_user_special_dir(D.DIRECTORY_DOWNLOAD)),
                 ("Music", "music", GLib.get_user_special_dir(D.DIRECTORY_MUSIC)),
                 ("Pictures", "image", GLib.get_user_special_dir(D.DIRECTORY_PICTURES)),
                 ("Videos", "film", GLib.get_user_special_dir(D.DIRECTORY_VIDEOS)), ("Trash", "trash", None)]
        for name, icn, p in items:
            if p is None and name != "Trash":
                continue
            uri = "trash:///" if name == "Trash" else Gio.File.new_for_path(p).get_uri()
            self._add_row(name, icn, uri)
        hdr = Gtk.ListBoxRow(); hdr.set_selectable(False); hdr.set_activatable(False)
        hdr.add(label("Devices", "muted")); self.places.add(hdr)
        self._add_row("Computer", "laptop", "file:///")
        self._refresh_devices()
        mon = Gio.VolumeMonitor.get()
        for sig in ("mount-added", "mount-removed", "mount-changed"):
            mon.connect(sig, lambda *_: GLib.idle_add(self._refresh_devices))      # plug in a stick: it shows up here, unplug: it goes
        self.places.show_all()

    def _refresh_devices(self):
        """Mounted drives under Devices, each with an eject button when it can be unmounted."""
        for r in [r for r in self.places.get_children() if getattr(r, "dev", False)]:
            self.places.remove(r)
        idx = next((i for i, r in enumerate(self.places.get_children()) if getattr(r, "uri", None) == "file:///"), None)
        if idx is None:
            return False
        for m in Gio.VolumeMonitor.get().get_mounts():
            if m.is_shadowed():
                continue
            r = Gtk.ListBoxRow(); r.uri = m.get_root().get_uri(); r.dev = True
            b = Gtk.Box(spacing=10); b.pack_start(Ico("drive", 14, ink(), 1.5), False, False, 2)
            b.pack_start(label(m.get_name()), True, True, 0)
            if m.can_unmount() or m.can_eject():
                eb = Gtk.Button(); eb.set_relief(Gtk.ReliefStyle.NONE); eb.set_tooltip_text("Safely remove")
                eb.add(Ico(self._eject_icon(), 12, ink(), 1.6))
                eb.connect("clicked", lambda _b, m=m: self._eject(m))
                b.pack_end(eb, False, False, 0)
            r.add(b)
            idx += 1
            self.places.insert(r, idx)
        self.places.show_all()
        if getattr(self, "cwd", None) is not None:           # also called while the window is still being built
            self._sync_sidebar()
        return False

    @staticmethod
    def _eject_icon():
        from . import icons
        for n in ("eject", "arrow_up", "chev_up"):
            try:
                if n in getattr(icons, "ICONS", {}) or hasattr(icons, "draw_" + n):
                    return n
            except Exception:
                pass
        return "chev_up"

    def _eject(self, mount):
        if self.cwd.get_uri().startswith(mount.get_root().get_uri()):       # do not leave the window inside the drive
            self.go(Gio.File.new_for_path(GLib.get_home_dir()))
        op = Gio.MountOperation()

        def done(m, res):
            try:
                (m.eject_with_operation_finish if m.can_eject() else m.unmount_with_operation_finish)(res)
                self.status.set_text("%s can be safely removed" % m.get_name())
            except GLib.Error as e:
                self.status.set_text("Could not remove %s: %s" % (m.get_name(), e.message))
        if mount.can_eject():
            mount.eject_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)
        else:
            mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)

    def _add_row(self, name, icn, uri):
        r = Gtk.ListBoxRow(); r.uri = uri
        b = Gtk.Box(spacing=10); b.pack_start(Ico(icn, 14, ink(), 1.5), False, False, 2); b.pack_start(label(name), False, False, 0)
        r.add(b); self.places.add(r)

    def _sync_sidebar(self):
        uri = self.cwd.get_uri().rstrip("/") + "/" if self.cwd.get_uri() != "file:///" else "file:///"
        best = None
        for r in self.places.get_children():
            u = getattr(r, "uri", None)
            if u and (uri == u.rstrip("/") + "/" or (uri.startswith(u.rstrip("/") + "/") and u != "file:///" and
                                                     (best is None or len(u) > len(best.uri)))):
                best = r if (best is None or len(u) >= len(best.uri)) else best
        if best:
            self.places.select_row(best)
        else:
            self.places.unselect_all()

    # ----------------------------------------------------------- navigation
    def go(self, f, push=True):
        try:
            if f.query_file_type(Gio.FileQueryInfoFlags.NONE, None) != Gio.FileType.DIRECTORY:
                self.open_item(None, f)
                return
        except GLib.Error as e:
            self.status.set_text("Cannot open: %s" % e.message)
            return
        if push:
            self.hist = self.hist[:self.pos + 1] + [f]
            self.pos = len(self.hist) - 1
        self.cwd = f
        self.search.set_text(""); self.filter = ""
        self._watch_dir()
        self.refresh()

    # ------------------------------------------------------------- tabs
    def _save_tab(self):
        self.tabs[self.cur_tab].update(hist=list(self.hist), pos=self.pos, cwd=self.cwd)

    def _load_tab(self, i):
        t = self.tabs[i]
        self.cur_tab = i
        self.hist, self.pos = list(t["hist"]), t["pos"]
        self.go(t["cwd"] or Gio.File.new_for_path(GLib.get_home_dir()), push=False)

    def new_tab(self, f=None):
        if not isinstance(f, Gio.File):
            f = self.cwd or Gio.File.new_for_path(GLib.get_home_dir())
        self._save_tab()
        self.tabs.append({"hist": [f], "pos": 0, "cwd": f})
        self._load_tab(len(self.tabs) - 1)
        self._rebuild_tabs()

    def switch_tab(self, i):
        if 0 <= i < len(self.tabs) and i != self.cur_tab:
            self._save_tab()
            self._load_tab(i)
            self._rebuild_tabs()

    def close_tab(self, i=None):
        i = self.cur_tab if i is None else i
        if len(self.tabs) <= 1:
            self.destroy()
            return
        self._save_tab()
        del self.tabs[i]
        if i < self.cur_tab:
            self.cur_tab -= 1
        self.cur_tab = min(self.cur_tab, len(self.tabs) - 1)
        self._load_tab(self.cur_tab)
        self._rebuild_tabs()

    def _tab_title(self, t):
        f = t.get("cwd")
        if f is None:
            return "Files"
        if f.get_uri() == "trash:///":
            return "Trash"
        if f.get_path() == GLib.get_home_dir():
            return "Home"
        return f.get_basename() or "/"

    def _rebuild_tabs(self):
        for ch in self.tabstrip.get_children():
            self.tabstrip.remove(ch); ch.destroy()
        self._save_tab()
        for i, t in enumerate(self.tabs):
            box = Gtk.Box(spacing=4)
            lb = label(self._tab_title(t)); lb.set_max_width_chars(18)
            box.pack_start(lb, False, False, 0)
            x = icon_button("close", 9, "Close tab", lambda i=i: self.close_tab(i), color=ink(), pad=4)
            box.pack_start(x, False, False, 0)
            b = Gtk.Button(); b.add(box); b.set_relief(Gtk.ReliefStyle.NONE); b.set_focus_on_click(False)
            ctx = b.get_style_context(); ctx.add_class("filetab")
            if i == self.cur_tab:
                ctx.add_class("sel")
            b.connect("clicked", lambda _b, i=i: self.switch_tab(i))
            b.connect("button-press-event", lambda _b, ev, i=i: (self.close_tab(i), True)[1] if ev.button == 2 else False)   # middle-click closes
            self.tabstrip.pack_start(b, False, False, 0)
        multi = len(self.tabs) > 1
        self.tabstrip.set_visible(multi)
        if multi:
            self.tabstrip.show_all()

    def back(self):
        if self.pos > 0:
            self.pos -= 1; self.go(self.hist[self.pos], push=False)

    def forward(self):
        if self.pos < len(self.hist) - 1:
            self.pos += 1; self.go(self.hist[self.pos], push=False)

    def up(self):
        p = self.cwd.get_parent()
        if p:
            self.go(p)

    def _path_enter(self, e):
        """Enter in the location box: ~, relative paths (against the folder being shown), URIs and trailing slashes all work."""
        t = e.get_text().strip()
        if not t:
            return
        if "://" in t:
            f = Gio.File.new_for_uri(t)
        else:
            t = os.path.expanduser(os.path.expandvars(t))
            if not os.path.isabs(t):
                base = self.cwd.get_path() if self.cwd is not None and self.cwd.get_path() else GLib.get_home_dir()
                t = os.path.join(base, t)
            f = Gio.File.new_for_path(os.path.normpath(t))
        self._path_dirty = False
        self.go(f)
        if self.cwd is not None and self.cwd.equal(f):
            self._focus_content()
        else:
            self.path.get_style_context().add_class("error")             # the status bar says why; the box turns red until you edit it
            self.path.connect_after("changed", lambda w: w.get_style_context().remove_class("error"))

    def _focus_content(self):
        (self.tree if self.view == "list" else self.flow).grab_focus()

    def _main_menu(self, btn):
        items = [("item", "New folder…", self.new_folder),
                 ("item", "Open terminal here", lambda: __import__("glitterde.services", fromlist=["fire"]).fire(["sparkterm", self.cwd.get_path() or GLib.get_home_dir()])),
                 ("sep",), ("head", "Sort by"),
                 ("check", "Name", self.sort == "name", lambda: self._set_sort("name")),
                 ("check", "Size", self.sort == "size", lambda: self._set_sort("size")),
                 ("check", "Type", self.sort == "type", lambda: self._set_sort("type")),
                 ("check", "Last modified", self.sort == "modified", lambda: self._set_sort("modified")),
                 ("check", "Reverse order", self.sort_rev, lambda: self._set_sort(self.sort, not self.sort_rev)),
                 ("sep",),
                 ("check", "List view", self.view == "list", self.toggle_view),
                 ("sep",),
                 ("check", "Show hidden files", self.hidden, self.toggle_hidden),
                 ("item", "Select all", self.select_all),
                 ("item", "Refresh", self.refresh)]
        pos = btn.translate_coordinates(self, 0, 0) or (0, 0)
        r = self.get_window().get_origin()
        GlassMenu(items, light=True, theme=self.th).popup_at(r[-2] + pos[0] - 150, r[-1] + pos[1] + btn.get_allocated_height() + 4)

    def select_all(self):
        self.tree.get_selection().select_all() if self.view == "list" else self.flow.select_all()

    def toggle_hidden(self):
        self.hidden = not self.hidden
        self.refresh()

    def _set_filter(self, t):
        self.filter = t.strip().lower()
        self.refresh()

    def _watch_dir(self):
        if self.monitor:
            self.monitor.cancel()
        try:
            self.monitor = self.cwd.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.monitor.connect("changed", self._changed)
        except GLib.Error:
            self.monitor = None

    def _changed(self, *_):
        if self._reload_id:
            GLib.source_remove(self._reload_id)
        self._reload_id = GLib.timeout_add(250, lambda: (setattr(self, "_reload_id", None), self.refresh(), False)[2])

    # -------------------------------------------------------------- listing
    def refresh(self):
        if self.cwd is None:                          # nothing opened yet (bad start path): nothing to list
            return
        for ch in self.flow.get_children():
            self.flow.remove(ch)
        self.store.clear()
        entries = []
        err = None
        try:
            en = self.cwd.enumerate_children(ATTRS, Gio.FileQueryInfoFlags.NONE, None)
            for i in en:
                if len(entries) >= 4000:
                    break
                if (i.get_is_hidden() or i.get_name().startswith(".")) and not self.hidden:
                    continue
                if self.filter and self.filter not in i.get_display_name().lower():
                    continue
                entries.append(i)
        except GLib.Error as e:
            err = e.message
        entries = self._sorted(entries)
        if self.view == "list":
            for i in entries:
                is_dir = i.get_file_type() == Gio.FileType.DIRECTORY
                nm = i.get_display_name(); ext = os.path.splitext(nm)[1].lstrip(".").lower()
                ct = i.get_attribute_string("standard::fast-content-type") or ""
                kind = "Folder" if is_dir else ((Gio.content_type_get_description(ct) or "").capitalize() if ct and not ct.startswith("application/octet") else
                                                ("%s file" % ext.upper() if ext else "File"))
                mt = i.get_attribute_uint64("time::modified")
                self.store.append([self._row_icon(is_dir, nm, ext), nm, "" if is_dir else GLib.format_size(i.get_size()), kind,
                                   time.strftime("%Y-%m-%d  %H:%M", time.localtime(mt)) if mt else "", i, self.cwd.get_child(i.get_name())])
        else:
            for i in entries:
                self.flow.add(self._make_item(i))
        self.flow.show_all()
        self.stack.set_visible_child_name(self.view)
        name = self.cwd.get_basename() if self.cwd.get_path() != GLib.get_home_dir() else "Home"
        if self.cwd.get_uri() == "trash:///":
            name = "Trash"
        self.set_title(name or "/")
        if not (self.path.has_focus() and self.path.get_text() != (self.cwd.get_path() or self.cwd.get_uri()) and self._path_dirty):
            self.path.set_text(self.cwd.get_path() or self.cwd.get_uri())      # (a background refresh must not wipe a path being typed)
        self.b_back.set_sensitive(self.pos > 0); self.b_fwd.set_sensitive(self.pos < len(self.hist) - 1)
        self.b_up.set_sensitive(self.cwd.get_parent() is not None)
        self.empty.set_text(err or ("No files match." if self.filter else "This folder is empty.") if not entries else "")
        self.empty.set_visible(not entries)
        self.status.set_text("%d item%s%s" % (len(entries), "" if len(entries) == 1 else "s", "  (hidden files shown)" if self.hidden else ""))
        self._recent()
        self._sync_sidebar()
        if len(self.tabs) > 1 and getattr(self, "tabstrip", None) is not None:
            self._rebuild_tabs()

    def _make_item(self, info):
        is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
        name = info.get_display_name()
        ch = Gtk.FlowBoxChild(); ch.info = info; ch.file = self.cwd.get_child(info.get_name())
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); v.set_margin_top(8); v.set_margin_bottom(6)
        da = Gtk.DrawingArea(); da.set_size_request(76, 52)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        da.connect("draw", self._draw_icon, is_dir, name, ext)
        l = label(name, xalign=0.5, ellipsize=False); l.set_line_wrap(True); l.set_max_width_chars(13); l.set_lines(2)
        l.set_justify(Gtk.Justification.CENTER)
        from gi.repository import Pango
        l.set_ellipsize(Pango.EllipsizeMode.MIDDLE); l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        v.pack_start(da, False, False, 0); v.pack_start(l, False, False, 0)
        ch.add(v); ch.set_tooltip_text(name)
        ch.connect("button-press-event", self._item_click)
        return ch

    @staticmethod
    def _draw_icon(da, cr, is_dir, name, ext):
        cx, cy = da.get_allocated_width() / 2, da.get_allocated_height() / 2
        if is_dir:
            top, bot = FOLDER_COLORS.get(name, DEFAULT_FOLDER)
            ic.folder(cr, cx - 24, cy - 22, 48, 42, top, bot)
            if name == "Desktop":
                ic.icon(cr, "monitor", cx, cy + 5, 16, (1, 1, 1, .9), 1.4)
        else:
            c1, c2 = FILE_COLORS.get(ext, DEFAULT_FILE)
            ic.file_icon(cr, cx - 17, cy - 22, 34, 42, c1, c2, ext.upper()[:4] if ext else None, None if ext else "doc")
        return False

    def _recent(self):
        for ch in self.recent_box.get_children():
            self.recent_box.remove(ch)
        if self.cwd.get_path() != GLib.get_home_dir() or self.filter:
            return
        try:
            items = [i for i in Gtk.RecentManager.get_default().get_items() if i.exists()]
        except Exception:
            items = []
        items.sort(key=lambda i: i.get_modified(), reverse=True)
        if not items:
            return
        self.recent_box.pack_start(label("Recent", "h2"), False, False, 4)
        for it in items[:4]:
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE)
            r = Gtk.Box(spacing=10)
            da = Gtk.DrawingArea(); da.set_size_request(26, 30)
            ext = os.path.splitext(it.get_display_name())[1].lstrip(".").lower()
            da.connect("draw", lambda w, cr, e=ext: (ic.file_icon(cr, 3, 2, 20, 26, *FILE_COLORS.get(e, DEFAULT_FILE),
                                                                   e.upper()[:3] or None, None), False)[1])
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.pack_start(label(it.get_display_name()), False, False, 0)
            v.pack_start(label(ago(it.get_modified()), "muted"), False, False, 0)
            r.pack_start(da, False, False, 0); r.pack_start(v, True, True, 0)
            b.add(r); b.connect("clicked", lambda _b, u=it.get_uri(): self.open_uri(u))
            self.recent_box.pack_start(b, False, False, 0)
        self.recent_box.show_all()

    # -------------------------------------------------------------- actions
    def open_uri(self, uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, self.get_display().get_app_launch_context())
        except GLib.Error as e:
            self.status.set_text("Could not open: %s" % e.message)

    def open_item(self, info, f):
        if info is not None and info.get_file_type() == Gio.FileType.DIRECTORY:
            self.go(f)
        else:
            self.open_uri(f.get_uri())

    def selected(self):
        if self.view == "list":
            model, paths = self.tree.get_selection().get_selected_rows()
            return [(model[p][5], model[p][6]) for p in paths]
        return [(c.info, c.file) for c in self.flow.get_selected_children()]

    def new_folder(self):
        name = self._ask("New folder", "Folder name", "Untitled folder")
        if name:
            try:
                self.cwd.get_child(name).make_directory(None)
            except GLib.Error as e:
                self.status.set_text("Could not create folder: %s" % e.message)

    def rename(self, info, f):
        name = self._ask("Rename", "New name", info.get_display_name())
        if name and name != info.get_name():
            try:
                f.set_display_name(name, None)
            except GLib.Error as e:
                self.status.set_text("Could not rename: %s" % e.message)

    def trash(self):
        for info, f in self.selected():
            try:
                f.trash(None)
            except GLib.Error as e:
                self.status.set_text("Could not move to Trash: %s" % e.message)

    def _ask(self, title, prompt, default=""):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        e = Gtk.Entry(); e.set_text(default); e.set_activates_default(True); e.set_margin_start(14); e.set_margin_end(14)
        d.get_content_area().pack_start(label(prompt), False, False, 10); d.get_content_area().pack_start(e, False, False, 10)
        d.show_all()
        r = d.run(); t = e.get_text().strip(); d.destroy()
        return t if r == Gtk.ResponseType.OK and t else None

    # ----------------------------------------------------------- input / menus
    def _item_click(self, ch, ev):
        if ev.button == 3:
            if ch not in self.flow.get_selected_children():
                self.flow.unselect_all(); self.flow.select_child(ch)
            return self._item_menu(ev, ch.info, ch.file)
        if ev.button == 2 and ch.info.get_file_type() == Gio.FileType.DIRECTORY:           # middle-click a folder: new tab
            self.new_tab(ch.file); return True
        return False

    def _bg_click(self, w, ev):
        """Press on the content area that the icons themselves did not take: right-click = folder menu."""
        if ev.button == 3 and self._flow_child_at(ev.x, ev.y) is None:
            return self._background_menu(ev)
        return False

    def _flow_child_at(self, x, y):
        pos = self._bg.translate_coordinates(self.flow, int(x), int(y))
        return self.flow.get_child_at_pos(*pos) if pos else None

    def _band_begin(self, g, x, y):
        if self._flow_child_at(x, y) is not None:                       # pressing an icon: normal click / drag-out
            g.set_state(Gtk.EventSequenceState.DENIED); self._band_start = None; return
        self._band_start = (x, y)
        ev = Gtk.get_current_event()
        keep = bool(ev is not None and ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self._band_base = set(self.flow.get_selected_children()) if keep else set()
        if not keep:
            self.flow.unselect_all()
        g.set_state(Gtk.EventSequenceState.CLAIMED)

    def _band_update(self, g, dx, dy):
        if not getattr(self, "_band_start", None):
            return
        x0, y0 = self._band_start
        r = (min(x0, x0 + dx), min(y0, y0 + dy), abs(dx), abs(dy))
        self._band_rect = r
        for ch in self.flow.get_children():
            pos = ch.translate_coordinates(self._bg, 0, 0)
            if pos is None:
                continue
            a = ch.get_allocation()
            hit = pos[0] < r[0] + r[2] and pos[0] + a.width > r[0] and pos[1] < r[1] + r[3] and pos[1] + a.height > r[1]
            want = hit or ch in self._band_base
            if want != ch.is_selected():
                self.flow.select_child(ch) if want else self.flow.unselect_child(ch)
        self._band.queue_draw()

    def _band_end(self, g, dx, dy):
        self._band_start = None; self._band_rect = None
        self._band.queue_draw()

    def _draw_band(self, w, cr):
        r = self._band_rect
        if not r or r[2] < 2 and r[3] < 2:
            return False
        cr.rectangle(*r); cr.set_source_rgba(0.45, 0.5, 1.0, 0.18); cr.fill_preserve()
        cr.set_source_rgba(0.45, 0.5, 1.0, 0.75); cr.set_line_width(1); cr.stroke()
        return False

    def _flow_click(self, w, ev):
        ch = self.flow.get_child_at_pos(ev.x, ev.y)
        self._press_item = (ch.info, ch.file) if ch is not None else None
        if ev.button == 3 and ch is None:
            return self._background_menu(ev)
        if ev.button == 3 and ch is not None:               # GtkFlowBoxChild does not reliably get its own press events: handle the item menu here too
            return self._item_click(ch, ev)
        return False

    def _key(self, w, ev):
        k, ctrl, alt = ev.keyval, ev.state & Gdk.ModifierType.CONTROL_MASK, ev.state & Gdk.ModifierType.MOD1_MASK
        foc = self.get_focus()
        typing = isinstance(foc, Gtk.Entry)
        if alt and k == Gdk.KEY_Left:
            self.back()
        elif alt and k == Gdk.KEY_Right:
            self.forward()
        elif alt and k == Gdk.KEY_Up:
            self.up()
        elif ctrl and k in (Gdk.KEY_h, Gdk.KEY_H):
            self.toggle_hidden()
        elif ctrl and k == Gdk.KEY_1:
            if self.view != "icons":
                self.toggle_view()
        elif ctrl and k == Gdk.KEY_2:
            if self.view != "list":
                self.toggle_view()
        elif ctrl and not ev.state & Gdk.ModifierType.SHIFT_MASK and k in (Gdk.KEY_t, Gdk.KEY_T):
            self.new_tab()
        elif ctrl and not ev.state & Gdk.ModifierType.SHIFT_MASK and k in (Gdk.KEY_w, Gdk.KEY_W):
            self.close_tab()
        elif ctrl and k in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up) and len(self.tabs) > 1:
            self.switch_tab((self.cur_tab + (1 if k == Gdk.KEY_Page_Down else -1)) % len(self.tabs))
        elif ctrl and k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and len(self.tabs) > 1:
            self.switch_tab((self.cur_tab + (-1 if ev.state & Gdk.ModifierType.SHIFT_MASK else 1)) % len(self.tabs))
        elif ctrl and k in (Gdk.KEY_l, Gdk.KEY_L):
            self.path.grab_focus()
        elif ctrl and k in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
        elif ctrl and not typing and k in (Gdk.KEY_c, Gdk.KEY_C) and self.selected():
            self.copy_sel()
        elif ctrl and not typing and k in (Gdk.KEY_x, Gdk.KEY_X) and self.selected():
            self.cut_sel()
        elif ctrl and not typing and k in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste_into(self._folder_for_paths())
        elif ctrl and not typing and k in (Gdk.KEY_a, Gdk.KEY_A):
            self.select_all()
        elif alt and k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.properties()
        elif k == Gdk.KEY_Delete and not typing and ev.state & Gdk.ModifierType.SHIFT_MASK and self.selected():
            self.delete_sel() if self.in_trash() else self.trash()
        elif k == Gdk.KEY_F5:
            self.refresh()
        elif ctrl and ev.state & Gdk.ModifierType.SHIFT_MASK and k in (Gdk.KEY_n, Gdk.KEY_N):
            self.new_folder()
        elif k == Gdk.KEY_BackSpace and not typing:
            self.up()
        elif k == Gdk.KEY_Delete and not typing:
            self.trash()
        elif k == Gdk.KEY_F2 and not typing and self.selected():
            self.rename(*self.selected()[0])
        else:
            return False
        return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    appkit.run(SparkFiles(argv[0] if argv else None))
