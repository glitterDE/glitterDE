"""System information for SparkMonitor: processes, CPU, memory, disks, network, sensors, filesystems.

Reads /proc and /sys only (no GTK, no third-party libraries). Every reader takes its root directory as an argument so the parsers can be
tested against a synthetic tree. Rates (CPU %, bytes/s) are computed from the difference between two polls, so the first poll of a
Sampler / ProcessTable reports zero rates.
"""
import errno
import os
import pwd
import re
import signal
import time

CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

STATES = {"R": "Running", "S": "Sleeping", "D": "Waiting (disk)", "T": "Stopped", "t": "Stopped (tracing)", "Z": "Zombie", "I": "Idle",
          "X": "Dead", "x": "Dead", "K": "Wakekill", "W": "Waking", "P": "Parked"}


def read(path, default=""):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return default


# ------------------------------------------------------------------------------------------------------------------------ formatting
def fmt_bytes(n, digits=1):
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.*f %s" % (digits, n, unit))
        n /= 1024.0


def fmt_rate(n):
    return fmt_bytes(n) + "/s"


def fmt_bits(n):
    """Network rates in bits per second (the unit link speeds are quoted in)."""
    n = float(n) * 8
    for unit in ("bit/s", "Kbit/s", "Mbit/s", "Gbit/s"):
        if n < 1000 or unit == "Gbit/s":
            return ("%d %s" % (n, unit)) if unit == "bit/s" else ("%.1f %s" % (n, unit))
        n /= 1000.0


