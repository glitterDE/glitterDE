"""glitterDE network + Bluetooth backend (no widgets)"""
import os
import re
import shutil
import struct

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

# ============================================================== subprocess helper (locale-proof)


def run(argv, cb, timeout=0, stdin=None):
    """Run argv without blocking; cb(ok, stdout, stderr). The environment is forced to LC_ALL=C so output can be parsed."""
    if not shutil.which(argv[0]):
        GLib.idle_add(lambda: (cb(False, "", "%s is not installed" % argv[0]), False)[1])
        return
    try:
        sl = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE |
                                        (Gio.SubprocessFlags.STDIN_PIPE if stdin is not None else Gio.SubprocessFlags.NONE))
        sl.setenv("LC_ALL", "C", True)
        sl.setenv("LANG", "C", True)
        sl.setenv("LANGUAGE", "C", True)
        p = sl.spawnv(argv)
    except GLib.Error as e:
        msg = e.message                                   # `e` is gone after the except block: capture before the idle callback runs
        GLib.idle_add(lambda: (cb(False, "", msg), False)[1])
        return
    state = {"done": False}

    def done(proc, res):
        state["done"] = True
        try:
            ok, out, err = proc.communicate_utf8_finish(res)
            cb(bool(ok and proc.get_successful()), out or "", err or "")
        except GLib.Error as e:
            cb(False, "", e.message)
    p.communicate_utf8_async(stdin, None, done)
    if timeout:
        GLib.timeout_add_seconds(timeout, lambda: (None if state["done"] else p.force_exit(), False)[1])


def have(tool):
    return shutil.which(tool) is not None


