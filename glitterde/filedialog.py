"""The glitterDE file chooser: open a file (or several), choose a folder, save as.

A replacement for Gtk.FileChooserDialog in the same glass as every other dialog: places sidebar, breadcrumb path bar, sortable list, file-type
filter, new folder, hidden-file toggle, overwrite confirmation. It follows the theme and the light / dark scheme.

    path  = choose_file(parent, "Open file", start="/home/me", filters=[PICTURES])      # str, or None when cancelled
    paths = choose_file(parent, "Open files", multiple=True)                            # list of str, or None
    path  = choose_folder(parent, "Save screenshots to", start="/home/me/Pictures")
    path  = save_file(parent, "Save as", start="/home/me", name="notes.txt")

Like GlassPrompt they run a nested main loop and return the answer, so call sites read the same as with the stock dialog.
The decisions (what a click, Enter or the OK button means in each mode) are plain functions below, independent of GTK.
"""
import fnmatch
import mimetypes
import os
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango  # noqa: E402,F401

from . import appkit, scheme
from . import icons as ic
from .menus import GlassConfirm, GlassMenu
from .widgets import Ico, icon_button, label

MODES = ("open", "multiple", "folder", "save")
OK_LABEL = {"open": "Open", "multiple": "Open", "folder": "Choose", "save": "Save"}


# ------------------------------------------------------------------------------------------------------------------------ filters
class Filter:
    """A named file-type filter: patterns are MIME types ('image/png', 'image/*') or file-name globs ('*.py'); '*' matches everything."""

    def __init__(self, name, patterns):
        self.name, self.patterns = name, tuple(patterns)

    def matches(self, filename):
        low = filename.lower()
        mime = None
        for p in self.patterns:
            if p == "*":
                return True
            if "/" in p:
                if mime is None:
                    mime = mimetypes.guess_type(filename)[0] or ""
                if fnmatch.fnmatchcase(mime, p):
                    return True
            elif fnmatch.fnmatchcase(low, p.lower()):
                return True
        return False


