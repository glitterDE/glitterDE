"""glitterDE session services: real system data, no GUI code.

Everything reads standard Linux interfaces (/proc, /sys, D-Bus, XDG .desktop files)
and degrades to "unavailable" instead of failing when a facility is missing.
"""
import os
import re
import shutil
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


# ------------------------------------------------------------------ helpers
def run_async(argv, cb):
    """Run a command without blocking the UI; cb(stdout or None)."""
    if not shutil.which(argv[0]):
        GLib.idle_add(cb, None)
        return
    try:
        # every caller parses this output (volume, mute, sink names ...): pactl and friends translate their labels and yes/no, which
        # silently broke mute detection and the output-device list on non-English systems
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        for k in ("LC_ALL", "LANG", "LANGUAGE"):
            launcher.setenv(k, "C", True)
        p = launcher.spawnv(argv)
    except GLib.Error:
        GLib.idle_add(cb, None)
        return

    def done(proc, res):
        try:
            ok, out, _ = proc.communicate_utf8_finish(res)
            cb(out if ok and proc.get_successful() else None)
        except GLib.Error:
            cb(None)
    p.communicate_utf8_async(None, None, done)


def fire(argv):
    own = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", argv[0])
    if os.path.isfile(own) and os.access(own, os.X_OK):      # our own tools: never resolve through PATH (stale copies in ~/.local/bin)
        argv = [own] + list(argv[1:])
    if os.path.isabs(argv[0]) or shutil.which(argv[0]):
        try:
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            pass


POLKIT_AGENTS = (
    "/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1", "/usr/libexec/polkit-gnome-authentication-agent-1",
    "/usr/libexec/polkit-mate-authentication-agent-1", "/usr/lib/mate-polkit/polkit-mate-authentication-agent-1",
    "/usr/lib/x86_64-linux-gnu/libexec/polkit-kde-authentication-agent-1", "/usr/libexec/polkit-kde-authentication-agent-1",
    "/usr/lib/polkit-kde-authentication-agent-1", "/usr/libexec/xfce-polkit", "/usr/lib/xfce-polkit/xfce-polkit",
    "/usr/libexec/lxqt-policykit-agent", "/usr/bin/lxpolkit", "/usr/bin/lxqt-policykit-agent", "/usr/libexec/hyprpolkitagent",
)


def start_polkit_agent():
    """Power actions can need an authentication prompt (another user logged in, an app holding a shutdown inhibitor). Without a polkit
    agent that prompt can never appear and logind just refuses - start any installed agent, once, at session start."""
    try:
        if Gio.bus_get_sync(Gio.BusType.SYSTEM, None) is None:
            return
    except GLib.Error:
        return
    for a in POLKIT_AGENTS:
        if os.path.isfile(a) and os.access(a, os.X_OK):
            try:
                Gio.Subprocess.new([a], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
                return
            except GLib.Error:
                continue


def _run_chain(chain, on_done):
    """Try argv lists one after another until one exits 0. on_done(ok, error_text)."""
    if not chain:
        on_done(False, "no working power command found")
        return
    argv, rest = chain[0], chain[1:]
    if not (os.path.isabs(argv[0]) and os.access(argv[0], os.X_OK)) and not shutil.which(argv[0]):
        _run_chain(rest, on_done)
        return
    try:
        p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error:
        _run_chain(rest, on_done)
        return

    def done(proc, res):
        try:
            _ok, _out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as e:
            _ok, err = False, e.message
        if proc.get_if_exited() and proc.get_exit_status() == 0:
            on_done(True, "")
        elif rest:
            _run_chain(rest, on_done)
        else:
            on_done(False, (err or "").strip().splitlines()[-1] if err and err.strip() else "command failed: " + " ".join(argv))
    p.communicate_utf8_async(None, None, done)


def power_action(what, on_result=None):
    """what: 'reboot' | 'poweroff' | 'suspend'. Asks systemd-logind over D-Bus and WAITS for the answer (it used to be fire-and-forget, so a
    refusal - polkit, an inhibitor, no logind - was silently lost and the old fallback never ran). On refusal it tries, in order:
    systemctl, systemctl ignoring inhibitors, loginctl, pkexec systemctl, shutdown(8), elogind/ConsoleKit tools.
    on_result(ok, message) is called on the main loop when the request was accepted or every method failed."""
    method = {"reboot": "Reboot", "poweroff": "PowerOff", "suspend": "Suspend"}[what]
    verb = {"reboot": "reboot", "poweroff": "poweroff", "suspend": "suspend"}[what]
    chain = [["systemctl", verb], ["systemctl", "-i", verb], ["loginctl", verb], ["pkexec", "systemctl", "-i", verb]]
    if what == "reboot":
        chain += [["/sbin/shutdown", "-r", "now"], ["/usr/sbin/shutdown", "-r", "now"], ["/sbin/reboot"], ["/usr/sbin/reboot"]]
    elif what == "poweroff":
        chain += [["/sbin/shutdown", "-P", "now"], ["/usr/sbin/shutdown", "-P", "now"], ["/sbin/poweroff"], ["/usr/sbin/poweroff"]]
    else:
        chain += [["pm-suspend"], ["/usr/sbin/pm-suspend"]]

    def finish(ok, msg):
        if not ok:
            print("glitterde: %s failed: %s" % (what, msg))
        if on_result:
            on_result(ok, msg)

    def fallback(why):
        print("glitterde: logind %s refused (%s), trying other methods" % (what, why))
        _run_chain(chain, finish)

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as e:
        fallback(e.message)
        return

    def reply(conn, res):
        try:
            conn.call_finish(res)
        except GLib.Error as e:
            fallback(e.message)
            return
        finish(True, "")
    bus.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method,
             GLib.Variant("(b)", (True,)), None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000, None, reply)


