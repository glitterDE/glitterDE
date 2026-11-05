"""Publish the desktop's cursor theme to everything that is not the shell itself."""
import os
import shlex
import shutil
import subprocess
import sys

from . import config

DEFAULT_THEME = "glitterde"
MARK = "# written by glitterDE\n"


def cursor():
    """(theme, size or None) the user chose, else the glitterDE theme and the library's own default size."""
    d = config.load().get("cursor", {})
    theme = config.cursor_theme() or os.environ.get("XCURSOR_THEME") or DEFAULT_THEME
    try:
        size = int(d["size"]) if d.get("size") else (int(os.environ["XCURSOR_SIZE"]) if os.environ.get("XCURSOR_SIZE") else None)
    except (TypeError, ValueError):
        size = None
    return theme, size


def search_path(here=None):
    """XCURSOR_PATH that also finds themes shipped inside a source checkout / unpacked tarball (…/share/icons)."""
    here = here or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(here, "share", "icons")
    base = [os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons"), "/usr/local/share/icons", "/usr/share/icons", "/usr/share/pixmaps"]
    return ":".join(([bundled] if os.path.isdir(bundled) else []) + base)


def env_lines():
    theme, size = cursor()
    out = ["XCURSOR_THEME=%s" % shlex.quote(theme), "XCURSOR_PATH=%s" % shlex.quote(os.environ.get("XCURSOR_PATH") or search_path())]
    if size:
        out.append("XCURSOR_SIZE=%d" % size)
    return ["export " + o for o in out]


def _write(path, text):
    try:
        if os.path.exists(path) and open(path).read() == text:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    except OSError:
        pass


def _ini(folder, kv):
    from gi.repository import GLib
    f = os.path.join(GLib.get_user_config_dir(), folder, "settings.ini")
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(f, GLib.KeyFileFlags.NONE)
    except GLib.Error:
        pass
    changed = False
    for k, v in kv.items():
        try:
            if kf.get_string("Settings", k) == str(v):
                continue
        except GLib.Error:
            pass
        kf.set_string("Settings", k, str(v)); changed = True
    if changed:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        kf.save_to_file(f)


def _xresources(theme, size):
    """Merge Xcursor.* into the X server's resource database (xrdb if present, else python-xlib)."""
    text = "Xcursor.theme: %s\n" % theme + ("Xcursor.size: %d\n" % size if size else "")
    try:
        if shutil.which("xrdb"):
            subprocess.run(["xrdb", "-merge"], input=text.encode(), timeout=4, stderr=subprocess.DEVNULL)
            return
        from Xlib import display, X
        d = display.Display(); root = d.screen().root
        a = d.intern_atom("RESOURCE_MANAGER")
        p = root.get_full_property(a, X.AnyPropertyType)
        cur = p.value.decode("utf-8", "replace") if p else ""
        keep = [ln for ln in cur.split("\n") if ln and not ln.startswith(("Xcursor.theme:", "Xcursor.size:"))]
        root.change_property(a, X.XA_STRING, 8, ("\n".join(keep + text.strip().split("\n")) + "\n").encode())
        d.sync(); d.close()
    except Exception:
        pass


def apply_cursor(theme=None, size=None, process_env=True):
    """Write the cursor theme everywhere (see the module doc). Safe to call repeatedly; every step is best effort."""
    t, s = cursor()
    theme, size = theme or t, size or s
    if process_env:
        os.environ["XCURSOR_THEME"] = theme
        os.environ.setdefault("XCURSOR_PATH", search_path())
        if size:
            os.environ["XCURSOR_SIZE"] = str(size)
    idx = "[Icon Theme]\nName=Default\nComment=glitterDE cursor theme\nInherits=%s\n" % theme
    for d in (os.path.expanduser("~/.icons/default"), os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "icons", "default")):
        _write(os.path.join(d, "index.theme"), idx)
    try:
        kv = {"gtk-cursor-theme-name": theme}
        if size:
            kv["gtk-cursor-theme-size"] = size
        for folder in ("gtk-3.0", "gtk-4.0"):
            _ini(folder, kv)
    except Exception:
        pass
    try:
        from gi.repository import Gio
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None and src.lookup("org.gnome.desktop.interface", True) is not None:
            st = Gio.Settings.new("org.gnome.desktop.interface")
            st.set_string("cursor-theme", theme)
            if size:
                st.set_int("cursor-size", size)
            Gio.Settings.sync()
    except Exception:
        pass
    if os.environ.get("DISPLAY"):
        _xresources(theme, size)
    pairs = ["XCURSOR_THEME=" + theme, "XCURSOR_PATH=" + os.environ.get("XCURSOR_PATH", search_path())] + (["XCURSOR_SIZE=%d" % size] if size else [])
    for cmd in (["dbus-update-activation-environment", "--systemd"] + pairs, ["systemctl", "--user", "set-environment"] + pairs):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass


def main(argv):
    if "--env" in argv:
        print("\n".join(env_lines()))
    if "--apply" in argv:
        apply_cursor()
    if not argv:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
