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


def _mini_toml(text):
    """Tiny fallback parser: [a.b] tables, key = "str" | number | bool."""
    root = {}
    cur = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            cur = root
            for part in line.strip("[]").split("."):
                cur = cur.setdefault(part, {})
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith('"'):
            v = v[1:v.find('"', 1)]
        else:
            v = v.split("#", 1)[0].strip()
            if v in ("true", "false"):
                v = v == "true"
            else:
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
        cur[k.strip()] = v
    return root


def _load(path):
    with open(path, "rb") as f:
        text = f.read().decode()
    return _toml.loads(text) if _toml else _mini_toml(text)


def _merge(base, over):
    """Deep merge: tables in `over` override those in `base`, everything else is inherited."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def hex_rgba(h, a=None):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    al = int(h[6:8], 16) / 255.0 if len(h) >= 8 else 1.0
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
        self.radius_scale = float(ap.get("radius_scale", 1.0))
        self.theme_id = os.path.basename(os.path.normpath(theme_dir))
        self.transparency = bool(ap.get("transparency", True))
        self.blur = bool(ap.get("blur", True))
        from . import config
        self.user = config.load()
        ua = self.user.get("appearance", {})
        self.transparency = bool(ua.get("transparency", self.transparency))
        self.blur = bool(ua.get("blur", self.blur))
        self.radius_scale *= float(ua.get("radius_scale", 1.0))
        self.glass_opacity = float(ua.get("glass_opacity", 1.0))
        self.blur_level = ua.get("blur_level", "normal")
        if self.blur_level == "off":
            self.blur = False
        acc = self.user.get("accent", {}).get("primary")
        if acc:
            self.pal["accent"]["primary"] = acc
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