# -------------------------------------------------------------- system stats
class Stats:
    def __init__(self):
        self._cpu = None
        self._net = None

    def cpu(self):
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle, tot = v[3] + v[4], sum(v[:8])         # not guest / guest_nice: the kernel already counts them inside user / nice
        prev, self._cpu = self._cpu, (idle, tot)
        if not prev or tot <= prev[1]:
            return 0.0
        return max(0.0, min(1.0, 1 - (idle - prev[0]) / (tot - prev[1])))

    def mem(self):
        d = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v = ln.split(":")
                d[k] = int(v.split()[0]) * 1024
        total = d["MemTotal"]
        used = total - d.get("MemAvailable", d.get("MemFree", 0))
        return used / total, used, total

    def disk(self, path="/"):
        s = os.statvfs(path)
        total = s.f_blocks * s.f_frsize
        used = total - s.f_bavail * s.f_frsize
        return used / total if total else 0.0, used, total

    def net_rate(self):
        """Bytes/second (rx+tx) over all non-loopback interfaces since last call."""
        rx = tx = 0
        with open("/proc/net/dev") as f:
            for ln in list(f)[2:]:
                name, data = ln.split(":")
                if name.strip() == "lo":
                    continue
                cols = data.split()
                rx += int(cols[0]); tx += int(cols[8])
        now = time.monotonic()
        prev, self._net = self._net, (now, rx + tx)
        if not prev or now <= prev[0]:
            return 0.0
        return max(0.0, (rx + tx - prev[1]) / (now - prev[0]))

    def uptime(self):
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])


def interfaces():
    """[(name, 'wifi'|'ethernet', is_up, speed_mbps|None)] for physical-looking links."""
    out = []
    base = "/sys/class/net"
    if not os.path.isdir(base):
        return out
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        if n == "lo" or not os.path.exists(os.path.join(p, "device")):
            continue
        kind = "wifi" if os.path.isdir(os.path.join(p, "wireless")) else "ethernet"
        try:
            up = open(os.path.join(p, "operstate")).read().strip() == "up"
        except OSError:
            up = False
        speed = None
        try:
            sp = int(open(os.path.join(p, "speed")).read())
            speed = sp if sp > 0 else None
        except (OSError, ValueError):
            pass
        out.append((n, kind, up, speed))
    return out


def _read(path):
    with open(path) as f:
        return f.read().strip()


