"""Glass progress window that shows file-operation jobs"""
import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import appkit
from .scheme import ink

NOFOLLOW = Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
SHOW_AFTER = 0.45          # seconds: quicker operations never open a window at all


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, title, verb="Working"):
        self.title, self.verb = title, verb
        self.cancellable = Gio.Cancellable()
        self.total = 0               # bytes to process (0 = unknown)
        self.done = 0                # bytes of finished files
        self.cur = 0                 # bytes of the file in flight
        self.n_total = 0             # items to process (used when bytes are unknown, e.g. deleting)
        self.n_done = 0
        self.name = ""
        self.started = time.monotonic()
        self.finished = False
        self.cancelled = False
        self.error = None
        self.created = []            # targets a cancelled COPY made: removed again
        self.partial = None          # the file being written right now: removed on cancel

    # -- worker side
    def check(self):
        if self.cancellable.is_cancelled():
            raise Cancelled()

    def progress(self, cur, _tot, _data=None):           # Gio.FileProgressCallback
        self.cur = cur

    def file_done(self, size=0):
        self.done += size
        self.cur = 0
        self.n_done += 1

    def cancel(self):
        self.cancelled = True
        self.cancellable.cancel()

    # -- UI side
    def bytes_done(self):
        return self.done + self.cur

    def fraction(self):
        if self.total > 0:
            return max(0.0, min(1.0, self.bytes_done() / float(self.total)))
        if self.n_total > 0:
            return max(0.0, min(1.0, self.n_done / float(self.n_total)))
        return None

    def detail(self):
        el = max(0.001, time.monotonic() - self.started)
        if self.total > 0:
            b = self.bytes_done()
            txt = "%s of %s" % (GLib.format_size(b), GLib.format_size(self.total))
            if el > 1.5 and b > 0:
                rate = b / el
                left = max(0, self.total - b) / rate
                txt += "  \u2022  %s/s" % GLib.format_size(int(rate))
                if left >= 1:
                    txt += "  \u2022  %s left" % ("%d s" % round(left) if left < 90 else "%d min" % round(left / 60.0))
            return txt
        if self.n_total > 0:
            return "%d of %d items" % (min(self.n_done, self.n_total), self.n_total)
        return "%d item%s so far" % (self.n_done, "" if self.n_done == 1 else "s") if self.n_done else ""


# ---------------------------------------------------------------- scanning
def scan(files):
    """(bytes, items) the files add up to, for local files; (0, 0) bytes/items when a path is not local (then the bar just pulses)."""
    size = items = 0
    for f in files:
        p = f.get_path()
        if not p:
            return 0, 0
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                items += 1
                for root, dirs, fl in os.walk(p):
                    items += len(dirs) + len(fl)
                    for fn in fl:
                        try:
                            size += os.lstat(os.path.join(root, fn)).st_size
                        except OSError:
                            pass
            else:
                items += 1
                size += os.lstat(p).st_size
        except OSError:
            pass
    return size, items


# ---------------------------------------------------------------- tree operations that report to a job
def copy_tree(src, dst, job=None):
    if job:
        job.check()
    if src.query_file_type(NOFOLLOW, None) == Gio.FileType.DIRECTORY:
        dst.make_directory_with_parents(None)
        for i in src.enumerate_children("standard::name", NOFOLLOW, None):
            copy_tree(src.get_child(i.get_name()), dst.get_child(i.get_name()), job)
        if job:
            job.n_done += 1
        return
    size = 0
    if job:
        job.name, job.cur, job.partial = src.get_basename() or "", 0, dst
        try:
            size = src.query_info("standard::size", NOFOLLOW, None).get_size()
        except GLib.Error:
            pass
    try:
        src.copy(dst, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, job.cancellable if job else None, job.progress if job else None, None)
    except GLib.Error as e:
        if job and e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
            raise Cancelled()
        raise
    if job:
        job.partial = None
        job.file_done(size)


def delete_tree(f, job=None):
    if job:
        job.check()
    if f.query_file_type(NOFOLLOW, None) == Gio.FileType.DIRECTORY:
        for i in f.enumerate_children("standard::name", NOFOLLOW, None):
            delete_tree(f.get_child(i.get_name()), job)
    if job:
        job.name = f.get_basename() or ""
    f.delete(None)
    if job:
        job.n_done += 1


def move_file(src, target, job=None):
    """Rename when the target is on the same filesystem (instant); otherwise copy with progress, then remove the original."""
    if job:
        job.check()
    size = 0
    if job:
        job.name, job.cur = src.get_basename() or "", 0
        try:
            size = src.query_info("standard::size", NOFOLLOW, None).get_size()
        except GLib.Error:
            pass
    try:
        src.move(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, job.cancellable if job else None, job.progress if job else None, None)
        if job:
            job.file_done(size)
        return
    except GLib.Error as e:
        if job and e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
            raise Cancelled()
    if job:
        job.cur = 0
    copy_tree(src, target, job)                          # a folder across filesystems, which Gio will not move by itself
    delete_tree(src, job)


