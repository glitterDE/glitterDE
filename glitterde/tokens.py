"""Theme tokens: loads theme.toml + palette.toml and exposes semantic roles.

Applications ask for roles ("accent.primary"), never literal colours (HIG s.28).
"""
import os

try:                                    # Python >= 3.11
    import tomllib as _toml
except ImportError:                     # pragma: no cover
    try:
        import tomli as _toml
    except ImportError:
        _toml = None


_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


class _Mini:
    """Fallback TOML reader for Python < 3.11 without tomli. Covers what themes and settings use: [a.b] tables, dotted and quoted keys,
    basic/literal strings (with \\uXXXX escapes), ints, floats, bools, (multi-line) arrays, inline tables and # comments."""

    def __init__(self, text):
        self.t, self.i = text, 0

    def ws(self, newlines=False):
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c in " \t\r" or (newlines and c == "\n"):
                self.i += 1
            elif c == "#" and newlines:
                while self.i < len(t) and t[self.i] != "\n":
                    self.i += 1
            else:
                break

    def string(self):
        t, q = self.t, self.t[self.i]
        self.i += 1
        out = []
        while self.i < len(t) and t[self.i] != q:
            c = t[self.i]
            if q == '"' and c == "\\" and self.i + 1 < len(t):
                self.i += 1
                e = t[self.i]
                if e in "uU":
                    n = 4 if e == "u" else 8
                    out.append(chr(int(t[self.i + 1:self.i + 1 + n], 16)))
                    self.i += n
                else:
                    out.append(_ESC.get(e, e))
            else:
                out.append(c)
            self.i += 1
        self.i += 1
        return "".join(out)

    def key(self):
        parts = []
        while True:
            self.ws()
            if self.t[self.i] in "\"'":
                parts.append(self.string())
            else:
                j = self.i
                while self.i < len(self.t) and (self.t[self.i].isalnum() or self.t[self.i] in "-_"):
                    self.i += 1
                parts.append(self.t[j:self.i])
            self.ws()
            if self.i < len(self.t) and self.t[self.i] == ".":
                self.i += 1
                continue
            return parts

    def value(self):
        self.ws()
        t, c = self.t, self.t[self.i]
        if c in "\"'":
            return self.string()
        if c == "[":
            self.i += 1
            out = []
            while True:
                self.ws(True)
                if t[self.i] == "]":
                    self.i += 1
                    return out
                out.append(self.value())
                self.ws(True)
                if t[self.i] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            out = {}
            while True:
                self.ws()
                if t[self.i] == "}":
                    self.i += 1
                    return out
                k = self.key()
                self.ws(); self.i += 1                                   # '='
                _put(out, k, self.value())
                self.ws()
                if t[self.i] == ",":
                    self.i += 1
        j = self.i
        while self.i < len(t) and t[self.i] not in ",]}#\n":
            self.i += 1
        raw = t[j:self.i].strip()
        if raw in ("true", "false"):
            return raw == "true"
        raw = raw.replace("_", "")
        try:
            return int(raw, 0) if raw[:2].lower() in ("0x", "0o", "0b") else int(raw)
        except ValueError:
            pass
        try:
            return float(raw.replace("inf", "Infinity")) if raw.lstrip("+-") in ("inf", "nan") else float(raw)
        except ValueError:
            return raw

    def parse(self):
        root = cur = {}
        t = self.t
        while True:
            self.ws(True)
            if self.i >= len(t):
                return root
            if t[self.i] == "[":
                self.i += 1
                self.ws()
                cur = root
                for part in self.key():
                    cur = cur.setdefault(part, {})
                self.ws()
                self.i += 1                                              # ']'
            else:
                k = self.key()
                self.ws(); self.i += 1                                   # '='
                _put(cur, k, self.value())
            while self.i < len(t) and t[self.i] != "\n":                # rest of the line (comment)
                self.i += 1


def _put(d, parts, v):
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = v


def _mini_toml(text):
    try:
        return _Mini(text).parse()
    except (IndexError, ValueError) as e:
        raise ValueError("invalid TOML: %s" % e)


def _load(path):
    with open(path, "rb") as f:
        text = f.read().decode()
    return _toml.loads(text) if _toml else _mini_toml(text)


