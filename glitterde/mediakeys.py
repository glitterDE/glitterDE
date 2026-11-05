"""Hardware media keys handler (XF86Audio*, XF86MonBrightness*)."""
import shutil
import subprocess
import sys

STEP = 5                                     # percent per key press

MPRIS = "org.mpris.MediaPlayer2"
PLAYER_CALLS = {"play-pause": "PlayPause", "play": "Play", "pause": "Pause", "stop": "Stop", "next": "Next", "prev": "Previous"}


def _run(argv):
    try:
        subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def volume(action):
    if shutil.which("wpctl"):
        sink, src = "@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@"
        if action == "vol-up":
            _run(["wpctl", "set-volume", "-l", "1.0", sink, "%d%%+" % STEP])
        elif action == "vol-down":
            _run(["wpctl", "set-volume", sink, "%d%%-" % STEP])
        elif action == "mute":
            _run(["wpctl", "set-mute", sink, "toggle"])
        elif action == "mic-mute":
            _run(["wpctl", "set-mute", src, "toggle"])
        if action == "vol-up":                 # raising the volume of a muted sink should be audible
            _run(["wpctl", "set-mute", sink, "0"])
    elif shutil.which("pactl"):
        if action == "vol-up":
            _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+%d%%" % STEP])
        elif action == "vol-down":
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-%d%%" % STEP])
        elif action == "mute":
            _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        elif action == "mic-mute":
            _run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"])


def brightness(action):
    if not shutil.which("brightnessctl"):
        return
    from .services import Light
    light = Light()
    dev = ["-d", light.name] if getattr(light, "name", None) else []
    _run(["brightnessctl", *dev, "set", "%d%%+" % STEP if action == "bright-up" else "%d%%-" % STEP])


def player(action):
    import gi
    from gi.repository import Gio, GLib
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        names = [n for n in conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None,
                                           GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 500, None).unpack()[0] if n.startswith(MPRIS + ".")]
    except GLib.Error:
        return
    if not names:
        return
    pick = names[0]
    for n in names:                              # prefer a player that is playing right now
        try:
            st = conn.call_sync(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                                GLib.Variant("(ss)", (MPRIS + ".Player", "PlaybackStatus")), GLib.VariantType("(v)"),
                                Gio.DBusCallFlags.NONE, 300, None).unpack()[0]
        except GLib.Error:
            continue
        if st == "Playing":
            pick = n
            break
    try:
        conn.call_sync(pick, "/org/mpris/MediaPlayer2", MPRIS + ".Player", PLAYER_CALLS[action], None, None, Gio.DBusCallFlags.NONE, 800, None)
    except GLib.Error:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    a = argv[0]
    if a in ("vol-up", "vol-down", "mute", "mic-mute"):
        volume(a)
    elif a in ("bright-up", "bright-down"):
        brightness(a)
    elif a in PLAYER_CALLS:
        player(a)
    else:
        print("unknown action", a, file=sys.stderr)
        return 2
    return 0
