"""SparkShot: the Screenshot app. Pick what to capture, an optional delay, and go; the result appears with a preview and quick actions."""
import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import appkit, config, scheme
from .menus import ChoiceButton
from .screenshot import Selector, active_window_rect, crop, grab_screen, notify
from .widgets import Ico, label

CSS = b"""
.shotgo { background-image: linear-gradient(135deg, #ff8fd2, #a98bff); color: #ffffff; border: none; border-radius: 999px; padding: 11px 34px; min-height: 0; box-shadow: 0 6px 18px rgba(169,139,255,0.45); }
.shotgo label { font-size: 15px; font-weight: 700; color: #ffffff; }
.shotgo:hover { background-image: linear-gradient(135deg, #ffa3dc, #b9a0ff); }
.shotmode { padding: 16px 8px; border-radius: 18px; }
.shotmode label.t { font-weight: 700; }
.shotmode label.d { font-size: 11px; }
.shotprev { border-radius: 14px; padding: 6px; background-color: rgba(255,255,255,0.35); }
.shottitle { font-size: 22px; font-weight: 800; }
.shotact { border-radius: 12px; padding: 7px 14px; }
"""

MODES = [("full", "monitor", "Screen", "Everything you see"), ("area", "cursor", "Area", "Drag a rectangle"), ("window", "windows", "Window", "The window you were using")]