def battery(base="/sys/class/power_supply"):
    """(percent, charging) for the machine's own battery, or None when it has none.
    Peripheral batteries (wireless mouse, keyboard, game pad: scope "Device") are not the machine's battery; a laptop with two
    batteries is shown as one, weighted by capacity; batteries that only report energy_*/charge_* (no "capacity" file) still work."""
    if not os.path.isdir(base):
        return None
    cells = []                                    # (now, full, percent, status)
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        try:
            if _read(os.path.join(p, "type")) != "Battery":
                continue
            try:
                if _read(os.path.join(p, "scope")) == "Device":
                    continue
            except OSError:
                pass                                # no scope file = the system's own battery
            status = _read(os.path.join(p, "status"))
        except OSError:
            continue
        pct = None
        try:
            pct = int(_read(os.path.join(p, "capacity")))
        except (OSError, ValueError):
            pass
        now = full = None
        for a, b in (("energy_now", "energy_full"), ("charge_now", "charge_full")):
            try:
                now, full = int(_read(os.path.join(p, a))), int(_read(os.path.join(p, b)))
                break
            except (OSError, ValueError):
                now = full = None
        if pct is None and full:
            pct = round(100.0 * now / full)
        if pct is not None:
            cells.append((now, full, max(0, min(100, pct)), status))
    if not cells:
        return None
    if len(cells) > 1 and all(c[1] for c in cells):
        pct = round(100.0 * sum(c[0] for c in cells) / sum(c[1] for c in cells))
    else:
        pct = round(sum(c[2] for c in cells) / len(cells))
    stats = [c[3] for c in cells]
    # "Full" on one battery while the other still discharges (ThinkPads do this) is not "plugged in"
    return max(0, min(100, pct)), ("Charging" in stats) or all(st == "Full" for st in stats)


# -------------------------------------------------------- volume / brightness
class Audio:
    """Volume via WirePlumber (wpctl) or PulseAudio (pactl); None when neither exists."""

    def __init__(self):
        self.backend = "wpctl" if shutil.which("wpctl") else "pactl" if shutil.which("pactl") else None

    @property
    def available(self):
        return self.backend is not None

    def get(self, cb):
        if self.backend == "wpctl":
            def p(out):
                try:
                    cb(float(out.split()[1]), "MUTED" in out)
                except Exception:
                    cb(None, False)
            run_async(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], p)
        elif self.backend == "pactl":
            def p(out):
                try:
                    import re
                    pct = int(re.search(r"(\d+)%", out).group(1)) / 100.0
                    run_async(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], lambda o: cb(pct, bool(o and "yes" in o)))
                except Exception:
                    cb(None, False)
            run_async(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], p)
        else:
            cb(None, False)

    def set(self, v):
        v = max(0.0, min(1.0, v))
        if self.backend == "wpctl":
            fire(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "%.2f" % v])
        elif self.backend == "pactl":
            fire(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % round(v * 100)])

    def toggle_mute(self):
        if self.backend == "wpctl":
            fire(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        elif self.backend == "pactl":
            fire(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])

    # ---- output devices
    def sinks(self, cb):
        """cb([(key, label, is_default), ...]): every audio output (speakers, headphones, HDMI, Bluetooth ...). `key` is what set_default() wants."""
        if self.backend == "wpctl":
            run_async(["wpctl", "status"], lambda out: cb(parse_wpctl_sinks(out or "")))
        elif self.backend == "pactl":
            def listed(out):
                found = parse_pactl_sinks(out or "")
                run_async(["pactl", "get-default-sink"], lambda d: cb([(k, lab, k == (d or "").strip()) for k, lab in found]))
            run_async(["pactl", "list", "sinks"], listed)
        else:
            cb([])

    def set_default(self, key, done=None):
        """Make `key` (from sinks()) the default output. Streams that are playing move with it. done() runs afterwards."""
        key = str(key)
        if self.backend == "wpctl":                            # WirePlumber moves the running streams by itself
            run_async(["wpctl", "set-default", key], lambda _o: done and done())
        elif self.backend == "pactl":
            def moved(out):
                for line in (out or "").splitlines():
                    sid = line.split("\t")[0].strip()
                    if sid.isdigit():
                        fire(["pactl", "move-sink-input", sid, key])
                if done:
                    done()
            run_async(["pactl", "set-default-sink", key],
                      lambda _o: run_async(["pactl", "list", "short", "sink-inputs"], moved))
        elif done:
            done()


def parse_wpctl_sinks(text):
    """[(id, label, is_default)] from `wpctl status` (the lines under  Audio > Sinks:). The default output carries a '*'."""
    out, in_audio, in_sinks = [], False, False
    for raw in text.splitlines():
        line = raw.strip(" \t│├└─")
        if not raw.startswith((" ", "\t", "│", "├", "└")) and line:                    # a top-level heading: Audio / Video / Settings
            in_audio, in_sinks = line == "Audio", False
            continue
        if not in_audio or not line:
            continue
        if line.endswith(":") and not line[0].isdigit() and not line.startswith("*"):  # a tree heading: Devices: / Sinks: / Sources: ...
            in_sinks = line == "Sinks:"
            continue
        if not in_sinks:
            continue
        m = re.match(r"^(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:[^\]]*\])?\s*$", line)
        if m:
            out.append((m.group(2), m.group(3), bool(m.group(1))))
    return out


