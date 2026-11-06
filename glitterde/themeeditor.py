"""Theme editor: build your own glitterDE themes (colours, glass, blur, corners, light/dark) with a live preview on the real desktop.

A theme is a folder with theme.toml + palette.toml in ~/.local/share/glitterde/themes/<id>/. The editor writes exactly that,
so anything it makes can be shared by copying the folder. Editing a built-in theme saves a copy; editing your own theme edits it in place.
"""
import copy
import os
import re
import shutil

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from . import appkit, config, pickers, scheme, tokens
from .menus import ChoiceButton
from .widgets import label

USER_DIR = os.path.expanduser("~/.local/share/glitterde/themes")

# (title, palette path) - colours the editor offers
COLOURS = [("Accent", ("accent", "primary")), ("Pink accent", ("accent", "pink")), ("Blue accent", ("accent", "blue")),
           ("Panel glass", ("materials", "panel", "tint")), ("Dock glass", ("materials", "dock", "tint")),
           ("Card glass", ("materials", "card", "tint")), ("Window glass", ("materials", "window_glass", "tint")),
           ("Light window", ("materials", "window_light", "tint")), ("Dark window", ("materials", "window_dark", "tint")),
           ("Text on light", ("text", "on_light"))]

# ------------------------------------------------------------------ toml writer
def _v(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_v(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    for ch, esc in (("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t")):        # a raw newline in a theme name would make the file invalid TOML
        s = s.replace(ch, esc)
    return '"' + s + '"'


def dump_toml(d):
    lines = []

    def emit(prefix, tbl):
        scal = {k: v for k, v in tbl.items() if not isinstance(v, dict)}
        subs = {k: v for k, v in tbl.items() if isinstance(v, dict)}
        if prefix and scal:
            lines.append("[%s]" % prefix)
        lines.extend("%s = %s" % (k, _v(v)) for k, v in scal.items())
        if scal:
            lines.append("")
        for k, v in subs.items():
            emit(prefix + "." + k if prefix else k, v)
    emit("", d)
    return "\n".join(lines) + "\n"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "my-theme"


def hex_of(rgba):
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(1, v)) * 255)) for v in rgba[:3])


def is_user_theme(theme):
    root = os.path.abspath(USER_DIR)
    return os.path.abspath(theme.dir).startswith(root + os.sep)       # not just a prefix: ".../themes-old" is not inside ".../themes"


def delete_user_theme(theme):
    if is_user_theme(theme):
        shutil.rmtree(theme.dir, ignore_errors=True)
        if config.load().get("appearance", {}).get("theme") == theme.theme_id:
            config.set("appearance", "theme", "trans-pride")


def write_theme(tid, name, meta, pal):
    d = os.path.join(USER_DIR, tid)
    os.makedirs(d, exist_ok=True)
    meta = copy.deepcopy(meta)
    meta.update(schema=1, id=tid, name=name, author="You", version="1.0.0")
    with open(os.path.join(d, "theme.toml"), "w", encoding="utf-8") as f:
        f.write("# glitterDE theme made with the SparkSettings theme editor\n" + dump_toml(meta))
    with open(os.path.join(d, "palette.toml"), "w", encoding="utf-8") as f:
        f.write("# %s\n# Semantic palette + materials\n" % name + dump_toml(pal))
    return d


def _get(d, path):
    for k in path:
        d = d[k]
    return d


def _set(d, path, v):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = v


