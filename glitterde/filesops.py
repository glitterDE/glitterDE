"""File operations and the right-click menus of SparkFiles (mixed into SparkFiles).

Item menu: open / open with / new window / terminal, cut / copy / paste, rename, duplicate, move to / copy to / link, compress / extract,
set as wallpaper, copy path, trash (restore / delete permanently inside the Trash), properties.
Background menu: new folder / new document (+ ~/Templates), paste, select all, sort, view, hidden files, terminal, copy path, properties, refresh.
Copy/cut use the desktop clipboard format (x-special/gnome-copied-files) so files move between SparkFiles windows and other file managers.
"""
import os
import shutil
import tarfile
import threading
import time
import zipfile

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import appkit, config, services
from .menus import GlassMenu
from .progress import Cancelled, Job, ProgressWindow, copy_tree, delete_tree, move_file, remove_quietly, scan
from .widgets import label

COPIED = "x-special/gnome-copied-files"
TARGETS = (COPIED, "text/uri-list", "text/plain")
ARCHIVE_EXT = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
DOUBLE_EXT = (".tar.gz", ".tar.bz2", ".tar.xz")
NOFOLLOW = Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS


def split_name(name):
    low = name.lower()
    for e in DOUBLE_EXT:
        if low.endswith(e):
            return name[:-len(e)], name[-len(e):]
    stem, ext = os.path.splitext(name)
    return (name, "") if not stem else (stem, ext)


def unique_child(folder, name, suffix=" (copy)"):
    """A child of `folder` that does not exist yet: name, then 'name (copy).ext', 'name (copy 2).ext', ..."""
    f = folder.get_child(name)
    if not f.query_exists(None):
        return f
    stem, ext = split_name(name)
    n = 1
    while True:
        cand = "%s%s%s" % (stem, suffix if n == 1 else suffix[:-1] + " %d)" % n, ext)
        f = folder.get_child(cand)
        if not f.query_exists(None):
            return f
        n += 1


def is_archive(name):
    return name.lower().endswith(ARCHIVE_EXT)


def inside(child, parent):
    a, b = child.get_path(), parent.get_path()
    return bool(a and b and (a == b or a.startswith(b.rstrip("/") + "/")))