def parse_pactl_sinks(text):
    """[(name, description)] from `pactl list sinks`."""
    out, name = [], None
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("Sink #"):
            name = None
        elif t.startswith("Name:"):
            name = t[5:].strip()
        elif t.startswith("Description:") and name:
            out.append((name, t[12:].strip() or name))
            name = None
    return out


class Backlight:
    """Screen brightness. Reads sysfs, sets through brightnessctl (needs no root). The SAME device is used for both: with several
    (acpi_video0 + intel_backlight is common) the slider used to read one and brightnessctl change another."""
    RANK = {"raw": 0, "platform": 1, "firmware": 2}                 # the kernel's documented order of preference

    def __init__(self, base="/sys/class/backlight"):
        self.dir = self.name = None
        try:
            names = os.listdir(base)
        except OSError:
            names = []

        def rank(n):
            try:
                t = _read(os.path.join(base, n, "type"))
            except OSError:
                t = ""
            return (self.RANK.get(t, 3), n)
        if names:
            self.name = min(names, key=rank)
            self.dir = os.path.join(base, self.name)
        self.available = bool(self.dir and shutil.which("brightnessctl"))

    def get(self):
        try:
            cur = int(_read(os.path.join(self.dir, "brightness")))
            mx = int(_read(os.path.join(self.dir, "max_brightness")))
            return max(0.0, min(1.0, cur / mx))
        except Exception:
            return None

    def set(self, v):
        fire(["brightnessctl", "-d", self.name, "set", "%d%%" % round(max(0.05, min(1, v)) * 100)])


# --------------------------------------------------- notification daemon
NOTIF_XML = """<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg direction="out" type="as"/></method>
<method name="Notify"><arg direction="in" type="s"/><arg direction="in" type="u"/><arg direction="in" type="s"/>
<arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="in" type="as"/>
<arg direction="in" type="a{sv}"/><arg direction="in" type="i"/><arg direction="out" type="u"/></method>
<method name="CloseNotification"><arg direction="in" type="u"/></method>
<method name="GetServerInformation"><arg direction="out" type="s"/><arg direction="out" type="s"/>
<arg direction="out" type="s"/><arg direction="out" type="s"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>"""


class Notification:
    def __init__(self, nid, app, icon, summary, body, urgency, timeout):
        # any local program can send these: bound them so one huge message cannot stall the panel while GTK lays the text out
        self.id, self.app, self.icon, self.summary, self.body = nid, (app or "")[:80], (icon or "")[:512], (summary or "")[:200], (body or "")[:1500]
        self.urgency, self.timeout, self.time = urgency, timeout, time.time()


class NotificationServer:
    """Owns org.freedesktop.Notifications on the session bus (spec: platform standard)."""

    def __init__(self, on_new, on_close):
        self.on_new, self.on_close = on_new, on_close
        self.active = False
        self.conn = None
        self._next = 1
        self._node = Gio.DBusNodeInfo.new_for_xml(NOTIF_XML)
        self._owner = Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                                       Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE,
                                       self._acquired, self._name_ok, self._lost)

    def _acquired(self, conn, name):
        self.conn = conn
        conn.register_object("/org/freedesktop/Notifications", self._node.interfaces[0], self._call, None, None)

    def _name_ok(self, conn, name):
        self.active = True

    def _lost(self, conn, name):
        self.active = False

    def _call(self, conn, sender, path, iface, method, params, inv):
        if method == "GetCapabilities":
            inv.return_value(GLib.Variant("(as)", (["body", "persistence"],)))      # not "actions": there is no ActionInvoked signal, so apps would wait for clicks that never come
        elif method == "GetServerInformation":
            from . import __version__
            inv.return_value(GLib.Variant("(ssss)", ("glitterde-notify", "glitterDE", __version__, "1.2")))
        elif method == "CloseNotification":
            nid = params.unpack()[0]
            inv.return_value(None)
            self.close(nid, 3)
        elif method == "Notify":
            app, rid, icon, summ, body, actions, hints, timeout = params.unpack()
            nid = rid if rid else self._next
            if not rid:
                self._next += 1
            urg = hints.get("urgency", 1)
            inv.return_value(GLib.Variant("(u)", (nid,)))
            GLib.idle_add(self.on_new, Notification(nid, app, icon, summ, body, urg, timeout))

    def close(self, nid, reason=2):
        if self.conn:
            self.conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                  "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))
        GLib.idle_add(self.on_close, nid)