def split_terse(line, n=-1):
    """Split one line of `nmcli -t` output on unescaped ':' (nmcli escapes ':' and '\\' with a backslash)."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1]); i += 2; continue
        if ch == ":" and (n < 0 or len(out) < n - 1):
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


# ============================================================== rfkill (sysfs + /dev/rfkill, no tools, no root)
RFKILL_TYPES = {"wlan": 1, "bluetooth": 2, "wwan": 5}


def rfkill_state(kind):
    """{'present': bool, 'soft': bool, 'hard': bool} for 'wlan' | 'bluetooth' (blocked = True)."""
    present, soft, hard = False, False, False
    base = "/sys/class/rfkill"
    try:
        for n in os.listdir(base):
            d = os.path.join(base, n)
            try:
                if open(os.path.join(d, "type")).read().strip() != kind:
                    continue
                present = True
                soft = soft or open(os.path.join(d, "soft")).read().strip() == "1"
                hard = hard or open(os.path.join(d, "hard")).read().strip() == "1"
            except OSError:
                continue
    except OSError:
        pass
    return {"present": present, "soft": soft, "hard": hard}


def rfkill_set(kind, blocked):
    """Soft block / unblock every radio of that kind. True when it worked (or there was nothing to change)."""
    t = RFKILL_TYPES.get(kind)
    try:
        fd = os.open("/dev/rfkill", os.O_WRONLY)
        try:
            os.write(fd, struct.pack("=IBBBB", 0, t, 3, 1 if blocked else 0, 0))      # idx, type, RFKILL_OP_CHANGE_ALL, soft, hard
        finally:
            os.close(fd)
        return True
    except (OSError, TypeError):
        pass
    if have("rfkill"):
        import subprocess
        try:
            return subprocess.run(["rfkill", "block" if blocked else "unblock", kind], timeout=5, capture_output=True).returncode == 0
        except Exception:
            return False
    return False


def airplane_mode():
    """True when every wireless radio on the machine is soft-blocked."""
    kinds = [rfkill_state(k) for k in ("wlan", "bluetooth")]
    kinds = [k for k in kinds if k["present"]]
    return bool(kinds) and all(k["soft"] or k["hard"] for k in kinds)


def set_airplane_mode(on):
    for k in ("wlan", "bluetooth"):
        rfkill_set(k, on)


# ============================================================== Wi-Fi / Ethernet / VPN (NetworkManager through nmcli)
class AccessPoint:
    """One visible Wi-Fi network (all of its access points merged; the strongest one decides the signal)."""
    __slots__ = ("ssid", "signal", "security", "in_use", "bssids", "band", "rate", "saved_uuid", "autoconnect", "device")

    def __init__(self, ssid):
        self.ssid, self.signal, self.security, self.in_use = ssid, 0, "", False
        self.bssids, self.band, self.rate = 0, "", 0
        self.saved_uuid, self.autoconnect, self.device = None, True, ""

    @property
    def secured(self):
        return bool(self.security) and self.security != "--"

    @property
    def enterprise(self):
        return "802.1X" in self.security

    @property
    def saved(self):
        return self.saved_uuid is not None


def _band(freq):
    m = re.match(r"\s*(\d+)", freq or "")
    if not m:
        return ""
    f = int(m.group(1))
    return "2.4 GHz" if f < 3000 else "5 GHz" if f < 5900 else "6 GHz"


def explain_nm_error(text):
    """nmcli failure text -> (kind, short sentence). kind: 'password' (ask again), 'enterprise', 'gone', 'timeout', 'off', 'failed'."""
    t = (text or "").lower()
    if "802.1x" in t or "eap" in t:
        return "enterprise", "This network needs a sign-in (802.1X). Use Network settings…"
    if any(k in t for k in ("secrets were required", "no secrets", "password", "psk", "wrong key", "authentication", "4-way handshake")):
        return "password", "Wrong password" if ("wrong" in t or "4-way" in t or "authentication" in t) else "Password needed"
    if "no network with ssid" in t or "not found" in t and "ssid" in t:
        return "gone", "Network not in range"
    if "timeout" in t or "timed out" in t:
        return "timeout", "Timed out. Try again"
    if "rfkill" in t or "wi-fi is disabled" in t or "unavailable" in t or "not ready" in t:
        return "off", "Wi-Fi is off or unavailable"
    if "networkmanager is not running" in t or "couldn't connect to server" in t or "could not create nmclient" in t:
        return "nm", "NetworkManager is not running"
    if "ip configuration could not be reserved" in t or "dhcp" in t:
        return "failed", "Connected, but no address from the router (DHCP)"
    last = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return "failed", (last[-1].replace("Error: ", "")[:80] if last else "Could not connect")


class Network:
    """NetworkManager front end. Create one per window; call `snapshot` / `scan` / `connect` ... with callbacks."""

    def __init__(self):
        self.ok = have("nmcli")

    # ---------------------------------------------------------------- state
    def status(self, cb):
        """cb({'nm': bool, 'wifi_on': bool, 'wifi_hw': bool, 'devices': [dict], 'wifi_dev': str|None, 'airplane': bool, 'connectivity': str}).
        'nm' False = NetworkManager is not installed or not running."""
        res = {"nm": False, "wifi_on": False, "wifi_hw": rfkill_state("wlan")["present"], "devices": [], "wifi_dev": None,
               "airplane": airplane_mode(), "connectivity": "unknown", "hard_block": rfkill_state("wlan")["hard"]}
        if not self.ok:
            GLib.idle_add(lambda: (cb(res), False)[1]); return

        def got_dev(ok, out, err):
            if not ok:
                cb(res); return
            res["nm"] = True
            for ln in out.splitlines():
                f = split_terse(ln)
                if len(f) < 4 or f[1] in ("loopback", "bridge", "wifi-p2p", "tun", "dummy") or f[0].startswith(("veth", "docker", "virbr", "br-")):
                    continue
                d = {"name": f[0], "type": f[1], "state": f[2], "connection": f[3] if f[3] != "--" else ""}
                res["devices"].append(d)
                if d["type"] == "wifi" and res["wifi_dev"] is None:
                    res["wifi_dev"] = d["name"]
            run(["nmcli", "-t", "-f", "WIFI", "radio"], got_radio)

        def got_radio(ok, out, err):
            res["wifi_on"] = "enabled" in out.lower()
            run(["nmcli", "-t", "-f", "CONNECTIVITY", "general"], got_conn)

        def got_conn(ok, out, err):
            res["connectivity"] = out.strip() or "unknown"
            cb(res)
        run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], got_dev)

    def saved_connections(self, cb):
        """cb({uuid: {'name','type','autoconnect','ssid'}}) for saved Wi-Fi / VPN / WireGuard / Ethernet profiles."""
        def done(ok, out, err):
            res = {}
            for ln in out.splitlines():
                f = split_terse(ln)
                if len(f) >= 4:
                    res[f[1]] = {"name": f[0], "uuid": f[1], "type": f[2], "autoconnect": f[3] == "yes", "active": len(f) > 4 and f[4] not in ("", "--")}
            cb(res)
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,DEVICE", "connection", "show"], done)

    # ---------------------------------------------------------------- Wi-Fi
    def radio(self, on, cb):
        """Switch the Wi-Fi radio. Clears a soft rfkill block first. cb(ok, message) once the radio has really changed."""
        if on and rfkill_state("wlan")["hard"]:
            GLib.idle_add(lambda: (cb(False, "Wi-Fi is switched off by a hardware key or switch"), False)[1])
            return
        if on:
            rfkill_set("wlan", False)

        def done(ok, out, err):
            GLib.timeout_add(400, lambda: (cb(ok, "" if ok else explain_nm_error(err)[1]), False)[1])     # let NetworkManager settle
        run(["nmcli", "radio", "wifi", "on" if on else "off"], done)

    def rescan(self, cb=None, dev=None):
        argv = ["nmcli", "device", "wifi", "rescan"] + (["ifname", dev] if dev else [])
        run(argv, lambda ok, out, err: cb and cb(ok))         # "Scanning not allowed immediately" is harmless: we list what is cached anyway

    def scan(self, cb, saved=None):
        """List networks without forcing a rescan (use rescan() first). cb([AccessPoint]) connected first, then strongest first."""
        def got(ok, out, err):
            rows = {}
            for ln in out.splitlines():
                f = split_terse(ln)
                if len(f) < 8:
                    continue
                in_use, bssid, ssid, chan, freq, rate, sig, sec = f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]
                if not ssid:
                    continue
                ap = rows.get(ssid)
                if ap is None:
                    ap = rows[ssid] = AccessPoint(ssid)
                ap.bssids += 1
                try:
                    s = int(sig or 0)
                except ValueError:
                    s = 0
                if s >= ap.signal:
                    ap.signal, ap.security, ap.band = s, (sec if sec != "--" else ""), _band(freq)
                    m = re.match(r"(\d+)", rate or "")
                    ap.rate = int(m.group(1)) if m else 0
                if in_use == "*":
                    ap.in_use = True
            out_rows = sorted(rows.values(), key=lambda a: (not a.in_use, -a.signal, a.ssid.lower()))
            if saved is not None:
                self._mark_saved(out_rows, saved)
                cb(out_rows)
            else:
                self.saved_connections(lambda sv: (self._mark_saved(out_rows, sv), cb(out_rows)))
        run(["nmcli", "-t", "-f", "IN-USE,BSSID,SSID,CHAN,FREQ,RATE,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], got)

    def _mark_saved(self, rows, saved):
        by_name = {}
        for sv in saved.values():
            if sv["type"] in ("802-11-wireless", "wifi"):
                by_name.setdefault(sv["name"], sv)
        for ap in rows:
            sv = by_name.get(ap.ssid)
            if sv:
                ap.saved_uuid, ap.autoconnect = sv["uuid"], sv["autoconnect"]

    def connect(self, ap_or_ssid, password, cb, hidden=False, dev=None):
        """Join a network. Uses the saved profile when there is one. cb(ok, kind, message); kind from explain_nm_error().
        A profile created by a failed attempt is removed again so the next try starts clean."""
        ssid = ap_or_ssid.ssid if isinstance(ap_or_ssid, AccessPoint) else ap_or_ssid
        saved_uuid = ap_or_ssid.saved_uuid if isinstance(ap_or_ssid, AccessPoint) else None

        def finish(ok, out, err, created_before=None):
            if ok:
                cb(True, "ok", "Connected to " + ssid); return
            kind, msg = explain_nm_error(err + "\n" + out)
            if kind == "password" and password:
                msg = "Wrong password"                      # we sent one and it was refused
            if created_before is None:
                cb(False, kind, msg); return

            def clean(sv):                                  # drop the profile this attempt made, and only report back once it is gone
                gone = [u for u, v in sv.items() if v["name"] == ssid and u not in created_before and v["type"] in ("802-11-wireless", "wifi")]
                left = {"n": len(gone)}
                if not gone:
                    cb(False, kind, msg); return

                def one(*_):
                    left["n"] -= 1
                    if left["n"] <= 0:
                        cb(False, kind, msg)
                for u in gone:
                    run(["nmcli", "connection", "delete", "uuid", u], one)
            self.saved_connections(clean)

        if saved_uuid and not password:
            run(["nmcli", "-w", "25", "connection", "up", "uuid", saved_uuid] + (["ifname", dev] if dev else []), finish)
            return

        def with_existing(sv):
            before = set(sv.keys())
            argv = ["nmcli", "-w", "25", "device", "wifi", "connect", ssid]
            if password:
                argv += ["password", password]
            if hidden:
                argv += ["hidden", "yes"]
            if dev:
                argv += ["ifname", dev]
            run(argv, lambda ok, out, err: finish(ok, out, err, before))
        if saved_uuid and password:                      # a new password for a known network: replace the stale profile's secret
            run(["nmcli", "connection", "modify", "uuid", saved_uuid, "wifi-sec.psk", password],
                lambda ok, out, err: run(["nmcli", "-w", "25", "connection", "up", "uuid", saved_uuid], finish))
        else:
            self.saved_connections(with_existing)

    def device_connect(self, dev, cb):
        """Bring a device up with its best saved profile (wired links)."""
        run(["nmcli", "-w", "25", "device", "connect", dev], lambda ok, out, err: cb(ok, "" if ok else explain_nm_error(err)[1]))

    def disconnect(self, dev, cb):
        run(["nmcli", "device", "disconnect", dev], lambda ok, out, err: cb(ok, "" if ok else explain_nm_error(err)[1]))

    def forget(self, uuid, cb):
        run(["nmcli", "connection", "delete", "uuid", uuid], lambda ok, out, err: cb(ok, "" if ok else (err.strip().splitlines() or ["Could not forget"])[-1]))

    def set_autoconnect(self, uuid, on, cb=None):
        run(["nmcli", "connection", "modify", "uuid", uuid, "connection.autoconnect", "yes" if on else "no"], lambda ok, *_: cb and cb(ok))

    def hotspot(self, ssid, password, cb, dev=None):
        argv = ["nmcli", "device", "wifi", "hotspot", "ssid", ssid, "password", password] + (["ifname", dev] if dev else [])
        run(argv, lambda ok, out, err: cb(ok, "" if ok else explain_nm_error(err)[1]))

    # ---------------------------------------------------------------- details of the active link
    def details(self, dev, cb):
        """cb({'ip','gateway','dns','mac','speed','ssid'...}) for a device."""
        def got(ok, out, err):
            d = {}
            for ln in out.splitlines():
                f = split_terse(ln, 2)
                if len(f) < 2:
                    continue
                k, v = f
                k = re.sub(r"\[\d+\]$", "", k)
                if k == "IP4.ADDRESS":
                    d.setdefault("ip", v.split("/")[0]); d.setdefault("prefix", v)
                elif k == "IP4.GATEWAY" and v:
                    d["gateway"] = v
                elif k == "IP4.DNS":
                    d["dns"] = (d.get("dns", "") + ", " + v) if d.get("dns") else v
                elif k == "GENERAL.HWADDR":
                    d["mac"] = v
                elif k == "GENERAL.CONNECTION":
                    d["connection"] = v
                elif k == "CAPABILITIES.SPEED" and v:
                    d["speed"] = v
                elif k == "IP6.ADDRESS":
                    d.setdefault("ip6", v.split("/")[0])
            cb(d)
        run(["nmcli", "-t", "-f", "GENERAL.HWADDR,GENERAL.CONNECTION,CAPABILITIES.SPEED,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS", "device", "show", dev], got)

    # ---------------------------------------------------------------- wired + VPN
    def activate(self, uuid, cb):
        run(["nmcli", "-w", "25", "connection", "up", "uuid", uuid], lambda ok, out, err: cb(ok, "" if ok else explain_nm_error(err)[1]))

    def deactivate(self, uuid, cb):
        run(["nmcli", "connection", "down", "uuid", uuid], lambda ok, out, err: cb(ok, "" if ok else explain_nm_error(err)[1]))

    def active_uuids(self, cb):
        run(["nmcli", "-t", "-f", "UUID,TYPE,DEVICE,STATE", "connection", "show", "--active"],
            lambda ok, out, err: cb({split_terse(l)[0] for l in out.splitlines() if l}))


# ============================================================== Bluetooth (BlueZ over D-Bus)
BLUEZ = "org.bluez"
IF_ADAPTER, IF_DEVICE, IF_PROPS, IF_OM = "org.bluez.Adapter1", "org.bluez.Device1", "org.freedesktop.DBus.Properties", "org.freedesktop.DBus.ObjectManager"
AGENT_PATH = "/org/glitterde/BluetoothAgent"
AGENT_XML = """<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>"""

BT_KINDS = {"audio-headset": "Headset", "audio-headphones": "Headphones", "audio-card": "Speaker", "input-keyboard": "Keyboard",
            "input-mouse": "Mouse", "input-gaming": "Controller", "input-tablet": "Tablet", "phone": "Phone", "computer": "Computer",
            "camera-photo": "Camera", "printer": "Printer", "modem": "Modem", "video-display": "Display", "network-wireless": "Network"}


def bt_error_text(msg):
    """Raw BlueZ / GDBus error -> one short human sentence."""
    t = (msg or "").lower()
    if "inprogress" in t.replace(" ", "").replace(".", ""):
        return "Another operation is still in progress"
    if "alreadyconnected" in t.replace(" ", "").replace(".", ""):
        return "Already connected"
    if "alreadyexists" in t.replace(" ", "").replace(".", ""):
        return "Already paired"
    if "authenticationcanceled" in t or "authenticationrejected" in t or "rejected" in t:
        return "Pairing was declined"
    if "authenticationfailed" in t or "authenticationtimeout" in t:
        return "Pairing failed. Put the device in pairing mode and try again"
    if "connectionattemptfailed" in t or "page timeout" in t or "host is down" in t:
        return "Could not reach the device. Is it on and close?"
    if "notready" in t.replace(" ", "") or "powered" in t:
        return "Bluetooth is off"
    if "rfkill" in t or "blocked" in t:
        return "Bluetooth is blocked (airplane mode or a hardware switch)"
    if "br-connection" in t or "profile-unavailable" in t or "profileunavailable" in t:
        return "The device is connected, but no audio/input profile is available (is bluez/pipewire-bluetooth installed?)"
    if "doesnotexist" in t or "unknownobject" in t:
        return "The device went away"
    if "timeout" in t or "timed out" in t or "noreply" in t.replace(" ", ""):
        return "No answer from the device"
    if "canceled" in t or "cancelled" in t:
        return "Cancelled"
    m = re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", (msg or "").strip())
    return (m or "Something went wrong")[:90]


class BtDevice:
    __slots__ = ("path", "address", "name", "alias", "icon", "paired", "trusted", "connected", "rssi", "blocked", "battery", "connecting", "uuids")

    def __init__(self, path):
        self.path, self.address, self.name, self.alias, self.icon = path, "", "", "", ""
        self.paired = self.trusted = self.connected = self.blocked = self.connecting = False
        self.rssi, self.battery, self.uuids = None, None, []

    @property
    def title(self):
        return self.alias or self.name or self.address

    @property
    def kind(self):
        return BT_KINDS.get(self.icon, "Device")


class Bluetooth:
    """BlueZ client with live updates. each listener (`on_change`, `add_listener`) is called (coalesced) whenever the adapter or any device changes.
    `agent_ui` (optional) is an object with methods confirm(device_title, passkey, reply(bool)), pin(device_title, reply(str|None)),
    passkey(device_title, reply(int|None)), authorize(device_title, reply(bool)), display(device_title, code) - it makes pairing keyboards
    and phones possible; without it only 'just works' devices (most headphones and speakers) can pair."""

    def __init__(self, on_change=None, agent_ui=None):
        self.listeners = [on_change] if on_change else []
        self.agent_ui = agent_ui
        self.bus = None
        self.adapter_path = None
        self.adapter = {}
        self.devices = {}
        self.available = False          # BlueZ is on the bus and has an adapter
        self.service_missing = False    # BlueZ itself is not running / installed
        self._subs = []
        self._pending = False
        self._agent_reg = None
        self._agent_id = None
        self._started = False

    # ---------------------------------------------------------------- lifecycle
    def add_listener(self, fn):
        if fn not in self.listeners:
            self.listeners.append(fn)

    def remove_listener(self, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)

    def start(self):
        if self._started:
            return
        self._started = True
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            self.service_missing = True
            self._changed(); return
        s = self.bus.signal_subscribe(BLUEZ, IF_OM, "InterfacesAdded", None, None, Gio.DBusSignalFlags.NONE, self._on_added)
        s2 = self.bus.signal_subscribe(BLUEZ, IF_OM, "InterfacesRemoved", None, None, Gio.DBusSignalFlags.NONE, self._on_removed)
        s3 = self.bus.signal_subscribe(BLUEZ, IF_PROPS, "PropertiesChanged", None, None, Gio.DBusSignalFlags.NONE, self._on_props)
        s4 = self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", None, BLUEZ, Gio.DBusSignalFlags.NONE,
                                       lambda *a: (self._agent_forget(), GLib.timeout_add(300, lambda: (self.reload(), False)[1])))
        self._subs = [s, s2, s3, s4]
        self.reload()

    def stop(self):
        if self.bus:
            for s in self._subs:
                self.bus.signal_unsubscribe(s)
        self._subs = []
        self.unregister_agent()
        self._started = False

    def reload(self):
        """Read the whole object tree again (after BlueZ restarts, or when the first read happened before BlueZ was up)."""
        if not self.bus:
            return

        def done(src, res):
            try:
                tree = self.bus.call_finish(res).unpack()[0]
            except GLib.Error:
                self.available, self.service_missing = False, True
                self.adapter_path, self.adapter, self.devices = None, {}, {}
                self._changed(); return
            self.service_missing = False
            self.adapter_path, self.adapter, self.devices = None, {}, {}
            for path, ifs in tree.items():
                if IF_ADAPTER in ifs and self.adapter_path is None:
                    self.adapter_path, self.adapter = path, dict(ifs[IF_ADAPTER])
                if IF_DEVICE in ifs:
                    self._set_dev(path, ifs[IF_DEVICE])
            for path, ifs in tree.items():
                if "org.bluez.Battery1" in ifs and path in self.devices:
                    self.devices[path].battery = int(ifs["org.bluez.Battery1"].get("Percentage", 0))
            self.available = self.adapter_path is not None
            if self.available and self.agent_ui is not None:
                self.register_agent()
            self._changed()
        self.bus.call(BLUEZ, "/", IF_OM, "GetManagedObjects", None, GLib.VariantType.new("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 4000, None, done)

    def _set_dev(self, path, props):
        d = self.devices.get(path) or BtDevice(path)
        m = {"Address": "address", "Name": "name", "Alias": "alias", "Icon": "icon", "Paired": "paired", "Trusted": "trusted",
             "Connected": "connected", "RSSI": "rssi", "Blocked": "blocked", "UUIDs": "uuids"}
        for k, v in props.items():
            if k in m:
                setattr(d, m[k], v)
        self.devices[path] = d
        return d

    def _changed(self):
        if self._pending:
            return
        self._pending = True

        def fire():
            self._pending = False
            for fn in list(self.listeners):
                try:
                    fn()
                except Exception:
                    import traceback
                    traceback.print_exc()
            return False
        GLib.timeout_add(120, fire)

    # ---------------------------------------------------------------- signals
    def _on_added(self, conn, sender, path, iface, sig, params, *a):
        opath, ifs = params.unpack()
        if IF_ADAPTER in ifs and self.adapter_path is None:
            self.adapter_path, self.adapter, self.available, self.service_missing = opath, dict(ifs[IF_ADAPTER]), True, False
            if self.agent_ui is not None:
                self.register_agent()
        if IF_DEVICE in ifs:
            self._set_dev(opath, ifs[IF_DEVICE])
        if "org.bluez.Battery1" in ifs and opath in self.devices:
            self.devices[opath].battery = int(ifs["org.bluez.Battery1"].get("Percentage", 0))
        self._changed()

    def _on_removed(self, conn, sender, path, iface, sig, params, *a):
        opath, ifs = params.unpack()
        if IF_ADAPTER in ifs and opath == self.adapter_path:
            self.adapter_path, self.adapter, self.available = None, {}, False
            self.devices = {}
        if IF_DEVICE in ifs:
            self.devices.pop(opath, None)
        self._changed()

    def _on_props(self, conn, sender, path, iface, sig, params, *a):
        which, changed, _inv = params.unpack()
        if which == IF_ADAPTER and path == self.adapter_path:
            self.adapter.update(changed)
        elif which == IF_DEVICE:
            if path in self.devices:
                self._set_dev(path, changed)
            else:
                self.reload(); return
        elif which == "org.bluez.Battery1" and path in self.devices and "Percentage" in changed:
            self.devices[path].battery = int(changed["Percentage"])
        else:
            return
        self._changed()

    # ---------------------------------------------------------------- state
    @property
    def powered(self):
        return bool(self.adapter.get("Powered"))

    @property
    def discovering(self):
        return bool(self.adapter.get("Discovering"))

    @property
    def name(self):
        return self.adapter.get("Alias") or self.adapter.get("Name") or "This computer"

    @property
    def discoverable(self):
        return bool(self.adapter.get("Discoverable"))

    def paired_devices(self):
        return sorted((d for d in self.devices.values() if d.paired), key=lambda d: (not d.connected, d.title.lower()))

    def nearby_devices(self):
        """Seen during a scan, not paired yet. Nameless ones (just a MAC address) are hidden: they are almost always beacons."""
        out = [d for d in self.devices.values() if not d.paired and (d.name or d.alias) and d.alias != d.address.replace(":", "-")]
        return sorted(out, key=lambda d: (-(d.rssi if d.rssi is not None else -200), d.title.lower()))

    def connected_devices(self):
        return [d for d in self.devices.values() if d.connected]

    # ---------------------------------------------------------------- calls
    def _call(self, path, iface, method, params, cb=None, timeout=30000):
        if self.bus is None or (path != "/org/bluez" and not self.available):
            if cb:
                GLib.idle_add(lambda: (cb(False, "Bluetooth is not available"), False)[1])
            return

        def done(src, res):
            try:
                self.bus.call_finish(res)
                if cb:
                    cb(True, "")
            except GLib.Error as e:
                if cb:
                    cb(False, bt_error_text(e.message))
        self.bus.call(BLUEZ, path, iface, method, params, None, Gio.DBusCallFlags.NONE, timeout, None, done)

    def _set_prop(self, path, iface, name, variant, cb=None):
        self._call(path, IF_PROPS, "Set", GLib.Variant("(ssv)", (iface, name, variant)), cb)

    def set_power(self, on, cb=None):
        """Power the adapter, clearing a soft rfkill block first. cb(ok, message)."""
        if not self.available:
            if cb:
                GLib.idle_add(lambda: (cb(False, "No Bluetooth adapter"), False)[1])
            return
        st = rfkill_state("bluetooth")
        if on and st["hard"]:
            if cb:
                GLib.idle_add(lambda: (cb(False, "Bluetooth is switched off by a hardware key or switch"), False)[1])
            return
        if not on and self.discovering:
            self.stop_scan()
        if on and st["soft"]:
            rfkill_set("bluetooth", False)
            GLib.timeout_add(250, lambda: (self._set_prop(self.adapter_path, IF_ADAPTER, "Powered", GLib.Variant("b", True), cb), False)[1])
            return
        self._set_prop(self.adapter_path, IF_ADAPTER, "Powered", GLib.Variant("b", on), cb)

    def start_scan(self, cb=None):
        if not (self.available and self.powered):
            if cb:
                GLib.idle_add(lambda: (cb(False, "Bluetooth is off"), False)[1])
            return
        self._call(self.adapter_path, IF_ADAPTER, "StartDiscovery", None, lambda ok, msg: cb and cb(ok or "inprogress" in msg.lower(), msg))

    def stop_scan(self, cb=None):
        if self.available and self.discovering:
            self._call(self.adapter_path, IF_ADAPTER, "StopDiscovery", None, lambda ok, msg: cb and cb(True, ""))

    def set_discoverable(self, on, cb=None):
        self._set_prop(self.adapter_path, IF_ADAPTER, "Discoverable", GLib.Variant("b", on), cb)

    def rename_adapter(self, name, cb=None):
        self._set_prop(self.adapter_path, IF_ADAPTER, "Alias", GLib.Variant("s", name), cb)

    def connect_device(self, d, cb):
        d.connecting = True
        self._changed()

        def done(ok, msg):
            d.connecting = False
            self._changed()
            cb(ok or "already connected" in msg.lower(), "" if "already connected" in msg.lower() else msg)
        self._call(d.path, IF_DEVICE, "Connect", None, done, timeout=40000)

    def disconnect_device(self, d, cb):
        d.connecting = True
        self._changed()

        def done(ok, msg):
            d.connecting = False
            self._changed()
            cb(ok, msg)
        self._call(d.path, IF_DEVICE, "Disconnect", None, done, timeout=15000)

    def pair(self, d, cb):
        """Pair, trust (so it reconnects by itself) and connect. cb(ok, message)."""
        d.connecting = True
        self.stop_scan()
        self._changed()

        def fail(msg):
            d.connecting = False
            self._changed()
            cb(False, msg)

        def after_pair(ok, msg):
            if not ok and "already paired" not in msg.lower():
                fail(msg); return
            self._set_prop(d.path, IF_DEVICE, "Trusted", GLib.Variant("b", True), lambda *_: self._call(
                d.path, IF_DEVICE, "Connect", None, lambda ok2, msg2: (setattr(d, "connecting", False), self._changed(),
                                                                         cb(True, "" if (ok2 or "already connected" in msg2.lower()) else "Paired, but not connected: " + msg2))[2], timeout=40000))
        self._call(d.path, IF_DEVICE, "Pair", None, after_pair, timeout=60000)

    def cancel_pairing(self, d):
        self._call(d.path, IF_DEVICE, "CancelPairing", None)

    def forget(self, d, cb=None):
        if d.connected:
            self._call(d.path, IF_DEVICE, "Disconnect", None, lambda *_: self._remove(d, cb))
        else:
            self._remove(d, cb)

    def _remove(self, d, cb):
        self._call(self.adapter_path, IF_ADAPTER, "RemoveDevice", GLib.Variant("(o)", (d.path,)), cb)

    def set_trusted(self, d, on, cb=None):
        self._set_prop(d.path, IF_DEVICE, "Trusted", GLib.Variant("b", on), cb)

    def rename(self, d, name, cb=None):
        self._set_prop(d.path, IF_DEVICE, "Alias", GLib.Variant("s", name), cb)

    def block(self, d, on, cb=None):
        self._set_prop(d.path, IF_DEVICE, "Blocked", GLib.Variant("b", on), cb)

    # ---------------------------------------------------------------- pairing agent
    def register_agent(self):
        """Answer BlueZ's pairing questions (PIN, passkey confirmation) through agent_ui. Safe to call repeatedly."""
        if self._agent_reg is not None or not self.bus or not self.available or self.agent_ui is None:
            return
        try:
            node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            self._agent_id = self.bus.register_object(AGENT_PATH, node.interfaces[0], self._agent_call, None, None)
        except GLib.Error:
            return
        self._agent_reg = True

        def reg(ok, msg):
            if ok:
                self._call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", GLib.Variant("(o)", (AGENT_PATH,)))
        self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), reg)

    def _agent_forget(self):
        """BlueZ restarted (or went away): its registration of our agent is gone, drop the local half so it is registered afresh."""
        if self._agent_id and self.bus:
            try:
                self.bus.unregister_object(self._agent_id)
            except Exception:
                pass
        self._agent_reg = self._agent_id = None

    def unregister_agent(self):
        if self._agent_reg and self.bus:
            self._call("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", GLib.Variant("(o)", (AGENT_PATH,)))
            if self._agent_id:
                self.bus.unregister_object(self._agent_id)
        self._agent_reg = self._agent_id = None

    def _title(self, path):
        d = self.devices.get(path)
        return d.title if d else "this device"

    def _agent_call(self, conn, sender, path, iface, method, params, inv):
        ui, args = self.agent_ui, params.unpack()
        dev = self._title(args[0]) if args and isinstance(args[0], str) else ""

        def err(name, text):
            inv.return_dbus_error("org.bluez.Error." + name, text)
        if ui is None or method in ("Release", "Cancel"):
            if method in ("Release", "Cancel"):
                if ui is not None and hasattr(ui, "cancel"):
                    ui.cancel()
                inv.return_value(None)
            else:
                err("Rejected", "No pairing UI")
            return
        try:
            if method == "RequestConfirmation":
                ui.confirm(dev, "%06d" % args[1], lambda yes: inv.return_value(None) if yes else err("Rejected", "Declined"))
            elif method == "RequestAuthorization":
                ui.authorize(dev, lambda yes: inv.return_value(None) if yes else err("Rejected", "Declined"))
            elif method == "AuthorizeService":
                d = self.devices.get(args[0])
                if d is not None and d.trusted:
                    inv.return_value(None)
                else:
                    ui.authorize(dev, lambda yes: inv.return_value(None) if yes else err("Rejected", "Declined"))
            elif method == "RequestPinCode":
                ui.pin(dev, lambda v: inv.return_value(GLib.Variant("(s)", (v,))) if v else err("Canceled", "Cancelled"))
            elif method == "RequestPasskey":
                ui.passkey(dev, lambda v: inv.return_value(GLib.Variant("(u)", (int(v),))) if v is not None else err("Canceled", "Cancelled"))
            elif method == "DisplayPinCode":
                ui.display(dev, args[1]); inv.return_value(None)
            elif method == "DisplayPasskey":
                ui.display(dev, "%06d" % args[1]); inv.return_value(None)
            else:
                err("Rejected", "Unsupported")
        except Exception:
            err("Failed", "Pairing UI failed")