def remove_quietly(f):
    try:
        if f.query_exists(None):
            delete_tree(f)
    except GLib.Error:
        pass


# ---------------------------------------------------------------- the window
class ProgressWindow(appkit.GlassWindow):
    """One small glass window per file manager: a row per running operation. Closing it only hides it - the work goes on."""

    def __init__(self, parent):
        super().__init__("File operations", "sparkfiles-progress", "window_light", (440, 10))
        self.disconnect(self._quit_id)                    # a secondary window: destroying it must not end the application
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.rows = {}
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, "set_margin_" + m)(14)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner = Gtk.Box(); inner.get_style_context().add_class("inner"); inner.pack_start(self.list, True, True, 0)
        self.list.set_margin_start(14); self.list.set_margin_end(14); self.list.set_margin_top(12); self.list.set_margin_bottom(12)
        outer.pack_start(inner, True, True, 0)
        hide = Gtk.Button(label="Hide"); hide.get_style_context().add_class("pill")
        hide.connect("clicked", lambda *_: self.hide())
        row = Gtk.Box(); row.pack_end(hide, False, False, 0)
        outer.pack_start(row, False, False, 0)
        self.add(outer)
        self.connect("delete-event", lambda *_: (self.hide(), True)[1])
        self._timer = None

    # -- jobs
    def add_job(self, job):
        r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label=job.title, xalign=0); title.set_ellipsize(Pango.EllipsizeMode.END); title.get_style_context().add_class("opname")
        title.set_max_width_chars(46)
        cancel = Gtk.Button(); cancel.set_relief(Gtk.ReliefStyle.NONE); cancel.set_tooltip_text("Cancel")
        from .widgets import Ico
        cancel.add(Ico("close", 10, ink(), 1.8))
        cancel.connect("clicked", lambda *_: self._cancel(job))
        head.pack_start(title, True, True, 0); head.pack_end(cancel, False, False, 0)
        bar = Gtk.ProgressBar(); bar.set_hexpand(True)
        what = Gtk.Label(label="", xalign=0); what.set_ellipsize(Pango.EllipsizeMode.MIDDLE); what.get_style_context().add_class("muted")
        what.set_max_width_chars(60)
        more = Gtk.Label(label="", xalign=0); more.get_style_context().add_class("muted")
        for w in (head, bar, what, more):
            r.pack_start(w, False, False, 0)
        self.list.pack_start(r, False, False, 0)
        r.show_all()
        self.rows[job] = dict(box=r, title=title, bar=bar, what=what, more=more, cancel=cancel, shown_error=False)
        if self._timer is None:
            self._timer = GLib.timeout_add(100, self._tick)

    def _cancel(self, job):
        row = self.rows.get(job)
        if row is None:
            return
        if job.finished:                                         # an error row: "Dismiss"
            self._drop(job)
            return
        job.cancel()
        row["what"].set_text("Cancelling...")
        row["cancel"].set_sensitive(False)

    def finish(self, job):
        """The worker is done (job.error / job.cancelled say how). Successful and cancelled jobs disappear; a failure stays, with the reason."""
        row = self.rows.get(job)
        if row is None:
            return
        if job.error:
            row["bar"].set_fraction(0.0)
            row["what"].set_text("Failed: %s" % job.error)
            row["what"].set_line_wrap(True); row["what"].set_max_width_chars(46); row["what"].set_ellipsize(Pango.EllipsizeMode.NONE)
            row["more"].set_text("")
            row["cancel"].set_sensitive(True); row["cancel"].set_tooltip_text("Dismiss")
            row["shown_error"] = True
            if not self.get_visible():
                self.show_all(); self.present()
        else:
            self._drop(job)

    def _drop(self, job):
        row = self.rows.pop(job, None)
        if row is not None:
            self.list.remove(row["box"]); row["box"].destroy()
        if not self.rows:
            self.hide()
            self.resize(440, 10)

    def _tick(self):
        now = time.monotonic()
        busy = False
        for job, row in list(self.rows.items()):
            if job.finished:
                continue
            busy = True
            if not self.get_visible() and now - job.started > SHOW_AFTER:
                self.show_all(); self.present()
            frac = job.fraction()
            if frac is None:
                row["bar"].pulse()
            else:
                row["bar"].set_fraction(frac)
            if not job.cancelled:
                row["what"].set_text("%s %s" % (job.verb, job.name) if job.name else job.verb + "...")
            row["more"].set_text(job.detail())
        if not busy:
            self._timer = None
            return False
        return True