def pictures_dir():
    d = os.path.join(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures"), "Screenshots")
    os.makedirs(d, exist_ok=True)
    return d


class SparkShot(appkit.GlassWindow):
    def __init__(self, mode="full"):
        super().__init__("Screenshot", "sparkshot", "window_light", (520, 560))
        p = Gtk.CssProvider(); p.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 12)
        self.mode, self.delay, self.copy = mode, 0, False
        self.folder = config.load().get("screenshot", {}).get("folder") or pictures_dir()
        self.shot = self.path = None
        self.prev_rect = active_window_rect()                    # the window in use before this one took the focus
        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE); self.stack.set_transition_duration(200)
        self.stack.add_named(self._setup_page(), "setup")
        self.result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.add_named(self.result_box, "result")
        self.add(self.stack)
        self.connect("key-press-event", self._key)

    # ------------------------------------------------------------ pages
    def _pad(self, w, m=22):
        box = Gtk.Box(); box.set_margin_top(m); box.set_margin_bottom(m); box.set_margin_start(m); box.set_margin_end(m); box.pack_start(w, True, True, 0)
        return box

    def _setup_page(self):
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        v.pack_start(label("Screenshot", "shottitle"), False, False, 0)
        row = Gtk.Box(spacing=10, homogeneous=True)
        self.tiles = {}
        for mid, icn, title, desc in MODES:
            b = Gtk.ToggleButton(); b.set_mode(False); ctx = b.get_style_context(); ctx.add_class("tilebtn"); ctx.add_class("shotmode")
            c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            ico = Ico(icn, 30, scheme.ink(), 1.5); c.pack_start(ico, False, False, 4)
            c.pack_start(label(title, "t", 0.5), False, False, 0)
            d = label(desc, "muted d", 0.5, ellipsize=False); d.set_line_wrap(True); d.set_justify(Gtk.Justification.CENTER); d.set_max_width_chars(16)
            c.pack_start(d, False, False, 0)
            b.add(c); b.set_active(mid == self.mode)
            b.connect("toggled", lambda bt, m=mid: self._pick(m) if bt.get_active() else None)
            self.tiles[mid] = b; row.pack_start(b, True, True, 0)
        v.pack_start(row, False, False, 0)

        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); opts.get_style_context().add_class("card2")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(inner, "set_margin_" + m)(14)
        opts.pack_start(inner, False, False, 0)

        def line(text, w):
            r = Gtk.Box(spacing=12); r.pack_start(label(text), True, True, 0); r.pack_end(w, False, False, 0); inner.pack_start(r, False, False, 0)
        dl = ChoiceButton([("0", "No delay"), ("3", "3 seconds"), ("5", "5 seconds"), ("10", "10 seconds")], light=True)
        dl.set_active_id("0"); dl.connect("changed", lambda c: setattr(self, "delay", int(c.get_active_id())))
        line("Delay", dl)
        sw = Gtk.Switch(); sw.set_valign(Gtk.Align.CENTER); sw.connect("notify::active", lambda s, _p: setattr(self, "copy", s.get_active()))
        line("Also copy to clipboard", sw)
        self.folder_btn = Gtk.Button(label=self._short(self.folder)); self.folder_btn.get_style_context().add_class("clear")
        self.folder_btn.connect("clicked", lambda *_: self._choose_folder())
        line("Save to", self.folder_btn)
        v.pack_start(opts, False, False, 0)

        go = Gtk.Button(); go.get_style_context().add_class("shotgo"); go.set_halign(Gtk.Align.CENTER)
        go.add(label("Take screenshot", None, 0.5)); go.connect("clicked", lambda *_: self.capture())
        v.pack_end(go, False, False, 4)
        hint = label("Enter to capture  ·  1 2 3 pick a mode", "muted", 0.5, ellipsize=False); v.pack_end(hint, False, False, 0)
        return self._pad(v)

    def _short(self, p):
        home = os.path.expanduser("~")
        return ("~" + p[len(home):]) if p.startswith(home) else p

    def _choose_folder(self):
        d = Gtk.FileChooserDialog(title="Save screenshots to", transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button("Choose", Gtk.ResponseType.OK); d.set_current_folder(self.folder)
        if d.run() == Gtk.ResponseType.OK and d.get_filename():
            self.folder = d.get_filename(); config.set("screenshot", "folder", self.folder); self.folder_btn.set_label(self._short(self.folder))
        d.destroy()

    def _pick(self, mode):
        self.mode = mode
        for m, b in self.tiles.items():
            if m != mode and b.get_active():
                b.set_active(False)
            if m == mode and not b.get_active():
                b.set_active(True)

    def _key(self, w, ev):
        k = ev.keyval
        if self.stack.get_visible_child_name() == "setup":
            if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.capture()
            elif k in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3):
                self._pick(MODES[k - Gdk.KEY_1][0])
            else:
                return False
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.stack.set_visible_child_name("setup"); return True
        return False

    # ------------------------------------------------------------ capture
    def capture(self):
        self.hide()
        if self.delay:
            notify("Screenshot in %d seconds" % self.delay, "")
        GLib.timeout_add(int(self.delay * 1000) + 500, self._grab)       # long enough for this window to be gone from the picture

    def _grab(self):
        full = grab_screen()
        if self.mode == "window":
            r = active_window_rect() or self.prev_rect
            self._done(crop(full, *r) if r else full)
        elif self.mode == "area":
            Selector(full, lambda r: self._done(crop(full, *r) if r else None)).show_all()
        else:
            self._done(full)
        return False

    def _done(self, pb):
        if pb is None:
            self.show_all(); self.present(); return
        self.shot = pb
        self.path = os.path.join(self.folder, time.strftime("Screenshot_%Y-%m-%d_%H-%M-%S.png"))
        os.makedirs(self.folder, exist_ok=True)
        pb.savev(self.path, "png", [], [])
        if self.copy:
            self._copy()
        self._result_page()
        self.show_all(); self.stack.set_visible_child_name("result"); self.present()

    def _copy(self, *_):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD); cb.set_image(self.shot); cb.store()
        self.status.set_text("Copied to clipboard")

    # ------------------------------------------------------------ result
    def _result_page(self):
        for ch in self.result_box.get_children():
            self.result_box.remove(ch)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        head = Gtk.Box(spacing=10)
        head.pack_start(Ico("check", 18, scheme.ink(), 2.0), False, False, 0)
        head.pack_start(label("Saved", "shottitle"), False, False, 0)
        v.pack_start(head, False, False, 0)
        pb = self.shot
        k = min(1.0, 440.0 / pb.get_width(), 280.0 / pb.get_height())
        th = pb.scale_simple(max(1, int(pb.get_width() * k)), max(1, int(pb.get_height() * k)), GdkPixbuf.InterpType.BILINEAR)
        fr = Gtk.Box(); fr.get_style_context().add_class("shotprev"); fr.set_halign(Gtk.Align.CENTER)
        fr.pack_start(Gtk.Image.new_from_pixbuf(th), False, False, 0)
        v.pack_start(fr, False, False, 0)
        try:
            size = GLib.format_size(os.path.getsize(self.path))
        except OSError:
            size = ""
        info = label("%s\n%d × %d  ·  %s" % (os.path.basename(self.path), pb.get_width(), pb.get_height(), size), "muted", 0.5, ellipsize=False)
        info.set_justify(Gtk.Justification.CENTER); v.pack_start(info, False, False, 0)
        self.status = label("", "muted", 0.5, ellipsize=False); v.pack_start(self.status, False, False, 0)
        acts = Gtk.Box(spacing=8); acts.set_halign(Gtk.Align.CENTER)
        for text, cb in (("Copy", self._copy), ("Show in folder", self._show), ("Save as…", self._save_as), ("Delete", self._delete)):
            b = Gtk.Button(label=text); b.get_style_context().add_class("clear"); b.get_style_context().add_class("shotact"); b.connect("clicked", cb)
            acts.pack_start(b, False, False, 0)
        v.pack_start(acts, False, False, 0)
        again = Gtk.Button(); again.get_style_context().add_class("shotgo"); again.set_halign(Gtk.Align.CENTER)
        again.add(label("New screenshot", None, 0.5)); again.connect("clicked", lambda *_: self.stack.set_visible_child_name("setup"))
        v.pack_end(again, False, False, 4)
        self.result_box.pack_start(self._pad(v), True, True, 0)
        self.result_box.show_all()

    def _show(self, *_):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(os.path.dirname(self.path)).get_uri(), None)
        except GLib.Error:
            pass

    def _save_as(self, *_):
        d = Gtk.FileChooserDialog(title="Save as", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); d.add_button("Save", Gtk.ResponseType.OK)
        d.set_do_overwrite_confirmation(True); d.set_current_name(os.path.basename(self.path)); d.set_current_folder(os.path.dirname(self.path))
        if d.run() == Gtk.ResponseType.OK and d.get_filename():
            self.shot.savev(d.get_filename(), "png", [], [])
            self.status.set_text("Saved a copy to %s" % self._short(d.get_filename()))
        d.destroy()

    def _delete(self, *_):
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.stack.set_visible_child_name("setup")


def main(mode="full"):
    appkit.run(SparkShot(mode))
    return 0
