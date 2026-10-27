"""glitterDE session services: real system data, no GUI code.

Everything reads standard Linux interfaces (/proc, /sys, D-Bus, XDG .desktop files)
and degrades to "unavailable" instead of failing when a facility is missing.
"""
import os
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
        p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
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
        idle, tot = v[3] + v[4], sum(v)
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


def battery():
    """(percent, charging) or None on machines without a battery."""
    base = "/sys/class/power_supply"
    if not os.path.isdir(base):
        return None
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        try:
            if open(os.path.join(p, "type")).read().strip() != "Battery":
                continue
            pct = int(open(os.path.join(p, "capacity")).read())
            st = open(os.path.join(p, "status")).read().strip()
            return pct, st in ("Charging", "Full")
        except (OSError, ValueError):
            continue
    return None


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


class Backlight:
    def __init__(self):
        base = "/sys/class/backlight"
        self.dir = None
        if os.path.isdir(base) and os.listdir(base):
            self.dir = os.path.join(base, sorted(os.listdir(base))[0])
        self.available = bool(self.dir and shutil.which("brightnessctl"))

    def get(self):
        try:
            cur = int(open(os.path.join(self.dir, "brightness")).read())
            mx = int(open(os.path.join(self.dir, "max_brightness")).read())
            return cur / mx
        except Exception:
            return None

    def set(self, v):
        fire(["brightnessctl", "set", "%d%%" % round(max(0.05, min(1, v)) * 100)])


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
        self.id, self.app, self.icon, self.summary, self.body = nid, app, icon, summary, body
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
            inv.return_value(GLib.Variant("(as)", (["body", "actions", "persistence"],)))
        elif method == "GetServerInformation":
            inv.return_value(GLib.Variant("(ssss)", ("glitterde-notify", "glitterDE", "0.2", "1.2")))
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


# ------------------------------------------------- network / Bluetooth helpers (nmcli, bluetoothctl)
def have(tool):
    return shutil.which(tool) is not None


def wifi_radio(cb):
    run_async(["nmcli", "radio", "wifi"], lambda o: cb(o is not None and "enabled" in o))


def wifi_set_radio(on):
    fire(["nmcli", "radio", "wifi", "on" if on else "off"])


def wifi_scan(cb):
    """cb([(in_use, ssid, signal, security)]) sorted: connected first, then by signal."""
    def done(out):
        seen, rows = set(), []
        for ln in (out or "").splitlines():
            f = [x.replace("\x00", ":") for x in ln.replace("\\:", "\x00").split(":")]
            if len(f) >= 4 and f[1] and f[1] not in seen:
                seen.add(f[1])
                try:
                    rows.append((f[0] == "*", f[1], int(f[2] or 0), f[3]))
                except ValueError:
                    pass
        rows.sort(key=lambda r: (not r[0], -r[2]))
        cb(rows)
    run_async(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "auto"], done)


def wifi_connect(ssid, password, cb):
    argv = ["nmcli", "-w", "20", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
    run_async(argv, lambda o: cb(o is not None))


def bt_adapter():
    return have("bluetoothctl") and os.path.isdir("/sys/class/bluetooth") and bool(os.listdir("/sys/class/bluetooth"))


def bt_powered(cb):
    run_async(["bluetoothctl", "show"], lambda o: cb("Powered: yes" in (o or "")))


def bt_set_power(on):
    fire(["bluetoothctl", "power", "on" if on else "off"])


def bt_devices(cb):
    """cb([(mac, name, connected)]) for paired devices."""
    def with_conn(conn_out):
        conn = {l.split(" ", 2)[1] for l in (conn_out or "").splitlines() if l.count(" ") >= 2}

        def done(out):
            rows = []
            for ln in (out or "").splitlines():
                p = ln.split(" ", 2)
                if len(p) >= 3:
                    rows.append((p[1], p[2], p[1] in conn))
            cb(rows)
        run_async(["bluetoothctl", "devices", "Paired"], done)
    run_async(["bluetoothctl", "devices", "Connected"], with_conn)


def bt_toggle(mac, connected):
    fire(["bluetoothctl", "disconnect" if connected else "connect", mac])


def run_async_err(argv, cb):
    """Like run_async, but cb(ok, stdout, stderr): the error text is how we tell the user WHY a connection failed."""
    if not shutil.which(argv[0]):
        GLib.idle_add(cb, False, "", "%s is not installed" % argv[0]); return
    try:
        p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as e:
        GLib.idle_add(cb, False, "", e.message); return

    def done(proc, res):
        try:
            ok, out, err = proc.communicate_utf8_finish(res)
            cb(bool(ok and proc.get_successful()), out or "", err or "")
        except GLib.Error as e:
            cb(False, "", e.message)
    p.communicate_utf8_async(None, None, done)


def net_error(text):
    """nmcli failure text -> (kind, short human sentence). kind 'password' means: ask for / re-ask the password."""
    t = (text or "").lower()
    if any(k in t for k in ("secrets were required", "password", "802-1x", "no suitable", "authentication")):
        return "password", "Password needed"
    if "no network with ssid" in t or "not found" in t:
        return "failed", "Not found. Out of range?"
    if "timeout" in t or "timed out" in t:
        return "failed", "Timed out. Try again"
    if "unavailable" in t or "not ready" in t or "rfkill" in t or "not available" in t:
        return "failed", "Wi-Fi is off or unavailable"
    last = [l.strip() for l in (text or "").splitlines() if l.strip()]
    msg = last[-1].replace("Error: ", "") if last else "Could not connect"
    return "failed", msg[:70]


def bt_result(ok, text, connecting):
    """bluetoothctl output -> (success, short human sentence)."""
    t = (text or "").lower()
    if "connection successful" in t or "successful disconnected" in t or "alreadyconnected" in t.replace(".", "").replace(" ", ""):
        return True, "Connected" if connecting else "Disconnected"
    if "not available" in t:
        return False, "Not found. Turn it on and move closer"
    if "no default controller" in t or "powered off" in t or "notready" in t.replace(".", "").replace(" ", ""):
        return False, "Bluetooth is off"
    if "inprogress" in t.replace(".", "").replace(" ", ""):
        return False, "Another connection is in progress"
    if "failed to connect" in t or "org.bluez.error" in t:
        return False, "Could not connect. Is it on and in range?"
    if ok and "fail" not in t:
        return True, "Connected" if connecting else "Disconnected"
    last = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return False, (last[-1][:70] if last else "No answer from the device")