class ThemeEditor(appkit.GlassDialog):
    """Glass dialog (follows the colour scheme like every Spark window). Save keeps the theme; Cancel, Esc and the window's close button all put
    everything back as it was."""

    def __init__(self, parent, base, on_done, new_copy=False):
        super().__init__("Theme editor", getattr(parent, "wm_class", None) or "sparksettings", parent=parent, size=(480, 660))
        self._done = False
        self.base, self.on_done = base, on_done
        self.prev_theme = config.load().get("appearance", {}).get("theme", "trans-pride")
        self.prev_accent = config.load().get("accent", {}).get("primary")
        self.inplace = is_user_theme(base) and not new_copy
        self.meta, self.pal = copy.deepcopy(base.meta), copy.deepcopy(base.pal)
        wp = base.wallpaper()
        self.meta.setdefault("wallpaper", {})["default"] = wp if os.path.isabs(wp) else os.path.join(base.root, wp)   # a copy must still find its wallpaper
        self.meta.setdefault("appearance", {})
        self.name0 = base.meta.get("name", base.theme_id)
        self.tid = base.theme_id if self.inplace else slug(self.name0 + " custom")
        while not self.inplace and os.path.exists(os.path.join(USER_DIR, self.tid)):
            self.tid += "-2"
        self.base_op = {m: v["opacity"] for m, v in self.pal.get("materials", {}).items()}
        self.base_blur = {m: v["blur"] for m, v in self.pal.get("materials", {}).items()}
        self._t = None
        self.created = not self.inplace
        self.backup = {}
        if self.inplace:                                                    # Cancel must restore what was on disk
            for fn in ("theme.toml", "palette.toml"):
                with open(os.path.join(base.dir, fn), "rb") as f:
                    self.backup[fn] = f.read()
        try:                                                                # GlassDialog closes (and would keep the preview) on Escape: Escape must cancel properly
            sid = GObject.signal_lookup("key-press-event", Gtk.Widget)
            GObject.signal_handlers_disconnect_matched(self, GObject.SignalMatchType.ID, sid, 0, None, None, None)
        except Exception:
            pass
        self.connect("key-press-event", lambda w, ev: (self._finish(False), True)[1] if ev.keyval == Gdk.KEY_Escape else False)
        self.connect("delete-event", lambda *_: (self._finish(False), True)[1])
        save = Gtk.Button(label="Save theme")
        save.get_style_context().add_class("pill"); save.get_style_context().add_class("active")
        save.connect("clicked", lambda *_: self._finish(True))
        row = self.close_btn.get_parent()
        row.remove(self.close_btn)
        cancel = Gtk.Button(label="Cancel"); cancel.get_style_context().add_class("pill")
        cancel.connect("clicked", lambda *_: self._finish(False))
        row.pack_end(save, False, False, 6); row.pack_end(cancel, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + m)(16)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(box)
        self.get_content_area().pack_start(sw, True, True, 0)

        self.name = Gtk.Entry(); self.name.set_text(self.name0 if self.inplace else self.name0 + " (custom)")
        self.name.connect("changed", lambda *_: self._changed())
        box.pack_start(label("Name", "h2"), False, False, 0); box.pack_start(self.name, False, False, 0)
        mode = ChoiceButton([("light", "Light apps"), ("dark", "Dark apps")], light=True)
        mode.set_active_id(self.meta["appearance"].get("app_scheme", "light")); mode.connect("changed", lambda c: self._set_meta("app_scheme", c.get_active_id()))
        r = Gtk.Box(spacing=10); r.pack_start(label("App colour scheme"), True, True, 0); r.pack_end(mode, False, False, 0)
        box.pack_start(r, False, False, 4)

        box.pack_start(label("Colours", "h2"), False, False, 4)
        for title, path in COLOURS:
            try:
                cur = tokens.hex_rgba(_get(self.pal, path))
            except (KeyError, TypeError):
                continue
            b = pickers.ColorButton.new_with_rgba(Gdk.RGBA(*cur[:3], 1.0))
            b.connect("color-set", lambda bt, p=path: self._colour(p, bt.get_rgba()))
            row = Gtk.Box(spacing=10); row.pack_start(label(title), True, True, 0); row.pack_end(b, False, False, 0)
            box.pack_start(row, False, False, 2)

        box.pack_start(label("Glass", "h2"), False, False, 4)
        self._slider(box, "Glass opacity", 0.5, 1.6, 0.05, 1.0, lambda v: self._glass("opacity", v))
        self._slider(box, "Blur strength", 0, 2.0, 0.1, 1.0, lambda v: self._glass("blur", v))
        self._slider(box, "Corner roundness", 0, 1.5, 0.1, float(self.meta["appearance"].get("radius_scale", 1.0)),
                     lambda v: self._set_meta("radius_scale", round(v, 2)))
        note = label("Changes appear on your desktop straight away. Cancel puts everything back; Save keeps the theme.", "muted", ellipsize=False)
        note.set_line_wrap(True); note.set_max_width_chars(48); note.set_xalign(0); note.set_margin_top(6)
        box.pack_start(note, False, False, 0)
        self.show_all()

    def _slider(self, box, title, lo, hi, step, val, cb):
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step); sc.set_value(val); sc.set_digits(2); sc.set_size_request(190, -1)
        sc.set_value_pos(Gtk.PositionType.RIGHT); sc.connect("value-changed", lambda s: cb(s.get_value()))
        row = Gtk.Box(spacing=10); row.pack_start(label(title), True, True, 0); row.pack_end(sc, False, False, 0)
        box.pack_start(row, False, False, 2)

    def _colour(self, path, rgba):
        _set(self.pal, path, hex_of((rgba.red, rgba.green, rgba.blue)))
        if path == ("accent", "primary"):
            config.remove("accent")                                                # an accent picked on the Colours page would hide this one
        self._changed()

    def _glass(self, what, factor):
        for m, v in self.pal.get("materials", {}).items():
            if what == "opacity":
                v["opacity"] = round(max(0.05, min(0.98, self.base_op[m] * factor)), 3)
            else:
                v["blur"] = round(self.base_blur[m] * factor, 1)
        self._changed()

    def _set_meta(self, key, v):
        self.meta["appearance"][key] = v
        self._changed()

    def _changed(self):
        if self._t:
            GLib.source_remove(self._t)
        self._t = GLib.timeout_add(250, self._apply)

    def _apply(self):
        self._t = None
        name = self.name.get_text().strip() or "My theme"
        write_theme(self.tid, name, self.meta, self.pal)
        config.set("appearance", "theme", self.tid)
        return False

    def _finish(self, save):
        if self._done:
            return
        self._done = True
        if self._t:
            GLib.source_remove(self._t); self._t = None
        if save:
            self._apply()
        else:
            if self.created:
                shutil.rmtree(os.path.join(USER_DIR, self.tid), ignore_errors=True)
            for fn, data in self.backup.items():
                with open(os.path.join(self.base.dir, fn), "wb") as f:
                    f.write(data)
            restore = {"appearance": {"theme": self.prev_theme}}
            if self.prev_accent:
                restore["accent"] = {"primary": self.prev_accent}
            config.update(restore)
        self.destroy()
        self.on_done()