def fmt_duration(sec):
    sec = int(max(0, sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%dd %02dh %02dm" % (d, h, m)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def fmt_hz(mhz):
    return "%.2f GHz" % (mhz / 1000.0) if mhz >= 1000 else "%d MHz" % mhz


# ------------------------------------------------------------------------------------------------------------------------ processes
def parse_stat(text):
    """Fields of /proc/<pid>/stat as a dict. The command name sits in parentheses and may itself contain spaces and parentheses."""
    i, j = text.find("("), text.rfind(")")
    if i < 0 or j < i:
        raise ValueError("bad stat")
    f = text[j + 2:].split()
    return {"pid": int(text[:i]), "comm": text[i + 1:j], "state": f[0], "ppid": int(f[1]), "utime": int(f[11]), "stime": int(f[12]),
            "nice": int(f[16]), "threads": int(f[17]), "start": int(f[19]), "vsize": int(f[20])}


def parse_statm(text):
    p = text.split()
    return int(p[1]) * PAGE, int(p[2]) * PAGE                    # resident, shared (bytes)


_INTERP = re.compile(r"^(python[\d.]*|perl[\d.]*|ruby[\d.]*|node(js)?|java|php[\d.]*|lua[\d.]*|bash|sh|dash|zsh|fish|wish|tclsh[\d.]*)$")


def display_name(comm, argv):
    """The name shown in the list. comm is cut at 15 characters, and every script is called python3 / bash: look at the command line."""
    if not argv:
        return comm
    exe = os.path.basename(argv[0])
    if _INTERP.match(comm.lower()) or _INTERP.match(exe.lower()):
        i = 1
        while i < len(argv) and argv[i].startswith("-"):
            if argv[i] == "-c":
                return comm                                        # bash -c "some command": not a script name
            if argv[i] == "-m" and i + 1 < len(argv):
                return argv[i + 1].split(".")[0]
            i += 1
        if i < len(argv):
            script = os.path.basename(argv[i])
            if script and not script.startswith(("-", "<")):
                return script
        return comm
    if exe.startswith(comm) and len(exe) > len(comm):
        return exe
    return comm


class Proc:
    __slots__ = ("pid", "ppid", "name", "cmd", "user", "uid", "state", "nice", "threads", "start", "mem", "rss", "shared", "virt", "ticks",
                 "cpu", "io", "kernel", "comm")

    def __repr__(self):
        return "<Proc %d %s cpu=%.1f mem=%d>" % (self.pid, self.name, self.cpu, self.mem)


_users = {}


def username(uid):
    n = _users.get(uid)
    if n is None:
        try:
            n = pwd.getpwuid(uid).pw_name
        except KeyError:
            n = str(uid)
        _users[uid] = n
    return n


class ProcessTable:
    """poll() -> [Proc]. CPU % is of ONE core (a busy 4-thread process shows 400); `io` is bytes/s read+written, None when unreadable."""

    def __init__(self, root="/proc"):
        self.root = root
        self._static = {}                    # pid -> (start, name, cmd, uid, kernel)
        self._prev = {}                      # pid -> (start, ticks, io_bytes)
        self._t = None

    def poll(self):
        now = time.monotonic()
        dt = (now - self._t) if self._t is not None else None
        self._t = now
        out, prev_new = [], {}
        try:
            names = os.listdir(self.root)
        except OSError:
            return out
        for n in names:
            if not n.isdigit():
                continue
            try:
                p = self._read(int(n), dt, prev_new)
            except (OSError, ValueError, IndexError):
                continue                      # it exited while we looked at it
            if p is not None:
                out.append(p)
        self._prev = prev_new
        self._static = {pid: v for pid, v in self._static.items() if pid in prev_new}
        return out

    def _read(self, pid, dt, prev_new):
        base = "%s/%d" % (self.root, pid)
        st = parse_stat(read(base + "/stat") or "x")
        info = self._static.get(pid)
        if info is None or info[0] != st["start"]:
            raw = read(base + "/cmdline")
            argv = [a for a in raw.split("\0") if a] if raw else []
            kernel = st["ppid"] == 2 or pid == 2
            name = display_name(st["comm"], argv)
            cmd = " ".join(argv) if argv else "[%s]" % st["comm"]
            try:
                uid = os.stat(base).st_uid
            except OSError:
                uid = 0
            info = self._static[pid] = (st["start"], name, cmd, uid, kernel)
        _, name, cmd, uid, kernel = info
        resident, shared = 0, 0
        try:
            resident, shared = parse_statm(read(base + "/statm"))
        except (ValueError, IndexError):
            pass
        io_bytes = None
        txt = read(base + "/io")
        if txt:
            rb = wb = 0
            for ln in txt.splitlines():
                if ln.startswith("read_bytes:"):
                    rb = int(ln.split()[1])
                elif ln.startswith("write_bytes:"):
                    wb = int(ln.split()[1])
            io_bytes = rb + wb
        ticks = st["utime"] + st["stime"]
        prev_new[pid] = (st["start"], ticks, io_bytes)
        cpu, io = 0.0, None
        pv = self._prev.get(pid)
        if pv is not None and pv[0] == st["start"] and dt:
            cpu = max(0.0, (ticks - pv[1]) / (CLK * dt) * 100.0)
            if io_bytes is not None and pv[2] is not None:
                io = max(0.0, (io_bytes - pv[2]) / dt)
        p = Proc()
        p.pid, p.ppid, p.name, p.cmd, p.uid, p.user = pid, st["ppid"], name, cmd, uid, username(uid)
        p.comm, p.state, p.nice, p.threads, p.start = st["comm"], st["state"], st["nice"], st["threads"], st["start"]
        p.rss, p.shared, p.virt, p.mem = resident, shared, st["vsize"], max(0, resident - shared)
        p.ticks, p.cpu, p.io, p.kernel = ticks, cpu, io, kernel
        return p

    def details(self, pid):
        """Extra, slower-to-read facts about one process for the Properties window ({} when it has gone)."""
        base = "%s/%d" % (self.root, pid)
        d = {}
        try:
            d["exe"] = os.readlink(base + "/exe")
        except OSError:
            d["exe"] = ""
        try:
            d["cwd"] = os.readlink(base + "/cwd")
        except OSError:
            d["cwd"] = ""
        try:
            d["fds"] = len(os.listdir(base + "/fd"))
        except OSError:
            d["fds"] = None
        for ln in read(base + "/status").splitlines():
            k, _, v = ln.partition(":")
            if k in ("VmPeak", "VmSwap", "VmHWM", "RssAnon", "RssFile", "RssShmem", "Threads", "voluntary_ctxt_switches", "State"):
                d[k] = v.strip()
        return d


def boot_time(root="/proc"):
    try:
        return time.time() - float(read(root + "/uptime", "0").split()[0])
    except (ValueError, IndexError):
        return time.time()


def signal_process(pid, start, sig, root="/proc"):
    """Send `sig` to pid, but only if it is still the process the list showed (same start time): a recycled PID is never signalled.
    Uses a pidfd where available so there is no race between the check and the signal. Returns (ok, message)."""
    fd = None
    try:
        if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            try:
                fd = os.pidfd_open(pid)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    return False, "The process has already exited."
                fd = None
        try:
            cur = parse_stat(read("%s/%d/stat" % (root, pid)) or "x")
        except ValueError:
            return False, "The process has already exited."
        if start is not None and cur["start"] != start:
            return False, "That process has already exited (its number was reused)."
        if fd is not None:
            signal.pidfd_send_signal(fd, sig)
        else:
            os.kill(pid, sig)
        return True, ""
    except ProcessLookupError:
        return False, "The process has already exited."
    except PermissionError:
        return False, "Not permitted: this process belongs to another user."
    except OSError as e:
        return False, e.strerror or str(e)
    finally:
        if fd is not None:
            os.close(fd)


def set_nice(pid, value, root="/proc"):
    """Set the nice value of every thread of a process (setpriority only affects one thread at a time on Linux)."""
    try:
        tids = [int(t) for t in os.listdir("%s/%d/task" % (root, pid))] or [pid]
    except OSError:
        return False, "The process has already exited."
    try:
        for t in tids:
            os.setpriority(os.PRIO_PROCESS, t, value)
        return True, ""
    except PermissionError:
        return False, "Raising a priority, or changing another user's process, needs administrator rights."
    except ProcessLookupError:
        return False, "The process has already exited."
    except OSError as e:
        return False, e.strerror or str(e)


# ------------------------------------------------------------------------------------------------------------------------ system-wide
def parse_meminfo(text):
    d = {}
    for ln in text.splitlines():
        k, _, v = ln.partition(":")
        try:
            d[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return d


def memory(root="/proc"):
    d = parse_meminfo(read(root + "/meminfo"))
    total = d.get("MemTotal", 0)
    free = d.get("MemFree", 0)
    avail = min(total, d.get("MemAvailable", free + d.get("Cached", 0) + d.get("Buffers", 0)))
    used = max(0, total - avail)
    cache = max(0, avail - free)
    st, sf = d.get("SwapTotal", 0), d.get("SwapFree", 0)
    return {"total": total, "used": used, "free": free, "available": avail, "cache": cache, "cached": d.get("Cached", 0),
            "buffers": d.get("Buffers", 0), "shared": d.get("Shmem", 0), "swap_total": st, "swap_used": max(0, st - sf),
            "dirty": d.get("Dirty", 0), "active": d.get("Active", 0), "inactive": d.get("Inactive", 0)}


def cpu_model(root="/proc"):
    model, cores = "", 0
    for ln in read(root + "/cpuinfo").splitlines():
        k, _, v = ln.partition(":")
        k = k.strip()
        if k in ("model name", "Model", "Hardware", "cpu model") and not model:
            model = v.strip()
        elif k == "processor":
            cores += 1
    return " ".join(model.split()) or "Processor", cores or (os.cpu_count() or 1)


def loadavg(root="/proc"):
    p = read(root + "/loadavg").split()
    try:
        return float(p[0]), float(p[1]), float(p[2])
    except (ValueError, IndexError):
        return 0.0, 0.0, 0.0


def uptime(root="/proc"):
    try:
        return float(read(root + "/uptime", "0").split()[0])
    except (ValueError, IndexError):
        return 0.0


def counts(procs):
    return len(procs), sum(p.threads for p in procs)


def cpu_freqs(sysroot="/sys", root="/proc"):
    """Current frequency of every logical CPU in MHz (cpufreq, else /proc/cpuinfo)."""
    out = []
    base = sysroot + "/devices/system/cpu"
    try:
        cpus = sorted((n for n in os.listdir(base) if n.startswith("cpu") and n[3:].isdigit()), key=lambda n: int(n[3:]))
    except OSError:
        cpus = []
    for n in cpus:
        v = read("%s/%s/cpufreq/scaling_cur_freq" % (base, n)).strip()
        if v.isdigit():
            out.append(int(v) / 1000.0)
    if not out:
        for ln in read(root + "/cpuinfo").splitlines():
            if ln.lower().startswith("cpu mhz"):
                try:
                    out.append(float(ln.split(":")[1]))
                except (ValueError, IndexError):
                    pass
    return out


def cpu_freq_limits(sysroot="/sys"):
    base = sysroot + "/devices/system/cpu/cpu0/cpufreq/"
    lo, hi = read(base + "cpuinfo_min_freq").strip(), read(base + "cpuinfo_max_freq").strip()
    return (int(lo) / 1000.0 if lo.isdigit() else None), (int(hi) / 1000.0 if hi.isdigit() else None)


def temperatures(sysroot="/sys"):
    """[(group, label, celsius)] from hwmon and thermal zones."""
    out = []
    hw = sysroot + "/class/hwmon"
    try:
        chips = sorted(os.listdir(hw))
    except OSError:
        chips = []
    for c in chips:
        base = "%s/%s" % (hw, c)
        name = read(base + "/name").strip() or c
        try:
            files = sorted(f for f in os.listdir(base) if f.startswith("temp") and f.endswith("_input"))
        except OSError:
            continue
        for f in files:
            v = read("%s/%s" % (base, f)).strip()
            try:
                t = int(v) / 1000.0
            except ValueError:
                continue
            if not -40 < t < 160:
                continue
            label = read("%s/%s" % (base, f.replace("_input", "_label"))).strip() or f[:-6].replace("temp", "Sensor ")
            out.append((name, label, t))
    if not out:
        tz = sysroot + "/class/thermal"
        try:
            zones = sorted(z for z in os.listdir(tz) if z.startswith("thermal_zone"))
        except OSError:
            zones = []
        for z in zones:
            v = read("%s/%s/temp" % (tz, z)).strip()
            try:
                t = int(v) / 1000.0
            except ValueError:
                continue
            if -40 < t < 160:
                out.append(("thermal", read("%s/%s/type" % (tz, z)).strip() or z, t))
    return out


def cpu_temperature(temps):
    """The temperature to show next to the processor: package / die sensors first."""
    for group, label, t in temps:
        if group in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "x86_pkg_temp") and any(
                k in label.lower() for k in ("package", "tctl", "tdie", "cpu", "soc")):
            return t
    for group, label, t in temps:
        if group in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "x86_pkg_temp"):
            return t
    return None


VIRTUAL_NETS = ("veth", "docker", "br-", "virbr", "tun", "tap", "wg", "tailscale", "vboxnet", "vmnet", "lo", "dummy", "ifb", "bond", "sit", "ip6tnl")


def net_kind(name, sysroot="/sys"):
    base = "%s/class/net/%s" % (sysroot, name)
    if os.path.isdir(base + "/wireless") or os.path.isdir(base + "/phy80211"):
        return "wifi"
    if os.path.exists(base + "/device") and not name.startswith(VIRTUAL_NETS):
        return "ethernet"
    return "virtual"


class Sampler:
    """Rates for the whole machine: CPU, disks, network. Call each method once per refresh."""

    def __init__(self, root="/proc", sysroot="/sys"):
        self.root, self.sysroot = root, sysroot
        self._cpu = None
        self._disk = None
        self._net = None

    # ------------------------------------------------------------------ cpu
    def cpu(self):
        """{'total': 0..1, 'cores': [0..1, ...], 'user', 'system', 'iowait'} since the previous call."""
        cur = {}
        for ln in read(self.root + "/stat").splitlines():
            if ln.startswith("cpu"):
                p = ln.split()
                try:
                    v = [int(x) for x in p[1:]]
                except ValueError:
                    continue
                v += [0] * (10 - len(v))
                idle, tot = v[3] + v[4], sum(v[:8])           # guest time is already inside user / nice
                cur[p[0]] = (idle, tot, v[0] + v[1], v[2], v[4])
        prev, self._cpu = self._cpu, cur
        res = {"total": 0.0, "cores": [], "user": 0.0, "system": 0.0, "iowait": 0.0}

        def frac(k):
            if not prev or k not in prev or k not in cur or cur[k][1] <= prev[k][1]:
                return None
            dt = cur[k][1] - prev[k][1]
            return max(0.0, min(1.0, 1 - (cur[k][0] - prev[k][0]) / dt)), dt
        t = frac("cpu")
        if t:
            res["total"] = t[0]
            dt = t[1]
            res["user"] = max(0.0, (cur["cpu"][2] - prev["cpu"][2]) / dt)
            res["system"] = max(0.0, (cur["cpu"][3] - prev["cpu"][3]) / dt)
            res["iowait"] = max(0.0, (cur["cpu"][4] - prev["cpu"][4]) / dt)
        n = sorted((k for k in cur if k != "cpu" and k[3:].isdigit()), key=lambda k: int(k[3:]))
        res["cores"] = [(frac(k) or (0.0,))[0] for k in n]
        return res

    # ------------------------------------------------------------------ disks
    def _whole_disks(self):
        try:
            names = set(os.listdir(self.sysroot + "/block"))
        except OSError:
            return None
        return {n for n in names if not n.startswith(("loop", "ram", "zram", "dm-", "md", "fd", "sr", "nbd"))}

    def disks(self):
        """{'devices': {name: {read, write, busy, read_total, write_total}}, 'read': B/s, 'write': B/s, 'busy': 0..1}"""
        whole = self._whole_disks()
        cur = {}
        for ln in read(self.root + "/diskstats").splitlines():
            p = ln.split()
            if len(p) < 13:
                continue
            name = p[2]
            if whole is not None and name not in whole:
                continue
            try:
                cur[name] = (int(p[5]) * 512, int(p[9]) * 512, int(p[12]))
            except ValueError:
                continue
        now = time.monotonic()
        prev, self._disk = self._disk, (now, cur)
        devs, tr, tw, busy = {}, 0.0, 0.0, 0.0
        for name, (rb, wb, ticks) in cur.items():
            d = {"read": 0.0, "write": 0.0, "busy": 0.0, "read_total": rb, "write_total": wb}
            if prev and name in prev[1] and now > prev[0]:
                dt = now - prev[0]
                pr, pw, pt = prev[1][name]
                d["read"], d["write"] = max(0.0, (rb - pr) / dt), max(0.0, (wb - pw) / dt)
                d["busy"] = max(0.0, min(1.0, (ticks - pt) / (dt * 1000.0)))
            devs[name] = d
            tr, tw, busy = tr + d["read"], tw + d["write"], max(busy, d["busy"])
        return {"devices": devs, "read": tr, "write": tw, "busy": busy}

    # ------------------------------------------------------------------ network
    def network(self):
        """{'ifaces': {name: {rx, tx, rx_total, tx_total, rx_pkts, tx_pkts, rx_err, tx_err, up, kind, speed}}, 'rx': B/s, 'tx': B/s}
        The totals count the physical-looking links only (bridges, veth pairs and VPN tunnels would count the same bytes twice)."""
        cur = {}
        for ln in read(self.root + "/net/dev").splitlines()[2:]:
            name, _, data = ln.partition(":")
            c = data.split()
            if len(c) < 16:
                continue
            try:
                cur[name.strip()] = (int(c[0]), int(c[8]), int(c[1]), int(c[9]), int(c[2]), int(c[10]))
            except ValueError:
                continue
        now = time.monotonic()
        prev, self._net = self._net, (now, cur)
        ifaces, trx, ttx = {}, 0.0, 0.0
        for name, (rx, tx, rp, tp, re_, te) in cur.items():
            if name == "lo":
                continue
            kind = net_kind(name, self.sysroot)
            base = "%s/class/net/%s/" % (self.sysroot, name)
            speed = read(base + "speed").strip()
            d = {"rx": 0.0, "tx": 0.0, "rx_total": rx, "tx_total": tx, "rx_pkts": rp, "tx_pkts": tp, "rx_err": re_, "tx_err": te,
                 "up": read(base + "operstate").strip() in ("up", "unknown") and (rx or tx or kind != "virtual"), "kind": kind,
                 "speed": int(speed) if speed.lstrip("-").isdigit() and int(speed) > 0 else None}
            if prev and name in prev[1] and now > prev[0]:
                dt = now - prev[0]
                d["rx"], d["tx"] = max(0.0, (rx - prev[1][name][0]) / dt), max(0.0, (tx - prev[1][name][1]) / dt)
            ifaces[name] = d
            if kind != "virtual":
                trx, ttx = trx + d["rx"], ttx + d["tx"]
        if not any(i["kind"] != "virtual" for i in ifaces.values()):          # a machine with only virtual links: count them all
            trx, ttx = sum(i["rx"] for i in ifaces.values()), sum(i["tx"] for i in ifaces.values())
        return {"ifaces": ifaces, "rx": trx, "tx": ttx}


# ------------------------------------------------------------------------------------------------------------------------ filesystems
PSEUDO_FS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "securityfs", "debugfs", "tracefs", "configfs", "fusectl",
             "pstore", "bpf", "mqueue", "hugetlbfs", "autofs", "binfmt_misc", "overlay", "squashfs", "ramfs", "efivarfs", "nsfs", "rpc_pipefs",
             "fuse.portal", "fuse.gvfsd-fuse", "fuse.lxcfs"}