def _num(v, default):
    """float(v), or `default` for a missing / hand-edited non-numeric setting (a typo must not take the whole shell down)."""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _merge(base, over):
    """Deep merge: tables in `over` override those in `base`, everything else is inherited."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


_BAD_COLOURS = set()


def hex_rgba(h, a=None):
    """"#rgb" / "#rrggbb" / "#rrggbbaa" -> (r, g, b, a) floats. A value that is not a colour (a typo in a hand-edited theme or settings
    file) gives neutral grey and one warning instead of raising: this runs inside the window manager's main loop, where an exception
    used to kill the WM, and the restart after the crash read the same bad value and died again."""
    s = str(h).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in s):
        if s not in _BAD_COLOURS:
            _BAD_COLOURS.add(s)
            print("glitterde: ignoring invalid colour %r (using grey)" % (h,), file=__import__("sys").stderr)
        return (0.5, 0.5, 0.5, 1.0 if a is None else a)
    r, g, b = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    al = int(s[6:8], 16) / 255.0 if len(s) >= 8 else 1.0
    return (r, g, b, al if a is None else a)


class Theme:
    def __init__(self, theme_dir):
        self.dir = theme_dir
        self.meta = _load(os.path.join(theme_dir, "theme.toml"))
        self.pal = _load(os.path.join(theme_dir, "palette.toml"))
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes", "trans-pride", "palette.toml")
        try:                                   # a partial / user-made palette inherits whatever it does not define
            if os.path.abspath(os.path.join(theme_dir, "palette.toml")) != os.path.abspath(base):
                self.pal = _merge(_load(base), self.pal)
        except Exception:
            pass
        self.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ap = self.meta.get("appearance", {})
        self.radius_scale = _num(ap.get("radius_scale"), 1.0)
        self.theme_id = os.path.basename(os.path.normpath(theme_dir))
        self.transparency = bool(ap.get("transparency", True))
        self.blur = bool(ap.get("blur", True))
        from . import config
        self.user = config.load()
        ua = self.user.get("appearance", {})
        self.transparency = bool(ua.get("transparency", self.transparency))
        self.blur = bool(ua.get("blur", self.blur))
        self.radius_scale *= _num(ua.get("radius_scale"), 1.0)
        self.glass_opacity = _num(ua.get("glass_opacity"), 1.0)
        self.blur_level = ua.get("blur_level", "normal")
        if self.blur_level == "off":
            self.blur = False
        acc = self.user.get("accent", {}).get("primary")
        if acc and isinstance(acc, str) and len(acc.lstrip("#")) in (3, 6, 8) and all(c in "0123456789abcdefABCDEF" for c in acc.lstrip("#")):
            self.pal["accent"]["primary"] = acc                # an invalid accent in settings.toml is ignored, not a crash
        if os.environ.get("GLITTERDE_REDUCED_EFFECTS"):
            self.transparency = self.blur = False

    def color(self, role, alpha=None):
        group, _, name = role.partition(".")
        return hex_rgba(self.pal[group][name], alpha)

    def radius(self, name):
        return self.pal["radius"][name] * self.radius_scale

    def rad(self, base):
        """Scale an arbitrary corner radius by the user's roundness setting."""
        return max(0, int(round(base * self.radius_scale)))

    def material(self, name):
        m = dict(self.pal["materials"][name])
        m["tint"] = hex_rgba(m["tint"])[:3]
        m["border"] = hex_rgba(m["border"])[:3]
        if not self.transparency:        # reduced-effects: map to opaque surface (THEMING s.7)
            m.update(opacity=0.96, blur=0, noise=0, sheen=0)
        else:
            m["opacity"] = max(0.05, min(0.98, m["opacity"] * self.glass_opacity))
            m["blur"] = m["blur"] * {"light": 0.6, "strong": 1.6}.get(self.blur_level, 1.0) if self.blur else 0
        return m

    def font(self, role="ui"):
        fam = self.meta.get("fonts", {}).get(role, "Inter")
        fallback = {"monospace": "DejaVu Sans Mono, monospace"}.get(
            role, "Noto Sans, Cantarell, DejaVu Sans, sans")
        return fam + ", " + fallback

    def wallpaper(self):
        p = self.meta.get("wallpaper", {}).get("default", "wallpapers/dusk-bay.png")
        user = self.user.get("wallpaper", {}).get("path")
        if user and os.path.exists(user):
            p = user
        return os.environ.get("GLITTERDE_WALLPAPER") or (p if os.path.isabs(p) else os.path.join(self.root, p))


def theme_dirs():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(root, "themes"), os.path.expanduser("~/.local/share/glitterde/themes")]


def find_themes():
    """{id: directory} for every installed theme package (theme.toml + palette.toml)."""
    out = {}
    for base in theme_dirs():
        try:
            for n in sorted(os.listdir(base)):
                d = os.path.join(base, n)
                if os.path.exists(os.path.join(d, "theme.toml")) and os.path.exists(os.path.join(d, "palette.toml")):
                    try:
                        Theme(d)                 # must load and resolve; otherwise ignore it instead of crashing apps
                    except Exception as e:
                        import sys
                        print("glitterde: ignoring broken theme %s: %s" % (d, e), file=sys.stderr)
                        continue
                    out[n] = d
        except OSError:
            pass
    return out


def active():
    """The theme chosen in SparkSettings (falls back to trans-pride)."""
    from . import config
    ids = find_themes()
    sel = config.load().get("appearance", {}).get("theme", "trans-pride")
    d = ids.get(sel) or ids.get("trans-pride")
    return Theme(d)
