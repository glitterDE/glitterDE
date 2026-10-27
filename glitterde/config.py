"""User settings (~/.config/glitterde/settings.toml): written by SparkSettings, read by shell/WM/apps."""
import os

from .tokens import _load


BUNDLED_ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share", "icons")
DEFAULT_CURSOR = "glitterde"


def _setup_xcursor_path():
    """libXcursor does not look in our checkout, so add the bundled icon dir (before the system ones)."""
    cur = os.environ.get("XCURSOR_PATH")
    if cur is None:
        cur = "~/.local/share/icons:~/.icons:/usr/share/icons:/usr/share/pixmaps"
    if BUNDLED_ICONS not in cur:
        os.environ["XCURSOR_PATH"] = BUNDLED_ICONS + ":" + cur


_setup_xcursor_path()


def _icon_dirs():
    dirs = [BUNDLED_ICONS, os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons")]
    dirs += [os.path.join(d, "icons") for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return dirs


def cursor_theme():
    """Configured cursor theme, else the bundled/installed glitterde theme (when present), else None (system default)."""
    t = load().get("cursor", {}).get("theme")
    if t:
        return str(t)
    return DEFAULT_CURSOR if any(os.path.isdir(os.path.join(d, DEFAULT_CURSOR, "cursors")) for d in _icon_dirs()) else None


def config_dir():
    d = os.environ.get("GLITTERDE_CONFIG_HOME") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "glitterde")
    return d


def path(name="settings.toml"):
    return os.path.join(config_dir(), name)


def load(name="settings.toml"):
    try:
        return _load(path(name))
    except (OSError, ValueError):
        return {}
    except Exception:                      # corrupt file must never take the session down
        return {}


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(data, name="settings.toml"):
    os.makedirs(config_dir(), exist_ok=True)
    out = []
    for sec, vals in data.items():
        out.append("[%s]" % sec)
        out += ["%s = %s" % (k, _fmt(v)) for k, v in vals.items()]
        out.append("")
    tmp = path(name) + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(out))
    os.replace(tmp, path(name))            # atomic: watchers never see a half-written file


def set(section, key, value, name="settings.toml"):
    d = load(name)
    d.setdefault(section, {})[key] = value
    save(d, name)