class FileOps:
    # ------------------------------------------------------------ plumbing
    def _progress_window(self):
        pw = getattr(self, "_pw", None)
        if pw is None:
            pw = self._pw = ProgressWindow(self)
        return pw

    def _run_job(self, title, work, done_text, verb="Working", total=(0, 0), copy_cleanup=False):
        """Run work(job) off the UI thread with a progress entry (window opens when it takes a moment) and a Cancel button.
        total = (bytes, items) when known. copy_cleanup: a cancelled COPY removes what it already made."""
        job = Job(title, verb)
        job.total, job.n_total = total
        self.status.set_text(title)
        pw = self._progress_window()
        pw.add_job(job)

        def run():
            err = None
            try:
                work(job)
            except Cancelled:
                job.cancelled = True
            except (GLib.Error, OSError, shutil.Error, zipfile.BadZipFile, tarfile.TarError, ValueError) as e:
                err = getattr(e, "message", None) or str(e)
            if job.cancelled or err:                           # do not leave half-written files lying around
                if job.partial is not None:
                    remove_quietly(job.partial)
                if copy_cleanup and job.cancelled:
                    for t in job.created:
                        remove_quietly(t)
            GLib.idle_add(self._job_done, job, err, done_text)
        threading.Thread(target=run, daemon=True).start()
        return job

    def _job(self, doing, work, done_text):
        """Simple background job without byte progress (the bar pulses): work() takes no arguments."""
        return self._run_job(doing, lambda job: work(), done_text)

    def _job_done(self, job, err, done_text):
        job.finished, job.error = True, err
        self.refresh()
        self.status.set_text("Cancelled" if job.cancelled else ("Failed: %s" % err) if err else done_text)
        self._progress_window().finish(job)
        return False

    def _say(self, text):
        self.status.set_text(text)

    def _sel_files(self):
        return [f for _i, f in self.selected()]

    def _folder_for_paths(self):
        """Where 'terminal here' / 'new' should act: the selected folder, else the one being viewed."""
        s = self.selected()
        if len(s) == 1 and s[0][0].get_file_type() == Gio.FileType.DIRECTORY:
            return s[0][1]
        return self.cwd

    # ------------------------------------------------------------ clipboard
    def clip_set(self, op, files):
        files = [f for f in files if f is not None]
        if not files:
            return
        uris = [f.get_uri() for f in files]
        names = "\n".join(f.get_path() or f.get_uri() for f in files)

        self._clip = (op, uris, names)
        if not getattr(self, "_clip_wired", False):                  # PyGObject hides Clipboard.set_with_data: own the selection through the window
            self.connect("selection-get", self._clip_get_cb)
            self._clip_wired = True
        cbs = Gdk.SELECTION_CLIPBOARD
        Gtk.selection_clear_targets(self, cbs)
        for i, t in enumerate(TARGETS):
            Gtk.selection_add_target(self, cbs, Gdk.Atom.intern(t, False), i)
        Gtk.selection_owner_set(self, cbs, Gdk.CURRENT_TIME)
        self._say("%s %d item%s" % ("Cut" if op == "cut" else "Copied", len(files), "" if len(files) == 1 else "s"))

    def _clip_get_cb(self, w, sel, info, time_):
        op, uris, names = self._clip
        t = TARGETS[info]
        txt = (op + "\n" + "\n".join(uris)) if t == COPIED else ("\r\n".join(uris) + "\r\n") if t == "text/uri-list" else names
        sel.set(sel.get_target(), 8, txt.encode())

    def clip_get(self):
        """(op, [uris]) from the clipboard; op is 'copy' or 'cut'."""
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        sel = cb.wait_for_contents(Gdk.Atom.intern(COPIED, False))
        if sel is not None and sel.get_data():
            lines = sel.get_data().decode("utf-8", "replace").split("\n")
            if lines and lines[0].strip() in ("copy", "cut"):
                return lines[0].strip(), [l.strip() for l in lines[1:] if l.strip()]
        uris = cb.wait_for_uris() or []
        return "copy", list(uris)

    def clip_has_files(self):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        return cb.wait_is_target_available(Gdk.Atom.intern(COPIED, False)) or cb.wait_is_target_available(Gdk.Atom.intern("text/uri-list", False))

    def copy_sel(self, *_):
        self.clip_set("copy", self._sel_files())

    def cut_sel(self, *_):
        self.clip_set("cut", self._sel_files())

    def paste_into(self, dest=None):
        op, uris = self.clip_get()
        if not uris:
            self._say("Nothing to paste")
            return
        self.transfer(op, uris, dest or self.cwd)
        if op == "cut":
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).clear()

    def transfer(self, op, uris, dest):
        """Copy ('copy') or move ('cut') the files behind `uris` into the folder `dest`; used by paste and by drag and drop."""
        pairs = []
        for u in uris:
            src = Gio.File.new_for_uri(u)
            if inside(dest, src) and src.query_file_type(NOFOLLOW, None) == Gio.FileType.DIRECTORY:
                self._say("Cannot put a folder inside itself")
                return
            pairs.append(src)

        n = len(pairs)
        noun = "%d item%s" % (n, "" if n == 1 else "s") if n != 1 else "\u201c%s\u201d" % (pairs[0].get_basename() or "item")
        where = dest.get_basename() or "/"
        total = scan(pairs)

        def work(job):
            for src in pairs:
                job.check()
                same = src.get_parent() is not None and src.get_parent().equal(dest)
                if op == "cut" and same:
                    continue                                          # moving into the folder it is already in
                target = unique_child(dest, src.get_basename())
                if op == "cut":
                    job.partial = target
                    move_file(src, target, job)
                    job.partial = None
                else:
                    job.created.append(target)
                    copy_tree(src, target, job)
        self._run_job("%s %s to %s" % ("Moving" if op == "cut" else "Copying", noun, where), work,
                      "%s %d item%s" % ("Moved" if op == "cut" else "Copied", n, "" if n == 1 else "s"),
                      verb="Moving" if op == "cut" else "Copying", total=total, copy_cleanup=(op != "cut"))

    # ------------------------------------------------------------ drag and drop
    def setup_dnd(self):
        """Drag files out to any app (text/uri-list, plus plain paths for terminals); drop files onto folders, the open folder or the sidebar."""
        acts = Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK
        src = [Gtk.TargetEntry.new("text/uri-list", 0, 0), Gtk.TargetEntry.new("text/plain", 0, 1)]
        dst = [Gtk.TargetEntry.new("text/uri-list", 0, 0)]
        self.tree.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, src, acts)
        # Icon view: GtkFlowBox collapses the selection to the pressed icon on press, and the stock drag source then only ever saw one file (or
        # never started). So the drag is started here, by hand, after the pointer has moved past the drag threshold.
        self._dnd_targets, self._dnd_actions = Gtk.TargetList.new(src), acts
        self._drag_pending = None
        # (which widget owns the pointer grab after a press depends on GTK's event windows, so listen on every level the icons sit in)
        for wd in (self.flow, self._bg, self._sw_icons, self):
            wd.add_events(Gdk.EventMask.BUTTON1_MOTION_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
            wd.connect("motion-notify-event", self._flow_motion)
        for w in (self.tree, self.flow):
            w.connect("drag-begin", self._dnd_begin)
            w.connect("drag-data-get", self._dnd_get)
        for w, kind in ((self._sw_list, "list"), (self._sw_icons, "icons"), (self.places, "places")):
            w.drag_dest_set(Gtk.DestDefaults.ALL, dst, Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
            w.connect("drag-data-received", self._dnd_received, kind)

    def _flow_motion(self, w, ev):
        return False

    def _drag_poll(self):
        """After a press on an icon: watch the pointer (GTK stops delivering motion events to us once the press has been claimed) and start the
        drag as soon as it has moved past the drag threshold with the button still down."""
        pend = self._drag_pending
        if pend is None:
            return False
        dev = Gdk.Display.get_default().get_default_seat().get_pointer()
        _w, x, y, mask = Gdk.Screen.get_default().get_root_window().get_device_position(dev)
        if not mask & Gdk.ModifierType.BUTTON1_MASK:
            self._drag_pending = None
            return False
        if not self.flow.drag_check_threshold(0, 0, int(x - pend[0]), int(y - pend[1])):
            return True
        self._drag_pending = None
        self._keep_sel = None                           # a real drag: the selection stays exactly as it is
        ctx = self.flow.drag_begin_with_coordinates(self._dnd_targets, self._dnd_actions, 1, pend[2], -1, -1)     # the press event itself starts it, like GTK would
        if ctx is None:
            self._keep_sel = None
        return False

    def _dnd_files(self):
        sel = self.selected()
        p = getattr(self, "_press_item", None)
        if p is not None and self.view == "icons" and not any(f.equal(p[1]) for _i, f in sel):
            sel = [p]                                   # dragging an icon that is not selected drags just that icon
        return [f for _i, f in sel]

    def _dnd_begin(self, w, ctx):
        self._tkeep = None
        self._keep_sel = None                      # it is a real drag: the multiple selection stays as it is (see _flow_click)
        files = self._dnd_files()
        if files:
            try:
                info = files[0].query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
                names = info.get_icon().get_names() if info.get_icon() is not None and hasattr(info.get_icon(), "get_names") else []
                Gtk.drag_set_icon_name(ctx, names[0] if names else "text-x-generic", 0, 0)
            except GLib.Error:
                pass

    def _dnd_get(self, w, ctx, sel, info, time_):
        files = self._dnd_files()
        if not files:
            return
        if info == 0:
            sel.set_uris([f.get_uri() for f in files])
        else:
            sel.set_text("\n".join(f.get_path() or f.get_uri() for f in files), -1)

    def _dnd_target(self, kind, x, y):
        """The folder a drop at (x, y) lands in: the folder under the pointer, else the folder being viewed."""
        try:
            if kind == "list":
                tx, ty = self._sw_list.translate_coordinates(self.tree, int(x), int(y))
                bx, by = self.tree.convert_widget_to_bin_window_coords(tx, ty)
                hit = self.tree.get_path_at_pos(bx, by)
                if hit:
                    row = self.store[hit[0]]
                    if row[5].get_file_type() == Gio.FileType.DIRECTORY:
                        return row[6]
            elif kind == "icons":
                tx, ty = self._sw_icons.translate_coordinates(self.flow, int(x), int(y))
                ch = self.flow.get_child_at_pos(tx, ty)
                if ch is not None and ch.info.get_file_type() == Gio.FileType.DIRECTORY:
                    return ch.file
            else:
                row = self.places.get_row_at_y(int(y))
                if row is not None and getattr(row, "uri", None):
                    return Gio.File.new_for_uri(row.uri)
                return None
        except (TypeError, AttributeError):
            pass
        return self.cwd

    def _dnd_received(self, w, ctx, x, y, sel, info, time_, kind):
        uris = sel.get_uris() or []
        dest = self._dnd_target(kind, x, y)
        if dest is not None:                       # dropping files into the folder they already live in does nothing (no "name (copy)")
            uris = [u for u in uris if not (Gio.File.new_for_uri(u).get_parent() is not None and Gio.File.new_for_uri(u).get_parent().equal(dest))]
            if not uris:
                self._say("Already in this folder")
                Gtk.drag_finish(ctx, False, False, time_)
                return
        ok = bool(uris and dest is not None)
        if ok:
            op = "copy" if ctx.get_selected_action() == Gdk.DragAction.COPY else "cut"
            self.transfer(op, uris, dest)
        Gtk.drag_finish(ctx, ok, False, time_)                           # the move is done here, so the source must not delete anything

    # ------------------------------------------------------------ basic operations
    def duplicate(self, *_):
        files = self._sel_files()

        def work(job):
            for f in files:
                t = unique_child(f.get_parent(), f.get_basename())
                job.created.append(t)
                copy_tree(f, t, job)
        self._run_job("Duplicating %d item%s" % (len(files), "" if len(files) == 1 else "s"), work,
                      "Duplicated %d item%s" % (len(files), "" if len(files) == 1 else "s"), verb="Copying", total=scan(files), copy_cleanup=True)

    def _choose_folder(self, title, verb):
        d = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button(verb, Gtk.ResponseType.OK)
        appkit.style_stock_dialog(d)
        if self.cwd.get_path():
            d.set_current_folder(self.cwd.get_path())
        r = d.run(); path = d.get_filename(); d.destroy()
        return Gio.File.new_for_path(path) if r == Gtk.ResponseType.OK and path else None

    def move_to(self, move=True):
        dest = self._choose_folder("Move to" if move else "Copy to", "Move" if move else "Copy")
        files = self._sel_files()
        if dest is None or not files:
            return
        if any(inside(dest, f) and f.query_file_type(NOFOLLOW, None) == Gio.FileType.DIRECTORY for f in files):
            self._say("Cannot put a folder inside itself")
            return

        def work(job):
            for f in files:
                job.check()
                t = unique_child(dest, f.get_basename())
                if move:
                    job.partial = t
                    move_file(f, t, job)
                    job.partial = None
                else:
                    job.created.append(t)
                    copy_tree(f, t, job)
        self._run_job("%s %d item%s to %s" % ("Moving" if move else "Copying", len(files), "" if len(files) == 1 else "s", dest.get_basename() or "/"),
                      work, "%s %d item%s to %s" % ("Moved" if move else "Copied", len(files), "" if len(files) == 1 else "s", dest.get_basename() or "/"),
                      verb="Moving" if move else "Copying", total=scan(files), copy_cleanup=not move)

    def make_link(self, *_):
        files = self._sel_files()
        try:
            for f in files:
                if f.get_path():
                    unique_child(f.get_parent(), "Link to " + f.get_basename(), suffix=" 2").make_symbolic_link(f.get_path(), None)
            self.refresh()
        except GLib.Error as e:
            self._say("Could not create link: %s" % e.message)

    def new_document(self, template=None):
        if template is not None:                                       # a file from ~/Templates
            t = unique_child(self.cwd, template.get_basename())
            self._run_job("Creating %s" % t.get_basename(), lambda job: copy_tree(template, t, job), "Created %s" % t.get_basename(), verb="Copying")
            return
        name = self._ask("New document", "File name", "Untitled document.txt")
        if not name:
            return
        f = self.cwd.get_child(name)
        try:
            if f.query_exists(None):
                self._say("'%s' already exists" % name)
                return
            f.create(Gio.FileCreateFlags.NONE, None).close()
            self.refresh()
        except GLib.Error as e:
            self._say("Could not create file: %s" % e.message)

    def copy_path(self, files=None):
        files = files or self._sel_files() or [self.cwd]
        txt = "\n".join(f.get_path() or f.get_uri() for f in files)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(txt, -1)
        self._say("Copied the path" + ("s" if len(files) > 1 else ""))

    def open_terminal(self, folder=None):
        f = folder or self._folder_for_paths()
        services.fire(["sparkterm", f.get_path() or GLib.get_home_dir()])

    def open_new_window(self, f):
        services.fire(["sparkfiles", f.get_path() or f.get_uri()])

    def open_with(self, app, files):
        try:
            app.launch(files, self.get_display().get_app_launch_context())
        except GLib.Error as e:
            self._say("Could not open: %s" % e.message)

    def open_with_other(self, files):
        ct = (files[0].query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None).get_content_type()
              if files else "application/octet-stream")
        d = Gtk.AppChooserDialog(transient_for=self, modal=True, content_type=ct)
        d.get_widget().set_show_all(True)
        appkit.style_stock_dialog(d)
        if d.run() == Gtk.ResponseType.OK and d.get_app_info():
            self.open_with(d.get_app_info(), files)
        d.destroy()

    def set_wallpaper(self, f):
        if f.get_path():
            config.set("wallpaper", "path", f.get_path())
            self._say("Wallpaper set to %s" % f.get_basename())

    # ------------------------------------------------------------ archives
    def compress(self, kind):
        files = [f for f in self._sel_files() if f.get_path()]
        paths = [f.get_path() for f in files]
        if not paths:
            return
        base = os.path.basename(paths[0]) if len(paths) == 1 else "Archive"
        out = unique_child(self.cwd, "%s.%s" % (base, kind), suffix=" 2").get_path()

        def work(job):
            try:
                if kind == "zip":
                    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                        def put(full, arc):
                            job.check()
                            job.name = os.path.basename(full)
                            z.write(full, arc)
                            try:
                                job.file_done(os.lstat(full).st_size)
                            except OSError:
                                job.file_done(0)
                        for p in paths:
                            parent = os.path.dirname(p)
                            if os.path.isdir(p) and not os.path.islink(p):
                                for root, dirs, fl in os.walk(p):
                                    z.write(root, os.path.relpath(root, parent))
                                    for fn in fl:
                                        put(os.path.join(root, fn), os.path.relpath(os.path.join(root, fn), parent))
                            else:
                                put(p, os.path.basename(p))
                else:
                    with tarfile.open(out, "w:gz") as t:
                        def flt(ti):
                            job.check()
                            job.name = os.path.basename(ti.name)
                            job.file_done(ti.size if ti.isfile() else 0)
                            return ti
                        for p in paths:
                            t.add(p, arcname=os.path.basename(p), filter=flt)
            except BaseException:
                if os.path.exists(out):
                    os.remove(out)
                raise
        self._run_job("Compressing to %s" % os.path.basename(out), work, "Created %s" % os.path.basename(out), verb="Compressing", total=scan(files))

    def extract(self, f):
        path = f.get_path()
        if not path:
            return
        dest = unique_child(self.cwd, split_name(f.get_basename())[0], suffix=" 2").get_path()

        def safe(name):
            full = os.path.realpath(os.path.join(dest, name))
            if not (full == os.path.realpath(dest) or full.startswith(os.path.realpath(dest) + os.sep)):
                raise ValueError("the archive wants to write outside the target folder (%s)" % name)

        def work(job):
            os.makedirs(dest)
            try:
                low = path.lower()
                if zipfile.is_zipfile(path) and low.endswith(".zip"):
                    with zipfile.ZipFile(path) as z:
                        infos = z.infolist()
                        job.total = sum(i.file_size for i in infos)
                        for i in infos:
                            job.check(); safe(i.filename)
                            job.name = os.path.basename(i.filename.rstrip("/")) or i.filename
                            z.extract(i, dest)
                            job.file_done(i.file_size)
                elif tarfile.is_tarfile(path):
                    with tarfile.open(path) as t:
                        members = t.getmembers()
                        job.total = sum(m.size for m in members if m.isfile())
                        for m in members:
                            job.check(); safe(m.name)
                            job.name = os.path.basename(m.name.rstrip("/")) or m.name
                            try:
                                t.extract(m, dest, filter="data")
                            except TypeError:                         # Python without extraction filters: the path check above is what we have
                                t.extract(m, dest)
                            job.file_done(m.size if m.isfile() else 0)
                else:
                    shutil.unpack_archive(path, dest)
            except BaseException:
                shutil.rmtree(dest, ignore_errors=True)
                raise
        self._run_job("Extracting %s" % f.get_basename(), work, "Extracted to %s" % os.path.basename(dest), verb="Extracting")

    # ------------------------------------------------------------ trash
    def in_trash(self):
        return self.cwd.get_uri().startswith("trash:")

    def restore_sel(self, *_):
        files = self._sel_files()

        def work(job):
            for f in files:
                job.check()
                info = f.query_info("trash::orig-path", Gio.FileQueryInfoFlags.NONE, None)
                orig = info.get_attribute_byte_string("trash::orig-path")
                if not orig:
                    raise ValueError("no original location is recorded for %s" % f.get_basename())
                dest = Gio.File.new_for_path(orig)
                dest = unique_child(dest.get_parent(), dest.get_basename(), suffix=" (restored)")
                job.name = f.get_basename() or ""
                f.move(dest, Gio.FileCopyFlags.NONE, None, None, None)
                job.file_done(0)
        self._run_job("Restoring %d item%s" % (len(files), "" if len(files) == 1 else "s"), work,
                      "Restored %d item%s" % (len(files), "" if len(files) == 1 else "s"), verb="Restoring", total=(0, len(files)))

    def delete_sel(self, *_):
        files = self._sel_files()
        n = len(files)
        from .menus import GlassConfirm

        def go():
            self._run_job("Deleting %d item%s" % (n, "" if n == 1 else "s"), lambda job: [delete_tree(f, job) for f in files],
                          "Deleted %d item%s" % (n, "" if n == 1 else "s"), verb="Deleting", total=(0, scan(files)[1]))
        GlassConfirm("Delete %s permanently?" % ("this item" if n == 1 else "%d items" % n), "This cannot be undone.", "Delete", go,
                     theme=self.th).show_centered()

    def empty_trash(self, *_):
        from .menus import GlassConfirm
        t = Gio.File.new_for_uri("trash:///")

        def work(job):
            for i in t.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NONE, None):
                delete_tree(t.get_child(i.get_name()), job)
        GlassConfirm("Empty the Trash?", "Everything in it will be deleted for good.", "Empty Trash",
                     lambda: self._run_job("Emptying the Trash", work, "Trash emptied", verb="Deleting"), theme=self.th).show_centered()

    # ------------------------------------------------------------ properties
    def properties(self, files=None):
        files = files or self._sel_files() or [self.cwd]
        d = appkit.GlassDialog("Properties", "sparkfiles-properties", parent=self)
        grid = Gtk.Grid(column_spacing=18, row_spacing=7); grid.set_margin_start(20); grid.set_margin_end(20); grid.set_margin_top(14); grid.set_margin_bottom(8)
        rows = {}

        def add(key, text):
            r = len(rows)
            k = label(key, "muted"); k.set_xalign(1.0); k.set_valign(Gtk.Align.START)
            v = label(text, ellipsize=False); v.set_selectable(True); v.set_line_wrap(True); v.set_max_width_chars(44); v.set_xalign(0)
            grid.attach(k, 0, r, 1, 1); grid.attach(v, 1, r, 1, 1)
            rows[key] = v

        def when(info, attr):
            ts = info.get_attribute_uint64(attr)
            return time.strftime("%A %d %B %Y, %H:%M", time.localtime(ts)) if ts else "Unknown"
        A = "standard::*,time::*,owner::*,access::*,unix::mode,trash::orig-path"
        infos = []
        for f in files:
            try:
                infos.append((f, f.query_info(A, NOFOLLOW, None)))
            except GLib.Error:
                pass
        if not infos:
            d.destroy()
            return
        if len(infos) == 1:
            f, i = infos[0]
            is_dir = i.get_file_type() == Gio.FileType.DIRECTORY
            title = i.get_display_name() or f.get_basename() or "/"
            add("Name", title)
            ct = i.get_content_type() or ""
            add("Type", "Folder" if is_dir else ((Gio.content_type_get_description(ct) or "File").capitalize() + ("  (%s)" % ct if ct else "")))
            add("Location", (f.get_parent().get_path() or f.get_parent().get_uri()) if f.get_parent() else "/")
            if i.get_is_symlink():
                add("Links to", i.get_symlink_target() or "?")
            add("Size", "Calculating..." if is_dir else "%s  (%s bytes)" % (GLib.format_size(i.get_size()), "{:,}".format(i.get_size())))
            if is_dir:
                add("Contains", "Calculating...")
            add("Modified", when(i, "time::modified")); add("Accessed", when(i, "time::access"))
            if i.has_attribute("owner::user"):
                add("Owner", "%s  (%s)" % (i.get_attribute_string("owner::user"), i.get_attribute_string("owner::group") or "-"))
            mode = i.get_attribute_uint32("unix::mode") if i.has_attribute("unix::mode") else None
            if mode is not None:
                perm = "".join(("r" if mode & b else "-") + ("w" if mode & (b >> 1) else "-") + ("x" if mode & (b >> 2) else "-") for b in (0o400, 0o040, 0o004))
                add("Permissions", "%s  (%o)" % (perm, mode & 0o777))
            if i.has_attribute("trash::orig-path"):
                add("Originally in", os.path.dirname(i.get_attribute_byte_string("trash::orig-path") or ""))
        else:
            add("Selection", "%d items" % len(infos)); add("Size", "Calculating..."); add("Contains", "Calculating...")
        head = Gtk.Box(spacing=12); head.set_margin_start(20); head.set_margin_end(20); head.set_margin_top(16)
        try:
            gi_ = infos[0][1].get_icon() if len(infos) == 1 else Gio.ThemedIcon.new("edit-copy")
            img = Gtk.Image.new_from_gicon(gi_, Gtk.IconSize.DIALOG); img.set_pixel_size(48)
            head.pack_start(img, False, False, 0)
        except Exception:
            pass
        hl = label(infos[0][1].get_display_name() if len(infos) == 1 else "%d items" % len(infos), ellipsize=False)
        hl.get_style_context().add_class("proptitle"); hl.set_line_wrap(True); hl.set_max_width_chars(34)
        head.pack_start(hl, True, True, 0)
        d.get_content_area().pack_start(head, False, False, 0)
        d.get_content_area().pack_start(grid, True, True, 0)
        if len(infos) == 1 and f.get_path() and not is_dir and mode is not None:      # "run as a program" switch
            sw = Gtk.Switch(); sw.set_active(bool(mode & 0o111)); sw.set_halign(Gtk.Align.START)

            def exec_toggled(s, _p, path=f.get_path(), m=mode):
                try:
                    os.chmod(path, (m | 0o111) if s.get_active() else (m & ~0o111))
                except OSError as e:
                    self._say("Could not change permissions: %s" % e)
            sw.connect("notify::active", exec_toggled)
            r = len(rows)
            k = label("Run as program", "muted"); k.set_xalign(1.0)
            grid.attach(k, 0, r, 1, 1); grid.attach(sw, 1, r, 1, 1)
        d.show_all()

        def count():                                                   # size + contents, off the UI thread
            size = nfiles = ndirs = 0
            for f_, i_ in infos:
                if i_.get_file_type() == Gio.FileType.DIRECTORY and f_.get_path():
                    ndirs += 0 if len(infos) == 1 else 1
                    for root, dirs, fl in os.walk(f_.get_path()):
                        ndirs += len(dirs); nfiles += len(fl)
                        for fn in fl:
                            try:
                                size += os.lstat(os.path.join(root, fn)).st_size
                            except OSError:
                                pass
                else:
                    size += i_.get_size(); nfiles += 1
            GLib.idle_add(lambda: (rows["Size"].set_text("%s  (%s bytes)" % (GLib.format_size(size), "{:,}".format(size))) if "Size" in rows else None,
                                   rows["Contains"].set_text("%d file%s, %d folder%s" % (nfiles, "" if nfiles == 1 else "s", ndirs, "" if ndirs == 1 else "s"))
                                   if "Contains" in rows else None, False)[-1])
        if any(i_.get_file_type() == Gio.FileType.DIRECTORY for _f, i_ in infos):
            threading.Thread(target=count, daemon=True).start()

    # ------------------------------------------------------------ menus
    def _show_menu(self, ev, items):
        GlassMenu(items, light=True, theme=self.th, min_width=244).popup_at(int(ev.x_root), int(ev.y_root))
        return True

    def _item_menu(self, ev, info, f):
        sel = self.selected() or [(info, f)]
        files = [x for _i, x in sel]
        one = len(sel) == 1
        is_dir = one and sel[0][0].get_file_type() == Gio.FileType.DIRECTORY
        n = len(sel)
        if self.in_trash():
            items = [("itemi", None, "Restore From Trash", self.restore_sel),
                     ("itemi", None, "Delete Permanently", self.delete_sel, True, "Shift+Del"), ("sep",),
                     ("itemi", None, "Properties", lambda: self.properties(files), True, "Alt+Enter")]
            return self._show_menu(ev, items)
        items = [("itemi", "arrow_right", "Open" if n == 1 else "Open %d Items" % n, lambda: [self.open_item(i, x) for i, x in sel], True, "Enter")]
        # Open With: apps that handle this content type (single selection, or several of the same type)
        cts = {(i.get_attribute_string("standard::fast-content-type") or "") for i, _x in sel}
        if len(cts) == 1 and not is_dir:
            apps = [a for a in Gio.AppInfo.get_all_for_type(next(iter(cts))) if a.should_show()] if next(iter(cts)) else []
            kids = [("item", a.get_display_name(), lambda a=a: self.open_with(a, files)) for a in apps[:10]]
            kids.append(("item", "Other application…", lambda: self.open_with_other(files)))
            items.append(("sub", "grid", "Open With", kids))
        if is_dir:
            pinned = self.is_pinned(files[0])
            items += [("itemi", "pin", "Unpin from Sidebar" if pinned else "Pin to Sidebar", lambda: self.toggle_pin(files[0])),
                      ("itemi", "plus", "Open in New Tab", lambda: self.new_tab(files[0])),
                      ("itemi", "windows", "Open in New Window", lambda: self.open_new_window(files[0])),
                      ("itemi", "terminal", "Open Terminal Here", lambda: self.open_terminal(files[0]))]
        items.append(("sep",))
        items += [("itemi", None, "Cut", self.cut_sel, True, "Ctrl+X"), ("itemi", "clipboard", "Copy", self.copy_sel, True, "Ctrl+C")]
        if is_dir:
            items.append(("itemi", "download", "Paste Into Folder", lambda: self.paste_into(files[0]), self.clip_has_files(), "Ctrl+V"))
        items.append(("sep",))
        if one:
            items.append(("itemi", None, "Rename…", lambda: self.rename(*sel[0]), True, "F2"))
        items.append(("itemi", None, "Duplicate", self.duplicate))
        items.append(("sub", None, "Organise", [("item", "Move to…", lambda: self.move_to(True)), ("item", "Copy to…", lambda: self.move_to(False)),
                                                 ("item", "Create link", self.make_link)]))
        if one and is_archive(files[0].get_basename() or ""):
            items.append(("itemi", None, "Extract Here", lambda: self.extract(files[0])))
        items.append(("sub", None, "Compress", [("item", "As .zip", lambda: self.compress("zip")), ("item", "As .tar.gz", lambda: self.compress("tar.gz"))]))
        if one and (cts & {"image/png", "image/jpeg", "image/webp"}):
            items.append(("itemi", "image", "Set as Wallpaper", lambda: self.set_wallpaper(files[0])))
        items.append(("itemi", None, "Copy Path", lambda: self.copy_path(files)))
        items += [("sep",), ("itemi", "trash", "Move to Trash", self.trash, True, "Del"),
                  ("itemi", "gear", "Properties", lambda: self.properties(files), True, "Alt+Enter")]
        return self._show_menu(ev, items)

    def _background_menu(self, ev):
        if self.in_trash():
            return self._show_menu(ev, [("itemi", "trash", "Empty Trash", self.empty_trash), ("sep",),
                                        ("itemi", None, "Select All", self.select_all, True, "Ctrl+A"), ("itemi", None, "Refresh", self.refresh, True, "F5")])
        tdir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
        tpl = []
        if tdir and os.path.isdir(tdir) and tdir != GLib.get_home_dir():
            tpl = [Gio.File.new_for_path(os.path.join(tdir, n)) for n in sorted(os.listdir(tdir))[:12] if os.path.isfile(os.path.join(tdir, n))]
        newkids = [("item", "Empty document…", self.new_document)] + [("item", t.get_basename(), lambda t=t: self.new_document(t)) for t in tpl]
        items = [("itemi", "plus", "New Folder", self.new_folder, True, "Ctrl+Shift+N"), ("sub", None, "New Document", newkids), ("sep",),
                 ("itemi", "download", "Paste", self.paste_into, self.clip_has_files(), "Ctrl+V"),
                 ("itemi", None, "Select All", self.select_all, True, "Ctrl+A"), ("sep",),
                 ("sub", None, "Sort by", [("check", "Name", self.sort == "name", lambda: self._set_sort("name")),
                                          ("check", "Size", self.sort == "size", lambda: self._set_sort("size")),
                                          ("check", "Type", self.sort == "type", lambda: self._set_sort("type")),
                                          ("check", "Last modified", self.sort == "modified", lambda: self._set_sort("modified")),
                                          ("check", "Reverse order", self.sort_rev, lambda: self._set_sort(self.sort, not self.sort_rev))]),
                 ("sub", None, "View as", [("check", "Icons", self.view == "icons", lambda: self.view != "icons" and self.toggle_view()),
                                           ("check", "List", self.view == "list", lambda: self.view != "list" and self.toggle_view())]),
                 ("check", "Show hidden files", self.hidden, self.toggle_hidden), ("sep",),
                 ("itemi", "terminal", "Open Terminal Here", lambda: self.open_terminal(self.cwd)),
                 ("itemi", "pin", "Unpin from Sidebar" if self.is_pinned(self.cwd) else "Pin Folder to Sidebar", lambda: self.toggle_pin(self.cwd)),
                 ("itemi", None, "Copy Folder Path", lambda: self.copy_path([self.cwd])),
                 ("itemi", "gear", "Properties", lambda: self.properties([self.cwd]), True, "Alt+Enter"),
                 ("itemi", None, "Refresh", self.refresh, True, "F5")]
        return self._show_menu(ev, items)

    def _place_click(self, lb, ev):
        """Right-click in the sidebar: open / new window / terminal / copy path, and Empty Trash."""
        if ev.button != 3:
            return False
        row = lb.get_row_at_y(int(ev.y))
        uri = getattr(row, "uri", None)
        if not uri:
            return False
        f = Gio.File.new_for_uri(uri)
        items = [("itemi", "arrow_right", "Open", lambda: self.go(f)), ("itemi", "windows", "Open in New Window", lambda: self.open_new_window(f))]
        if f.get_path():
            items += [("itemi", "terminal", "Open Terminal Here", lambda: self.open_terminal(f)),
                      ("itemi", None, "Copy Path", lambda: self.copy_path([f]))]
        if getattr(row, "pin", False):
            items += [("sep",), ("itemi", "pin", "Unpin from Sidebar", lambda: self.toggle_pin(f))]
        if uri.startswith("trash:"):
            items += [("sep",), ("itemi", "trash", "Empty Trash", self.empty_trash)]
        return self._show_menu(ev, items)
