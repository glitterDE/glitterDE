"""SparkCode: the glitterDE code editor.

Tabs, a folder sidebar (lazy tree), syntax highlighting (glitterde.synhl, no extra libraries), line numbers, find / replace, quick open,
auto-indent, bracket pairing + matching, comment toggling and line editing. Colours come from the active theme's semantic roles, so the
editor follows the theme, the accent colour and the light / dark scheme like every other glitterDE app.

    sparkcode                      restore the last session (folder + open files)
    sparkcode FOLDER               open a folder in the sidebar
    sparkcode FILE[:LINE[:COL]]    open files (also +LINE before a file)
"""
import bisect
import os
import re
import sys
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import appkit, codeutil as cu, config, scheme, synhl
from . import icons as ic
from .menus import GlassConfirm, GlassMenu
from .widgets import Ico, icon_button, label

CFG = "code.toml"
MAX_OPEN = 20 * 1024 * 1024            # larger files are refused
MAX_HL = 1500000                       # above this many characters syntax highlighting is switched off
MAX_BRACKET = 400000                   # bracket matching is skipped for documents larger than this
OPEN_CLOSE = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}
CLOSERS = set(")]}\"'`")
QUOTES = set("\"'`")
HIDDEN_ALWAYS = {".git", "__pycache__", ".DS_Store"}

DEFAULTS = {"sidebar": True, "numbers": True, "wrap": False, "hl_line": True, "hidden": True, "pairs": True, "trim": False,
            "final_nl": False, "zoom": 1.0, "sidebar_w": 240}


# ------------------------------------------------------------------------------------------------------------------------ colours
def _mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def _lum(c):
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable(c, bg, toward, need=4.5):
    """Nudge colour c towards `toward` until it has at least `need`:1 contrast against bg (themes may bring any palette)."""
    for _ in range(14):
        if contrast(c, bg) >= need:
            break
        c = _mix(c, toward, 0.12)
    return c


ROLES = {"keyword": "accent.pink", "builtin": "accent.blue", "type": "status.info", "function": "accent.hover", "string": "status.success",
         "number": "status.warning", "decorator": "pride.pink", "tag": "accent.pink", "attr": "status.info", "heading": "accent.hover",
         "link": "accent.blue", "added": "status.success", "removed": "status.error", "meta": "accent.primary", "variable": "pride.blue",
         "escape": "status.info"}
TAG_STYLE = {"comment": {"style": Pango.Style.ITALIC}, "heading": {"weight": Pango.Weight.BOLD}, "link": {"underline": Pango.Underline.SINGLE}}


def syntax_palette(th, dark):
    """{kind: (r, g, b)} for every highlight kind, from the theme's semantic colour roles, kept readable on the window material."""
    col = lambda role: tuple(th.color(role)[:3])
    surface = th.material("window_dark" if dark else "window_light")["tint"]
    navy, white = tuple(scheme.NAVY[:3]), (1.0, 1.0, 1.0)
    pal = {k: col(r) for k, r in ROLES.items()}
    pal["constant"] = _mix(col("accent.pink"), col("status.warning"), 0.5)
    if dark:
        pal["operator"], pal["comment"] = col("text.secondary"), col("text.disabled")
    else:
        pal = {k: _mix(v, navy, 0.42) for k, v in pal.items()}
        pal["operator"], pal["comment"] = col("text.on_light"), col("text.on_light_muted")
    toward = white if dark else navy
    return {k: readable(v, surface, toward, 3.6 if k == "comment" else 4.5) for k, v in pal.items()}


class Style:
    """Everything colour-related, derived once from the active theme."""

    def __init__(self, th):
        self.dark = scheme.is_dark()
        self.pal = syntax_palette(th, self.dark)
        self.ink = tuple(scheme.ink()[:3])
        acc, pink, warn = (tuple(th.color(r)[:3]) for r in ("accent.primary", "accent.pink", "status.warning"))
        self.acc = acc
        self.line_rgba = self.ink + (0.075,)
        self.sel_rgba = acc + (0.45,)
        self.find_rgba = warn + (0.38,)
        self.cur_rgba = pink + (0.62,)
        self.br_rgba = acc + (0.55,)
        self.gutter = self.ink + (0.45,)
        self.gutter_cur = self.ink + (0.95,)

    def apply_tags(self, doc):
        for kind, tag in doc.tags.items():
            tag.set_property("foreground-rgba", Gdk.RGBA(*(self.pal.get(kind, self.ink) + (1.0,))))
            for k, v in TAG_STYLE.get(kind, {}).items():
                tag.set_property(k, v)
        doc.t_find.set_property("background-rgba", Gdk.RGBA(*self.find_rgba))
        doc.t_cur.set_property("background-rgba", Gdk.RGBA(*self.cur_rgba))
        doc.t_br.set_property("background-rgba", Gdk.RGBA(*self.br_rgba))

    def css(self, family, pt):
        rgba = lambda c, a=None: "rgba(%d,%d,%d,%.3f)" % (c[0] * 255, c[1] * 255, c[2] * 255, c[3] if a is None and len(c) > 3 else (a if a is not None else 1))
        return ("""
        textview { font-family: "%s", "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: %.1fpt; }
        textview text { background-color: transparent; color: %s; caret-color: %s; }
        textview text selection, textview text selection:focus { background-color: %s; color: %s; }
        textview border { background-color: transparent; }
        treeview.codetree, treeview.codetree.view { background-color: transparent; background-image: none; }
        treeview.codetree:selected, treeview.codetree:selected:focus { background-color: %s; border-radius: 8px; }
        treeview.codetree:hover { background-color: %s; border-radius: 8px; }
        label.dirtydot { color: %s; font-size: 9px; }
        button.findtoggle { border: 1px solid %s; border-radius: 9px; padding: 2px 7px; min-height: 0; background-color: transparent; }
        button.findtoggle:checked { background-color: %s; }
        label.langbtn, button.statusbtn { font-size: 11px; }
        button.statusbtn { padding: 1px 8px; border-radius: 9px; }
        list.quick row { padding: 4px 8px; }
        """ % (family, pt, rgba(self.ink, 1.0), rgba(self.ink, 1.0), rgba(self.acc, 0.5), rgba(self.ink, 1.0), rgba(self.acc, 0.30),
               rgba(self.ink, 0.08), rgba(tuple(self.pal["keyword"]), 1.0), rgba(self.ink, 0.25), rgba(self.acc, 0.45))).encode()


# ------------------------------------------------------------------------------------------------------------------------ icons
FILE_COLORS = {"Python": ((.55, .78, 1), (.38, .58, .98)), "JavaScript": ((1, .88, .45), (.95, .70, .25)),
               "TypeScript": ((.55, .75, 1), (.35, .55, .95)), "C": ((.72, .72, 1), (.52, .52, .95)), "C++": ((.72, .66, 1), (.52, .46, .95)),
               "Rust": ((1, .72, .52), (.95, .52, .36)), "Go": ((.52, .90, .95), (.30, .75, .90)), "Java": ((1, .74, .55), (.95, .55, .35)),
               "HTML": ((1, .68, .58), (.95, .46, .42)), "CSS": ((.62, .72, 1), (.46, .52, .96)), "JSON": ((1, .90, .55), (.95, .75, .35)),
               "Markdown": ((.80, .82, .97), (.62, .66, .90)), "Shell": ((.62, .95, .72), (.36, .80, .56)),
               "TOML / INI": ((.90, .76, 1), (.70, .56, .95)), "YAML": ((.90, .76, 1), (.70, .56, .95)), "XML": ((1, .78, .6), (.95, .6, .4))}
DEFAULT_FILE = ((.72, .76, 1), (.55, .60, .95))
DIR_COLORS = ((.62, .74, 1, 1), (.40, .55, 1, 1))
_PIX = {}


def tree_icon(is_dir, lang=None):
    """Small pixbuf for the sidebar, drawn with the DE's own folder / file artwork."""
    key = ("dir",) if is_dir else ("file", lang)
    pb = _PIX.get(key)
    if pb is None:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 20, 20)
        cr = cairo.Context(surf)
        if is_dir:
            ic.folder(cr, 1, 3, 18, 15, DIR_COLORS[0], DIR_COLORS[1])
        else:
            c1, c2 = FILE_COLORS.get(lang, DEFAULT_FILE)
            ic.file_icon(cr, 3.5, 1, 13, 18, c1 + (1,), c2 + (1,))
        pb = _PIX[key] = Gdk.pixbuf_get_from_surface(surf, 0, 0, 20, 20)
    return pb


# ------------------------------------------------------------------------------------------------------------------------ the editor view
class CodeView(Gtk.TextView):
    """TextView with a line-number gutter (left border window) and a current-line highlight painted under the text."""

    def __init__(self, doc):
        super().__init__(buffer=doc.buf)
        self.doc = doc
        self._gw = 0
        self.set_monospace(True)
        self.set_left_margin(8); self.set_right_margin(8); self.set_top_margin(6); self.set_bottom_margin(60)
        self.set_pixels_above_lines(1); self.set_pixels_below_lines(1)
        self.set_accepts_tab(True)
        self.set_wrap_mode(Gtk.WrapMode.NONE)
        self.set_border_window_size(Gtk.TextWindowType.LEFT, 52)
        self.connect("draw", self._draw_below)                 # RUN_LAST: our handler runs before the text is drawn, so this lands under it
        self.connect_after("draw", self._draw_gutter)

    def update_gutter(self):
        n = self.get_buffer().get_line_count()
        if not self.doc.app.opt["numbers"]:
            w = 0
        else:
            cw = self.create_pango_layout("0").get_pixel_size()[0]
            w = max(3, len(str(n))) * cw + 22
        if w != self._gw:
            self._gw = w
            self.set_border_window_size(Gtk.TextWindowType.LEFT, w)

    def _draw_below(self, view, cr):
        if not self.doc.app.opt["hl_line"]:
            return False
        win = self.get_window(Gtk.TextWindowType.TEXT)
        buf = self.get_buffer()
        if win is None or buf.get_has_selection() or not Gtk.cairo_should_draw_window(cr, win):
            return False
        r = self.get_iter_location(buf.get_iter_at_mark(buf.get_insert()))
        wy = self.buffer_to_window_coords(Gtk.TextWindowType.TEXT, 0, r.y)[1]
        cr.save()
        Gtk.cairo_transform_to_window(cr, self, win)
        cr.rectangle(0, wy, win.get_width(), r.height)
        cr.set_source_rgba(*self.doc.app.style.line_rgba)
        cr.fill()
        cr.restore()
        return False

    def _draw_gutter(self, view, cr):
        win = self.get_window(Gtk.TextWindowType.LEFT)
        if win is None or self._gw == 0 or not Gtk.cairo_should_draw_window(cr, win):
            return False
        st = self.doc.app.style
        buf = self.get_buffer()
        cur = buf.get_iter_at_mark(buf.get_insert()).get_line()
        w, h = win.get_width(), win.get_height()
        cr.save()
        Gtk.cairo_transform_to_window(cr, self, win)
        lay = self.create_pango_layout("")
        lay.set_alignment(Pango.Alignment.RIGHT)
        lay.set_width((w - 12) * Pango.SCALE)
        rect = self.get_visible_rect()
        it, _top = self.get_line_at_y(rect.y)
        ln = it.get_line()

        def draw(n, y):
            lay.set_text(str(n + 1), -1)
            cr.set_source_rgba(*(st.gutter_cur if n == cur else st.gutter))
            cr.move_to(0, y + 1)
            PangoCairo.show_layout(cr, lay)

        while True:
            y, _h = self.get_line_yrange(it)
            wy = self.buffer_to_window_coords(Gtk.TextWindowType.LEFT, 0, y)[1]
            if wy > h:
                break
            draw(ln, wy)
            if not it.forward_line():
                if it.get_line() != ln and it.is_end():          # the empty line after a final newline
                    y, _h = self.get_line_yrange(it)
                    draw(it.get_line(), self.buffer_to_window_coords(Gtk.TextWindowType.LEFT, 0, y)[1])
                break
            ln = it.get_line()
        cr.restore()
        return False


