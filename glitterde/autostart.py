"""XDG autostart for the glitterDE session: launches ~/.config/autostart and /etc/xdg/autostart entries (per the Desktop Entry spec)."""
import glob
import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

DESKTOP = "glitterDE"


def entries():
    """{basename: path}; a user entry with the same file name overrides the system one."""
    dirs = [os.path.join(GLib.get_user_config_dir(), "autostart")]
    dirs += [os.path.join(d, "autostart") for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    found = {}
    for d in reversed(dirs):
        for f in glob.glob(os.path.join(d, "*.desktop")):
            found[os.path.basename(f)] = f
    return found


def main():
    n = 0
    for name, path in sorted(entries().items()):
        info = Gio.DesktopAppInfo.new_from_filename(path)
        if info is None or info.get_is_hidden():
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(path, GLib.KeyFileFlags.NONE)
            if kf.get_string("Desktop Entry", "X-GNOME-Autostart-enabled") == "false":
                continue
        except GLib.Error:
            pass
        if not info.get_show_in(DESKTOP):          # honours OnlyShowIn / NotShowIn
            continue
        try:
            info.launch([], None)
            n += 1
        except GLib.Error as e:
            print("glitterde-autostart: %s: %s" % (name, e.message), file=sys.stderr)
    return 0