PICTURES = Filter("Pictures", ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"))
ALL_FILES = Filter("All files", ("*",))


# ------------------------------------------------------------------------------------------------------------------------ pure logic
def resolve_location(text, cwd):
    """A typed path as an absolute one: '~' expands, a relative name is relative to the folder being shown."""
    text = text.strip()
    if not text:
        return cwd
    text = os.path.expanduser(text)
    return os.path.normpath(text if os.path.isabs(text) else os.path.join(cwd, text))


def breadcrumbs(path, home, limit=5):
    """[(label, path)] for the path bar. Under the home folder it starts at 'Home'; long paths are shortened to '…' + the last parts."""
    path = os.path.normpath(path)
    if path == home or path.startswith(home.rstrip(os.sep) + os.sep):
        items, base, rest = [("Home", home)], home, path[len(home):].strip(os.sep)
    else:
        items, base, rest = [("/", "/")], "/", path.strip(os.sep)
    for part in [p for p in rest.split(os.sep) if p]:
        base = os.path.join(base, part)
        items.append((part, base))
    if len(items) > limit:
        keep = items[-(limit - 1):]
        items = [("…", os.path.dirname(keep[0][1]) or "/")] + keep
    return items


def fmt_when(ts, now=None):
    """Modified time in the list: today -> '14:47', this year -> '24 Oct', older -> '24 Oct 2023'."""
    now = now if now is not None else time.time()
    t, n = time.localtime(ts), time.localtime(now)
    if (t.tm_year, t.tm_yday) == (n.tm_year, n.tm_yday):
        return time.strftime("%H:%M", t)
    if t.tm_year == n.tm_year:
        return time.strftime("%-d %b", t)
    return time.strftime("%-d %b %Y", t)


def list_dir(path, hidden=False, flt=None, mode="open", sort="name", reverse=False):
    """(entries, error). entries: [{'name','path','dir','size','mtime','enabled'}], folders first whatever the sort; error is a message
    when the folder cannot be read. Open / save modes hide files the filter rejects; folder mode shows files but disables them."""
    out = []
    try:
        with os.scandir(path) as it:
            for e in it:
                n = e.name
                if not hidden and n.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                    st = e.stat()
                    size, mtime = (0, st.st_mtime) if is_dir else (st.st_size, st.st_mtime)
                except OSError:
                    is_dir, size, mtime = False, 0, 0.0
                enabled = True
                if not is_dir:
                    if mode == "folder":
                        enabled = False
                    elif flt is not None and not flt.matches(n):
                        continue
                out.append({"name": n, "path": os.path.join(path, n), "dir": is_dir, "size": size, "mtime": mtime, "enabled": enabled})
    except PermissionError:
        return [], "You do not have permission to open this folder."
    except FileNotFoundError:
        return [], "This folder no longer exists."
    except OSError as e:
        return [], e.strerror or "This folder cannot be opened."
    if sort == "size":
        key = lambda e: (e["size"], e["name"].casefold())
    elif sort == "modified":
        key = lambda e: (e["mtime"], e["name"].casefold())
    else:
        key = lambda e: e["name"].casefold()
    dirs = sorted((e for e in out if e["dir"]), key=key, reverse=reverse)
    files = sorted((e for e in out if not e["dir"]), key=key, reverse=reverse)
    return dirs + files, ""


def decide(mode, cwd, selected, name="", exists=os.path.exists, isdir=os.path.isdir):
    """What pressing OK / Enter / double-click means. selected: [(path, is_dir)] of the selected rows.
    Returns None (nothing to do), ('finish', result), ('navigate', folder), ('replace', path) (ask first) or ('error', message)."""
    if mode == "save":
        text = name.strip()
        if not text:
            return None
        target = resolve_location(text, cwd)
        if os.path.basename(target) in ("", ".", ".."):
            return ("error", "Type a file name.")
        if isdir(target):
            return ("navigate", target)
        if not isdir(os.path.dirname(target)):
            return ("error", "That folder does not exist.")
        return ("replace", target) if exists(target) else ("finish", target)
    if mode == "folder":
        for p, d in selected:
            if d:
                return ("finish", p)
        return ("finish", cwd)
    if not selected:
        return None
    files = [p for p, d in selected if not d]
    if not files:
        return ("navigate", next(p for p, d in selected if d))
    return ("finish", files if mode == "multiple" else files[0])


def location_action(text, cwd, mode, isdir=os.path.isdir, isfile=os.path.isfile):
    """What Enter in the typed-location box does: ('navigate', folder), ('finish', file) or ('error', message)."""
    target = resolve_location(text, cwd)
    if isdir(target):
        return ("navigate", target)
    if mode in ("open", "multiple") and isfile(target):
        return ("finish", [target] if mode == "multiple" else target)
    if mode == "save" and isdir(os.path.dirname(target)):
        return ("name", target)
    return ("error", "There is no such file or folder.")


def user_places():
    """[(name, icon, path)]: home and the standard folders that exist, GTK bookmarks, the file system root and the mounted drives."""
    D = GLib.UserDirectory
    home = GLib.get_home_dir()
    out, seen = [("Home", "home", home)], {home}
    for name, icon, d in (("Desktop", "monitor", D.DIRECTORY_DESKTOP), ("Documents", "doc", D.DIRECTORY_DOCUMENTS), ("Downloads", "download", D.DIRECTORY_DOWNLOAD),
                          ("Music", "music", D.DIRECTORY_MUSIC), ("Pictures", "image", D.DIRECTORY_PICTURES), ("Videos", "film", D.DIRECTORY_VIDEOS)):
        p = GLib.get_user_special_dir(d)
        if p and p not in seen and os.path.isdir(p):
            out.append((name, icon, p))
            seen.add(p)
    try:
        with open(os.path.join(GLib.get_user_config_dir(), "gtk-3.0", "bookmarks"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                uri, _, nm = ln.strip().partition(" ")
                if uri.startswith("file://"):
                    p = Gio.File.new_for_uri(uri).get_path()
                    if p and p not in seen and os.path.isdir(p):
                        out.append((nm or os.path.basename(p) or p, "folder_line", p))
                        seen.add(p)
    except OSError:
        pass
    out.append(("Computer", "laptop", "/"))
    try:
        for m in Gio.VolumeMonitor.get().get_mounts():
            r = m.get_root()
            p = r.get_path() if r is not None else None
            if p and not m.is_shadowed() and p not in seen and p != "/":
                out.append((m.get_name(), "drive", p))
                seen.add(p)
    except Exception:
        pass
    return out


# ------------------------------------------------------------------------------------------------------------------------ icons
FOLDER_COLORS = {"Documents": ((.98, .68, 1, 1), (.84, .40, .95, 1)), "Downloads": ((.68, .88, 1, 1), (.45, .72, 1, 1)),
                 "Music": ((.82, .64, 1, 1), (.66, .46, .95, 1)), "Pictures": ((.66, .70, 1, 1), (.46, .52, .96, 1)),
                 "Videos": ((.54, .68, 1, 1), (.36, .52, .98, 1)), "Desktop": ((.64, .72, 1, 1), (.40, .52, .98, 1))}
DEFAULT_FOLDER = ((.62, .74, 1, 1), (.40, .55, 1, 1))
FILE_COLORS = {"pdf": ((1, .45, .62, 1), (.93, .32, .55, 1)), "png": ((.66, .58, 1, 1), (.52, .42, .95, 1)), "jpg": ((.66, .58, 1, 1), (.52, .42, .95, 1)),
               "jpeg": ((.66, .58, 1, 1), (.52, .42, .95, 1)), "webp": ((.66, .58, 1, 1), (.52, .42, .95, 1)), "svg": ((.35, .80, 1, 1), (.22, .60, .98, 1)),
               "zip": ((1, .78, .4, 1), (.95, .6, .25, 1)), "mp3": ((.55, .9, .7, 1), (.3, .75, .55, 1)), "py": ((.5, .75, 1, 1), (.35, .55, .95, 1)),
               "txt": ((.78, .8, .95, 1), (.6, .64, .88, 1)), "md": ((.78, .8, .95, 1), (.6, .64, .88, 1))}
DEFAULT_FILE = ((.72, .76, 1, 1), (.55, .6, .95, 1))
_PIX = {}


def row_icon(is_dir, name):
    ext = "" if is_dir else (name.rsplit(".", 1)[-1].lower() if "." in name else "")
    key = (True, name if name in FOLDER_COLORS else "") if is_dir else (False, ext)
    pb = _PIX.get(key)
    if pb is None:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 20, 20)
        cr = cairo.Context(surf)
        if is_dir:
            c = FOLDER_COLORS.get(name, DEFAULT_FOLDER)
            ic.folder(cr, 1, 3, 18, 15, c[0], c[1])
        else:
            c = FILE_COLORS.get(ext, DEFAULT_FILE)
            ic.file_icon(cr, 3.5, 1, 13, 18, c[0], c[1])
        pb = _PIX[key] = Gdk.pixbuf_get_from_surface(surf, 0, 0, 20, 20)
    return pb


# ------------------------------------------------------------------------------------------------------------------------ the dialog
_css_done = False


def _install_css():
    global _css_done
    ink = tuple(scheme.ink()[:3])
    acc = tuple(appkit.theme().color("accent.primary")[:3])
    rgba = lambda c, a: "rgba(%d,%d,%d,%.2f)" % (c[0] * 255, c[1] * 255, c[2] * 255, a)
    p = Gtk.CssProvider()
    p.load_from_data(("""
    treeview.chooserlist, treeview.chooserlist.view { background-color: transparent; background-image: none; }
    treeview.chooserlist:selected, treeview.chooserlist:selected:focus { background-color: %s; color: %s; }
    treeview.chooserlist header button { font-weight: 600; font-size: 11px; padding: 6px 8px; background: transparent; border: none; box-shadow: none; }
    list.chooserplaces, list.chooserplaces row { background-color: transparent; }
    list.chooserplaces row { padding: 6px 8px; margin: 1px 4px; border-radius: 10px; }
    list.chooserplaces row:hover { background-color: %s; }
    list.chooserplaces row:selected { background-color: %s; }
    button.crumb { padding: 3px 8px; border-radius: 9px; min-height: 0; background: transparent; border: none; box-shadow: none; }
    button.crumb:hover { background-color: %s; }
    label.choosererror { color: #ff6b88; }
    entry.error { border-color: #ff5c7a; }
    """ % (rgba(acc, 0.34), rgba(ink, 1.0), rgba(ink, 0.08), rgba(acc, 0.30), rgba(ink, 0.10))).encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 14)
    _css_done = True


class GlassFileChooser(appkit.GlassDialog):
    """mode: 'open' (one file), 'multiple' (several files), 'folder' (one folder), 'save'. run() -> str | [str] | None."""

    def __init__(self, title, mode="open", parent=None, start=None, name="", filters=None, ok=None):
        assert mode in MODES, mode
        super().__init__(title, getattr(parent, "wm_class", None) or "glitterde-filechooser", parent=parent, size=(860, 580))
        if not _css_done:
            _install_css()
        self.mode, self.filters = mode, list(filters or [])
        self.flt = self.filters[0] if self.filters else None
        self.hidden, self.sort, self.reverse = False, "name", False
        self.hist, self.pos, self.cwd = [], -1, None
        self._result, self._loop = None, None
        self._ink = scheme.ink()
        self.set_modal(True)
        self._own_keys()
        self._build(ok or OK_LABEL[mode], name)
        start = start if start and os.path.isdir(start) else GLib.get_home_dir()
        self.navigate(start)
        self.connect("map", lambda *_: (self.name_entry if mode == "save" else self.tree).grab_focus())
        self.connect("destroy", lambda *_: self._loop and self._loop.quit())

    # ---------------------------------------------------------------- construction
    def _own_keys(self):
        """GlassDialog closes on any Escape. Here Escape first leaves the typed-location box, so replace its key handler with ours."""
        try:
            sid = GObject.signal_lookup("key-press-event", Gtk.Widget)
            GObject.signal_handlers_disconnect_matched(self, GObject.SignalMatchType.ID, sid, 0, None, None, None)
        except Exception:
            pass
        self.connect("key-press-event", self._key)

    def _build(self, ok_text, name):
        box = self.body
        for m, v in (("start", 14), ("end", 14), ("top", 12), ("bottom", 10)):
            getattr(box, "set_margin_" + m)(v)
        box.set_spacing(10)
        ink = self._ink
        if self.mode == "save":
            row = Gtk.Box(spacing=10)
            row.pack_start(label("Name", "muted"), False, False, 0)
            self.name_entry = Gtk.Entry()
            self.name_entry.set_text(name)
            self.name_entry.set_hexpand(True)
            self.name_entry.connect("changed", lambda *_: (self.name_entry.get_style_context().remove_class("error"), self._msg(""), self._update_ok()))
            self.name_entry.connect("activate", lambda *_: self._accept())
            row.pack_start(self.name_entry, True, True, 0)
            box.pack_start(row, False, False, 0)
        bar = Gtk.Box(spacing=2)
        self.b_back = icon_button("arrow_left", 14, "Back (Alt+Left)", self.go_back, color=ink, pad=7)
        self.b_fwd = icon_button("arrow_right", 14, "Forward (Alt+Right)", self.go_forward, color=ink, pad=7)
        self.b_up = icon_button("arrow_up", 14, "Parent folder (Alt+Up)", self.go_up, color=ink, pad=7)
        for b in (self.b_back, self.b_fwd, self.b_up):
            bar.pack_start(b, False, False, 0)
        self.pathstack = Gtk.Stack()
        self.pathstack.set_hexpand(True)
        self.crumbs = Gtk.Box(spacing=0)
        ev = Gtk.EventBox()
        ev.set_visible_window(False)
        ev.set_tooltip_text("Click an empty part of the bar, or press Ctrl+L, to type a location")
        ev.add(self.crumbs)
        ev.connect("button-press-event", lambda w, e: (self._location(True), True)[1] if e.button == 1 else False)
        self.pathstack.add_named(ev, "crumbs")
        self.loc_entry = Gtk.Entry()
        self.loc_entry.set_placeholder_text("Type a path and press Enter")
        self.loc_entry.connect("activate", self._loc_activate)
        self.pathstack.add_named(self.loc_entry, "entry")
        bar.pack_start(self.pathstack, True, True, 6)
        if self.mode in ("save", "folder"):
            bar.pack_start(icon_button("folder_line", 15, "New folder", self.new_folder, color=ink, pad=7), False, False, 0)
        self.b_hidden = Gtk.ToggleButton(label="Hidden")
        self.b_hidden.get_style_context().add_class("choicebtn")
        self.b_hidden.set_tooltip_text("Show hidden files (Ctrl+H)")
        self.b_hidden.set_focus_on_click(False)
        self.b_hidden.connect("toggled", lambda b: self._set_hidden(b.get_active()))
        bar.pack_start(self.b_hidden, False, False, 0)
        box.pack_start(bar, False, False, 0)

        mid = Gtk.Box(spacing=10)
        side = Gtk.Box()
        side.get_style_context().add_class("sidebar")
        side.set_size_request(190, -1)
        self.places = Gtk.ListBox()
        self.places.get_style_context().add_class("chooserplaces")
        self.places.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.places.connect("row-activated", lambda lb, r: r.path and self.navigate(r.path))
        for pname, icon, path in user_places():
            r = Gtk.ListBoxRow()
            r.path = path
            h = Gtk.Box(spacing=10)
            h.pack_start(Ico(icon, 16, ink, 1.5), False, False, 2)
            h.pack_start(label(pname), True, True, 0)
            r.add(h)
            self.places.add(r)
        psw = Gtk.ScrolledWindow()
        psw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        psw.add(self.places)
        side.pack_start(psw, True, True, 0)
        mid.pack_start(side, False, False, 0)

        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, bool, float, float, str, str, bool)   # icon name path dir size mtime sizetxt datetxt enabled
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_style_context().add_class("chooserlist")
        self.tree.set_enable_search(True)
        self.tree.set_search_column(1)
        self.tree.set_headers_clickable(True)
        sel = self.tree.get_selection()
        sel.set_mode(Gtk.SelectionMode.MULTIPLE if self.mode == "multiple" else Gtk.SelectionMode.SINGLE)
        sel.set_select_function(lambda s, model, path, cur, *a: bool(model[path][8]))
        sel.connect("changed", self._sel_changed)
        self.tree.connect("row-activated", self._row_activated)
        self.cols = {}
        c = Gtk.TreeViewColumn("Name")
        pr = Gtk.CellRendererPixbuf()
        pr.set_padding(6, 3)
        c.pack_start(pr, False)
        c.add_attribute(pr, "pixbuf", 0)
        tr = Gtk.CellRendererText()
        tr.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        c.pack_start(tr, True)
        c.add_attribute(tr, "text", 1)
        c.set_cell_data_func(tr, self._dim)
        c.set_expand(True)
        self.cols["name"] = c
        for key, title, idx, right in (("size", "Size", 6, True), ("modified", "Modified", 7, False)):
            r = Gtk.CellRendererText()
            r.set_property("xalign", 1.0 if right else 0.0)
            r.set_padding(10, 3)
            cc = Gtk.TreeViewColumn(title, r, text=idx)
            cc.set_cell_data_func(r, self._dim)
            cc.set_min_width(96 if right else 110)
            if right:
                cc.set_alignment(1.0)
            self.cols[key] = cc
        for key, c in self.cols.items():
            c.set_resizable(True)
            c.set_clickable(True)
            c.connect("clicked", lambda col, k=key: self._sort_by(k))
            self.tree.append_column(c)
        tsw = Gtk.ScrolledWindow()
        tsw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tsw.add(self.tree)
        tsw.set_hexpand(True)
        tsw.set_vexpand(True)
        mid.pack_start(tsw, True, True, 0)
        box.pack_start(mid, True, True, 0)
        self._sort_marks()

        foot = Gtk.Box(spacing=8)
        self.info = label("", "muted", 0.0)
        foot.pack_start(self.info, True, True, 0)
        self.err = label("", "choosererror", 1.0, ellipsize=False)
        foot.pack_start(self.err, False, False, 0)
        if self.filters:
            self.b_filter = Gtk.Button()
            self.b_filter.get_style_context().add_class("choicebtn")
            h = Gtk.Box(spacing=6)
            self.filter_lbl = label(self.flt.name)
            h.pack_start(self.filter_lbl, False, False, 0)
            h.pack_start(Ico("chev_down", 11, ink, 1.8), False, False, 0)
            self.b_filter.add(h)
            self.b_filter.connect("clicked", self._filter_menu)
            foot.pack_end(self.b_filter, False, False, 0)
        box.pack_start(foot, False, False, 0)

        self.ok_btn = Gtk.Button(label=ok_text)
        self.ok_btn.get_style_context().add_class("pill")
        self.ok_btn.get_style_context().add_class("active")
        self.ok_btn.connect("clicked", lambda *_: self._accept())
        self.close_btn.set_label("Cancel")
        row = self.close_btn.get_parent()
        row.remove(self.close_btn)
        row.pack_end(self.ok_btn, False, False, 6)
        row.pack_end(self.close_btn, False, False, 0)
        self._update_ok()

    # ---------------------------------------------------------------- navigation
    def navigate(self, path, push=True):
        path = os.path.normpath(os.path.abspath(path))
        entries, err = list_dir(path, self.hidden, self.flt, self.mode, self.sort, self.reverse)
        if err:
            self._msg(err)
            return False
        self._msg("")
        if push:
            del self.hist[self.pos + 1:]
            if not self.hist or self.hist[-1] != path:
                self.hist.append(path)
            self.pos = len(self.hist) - 1
        self.cwd = path
        self._fill(entries)
        self._crumbs()
        self._sync_places()
        self.b_back.set_sensitive(self.pos > 0)
        self.b_fwd.set_sensitive(self.pos < len(self.hist) - 1)
        self.b_up.set_sensitive(path != "/")
        self._location(False)
        return True

    def refresh(self):
        if self.cwd:
            entries, err = list_dir(self.cwd, self.hidden, self.flt, self.mode, self.sort, self.reverse)
            if err:
                self._msg(err)
            else:
                self._fill(entries)

    def go_back(self, *_):
        if self.pos > 0:
            self.pos -= 1
            self.navigate(self.hist[self.pos], push=False)

    def go_forward(self, *_):
        if self.pos < len(self.hist) - 1:
            self.pos += 1
            self.navigate(self.hist[self.pos], push=False)

    def go_up(self, *_):
        if self.cwd and self.cwd != "/":
            self.navigate(os.path.dirname(self.cwd) or "/")

    def _fill(self, entries):
        self.store.clear()
        for e in entries:
            self.store.append([row_icon(e["dir"], e["name"]), e["name"], e["path"], e["dir"], float(e["size"]), float(e["mtime"]),
                               "" if e["dir"] else GLib.format_size(e["size"]), fmt_when(e["mtime"]) if e["mtime"] else "", e["enabled"]])
        n = len(entries)
        self.info.set_text("Empty folder" if not n else "%d item%s" % (n, "" if n == 1 else "s"))
        self._update_ok()

    def _crumbs(self):
        for ch in self.crumbs.get_children():
            self.crumbs.remove(ch)
        items = breadcrumbs(self.cwd, GLib.get_home_dir())
        for i, (text, path) in enumerate(items):
            b = Gtk.Button()
            b.get_style_context().add_class("crumb")
            b.set_relief(Gtk.ReliefStyle.NONE)
            lab = Gtk.Label()
            last = i == len(items) - 1
            lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(text) if last else GLib.markup_escape_text(text))
            b.add(lab)
            b.set_tooltip_text(path)
            b.connect("clicked", lambda _b, p=path: self.navigate(p))
            self.crumbs.pack_start(b, False, False, 0)
            if not last:
                self.crumbs.pack_start(Ico("chev_right", 10, self._ink, 1.6), False, False, 2)
        self.crumbs.show_all()

    def _sync_places(self):
        self.places.unselect_all()
        for r in self.places.get_children():
            if r.path == self.cwd:
                self.places.select_row(r)
                break

    def _location(self, show):
        if show:
            self.pathstack.set_visible_child_name("entry")
            self.loc_entry.set_text(self.cwd.rstrip("/") + "/")
            self.loc_entry.grab_focus()
            self.loc_entry.set_position(-1)
        else:
            self.pathstack.set_visible_child_name("crumbs")

    def _loc_activate(self, e):
        act = location_action(e.get_text(), self.cwd, self.mode)
        if act[0] == "navigate":
            self.navigate(act[1])
            self.tree.grab_focus()
        elif act[0] == "finish":
            self._finish(act[1])
        elif act[0] == "name":                                   # save: a path to a new file -> its folder + its name
            self.navigate(os.path.dirname(act[1]))
            self.name_entry.set_text(os.path.basename(act[1]))
            self.name_entry.grab_focus()
        else:
            self._msg(act[1])

    def _set_hidden(self, on):
        self.hidden = on
        self.refresh()

    def _sort_by(self, key):
        self.reverse = (not self.reverse) if key == self.sort else False
        self.sort = key
        self._sort_marks()
        self.refresh()

    def _sort_marks(self):
        for k, c in self.cols.items():
            c.set_sort_indicator(k == self.sort)
            c.set_sort_order(Gtk.SortType.DESCENDING if self.reverse else Gtk.SortType.ASCENDING)

    def _filter_menu(self, btn):
        items = [("check", f.name, f is self.flt, lambda f=f: self._set_filter(f)) for f in self.filters]
        win = btn.get_window()
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        m = GlassMenu(items, light=True, theme=appkit.theme(), min_width=max(160, a.width))
        m.show_all()
        h = m.get_preferred_height()[1]
        m.popup_at(ox + a.x, oy + a.y - h - 6)

    def _set_filter(self, f):
        self.flt = f
        self.filter_lbl.set_text(f.name)
        self.refresh()

    def new_folder(self, *_):
        if not self.cwd:
            return
        name = appkit.ask_text(self, "New folder", "Folder name", "Untitled folder", ok="OK")
        if not name:
            return
        if "/" in name or name in (".", ".."):
            self._msg("A folder name cannot contain slashes.")
            return
        try:
            os.mkdir(os.path.join(self.cwd, name))
        except OSError as e:
            self._msg("Could not create the folder: %s" % (e.strerror or e))
            return
        self.refresh()
        for r in self.store:                                     # select what was just made
            if r[1] == name:
                self.tree.get_selection().select_path(r.path)
                self.tree.scroll_to_cell(r.path, None, True, 0.5, 0.0)
                break

    # ---------------------------------------------------------------- selection and answers
    def _dim(self, col, cell, model, it, _d=None):
        r, g, b = self._ink[:3]
        cell.set_property("foreground-rgba", Gdk.RGBA(r, g, b, 1.0 if model.get_value(it, 8) else 0.42))

    def _selected(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return [(model[p][2], model[p][3]) for p in paths]

    def _msg(self, text):
        self.err.set_text(text)

    def _sel_changed(self, *_):
        sel = self._selected()
        if self.mode == "save":
            files = [p for p, d in sel if not d]
            if files:
                self.name_entry.set_text(os.path.basename(files[0]))
        if len(sel) == 1:
            p, d = sel[0]
            try:
                self.info.set_text(os.path.basename(p) + ("" if d else "  ·  " + GLib.format_size(os.stat(p).st_size)))
            except OSError:
                self.info.set_text(os.path.basename(p))
        elif sel:
            self.info.set_text("%d selected" % len(sel))
        self._update_ok()

    def _update_ok(self):
        if self.mode == "save":
            ok = bool(self.name_entry.get_text().strip())
        elif self.mode == "folder":
            ok = True
        else:
            ok = bool(self._selected())
        self.ok_btn.set_sensitive(ok)

    def _row_activated(self, tree, path, col):
        p, d = self.store[path][2], self.store[path][3]
        if not self.store[path][8]:
            return
        if d:
            self.navigate(p)
        else:
            self._accept()

    def _accept(self):
        act = decide(self.mode, self.cwd, self._selected(), self.name_entry.get_text() if self.mode == "save" else "")
        if act is None:
            return
        kind, val = act
        if kind == "finish":
            self._finish(val)
        elif kind == "navigate":
            self.navigate(val)
        elif kind == "error":
            self._msg(val)
            if self.mode == "save":
                self.name_entry.get_style_context().add_class("error")
        elif kind == "replace":
            GlassConfirm("Replace “%s”?" % os.path.basename(val),
                         "A file with this name already exists in %s. Saving replaces its contents." % (os.path.dirname(val) or "/"),
                         "Replace", lambda: self._finish(val), theme=appkit.theme()).show_centered()

    def _finish(self, result):
        self._result = result
        self.destroy()

    # ---------------------------------------------------------------- keys
    def _key(self, w, ev):
        st = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl, alt = bool(st & Gdk.ModifierType.CONTROL_MASK), bool(st & Gdk.ModifierType.MOD1_MASK)
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            if self.pathstack.get_visible_child_name() == "entry":
                self._location(False)
                self.tree.grab_focus()
            else:
                self.destroy()
            return True
        if ctrl and k in (Gdk.KEY_l, Gdk.KEY_L):
            self._location(True)
            return True
        if ctrl and k in (Gdk.KEY_h, Gdk.KEY_H):
            self.b_hidden.set_active(not self.b_hidden.get_active())
            return True
        if alt and k == Gdk.KEY_Left:
            self.go_back()
            return True
        if alt and k == Gdk.KEY_Right:
            self.go_forward()
            return True
        if alt and k == Gdk.KEY_Up:
            self.go_up()
            return True
        if k == Gdk.KEY_F5:
            self.refresh()
            return True
        if k == Gdk.KEY_BackSpace and not isinstance(self.get_focus(), Gtk.Entry):
            self.go_up()
            return True
        return False

    def run(self):
        self._loop = GLib.MainLoop()
        self.show_all()
        self.present()
        self._loop.run()
        return self._result


# ------------------------------------------------------------------------------------------------------------------------ entry points
def _start_dir(start):
    if start and os.path.isfile(start):
        return os.path.dirname(start)
    return start if start and os.path.isdir(start) else None


def choose_file(parent, title="Open file", start=None, multiple=False, filters=None, ok="Open"):
    """The chosen file (a list of files with multiple=True), or None when cancelled."""
    return GlassFileChooser(title, "multiple" if multiple else "open", parent, _start_dir(start), filters=filters, ok=ok).run()


def choose_folder(parent, title="Choose folder", start=None, ok="Choose"):
    return GlassFileChooser(title, "folder", parent, _start_dir(start), ok=ok).run()


def save_file(parent, title="Save as", start=None, name="", ok="Save", filters=None):
    """The path to save to (it may already exist: the user was asked to confirm replacing it), or None when cancelled."""
    if start and os.path.isfile(start):
        name = name or os.path.basename(start)
    return GlassFileChooser(title, "save", parent, _start_dir(start), name=name, filters=filters, ok=ok).run()