# ------------------------------------------------------------------------------------------------------------------------ a document
class Doc:
    """One open file: text buffer, view, undo history, highlighting state."""

    def __init__(self, app, path=None):
        self.app, self.path = app, path
        self.lang = synhl.PLAIN
        self.enc, self.bom, self.eol = "utf-8", False, "\n"
        self.mtime = None
        self.use_tabs, self.width = False, 4
        self.dirty = False
        self.missing = False
        self.undo = cu.UndoStack()
        self.buf = Gtk.TextBuffer()
        self.tags = {k: self.buf.create_tag("syn-" + k) for k in synhl.KINDS}
        self.t_find = self.buf.create_tag("find")
        self.t_cur = self.buf.create_tag("findcur")
        self.t_br = self.buf.create_tag("bracket")             # created last = highest priority
        app.style.apply_tags(self)
        self.view = CodeView(self)
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.sw.add(self.view)
        self.sw.doc = self
        self.tab_title = self.tab_dot = None
        self._tokens, self._starts, self._spans = [], [], []
        self._ver = self._tok_ver = 0
        self._hl_src = self._ap_src = self._st_src = 0
        self._br = []
        self.matches = []
        self.big = False
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if app.opt["wrap"] else Gtk.WrapMode.NONE)
        self.buf.connect("insert-text", self._on_insert)
        self.buf.connect("delete-range", self._on_delete)
        self.buf.connect("changed", self._on_changed)
        self.buf.connect("mark-set", self._on_mark)
        self.view.connect("key-press-event", self.on_key)
        self.view.connect("size-allocate", lambda *_: self._queue_apply())
        self.view.connect("populate-popup", self._popup)
        self.sw.get_vadjustment().connect("value-changed", lambda *_: self._queue_apply())

    # ---------------------------------------------------------------- basics
    @property
    def name(self):
        return os.path.basename(self.path) if self.path else "Untitled"

    def text(self):
        return self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), True)

    def at(self, off):
        return self.buf.get_iter_at_offset(max(0, min(off, self.buf.get_char_count())))

    def cursor(self):
        return self.buf.get_iter_at_mark(self.buf.get_insert())

    def group(self):
        doc = self

        class _G:
            def __enter__(s):
                doc.undo.begin(doc.cursor().get_offset())
                doc.buf.begin_user_action()

            def __exit__(s, *a):
                doc.buf.end_user_action()
                doc.undo.end()
                return False
        return _G()

    def unit(self):
        return "\t" if self.use_tabs else " " * self.width

    def set_dirty(self, d):
        if d != self.dirty:
            self.dirty = d
            if self.tab_dot is not None:
                self.tab_dot.set_visible(d)
            self.app.doc_state_changed(self)

    # ---------------------------------------------------------------- load / save
    def load(self):
        st = os.stat(self.path)
        if st.st_size > MAX_OPEN:
            raise ValueError("too large (%d MB)" % (st.st_size // 1048576))
        with open(self.path, "rb") as f:
            data = f.read()
        text, self.enc, self.bom, self.eol = cu.decode(data)
        self.mtime = st.st_mtime
        self.missing = False
        self._set_text(text)
        self.lang = synhl.detect(self.path, text.split("\n", 1)[0])
        mode, w = cu.detect_indent(text, self.lang.indent)
        self.use_tabs, self.width = (True, self.lang.indent) if (mode == "tabs" or self.lang.tabs and mode != "spaces") else (False, w)

    def _set_text(self, text):
        keep = self.cursor().get_line() if self.buf.get_char_count() else 0
        self.undo.busy = True
        try:
            self.buf.set_text(text)
        finally:
            self.undo.busy = False
        self.undo.reset()
        self.undo.mark_clean()
        self.big = len(text) > MAX_HL
        self.buf.place_cursor(self.buf.get_iter_at_line(min(keep, self.buf.get_line_count() - 1)))
        self.set_dirty(False)
        self._hl_now()

    def reload(self):
        """Re-read the file from disk (the buffer was clean, or the user chose to discard its changes)."""
        line = self.cursor().get_line()
        self.load()
        self.buf.place_cursor(self.buf.get_iter_at_line(min(line, self.buf.get_line_count() - 1)))

    def write(self, path=None):
        """Save to `path` (default: its own); raises OSError. Applies the trim / final-newline options first."""
        target = path or self.path
        if self.app.opt["trim"] or self.app.opt["final_nl"]:
            self._tidy()
        data = cu.encode(self.text(), self.enc, self.bom, self.eol)
        mode = None
        try:
            mode = os.stat(target).st_mode & 0o7777
        except OSError:
            pass
        tmp = "%s.%d.tmp" % (target, os.getpid())
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            if mode is not None:
                os.chmod(tmp, mode)
            os.replace(tmp, target)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            with open(target, "wb") as f:                       # e.g. a directory we may not create files in
                f.write(data)
        self.path = target
        self.mtime = os.stat(target).st_mtime
        self.missing = False
        self.undo.mark_clean()
        self.set_dirty(False)
        self.lang = synhl.detect(self.path, self.buf.get_text(self.buf.get_start_iter(), self.at(200), False).split("\n", 1)[0])
        self._hl_now()

    def _tidy(self):
        with self.group():
            if self.app.opt["trim"]:
                for n in range(self.buf.get_line_count() - 1, -1, -1):
                    a = self.buf.get_iter_at_line(n)
                    b = a.copy()
                    if not b.ends_line():
                        b.forward_to_line_end()
                    line = self.buf.get_text(a, b, False)
                    stripped = line.rstrip(" \t")
                    if len(stripped) != len(line):
                        s = self.buf.get_iter_at_line(n)
                        s.forward_chars(len(stripped))
                        self.buf.delete(s, b)
            if self.app.opt["final_nl"]:
                end = self.buf.get_end_iter()
                if self.buf.get_char_count() and not end.starts_line():
                    self.buf.insert(end, "\n")

    def changed_on_disk(self):
        if not self.path or self.missing:
            return None
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            return "deleted"
        return "changed" if self.mtime is not None and abs(m - self.mtime) > 0.001 else None

    # ---------------------------------------------------------------- undo
    def _on_insert(self, buf, loc, text, length):
        if not self.undo.busy:
            off = loc.get_offset()
            self.undo.record("i", off, text, self.cursor().get_offset(), off + len(text))

    def _on_delete(self, buf, a, b):
        if not self.undo.busy:
            off = a.get_offset()
            self.undo.record("d", off, buf.get_text(a, b, True), self.cursor().get_offset(), off)

    def _apply_op(self, kind, off, text):
        if kind == "i":
            self.buf.insert(self.at(off), text)
        else:
            self.buf.delete(self.at(off), self.at(off + len(text)))

    def do_undo(self):
        c = self.undo.undo_step(self._apply_op)
        self._after_undo(c)

    def do_redo(self):
        c = self.undo.redo_step(self._apply_op)
        self._after_undo(c)

    def _after_undo(self, c):
        if c is None:
            self.app.say("Nothing to undo / redo")
            return
        self.buf.place_cursor(self.at(c))
        self.view.scroll_mark_onscreen(self.buf.get_insert())
        self.set_dirty(not self.undo.is_clean())

    # ---------------------------------------------------------------- signals
    def _on_changed(self, buf):
        self._ver += 1
        self.set_dirty(not self.undo.is_clean())
        self.view.update_gutter()
        self._schedule_hl()
        self._queue_status()
        self.app.doc_edited(self)

    def _on_mark(self, buf, it, mark):
        if mark == buf.get_insert():
            self.view.queue_draw()
            self._queue_status()

    def _queue_status(self):
        if not self._st_src:
            self._st_src = GLib.timeout_add(40, self._status_now)

    def _status_now(self):
        self._st_src = 0
        self._brackets()
        if self.app.cur() is self:
            self.app.update_status()
        return False

    def _popup(self, view, menu):
        pass

    # ---------------------------------------------------------------- highlighting
    def set_lang(self, lang):
        self.lang = lang
        self._hl_now()
        self.app.update_status()

    def _schedule_hl(self):
        if not self._hl_src:
            self._hl_src = GLib.timeout_add(90 if self.buf.get_char_count() < 300000 else 350, self._hl_now)

    def _hl_now(self):
        if self._hl_src:
            GLib.source_remove(self._hl_src)
        self._hl_src = 0
        if self.big:
            self._tokens, self._starts, self._spans = [], [], []
            self.buf.remove_all_tags(self.buf.get_start_iter(), self.buf.get_end_iter())
            return False
        text = self.text()
        toks = list(self.lang.tokenize(text))
        self._tokens, self._starts = toks, [t[0] for t in toks]
        self._spans = [(s, e) for s, e, k in toks if k in ("string", "comment")]
        self._tok_ver = self._ver
        self._apply_region()
        return False

    def _queue_apply(self):
        if not self._ap_src:
            self._ap_src = GLib.timeout_add(25, self._apply_region)

    def _apply_region(self):
        self._ap_src = 0
        if self.big or not self._tokens:
            return False
        buf, view = self.buf, self.view
        rect = view.get_visible_rect()
        top = view.get_line_at_y(max(0, rect.y - 500))[0]
        bot = view.get_line_at_y(rect.y + rect.height + 500)[0]
        bot.forward_to_line_end()
        s_off, e_off = top.get_offset(), bot.get_offset()
        for t in self.tags.values():
            buf.remove_tag(t, top, bot)
        i = max(0, bisect.bisect_left(self._starts, s_off) - 1)
        toks, n = self._tokens, len(self._tokens)
        while i < n and toks[i][0] < e_off:
            s, e, k = toks[i]
            if e > s_off:
                buf.apply_tag(self.tags[k], buf.get_iter_at_offset(s), buf.get_iter_at_offset(e))
            i += 1
        return False

    def _brackets(self):
        buf = self.buf
        for s, e in self._br:
            if e <= buf.get_char_count():
                buf.remove_tag(self.t_br, self.at(s), self.at(e))
        self._br = []
        if buf.get_has_selection() or buf.get_char_count() > MAX_BRACKET or not self.lang.pairs:
            return
        it = self.cursor()
        off = it.get_offset()
        text = self.text()
        skip = self._spans if self._tok_ver == self._ver else None
        for p in (off, off - 1):
            if 0 <= p < len(text) and text[p] in "()[]{}":
                m = synhl.find_match(text, p, skip)
                if m is not None:
                    self._br = [(p, p + 1), (m, m + 1)]
                    for s, e in self._br:
                        buf.apply_tag(self.t_br, self.at(s), self.at(e))
                    return

    # ---------------------------------------------------------------- navigation
    def goto(self, line, col=1):
        n = max(0, min(line - 1, self.buf.get_line_count() - 1))
        it = self.buf.get_iter_at_line(n)
        end = it.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        it.forward_chars(max(0, min(col - 1, end.get_line_offset())))
        self.buf.place_cursor(it)
        GLib.idle_add(lambda: (self.view.scroll_to_iter(self.cursor(), 0.12, True, 0.5, 0.4), False)[1])

    def select_span(self, s, e, centre=True):
        self.buf.select_range(self.at(e), self.at(s))
        if centre:
            self.view.scroll_to_iter(self.at(s), 0.12, True, 0.5, 0.4)

    # ---------------------------------------------------------------- line helpers
    def lines_span(self):
        b = self.buf.get_selection_bounds()
        if not b:
            n = self.cursor().get_line()
            return n, n
        first, last = b[0].get_line(), b[1].get_line()
        if b[1].get_line_offset() == 0 and last > first:
            last -= 1
        return first, last

    def _line_iters(self, first, last):
        a = self.buf.get_iter_at_line(first)
        b = self.buf.get_iter_at_line(last)
        if not b.ends_line():
            b.forward_to_line_end()
        return a, b

    def get_lines(self, first, last):
        a, b = self._line_iters(first, last)
        return self.buf.get_text(a, b, True).split("\n")

    def replace_lines(self, first, last, new, select=True):
        a, b = self._line_iters(first, last)
        start = a.get_offset()
        self.buf.delete(a, b)
        body = "\n".join(new)
        self.buf.insert(self.at(start), body)
        if select:
            self.buf.select_range(self.at(start + len(body)), self.at(start))

    def edit_lines(self, fn):
        first, last = self.lines_span()
        with self.group():
            self.replace_lines(first, last, fn(self.get_lines(first, last)))

    def indent(self):
        self.edit_lines(lambda ls: cu.indent_lines(ls, self.unit()))

    def outdent(self):
        self.edit_lines(lambda ls: cu.outdent_lines(ls, self.unit(), self.width))

    def toggle_comment(self):
        lc, bc = self.lang.line_comment, self.lang.block_comment
        if not lc and not bc:
            self.app.say("%s has no comment syntax" % self.lang.name)
            return
        self.edit_lines(lambda ls: cu.toggle_comment(ls, lc, None if lc else bc))

    def duplicate(self):
        first, last = self.lines_span()
        had_sel = self.buf.get_has_selection()
        col = self.cursor().get_line_offset()
        lines = self.get_lines(first, last)
        with self.group():
            end = self._line_iters(last, last)[1]
            self.buf.insert(end, "\n" + "\n".join(lines))
        if had_sel:
            a, b = self._line_iters(last + 1, last + len(lines))
            self.buf.select_range(b, a)
        else:
            it = self.buf.get_iter_at_line(last + 1)
            it.forward_chars(min(col, len(lines[0])))
            self.buf.place_cursor(it)

    def delete_lines(self):
        first, last = self.lines_span()
        with self.group():
            a = self.buf.get_iter_at_line(first)
            if last + 1 < self.buf.get_line_count():
                b = self.buf.get_iter_at_line(last + 1)
            else:
                b = self.buf.get_end_iter()
                if first > 0:
                    a.backward_char()
            self.buf.delete(a, b)

    def move_lines(self, down):
        first, last = self.lines_span()
        had_sel = self.buf.get_has_selection()
        col = self.cursor().get_line_offset()
        count = self.buf.get_line_count()
        if (not down and first == 0) or (down and last + 1 >= count):
            return
        with self.group():
            block = self.get_lines(first, last)
            if down:
                other = self.get_lines(last + 1, last + 1)
                self.replace_lines(first, last + 1, other + block, select=False)
                nf, nl = first + 1, last + 1
            else:
                other = self.get_lines(first - 1, first - 1)
                self.replace_lines(first - 1, last, block + other, select=False)
                nf, nl = first - 1, last - 1
        if had_sel:
            a, b = self._line_iters(nf, nl)
            self.buf.select_range(b, a)
        else:
            it = self.buf.get_iter_at_line(nf)
            it.forward_chars(min(col, len(block[0])))
            self.buf.place_cursor(it)
        self.view.scroll_mark_onscreen(self.buf.get_insert())

    # ---------------------------------------------------------------- typing
    def on_key(self, view, ev):
        if view.get_buffer() is not self.buf:
            return False
        st = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl, shift, alt = bool(st & Gdk.ModifierType.CONTROL_MASK), bool(st & Gdk.ModifierType.SHIFT_MASK), bool(st & Gdk.ModifierType.MOD1_MASK)
        kv = ev.keyval
        if not view.get_editable():
            return False
        if kv in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not ctrl and not alt:
            return self._tab(shift or kv == Gdk.KEY_ISO_Left_Tab)
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not ctrl and not alt:
            return self._enter()
        if kv == Gdk.KEY_BackSpace and not st:
            return self._backspace()
        if kv in (Gdk.KEY_Home, Gdk.KEY_KP_Home) and not ctrl and not alt:
            return self._home(shift)
        if alt and not ctrl and not shift and kv in (Gdk.KEY_Up, Gdk.KEY_Down):
            self.move_lines(kv == Gdk.KEY_Down)
            return True
        if not ctrl and not alt:
            u = Gdk.keyval_to_unicode(kv)
            if u and chr(u).isprintable():
                return self._type(chr(u))
        return False

    def _tab(self, back):
        sel = self.buf.get_selection_bounds()
        if sel and sel[0].get_line() != sel[1].get_line():
            (self.outdent if back else self.indent)()
            return True
        if back:
            self.outdent()
            return True
        if self.use_tabs:
            return False                                       # the view inserts a real tab
        it = self.cursor()
        col = it.get_line_offset()
        with self.group():
            if sel:
                self.buf.delete_selection(True, True)
            self.buf.insert_at_cursor(" " * (self.width - col % self.width))
        self.view.scroll_mark_onscreen(self.buf.get_insert())
        return True

    def _enter(self):
        buf = self.buf
        with self.group():
            if buf.get_has_selection():
                buf.delete_selection(True, True)
            it = self.cursor()
            ls = it.copy()
            ls.set_line_offset(0)
            before = buf.get_text(ls, it, False)
            nxt = "" if it.is_end() else it.get_char()
            indent = synhl.next_indent(self.lang, before, self.unit())
            if self.lang.name == "Python":
                w = before.strip().split(None, 1)[0] if before.strip() else ""
                if w in ("return", "pass", "break", "continue", "raise") and not before.rstrip().endswith((":", "\\", "(", "[", "{", ",")):
                    cut = len(self.unit())
                    indent = indent[:-cut] if cut and indent.endswith(self.unit()) else indent
            if before and not before.strip():                  # an all-blank line: do not leave trailing white space behind
                buf.delete(ls, it)
                it = self.cursor()
            btrim = before.rstrip()
            if self.lang.pairs and btrim and btrim[-1] in "([{" and nxt == OPEN_CLOSE.get(btrim[-1]):
                base = synhl.indent_of(before)
                buf.insert_at_cursor("\n" + indent + "\n" + base)
                it = self.cursor()
                it.backward_chars(1 + len(base))
                buf.place_cursor(it)
            else:
                buf.insert_at_cursor("\n" + indent)
        self.view.scroll_mark_onscreen(buf.get_insert())
        return True

    def _backspace(self):
        buf = self.buf
        if buf.get_has_selection():
            return False
        it = self.cursor()
        if it.is_start():
            return False
        prev = it.copy()
        prev.backward_char()
        pc = prev.get_char()
        nxt = "" if it.is_end() else it.get_char()
        if self.app.opt["pairs"] and self.lang.pairs and pc in OPEN_CLOSE and nxt == OPEN_CLOSE[pc]:
            end = it.copy()
            end.forward_char()
            with self.group():
                buf.delete(prev, end)
            return True
        if not self.use_tabs:
            ls = it.copy()
            ls.set_line_offset(0)
            before = buf.get_text(ls, it, False)
            if len(before) > 1 and not before.strip(" "):
                n = len(before) % self.width or self.width
                start = it.copy()
                start.backward_chars(min(n, len(before)))
                with self.group():
                    buf.delete(start, it)
                return True
        return False

    def _home(self, extend):
        buf = self.buf
        it = self.cursor()
        ls = it.copy()
        ls.set_line_offset(0)
        fn = ls.copy()
        while not fn.ends_line() and fn.get_char() in " \t":
            fn.forward_char()
        target = fn if it.get_offset() != fn.get_offset() else ls
        if extend:
            buf.move_mark(buf.get_insert(), target)
        else:
            buf.place_cursor(target)
        self.view.scroll_mark_onscreen(buf.get_insert())
        return True

    def _type(self, ch):
        if not (self.app.opt["pairs"] and self.lang.pairs) or ch not in OPEN_CLOSE and ch not in CLOSERS:
            return False
        if ch == "'" and self.lang.name == "Rust":
            return False
        buf = self.buf
        sel = buf.get_selection_bounds()
        if sel:
            if ch in OPEN_CLOSE:
                s, e = sel[0].get_offset(), sel[1].get_offset()
                with self.group():
                    buf.insert(self.at(e), OPEN_CLOSE[ch])
                    buf.insert(self.at(s), ch)
                buf.select_range(self.at(e + 1), self.at(s + 1))
                return True
            return False
        it = self.cursor()
        nxt = "" if it.is_end() else it.get_char()
        if ch in CLOSERS and nxt == ch:
            it.forward_char()
            buf.place_cursor(it)
            return True
        if ch in OPEN_CLOSE:
            prev = ""
            if not it.starts_line():
                p = it.copy()
                p.backward_char()
                prev = p.get_char()
            if ch in QUOTES and (prev.isalnum() or prev in ("\\", ch, "_")):
                return False
            if nxt and (nxt.isalnum() or nxt in "_$"):
                return False
            with self.group():
                buf.insert_at_cursor(ch + OPEN_CLOSE[ch])
                it = self.cursor()
                it.backward_char()
                buf.place_cursor(it)
            return True
        return False

    def dispose(self):
        for s in (self._hl_src, self._ap_src, self._st_src):
            if s:
                try:
                    GLib.source_remove(s)
                except Exception:
                    pass
        self._hl_src = self._ap_src = self._st_src = 0


# ------------------------------------------------------------------------------------------------------------------------ sidebar tree
class FolderTree(Gtk.Box):
    """Directory tree of the opened folder: lazy loading, folders first, right-click actions, refresh without losing the expansion."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.app, self.root = app, None
        self.store = Gtk.TreeStore(GdkPixbufType(), str, str, bool)            # icon, name, path, is_dir
        self.store.set_sort_func(1, self._cmp, None)
        self.store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        head = Gtk.Box(spacing=2)
        head.set_margin_start(10); head.set_margin_end(4); head.set_margin_top(6)
        self.title = label("No folder opened", "h1")
        head.pack_start(self.title, True, True, 0)
        for icon, tip, cb in (("file_plus", "New file", lambda: self.new_item(False)), ("folder_line", "New folder", lambda: self.new_item(True)),
                              ("refresh", "Refresh", self.refresh), ("collapse", "Collapse all", self.collapse_all)):
            b = icon_button(icon, 13, tip, cb, color=scheme.ink(), pad=6)
            head.pack_start(b, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.view = Gtk.TreeView(model=self.store)
        self.view.get_style_context().add_class("codetree")
        self.view.set_headers_visible(False)
        self.view.set_enable_search(True)
        self.view.set_search_column(1)
        self.view.set_enable_tree_lines(False)
        self.view.set_show_expanders(True)
        self.view.set_level_indentation(2)
        col = Gtk.TreeViewColumn()
        pr = Gtk.CellRendererPixbuf()
        pr.set_padding(4, 2)
        col.pack_start(pr, False)
        col.add_attribute(pr, "pixbuf", 0)
        tr = Gtk.CellRendererText()
        tr.set_padding(2, 3)
        tr.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        tr.set_property("foreground-rgba", Gdk.RGBA(*scheme.ink()))
        col.pack_start(tr, True)
        col.add_attribute(tr, "text", 1)
        self.view.append_column(col)
        self.view.connect("row-expanded", self._expanded)
        self.view.connect("row-activated", self._activated)
        self.view.connect("button-press-event", self._press)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.view)
        sw.set_vexpand(True)
        self.pack_start(sw, True, True, 0)

    @staticmethod
    def _cmp(model, a, b, _data):
        da, db = model.get_value(a, 3), model.get_value(b, 3)
        if da != db:
            return -1 if da else 1
        na, nb = model.get_value(a, 1).casefold(), model.get_value(b, 1).casefold()
        return (na > nb) - (na < nb)

    # ---------------------------------------------------------------- content
    def scan(self, path):
        out = {}
        hidden = self.app.opt["hidden"]
        try:
            with os.scandir(path) as entries:
                for e in entries:
                    n = e.name
                    if n in HIDDEN_ALWAYS or n.endswith((".pyc", "~")) or (not hidden and n.startswith(".")):
                        continue
                    try:
                        out[n] = e.is_dir()
                    except OSError:
                        out[n] = False
        except OSError:
            pass
        return out

    def _row(self, parent, name, path, is_dir):
        lang = None if is_dir else synhl.detect(path).name
        it = self.store.append(parent, [tree_icon(is_dir, lang), name, path, is_dir])
        if is_dir:
            self.store.append(it, [None, "", "", False])                     # placeholder so the expander shows
        return it

    def set_root(self, path):
        self.root = path
        self.store.clear()
        if not path:
            self.title.set_text("No folder opened")
            return
        self.title.set_text(os.path.basename(path.rstrip("/")) or path)
        self.title.set_tooltip_text(path)
        for name, is_dir in self.scan(path).items():
            self._row(None, name, os.path.join(path, name), is_dir)

    def _expanded(self, view, it, tpath):
        child = self.store.iter_children(it)
        if child is not None and self.store.get_value(child, 2) == "":
            self.store.remove(child)
            base = self.store.get_value(it, 2)
            for name, is_dir in self.scan(base).items():
                self._row(it, name, os.path.join(base, name), is_dir)

    def refresh(self):
        if not self.root:
            return
        self._sync(None, self.root)

    def _sync(self, parent, base):
        entries = self.scan(base)
        existing = {}
        child = self.store.iter_children(parent)
        while child is not None:
            existing[self.store.get_value(child, 1)] = child
            child = self.store.iter_next(child)
        existing.pop("", None)
        for name, it in list(existing.items()):
            if name not in entries or self.store.get_value(it, 3) != entries[name]:
                self.store.remove(it)
                del existing[name]
        for name, is_dir in entries.items():
            if name not in existing:
                existing[name] = self._row(parent, name, os.path.join(base, name), is_dir)
        for name, it in existing.items():
            if entries[name] and self.view.row_expanded(self.store.get_path(it)):
                self._sync(it, os.path.join(base, name))

    def collapse_all(self):
        self.view.collapse_all()

    def reveal(self, path):
        """Expand the tree down to `path` and select it."""
        if not self.root or not path.startswith(self.root.rstrip("/") + "/"):
            return
        parts = os.path.relpath(path, self.root).split(os.sep)
        parent, cur = None, self.root
        for i, part in enumerate(parts):
            it = self.store.iter_children(parent)
            while it is not None and self.store.get_value(it, 1) != part:
                it = self.store.iter_next(it)
            if it is None:
                return
            cur = os.path.join(cur, part)
            tp = self.store.get_path(it)
            if i < len(parts) - 1:
                self.view.expand_row(tp, False)
                parent = it
            else:
                self.view.get_selection().select_path(tp)
                self.view.scroll_to_cell(tp, None, True, 0.5, 0.0)

    # ---------------------------------------------------------------- interaction
    def _info(self, tpath):
        it = self.store.get_iter(tpath)
        return self.store.get_value(it, 1), self.store.get_value(it, 2), self.store.get_value(it, 3)

    def _activated(self, view, tpath, col):
        name, path, is_dir = self._info(tpath)
        if is_dir:
            if view.row_expanded(tpath):
                view.collapse_row(tpath)
            else:
                view.expand_row(tpath, False)
        else:
            self.app.open_file(path)

    def _press(self, view, ev):
        if ev.button not in (1, 3):
            return False
        hit = view.get_path_at_pos(int(ev.x), int(ev.y))
        if hit is None:
            if ev.button == 3 and self.root:
                self._menu(ev, self.root, True)
                return True
            return False
        tpath = hit[0]
        name, path, is_dir = self._info(tpath)
        view.get_selection().select_path(tpath)
        view.grab_focus()
        if ev.button == 3:
            self._menu(ev, path, is_dir)
            return True
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            return True
        if is_dir:
            if view.row_expanded(tpath):
                view.collapse_row(tpath)
            else:
                view.expand_row(tpath, False)
        else:
            self.app.open_file(path)
        return True

    def selected(self):
        model, it = self.view.get_selection().get_selected()
        if it is None:
            return self.root, True
        return model.get_value(it, 2), model.get_value(it, 3)

    def _menu(self, ev, path, is_dir):
        a = self.app
        folder = path if is_dir else os.path.dirname(path)
        items = []
        if is_dir:
            items += [("item", "New file…", lambda: self.new_item(False, folder)), ("item", "New folder…", lambda: self.new_item(True, folder)), ("sep",)]
        else:
            items += [("item", "Open", lambda: a.open_file(path)), ("sep",)]
        if path != self.root:
            items += [("item", "Rename…", lambda: a.rename_path(path)), ("item", "Move to Trash", lambda: a.trash_path(path)), ("sep",)]
        items += [("item", "Open terminal here", lambda: a.fire("sparkterm", folder)),
                  ("item", "Show in Files", lambda: a.fire("sparkfiles", folder)),
                  ("item", "Copy path", lambda: a.copy_text(path)), ("sep",),
                  ("item", "Refresh", self.refresh)]
        GlassMenu(items, light=True, theme=a.th).popup_at(ev.x_root, ev.y_root)

    def new_item(self, is_dir, folder=None):
        if folder is None:
            p, d = self.selected()
            folder = (p if d else os.path.dirname(p)) if p else None
        if not folder:
            self.app.say("Open a folder first")
            return
        self.app.new_in_folder(folder, is_dir)


def GdkPixbufType():
    from gi.repository import GdkPixbuf
    return GdkPixbuf.Pixbuf


# ------------------------------------------------------------------------------------------------------------------------ the window
class SparkCode(appkit.GlassWindow):
    def __init__(self, paths=(), line=None):
        super().__init__("SparkCode", "sparkcode", "window_light", (1120, 740))
        self.cfg = config.load(CFG)
        saved = self.cfg.get("view", {})
        self.opt = {k: (type(v)(saved[k]) if k in saved and not isinstance(v, bool) else bool(saved[k]) if k in saved else v) for k, v in DEFAULTS.items()}
        self.opt["zoom"] = max(0.6, min(3.0, float(self.opt["zoom"])))
        self.style = Style(self.th)
        self.docs, self.root = [], None
        self._rx, self._find_src, self._msg_src = None, 0, 0
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 14)
        self._apply_css()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m, v in (("top", 2), ("bottom", 4), ("start", 4), ("end", 4)):
            getattr(outer, "set_margin_" + m)(v)
        self.add(outer)
        outer.pack_start(self._build_toolbar(), False, False, 0)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(self.paned, True, True, 0)
        self.tree = FolderTree(self)
        self.side = Gtk.Box()
        self.side.get_style_context().add_class("sidebar")
        self.side.pack_start(self.tree, True, True, 0)
        self.side.set_size_request(150, -1)
        self.paned.pack1(self.side, False, False)
        self.paned.set_position(int(self.opt["sidebar_w"]))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stack = Gtk.Stack()
        self.stack.add_named(self._build_welcome(), "welcome")
        self.stack.add_named(self._build_editor(), "editor")
        wrap = Gtk.Box()
        wrap.get_style_context().add_class("inner")
        wrap.pack_start(self.stack, True, True, 0)
        right.pack_start(wrap, True, True, 0)
        self.paned.pack2(right, True, False)

        outer.pack_start(self._build_status(), False, False, 0)
        self.connect("key-press-event", self._key)
        self.connect("delete-event", self._on_delete_event)
        self.connect("focus-in-event", self._focus_in)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._dropped)

        self.show_all()
        self.side.set_visible(self.opt["sidebar"])
        self.find_rev.set_reveal_child(False)
        self.notice_box.hide()
        self.stack.set_visible_child_name("welcome")
        self._startup(list(paths), line)

    # ---------------------------------------------------------------- building
    def _build_toolbar(self):
        ink = scheme.ink()
        tb = Gtk.Box(spacing=2)
        self.b_side = icon_button("panel_left", 15, "Toggle sidebar (Ctrl+B)", self.toggle_sidebar, color=ink, pad=8)
        tb.pack_start(self.b_side, False, False, 0)
        for icon, tip, cb in (("folder_line", "Open folder… (Ctrl+Shift+O)", self.open_folder_dialog), ("doc", "Open file… (Ctrl+O)", self.open_file_dialog),
                              ("file_plus", "New file (Ctrl+N)", self.new_file), ("save", "Save (Ctrl+S)", self.save)):
            tb.pack_start(icon_button(icon, 15, tip, cb, color=ink, pad=8), False, False, 0)
        self.crumb = label("", "muted", 0.5)
        tb.pack_start(self.crumb, True, True, 8)
        for icon, tip, cb in (("search", "Go to file… (Ctrl+P)", self.quick_open), ("terminal", "Open terminal here (Ctrl+`)", self.open_terminal)):
            tb.pack_start(icon_button(icon, 15, tip, cb, color=ink, pad=8), False, False, 0)
        self.b_menu = icon_button("list", 15, "Menu", None, color=ink, pad=8)
        self.b_menu.connect("clicked", lambda b: self._popup_below(b, self._main_menu_items(), 250))
        tb.pack_start(self.b_menu, False, False, 0)
        return tb

    def _build_welcome(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        logo = Ico("code", 54, scheme.ink(), 1.5)
        box.pack_start(logo, False, False, 0)
        box.pack_start(label("SparkCode", "proptitle", 0.5, ellipsize=False), False, False, 0)
        box.pack_start(label("Open a folder to browse a project, or drop files here.", "muted", 0.5, ellipsize=False), False, False, 0)
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.CENTER)
        row.set_margin_top(8)
        for text, cb in (("Open folder…", self.open_folder_dialog), ("Open file…", self.open_file_dialog), ("New file", self.new_file)):
            b = Gtk.Button(label=text)
            b.get_style_context().add_class("choicebtn")
            b.connect("clicked", lambda *_, f=cb: f())
            row.pack_start(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.recent_box.set_margin_top(14)
        box.pack_start(self.recent_box, False, False, 0)
        self._fill_recent()
        return box

    def _fill_recent(self):
        for c in self.recent_box.get_children():
            self.recent_box.remove(c)
        recent = [p for p in (self.cfg.get("recent", {}).get("folders") or []) if isinstance(p, str) and os.path.isdir(p)][:5]
        if recent:
            self.recent_box.pack_start(label("Recent folders", "h2", 0.5), False, False, 2)
        for p in recent:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(label(p.replace(os.path.expanduser("~"), "~"), None, 0.5))
            b.connect("clicked", lambda _b, q=p: self.open_folder(q))
            self.recent_box.pack_start(b, False, False, 0)
        self.recent_box.show_all()

    def _build_editor(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.notice_box = Gtk.Box(spacing=8)
        self.notice_box.set_margin_start(12); self.notice_box.set_margin_end(12); self.notice_box.set_margin_top(6)
        self.notice_lbl = label("", None)
        self.notice_btns = Gtk.Box(spacing=6)
        self.notice_box.pack_start(self.notice_lbl, True, True, 0)
        self.notice_box.pack_start(self.notice_btns, False, False, 0)
        box.pack_start(self.notice_box, False, False, 0)
        self.nb = Gtk.Notebook()
        self.nb.set_scrollable(True)
        self.nb.set_show_border(False)
        self.nb.set_margin_start(4); self.nb.set_margin_end(4); self.nb.set_margin_top(2)
        add = icon_button("plus", 13, "New file (Ctrl+N)", self.new_file, color=scheme.ink(), pad=7)
        add.show_all()
        self.nb.set_action_widget(add, Gtk.PackType.END)
        self.nb.connect("switch-page", self._switched)
        box.pack_start(self.nb, True, True, 0)
        box.pack_start(self._build_find(), False, False, 0)
        return box

    def _build_find(self):
        self.find_rev = Gtk.Revealer()
        self.find_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bar.get_style_context().add_class("card2")
        for m in ("top", "bottom", "start", "end"):
            getattr(bar, "set_margin_" + m)(6)
        bar.set_border_width(6)
        r1 = Gtk.Box(spacing=6)
        self.find_entry = Gtk.Entry()
        self.find_entry.set_placeholder_text("Find")
        self.find_entry.set_hexpand(True)
        self.find_entry.connect("changed", lambda *_: self.find_update())
        self.find_entry.connect("key-press-event", self._find_key)
        r1.pack_start(self.find_entry, True, True, 0)
        self.t_case, self.t_regex, self.t_word = (Gtk.ToggleButton(label=t) for t in ("Aa", ".*", "W"))
        for b, tip in ((self.t_case, "Match case"), (self.t_regex, "Regular expression"), (self.t_word, "Whole word")):
            b.get_style_context().add_class("findtoggle")
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("toggled", lambda *_: self.find_update())
            r1.pack_start(b, False, False, 0)
        self.find_count = label("", "muted")
        self.find_count.set_width_chars(11)
        r1.pack_start(self.find_count, False, False, 4)
        r1.pack_start(icon_button("chev_up", 12, "Previous (Shift+F3)", lambda: self.find_next(True), color=scheme.ink(), pad=6), False, False, 0)
        r1.pack_start(icon_button("chev_down", 12, "Next (F3)", lambda: self.find_next(False), color=scheme.ink(), pad=6), False, False, 0)
        r1.pack_start(icon_button("close", 10, "Close (Esc)", self.find_close, color=scheme.ink(), pad=6), False, False, 0)
        bar.pack_start(r1, False, False, 0)
        self.rep_row = Gtk.Box(spacing=6)
        self.rep_entry = Gtk.Entry()
        self.rep_entry.set_placeholder_text("Replace with")
        self.rep_entry.set_hexpand(True)
        self.rep_entry.connect("key-press-event", self._find_key)
        self.rep_row.pack_start(self.rep_entry, True, True, 0)
        for text, cb in (("Replace", self.replace_one), ("Replace all", self.replace_all)):
            b = Gtk.Button(label=text)
            b.get_style_context().add_class("choicebtn")
            b.connect("clicked", lambda *_, f=cb: f())
            self.rep_row.pack_start(b, False, False, 0)
        bar.pack_start(self.rep_row, False, False, 0)
        self.find_rev.add(bar)
        return self.find_rev

    def _build_status(self):
        sb = Gtk.Box(spacing=4)
        sb.set_margin_start(8); sb.set_margin_end(4)
        self.status = label("", "muted")
        sb.pack_start(self.status, True, True, 0)

        def btn(cb):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("statusbtn")
            l = label("", "muted")
            b.add(l)
            b.lab = l
            b.connect("clicked", lambda x: cb(x))
            sb.pack_start(b, False, False, 0)
            return b
        self.s_pos = btn(lambda b: self.goto_line())
        self.s_indent = btn(lambda b: self._indent_menu(b))
        self.s_enc = btn(lambda b: None)
        self.s_eol = btn(lambda b: self._eol_menu(b))
        self.s_lang = btn(lambda b: self._lang_menu(b))
        return sb

    # ---------------------------------------------------------------- styling
    def _font(self):
        fam, pt = "JetBrains Mono", 10.0
        try:
            from .sparkterm import mono_font
            fd = mono_font(config.load().get("fonts", {}).get("monospace", "JetBrains Mono 10"))
            fam = (fd.get_family() or fam).split(",")[0].strip()
            if fd.get_size() > 0:
                pt = fd.get_size() / Pango.SCALE
        except Exception:
            pass
        return fam, pt

    def _apply_css(self):
        fam, pt = self._font()
        self._css.load_from_data(self.style.css(fam, pt * self.opt["zoom"]))

    def _reload(self):
        r = super()._reload()
        try:
            self.style = Style(self.th)
            self._apply_css()
            for d in self.docs:
                self.style.apply_tags(d)
                d.view.update_gutter()
                d._apply_region()
                d.view.queue_draw()
        except Exception as e:                       # a broken user theme must not take the editor down
            print("sparkcode: theme reload failed:", e, file=sys.stderr)
        return r

    def on_scheme_change(self):
        """The default re-executes the program, which would lose unsaved text: only do that when nothing is modified."""
        if any(d.dirty for d in self.docs):
            self.say("The colour scheme changes the next time SparkCode starts (you have unsaved changes).", 8000)
            return
        self.save_session()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def zoom(self, delta):
        self.opt["zoom"] = 1.0 if delta == 0 else max(0.6, min(3.0, round(self.opt["zoom"] + delta, 2)))
        self._apply_css()
        for d in self.docs:
            d.view.update_gutter()
            d.view.queue_draw()
        self.save_options()

    # ---------------------------------------------------------------- state helpers
    def cur(self):
        p = self.nb.get_current_page()
        if p < 0:
            return None
        w = self.nb.get_nth_page(p)
        return getattr(w, "doc", None)

    def say(self, text, ms=4500):
        self.status.set_text(text)
        if self._msg_src:
            GLib.source_remove(self._msg_src)
        self._msg_src = GLib.timeout_add(ms, self._clear_msg)

    def _clear_msg(self):
        self._msg_src = 0
        self.status.set_text("")
        return False

    def fire(self, app, path):
        try:
            from . import services
            services.fire([app, path or GLib.get_home_dir()])
        except Exception as e:
            self.say("Could not start %s: %s" % (app, e))

    def copy_text(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.say("Copied the path")

    def update_status(self):
        d = self.cur()
        if d is None:
            for b in (self.s_pos, self.s_indent, self.s_enc, self.s_eol, self.s_lang):
                b.hide()
            self.crumb.set_text("")
            self.set_title("SparkCode" + (" — " + os.path.basename(self.root) if self.root else ""))
            return
        it = d.cursor()
        sel = d.buf.get_selection_bounds()
        txt = "Ln %d, Col %d" % (it.get_line() + 1, it.get_line_offset() + 1)
        if sel:
            txt += "  (%d selected)" % abs(sel[1].get_offset() - sel[0].get_offset())
        self.s_pos.lab.set_text(txt)
        self.s_indent.lab.set_text("Tabs" if d.use_tabs else "Spaces: %d" % d.width)
        self.s_enc.lab.set_text({"utf-8": "UTF-8", "latin-1": "Latin-1", "utf-16": "UTF-16"}.get(d.enc, d.enc) + (" BOM" if d.bom else ""))
        self.s_eol.lab.set_text({"\n": "LF", "\r\n": "CRLF", "\r": "CR"}[d.eol])
        self.s_lang.lab.set_text(d.lang.name + (" (no highlighting: large file)" if d.big else ""))
        for b in (self.s_pos, self.s_indent, self.s_enc, self.s_eol, self.s_lang):
            b.show_all()
        self.crumb.set_text(self._rel(d.path) if d.path else "Untitled")
        self.set_title("%s%s — SparkCode" % ("● " if d.dirty else "", d.name))

    def _rel(self, path):
        if self.root and path.startswith(self.root.rstrip("/") + "/"):
            return os.path.relpath(path, self.root)
        return path.replace(os.path.expanduser("~"), "~")

    def doc_state_changed(self, d):
        if self.cur() is d:
            self.update_status()

    def doc_edited(self, d):
        if self.cur() is d and self.find_rev.get_reveal_child():
            if not self._find_src:
                self._find_src = GLib.timeout_add(220, self._find_refresh)

    def _switched(self, nb, page, num):
        d = getattr(page, "doc", None)
        if d is None:
            return
        GLib.idle_add(self._after_switch, d)

    def _after_switch(self, d):
        if d in self.docs:
            self.update_status()
            if d.path and self.tree.root:
                self.tree.reveal(d.path)
            d._apply_region()
            if self.find_rev.get_reveal_child():
                self.find_update(jump=False)
        return False

    # ---------------------------------------------------------------- opening
    def _startup(self, paths, line):
        folder, files = None, []
        for a in paths:
            p, ln, col = self._parse_arg(a)
            if os.path.isdir(p):
                folder = folder or p
            else:
                files.append((p, ln or line, col))
        if not paths:
            s = self.cfg.get("session", {})
            f = s.get("folder")
            if isinstance(f, str) and os.path.isdir(f):
                folder = f
            lst = s.get("files") if isinstance(s.get("files"), list) else []
            files = [(p, None, None) for p in lst if isinstance(p, str) and os.path.isfile(p)]
        if folder:
            self.open_folder(folder)
        for p, ln, col in files:
            self.open_file(p, ln, col or 1)
        if files and not paths and self.cfg.get("session", {}).get("current") in [p for p, _, _ in files]:
            cur = self.cfg["session"]["current"]
            for d in self.docs:
                if d.path == cur:
                    self.nb.set_current_page(self.nb.page_num(d.sw))

    @staticmethod
    def _parse_arg(a):
        if a.startswith("file://"):
            a = Gio.File.new_for_uri(a).get_path() or a
        a = os.path.expanduser(a)
        if os.path.exists(a):
            return os.path.abspath(a), None, None
        m = re.match(r"^(.*?):(\d+)(?::(\d+))?$", a)
        if m and os.path.exists(m.group(1)):
            return os.path.abspath(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        return os.path.abspath(a), None, None

    def open_folder(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            self.say("Not a folder: " + path)
            return
        self.root = path
        self.tree.set_root(path)
        self.side.show_all()
        self.side.set_visible(True)
        self.opt["sidebar"] = True
        rec = [p for p in (self.cfg.get("recent", {}).get("folders") or []) if isinstance(p, str) and p != path]
        self.cfg.setdefault("recent", {})["folders"] = ([path] + rec)[:8]
        self._fill_recent()
        self._files_cache = None
        if self.stack.get_visible_child_name() == "welcome":
            self.update_status()
        self.say("Opened folder " + path.replace(os.path.expanduser("~"), "~"))

    def open_file(self, path, line=None, col=1, focus=True):
        path = os.path.abspath(path)
        for d in self.docs:
            if d.path == path:
                self.nb.set_current_page(self.nb.page_num(d.sw))
                if line:
                    d.goto(line, col or 1)
                if focus:
                    d.view.grab_focus()
                return d
        d = Doc(self, path)
        if os.path.exists(path):
            try:
                d.load()
            except ValueError as e:
                self.say("Cannot open %s: %s" % (os.path.basename(path), "binary file" if str(e) == "binary" else e))
                d.dispose()
                return None
            except OSError as e:
                self.say("Cannot open %s: %s" % (os.path.basename(path), e.strerror or e))
                d.dispose()
                return None
        else:
            d.lang = synhl.detect(path)
            d.use_tabs, d.width = d.lang.tabs, d.lang.indent
        if len(self.docs) == 1 and not self.docs[0].path and not self.docs[0].dirty and self.docs[0].buf.get_char_count() == 0:
            self._remove_doc(self.docs[0])                            # the untouched "Untitled" tab makes room
        self._add_doc(d)
        if line:
            d.goto(line, col or 1)
        if focus:
            d.view.grab_focus()
        try:
            Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())
        except Exception:
            pass
        return d

    def _add_doc(self, d):
        self.docs.append(d)
        box = Gtk.Box(spacing=5)
        d.tab_dot = Gtk.Label(label="●")
        d.tab_dot.get_style_context().add_class("dirtydot")
        d.tab_dot.set_no_show_all(True)
        d.tab_title = label(d.name, None, 0.0, width_chars=20)
        close = icon_button("close", 9, "Close (Ctrl+W)", None, color=scheme.ink(), pad=4)
        close.connect("clicked", lambda *_: self.close_doc(d))
        box.pack_start(d.tab_dot, False, False, 0)
        box.pack_start(d.tab_title, True, True, 0)
        box.pack_start(close, False, False, 0)
        box.show_all()
        d.tab_dot.set_visible(d.dirty)
        d.tab_title.set_tooltip_text(d.path or "Untitled")
        idx = self.nb.append_page(d.sw, box)
        self.nb.set_tab_reorderable(d.sw, True)
        d.sw.show_all()
        d.view.update_gutter()
        self.stack.set_visible_child_name("editor")
        self.nb.set_current_page(idx)
        self.nb.set_show_tabs(True)
        d._hl_now()

    def _retitle(self, d):
        if d.tab_title is not None:
            d.tab_title.set_text(d.name)
            d.tab_title.set_tooltip_text(d.path or "Untitled")

    def new_file(self, *_):
        d = Doc(self, None)
        d.lang = synhl.PLAIN
        self._add_doc(d)
        d.view.grab_focus()

    def _remove_doc(self, d):
        i = self.nb.page_num(d.sw)
        if i >= 0:
            self.nb.remove_page(i)
        if d in self.docs:
            self.docs.remove(d)
        d.dispose()
        if not self.docs:
            self.stack.set_visible_child_name("welcome")
            self.find_close()
            self.update_status()

    def close_doc(self, d=None, then=None):
        d = d or self.cur()
        if d is None:
            if then:
                then()
            return
        if not d.dirty:
            self._remove_doc(d)
            if then:
                then()
            return

        def decided(what):
            if what == "save":
                if self.save(d):
                    self._remove_doc(d)
                    if then:
                        then()
            elif what == "discard":
                self._remove_doc(d)
                if then:
                    then()
        self.ask_save(d, decided)

    def close_tab(self, *_):
        self.close_doc()

    def next_tab(self, back=False):
        n = self.nb.get_n_pages()
        if n > 1:
            self.nb.set_current_page((self.nb.get_current_page() + (-1 if back else 1)) % n)

    # ---------------------------------------------------------------- dialogs
    def _chooser(self, title, action, verb, start=None):
        d = Gtk.FileChooserDialog(title=title, transient_for=self, action=action)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button(verb, Gtk.ResponseType.OK)
        if start and os.path.isdir(start):
            d.set_current_folder(start)
        return d

    def open_folder_dialog(self, *_):
        d = self._chooser("Open folder", Gtk.FileChooserAction.SELECT_FOLDER, "Open", self.root or GLib.get_home_dir())
        r, p = d.run(), d.get_filename()
        d.destroy()
        if r == Gtk.ResponseType.OK and p:
            self.open_folder(p)

    def open_file_dialog(self, *_):
        d = self._chooser("Open file", Gtk.FileChooserAction.OPEN, "Open", self.root or GLib.get_home_dir())
        d.set_select_multiple(True)
        r, names = d.run(), d.get_filenames()
        d.destroy()
        if r == Gtk.ResponseType.OK:
            for p in names:
                self.open_file(p)

    def _dialog(self, title, size=(440, 10)):
        d = appkit.GlassDialog(title, "sparkcode-dialog", parent=self, size=size)
        d.set_modal(True)
        d.body.set_border_width(14)
        return d

    def prompt(self, title, detail, default, verb, cb, validate=None, select_to=None):
        d = self._dialog(title)
        d.body.pack_start(label(title, "proptitle", 0.0, ellipsize=False), False, False, 0)
        if detail:
            l = label(detail, "muted", 0.0, ellipsize=False)
            l.set_line_wrap(True)
            d.body.pack_start(l, False, False, 0)
        e = Gtk.Entry()
        e.set_text(default)
        d.body.pack_start(e, False, False, 0)
        err = label("", "muted", 0.0, ellipsize=False)
        d.body.pack_start(err, False, False, 0)
        ok = Gtk.Button(label=verb)
        ok.get_style_context().add_class("pill")
        ok.get_style_context().add_class("active")
        row = Gtk.Box()
        row.pack_end(ok, False, False, 0)
        d.body.pack_start(row, False, False, 0)
        d.close_btn.set_label("Cancel")

        def go(*_):
            v = e.get_text().strip()
            msg = validate(v) if validate else None
            if msg:
                err.set_text(msg)
                return
            d.destroy()
            cb(v)
        ok.connect("clicked", go)
        e.connect("activate", go)
        d.show_all()
        d.present()
        GLib.idle_add(lambda: (e.grab_focus(), e.select_region(0, select_to if select_to is not None else -1), False)[2])

    def ask_save(self, doc, then):
        d = self._dialog("Unsaved changes")
        d.body.pack_start(label("Save changes to %s?" % doc.name, "proptitle", 0.0, ellipsize=False), False, False, 0)
        d.body.pack_start(label("Your changes will be lost if you don't save them.", "muted", 0.0, ellipsize=False), False, False, 0)
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.END)
        row.set_margin_top(8)
        done = []

        def pick(what):
            if not done:
                done.append(what)
                d.destroy()
                if what != "cancel":
                    GLib.idle_add(lambda: (then(what), False)[1])
        b1 = Gtk.Button(label="Don't save")
        b2 = Gtk.Button(label="Save")
        for b in (b1, b2):
            b.get_style_context().add_class("pill")
        b2.get_style_context().add_class("active")
        b1.connect("clicked", lambda *_: pick("discard"))
        b2.connect("clicked", lambda *_: pick("save"))
        row.pack_start(b1, False, False, 0)
        row.pack_start(b2, False, False, 0)
        d.body.pack_start(row, False, False, 0)
        d.close_btn.set_label("Cancel")
        d.show_all()
        d.present()
        GLib.idle_add(lambda: (b2.grab_focus(), False)[1])

    def goto_line(self, *_):
        d = self.cur()
        if d is None:
            return

        def check(v):
            return None if re.match(r"^\d+(:\d+)?$", v) else "Type a line number, or line:column"

        def go(v):
            ln, _, col = v.partition(":")
            d.goto(int(ln), int(col or 1))
            d.view.grab_focus()
        self.prompt("Go to line", "1 – %d" % d.buf.get_line_count(), "", "Go", go, check)

    # ---------------------------------------------------------------- saving
    def save(self, doc=None, *_):
        doc = doc if isinstance(doc, Doc) else self.cur()
        if doc is None:
            return False
        if not doc.path:
            return self.save_as(doc)
        try:
            doc.write()
        except OSError as e:
            self.say("Could not save %s: %s" % (doc.name, e.strerror or e), 8000)
            return False
        self._saved(doc)
        return True

    def save_as(self, doc=None, *_):
        doc = doc if isinstance(doc, Doc) else self.cur()
        if doc is None:
            return False
        d = self._chooser("Save as", Gtk.FileChooserAction.SAVE, "Save", os.path.dirname(doc.path) if doc.path else (self.root or GLib.get_home_dir()))
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(doc.name)
        r, p = d.run(), d.get_filename()
        d.destroy()
        if r != Gtk.ResponseType.OK or not p:
            return False
        try:
            doc.write(p)
        except OSError as e:
            self.say("Could not save: %s" % (e.strerror or e), 8000)
            return False
        self._retitle(doc)
        self._saved(doc)
        return True

    def save_all(self, *_):
        for d in list(self.docs):
            if d.dirty and not self.save(d):
                break

    def _saved(self, doc):
        self.say("Saved " + doc.name)
        self.update_status()
        self.tree.refresh()
        try:
            Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(doc.path).get_uri())
        except Exception:
            pass

    def _focus_in(self, w, ev):
        GLib.idle_add(self._check_disk)
        return False

    def _check_disk(self):
        if self.root:
            self.tree.refresh()
        d = self.cur()
        if d is None or not d.path:
            return False
        what = d.changed_on_disk()
        if what is None:
            return False
        if what == "deleted":
            d.missing = True
            self.notice("%s was deleted or moved on disk." % d.name, [("Keep editing", None)])
        elif not d.dirty:
            d.reload()
            self.say("Reloaded %s (changed on disk)" % d.name)
        else:
            def mine():
                d.mtime = os.stat(d.path).st_mtime if os.path.exists(d.path) else None
            self.notice("%s changed on disk, and you have unsaved edits." % d.name, [("Reload from disk", d.reload), ("Keep my version", mine)])
        return False

    def notice(self, text, buttons):
        for c in self.notice_btns.get_children():
            self.notice_btns.remove(c)
        self.notice_lbl.set_text(text)
        for t, cb in buttons:
            b = Gtk.Button(label=t)
            b.get_style_context().add_class("choicebtn")

            def clicked(_b, cb=cb):
                self.notice_box.hide()
                if cb:
                    cb()
            b.connect("clicked", clicked)
            self.notice_btns.pack_start(b, False, False, 0)
        self.notice_box.show_all()

    # ---------------------------------------------------------------- file operations from the tree
    def new_in_folder(self, folder, is_dir):
        def bad(v):
            if not v or "/" in v or v in (".", ".."):
                return "Enter a name without slashes"
            return "That name already exists" if os.path.exists(os.path.join(folder, v)) else None

        def make(v):
            p = os.path.join(folder, v)
            try:
                if is_dir:
                    os.makedirs(p)
                else:
                    open(p, "x").close()
            except OSError as e:
                self.say("Could not create %s: %s" % (v, e.strerror or e))
                return
            self.tree.refresh()
            if self.root and folder != self.root:
                self.tree.reveal(p)
            if not is_dir:
                self.open_file(p)
        self.prompt("New folder" if is_dir else "New file", "in " + self._rel(folder), "", "Create", make, bad)

    def rename_path(self, path):
        base = os.path.basename(path)
        folder = os.path.dirname(path)

        def bad(v):
            if not v or "/" in v:
                return "Enter a name without slashes"
            return "That name already exists" if v != base and os.path.exists(os.path.join(folder, v)) else None

        def go(v):
            if v == base:
                return
            new = os.path.join(folder, v)
            try:
                os.rename(path, new)
            except OSError as e:
                self.say("Could not rename: %s" % (e.strerror or e))
                return
            for d in self.docs:
                if d.path == path or (d.path and d.path.startswith(path + os.sep)):
                    d.path = new + d.path[len(path):]
                    d.lang = synhl.detect(d.path)
                    self._retitle(d)
                    d._hl_now()
            self.tree.refresh()
            self.update_status()
        stem = len(os.path.splitext(base)[0]) or len(base)
        self.prompt("Rename", base, base, "Rename", go, bad, select_to=stem)

    def trash_path(self, path):
        def go():
            try:
                Gio.File.new_for_path(path).trash(None)
            except GLib.Error as e:
                self.say("Could not move to Trash: %s" % e.message, 8000)
                return
            for d in list(self.docs):
                if d.path and (d.path == path or d.path.startswith(path + os.sep)):
                    d.missing = True
            self.tree.refresh()
            self.say("Moved %s to the Trash" % os.path.basename(path))
        GlassConfirm("Move to Trash?", os.path.basename(path), "Move to Trash", go, theme=self.th).show_centered()

    # ---------------------------------------------------------------- quick open
    def _files(self):
        c = getattr(self, "_files_cache", None)
        if c is None or time.time() - c[0] > 20 or c[1] != self.root:
            c = self._files_cache = (time.time(), self.root, cu.list_files(self.root))
        return c[2]

    def quick_open(self, *_):
        if not self.root:
            self.open_folder_dialog()
            if not self.root:
                return
        files = self._files()
        d = self._dialog("Go to file", (580, 10))
        e = Gtk.Entry()
        e.set_placeholder_text("Type part of a file name")
        d.body.pack_start(e, False, False, 0)
        lb = Gtk.ListBox()
        lb.get_style_context().add_class("quick")
        lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(300)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(lb)
        d.body.pack_start(sw, True, True, 0)
        d.close_btn.set_label("Close")

        def fill(*_):
            for c in lb.get_children():
                lb.remove(c)
            q = e.get_text()
            res = cu.fuzzy_filter(q, files, 60) if q else sorted(files, key=lambda p: (p.count("/"), len(p), p))[:60]
            for p in res:
                row = Gtk.ListBoxRow()
                row.relpath = p
                h = Gtk.Box(spacing=10)
                h.pack_start(label(os.path.basename(p), None, 0.0), False, False, 0)
                dn = os.path.dirname(p)
                if dn:
                    h.pack_start(label(dn, "muted", 0.0), True, True, 0)
                row.add(h)
                lb.add(row)
            lb.show_all()
            first = lb.get_row_at_index(0)
            if first:
                lb.select_row(first)

        def move(step):
            r = lb.get_selected_row()
            idx = (r.get_index() if r else -1) + step
            nr = lb.get_row_at_index(max(0, idx))
            if nr:
                lb.select_row(nr)
                y = nr.translate_coordinates(lb, 0, 0)
                adj = sw.get_vadjustment()
                if y:
                    h = nr.get_allocated_height()
                    if y[1] < adj.get_value():
                        adj.set_value(y[1])
                    elif y[1] + h > adj.get_value() + adj.get_page_size():
                        adj.set_value(y[1] + h - adj.get_page_size())

        def choose(*_):
            r = lb.get_selected_row()
            if r is not None:
                d.destroy()
                self.open_file(os.path.join(self.root, r.relpath))

        def key(w, ev):
            if ev.keyval == Gdk.KEY_Down:
                move(1)
                return True
            if ev.keyval == Gdk.KEY_Up:
                move(-1)
                return True
            return False
        e.connect("changed", fill)
        e.connect("key-press-event", key)
        e.connect("activate", choose)
        lb.connect("row-activated", choose)
        fill()
        d.show_all()
        d.present()
        GLib.idle_add(lambda: (e.grab_focus(), False)[1])

    # ---------------------------------------------------------------- find / replace
    def find_open(self, replace=False):
        d = self.cur()
        if d is None:
            return
        self.find_rev.set_reveal_child(True)
        self.rep_row.set_visible(replace)
        sel = d.buf.get_selection_bounds()
        if sel and sel[0].get_line() == sel[1].get_line():
            self.find_entry.set_text(d.buf.get_text(sel[0], sel[1], False))
        self.find_entry.grab_focus()
        self.find_entry.select_region(0, -1)
        self.find_update()

    def replace_open(self, *_):
        self.find_open(True)
        if self.find_entry.get_text():
            self.rep_entry.grab_focus()

    def find_close(self, *_):
        if not hasattr(self, "find_rev"):
            return
        self.find_rev.set_reveal_child(False)
        d = self.cur()
        if d is not None:
            self._clear_find(d)
            d.view.grab_focus()

    def _clear_find(self, d):
        d.matches = []
        d.buf.remove_tag(d.t_find, d.buf.get_start_iter(), d.buf.get_end_iter())
        d.buf.remove_tag(d.t_cur, d.buf.get_start_iter(), d.buf.get_end_iter())

    def _find_refresh(self):
        self._find_src = 0
        self.find_update(jump=False)
        return False

    def find_update(self, *_, jump=True):
        d = self.cur()
        if d is None:
            return
        self._clear_find(d)
        self._rx, err = cu.compile_pattern(self.find_entry.get_text(), self.t_case.get_active(), self.t_regex.get_active(), self.t_word.get_active())
        if self._rx is None:
            self.find_count.set_text("Invalid regex" if err else "")
            return
        text = d.text()
        d.matches = cu.find_all(self._rx, text)
        for s, e in d.matches[:5000]:
            d.buf.apply_tag(d.t_find, d.at(s), d.at(e))
        if not d.matches:
            self.find_count.set_text("No results")
            return
        if jump:
            pos = d.buf.get_selection_bounds()[0].get_offset() if d.buf.get_selection_bounds() else d.cursor().get_offset()
            i = bisect.bisect_left([m[0] for m in d.matches], pos)
            self._show_match(d, i % len(d.matches))
        else:
            self.find_count.set_text("%d found" % len(d.matches))

    def _show_match(self, d, i):
        s, e = d.matches[i]
        d.buf.remove_tag(d.t_cur, d.buf.get_start_iter(), d.buf.get_end_iter())
        d.buf.apply_tag(d.t_cur, d.at(s), d.at(e))
        d.select_span(s, e)
        self._match_i = i
        self.find_count.set_text("%d of %d" % (i + 1, len(d.matches)))

    def find_next(self, back=False):
        d = self.cur()
        if d is None:
            return
        if not self.find_rev.get_reveal_child():
            self.find_open()
            return
        if not d.matches:
            self.find_update()
            return
        sel = d.buf.get_selection_bounds()
        starts = [m[0] for m in d.matches]
        if back:
            pos = sel[0].get_offset() if sel else d.cursor().get_offset()
            i = bisect.bisect_left(starts, pos) - 1
        else:
            pos = sel[1].get_offset() if sel else d.cursor().get_offset()
            i = bisect.bisect_left(starts, pos)
        self._show_match(d, i % len(d.matches))

    def _find_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.find_close()
            return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if w is self.rep_entry:
                self.replace_one()
            else:
                self.find_next(bool(ev.state & Gdk.ModifierType.SHIFT_MASK))
            return True
        return False

    def replace_one(self, *_):
        d = self.cur()
        if d is None or self._rx is None or not d.matches:
            return
        sel = d.buf.get_selection_bounds()
        span = (sel[0].get_offset(), sel[1].get_offset()) if sel else None
        if span not in d.matches:
            self.find_next()
            return
        text = d.text()
        new = cu.expand(self._rx, text, span, self.rep_entry.get_text(), self.t_regex.get_active())
        with d.group():
            d.buf.delete(d.at(span[0]), d.at(span[1]))
            d.buf.insert(d.at(span[0]), new)
        d.buf.place_cursor(d.at(span[0] + len(new)))
        self.find_update()

    def replace_all(self, *_):
        d = self.cur()
        if d is None or self._rx is None:
            return
        text = d.text()
        matches = cu.find_all(self._rx, text)
        if not matches:
            return
        repl = self.rep_entry.get_text()
        regex = self.t_regex.get_active()
        with d.group():
            for s, e in reversed(matches):
                new = cu.expand(self._rx, text, (s, e), repl, regex)
                d.buf.delete(d.at(s), d.at(e))
                d.buf.insert(d.at(s), new)
        self.find_update(jump=False)
        self.say("Replaced %d occurrence%s" % (len(matches), "" if len(matches) == 1 else "s"))

    # ---------------------------------------------------------------- menus
    def _popup_below(self, btn, items, width=230):
        win = btn.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        m = GlassMenu(items, light=True, theme=self.th, min_width=width)
        m.popup_at(ox + a.x, oy + a.y + a.height + 4)

    def _popup_above(self, btn, items, width=200):
        win = btn.get_window()
        if win is None:
            return
        _, ox, oy = win.get_origin()
        a = btn.get_allocation()
        m = GlassMenu(items, light=True, theme=self.th, min_width=width)
        m.show_all()
        h = m.get_preferred_height()[1]
        m.popup_at(ox + a.x, oy + a.y - h - 6)

    def _main_menu_items(self):
        o = self.opt
        d = self.cur()
        has = d is not None

        def toggle(key, after=None):
            def f():
                self.opt[key] = not self.opt[key]
                self.save_options()
                if after:
                    after()
            return f
        return [
            ("itemi", None, "New file", self.new_file, True, "Ctrl+N"),
            ("itemi", None, "Open file…", self.open_file_dialog, True, "Ctrl+O"),
            ("itemi", None, "Open folder…", self.open_folder_dialog, True, "Ctrl+Shift+O"),
            ("itemi", None, "Go to file…", self.quick_open, True, "Ctrl+P"),
            ("sep",),
            ("itemi", None, "Save", self.save, has, "Ctrl+S"),
            ("itemi", None, "Save as…", self.save_as, has, "Ctrl+Shift+S"),
            ("item", "Save all", self.save_all, any(x.dirty for x in self.docs)),
            ("itemi", None, "Close tab", self.close_tab, has, "Ctrl+W"),
            ("sep",),
            ("itemi", None, "Find…", self.find_open, has, "Ctrl+F"),
            ("itemi", None, "Replace…", self.replace_open, has, "Ctrl+H"),
            ("itemi", None, "Go to line…", self.goto_line, has, "Ctrl+G"),
            ("itemi", None, "Toggle comment", lambda: self.cur().toggle_comment(), has, "Ctrl+/"),
            ("sep",),
            ("head", "View"),
            ("check", "Sidebar", o["sidebar"], self.toggle_sidebar),
            ("check", "Line numbers", o["numbers"], toggle("numbers", self._relayout)),
            ("check", "Word wrap", o["wrap"], toggle("wrap", self._relayout)),
            ("check", "Highlight current line", o["hl_line"], toggle("hl_line", self._relayout)),
            ("check", "Show hidden files", o["hidden"], toggle("hidden", self._reload_tree)),
            ("itemi", None, "Zoom in", lambda: self.zoom(0.1), True, "Ctrl++"),
            ("itemi", None, "Zoom out", lambda: self.zoom(-0.1), True, "Ctrl+-"),
            ("itemi", None, "Reset zoom", lambda: self.zoom(0), True, "Ctrl+0"),
            ("sep",),
            ("head", "Editing"),
            ("check", "Auto-close brackets and quotes", o["pairs"], toggle("pairs")),
            ("check", "Trim trailing spaces on save", o["trim"], toggle("trim")),
            ("check", "Ensure final newline on save", o["final_nl"], toggle("final_nl")),
        ]

    def _reload_tree(self):
        if self.root:
            self.tree.set_root(self.root)

    def _relayout(self):
        for d in self.docs:
            d.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if self.opt["wrap"] else Gtk.WrapMode.NONE)
            d.view.update_gutter()
            d.view.queue_draw()

    def _lang_menu(self, btn):
        d = self.cur()
        if d is None:
            return
        self._popup_above(btn, [("check", l.name, l is d.lang, lambda l=l: d.set_lang(l)) for l in synhl.LANGS], 190)

    def _indent_menu(self, btn):
        d = self.cur()
        if d is None:
            return

        def setw(tabs, w):
            def f():
                d.use_tabs = tabs
                d.width = w or d.width
                self.update_status()
            return f
        items = [("check", "Spaces: %d" % w, not d.use_tabs and d.width == w, setw(False, w)) for w in (2, 3, 4, 8)]
        items += [("sep",), ("check", "Tabs", d.use_tabs, setw(True, 0))]
        self._popup_above(btn, items, 170)

    def _eol_menu(self, btn):
        d = self.cur()
        if d is None:
            return

        def sete(e):
            def f():
                d.eol = e
                d.set_dirty(True)
                self.update_status()
            return f
        self._popup_above(btn, [("check", n, d.eol == e, sete(e)) for n, e in (("LF (Unix)", "\n"), ("CRLF (Windows)", "\r\n"), ("CR (old Mac)", "\r"))], 170)

    def open_terminal(self, *_):
        d = self.cur()
        self.fire("sparkterm", self.root or (os.path.dirname(d.path) if d is not None and d.path else None))

    def toggle_sidebar(self, *_):
        self.opt["sidebar"] = not self.opt["sidebar"]
        self.side.set_visible(self.opt["sidebar"])
        self.save_options()

    # ---------------------------------------------------------------- keys
    def _key(self, w, ev):
        st = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl, shift = bool(st & Gdk.ModifierType.CONTROL_MASK), bool(st & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(st & Gdk.ModifierType.MOD1_MASK)
        kv = Gdk.keyval_to_lower(ev.keyval)
        d = self.cur()
        in_entry = isinstance(self.get_focus(), Gtk.Entry)
        if kv == Gdk.KEY_Escape and not st and self.find_rev.get_reveal_child():
            self.find_close()
            return True
        if kv == Gdk.KEY_F3 and not ctrl and not alt:
            self.find_next(shift)
            return True
        if not ctrl or alt:
            return False
        if kv in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.zoom(0.1); return True
        if kv in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom(-0.1); return True
        if kv in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.zoom(0); return True
        if kv in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.next_tab(shift or kv == Gdk.KEY_ISO_Left_Tab); return True
        table = {(Gdk.KEY_s, False): self.save, (Gdk.KEY_s, True): self.save_as, (Gdk.KEY_o, False): self.open_file_dialog,
                 (Gdk.KEY_o, True): self.open_folder_dialog, (Gdk.KEY_n, False): self.new_file, (Gdk.KEY_w, False): self.close_tab,
                 (Gdk.KEY_f, False): self.find_open, (Gdk.KEY_h, False): self.replace_open, (Gdk.KEY_g, False): self.goto_line,
                 (Gdk.KEY_p, False): self.quick_open, (Gdk.KEY_b, False): self.toggle_sidebar, (Gdk.KEY_grave, False): self.open_terminal}
        fn = table.get((kv, shift))
        if fn is not None:
            fn()
            return True
        if d is None or in_entry:
            return False
        edit = {(Gdk.KEY_z, False): d.do_undo, (Gdk.KEY_z, True): d.do_redo, (Gdk.KEY_y, False): d.do_redo, (Gdk.KEY_slash, False): d.toggle_comment,
                (Gdk.KEY_d, True): d.duplicate, (Gdk.KEY_k, True): d.delete_lines, (Gdk.KEY_bracketright, False): d.indent,
                (Gdk.KEY_bracketleft, False): d.outdent}
        fn = edit.get((kv, shift))
        if fn is not None and d.view.has_focus():
            fn()
            return True
        return False

    # ---------------------------------------------------------------- drag and drop
    def _dropped(self, w, ctx, x, y, data, info, t):
        for uri in data.get_uris() or []:
            p = Gio.File.new_for_uri(uri).get_path()
            if p:
                (self.open_folder if os.path.isdir(p) else self.open_file)(p)
        ctx.finish(True, False, t)

    # ---------------------------------------------------------------- closing and settings
    def save_options(self):
        self.cfg = config.load(CFG)
        self.opt["sidebar_w"] = self.paned.get_position() if self.side.get_visible() and self.paned.get_position() > 100 else self.opt["sidebar_w"]
        self.cfg["view"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.opt.items()}
        self._write_cfg()

    def _write_cfg(self):
        try:
            config.save(self.cfg, CFG)
        except OSError:
            pass

    def save_session(self):
        self.cfg = {**config.load(CFG), "recent": self.cfg.get("recent", {})}
        self.cfg["view"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.opt.items()}
        cur = self.cur()
        files = [d.path for d in self.docs if d.path and os.path.exists(d.path)]
        self.cfg["session"] = {"folder": self.root or "", "files": files, "current": cur.path if cur is not None and cur.path else ""}
        self._write_cfg()

    def _on_delete_event(self, w, ev):
        dirty = [d for d in self.docs if d.dirty]
        if not dirty:
            self.save_options()
            self.save_session()
            return False

        def step():
            nxt = [d for d in self.docs if d.dirty]
            if not nxt:
                self.save_session()
                self.destroy()
                return
            d = nxt[0]
            self.nb.set_current_page(self.nb.page_num(d.sw))
            self.close_doc(d, then=step)
        step()
        return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return
    paths, line = [], None
    for a in argv:
        if a.startswith("+") and a[1:].isdigit():
            line = int(a[1:])
        else:
            paths.append(a)
    appkit.run(SparkCode(paths, line))


if __name__ == "__main__":
    main()