# ----------------------------------------------------------------- MPRIS
MPRIS = "org.mpris.MediaPlayer2"


class Media:
    """Tracks the most recently active MPRIS player; signal driven, polls position only while playing."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.name = None
        self.status = "Stopped"
        self.title = self.artist = ""
        self.length = 0
        self.art = None
        self._pos_base = (0, time.monotonic())
        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.conn.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                   "/org/mpris/MediaPlayer2", MPRIS + ".Player", Gio.DBusSignalFlags.NONE, self._props)
        self.conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                   "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._owner)
        self._scan()

    def _call(self, name, iface, method, args=None, rtype=None):
        return self.conn.call_sync(name, "/org/mpris/MediaPlayer2", iface, method, args,
                                   GLib.VariantType(rtype) if rtype else None, Gio.DBusCallFlags.NONE, 150, None)

    def _scan(self):
        try:
            r = self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                    "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 400, None)
            names = [n for n in r.unpack()[0] if n.startswith(MPRIS + ".")]
        except GLib.Error:
            names = []
        if self.name not in names:
            self.name = names[0] if names else None
        if self.name:
            self.refresh()
        else:
            self._reset()

    def _reset(self):
        self.status, self.title, self.artist, self.length, self.art, self.art_url = "Stopped", "", "", 0, None, None
        self.on_change()

    def _owner(self, conn, sender, path, iface, sig, params, *_):
        name, old, new = params.unpack()
        if name.startswith(MPRIS + "."):
            if new and not self.name:
                self.name = name; self.refresh()
            elif not new and name == self.name:
                self.name = None; self._scan()

    def _props(self, conn, sender, path, iface, sig, params, *_):
        if getattr(self, "_pending", None):          # players can emit dozens of property changes a second
            return
        self._pending = GLib.timeout_add(250, self._flush)

    def _flush(self):
        self._pending = None
        self.refresh()
        return False

    def refresh(self):
        if not self.name:
            return
        name = self.name
        # async: a slow or busy player must never block the GTK main loop
        self.conn.call(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll",
                       GLib.Variant("(s)", (MPRIS + ".Player",)), GLib.VariantType("(a{sv})"),
                       Gio.DBusCallFlags.NONE, 1500, None, self._got, name)

    def _got(self, conn, res, name):
        try:
            r = conn.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        if name != self.name:
            return
        self.status = r.get("PlaybackStatus", "Stopped")
        md = r.get("Metadata", {})
        self.title = md.get("xesam:title", "")
        a = md.get("xesam:artist", [])
        self.artist = ", ".join(a) if isinstance(a, list) else str(a)
        self.length = int(md.get("mpris:length", 0))
        self.trackid = md.get("mpris:trackid", "/org/mpris/MediaPlayer2/TrackList/NoTrack")
        self.player = self.name.replace(MPRIS + ".", "").split(".instance")[0] if self.name else ""
        self.can_seek = bool(r.get("CanSeek", False))
        art = md.get("mpris:artUrl", "")
        if art != getattr(self, "art_url", None):          # new track / cover: clear the old one, resolve the new one async
            self.art_url, self.art = art, None
            resolve_art(art, lambda path, u=art: self._art_ready(u, path))
        self._pos_base = (int(r.get("Position", 0)), time.monotonic())
        self.on_change()

    def _art_ready(self, url, path):
        if url == getattr(self, "art_url", None) and path != self.art:     # ignore results for a track that already changed
            self.art = path
            self.on_change()

    def position_us(self):
        base, t0 = self._pos_base
        return base + (int((time.monotonic() - t0) * 1e6) if self.status == "Playing" else 0)

    def seek_to(self, frac):
        """Jump to a fraction of the current track (MPRIS SetPosition)."""
        if self.name and self.length and self.can_seek:
            try:
                self.conn.call(self.name, "/org/mpris/MediaPlayer2", MPRIS + ".Player", "SetPosition",
                               GLib.Variant("(ox)", (str(self.trackid), int(frac * self.length))), None,
                               Gio.DBusCallFlags.NONE, 400, None, None, None)
                self._pos_base = (int(frac * self.length), time.monotonic())
            except Exception:
                pass

    def control(self, method):
        if self.name:
            self.conn.call(self.name, "/org/mpris/MediaPlayer2", MPRIS + ".Player", method, None, None,
                           Gio.DBusCallFlags.NONE, 400, None, None, None)


# --------------------------------------------------------- album art (MPRIS mpris:artUrl)
ART_MAX = 6 * 1024 * 1024


def _art_cache_dir():
    d = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "glitterde", "art")
    os.makedirs(d, exist_ok=True)
    return d


def resolve_art(url, done):
    """Turn an mpris:artUrl into a local image file and call done(path or None) on the GLib main loop.
    Handles file:// (percent-encoded), plain paths, data: URIs and http(s):// (downloaded in a thread, cached on disk)."""
    import base64
    import hashlib
    import threading
    import urllib.parse
    if not url:
        done(None); return
    if url.startswith("file://"):
        p = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        done(p if os.path.isfile(p) else None); return
    if url.startswith("/"):
        done(url if os.path.isfile(url) else None); return
    key = hashlib.sha1(url.encode()).hexdigest()
    try:
        path = os.path.join(_art_cache_dir(), key)
    except OSError:
        done(None); return
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        done(path); return
    if url.startswith("data:"):
        try:
            head, _, payload = url.partition(",")
            raw = base64.b64decode(payload) if ";base64" in head else urllib.parse.unquote_to_bytes(payload)
            if len(raw) > ART_MAX:
                raise ValueError("too big")
            with open(path, "wb") as f:
                f.write(raw)
            done(path)
        except Exception:
            done(None)
        return
    if not url.startswith(("http://", "https://")):
        done(None); return

    def work():
        ok = None
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "glitterde/0.7"})
            with urllib.request.urlopen(req, timeout=8) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                data = r.read(ART_MAX + 1)
            if len(data) <= ART_MAX and (ctype.startswith("image/") or data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")):
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                ok = path
        except Exception:
            ok = None
        GLib.idle_add(lambda: (done(ok), False)[1])

    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------- applications
CATEGORY_MAP = [("Games", "Game"), ("Development", "Development"), ("Graphics", "Graphics"),
                ("Multimedia", "AudioVideo"), ("Multimedia", "Audio"), ("Multimedia", "Video"),
                ("Internet", "Network"), ("Office", "Office"), ("Settings", "Settings"),
                ("System", "System"), ("Accessories", "Utility")]
CATEGORIES = ["Pinned", "Applications", "System", "Development", "Graphics", "Internet",
              "Multimedia", "Office", "Games", "Accessories", "Settings"]


def all_apps():
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
    apps.sort(key=lambda a: a.get_display_name().lower())
    return apps


def category_of(app):
    cats = (app.get_categories() or "").split(";") if hasattr(app, "get_categories") else []
    for label, key in CATEGORY_MAP:
        if key in cats:
            return label
    return "Accessories"


def default_favorites(apps, configured=None):
    """Pinned apps: configured ids, else the system's defaults (browser, terminal, files, editor, settings)."""
    by_id = {a.get_id(): a for a in apps}
    favs = []

    def add(a):
        if a and a.get_id() in by_id and by_id[a.get_id()] not in favs:
            favs.append(by_id[a.get_id()])
    for i in configured or []:
        add(by_id.get(i if i.endswith(".desktop") else i + ".desktop"))
    if configured:
        return favs
    own = lambda n: by_id.get("glitterde-%s.desktop" % n)
    add(Gio.AppInfo.get_default_for_type("x-scheme-handler/http", False))
    if own("terminal"):
        add(own("terminal"))
    else:
        for a in apps:                                   # any terminal emulator
            if "TerminalEmulator" in (a.get_categories() or ""):
                add(a); break
    add(own("files") or Gio.AppInfo.get_default_for_type("inode/directory", False))
    add(Gio.AppInfo.get_default_for_type("text/plain", False))
    if own("settings"):
        add(own("settings"))
    else:
        for a in apps:
            if "DesktopSettings" in (a.get_categories() or ""):
                add(a); break
    return favs


def have(tool):
    return shutil.which(tool) is not None


# Wi-Fi / Ethernet / Bluetooth live in netbt.py (backend) and netui.py (widgets).