def _unescape(s):
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def filesystems(root="/proc"):
    """[{'device', 'mount', 'type', 'total', 'used', 'free'}] for the real (disk, network) filesystems, one entry per device."""
    seen, out = set(), []
    for ln in read(root + "/mounts").splitlines():
        p = ln.split()
        if len(p) < 3:
            continue
        dev, mnt, fs = _unescape(p[0]), _unescape(p[1]), p[2]
        if fs in PSEUDO_FS or mnt.startswith(("/snap/", "/var/lib/docker", "/run/", "/sys", "/proc", "/dev")):
            continue
        if not (dev.startswith("/dev/") or fs.startswith(("nfs", "cifs", "smb", "fuse.", "9p", "zfs", "btrfs"))):
            continue
        if dev.startswith("/dev/loop"):
            continue
        key = dev if dev.startswith("/dev/") else dev + mnt
        if key in seen:
            continue
        seen.add(key)
        try:
            s = os.statvfs(mnt)
        except OSError:
            continue
        total = s.f_blocks * s.f_frsize
        if total <= 0:
            continue
        free = s.f_bavail * s.f_frsize
        out.append({"device": dev, "mount": mnt, "type": fs, "total": total, "free": free, "used": total - (s.f_bfree * s.f_frsize)})
    out.sort(key=lambda f: (f["mount"] != "/", f["mount"]))
    return out
