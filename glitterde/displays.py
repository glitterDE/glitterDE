"""Display configuration through xrandr"""
import json
import os
import re
import shutil
import subprocess
import sys

from . import config

ROTATIONS = [("normal", "Landscape"), ("left", "Portrait (left)"), ("inverted", "Landscape (flipped)"), ("right", "Portrait (right)")]
POSITIONS = [("right-of", "Right of"), ("left-of", "Left of"), ("above", "Above"), ("below", "Below")]


class Mode:
    def __init__(self, w, h, rates, current=None, preferred=None):
        self.w, self.h, self.rates = w, h, rates          # rates: [float, ...] highest first
        self.current, self.preferred = current, preferred  # the rate that is in use / preferred, or None

    @property
    def key(self):
        return "%dx%d" % (self.w, self.h)

    def label(self):
        return "%d × %d" % (self.w, self.h)


class Output:
    def __init__(self, name):
        self.name = name
        self.connected = False
        self.primary = False
        self.x = self.y = 0
        self.w = self.h = 0                 # geometry on screen (already rotated)
        self.rotation = "normal"
        self.modes = []
        self.mode_key = None                # the mode in use ("1920x1080") or None when the output is off
        self.rate = None
        self.model = ""

    @property
    def enabled(self):
        return self.connected and self.mode_key is not None

    def mode(self, key):
        for m in self.modes:
            if m.key == key:
                return m
        return None

    def preferred(self):
        for m in self.modes:
            if m.preferred is not None:
                return m, m.preferred
        return (self.modes[0], self.modes[0].rates[0]) if self.modes else (None, None)


def available():
    return shutil.which("xrandr") is not None


def _run(argv, timeout=8):
    env = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env, universal_newlines=True)
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


_HEAD = re.compile(r"^(\S+) (connected|disconnected)(?: (primary))?(?: (\d+)x(\d+)\+(-?\d+)\+(-?\d+))?(?: (normal|left|inverted|right))?")
_MODE = re.compile(r"^\s+(\d+)x(\d+)(?:i)?\s+(.*)$")
_RATE = re.compile(r"([0-9]+(?:\.[0-9]+)?)([*+ ]{0,2})")


def parse(text):
    outs, cur = [], None
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            cur = Output(m.group(1))
            cur.connected = m.group(2) == "connected"
            cur.primary = bool(m.group(3))
            if m.group(4):
                cur.w, cur.h, cur.x, cur.y = int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
            cur.rotation = m.group(8) or "normal"
            outs.append(cur)
            continue
        if cur is None:
            continue
        mm = _MODE.match(line)
        if not mm or not cur.connected:
            continue
        w, h, rest = int(mm.group(1)), int(mm.group(2)), mm.group(3)
        rates, current, pref = [], None, None
        for r in re.finditer(r"([0-9]+(?:\.[0-9]+)?) ?([*+]*)", rest):
            val = float(r.group(1))
            rates.append(val)
            if "*" in r.group(2):
                current = val
            if "+" in r.group(2):
                pref = val
        if not rates:
            continue
        mode = next((x for x in cur.modes if x.w == w and x.h == h), None)
        if mode is None:
            mode = Mode(w, h, [])
            cur.modes.append(mode)
        for v in rates:
            if v not in mode.rates:
                mode.rates.append(v)
        mode.rates.sort(reverse=True)
        if current is not None:
            mode.current = current
            cur.mode_key, cur.rate = mode.key, current
        if pref is not None:
            mode.preferred = pref
    for o in outs:
        o.modes.sort(key=lambda m: (m.w * m.h, m.w), reverse=True)
    return outs


def query():
    """[Output, ...] for every connected output (disconnected ones are left out), or [] when xrandr is missing."""
    if not available():
        return []
    ok, out = _run(["xrandr", "--query"])
    return [o for o in parse(out) if o.connected] if ok else []


def _size(o, mode_key=None, rotation=None):
    key = mode_key or o.mode_key
    m = o.mode(key) if key else None
    if m is None:
        return 0, 0
    rot = rotation or o.rotation
    return (m.h, m.w) if rot in ("left", "right") else (m.w, m.h)


def layout_of(outs):
    """What we persist: {name: {on, mode, rate, rotation, x, y, primary}}"""
    return {o.name: dict(on=o.enabled, mode=o.mode_key, rate=o.rate, rotation=o.rotation, x=o.x, y=o.y, primary=o.primary) for o in outs}


def command(layout, mirror=False):
    """The xrandr argv that produces `layout` (a layout_of() dict)."""
    argv = ["xrandr"]
    first_on = None
    for name, s in layout.items():
        argv += ["--output", name]
        if not s.get("on") or not s.get("mode"):
            argv += ["--off"]
            continue
        argv += ["--mode", s["mode"]]
        if s.get("rate"):
            argv += ["--rate", "%g" % s["rate"]]
        argv += ["--rotate", s.get("rotation") or "normal"]
        if mirror:
            argv += ["--pos", "0x0"]
        else:
            argv += ["--pos", "%dx%d" % (int(s.get("x", 0)), int(s.get("y", 0)))]
        if s.get("primary"):
            argv += ["--primary"]
        first_on = first_on or name
    return argv


def apply_layout(layout, mirror=False):
    """Run xrandr. Returns (ok, message)."""
    if not available():
        return False, "xrandr is not installed (package x11-xserver-utils / xorg-xrandr)."
    if not any(s.get("on") for s in layout.values()):
        return False, "At least one display must stay on."
    ok, msg = _run(command(layout, mirror))
    return ok, msg.strip()


def tidy(layout, outs):
    """Make sure no two enabled outputs overlap and none has a gap: line them up left to right in their current order (used after a change)."""
    order = sorted([n for n, s in layout.items() if s.get("on")], key=lambda n: (layout[n].get("x", 0), layout[n].get("y", 0)))
    by = {o.name: o for o in outs}
    x = 0
    for n in order:
        s = layout[n]
        w, h = _size(by[n], s["mode"], s["rotation"])
        s["x"] = x
        s["y"] = s.get("y", 0) if s.get("y", 0) >= 0 else 0
        x += w
    mn = min([layout[n]["y"] for n in order] or [0])
    for n in order:
        layout[n]["y"] -= mn
    return layout


def place(layout, outs, name, rel, other):
    """Put output `name` next to output `other`: rel in right-of / left-of / above / below."""
    by = {o.name: o for o in outs}
    s, t = layout[name], layout[other]
    sw, sh = _size(by[name], s["mode"], s["rotation"])
    tw, th = _size(by[other], t["mode"], t["rotation"])
    if rel == "right-of":
        s["x"], s["y"] = t["x"] + tw, t["y"]
    elif rel == "left-of":
        s["x"], s["y"] = t["x"] - sw, t["y"]
    elif rel == "above":
        s["x"], s["y"] = t["x"], t["y"] - sh
    elif rel == "below":
        s["x"], s["y"] = t["x"], t["y"] + th
    mx = min(v["x"] for v in layout.values() if v.get("on"))
    my = min(v["y"] for v in layout.values() if v.get("on"))
    for v in layout.values():
        if v.get("on"):
            v["x"] -= mx
            v["y"] -= my
    return layout


def set_primary(layout, name):
    for n, s in layout.items():
        s["primary"] = (n == name)
    return layout


# ------------------------------------------------------------------ persistence
def save(layout):
    config.set("display", "layout", json.dumps(layout, sort_keys=True))


def saved():
    raw = config.load().get("display", {}).get("layout")
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except (TypeError, ValueError):
        return None


def restore():
    """Apply the saved layout, but only for outputs that are actually connected now (a laptop undocked, a monitor unplugged ...)."""
    lay = saved()
    if not lay or not available():
        return 0
    outs = query()
    names = {o.name for o in outs}
    mine = {n: s for n, s in lay.items() if n in names}
    if not mine or not any(s.get("on") for s in mine.values()):
        return 0
    for o in outs:                                           # a connected output the layout does not know: leave it as it is
        if o.name not in mine:
            mine[o.name] = dict(on=o.enabled, mode=o.mode_key, rate=o.rate, rotation=o.rotation, x=o.x, y=o.y, primary=o.primary)
    for n, s in list(mine.items()):
        o = next((x for x in outs if x.name == n), None)
        if o is not None and s.get("on") and (not s.get("mode") or o.mode(s["mode"]) is None):
            mine[n]["mode"], mine[n]["rate"] = None, None
            m, r = o.preferred()
            if m is not None:
                mine[n]["mode"], mine[n]["rate"] = m.key, r
    ok, msg = apply_layout(mine)
    if not ok:
        print("glitterde: could not restore the display layout:", msg, file=sys.stderr)
    return 0 if ok else 1


def main(argv):
    if "--apply" in argv:
        return restore()
    if "--list" in argv:
        for o in query():
            print(o.name, o.mode_key, o.rate, o.rotation, "+%d+%d" % (o.x, o.y), "primary" if o.primary else "")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
